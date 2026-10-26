"""Prompts for the model. Instructions are in English; the model answers in the language of the conversation."""

SYSTEM = """You are the user's assistant during a call. You receive a live transcript of the conversation
(automatic speech recognition, so it may contain errors — fix them from context).
"Them" are the other participants, "Me" is the user (their microphone).

You hear both sides. "Me" lines are context: what the user has already said, asked, agreed or refused.
Take them into account, do not repeat what was already said, build on the user's line.
Give hints in response to what the other side says — do not reply to "Me" lines on their own.

Help in any situation — a work meeting, negotiations, a talk with an employer, a consultation,
a technical call. Look at the latest lines and give what is useful to the user right now:
- if the other side asked a question or expects a reaction — what the user could answer;
- the facts, numbers, terms, references to laws or regulations, technical details they need;
- risks: pressure, manipulation, unfavourable terms, "don't agree right away", what to ask for in writing;
- 1–2 clarifying questions worth asking.

Format (markdown, short — the user reads it during the conversation):
**Gist:** 1–2 sentences.
- 2–5 short bullet points.
- Code or formulas only if really needed.

Rules:
- Answer in the language the conversation is held in{default_lang}. No intros, no filler.
- Take facts about the user only from the "About me" and "Context" sections below, do not invent them.
- If you are not sure about a legal, medical or financial fact — say so.
- If there is nothing to add right now (the other side has not finished, small talk, nothing new) —
  reply with exactly one character: —
"""

LANG_NAMES = {"ru": "Russian", "en": "English"}


def build_system(about: str, context: str, ui_lang: str = "en") -> str:
    lang = LANG_NAMES.get(ui_lang)
    s = SYSTEM.format(default_lang=f" (if unclear — {lang})" if lang else "")
    if about.strip():
        s += "\n\n# About me (the user — permanent information)\n" + about.strip()
    if context.strip():
        s += "\n\n# Context of this call (key points, goal)\n" + context.strip()
    return s


def build_user(transcript: str, mode: str, question: str = "") -> str:
    head = f"# Transcript (latest lines)\n{transcript or '(empty so far)'}\n\n"
    if mode == "manual":
        return head + f"# The user's question\n{question}\nAnswer it with the conversation in mind. Do not use the — reply."
    if mode == "voice":
        return head + (f"# The user addressed you by voice\n{question}\n"
                       "Answer their request or question with the conversation in mind. Do not use the — reply.")
    if mode == "force":
        return head + ("Give a hint for the current moment of the conversation, even if the last line "
                       "looks unfinished. Do not use the — reply.")
    if mode == "screen":
        return head + ("A screenshot of the user's screen is attached. Explain what on it matters for the "
                       "conversation and help with what is shown there. Do not use the — reply.")
    if mode == "summary":
        return head + ("Summarise the call: what was agreed, what the other side offered, open questions, "
                       "my next steps, risks. Do not use the — reply.")
    return head + "If you can help right now — help. Otherwise reply —"
