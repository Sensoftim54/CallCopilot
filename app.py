"""Call Copilot: listens to a call, transcribes speech locally and gives hints through your
Claude / ChatGPT (Codex) subscription.

Run:  .venv\\Scripts\\python app.py            (normal)
      .venv\\Scripts\\python app.py --devices  (list audio devices)
"""
import bisect
import ctypes
import itertools
import json
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QApplication

from copilot import i18n, models
from copilot.echo import EchoFilter
from copilot.i18n import t
from copilot.llm import WORKDIR, connection_status, make_backend, start_connect
from copilot.prompts import build_system, build_user

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
CONTEXT_PATH = os.path.join(ROOT, "context.md")  # for the current call, wiped by Clear
ABOUT_PATH = os.path.join(ROOT, "about.md")  # about the user, permanent
LOG_DIR = os.path.join(ROOT, "logs")

DEFAULT_CONFIG = {
    "backend": "codex",
    "claude_model": "sonnet",
    "claude_effort": "low",
    "codex_model": "gpt-6-luna",
    "codex_effort": "low",
    "codex_service_tier": "fast",
    "codex_ignore_user_config": True,
    "ui_language": "",  # "en" / "ru"; empty — follow the Windows display language
    "language": "",  # speech language for Whisper: "en", "ru", ... ; "auto" — detect; empty — same as the UI
    "whisper_model": "small",
    "stt_hint": "",
    "loopback_device": "",
    "mic_device": "",
    "capture_mic": True,
    "auto_answer": True,
    "debounce_ms": 1200,
    "min_words": 4,
    "extra_wake_words": [],  # the model's own name (Luna / Sonnet / …) always works; add more words here
    "echo_filter": True,
    "echo_similarity": 0.7,
    "echo_hold_ms": 8000,
    "context_lines": 40,
    "silence_ms": 700,
    "vad_threshold": 0.006,
    "always_on_top": True,
    "window_size": [600, 780],
    "font_size": 13,
    "hotkeys": {
        "answer": "ctrl+alt+enter",
        "screen": "ctrl+alt+s",
        "summary": "ctrl+alt+r",
        "focus": "ctrl+alt+space",
        "mute": "ctrl+alt+m",
    },
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        # hotkeys added in updates are merged into an older config.json instead of being lost
        user["hotkeys"] = {**DEFAULT_CONFIG["hotkeys"], **user.get("hotkeys", {})}
        user.pop("wake_words", None)  # old fixed list; the wake word now follows the chosen model
        cfg.update(user)
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def load_context():
    if not os.path.exists(CONTEXT_PATH):
        return ""
    with open(CONTEXT_PATH, encoding="utf-8") as f:
        return f.read()


def save_context(text):
    with open(CONTEXT_PATH, "w", encoding="utf-8") as f:
        f.write(text)


def load_about():
    if not os.path.exists(ABOUT_PATH):
        return ""
    with open(ABOUT_PATH, encoding="utf-8") as f:
        return f.read()


def save_about(text):
    with open(ABOUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)


def migrate_about():
    """Before About me existed, people described themselves in Context. On the first launch with
    About me that text moves there, so that Clear does not erase it."""
    if not os.path.exists(ABOUT_PATH) and load_context().strip():
        save_about(load_context())
        save_context("")


class Bus(QObject):
    text = pyqtSignal(str, str)
    status = pyqtSignal(str)
    delta = pyqtSignal(int, str)
    done = pyqtSignal(int, str)
    error = pyqtSignal(int, str)
    hotkey = pyqtSignal(str)
    call = pyqtSignal(object)  # a function to run on the UI thread


class SessionLog:
    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.path = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".md")

    def write(self, s):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(s + "\n")


