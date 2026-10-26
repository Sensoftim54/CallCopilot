"""Custom-painted, animated widgets: buttons with hover / press / ripple, segmented tabs with a sliding
indicator, a status pill with a pulse, a segmented level meter, a shimmering busy bar and typing dots."""
import math
import time

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPointF, QRectF, QSize, Qt, QTimer, \
    QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QPushButton, QToolTip, QWidget

ACCENT = QColor("#7c6cff")
ACCENT_2 = QColor("#5b7cff")
TEXT = QColor("#eef0f4")
MUTED = QColor("#8a93a6")


def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


class Tween:
    """An animated float: tween.to(x) glides from the current value to x and repaints the owner."""

    def __init__(self, owner, value=0.0, ms=170, curve=QEasingCurve.Type.OutCubic, on_change=None):
        self.value = float(value)
        self.on_change = on_change or owner.update
        self.anim = QVariantAnimation(owner)
        self.anim.setDuration(ms)
        self.anim.setEasingCurve(curve)
        self.anim.valueChanged.connect(self._set)

    def _set(self, v):
        self.value = float(v)
        self.on_change()

    def to(self, target):
        target = float(target)
        if abs(self.value - target) < 1e-4 and self.anim.state() != QAbstractAnimation.State.Running:
            return
        self.anim.stop()
        self.anim.setStartValue(self.value)
        self.anim.setEndValue(target)
        self.anim.start()


