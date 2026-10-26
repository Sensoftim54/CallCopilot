"""Main window: Hints tab (devices, transcript, hint feed, question box), About me, Context and Settings tabs."""
import ctypes
import os
import tempfile
from ctypes import wintypes
from datetime import datetime

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPlainTextEdit, QScrollArea, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from . import models
from .i18n import t
from .icon import make_icon, make_pixmap
from .widgets import Button, LevelMeter, Segmented, ShimmerBar, StatusPill, TypingDots, fade_in

MIC_OFF = "__off__"


def _chevron_path():
    """Down-arrow for combo boxes, drawn once into a temp png (Qt style sheets take images from files)."""
    path = os.path.join(tempfile.gettempdir(), "callcopilot_chevron.png")
    if not os.path.exists(path):
        pm = QPixmap(20, 20)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#8a93a6"), 2.0, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(5, 8), QPointF(10, 13), QPointF(15, 8)])
        p.end()
        pm.save(path, "PNG")
    return path.replace("\\", "/")


STYLE = """
* { font-family: "Segoe UI Variable Text", "Segoe UI"; }
QFrame[card="true"] { background: rgba(19, 22, 30, 235); border: 1px solid #1d2230; border-radius: 14px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QWidget#feed { background: transparent; }
QFrame#msg { background: #161a24; border: 1px solid #222837; border-radius: 12px; }
QFrame#msg[hover="true"] { background: #191e29; border-color: #313950; }
QLabel { color: #9aa3b2; font-size: 12px; background: transparent; }
QLabel[role="title"] { color: #f4f5f8; font-size: 15px; font-weight: 600; }
QLabel[role="section"] { color: #6b7488; font-size: 10px; font-weight: 700; }
QLabel[role="chip"] { color: #cbc5ff; background: rgba(124, 108, 255, 30); border: 1px solid rgba(124, 108, 255, 60);
    border-radius: 10px; padding: 2px 10px; font-size: 11px; }
QLabel[role="meta"] { color: #6b7488; font-size: 11px; }
QLabel[role="error"] { color: #ff8a8a; font-size: 11px; }
QTextEdit, QTextBrowser { background: transparent; color: #e9ebef; border: none; selection-background-color: #4b3fd1; }
QPlainTextEdit { background: #0f1218; color: #e9ebef; border: 1px solid #222837; border-radius: 12px; padding: 10px;
    font-size: 13px; selection-background-color: #4b3fd1; }
QPlainTextEdit:focus { border-color: #6d5ff0; }
QLineEdit { background: #0f1218; color: #f2f3f5; border: 1px solid #222837; border-radius: 12px; padding: 10px 14px;
    font-size: 13px; selection-background-color: #4b3fd1; }
QLineEdit:hover { border-color: #2c3346; }
QLineEdit:focus { border-color: #6d5ff0; background: #11141c; }
QComboBox { background: #0f1218; color: #d6d9e0; border: 1px solid #222837; border-radius: 9px; padding: 6px 30px 6px 11px;
    font-size: 12px; }
QComboBox:hover { border-color: #343c52; background: #12151d; }
QComboBox:on { border-color: #6d5ff0; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(CHEVRON); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: #151922; color: #e9ebef; border: 1px solid #2a3142; border-radius: 8px;
    outline: 0; padding: 4px; selection-background-color: #2c2556; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #252b39; border-radius: 3px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #343c52; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QToolTip { background: #1a1e28; color: #e9ebef; border: 1px solid #2c3344; border-radius: 6px; padding: 6px 8px; }
"""

# message kinds in the hint feed -> title key and colour
KINDS = {"hint": ("title_hint", "#a99dff"), "summary": ("title_summary", "#6ee7b7"),
         "screen": ("title_screen", "#8fb3ff"), "answer": ("title_answer", "#fcd34d")}


def _prop(w, **props):
    for k, v in props.items():
        w.setProperty(k, v)
    return w


def _card():
    f = QFrame()
    f.setProperty("card", True)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(10)
    return f, lay


def _section(text):
    lbl = _prop(QLabel(text), role="section")
    f = lbl.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.1)
    lbl.setFont(f)
    return lbl


APP_ID = "CallCopilot.App"  # Windows taskbar identity; the installer tags the shortcuts with the same id