class Controller:
    DASHES = {"—", "-", "–", ""}

    def __init__(self, cfg, win, bus):
        self.cfg, self.win, self.bus = cfg, win, bus
        self.backend = make_backend(cfg)
        self.lines = []
        self.req = 0
        self.busy_mode = None  # which request is running now
        self.msg_id = None  # its message in the feed
        self.question = ""  # the typed / spoken question it answers
        self.muted = False
        self.conn_err = ""  # "<subscription> is not connected" for the footer
        self.echo = EchoFilter(cfg.get("echo_similarity", 0.7), keep=self._is_wake)
        self.held = {}  # my lines held back for the echo check: [ts, text, held since, ticks]
        self._held_ids = itertools.count()
        self.hold_timer = QTimer(interval=250)
        self.hold_timer.timeout.connect(self._check_held)
        self.stt = None
        self.deferred_auto = False
        self.pending_words = 0
        self.audio = None
        self.audio_q = queue.PriorityQueue()
        self.log = SessionLog()
        self.auto = cfg["auto_answer"]

        self.debounce = QTimer(singleShot=True, interval=cfg["debounce_ms"])
        self.debounce.timeout.connect(lambda: self.trigger("auto"))
        # voice question: "<model name>, …" — wait until you finish and answer that phrase
        self.voice_buf = None
        self.voice_timer = QTimer(singleShot=True, interval=cfg["debounce_ms"])
        self.voice_timer.timeout.connect(self._voice_done)
        self.meter = QTimer(interval=150)
        self.meter.timeout.connect(self._levels)
        self.meter.start()

        bus.text.connect(self.on_text)
        bus.status.connect(lambda m: win.set_status(msg=m))
        bus.delta.connect(self.on_delta)
        bus.done.connect(self.on_done)
        bus.error.connect(self.on_error)
        bus.hotkey.connect(self.on_action)
        win.action.connect(self.on_action)
        win.ask.connect(lambda q: self.trigger("manual", question=q))
        win.device_changed.connect(self.on_device)
        win.context_changed.connect(save_context)
        win.about_changed.connect(save_about)
        win.backend_changed.connect(self.set_backend)
        win.connect_requested.connect(self.connect_backend)
        win.ui_lang_changed.connect(self.set_ui_language)
        win.speech_lang_changed.connect(self.set_speech_language)
        bus.call.connect(lambda fn: fn())
        win.set_context(load_context())
        win.set_about(load_about())
        self._apply_backend()
        win.settings.set_langs(i18n.LANG, cfg.get("language") or i18n.LANG)
        win.set_auto(self.auto)
        win.set_on_top(cfg["always_on_top"])
        self._check(models.backend_of(cfg), self._show_connection)

    def _bg(self, fn, then):
        """Run fn() in a thread and then(result) back on the UI thread."""
        threading.Thread(target=lambda: (lambda r: self.bus.call.emit(lambda: then(r)))(fn()), daemon=True).start()

    # --- model: ChatGPT (Codex) or Claude ---
    NAMES = {"codex": "ChatGPT", "claude": "Claude"}

    def _apply_backend(self):
        """Make the backend from cfg; the wake word, echo filter and UI follow the chosen model."""
        self.backend = make_backend(self.cfg)
        self.wake = models.wake_words(self.cfg)
        self.wake_bases = models.wake_bases(self.cfg)
        backend, model = models.backend_of(self.cfg), models.model_of(self.cfg)
        label = dict(models.CHOICES[backend]).get(model, model or t("model_default"))
        if backend == "codex":
            label = "Codex · " + label + (" · ⚡fast" if self.cfg.get("codex_service_tier") == "fast" else "")
        self.win.set_backend_state(backend, model, models.wake_name(self.cfg, i18n.LANG), label, "")
        return label

    def _check(self, backend, then):
        """Is this subscription installed and signed in? — then(state) on the UI thread."""
        self.win.settings.set_connection("checking")
        self._bg(lambda: connection_status(backend, self.cfg), then)

    def _show_connection(self, state):
        """Connection state of the current subscription: Settings tab and a hint in the footer."""
        self.win.settings.set_connection(state)
        name = self.NAMES[models.backend_of(self.cfg)]
        self.conn_err = "" if state == "ok" else t("not_connected", name=name)
        self._update_err()

    def _update_err(self):
        audio = "; ".join(self.audio.errors) if self.audio else ""
        self.win.set_status(err="; ".join(x for x in (self.conn_err, audio) if x))

    def set_backend(self, backend, model):
        """Settings tab: switch the subscription / model. A subscription that is not connected yet is offered
        to be connected first; until then — or if the user declines — the current one keeps working."""
        if backend == models.backend_of(self.cfg):  # only the model within the same subscription
            self._switch(backend, model)
            return

        def checked(state):
            if state == "ok":
                self._switch(backend, model)
                self._show_connection("ok")
                return
            name = self.NAMES[backend]
            if self.win.confirm(t("connect_q_title", name=name), t("connect_q_text", name=name),
                                t("btn_connect"), t("btn_cancel")):
                self.connect_backend(backend, switch_model=model)
            else:
                self._revert_settings()

        self._check(backend, checked)

    def _revert_settings(self):
        """Put the Settings tab back on the subscription that is actually in use."""
        self._apply_backend()
        self._check(models.backend_of(self.cfg), self._show_connection)

    def _switch(self, backend, model):
        if self.busy_mode:  # the old model's answer is no longer wanted
            self._abort()
            self.busy_mode = None
            self.win.set_status(busy=False)
        self.cfg["backend"] = backend
        self.cfg["codex_model" if backend == "codex" else "claude_model"] = model
        save_config(self.cfg)
        self.voice_timer.stop()
        self.voice_buf = None
        self.log.write("\n" + t("log_backend", label=self._apply_backend()) + "\n")

    def connect_backend(self, backend, switch_model=None):
        """Open the connection window (installs the CLI if needed, then the account sign-in) and wait for it.
        switch_model — switch to this subscription once it is connected."""
        proc = start_connect(backend, i18n.LANG)
        if proc is None:
            self.win.settings.warn.setText("⚠ " + t("connect_script_missing"))
            self._revert_settings()
            return
        self.win.settings.warn.setText("")
        self.win.settings.set_connection("connecting")

        def finished(_rc):
            def checked(state):
                if state == "ok":
                    if switch_model is not None:
                        self._switch(backend, switch_model)
                    self._show_connection("ok")
                else:
                    self.win.settings.warn.setText("⚠ " + t("connect_failed", name=self.NAMES[backend]))
                    self._revert_settings()
            self._check(backend, checked)

        self._bg(proc.wait, finished)

    # --- language ---
    def set_ui_language(self, code):
        self.cfg["ui_language"] = code
        save_config(self.cfg)
        if code != i18n.LANG and self.win.confirm(t("restart_q_title"), t("restart_q_text"),
                                                   t("btn_restart"), t("btn_later")):
            self.restart()

    def set_speech_language(self, code):
        self.cfg["language"] = code  # the speech recognizer reads it for every phrase
        save_config(self.cfg)

    def restart(self):
        """Start a fresh copy of the app and close this one (used to apply the interface language)."""
        self.win.flush_context()
        self.backend.cancel()
        if self.audio:
            self.audio.close()
            self.audio = None
        QProcess.startDetached(sys.executable, [os.path.abspath(sys.argv[0])] + sys.argv[1:], ROOT)
        QApplication.quit()

    # --- audio devices ---
    def start_audio(self):
        from copilot.audio import AudioManager
        if self.audio:
            self.audio.close()
            self.audio = None
        self.audio = AudioManager(self.cfg, self.audio_q)
        self.audio.set_muted(self.muted)  # switching a device must not lift Mute
        names = self.audio.names()
        self.log.write("\n" + t("log_devices", them=names.get("them", "-"), me=names.get("me", "-")) + "\n")
        self.win.set_status(levels=self.audio.levels())
        self._update_err()

    def refresh_devices(self):
        from copilot.audio import enumerate_devices
        from copilot.ui import MIC_OFF
        try:
            loops, mics, def_loop, def_mic = enumerate_devices()
        except Exception as e:
            self.win.set_status(msg=t("devices_failed", e=e))
            return
        cur_mic = self.cfg["mic_device"] if self.cfg["capture_mic"] else MIC_OFF
        self.win.set_devices(loops, mics, def_loop, def_mic, self.cfg["loopback_device"], cur_mic)

    def on_device(self, kind, name):
        from copilot.ui import MIC_OFF
        if kind == "them":
            self.cfg["loopback_device"] = name
        else:
            self.cfg["capture_mic"] = name != MIC_OFF
            self.cfg["mic_device"] = "" if name == MIC_OFF else name
        save_config(self.cfg)
        self.start_audio()

    def rescan(self):
        if self.audio:  # PortAudio only sees new devices after a full restart
            self.audio.close()
            self.audio = None
        self.refresh_devices()
        self.start_audio()

    # --- transcript ---
    def on_text(self, source, text):
        ts = datetime.now().strftime("%H:%M:%S")
        if not self.cfg.get("echo_filter", True):
            return self._commit(ts, source, text)
        if source == "them":
            self.echo.add_them(text)
            self._commit(ts, source, text)
            for key, item in list(self.held.items()):  # a held "my" line turned out to be an echo
                if self.echo.check(item[1]):
                    del self.held[key]
                    self._drop_echo(item[1])
            return
        if self.echo.check(text):
            return self._drop_echo(text)
        # The other side has no unfinished or untranscribed phrase — nothing to compare with, show now.
        # "Luna, …" is never an echo — also show now, so a voice question does not wait.
        if not self._them_pending() or self._is_wake(text):
            return self._commit(ts, source, text)
        self.held[next(self._held_ids)] = [ts, text, time.time(), 0]
        self.hold_timer.start()

    def _them_pending(self):
        """The other side's phrase is still being spoken, waiting for transcription or being transcribed."""
        return bool(self.audio and self.audio.speaking("them")
                    or any(item[2] == "them" for item in list(self.audio_q.queue))
                    or self.stt and self.stt.busy_source == "them")

    def _check_held(self):
        # held lines are released once the other side's phrase is transcribed and they were not an echo
        # (two ticks in a row, so the signal with the transcribed text has arrived), but no longer than echo_hold_ms
        pending = self._them_pending()
        for key, item in list(self.held.items()):
            item[3] = 0 if pending else item[3] + 1
            if item[3] >= 2 or time.time() - item[2] > self.cfg.get("echo_hold_ms", 8000) / 1000:
                del self.held[key]
                self._commit(item[0], "me", item[1])
        if not self.held:
            self.hold_timer.stop()

    def _drop_echo(self, text):
        self.log.write(t("log_echo", text=text))

    def _commit(self, ts, source, text):
        bisect.insort(self.lines, (ts, source, text), key=lambda x: x[0])  # a held line goes back to its time
        self.win.add_line(ts, source, text)
        self.log.write(f"[{ts}] {t('who_them') if source == 'them' else t('who_me')}: {text}")
        if source == "them":
            self.pending_words += len(text.split())
            if self.auto:
                self.debounce.start()
        elif self.voice_buf is not None:  # continuation after "Luna, …" (Whisper splits on pauses)
            self.voice_buf.append(text)
            self.voice_timer.start()
        elif self._is_wake(text):
            self.voice_buf = [text]
            self.voice_timer.start()

    def _is_wake(self, text):
        """Addressed to the assistant by its name — exact or misheard (Сонат ≈ Sonnet)."""
        return models.is_wake(text, self.wake, self.wake_bases)

    def _voice_done(self):
        question, self.voice_buf = " ".join(self.voice_buf or []), None
        if question:
            self.trigger("voice", question=question)

    def transcript(self):
        n = self.cfg["context_lines"]
        return "\n".join(f"[{ts}] {'Them' if s == 'them' else 'Me'}: {txt}" for ts, s, txt in self.lines[-n:])

    # --- model requests ---
    MODES = {  # feed message kind; what to show while the model thinks (None — the message appears with the answer)
        "auto": ("hint", None),
        "force": ("hint", "note_force"),
        "manual": ("answer", "note_manual"),
        "voice": ("answer", "note_voice"),
        "screen": ("screen", "note_screen"),
        "summary": ("summary", "note_summary"),
    }

    def trigger(self, mode, question="", image=None):
        if mode == "auto":
            if self.pending_words < self.cfg["min_words"]:
                return
            if self.busy_mode not in (None, "auto"):  # do not interrupt a button request — run afterwards
                self.deferred_auto = True
                return
        elif mode == self.busy_mode and mode not in ("manual", "voice"):
            return  # the same button pressed again while it is still running
        if mode in ("auto", "force"):  # both answer the current moment — a pending auto hint is not needed
            self.pending_words = 0
            self.deferred_auto = False
            self.debounce.stop()
        self._abort()
        rid = self.req
        self.busy_mode = mode
        self.question = question if mode in ("manual", "voice") else ""
        self.win.flush_context()  # edits from the last fraction of a second must get into the request too
        system = build_system(load_about(), load_context(), i18n.LANG)  # re-read: can be edited on the fly
        user = build_user(self.transcript(), mode, question)
        if mode in ("manual", "voice"):
            self.log.write("\n" + t("log_question_voice" if mode == "voice" else "log_question", q=question))
        kind, note_key = self.MODES[mode]
        note = None
        if self.question:
            note = f"{self._head()}{t(note_key)}"
        elif note_key:
            note = f"{t(note_key)} {t('usual_time')}"
        self.msg_id = self.win.start_message(kind, note, jump=True, pending=True) if note else None
        self.win.set_status(busy=True)
        threading.Thread(target=self._run, args=(rid, system, user, image), daemon=True).start()

    def _abort(self):
        """Stop the current request; mark its "⏳ …" in the feed as interrupted."""
        self.backend.cancel()
        self.req += 1  # answers of the old request will be ignored
        if self.busy_mode and self.msg_id is not None:
            self.win.update_message(self.msg_id, text=self._head() + t("interrupted"))
        self.msg_id = None
        self.question = ""

    def _head(self):
        return f"**{t('question')}:** {self.question}\n\n---\n\n" if self.question else ""

    def _show(self, text):
        kind = self.MODES[self.busy_mode or "auto"][0]
        if self.msg_id is None:
            self.msg_id = self.win.start_message(kind, text)
        else:
            self.win.update_message(self.msg_id, kind, text)

    def _finish(self):
        self.busy_mode = None
        self.msg_id = None
        self.win.set_status(busy=False)
        if self.deferred_auto:  # the other side said something while a button request was running
            self.deferred_auto = False
            self.trigger("auto")

    def _run(self, rid, system, user, image):
        try:
            text = self.backend.run(system, user, lambda x: self.bus.delta.emit(rid, x), image=image)
            self.bus.done.emit(rid, text)
        except Exception as e:
            self.bus.error.emit(rid, str(e))

    def on_delta(self, rid, text):
        if rid == self.req and text.strip() not in self.DASHES:
            self._show(self._head() + text)

    def on_done(self, rid, text):
        if rid != self.req:
            return
        mode = self.busy_mode or "auto"
        if text.strip() in self.DASHES:
            if mode == "auto":  # nothing new to suggest — add nothing to the feed
                self._finish()
                return
            text = t("nothing_to_add")
        self._show(self._head() + text)
        title = t(f"title_{self.MODES[mode][0]}").capitalize()
        self.log.write(f"\n**{title} {datetime.now():%H:%M:%S}:**\n{text}\n")
        self._finish()

    def on_error(self, rid, err):
        if rid == self.req:
            self._show(self._head() + f"**{t('model_error')}:**\n\n```\n{err}\n```")
            self.log.write("\n" + t("log_model_error", e=err) + "\n")
            self._finish()

    def reset(self):
        """Clear button: start the conversation from scratch. About me stays, call Context is wiped."""
        self.win.flush_context()  # unsaved About me edits are kept
        save_context("")
        self.win.set_context("")
        self._abort()
        self.busy_mode = None
        self.deferred_auto = False
        self.pending_words = 0
        self.debounce.stop()
        self.voice_timer.stop()
        self.voice_buf = None
        self.lines.clear()
        self.held.clear()
        self.echo.clear()
        self.win.clear()
        self.win.set_status(busy=False)
        self.log = SessionLog()
        self.log.write(t("log_call", dt=f"{datetime.now():%Y-%m-%d %H:%M}") + "\n")

    # --- buttons and hotkeys ---
    def on_action(self, act):
        if act == "auto":
            self.auto = not self.auto
            self.win.set_auto(self.auto)
        elif act == "top":
            self.win.set_on_top(self.win.btn_top.isChecked())  # the button has already toggled on click
        elif act == "answer":
            self.trigger("force")
        elif act == "summary":
            self.trigger("summary")
        elif act == "screen" and self.busy_mode != "screen":
            self.screenshot()
        elif act == "rescan":
            self.rescan()
        elif act == "clear":
            self.reset()
        elif act == "mute":
            self.set_muted(not self.muted)
        elif act == "focus":
            self.win.showNormal()
            self.win.activateWindow()
            self.win.focus_input()

    def set_muted(self, on):
        self.muted = on
        if self.audio:
            self.audio.set_muted(on)
        if on:  # an unfinished voice question is dropped too
            self.voice_timer.stop()
            self.voice_buf = None
        self.win.set_muted(on)
        self.log.write("\n" + t("log_muted" if on else "log_unmuted", time=f"{datetime.now():%H:%M:%S}") + "\n")

    def screenshot(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.win.setWindowOpacity(0.0)  # hide our own window from the shot without moving or resizing it

        def grab():
            path = os.path.join(WORKDIR, f"shot_{int(time.time())}.png")
            screen.grabWindow(0).save(path, "PNG")
            self.win.setWindowOpacity(1.0)
            self.trigger("screen", image=path)

        QTimer.singleShot(200, grab)

    def _levels(self):
        if self.audio:
            self.win.set_status(levels=self.audio.levels())


def register_hotkeys(cfg, bus):
    try:
        import keyboard
    except ImportError:
        return
    for act, combo in cfg.get("hotkeys", {}).items():
        if combo:
            keyboard.add_hotkey(combo, lambda a=act: bus.hotkey.emit(a))


def main():
    if "--devices" in sys.argv:
        from copilot.audio import list_devices
        list_devices()
        return

    if sys.stderr is None:  # started via pythonw / a shortcut — errors go to a file
        os.makedirs(LOG_DIR, exist_ok=True)
        sys.stdout = sys.stderr = open(os.path.join(LOG_DIR, "app.log"), "a", encoding="utf-8", buffering=1)
    # PyQt6 aborts the whole app on an exception in a slot unless sys.excepthook is replaced: log it and go on
    sys.excepthook = lambda *exc: traceback.print_exception(*exc, file=sys.stderr)
    try:  # own icon and taskbar group instead of the Python one
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CallCopilot.App")  # = ui.APP_ID
    except Exception:
        pass

    cfg = load_config()
    i18n.set_language(cfg.get("ui_language"))
    migrate_about()
    app = QApplication(sys.argv)
    from copilot.icon import make_icon
    app.setWindowIcon(make_icon())
    bus = Bus()
    from copilot.ui import MainWindow
    win = MainWindow(cfg)
    ctl = Controller(cfg, win, bus)
    win.show()
    from copilot.ui import set_taskbar_identity  # our icon on the taskbar and when pinned, not a generic one
    set_taskbar_identity(win, os.path.join(ROOT, "assets", "icon.ico"),
                         f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"')

    ctl.log.write(t("log_call", dt=f"{datetime.now():%Y-%m-%d %H:%M}") + "\n")
    ctl.refresh_devices()
    try:
        ctl.start_audio()
    except Exception as e:
        bus.status.emit(t("audio_failed", e=e))

    from copilot.stt import STTWorker
    ctl.stt = STTWorker(ctl.audio_q, cfg, bus.text.emit, bus.status.emit)
    ctl.stt.start()
    register_hotkeys(cfg, bus)

    code = app.exec()
    win.flush_context()
    ctl.backend.cancel()
    if ctl.audio:
        ctl.audio.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