def fade_in(widget, ms=220, on_step=None):
    """Fade a widget in; the opacity effect is removed afterwards so it costs nothing later.
    A new fade on the same widget stops the previous one — its effect is replaced and would be gone."""
    old = getattr(widget, "_fade_anim", None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:  # already deleted
            pass
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    widget._fade_anim = anim

    def step(v):
        try:
            eff.setOpacity(float(v))
        except RuntimeError:  # the widget (and its effect) was deleted mid-animation
            return
        if on_step:
            on_step(float(v))

    def done():
        try:
            if widget.graphicsEffect() is eff:
                widget.setGraphicsEffect(None)
            widget._fade_anim = None
        except RuntimeError:
            pass

    anim.valueChanged.connect(step)
    anim.finished.connect(done)
    anim.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


class Button(QPushButton):
    """A button painted by hand: hover glide, press squeeze, click ripple, animated checked state."""

    PALETTE = {
        "secondary": dict(bg="#161a23", bg_h="#1f2431", line="#252b39", line_h="#343d51", fg="#d9dde6", fg_h="#ffffff"),
        "ghost": dict(bg="#00161a23", bg_h="#1c212c", line="#00000000", line_h="#00000000", fg="#8a93a6", fg_h="#eef0f4"),
        "toggle": dict(bg="#161a23", bg_h="#1f2431", line="#252b39", line_h="#343d51", fg="#c9cedb", fg_h="#ffffff",
                       bg_c="#211c44", line_c="#7c6cff", fg_c="#ebe7ff"),
        "mute": dict(bg="#161a23", bg_h="#1f2431", line="#252b39", line_h="#343d51", fg="#c9cedb", fg_h="#ffffff",
                     bg_c="#3a161c", line_c="#f87171", fg_c="#ffdcdc"),
    }

    def __init__(self, text="", kind="secondary", checkable=False, tip=None, parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(34)
        if tip:
            self.setToolTip(tip)
        self.hover = Tween(self, ms=180)
        self.press = Tween(self, ms=120)
        self.check = Tween(self, ms=240)
        self.toggled.connect(lambda on: self.check.to(1.0 if on else 0.0))
        self._ripples = []
        self._rt = QTimer(self, interval=16)
        self._rt.timeout.connect(self._tick)

    def sizeHint(self):
        return QSize(max(34, self.fontMetrics().horizontalAdvance(self.text()) + 30), 34)

    def minimumSizeHint(self):
        return self.sizeHint()

    def enterEvent(self, e):
        self.hover.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hover.to(0.0)
        self.press.to(0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._ripples.append((e.position(), time.monotonic()))
            self._rt.start()
            self.press.to(1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.press.to(0.0)
        super().mouseReleaseEvent(e)

    def _tick(self):
        now = time.monotonic()
        self._ripples = [(p, t0) for p, t0 in self._ripples if now - t0 < 0.6]
        if not self._ripples:
            self._rt.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        s = 1.0 - 0.04 * self.press.value  # squeeze while pressed
        p.translate(r.center())
        p.scale(s, s)
        p.translate(-r.center())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        h, c = self.hover.value, self.check.value

        if self.kind == "primary":
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, mix("#7c6cff", "#9488ff", h))
            g.setColorAt(1, mix("#5b6fff", "#6f86ff", h))
            p.fillPath(path, g)
            shine = QLinearGradient(r.topLeft(), r.bottomLeft())  # soft top highlight
            shine.setColorAt(0, QColor(255, 255, 255, int(46 + 30 * h)))
            shine.setColorAt(0.5, QColor(255, 255, 255, 0))
            p.setPen(QPen(shine, 1))
            p.drawPath(path)
            fg = QColor("#ffffff")
        else:
            pal = self.PALETTE.get(self.kind, self.PALETTE["secondary"])
            bg, line, fg = mix(pal["bg"], pal["bg_h"], h), mix(pal["line"], pal["line_h"], h), mix(pal["fg"], pal["fg_h"], h)
            if "bg_c" in pal:
                bg = mix(bg, mix(pal["bg_c"], QColor(pal["bg_c"]).lighter(125), h), c)
                line, fg = mix(line, pal["line_c"], c), mix(fg, pal["fg_c"], c)
            p.fillPath(path, bg)
            if line.alpha():
                p.setPen(QPen(line, 1))
                p.drawPath(path)

        if self._ripples:  # click ripple from the press point, clipped to the button
            p.save()
            p.setClipPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            now = time.monotonic()
            reach = math.hypot(r.width(), r.height())
            for pos, t0 in self._ripples:
                a = min(1.0, (now - t0) / 0.6)
                rad = reach * (1 - (1 - a) ** 3)
                p.setBrush(QColor(255, 255, 255, int(60 * (1 - a))))
                p.drawEllipse(pos, rad, rad)
            p.restore()

        if not self.isEnabled():
            fg.setAlpha(110)
        f = QFont(self.font())
        if self.kind == "primary":
            f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())


class Segmented(QWidget):
    """Segmented tab control with a sliding, springy indicator."""
    changed = pyqtSignal(int)

    def __init__(self, items, tips=None, parent=None):
        super().__init__(parent)
        self.items, self.tips = list(items), list(tips or [None] * len(items))
        self.idx, self.hover_i = 0, -1
        self.ind = Tween(self, ms=360, curve=QEasingCurve.Type.OutBack)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)

    def _rects(self):
        fm, x, out = self.fontMetrics(), 4.0, []
        for text in self.items:
            w = fm.horizontalAdvance(text) + 30
            out.append(QRectF(x, 4, w, self.height() - 8))
            x += w
        return out

    def sizeHint(self):
        rs = self._rects()
        return QSize(int(rs[-1].right() + 4), 38)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_index(self, i, emit=False):
        self.idx = i
        self.ind.to(i)
        if emit:
            self.changed.emit(i)
        self.update()

    def _at(self, pos):
        return next((i for i, r in enumerate(self._rects()) if r.contains(pos)), -1)

    def mouseMoveEvent(self, e):
        i = self._at(e.position())
        if i != self.hover_i:
            self.hover_i = i
            self.update()

    def leaveEvent(self, e):
        self.hover_i = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._at(e.position())
        if i >= 0 and i != self.idx:
            self.set_index(i, emit=True)

    def event(self, e):
        if e.type() == QEvent.Type.ToolTip:
            i = self._at(QPointF(e.pos()))
            if i >= 0 and self.tips[i]:
                QToolTip.showText(e.globalPos(), self.tips[i], self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor("#1f2430"), 1))
        p.setBrush(QColor("#11141b"))
        p.drawRoundedRect(track, 12, 12)
        rs = self._rects()
        v = max(0.0, min(len(rs) - 1.0, self.ind.value))
        a, b = rs[int(math.floor(v))], rs[int(math.ceil(v))]
        f = v - math.floor(v)
        ind = QRectF(a.x() + (b.x() - a.x()) * f, a.y(), a.width() + (b.width() - a.width()) * f, a.height())
        g = QLinearGradient(ind.topLeft(), ind.bottomLeft())
        g.setColorAt(0, QColor("#2a3042"))
        g.setColorAt(1, QColor("#222738"))
        p.setPen(QPen(QColor("#343c52"), 1))
        p.setBrush(g)
        p.drawRoundedRect(ind, 9, 9)
        for i, (r, text) in enumerate(zip(rs, self.items)):
            near = max(0.0, 1.0 - abs(i - v))
            col = mix(MUTED, TEXT, max(near, 0.55 if i == self.hover_i else 0.0))
            p.setPen(col)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


