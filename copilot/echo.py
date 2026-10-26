"""Echo filter: the microphone may pick up the other side from headphones/speakers, and their words end up
as "Me". Such a "my" line is recognised by almost all of its words having just been said by the other side."""
import re
import time


def _stems(text):
    # word endings dropped: Whisper often transcribes word endings differently in the two channels
    return [w[:6] for w in re.findall(r"\w+", text.lower())]


def is_echo(me_text, them_texts, threshold=0.7, min_words=2, keep=None):
    if keep and keep(me_text):
        return False  # "Luna, …" — addressed to the assistant, the other side does not say that
    me = _stems(me_text)
    if len(me) < min_words:  # "Yes", "No", "Uh-huh" — left alone, they can match by chance
        return False
    them = set(_stems(" ".join(them_texts)))
    return sum(w in them for w in me) / len(me) >= threshold


class EchoFilter:
    def __init__(self, threshold=0.7, lookback=12.0, keep=None):
        self.threshold = threshold
        self.lookback = lookback
        self.keep = keep  # phrase -> True if it must never count as an echo (addressed to the assistant)
        self.recent = []  # (time, text) of the other side's latest lines

    def add_them(self, text, now=None):
        now = now or time.time()
        self.recent = [(t, s) for t, s in self.recent if now - t <= self.lookback] + [(now, text)]

    def check(self, me_text, now=None):
        now = now or time.time()
        return is_echo(me_text, [s for t, s in self.recent if now - t <= self.lookback], self.threshold,
                       keep=self.keep)

    def clear(self):
        self.recent.clear()
