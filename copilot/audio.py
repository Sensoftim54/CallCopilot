"""Audio capture: system audio (WASAPI loopback) = the other side, microphone = me.

Each stream is cut into phrases by a simple energy-based VAD and queued for transcription.
"""
import collections
import itertools
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio

from .i18n import t

TARGET_SR = 16000
FRAME = TARGET_SR * 30 // 1000  # 30 ms
FRAME_MS = 30

_seq = itertools.count()


def to_16k(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == TARGET_SR:
        return x
    if sr % TARGET_SR == 0:  # 48k/96k: block averaging = cheap low-pass + decimation
        k = sr // TARGET_SR
        n = len(x) // k * k
        return x[:n].reshape(-1, k).mean(axis=1).astype(np.float32)
    n = int(round(len(x) * TARGET_SR / sr))
    return np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x).astype(np.float32)


class Segmenter:
    def __init__(self, source, out_q, cfg):
        self.source = source
        self.out_q = out_q
        self.silence_ms = cfg.get("silence_ms", 700)
        self.max_ms = cfg.get("max_segment_s", 20) * 1000
        self.min_speech_ms = cfg.get("min_speech_ms", 400)
        self.thr_min = cfg.get("vad_threshold", 0.006)
        self.priority = 0 if source == "them" else 1
        self.noise = 0.002
        self.pre = collections.deque(maxlen=10)  # 300 ms before speech starts
        self.pending = np.zeros(0, np.float32)
        self.buf = []
        self.active = False
        self.speech_ms = 0
        self.silent_ms = 0
        self.level = 0.0

    def feed(self, x):
        self.pending = np.concatenate([self.pending, x])
        while len(self.pending) >= FRAME:
            f, self.pending = self.pending[:FRAME], self.pending[FRAME:]
            self._frame(f)

    def _frame(self, f):
        rms = float(np.sqrt(np.mean(f * f)) + 1e-9)
        self.level = rms
        speech = rms > max(self.thr_min, self.noise * 3)
        if not self.active:
            if not speech:
                self.noise = 0.95 * self.noise + 0.05 * rms
            self.pre.append(f)
            if speech:
                self.active = True
                self.buf = list(self.pre)
                self.pre.clear()
                self.speech_ms, self.silent_ms = FRAME_MS, 0
            return
        self.buf.append(f)
        if speech:
            self.speech_ms += FRAME_MS
            self.silent_ms = 0
        else:
            self.silent_ms += FRAME_MS
        if self.silent_ms >= self.silence_ms or len(self.buf) * FRAME_MS >= self.max_ms:
            self.flush()

    def flush(self):
        if self.active and self.speech_ms >= self.min_speech_ms:
            self.out_q.put((self.priority, next(_seq), self.source, np.concatenate(self.buf)))
        self.buf = []
        self.active = False
        self.speech_ms = self.silent_ms = 0


