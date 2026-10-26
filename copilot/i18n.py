"""UI strings in English and Russian.

The language comes from "ui_language" in config.json ("en" / "ru"); if it is not set,
from the Windows display language (Russian Windows -> "ru", anything else -> "en").
"""
import ctypes

LANG = "en"


def detect_language():
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "ru" if (langid & 0x3FF) == 0x19 else "en"  # 0x19 = LANG_RUSSIAN
    except Exception:
        return "en"


def set_language(code):
    global LANG
    LANG = code if code in STRINGS else detect_language()
    return LANG


def t(key, **kw):
    s = STRINGS[LANG].get(key, STRINGS["en"][key])
    return s.format(**kw) if kw else s


STRINGS = {
    "en": {
        # tabs and toolbar
        "tab_hints": "Hints", "tab_about": "About me", "tab_context": "Context",
        "btn_auto": "Auto", "tip_auto": "A hint arrives on its own when the other person finishes speaking",
        "btn_top": "📌 On top", "tip_top": "Keep the window above other windows",
        "btn_clear": "🗑 Clear",
        "tip_clear": "Reset the current conversation: transcript, hints and Context.\n"
                     "About me stays. The log starts a new file.",
        "btn_screen": "📷 Screen",
        "tip_screen": "Take a screenshot and send it to the model: it will go through what is on it\n"
                      "(a document, contract, task, slide) in light of the conversation  ·  Ctrl+Alt+S",
        "btn_summary": "📝 Summary",
        "tip_summary": "Short call summary: what was agreed, what was offered,\n"
                       "open questions, your next steps  ·  Ctrl+Alt+R",
        "btn_answer": "💡 Hint now",
        "tip_answer": "A hint right now for the current moment of the conversation,\n"
                      "without waiting for a pause  ·  Ctrl+Alt+Enter",
        # devices
        "dev_them": "Other side", "tip_them": "Where to listen to the other side — system audio",
        "dev_me": "Microphone", "tip_me": "Your microphone",
        "tip_rescan": "Refresh the device list",
        "btn_mute": "🔇 Mute", "btn_muted": "🔇 Muted",
        "tip_mute": "Temporarily cut all audio from the app — both the other side and your microphone.\n"
                    "While on, nothing is recorded, transcribed or sent to the model  ·  Ctrl+Alt+M",
        "device_default": "Default — {name}", "device_none": "none", "mic_off": "Off",
        # transcript and feed
        "transcript_title": "TRANSCRIPT",
        "transcript_note": "hears both sides · ask by voice: “{name}, …”",
        "transcript_note_tip": "The model hears both you and the other side and gives hints on what they say.\n"
                               "To ask it by voice, start a phrase with “{name}, …” — it will answer it as a question.",
        "hints_title": "HINTS",
        "btn_jump": "↓ Latest", "tip_jump": "Scroll to the newest hints and turn auto-scroll back on",
        "input_placeholder": "Ask with the conversation in mind…   Ctrl+Alt+Space", "tip_send": "Send",
        "answer_placeholder": "Hints will appear here. When the other side finishes speaking, a hint arrives "
                              "on its own (Auto mode).\n\n"
                              "💡 Hint now — a hint right away, without waiting for a pause.\n"
                              "📷 Screen — the model looks at your screen (document, contract, task, slide) "
                              "and goes through it.\n"
                              "📝 Summary — call summary: agreements, open questions, next steps.\n"
                              "The field at the bottom — your own question, with the whole conversation in mind.\n"
                              "🎙 Or ask by voice: “{name}, how many days of notice do they owe me?” — "
                              "the model answers your phrase.\n\n"
                              "An answer usually takes 5–10 seconds.",
        "who_them": "Them", "who_me": "Me",
        "title_hint": "HINT", "title_summary": "CALL SUMMARY", "title_screen": "SCREEN REVIEW",
        "title_answer": "ANSWER", "updated": "updated {time}", "thinking": "thinking",
        # About me / Context
        "about_title": "ABOUT ME",
        "about_hint": "Fill this in once: who you are, your work, experience, skills, how you like answers. "
                      "Kept between launches and not erased by “🗑 Clear”.",
        "about_placeholder": "Example:\nI'm Alex, 29, backend developer (Python, Go), 5 years at Acme Corp.\n"
                             "Strengths: high-load services, PostgreSQL, mentoring juniors.\n"
                             "Keep answers short and to the point.",
        "about_empty": "Empty — the model knows nothing about you",
        "context_title": "CALL CONTEXT",
        "context_hint": "What matters for this call: who you are talking to, the goal, facts, numbers, "
                        "the text of a contract or email. The model sees it with every hint. "
                        "Erased by “🗑 Clear” together with the chat.",
        "context_placeholder": "Example:\nCall with a client about extending the contract.\n"
                               "Goal: keep the price, agree on a March deadline, get the scope in writing.\n"
                               "Important: our last offer was $12k for phase 2.",
        "context_empty": "Empty — the model works without call context",
        "paste": "Paste from clipboard", "clear_text": "Clear",
        "saved": "Saved", "saved_ok": "Saved ✓", "edited": "Edited…", "chars": "{prefix}  ·  {n} chars",
        # status
        "status_loading": "Loading Whisper “{name}”…", "status_listening": "Listening",
        "status_muted": "🔇 Muted — the app hears nothing", "stt_error": "Speech recognition error: {e}",
        "audio_failed": "Audio did not start: {e}", "devices_failed": "Could not get the device list: {e}",
        "err_them": "other side audio: {e}", "err_mic": "microphone: {e}",
        "device_not_found": "Device not found: {name!r}", "no_default_mic": "No default microphone is set in Windows",
        "model_default": "default",
        # requests
        "note_force": "Thinking about a hint for the current moment of the conversation…",
        "note_manual": "Answering your question…", "note_voice": "Heard you — answering…",
        "note_screen": "Screenshot taken — going through what is on it…",
        "note_summary": "Putting together the summary: agreements, open questions, your next steps…",
        "usual_time": "Usually 5–10 seconds.",
        "interrupted": "*Interrupted: a new request started.*", "question": "Question",
        "nothing_to_add": "The model has nothing to add at this moment.", "model_error": "Model error",
        "codex_missing": "ChatGPT is not connected: open ⚙ Settings and press Connect.",
        "claude_login": "Open ⚙ Settings and press Connect.",
        "cli_exit": "{name} exited with code {code}",
        # session log
        "log_call": "# Call {dt}", "log_devices": "_Devices: other side — {them}; me — {me}_",
        "log_question": "> Question: {q}", "log_question_voice": "> Voice question: {q}",
        "log_echo": "_(echo dropped — the microphone heard the other side: “{text}”)_",
        "log_muted": "_🔇 Audio muted {time}_", "log_unmuted": "_🔊 Audio back on {time}_",
        "log_model_error": "_Model error: {e}_",
        # settings
        "tip_settings": "Settings", "settings_title": "SETTINGS",
        "set_provider": "Subscription", "set_model": "Model",
        "provider_codex": "ChatGPT (Codex)", "provider_claude": "Claude (Claude Code)",
        "set_hint": "The model runs through your own subscription. Switching applies right away, no restart needed.",
        "set_wake": "Ask by voice: start a phrase with “{name}, …”",
        "claude_missing": "Claude is not connected: open ⚙ Settings and press Connect.",
        "log_backend": "_Model: {label}_",
        "pill_listening": "Listening", "pill_thinking": "Thinking", "pill_muted": "Muted",
        "pill_error": "Error", "pill_starting": "Starting",
        "empty_title": "Ready for your call",
        # connecting a subscription
        "st_ok": "Connected", "st_no_cli": "Not installed", "st_no_login": "Not signed in",
        "st_checking": "Checking the connection…",
        "st_connecting": "Connecting — finish signing in in the window that opened…",
        "btn_connect": "Connect", "btn_cancel": "Cancel",
        "connect_q_title": "Connect {name}?",
        "connect_q_text": "{name} is not connected yet. A window will open: the app installs what is needed and "
                          "opens the sign-in to your account with a subscription. Connect now?",
        "connect_failed": "{name} was not connected. Try again or check the connection window.",
        "not_connected": "{name} is not connected — ⚙ Settings → Connect",
        "connect_script_missing": "connect.ps1 not found — reinstall the app.",
        # languages
        "set_ui_lang": "Interface", "set_speech_lang": "Conversation",
        "lang_ru": "Русский", "lang_en": "English", "lang_auto": "Russian / English — auto",
        "restart_q_title": "Change the language?",
        "restart_q_text": "The interface language changes after the window restarts (a couple of seconds). Restart now?",
        "btn_restart": "Restart", "btn_later": "Later",
    },
    "ru": {
        "tab_hints": "Подсказки", "tab_about": "Обо мне", "tab_context": "Контекст",
        "btn_auto": "Авто", "tip_auto": "Подсказка приходит сама, когда собеседник договорил",
        "btn_top": "📌 Поверх", "tip_top": "Держать окно поверх остальных",
        "btn_clear": "🗑 Очистить",
        "tip_clear": "Сбросить текущий разговор: расшифровку, подсказки и «Контекст».\n"
                     "«Обо мне» остаётся. Журнал начнётся с нового файла.",
        "btn_screen": "📷 Экран",
        "tip_screen": "Сделать снимок экрана и отправить модели: она разберёт, что на нём\n"
                      "(документ, договор, задачу, слайд) с учётом разговора  ·  Ctrl+Alt+S",
        "btn_summary": "📝 Итоги",
        "tip_summary": "Краткий итог созвона: о чём договорились, что предложили,\n"
                       "открытые вопросы, твои следующие шаги  ·  Ctrl+Alt+R",
        "btn_answer": "💡 Подсказать",
        "tip_answer": "Подсказка прямо сейчас по текущему моменту разговора,\n"
                      "не дожидаясь паузы собеседника  ·  Ctrl+Alt+Enter",
        "dev_them": "Собеседник", "tip_them": "Откуда слушать собеседника — системный звук",
        "dev_me": "Микрофон", "tip_me": "Твой микрофон",
        "tip_rescan": "Обновить список устройств",
        "btn_mute": "🔇 Заглушить", "btn_muted": "🔇 Заглушено",
        "tip_mute": "Временно отключить весь звук от программы — и собеседника, и микрофон.\n"
                    "Пока включено, ничего не записывается, не распознаётся и не уходит модели  ·  Ctrl+Alt+M",
        "device_default": "По умолчанию — {name}", "device_none": "нет", "mic_off": "Выключен",
        "transcript_title": "РАСШИФРОВКА",
        "transcript_note": "слышит обе стороны · спроси голосом: «{name}, …»",
        "transcript_note_tip": "Модель слышит и тебя, и собеседника. Сама подсказывает на реплики собеседника.\n"
                               "Чтобы спросить её голосом, начни фразу с «{name}, …» — ответ придёт как на вопрос.",
        "hints_title": "ПОДСКАЗКИ",
        "btn_jump": "↓ К последним", "tip_jump": "Прокрутить к новым подсказкам и снова включить автопрокрутку",
        "input_placeholder": "Спросить с учётом разговора…   Ctrl+Alt+Space", "tip_send": "Отправить",
        "answer_placeholder": "Здесь появятся подсказки. Когда собеседник договорит, подсказка придёт сама "
                              "(режим «Авто»).\n\n"
                              "💡 Подсказать — подсказка прямо сейчас, не дожидаясь паузы.\n"
                              "📷 Экран — модель посмотрит на твой экран (документ, договор, задачу, слайд) "
                              "и разберёт его.\n"
                              "📝 Итоги — итог созвона: договорённости, открытые вопросы, следующие шаги.\n"
                              "Поле внизу — свой вопрос модели с учётом всего разговора.\n"
                              "🎙 Или спроси голосом: «{name}, сколько дней на уведомление?» — "
                              "модель ответит на твою фразу.\n\n"
                              "Ответ обычно приходит за 5–10 секунд.",
        "who_them": "Собеседник", "who_me": "Я",
        "title_hint": "ПОДСКАЗКА", "title_summary": "ИТОГИ СОЗВОНА", "title_screen": "РАЗБОР ЭКРАНА",
        "title_answer": "ОТВЕТ НА ВОПРОС", "updated": "обновлено {time}", "thinking": "думаю",
        "about_title": "ОБО МНЕ",
        "about_hint": "Заполни один раз: кто ты, работа, опыт, навыки, как тебе удобнее отвечать. "
                      "Сохраняется между запусками и не стирается кнопкой «🗑 Очистить».",
        "about_placeholder": "Пример:\nМеня зовут Алексей, 29 лет. Бэкенд-разработчик (Python, Go), "
                             "5 лет в компании «Ромашка».\n"
                             "Сильные стороны: высоконагруженные сервисы, PostgreSQL, менторство джунов.\n"
                             "Отвечай мне коротко и по делу, на «ты».",
        "about_empty": "Пусто — модель ничего о тебе не знает",
        "context_title": "КОНТЕКСТ СОЗВОНА",
        "context_hint": "Важное для этого созвона: с кем говоришь, цель, факты, цифры, текст договора или письма. "
                        "Модель видит это при каждой подсказке. Очищается кнопкой «🗑 Очистить» вместе с чатом.",
        "context_placeholder": "Пример:\nСозвон с клиентом о продлении договора.\n"
                               "Цель: удержать цену, договориться о сроке в марте, зафиксировать объём письменно.\n"
                               "Важно: наше последнее предложение — 1,2 млн за второй этап.",
        "context_empty": "Пусто — модель работает без контекста созвона",
        "paste": "Вставить из буфера", "clear_text": "Очистить",
        "saved": "Сохранено", "saved_ok": "Сохранено ✓", "edited": "Изменено…", "chars": "{prefix}  ·  {n} симв.",
        "status_loading": "Загружаю Whisper «{name}»…", "status_listening": "Слушаю",
        "status_muted": "🔇 Заглушено — программа ничего не слышит", "stt_error": "Ошибка распознавания: {e}",
        "audio_failed": "Аудио не запустилось: {e}", "devices_failed": "Не удалось получить список устройств: {e}",
        "err_them": "звук собеседника: {e}", "err_mic": "микрофон: {e}",
        "device_not_found": "Устройство не найдено: {name!r}", "no_default_mic": "В Windows не выбран микрофон по умолчанию",
        "model_default": "по умолчанию",
        "note_force": "Думаю над подсказкой по текущему моменту разговора…",
        "note_manual": "Отвечаю на твой вопрос…", "note_voice": "Услышал обращение — отвечаю…",
        "note_screen": "Снимок экрана сделан — разбираю, что на нём…",
        "note_summary": "Собираю итоги: о чём договорились, открытые вопросы, твои следующие шаги…",
        "usual_time": "Обычно это 5–10 секунд.",
        "interrupted": "*Прервано: начат новый запрос.*", "question": "Вопрос",
        "nothing_to_add": "Модели нечего добавить по текущему моменту.", "model_error": "Ошибка модели",
        "codex_missing": "ChatGPT не подключён: открой ⚙ Настройки и нажми «Подключить».",
        "claude_login": "Открой ⚙ Настройки и нажми «Подключить».",
        "cli_exit": "{name} завершился с кодом {code}",
        "log_call": "# Созвон {dt}", "log_devices": "_Устройства: собеседник — {them}; я — {me}_",
        "log_question": "> Вопрос: {q}", "log_question_voice": "> Вопрос голосом: {q}",
        "log_echo": "_(эхо отброшено — микрофон услышал собеседника: «{text}»)_",
        "log_muted": "_🔇 Звук отключён {time}_", "log_unmuted": "_🔊 Звук снова включён {time}_",
        "log_model_error": "_Ошибка модели: {e}_",
        "tip_settings": "Настройки", "settings_title": "НАСТРОЙКИ",
        "set_provider": "Подписка", "set_model": "Модель",
        "provider_codex": "ChatGPT (Codex)", "provider_claude": "Claude (Claude Code)",
        "set_hint": "Модель работает через твою подписку. Переключение сразу, без перезапуска.",
        "set_wake": "Спросить голосом: начни фразу с «{name}, …»",
        "claude_missing": "Claude не подключён: открой ⚙ Настройки и нажми «Подключить».",
        "log_backend": "_Модель: {label}_",
        "pill_listening": "Слушаю", "pill_thinking": "Думаю", "pill_muted": "Заглушено",
        "pill_error": "Ошибка", "pill_starting": "Запуск",
        "empty_title": "Готов к созвону",
        "st_ok": "Подключено", "st_no_cli": "Не установлено", "st_no_login": "Вход не выполнен",
        "st_checking": "Проверяю подключение…",
        "st_connecting": "Подключаю — заверши вход в открывшемся окне…",
        "btn_connect": "Подключить", "btn_cancel": "Отмена",
        "connect_q_title": "Подключить {name}?",
        "connect_q_text": "{name} ещё не подключён. Откроется окно: программа сама установит нужное и откроет "
                          "вход в аккаунт с подпиской. Подключить сейчас?",
        "connect_failed": "{name} не подключён. Попробуй ещё раз или посмотри сообщения в окне подключения.",
        "not_connected": "{name} не подключён — ⚙ Настройки → Подключить",
        "connect_script_missing": "Не найден connect.ps1 — переустанови программу.",
        "set_ui_lang": "Интерфейс", "set_speech_lang": "Разговор",
        "lang_ru": "Русский", "lang_en": "English", "lang_auto": "Русский / английский — сам",
        "restart_q_title": "Сменить язык?",
        "restart_q_text": "Язык интерфейса сменится после перезапуска окна (пара секунд). Перезапустить сейчас?",
        "btn_restart": "Перезапустить", "btn_later": "Позже",
    },
}
