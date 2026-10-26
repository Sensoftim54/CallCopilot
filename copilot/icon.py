"""The app icon is drawn in code — no external files. Small sizes get a simpler, bolder drawing so they stay crisp."""
import struct

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPixmap

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def make_pixmap(size=256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    small = size <= 24
    pad = size * (0.0 if small else 8 / 256)  # small icons use the whole square — every pixel counts
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#9a8cff"))
    g.setColorAt(1, QColor("#5a46e0"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    side = size - 2 * pad
    p.drawRoundedRect(QRectF(pad, pad, side, side), side * 0.23, side * 0.23)

    # sound wave: five thin bars, or three bold ones on small sizes
    p.setBrush(QColor("white"))
    if small:
        heights, w, gap = [0.36, 0.62, 0.36], 0.17 * size, 0.1 * size
    else:
        heights, w, gap = [56 / 256, 104 / 256, 150 / 256, 104 / 256, 56 / 256], 22 * size / 256, 14 * size / 256
    x = (size - (len(heights) * w + (len(heights) - 1) * gap)) / 2
    for h in heights:
        h *= size
        p.drawRoundedRect(QRectF(x, (size - h) / 2, w, h), w / 2, w / 2)
        x += w + gap
    p.end()
    return pm


def make_icon() -> QIcon:
    icon = QIcon()
    for sz in SIZES:
        icon.addPixmap(make_pixmap(sz))
    return icon


def save_ico(path):
    """A real multi-size .ico (PNG entries 16…256 px), so Windows never has to blur one big picture down."""
    images = []
    for sz in SIZES:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        make_pixmap(sz).save(buf, "PNG")
        images.append((sz, bytes(data)))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for sz, png in images:
        entries += struct.pack("<BBBBHHII", sz % 256, sz % 256, 0, 0, 1, 32, len(png), offset + len(blobs))
        blobs += png
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(images)) + entries + blobs)


if __name__ == "__main__":  # python -m copilot.icon assets/icon.ico
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    out = sys.argv[1] if len(sys.argv) > 1 else "icon.ico"
    save_ico(out)
    print("saved", out)