def set_taskbar_identity(widget, icon_path, relaunch_cmd):
    """Tell the Windows taskbar who this window is: app id, icon and how to relaunch it (also used when the
    window is pinned). Without it Windows 11 may show a generic icon for a Python app with its own app id."""
    try:
        import uuid
        from ctypes import POINTER, WINFUNCTYPE, Structure, byref, c_long, c_ubyte, c_ulong, c_ushort, c_void_p

        class GUID(Structure):
            _fields_ = [("d1", c_ulong), ("d2", c_ushort), ("d3", c_ushort), ("d4", c_ubyte * 8)]

        def guid(text):
            u = uuid.UUID(text)
            g = GUID(u.fields[0], u.fields[1], u.fields[2])
            g.d4[:] = list(u.bytes[8:])
            return g

        class PROPERTYKEY(Structure):
            _fields_ = [("fmtid", GUID), ("pid", c_ulong)]

        class PROPVARIANT(Structure):
            _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort), ("r3", c_ushort),
                        ("p", c_void_p), ("p2", c_void_p)]

        store = c_void_p()
        if ctypes.windll.shell32.SHGetPropertyStoreForWindow(
                wintypes.HWND(int(widget.winId())), byref(guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")),
                byref(store)) != 0:
            return False
        vtbl = ctypes.cast(store, POINTER(POINTER(c_void_p))).contents
        set_value = WINFUNCTYPE(c_long, c_void_p, POINTER(PROPERTYKEY), POINTER(PROPVARIANT))(vtbl[6])
        commit = WINFUNCTYPE(c_long, c_void_p)(vtbl[7])
        release = WINFUNCTYPE(c_ulong, c_void_p)(vtbl[2])
        fmt = guid("9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3")  # System.AppUserModel.*
        keep, ok = [], True
        # relaunch command (2), icon (3) and name (4) first, the app id (5) last
        for pid, value in ((2, relaunch_cmd), (3, icon_path + ",0"), (4, "Call Copilot"), (5, APP_ID)):
            buf = ctypes.create_unicode_buffer(value)
            keep.append(buf)
            pv = PROPVARIANT(vt=31)  # VT_LPWSTR
            pv.p = ctypes.cast(buf, c_void_p)
            ok &= set_value(store, byref(PROPERTYKEY(fmt, pid)), byref(pv)) == 0
        ok &= commit(store) == 0
        release(store)
        return ok
    except Exception:
        return False


def _dark_titlebar(widget):
    try:  # Windows 10 20H1+/11: dark system title bar
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(int(widget.winId())), 20,
                                                   ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


class NoteEditor(QWidget):
    """A tab with text for the model (About me, Context): autosave, paste from clipboard, clear."""
    saved = pyqtSignal(str)

    def __init__(self, parent, title, hint, placeholder, empty_note):
        super().__init__(parent)
        self.empty_note = empty_note
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        card, cl = _card()
        cl.addWidget(_section(title))
        h = QLabel(hint)
        h.setWordWrap(True)
        cl.addWidget(h)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.textChanged.connect(self._edited)
        cl.addWidget(self.edit, 1)
        foot = QHBoxLayout()
        self.state = _prop(QLabel(""), role="meta")
        foot.addWidget(self.state)
        foot.addStretch(1)
        for text, fn in ((t("paste"), self._paste), (t("clear_text"), self.edit.clear)):
            b = Button(text)
            b.clicked.connect(fn)
            foot.addWidget(b)
        cl.addLayout(foot)
        v.addWidget(card, 1)
        self.timer = QTimer(self, singleShot=True, interval=600)
        self.timer.timeout.connect(self._save)

    def text(self):
        return self.edit.toPlainText()

    def set_text(self, text):
        self.timer.stop()
        self.edit.blockSignals(True)
        self.edit.setPlainText(text)
        self.edit.blockSignals(False)
        self._update_state(t("saved"))

    def _edited(self):
        self.state.setText(t("edited"))
        self.timer.start()

    def _save(self):
        self.saved.emit(self.text())
        self._update_state(t("saved_ok"))

    def flush(self):
        if self.timer.isActive():
            self.timer.stop()
            self._save()

    def _update_state(self, prefix):
        n = len(self.text())
        self.state.setText(t("chars", prefix=prefix, n=n) if n else self.empty_note)

    def _paste(self):
        clip = QApplication.clipboard().text()
        if clip:
            cur = self.text()
            self.edit.setPlainText((cur.rstrip() + "\n\n" + clip) if cur.strip() else clip)


class AskDialog(QDialog):
    """A question in the app's own style: title, text, Cancel and a primary action."""

    def __init__(self, parent, title, text, ok, cancel):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setStyleSheet((parent.styleSheet() if parent else "") + "QDialog { background: #12151c; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(_prop(QLabel(title), role="title"))
        body = QLabel(text)
        body.setWordWrap(True)
        body.setMinimumWidth(400)
        body.setStyleSheet("color: #c9cedb; font-size: 13px;")
        v.addWidget(body)
        row = QHBoxLayout()
        row.addStretch(1)
        no = Button(cancel)
        no.clicked.connect(self.reject)
        yes = Button(ok, "primary")
        yes.clicked.connect(self.accept)
        row.addWidget(no)
        row.addWidget(yes)
        v.addLayout(row)

    def showEvent(self, e):
        super().showEvent(e)
        _dark_titlebar(self)


class SettingsPage(QWidget):
    """Settings tab: subscription and model (switching applies right away; a subscription that is not
    connected yet can be connected from here), interface and conversation language."""
    changed = pyqtSignal(str, str)  # backend, model
    connect_clicked = pyqtSignal(str)  # backend
    ui_lang_changed = pyqtSignal(str)
    speech_lang_changed = pyqtSignal(str)

    STATE_COLORS = {"ok": "#34d399", "no_cli": "#f87171", "no_login": "#fbbf24", "checking": "#8a93a6",
                    "connecting": "#7c6cff"}

    def __init__(self, parent):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        card, cl = _card()
        cl.addWidget(_section(t("settings_title")))
        hint = QLabel(t("set_hint"))
        hint.setWordWrap(True)
        cl.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(QLabel(t("set_provider")), 0, 0)
        self.cb_backend = QComboBox()
        for b in models.CHOICES:
            self.cb_backend.addItem(t(f"provider_{b}"), b)
        grid.addWidget(self.cb_backend, 0, 1)
        conn = QHBoxLayout()  # connection status of the chosen subscription + Connect
        self.conn_label = QLabel("")
        self.conn_label.setTextFormat(Qt.TextFormat.RichText)
        conn.addWidget(self.conn_label)
        conn.addStretch(1)
        self.btn_connect = Button(t("btn_connect"), "primary")
        self.btn_connect.clicked.connect(lambda: self.connect_clicked.emit(self.cb_backend.currentData()))
        self.btn_connect.hide()
        conn.addWidget(self.btn_connect)
        grid.addLayout(conn, 1, 1)
        grid.addWidget(QLabel(t("set_model")), 2, 0)
        self.cb_model = QComboBox()
        grid.addWidget(self.cb_model, 2, 1)
        grid.addWidget(QLabel(t("set_ui_lang")), 3, 0)
        self.cb_ui = QComboBox()
        for code in ("ru", "en"):
            self.cb_ui.addItem(t(f"lang_{code}"), code)
        grid.addWidget(self.cb_ui, 3, 1)
        grid.addWidget(QLabel(t("set_speech_lang")), 4, 0)
        self.cb_speech = QComboBox()
        for code in ("ru", "en", "auto"):
            self.cb_speech.addItem(t(f"lang_{code}"), code)
        grid.addWidget(self.cb_speech, 4, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        self.cb_ui.currentIndexChanged.connect(lambda _: self.ui_lang_changed.emit(self.cb_ui.currentData()))
        self.cb_speech.currentIndexChanged.connect(lambda _: self.speech_lang_changed.emit(self.cb_speech.currentData()))
        self.wake = QLabel()
        self.wake.setStyleSheet("color: #e9ebef; font-size: 13px; background: rgba(124,108,255,22);"
                                "border: 1px solid rgba(124,108,255,50); border-radius: 10px; padding: 10px 12px;")
        cl.addWidget(self.wake)
        self.warn = _prop(QLabel(""), role="error")
        self.warn.setWordWrap(True)
        cl.addWidget(self.warn)
        cl.addStretch(1)
        v.addWidget(card, 1)
        self.cb_backend.currentIndexChanged.connect(self._backend_picked)
        self.cb_model.currentIndexChanged.connect(self._emit)

    def _fill_models(self, backend, model=None):
        self.cb_model.blockSignals(True)
        self.cb_model.clear()
        for value, label in models.CHOICES[backend]:
            self.cb_model.addItem(label, value)
        if model and self.cb_model.findData(model) < 0:  # a model set by hand in config.json stays selectable
            self.cb_model.addItem(model, model)
        i = self.cb_model.findData(model)
        self.cb_model.setCurrentIndex(i if i >= 0 else 0)
        self.cb_model.blockSignals(False)

    def set_state(self, backend, model, wake_name, warning):
        self.cb_backend.blockSignals(True)
        self.cb_backend.setCurrentIndex(max(0, self.cb_backend.findData(backend)))
        self.cb_backend.blockSignals(False)
        self._fill_models(backend, model)
        self.wake.setText("🎙  " + t("set_wake", name=wake_name))
        self.warn.setText(f"⚠ {warning}" if warning else "")

    def set_connection(self, state):
        """state: ok / no_cli / no_login / checking / connecting — for the subscription chosen above."""
        color = self.STATE_COLORS.get(state, "#8a93a6")
        self.conn_label.setText(f'<span style="color:{color}">●</span>&nbsp; '
                                f'<span style="color:#c9cedb">{t("st_" + state)}</span>')
        self.btn_connect.setVisible(state in ("no_cli", "no_login"))
        busy = state in ("checking", "connecting")
        self.cb_backend.setEnabled(not busy)
        self.cb_model.setEnabled(not busy)

    def set_langs(self, ui, speech):
        for cb, code in ((self.cb_ui, ui), (self.cb_speech, speech)):
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData(code)))
            cb.blockSignals(False)

    def _backend_picked(self):
        self._fill_models(self.cb_backend.currentData())
        self._emit()

    def _emit(self):
        self.changed.emit(self.cb_backend.currentData(), self.cb_model.currentData())


class MainWindow(QWidget):
    ask = pyqtSignal(str)
    action = pyqtSignal(str)
    device_changed = pyqtSignal(str, str)  # ("them"|"me", device name; "" = Windows default)
    context_changed = pyqtSignal(str)
    about_changed = pyqtSignal(str)
    backend_changed = pyqtSignal(str, str)  # backend, model — from the Settings tab
    connect_requested = pyqtSignal(str)  # backend
    ui_lang_changed = pyqtSignal(str)
    speech_lang_changed = pyqtSignal(str)

    def __init__(self, cfg):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Call Copilot")
        self.setWindowIcon(make_icon())
        self.setStyleSheet(STYLE.replace("CHEVRON", _chevron_path()))
        self.resize(*cfg.get("window_size", [620, 800]))  # the layout sets the minimum, so buttons never get cut
        self.fs = cfg.get("font_size", 13)
        self._st = {"msg": "", "busy": False, "backend": "", "err": "", "muted": False}
        self._shown_once = False

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(12)
        root.addLayout(self._header())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._assistant_page())
        self.about_ed = NoteEditor(self, t("about_title"), t("about_hint"), t("about_placeholder"), t("about_empty"))
        self.about_ed.saved.connect(self.about_changed)
        self.pages.addWidget(self.about_ed)
        self.context_ed = NoteEditor(self, t("context_title"), t("context_hint"), t("context_placeholder"),
                                     t("context_empty"))
        self.context_ed.saved.connect(self.context_changed)
        self.pages.addWidget(self.context_ed)
        self.settings = SettingsPage(self)
        self.settings.changed.connect(self.backend_changed)
        self.settings.connect_clicked.connect(self.connect_requested)
        self.settings.ui_lang_changed.connect(self.ui_lang_changed)
        self.settings.speech_lang_changed.connect(self.speech_lang_changed)
        self.pages.addWidget(self.settings)
        root.addWidget(self.pages, 1)

        foot = QHBoxLayout()
        self.status = _prop(QLabel(""), role="meta")
        self.error = _prop(QLabel(""), role="error")
        self.error.setWordWrap(True)
        foot.addWidget(self.status)
        foot.addWidget(self.error, 1)
        self.chip = _prop(QLabel(""), role="chip")
        foot.addWidget(self.chip)
        root.addLayout(foot)
        self._show_tab(0, animate=False)

    # ---------- background ----------
    def paintEvent(self, _):
        p = QPainter(self)
        r = QRectF(self.rect())
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#0e1018"))
        g.setColorAt(1, QColor("#090b10"))
        p.fillRect(r, g)
        for cx, cy, rad, col in ((0.0, 0.0, 0.9, QColor(124, 108, 255, 34)), (1.0, 1.0, 0.8, QColor(91, 124, 255, 20))):
            glow = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), max(r.width(), r.height()) * rad)
            glow.setColorAt(0, col)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(r, glow)

    # ---------- layout ----------
    def _header(self):
        h = QHBoxLayout()
        h.setSpacing(10)
        logo = QLabel()
        dpr = self.devicePixelRatioF() or 1.0
        pm = make_pixmap(int(26 * dpr))
        pm.setDevicePixelRatio(dpr)
        logo.setPixmap(pm)
        h.addWidget(logo)
        h.addWidget(_prop(QLabel("Call Copilot"), role="title"))
        self.pill = StatusPill()
        h.addWidget(self.pill)
        h.addStretch(1)
        self.tabs = Segmented([t("tab_hints"), t("tab_about"), t("tab_context"), "⚙"],
                              tips=[None, None, None, t("tip_settings")])
        self.tabs.changed.connect(self._show_tab)
        h.addWidget(self.tabs)
        return h

    def _btn(self, text, act=None, kind="secondary", checkable=False, tip=None):
        b = Button(text, kind, checkable, tip)
        if act:
            b.clicked.connect(lambda: self.action.emit(act))
        return b

    def _assistant_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_auto = self._btn(t("btn_auto"), "auto", "toggle", True, t("tip_auto"))
        self.btn_top = self._btn(t("btn_top"), "top", "toggle", True, t("tip_top"))
        bar.addWidget(self.btn_auto)
        bar.addWidget(self.btn_top)
        bar.addWidget(self._btn(t("btn_clear"), "clear", tip=t("tip_clear")))
        bar.addStretch(1)
        bar.addWidget(self._btn(t("btn_screen"), "screen", tip=t("tip_screen")))
        bar.addWidget(self._btn(t("btn_summary"), "summary", tip=t("tip_summary")))
        bar.addWidget(self._btn(t("btn_answer"), "answer", "primary", tip=t("tip_answer")))
        v.addLayout(bar)

        card, cl = _card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.cb_loop, self.meter_them = self._device_row(grid, 0, t("dev_them"), "them", t("tip_them"))
        self.cb_mic, self.meter_me = self._device_row(grid, 1, t("dev_me"), "me", t("tip_me"))
        grid.addWidget(self._btn("⟳", "rescan", "ghost", tip=t("tip_rescan")), 0, 3, 2, 1)
        self.btn_mute = self._btn(t("btn_mute"), "mute", "mute", True, t("tip_mute"))
        fm = self.btn_mute.fontMetrics()  # wide enough for both labels so the button does not jump
        self.btn_mute.setFixedWidth(max(fm.horizontalAdvance(t(k)) for k in ("btn_mute", "btn_muted")) + 34)
        grid.addWidget(self.btn_mute, 0, 4, 2, 1)
        grid.setColumnStretch(1, 1)
        cl.addLayout(grid)
        v.addWidget(card)

        card, cl = _card()
        head = QHBoxLayout()
        head.addWidget(_section(t("transcript_title")))
        self.note = _prop(QLabel(""), role="meta")  # text depends on the model's name — see set_backend_state
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # gets cut when short of space
        head.addSpacing(6)
        head.addWidget(self.note, 1)
        cl.addLayout(head)
        self.transcript = QTextEdit(readOnly=True)
        self.transcript.setStyleSheet(f"font-size: {self.fs - 1}px;")
        cl.addWidget(self.transcript)
        card.setFixedHeight(196)
        v.addWidget(card)

        card, cl = _card()
        head = QHBoxLayout()
        head.addWidget(_section(t("hints_title")))
        head.addStretch(1)
        self.meta = _prop(QLabel(""), role="meta")
        head.addWidget(self.meta)
        self.btn_jump = self._btn(t("btn_jump"), kind="ghost", tip=t("tip_jump"))
        self.btn_jump.hide()
        head.addWidget(self.btn_jump)
        cl.addLayout(head)
        self.progress = ShimmerBar()  # light sweep while the model thinks
        cl.addWidget(self.progress)
        self.feed = Feed(self.fs)
        self.feed.stick_changed.connect(self._jump_visible)
        self.btn_jump.clicked.connect(self.feed.scroll_to_end)
        cl.addWidget(self.feed, 1)
        v.addWidget(card, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit(placeholderText=t("input_placeholder"))
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input, 1)
        send = self._btn("➤", kind="primary", tip=t("tip_send"))
        send.setFixedSize(46, 40)
        send.clicked.connect(self._submit)
        row.addWidget(send)
        v.addLayout(row)
        return page

    def _jump_visible(self, stuck):
        show = not stuck and bool(self.feed.msgs)
        if show and not self.btn_jump.isVisible():
            self.btn_jump.show()
            fade_in(self.btn_jump, 180)
        elif not show:
            self.btn_jump.hide()

    def _device_row(self, grid, r, title, kind, tip):
        grid.addWidget(QLabel(title), r, 0)
        cb = QComboBox()
        cb.setToolTip(tip)
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(16)
        cb.currentIndexChanged.connect(lambda _: (cb.setToolTip(cb.currentText()),
                                                  self.device_changed.emit(kind, cb.currentData())))
        grid.addWidget(cb, r, 1)
        m = LevelMeter()
        grid.addWidget(m, r, 2)
        return cb, m

    # ---------- tabs, About me and Context ----------
    def _show_tab(self, i, animate=True):
        if self.pages.currentIndex() == i and animate:
            return
        self.pages.setCurrentIndex(i)
        self.tabs.set_index(i)
        w = self.pages.currentWidget()
        if animate:
            fade_in(w, 200)
        if isinstance(w, NoteEditor):
            w.edit.setFocus()

    def set_about(self, text):
        self.about_ed.set_text(text)

    def set_context(self, text):
        self.context_ed.set_text(text)

    def flush_context(self):
        self.about_ed.flush()
        self.context_ed.flush()

    # ---------- state ----------
    def showEvent(self, e):
        super().showEvent(e)
        _dark_titlebar(self)
        if not self._shown_once:  # soft appearance of the window
            self._shown_once = True
            self.setWindowOpacity(0.0)
            self._appear = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=260,
                                             easingCurve=QEasingCurve.Type.OutCubic)
            self._appear.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))
            self._appear.start()

    def _submit(self):
        q = self.input.text().strip()
        if q:
            self.input.clear()
            self.ask.emit(q)

    def focus_input(self):
        self._show_tab(0)
        self.input.setFocus()

    def set_on_top(self, on):
        self.btn_top.setChecked(on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def set_auto(self, on):
        self.btn_auto.setChecked(on)

    def confirm(self, title, text, ok, cancel):
        """Yes/no question in the app's style; True if the primary action was chosen."""
        return AskDialog(self, title, text, ok, cancel).exec() == QDialog.DialogCode.Accepted

    def set_backend_state(self, backend, model, wake_name, label, warning):
        """Which model answers: Settings tab, footer chip and every hint that names it for voice questions."""
        self.settings.set_state(backend, model, wake_name, warning)
        self.chip.setText(label)
        self.note.setText(t("transcript_note", name=wake_name))
        self.note.setToolTip(t("transcript_note_tip", name=wake_name))
        self.feed.placeholder.setText(t("answer_placeholder", name=wake_name))

    def set_devices(self, loops, mics, def_loop, def_mic, cur_loop, cur_mic):
        for cb, names, default, cur, extra in ((self.cb_loop, loops, def_loop, cur_loop, None),
                                               (self.cb_mic, mics, def_mic, cur_mic, (t("mic_off"), MIC_OFF))):
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(t("device_default", name=_short(default) or t("device_none")), "")
            for n in names:
                cb.addItem(_short(n), n)
            if extra:
                cb.addItem(*extra)
            i = cb.findData(cur)
            cb.setCurrentIndex(i if i >= 0 else 0)
            cb.setToolTip(cb.currentText())
            cb.blockSignals(False)

    def set_muted(self, on):
        self.btn_mute.setChecked(on)
        self.btn_mute.setText(t("btn_muted") if on else t("btn_mute"))
        self._st["muted"] = on
        self.set_status(levels={})

    def set_status(self, msg=None, busy=None, levels=None, backend=None, err=None):
        s = self._st
        if levels is not None:
            self.meter_them.set_level(levels.get("them", 0) * 25)
            self.meter_me.set_level(levels.get("me", 0) * 25)
        if backend is not None:
            self.chip.setText(backend)
        if err is not None:
            s["err"] = err
            self.error.setText(f"⚠ {err}" if err else "")
        if msg is not None:
            s["msg"] = msg
        self.status.setText(t("status_muted") if s["muted"] else s["msg"])
        if busy is not None and busy != s["busy"]:
            s["busy"] = busy
            self.progress.set_active(busy)
            self.meta.setText(t("thinking") + "…" if busy else t("updated", time=f"{datetime.now():%H:%M:%S}"))
        if s["err"]:
            self.pill.set_state("#f87171", t("pill_error"), False)
        elif s["muted"]:
            self.pill.set_state("#f87171", t("pill_muted"), False)
        elif s["busy"]:
            self.pill.set_state("#fbbf24", t("pill_thinking"), True)
        elif s["msg"] == t("status_listening"):
            self.pill.set_state("#34d399", t("pill_listening"), True)
        else:
            self.pill.set_state("#8a93a6", t("pill_starting"), False)

    def add_line(self, ts, source, text):
        color, who = ("#8fb3ff", t("who_them")) if source == "them" else ("#7ee2a8", t("who_me"))
        sb = self.transcript.verticalScrollBar()
        at_end = sb.value() >= sb.maximum() - 24  # do not jump while the user scrolls up
        self.transcript.append(f'<p style="margin:0 0 5px 0"><span style="color:#5a6276">{ts}</span>&nbsp;&nbsp;'
                               f'<span style="color:{color};font-weight:600">{who}</span>&nbsp;&nbsp;'
                               f'<span style="color:#e3e6ec">{_esc(text)}</span></p>')
        if at_end:
            sb.setValue(sb.maximum())

    # hint feed
    def start_message(self, kind, text, jump=False, pending=False):
        """New feed message; jump — from a button: show it even if the feed is scrolled up;
        pending — the model is still thinking (typing dots until the first update)."""
        if jump:
            self._show_tab(0)
        return self.feed.add(kind, text, jump, pending)

    def update_message(self, mid, kind=None, text=None):
        self.feed.update(mid, kind, text)

    def clear(self):
        self.transcript.clear()
        self.feed.clear()
        self.btn_jump.hide()
        self.meta.setText("")


class MessageCard(QFrame):
    """One feed message: coloured accent bar, kind chip, time, markdown body, typing dots while pending."""

    def __init__(self, fs):
        super().__init__()
        self.setObjectName("msg")
        self.accent = QColor("#a99dff")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(15, 0, 12, 0)  # the accent bar is painted in the first 3 px — see paintEvent
        outer.setSpacing(0)
        col = QVBoxLayout()
        col.setContentsMargins(0, 11, 0, 12)
        col.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title = QLabel()
        f = self.title.font()
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
        self.title.setFont(f)
        head.addWidget(self.title)
        self.dots = TypingDots()
        self.dots.hide()
        head.addWidget(self.dots)
        head.addStretch(1)
        head.addWidget(_prop(QLabel(datetime.now().strftime("%H:%M:%S")), role="meta"))
        col.addLayout(head)
        self.body = QLabel()
        self.body.setTextFormat(Qt.TextFormat.MarkdownText)
        self.body.setWordWrap(True)
        self.body.setOpenExternalLinks(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                          | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.body.setStyleSheet(f"color: #e9ebef; font-size: {fs + 1}px;")
        col.addWidget(self.body)
        outer.addLayout(col, 1)

    def set_kind(self, kind):
        key, color = KINDS[kind]
        c = QColor(color)
        self.title.setText(t(key))
        self.title.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 700; padding: 2px 8px;"
                                 f"background: rgba({c.red()},{c.green()},{c.blue()},30); border-radius: 8px;")
        self.accent = c
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)  # background and border from the style sheet
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.setClipPath(shape)  # the bar follows the card's rounded corners
        g = QLinearGradient(0, 0, 0, self.height())
        fade = QColor(self.accent)
        fade.setAlpha(70)
        g.setColorAt(0, self.accent)
        g.setColorAt(1, fade)
        p.fillRect(QRectF(0, 0, 3.5, self.height()), g)

    def set_text(self, text, pending):
        self.body.setText(text)
        self.dots.setVisible(pending)

    def enterEvent(self, e):
        self._hover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover(False)
        super().leaveEvent(e)

    def _hover(self, on):
        self.setProperty("hover", on)
        self.style().unpolish(self)
        self.style().polish(self)