class StatusPill(QWidget):
    """Header pill: a coloured dot with a soft pulse ring and a short state word."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.color, self.text, self.pulse_on = QColor("#6f7889"), "", False
        self.phase = 0.0
        self.pulse = QVariantAnimation(self)
        self.pulse.setStartValue(0.0)
        self.pulse.setEndValue(1.0)
        self.pulse.setDuration(1600)
        self.pulse.setLoopCount(-1)
        self.pulse.valueChanged.connect(self._phase)
        self.color_t = Tween(self, ms=300)
        self._from = self._to = self.color
        self.setFixedHeight(26)

    def _phase(self, v):
        self.phase = float(v)
        self.update()

    def set_state(self, color, text, pulse):
        color = QColor(color)
        if color != self._to:
            self._from, self._to = self._shown(), color
            self.color_t.value = 0.0
            self.color_t.to(1.0)
        if text != self.text:
            self.text = text
            self.updateGeometry()
        if pulse and not self.pulse_on:
            self.pulse.start()
        elif not pulse and self.pulse_on:
            self.pulse.stop()
            self.phase = 0.0
        self.pulse_on = pulse
        self.update()

    def _shown(self):
        return mix(self._from, self._to, self.color_t.value)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text) + 36, 26)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._shown()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QColor(c)
        bg.setAlpha(30)
        line = QColor(c)
        line.setAlpha(70)
        p.setPen(QPen(line, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        center = QPointF(14, r.center().y())
        if self.pulse_on:  # expanding, fading ring
            ring = QColor(c)
            ring.setAlpha(int(150 * (1 - self.phase)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(ring)
            rad = 3.5 + 6 * self.phase
            p.drawEllipse(center, rad, rad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(center, 3.5, 3.5)
        p.setPen(mix(c, TEXT, 0.55))
        p.drawText(QRectF(24, 0, r.width() - 28, r.height()), Qt.AlignmentFlag.AlignVCenter, self.text)


class LevelMeter(QWidget):
    """Segmented level meter: fast attack, smooth release, a short peak hold."""

    def __init__(self, segments=14, parent=None):
        super().__init__(parent)
        self.n = segments
        self.target = self.shown = self.peak = 0.0
        self.peak_t = 0.0
        self.timer = QTimer(self, interval=33)
        self.timer.timeout.connect(self._tick)
        self.setFixedSize(96, 12)

    def set_level(self, v):
        self.target = max(0.0, min(1.0, v))
        if not self.timer.isActive() and (self.target > 0 or self.shown > 0):
            self.timer.start()

    def _tick(self):
        if self.target > self.shown:
            self.shown += (self.target - self.shown) * 0.55
        else:
            self.shown = max(self.target, self.shown - max(0.012, (self.shown - self.target) * 0.16))
        now = time.monotonic()
        if self.shown >= self.peak:
            self.peak, self.peak_t = self.shown, now
        elif now - self.peak_t > 0.7:
            self.peak = max(self.shown, self.peak - 0.03)
        if self.target == 0 and self.shown < 0.004 and self.peak < 0.004:
            self.shown = self.peak = 0.0
            self.timer.stop()
        self.update()

    @staticmethod
    def _color(x):
        return mix("#34d399", "#fbbf24", (x - 0.55) / 0.25) if x < 0.8 else mix("#fbbf24", "#f87171", (x - 0.8) / 0.2)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 2.0
        w = (self.width() - gap * (self.n - 1)) / self.n
        lit = self.shown * self.n
        peak_i = int(self.peak * self.n - 0.001)
        for i in range(self.n):
            x = i * (w + gap)
            r = QRectF(x, 2, w, self.height() - 4)
            if i < lit:
                col = self._color(i / self.n)
                if i + 1 > lit:  # partially lit segment
                    col.setAlpha(int(255 * max(0.25, lit - i)))
            elif i == peak_i and self.peak > 0.05:
                col = self._color(i / self.n)
                col.setAlpha(140)
            else:
                col = QColor("#1e2330")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(r, 1.5, 1.5)


class ShimmerBar(QWidget):
    """Thin bar with a light sweeping across while the model thinks; fades in and out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(3)
        self.phase = 0.0
        self.alpha = Tween(self, ms=260)
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self._tick)
        self.active = False

    def set_active(self, on):
        self.active = on
        self.alpha.to(1.0 if on else 0.0)
        if on:
            self.timer.start()

    def _tick(self):
        self.phase = (self.phase + 0.012) % 1.0
        if not self.active and self.alpha.value < 0.01:
            self.timer.stop()
        self.update()

    def paintEvent(self, _):
        if self.alpha.value < 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.alpha.value)
        r = QRectF(self.rect())
        base = QColor(ACCENT)
        base.setAlpha(45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(r, 1.5, 1.5)
        span = r.width() * 0.35
        x = -span + (r.width() + span) * self.phase
        g = QLinearGradient(x, 0, x + span, 0)
        g.setColorAt(0.0, QColor(124, 108, 255, 0))
        g.setColorAt(0.5, QColor(160, 150, 255, 255))
        g.setColorAt(1.0, QColor(91, 124, 255, 0))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x, 0, span, r.height()), 1.5, 1.5)


class TypingDots(QWidget):
    """Three bouncing dots — the model is writing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 16)
        self.t0 = time.monotonic()
        self.timer = QTimer(self, interval=16)
        self.timer.timeout.connect(self.update)

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        t = (time.monotonic() - self.t0) * 6.0
        for i in range(3):
            k = max(0.0, math.sin(t - i * 0.7))
            c = mix("#5d6580", "#b9b0ff", k)
            p.setBrush(c)
            p.drawEllipse(QPointF(6 + i * 11, 10 - 4 * k), 3.0, 3.0)
