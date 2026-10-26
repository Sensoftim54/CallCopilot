"""Models that can be picked in Settings, and the name the assistant answers to by voice for each of them."""
import re

# backend -> [(config value, label)]
CHOICES = {
    "codex": [("gpt-6-luna", "GPT-6 Luna")],
    "claude": [("sonnet", "Claude Sonnet"), ("opus", "Claude Opus"), ("haiku", "Claude Haiku")],
}

# model family -> (English name, Russian name, word forms Whisper may write for it)
NAMES = {
    "luna": ("Luna", "Луна", ("luna", "луна", "луну", "луне", "луны", "луной")),
    "sonnet": ("Sonnet", "Соннет", ("sonnet", "sonet", "соннет", "сонет", "соннета", "сонета", "соннету", "сонету",
                                    "соннетом", "сонетом")),
    "opus": ("Opus", "Опус", ("opus", "опус", "опуса", "опусу", "опусом")),
    "haiku": ("Haiku", "Хайку", ("haiku", "хайку", "хаику")),
}
DEFAULT_FAMILY = {"codex": "luna", "claude": "sonnet"}


def backend_of(cfg):
    return "codex" if cfg.get("backend", "codex").lower() == "codex" else "claude"


def model_of(cfg):
    return cfg.get("codex_model" if backend_of(cfg) == "codex" else "claude_model") or ""


def family(cfg):
    m = model_of(cfg).lower()
    return next((k for k in NAMES if k in m), DEFAULT_FAMILY[backend_of(cfg)])


def wake_name(cfg, lang):
    en, ru, _ = NAMES[family(cfg)]
    return ru if lang == "ru" else en


def wake_words(cfg):
    """Words that turn your phrase into a question to the model: the model's name plus extra_wake_words."""
    return set(NAMES[family(cfg)][2]) | {w.lower() for w in cfg.get("extra_wake_words", [])}


_LAT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                 "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _latin(word):
    return "".join(_LAT.get(ch, ch) for ch in word.lower())


def _close(a, b):
    """Similarity of two words in Latin letters, 0..1 (Сонат ≈ sonnet, Sonneb ≈ sonnet)."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, _latin(a), _latin(b)).ratio()


ALT_SPELLINGS = {"sonnet": ("сонет",)}  # the usual Russian spelling of the word, with one «н»


def wake_bases(cfg):
    """The model's name itself (no case forms) — what a misheard word is compared with."""
    fam = family(cfg)
    en, ru, _ = NAMES[fam]
    return {en.lower(), ru.lower(), *ALT_SPELLINGS.get(fam, ())} | {w.lower() for w in cfg.get("extra_wake_words", [])}


def is_wake(text, words, bases, fuzzy=0.75):
    """Is the phrase addressed to the assistant? An exact wake word (any case form) anywhere, or a word that
    sounds like the name itself among the first three — Whisper often misspells a name it does not know
    (Сонат, Sonneb, Сонъть). Only the base names are compared, so «монета» is not taken for «сонета»."""
    tokens = re.findall(r"\w+", text.lower())
    if words.intersection(tokens):
        return True
    targets = {_latin(w) for w in bases}
    return any(len(tok) >= 4 and max(_close(tok, w) for w in targets) >= fuzzy for tok in tokens[:3])