class Feed(QScrollArea):
    """Chat-like message feed: new ones slide up and fade in at the bottom; auto-scroll while you are at
    the bottom, paused while you scroll up."""
    stick_changed = pyqtSignal(bool)

    def __init__(self, fs):
        super().__init__()
        self.fs = fs
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("feed")
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(0, 0, 8, 0)
        self.lay.setSpacing(10)

        self.empty = QWidget()  # empty state: logo, title, how it works
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(4, 6, 4, 6)
        ev.setSpacing(8)
        top = QHBoxLayout()
        logo = QLabel()
        dpr = self.devicePixelRatioF() or 1.0
        pm = make_pixmap(int(32 * dpr))
        pm.setDevicePixelRatio(dpr)
        logo.setPixmap(pm)
        top.addWidget(logo)
        title = QLabel(t("empty_title"))
        title.setStyleSheet("color: #e9ebef; font-size: 14px; font-weight: 600;")
        top.addWidget(title)
        top.addStretch(1)
        ev.addLayout(top)
        self.placeholder = QLabel("")
        self.placeholder.setWordWrap(True)
        self.placeholder.setStyleSheet("color: #8a93a6; font-size: 12px;")
        ev.addWidget(self.placeholder)
        self.lay.addWidget(self.empty)
        self.lay.addStretch(1)
        self.setWidget(inner)
        self.viewport().setAutoFillBackground(False)

        self.msgs = {}  # mid -> (wrapper, title label, body label)
        self.cards = {}
        self._next = 0
        self.stick = True
        self._gliding = False
        sb = self.verticalScrollBar()
        sb.rangeChanged.connect(self._on_range)
        sb.valueChanged.connect(self._on_value)

    def _on_range(self, lo, hi):
        if self.stick and self.msgs:  # an empty feed with instructions is shown from the top
            self.verticalScrollBar().setValue(hi)

    def _on_value(self, v):
        if self._gliding:  # our own smooth scroll — its in-between positions are not the user scrolling up
            return
        stick = v >= self.verticalScrollBar().maximum() - 24
        if stick != self.stick:
            self.stick = stick
            self.stick_changed.emit(stick)

    def scroll_to_end(self):
        self.stick = True
        self.stick_changed.emit(True)
        sb = self.verticalScrollBar()
        self._gliding = True
        anim = QVariantAnimation(self, startValue=sb.value(), endValue=sb.maximum(), duration=320,
                                 easingCurve=QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: sb.setValue(min(int(v), sb.maximum())))

        def done():
            self._gliding = False
            sb.setValue(sb.maximum())

        anim.finished.connect(done)
        QTimer.singleShot(0, lambda: anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped))

    def add(self, kind, text, jump=False, pending=False):
        card = MessageCard(self.fs)
        card.set_kind(kind)
        card.set_text(text, pending)
        wrap = QWidget()  # the wrapper's top margin animates — the card slides up into place
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 18, 0, 0)
        wl.addWidget(card)
        if self.empty.isVisible():
            self.empty.hide()
        self.lay.insertWidget(self.lay.count() - 1, wrap)
        fade_in(wrap, 340, on_step=lambda v: wl.setContentsMargins(0, int(18 * (1 - v)), 0, 0))
        mid = self._next
        self._next += 1
        self.msgs[mid] = (wrap, card.title, card.body)
        self.cards[mid] = card
        if jump:
            self.scroll_to_end()
        return mid

    def update(self, mid, kind=None, text=None):
        card = self.cards.get(mid)
        if not card:
            return
        if kind is not None:
            card.set_kind(kind)
        if text is not None:
            card.set_text(text, pending=False)

    def clear(self):
        for wrap, _, _ in self.msgs.values():
            wrap.deleteLater()
        self.msgs.clear()
        self.cards.clear()
        self.empty.show()
        fade_in(self.empty, 260)
        self.stick = True


def _short(name):
    # "Vendor Device - Channel (Vendor Virtual Audio Device) [Loopback]" -> "Vendor Device - Channel";
    # names like "Headphones (Some Headset)" keep the part in brackets — that is the actual device
    name = name.replace(" [Loopback]", "")
    if " (" in name and name.endswith(")") and not name.startswith(("Наушники", "Динамики", "Микрофон", "Speakers",
                                                                        "Headphones", "Microphone")):
        name = name[:name.index(" (")]
    return name


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
