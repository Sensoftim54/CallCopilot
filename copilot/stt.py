"""Local speech recognition (faster-whisper on CPU). No external APIs."""
import re
import threading

from faster_whisper import WhisperModel

from . import i18n
from .i18n import t

# typical Whisper hallucinations on silence / noise
_JUNK = re.compile(
    r"(субтитр|продолжение следует|спасибо за просмотр|подписывайтесь|редактор субтитров|"
    r"thanks for watching|subscribe|amara\.org|dimatorzok)",
    re.I,
)


class STTWorker(threading.Thread):
    def __init__(self, in_q, cfg, on_text, on_status):
        super().__init__(daemon=True)
        self.in_q = in_q
        self.cfg = cfg
        self.on_text = on_text
        self.on_status = on_status
        self.busy_source = None

    def _language(self, model, audio):
        """The language to transcribe this phrase in. "auto" picks between the conversation languages only
        (Russian / English): free auto-detection takes short Russian phrases for Bulgarian or Ukrainian."""
        lang = self.cfg.get("language") or i18n.LANG  # read every time: Settings can change it; empty — UI language
        if lang != "auto":
            return lang
        try:
            _, _, probs = model.detect_language(audio)
            allowed = self.cfg.get("auto_languages", ["ru", "en"])
            return max((p, code) for code, p in probs if code in allowed)[1]
        except Exception:
            return None

    def run(self):
        name = self.cfg.get("whisper_model", "small")
        self.on_status(t("status_loading", name=name))
        model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=self.cfg.get("cpu_threads", 0))
        self.on_status(t("status_listening"))
        hint = self.cfg.get("stt_hint") or None
        while True:
            _, _, source, audio = self.in_q.get()
            self.busy_source = source  # the echo filter waits until the other side's phrase is transcribed
            try:
                segs, _ = model.transcribe(
                    audio,
                    language=self._language(model, audio),
                    beam_size=1,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    initial_prompt=hint,  # no hotwords: Whisper takes them as already said and drops the name
                )
                text = " ".join(s.text.strip() for s in segs if s.no_speech_prob < 0.6).strip()
            except Exception as e:  # one bad phrase must not kill the thread
                self.on_status(t("stt_error", e=e))
                text = ""
            if len(text) >= 2 and not _JUNK.search(text):
                self.on_text(source, text)
            self.busy_source = None