class Capture:
    """One PyAudio input stream -> Segmenter."""

    def __init__(self, pa, device, source, out_q, cfg, channels=None):
        self.source = source
        self.name = device["name"]
        self.rate = int(device["defaultSampleRate"])
        self.ch = channels or int(device["maxInputChannels"])
        self.seg = Segmenter(source, out_q, cfg)
        self.lock = threading.Lock()
        self.last = time.time()
        self.muted = False
        self.stream = pa.open(
            format=pyaudio.paInt16,
            channels=self.ch,
            rate=self.rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=int(self.rate * 0.05),
            stream_callback=self._cb,
        )

    def _cb(self, data, frames, time_info, status):
        if self.muted:  # muted: audio is dropped right here and goes nowhere
            return (None, pyaudio.paContinue)
        x = np.frombuffer(data, np.int16).astype(np.float32) / 32768.0
        x = x.reshape(-1, self.ch).mean(axis=1)
        with self.lock:
            self.seg.feed(to_16k(x, self.rate))
            self.last = time.time()
        return (None, pyaudio.paContinue)

    def set_muted(self, on):
        with self.lock:
            self.muted = on
            if on:  # an unfinished phrase is dropped too, not sent for transcription
                self.seg.buf = []
                self.seg.active = False
                self.seg.speech_ms = self.seg.silent_ms = 0
                self.seg.pending = np.zeros(0, np.float32)
                self.seg.pre.clear()
                self.seg.level = 0.0

    def tick(self):
        # WASAPI loopback sends no packets while nothing is playing — close the phrase on a timeout
        with self.lock:
            if self.seg.active and time.time() - self.last > self.seg.silence_ms / 1000:
                self.seg.flush()
            if time.time() - self.last > 0.3:
                self.seg.level = 0.0

    def close(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except Exception:
            pass


def _find(devices, name):
    for d in devices:  # exact name first, then a substring
        if d["name"] == name:
            return d
    for d in devices:
        if name.lower() in d["name"].lower():
            return d
    raise RuntimeError(t("device_not_found", name=name))


def _wasapi_inputs(pa):
    """WASAPI microphones — full names, no MME/DirectSound duplicates."""
    api = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["hostApi"] == api and d["maxInputChannels"] > 0 and not d.get("isLoopbackDevice"):
            yield d


def _default_mic(pa):
    i = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["defaultInputDevice"]
    if i < 0:
        raise RuntimeError(t("no_default_mic"))
    return pa.get_device_info_by_index(i)


def enumerate_devices():
    """-> (loopback names, microphone names, default loopback, default microphone) as set in Windows."""
    pa = pyaudio.PyAudio()
    try:
        loops = [d["name"] for d in pa.get_loopback_device_info_generator()]
        mics = [d["name"] for d in _wasapi_inputs(pa)]
        try:
            def_loop = pa.get_default_wasapi_loopback()["name"]
        except Exception:
            def_loop = ""
        try:
            def_mic = _default_mic(pa)["name"]
        except Exception:
            def_mic = ""
        return loops, mics, def_loop, def_mic
    finally:
        pa.terminate()


def list_devices():
    loops, mics, def_loop, def_mic = enumerate_devices()
    print("Other side audio (loopback):")
    for n in loops:
        print(("  * " if n == def_loop else "    ") + n)
    print("Microphones:")
    for n in mics:
        print(("  * " if n == def_mic else "    ") + n)
    print("(* — Windows default)")


class AudioManager:
    def __init__(self, cfg, out_q):
        self.pa = pyaudio.PyAudio()
        self.captures = []
        self._stop = threading.Event()
        self.errors = []  # one failing device must not take the other one down

        try:
            loops = list(self.pa.get_loopback_device_info_generator())
            lb = _find(loops, cfg["loopback_device"]) if cfg.get("loopback_device") else self.pa.get_default_wasapi_loopback()
            self.captures.append(Capture(self.pa, lb, "them", out_q, cfg))
        except Exception as e:
            self.errors.append(t("err_them", e=e))

        if cfg.get("capture_mic", True):
            try:
                mic = _find(list(_wasapi_inputs(self.pa)), cfg["mic_device"]) if cfg.get("mic_device") else _default_mic(self.pa)
                self.captures.append(Capture(self.pa, mic, "me", out_q, cfg))
            except Exception as e:
                self.errors.append(t("err_mic", e=e))

        threading.Thread(target=self._ticker, daemon=True).start()

    def _ticker(self):
        while not self._stop.is_set():
            for c in self.captures:
                c.tick()
            time.sleep(0.15)

    def set_muted(self, on):
        for c in self.captures:
            c.set_muted(on)

    def speaking(self, source):
        """A phrase is in progress in this channel and has not gone to transcription yet."""
        return any(c.seg.active for c in self.captures if c.source == source)

    def levels(self):
        return {c.source: c.seg.level for c in self.captures}

    def names(self):
        return {c.source: c.name for c in self.captures}

    def close(self):
        self._stop.set()
        for c in self.captures:
            c.close()
        self.pa.terminate()
