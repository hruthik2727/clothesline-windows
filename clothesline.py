"""
Clothesline for Windows - a clothesline for your screenshots.
 
An independent app inspired by Tendedero for macOS by Alejandro Bujan
(https://tendedero.app). No code is shared; it is not affiliated with or endorsed by it.
 
A glass bar glides down from the top edge of the screen. New screenshots (from the
Screenshots folder or the clipboard) are pegged onto the line.
 
  Click          copy image to clipboard (ripple + "Copied!")
  Double-click   open in the default photo viewer
  Drag           drop into Slack, Discord, browsers, Explorer ...
  Hover -> X     let it go (fade out; the file on disk is never deleted)
  Right-click    menu (copy / open / show in folder / remove)
  Ctrl+Alt+T or Win+Shift+Y   show / hide the line
"""
import sys, os, time, json, random, queue, hashlib, threading, subprocess, tempfile, ctypes
from datetime import datetime
 
from PySide6.QtCore import (Qt, QObject, QPoint, QPointF, QRect, QRectF, QSize, QTimer, QUrl,
                            QMimeData, QEasingCurve, QPropertyAnimation, QFileSystemWatcher,
                            QAbstractNativeEventFilter, QLockFile, Property, Signal,
                            QStandardPaths)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor, QDrag, QFont, QGuiApplication, QIcon,
                           QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget
 
# ----------------------------------------------------------------------------- layout
CARD_W, CARD_H = 176, 116          # visual size of a hung screenshot
THUMB_W, THUMB_H = CARD_W - 10, CARD_H - 10
PADX, PADT, PADB = 30, 18, 24      # transparent padding around a card (room for swing/peg)
STEP = CARD_W + 16                 # distance between card centres
SH = 30                            # shadow margin on the left/right of the window
PH = 172                           # visible panel height
WIN_H = PH + 30
CARD_Y = 8                         # card widget y inside the window
PANEL_MIN_W = 400
DPR = 2.0                          # thumbnail pixel density
EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
XC_DX = CARD_W / 2 - 16            # close-button centre, relative to card centre
XC_DY = 16
KEEP_R = QRectF(CARD_W / 2 - 76, CARD_H - 36, 70, 26)   # button rects, card-local coords
DEL_R = QRectF(CARD_W / 2 + 6, CARD_H - 36, 70, 26)
 
IS_WIN = sys.platform == "win32"
 
 
def curve(kind, overshoot=None):
    c = QEasingCurve(kind)
    if overshoot is not None:
        c.setOvershoot(overshoot)
    return c
 
 
def clamp01(v):
    return max(0.0, min(1.0, v))
 
 
def img_hash(img):
    small = img.scaled(32, 32, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    small = small.convertToFormat(QImage.Format_RGB888)
    return hashlib.md5(bytes(small.constBits())).hexdigest()
 
 
def data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "Clothesline")
    os.makedirs(d, exist_ok=True)
    return d
 
 
def clip_dir():
    d = os.path.join(tempfile.gettempdir(), "Clothesline")
    os.makedirs(d, exist_ok=True)
    return d
 
 
def screenshot_dirs():
    pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    cands = [os.path.join(pics, "Screenshots")]
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(env):
            cands.append(os.path.join(os.environ[env], "Pictures", "Screenshots"))
    found = [d for d in dict.fromkeys(cands) if os.path.isdir(d)]
    if not found:
        os.makedirs(cands[0], exist_ok=True)
        found = [cands[0]]
    return found
 
 
def move_to_recycle_bin(path):
    """Send a file to the Windows Recycle Bin (recoverable). Returns True on success."""
    if not IS_WIN:
        return False
    import ctypes.wintypes as wt
 
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR),
                    ("pTo", wt.LPCWSTR), ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wt.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wt.LPCWSTR)]
    op = SHFILEOPSTRUCTW()
    op.hwnd, op.wFunc = None, 3                       # FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"           # list must end with a double null
    op.pTo = None
    op.fFlags = 0x40 | 0x10 | 0x04 | 0x400            # allow undo, no prompts, silent, no error UI
    try:
        return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 \
            and not op.fAnyOperationsAborted
    except Exception:
        return False
 
 
def make_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#E6D2A8"), 3, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(4, 14, 60, 14)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#5B8CFF"))
    p.drawRoundedRect(QRectF(12, 20, 40, 32), 7, 7)
    p.setBrush(QColor("#F6D8A0"))
    p.drawRoundedRect(QRectF(27, 6, 10, 22), 3, 3)
    p.end()
    return QIcon(pm)
 
 
# ----------------------------------------------------------------------------- card
def _prop(name):
    attr = "_" + name
    return Property(float, lambda s: getattr(s, attr), lambda s, v: s._set(name, v))
 
 
class ThumbCard(QWidget):
    """One screenshot hanging on the line. Pure painter - the shelf handles the mouse."""
 
    def __init__(self, shelf, path, pixmap, temp):
        super().__init__(shelf)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.resize(CARD_W + 2 * PADX, PADT + CARD_H + PADB)
        self.shelf, self.path, self.pm, self.temp = shelf, path, pixmap, temp
        self._appear, self._drop, self._swing = 0.0, -46.0, 0.0
        self._hover, self._copied, self._slot = 0.0, 1.0, 0.0
        self.x_hover = self.dragging = self.removing = self.confirming = self.hovering = False
        self._confirm = 0.0
        self.btn_hover = None
        self.born = time.time()
        self._ctimer = QTimer(self, singleShot=True, interval=5000)
        self._ctimer.timeout.connect(self.cancel_confirm)
        self.rip = QPointF(0, CARD_H / 2)
        self._anims = {}
 
    # animated properties
    appear, drop, swing = _prop("appear"), _prop("drop"), _prop("swing")
    hover, copied, confirm = _prop("hover"), _prop("copied"), _prop("confirm")
    slot = Property(float, lambda s: s._slot, lambda s, v: s._set_slot(v))
 
    def _set(self, name, v):
        setattr(self, "_" + name, v)
        self.update()
 
    def _set_slot(self, v):
        self._slot = v
        self.place()
 
    def place(self):
        self.move(int(round(self.shelf.width() / 2 + self._slot - self.width() / 2)), CARD_Y)
 
    def run(self, name, start, end, ms, easing=None, finished=None):
        old = self._anims.get(name)
        if old:
            old.stop()
        a = QPropertyAnimation(self, name.encode())
        a.setDuration(ms)
        a.setStartValue(float(getattr(self, "_" + name) if start is None else start))
        a.setEndValue(float(end))
        a.setEasingCurve(easing or curve(QEasingCurve.OutCubic))
        if finished:
            a.finished.connect(finished)
        self._anims[name] = a
        a.start()
 
    # entrance: fade + drop with a bounce + pendulum settle
    def play_in(self):
        self.run("appear", 0, 1, 380, curve(QEasingCurve.OutCubic))
        self.run("drop", -46, 0, 620, curve(QEasingCurve.OutBack, 1.6))
        self.run("swing", random.choice((-1, 1)) * 13, 0, 1500, curve(QEasingCurve.OutElastic))
 
    def set_hover(self, on):
        self.hovering = on
        self.run("hover", None, 1.0 if on else 0.0, 170)
 
    def ask_confirm(self):
        self.confirming = True
        self.run("confirm", None, 1.0, 200)
        self._ctimer.start()                            # gives up (and keeps the file) after 5 s
 
    def cancel_confirm(self):
        if self.confirming:
            self.confirming = False
            self._ctimer.stop()
            self.run("confirm", None, 0.0, 170)
 
    def button_at(self, pos):
        r = self.visual_rect()
        lp = QPointF(pos.x() - r.x(), pos.y() - r.y())
        if self.confirming:
            return "cancel" if KEEP_R.contains(lp) else "confirm" if DEL_R.contains(lp) else None
        if not self.hovering:
            return None
        if KEEP_R.contains(lp):
            return "keep"
        if DEL_R.contains(lp):
            return "delete"
        if (lp.x() - (CARD_W / 2 + XC_DX)) ** 2 + (lp.y() - XC_DY) ** 2 <= 14 ** 2:
            return "x"
        return None
 
    @staticmethod
    def _pill(p, r, text, color, hot):
        r = QRectF(r).translated(-CARD_W / 2, 0)
        c = QColor(color)
        if hot:
            c.setAlpha(min(255, c.alpha() + 70))
        p.setPen(QPen(QColor(255, 255, 255, 150 if hot else 70), 1))
        p.setBrush(c)
        p.drawRoundedRect(r, 13, 13)
        p.setPen(Qt.white)
        p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        p.drawText(r, Qt.AlignCenter, text)
 
    def flash(self, pos):
        self.rip = QPointF(pos.x() - (self.x() + self.width() / 2), pos.y() - (self.y() + PADT))
        self.run("copied", 0, 1, 1000, curve(QEasingCurve.Linear))
 
    def vis_center_of_x(self):
        return QPointF(self.x() + self.width() / 2 + XC_DX, self.y() + PADT + XC_DY)
 
    def x_hit(self, pos):
        c = self.vis_center_of_x()
        return (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= 14 ** 2
 
    def visual_rect(self):
        return QRect(self.x() + PADX, self.y() + PADT, CARD_W, CARD_H)
 
    # ---- painting
    def paintEvent(self, ev):
        a = clamp01(self._appear)
        if a <= 0.003:
            return
        base = a * (0.35 if self.dragging else 1.0)
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform |
                         QPainter.TextAntialiasing)
        p.setOpacity(base)
        p.translate(self.width() / 2, PADT + self._drop)
        p.rotate(self._swing)
        sc = (0.88 + 0.12 * a) * (1 + 0.035 * self._hover)
        p.scale(sc, sc)
        body = QRectF(-CARD_W / 2, 0, CARD_W, CARD_H)
 
        # soft shadow
        p.setPen(Qt.NoPen)
        for i in range(10, 0, -1):
            sp = QPainterPath()
            sp.addRoundedRect(body.adjusted(-i, -i + 5, i, i + 5), 16 + i, 16 + i)
            p.fillPath(sp, QColor(0, 0, 0, 7))
 
        # glass body + thumbnail
        path = QPainterPath()
        path.addRoundedRect(body, 16, 16)
        p.fillPath(path, QColor(255, 255, 255, 46))
        inner = body.adjusted(5, 5, -5, -5)
        ipath = QPainterPath()
        ipath.addRoundedRect(inner, 12, 12)
        p.save()
        p.setClipPath(ipath)
        p.drawPixmap(inner, self.pm, QRectF(self.pm.rect()))
        g = QLinearGradient(inner.topLeft(), inner.bottomRight())
        g.setColorAt(0.0, QColor(255, 255, 255, 60))
        g.setColorAt(0.35, QColor(255, 255, 255, 14))
        g.setColorAt(0.36, QColor(255, 255, 255, 0))
        p.fillRect(inner, g)
 
        # hover buttons: [Keep] [Delete]
        ch = self._confirm
        hv = self._hover * (1 - ch)
        if hv > 0.01:
            sc_ = QLinearGradient(0, CARD_H - 56, 0, CARD_H)
            sc_.setColorAt(0, QColor(0, 0, 0, 0)); sc_.setColorAt(1, QColor(0, 0, 0, 160))
            p.setOpacity(base * hv)
            p.fillRect(QRectF(-CARD_W / 2, CARD_H - 56, CARD_W, 56), sc_)
            self._pill(p, KEEP_R, "Keep", QColor(255, 255, 255, 56), self.btn_hover == "keep")
            self._pill(p, DEL_R, "Delete", QColor(235, 77, 75, 200), self.btn_hover == "delete")
        # inline confirmation
        if ch > 0.01:
            p.setOpacity(base * ch)
            p.fillRect(inner, QColor(12, 12, 18, 210))
            p.setPen(Qt.white)
            p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
            p.drawText(QRectF(-CARD_W / 2, 18, CARD_W, 24), Qt.AlignCenter, "Move to Recycle Bin?")
            p.setPen(QColor(255, 255, 255, 170))
            p.setFont(QFont("Segoe UI", 8))
            p.drawText(QRectF(-CARD_W / 2, 42, CARD_W, 18), Qt.AlignCenter, "You can restore it from there")
            self._pill(p, KEEP_R, "Cancel", QColor(255, 255, 255, 56), self.btn_hover == "cancel")
            self._pill(p, DEL_R, "Recycle", QColor(235, 77, 75, 220), self.btn_hover == "confirm")
 
        # copy feedback: ripple + check badge
        t = self._copied
        if t < 1.0:
            e = QEasingCurve(QEasingCurve.OutCubic).valueForProgress(t)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(120 * (1 - t))))
            r = e * CARD_W * 1.1
            p.drawEllipse(self.rip, r, r)
            fade = clamp01(t / 0.12) * clamp01((1 - t) / 0.28)
            pop = QEasingCurve(QEasingCurve.OutBack).valueForProgress(clamp01(t / 0.3))
            p.save()
            p.setOpacity(base * fade)
            p.translate(0, CARD_H / 2 - 26)
            p.scale(pop, pop)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(46, 204, 113))
            p.drawEllipse(QPointF(0, 0), 20, 20)
            p.setPen(QPen(Qt.white, 3.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            chk = QPainterPath(QPointF(-8, 0))
            chk.lineTo(-2, 6)
            chk.lineTo(9, -6)
            p.drawPath(chk)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(QRectF(-31, 26, 62, 20), 10, 10)
            p.setPen(Qt.white)
            p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
            p.drawText(QRectF(-31, 26, 62, 20), Qt.AlignCenter, "Copied!")
            p.restore()
        p.restore()
 
        # glass border
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, int(80 + 100 * self._hover)), 1.2))
        p.drawPath(path)
 
        # clothes peg
        peg = QRectF(-7, -16, 14, 34)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(peg.translated(1.5, 2), 4, 4)
        pg = QLinearGradient(peg.topLeft(), peg.topRight())
        pg.setColorAt(0, QColor("#E9BE7C"))
        pg.setColorAt(0.5, QColor("#F6D8A0"))
        pg.setColorAt(1, QColor("#C99352"))
        p.setBrush(pg)
        p.setPen(QPen(QColor(120, 80, 30, 150), 0.8))
        p.drawRoundedRect(peg, 4, 4)
        p.setPen(QPen(QColor(110, 70, 25, 170), 1.2))
        p.drawLine(QPointF(0, 5), QPointF(0, 17))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#9AA0A6"))
        p.drawEllipse(QPointF(0, 1), 3.2, 3.2)
 
        # hover close button
        if self._hover > 0.01 and self._confirm < 0.05:
            p.setOpacity(base * self._hover)
            c = QPointF(XC_DX, XC_DY)
            p.setPen(QPen(QColor(255, 255, 255, 120), 1))
            p.setBrush(QColor(235, 77, 75, 235) if self.x_hover else QColor(20, 20, 26, 190))
            p.drawEllipse(c, 11, 11)
            p.setPen(QPen(Qt.white, 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(c + QPointF(-3.8, -3.8), c + QPointF(3.8, 3.8))
            p.drawLine(c + QPointF(-3.8, 3.8), c + QPointF(3.8, -3.8))
        p.end()
 
 
# ----------------------------------------------------------------------------- shelf
class Shelf(QWidget):
    def __init__(self, app_ref):
        super().__init__()
        self.app = app_ref
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                            Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.ArrowCursor)
        self.cards, self.dying = [], []
        self.state = "hidden"            # hidden | showing | shown | hiding
        self.pinned = self.dragging = self.menu_open = False
        self.hold_until = 0.0
        self.last_inside = time.time()
        self._edge_ticks = 0
        self._hover_card = None
        self._press = None
        self._press_pos, self._press_btn, self._drag_started = QPoint(), None, False
        self._last_age = 0.0
        self._screen_geo = QGuiApplication.primaryScreen().geometry()
        self._bw = float(PANEL_MIN_W + 2 * SH)
        self._y = float(self._screen_geo.y() - WIN_H - 10)
 
        self._slide = QPropertyAnimation(self, b"slideY")
        self._slide.finished.connect(self._slide_done)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._width_anim = QPropertyAnimation(self, b"barWidth")
        self.setWindowOpacity(0.0)
        self._apply_geo()
 
    # geometry-driven properties
    def _get_y(self): return self._y
    def _set_y(self, v):
        self._y = v
        self._apply_geo()
    slideY = Property(float, _get_y, _set_y)
 
    def _get_bw(self): return self._bw
    def _set_bw(self, v):
        self._bw = v
        self._apply_geo()
        for c in self.cards + self.dying:
            c.place()
    barWidth = Property(float, _get_bw, _set_bw)
 
    def _apply_geo(self):
        sg = self._screen_geo
        w = int(round(self._bw))
        self.setGeometry(sg.x() + (sg.width() - w) // 2, int(round(self._y)), w, WIN_H)
 
    def shown_y(self): return self._screen_geo.y() - 6
    def hidden_y(self): return self._screen_geo.y() - WIN_H - 12
 
    # ---- show / hide
    def reveal(self, pinned=False):
        if pinned:
            self.pinned = True
        self.last_inside = time.time()
        if self.state in ("shown", "showing"):
            return
        if self.state == "hidden":
            scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            self._screen_geo = scr.geometry()
            self._y = self.hidden_y()
            self.setWindowOpacity(0.0)
            self._apply_geo()
            self.show()
        self.state = "showing"
        self._slide.stop(); self._fade.stop()
        self._slide.setStartValue(self._y); self._slide.setEndValue(float(self.shown_y()))
        self._slide.setDuration(560); self._slide.setEasingCurve(curve(QEasingCurve.OutBack, 0.75))
        self._fade.setStartValue(self.windowOpacity()); self._fade.setEndValue(1.0)
        self._fade.setDuration(240); self._fade.setEasingCurve(curve(QEasingCurve.OutCubic))
        self._slide.start(); self._fade.start()
 
    def conceal(self):
        if self.state in ("hidden", "hiding"):
            return
        self.pinned = False
        self.state = "hiding"
        self._slide.stop(); self._fade.stop()
        self._slide.setStartValue(self._y); self._slide.setEndValue(float(self.hidden_y()))
        self._slide.setDuration(340); self._slide.setEasingCurve(curve(QEasingCurve.InCubic))
        self._fade.setStartValue(self.windowOpacity()); self._fade.setEndValue(0.0)
        self._fade.setDuration(300); self._fade.setEasingCurve(curve(QEasingCurve.InQuad))
        self._slide.start(); self._fade.start()
 
    def _slide_done(self):
        if self.state == "hiding":
            self.state = "hidden"
            self.hide()
        elif self.state == "showing":
            self.state = "shown"
 
    def peek(self, seconds):
        self.hold_until = max(self.hold_until, time.time() + seconds)
        self.reveal()
 
    def toggle(self):
        if self.state in ("shown", "showing"):
            self.conceal()
        else:
            self.reveal(pinned=True)
 
    def cursor_inside(self, pos):
        g = self.geometry()
        return QRect(g.x() + SH - 16, g.y(), g.width() - 2 * SH + 32, PH + 16).contains(pos)
 
    def tick(self):
        now, pos = time.time(), QCursor.pos()
        if self.app.auto_keep_secs and now - self._last_age >= 1.0:
            self._last_age = now                          # cards nobody touched leave the line; files stay
            for c in list(self.cards):
                if (now - c.born > self.app.auto_keep_secs and not c.hovering and
                        not c.confirming and not c.dragging and not self.dragging):
                    self.remove_card(c)
        if self.app.hover_reveal:
            scr = QGuiApplication.screenAt(pos)
            if scr:
                g = scr.geometry()
                near = pos.y() <= g.y() and abs(pos.x() - g.center().x()) <= max(self._bw / 2, 220)
                self._edge_ticks = self._edge_ticks + 1 if near else 0
                if self._edge_ticks >= 5 and self.state in ("hidden", "hiding"):
                    self.reveal()
        if self.state in ("shown", "showing"):
            busy = (self.pinned or self.dragging or self.menu_open or now < self.hold_until
                    or self.cursor_inside(pos) or any(c.confirming for c in self.cards))
            if busy:
                self.last_inside = now
            elif now - self.last_inside > 0.5:
                self.conceal()
 
    # ---- cards
    def max_items(self):
        w = self._screen_geo.width() - 2 * SH - 120
        return max(3, int((w - 68 + 16) / STEP))
 
    def add_card(self, path, pixmap, temp, delay_ms):
        card = ThumbCard(self, path, pixmap, temp)
        self.cards.insert(0, card)
        self.relayout(new_card=card)
        card.show()
        QTimer.singleShot(delay_ms, card.play_in)
        while len(self.cards) > self.max_items():
            self.remove_card(self.cards[-1])
 
    def remove_card(self, card, trash=False):
        if card not in self.cards:
            return
        if trash:
            self.app.trash_file(card)
        card.removing = True
        self.cards.remove(card)
        self.dying.append(card)
        if self._hover_card is card:
            self._hover_card = None
 
        def done():
            if card in self.dying:
                self.dying.remove(card)
            card.hide(); card.deleteLater()
            if card.temp:
                try: os.remove(card.path)
                except OSError: pass
        card.run("appear", None, 0, 240, curve(QEasingCurve.InCubic), finished=done)
        card.run("drop", None, 16, 240, curve(QEasingCurve.InCubic))
        self.relayout()
        self.app.save_state()
 
    def clear_all(self):
        for i, c in enumerate(list(self.cards)):
            QTimer.singleShot(i * 60, lambda c=c: self.remove_card(c))
 
    def relayout(self, new_card=None):
        n = len(self.cards)
        panel_w = max(PANEL_MIN_W, n * STEP - (STEP - CARD_W) + 68)
        self._width_anim.stop()
        self._width_anim.setStartValue(self._bw)
        self._width_anim.setEndValue(float(panel_w + 2 * SH))
        self._width_anim.setDuration(420)
        self._width_anim.setEasingCurve(curve(QEasingCurve.OutCubic))
        self._width_anim.start()
        for i, c in enumerate(self.cards):
            target = (i - (n - 1) / 2) * STEP
            if c is new_card:
                c._slot = target
                c.place()
            else:
                c.run("slot", None, target, 460, curve(QEasingCurve.OutCubic))
 
    # ---- painting the bar
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        pw = self.width() - 2 * SH
        panel = QRectF(SH, -60, pw, PH + 60)
        for i in range(14, 0, -1):
            sp = QPainterPath()
            sp.addRoundedRect(QRectF(SH - i, -60, pw + 2 * i, PH + 60 + i + 4), 26 + i, 26 + i)
            p.fillPath(sp, QColor(0, 0, 0, 5))
        path = QPainterPath()
        path.addRoundedRect(panel, 26, 26)
        g = QLinearGradient(0, 0, 0, PH)
        g.setColorAt(0, QColor(42, 44, 58, 224)); g.setColorAt(1, QColor(22, 23, 31, 234))
        p.fillPath(path, g)
        sheen = QLinearGradient(0, 0, 0, PH * 0.6)
        sheen.setColorAt(0, QColor(255, 255, 255, 28)); sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, sheen)
        p.setPen(QPen(QColor(255, 255, 255, 52), 1))
        p.drawPath(path)
        # the line itself, with a gentle sag
        line = QPainterPath(QPointF(SH + 16, 17))
        line.quadTo(QPointF(self.width() / 2, 24), QPointF(SH + pw - 16, 17))
        p.setPen(QPen(QColor(222, 205, 170, 215), 2.2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)
        if not self.cards:
            p.setPen(QColor(255, 255, 255, 190))
            p.setFont(QFont("Segoe UI", 12, QFont.DemiBold))
            p.drawText(QRectF(SH, 52, pw, 30), Qt.AlignCenter, "Nothing on the line yet")
            p.setPen(QColor(255, 255, 255, 120))
            p.setFont(QFont("Segoe UI", 10))
            p.drawText(QRectF(SH, 84, pw, 24), Qt.AlignCenter,
                       "Take a screenshot (Win + Shift + S) and it will hang here")
        p.end()
 
    # ---- mouse
    def card_at(self, pos):
        for c in self.cards:
            if c.visual_rect().contains(pos):
                return c
        return None
 
    def _update_hover(self, pos):
        hc = self.card_at(pos)
        if hc is not self._hover_card:
            if self._hover_card:
                self._hover_card.set_hover(False)
            if hc:
                hc.set_hover(True)
            self._hover_card = hc
        for c in self.cards:
            b = c.button_at(pos) if c is hc else None
            if b != c.btn_hover:
                c.btn_hover = b
                c.x_hover = (b == "x")
                c.update()
        self.setCursor(Qt.PointingHandCursor if hc else Qt.ArrowCursor)
 
    def leaveEvent(self, ev):
        self._update_hover(QPoint(-999, -999))
 
    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if (e.buttons() & Qt.LeftButton) and self._press and not self._press_btn and not self._drag_started and \
                (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
            self._start_drag(self._press)
            return
        if not (e.buttons() & Qt.LeftButton):
            self._update_hover(pos)
 
    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        card = self.card_at(pos)
        if e.button() == Qt.RightButton and card:
            self._card_menu(card, e.globalPosition().toPoint())
        elif e.button() == Qt.LeftButton:
            btn = card.button_at(pos) if card else None
            if card and card.confirming and not btn:
                card = None                           # while asking, a stray click does nothing
            self._press, self._press_pos, self._drag_started = card, pos, False
            self._press_btn = btn
 
    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        card, self._press = self._press, None
        btn0, self._press_btn = self._press_btn, None
        if not card or self._drag_started:
            self._drag_started = False
            return
        pos = e.position().toPoint()
        if btn0:
            if card.button_at(pos) == btn0:
                self._do_button(card, btn0)
        else:
            self.app.copy_image(card, pos)
 
    def _do_button(self, card, btn):
        if btn == "keep":
            self.remove_card(card)                        # off the line, file stays put
        elif btn in ("delete", "x"):
            self.app.request_delete(card)
        elif btn == "cancel":
            card.cancel_confirm()
        elif btn == "confirm":
            self.remove_card(card, trash=True)
 
    def mouseDoubleClickEvent(self, e):
        self._press = None
        card = self.card_at(e.position().toPoint())
        if card and not card.confirming and not card.button_at(e.position().toPoint()):
            self.app.open_image(card.path)
 
    def _start_drag(self, card):
        self._drag_started = self.dragging = True
        self._press = None
        card.dragging = True
        card.update()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(card.path)])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(card.pm)
        drag.setHotSpot(QPoint(THUMB_W // 2, THUMB_H // 2))
        drag.exec(Qt.CopyAction, Qt.CopyAction)       # copy only: never moves the original
        card.dragging = False
        card.update()
        self.dragging = False
        self.hold_until = time.time() + 1.2
 
    def _card_menu(self, card, gpos):
        self.menu_open = True
        m = QMenu()
        a_copy = m.addAction("Copy image")
        a_open = m.addAction("Open")
        a_show = m.addAction("Show in folder")
        m.addSeparator()
        a_bin = m.addAction("Move to Recycle Bin")
        a_rm = m.addAction("Keep file, remove from line")
        act = m.exec(gpos)
        self.menu_open = False
        if act == a_copy: self.app.copy_image(card, None)
        elif act == a_open: self.app.open_image(card.path)
        elif act == a_show: self.app.show_in_folder(card.path)
        elif act == a_bin: self.app.request_delete(card)
        elif act == a_rm: self.remove_card(card)
 
 
# ----------------------------------------------------------------------------- hotkeys
class HotkeyFilter(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312
 
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.ids = []
 
    def register(self):
        if not IS_WIN:
            return []
        MOD_ALT, MOD_CTRL, MOD_SHIFT, MOD_WIN, NOREPEAT = 1, 2, 4, 8, 0x4000
        combos = [(1, MOD_CTRL | MOD_ALT, 0x54, "Ctrl+Alt+T"), (2, MOD_WIN | MOD_SHIFT, 0x59, "Win+Shift+Y")]
        ok = []
        for hid, mod, vk, label in combos:
            if ctypes.windll.user32.RegisterHotKey(None, hid, mod | NOREPEAT, vk):
                self.ids.append(hid)
                ok.append(label)
        return ok
 
    def unregister(self):
        for hid in self.ids:
            ctypes.windll.user32.UnregisterHotKey(None, hid)
 
    def nativeEventFilter(self, event_type, message):
        if IS_WIN and bytes(event_type) == b"windows_generic_MSG":
            import ctypes.wintypes as wt
            msg = wt.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam in self.ids:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0
 
 
# ----------------------------------------------------------------------------- controller
class ClotheslineApp(QObject):
    ready = Signal(str, QImage, int, int, str, str, bool)
 
    def __init__(self, app, dirs=None):
        super().__init__()
        self.qapp = app
        self.hover_reveal = True
        self.confirm_delete = False
        self.auto_keep_secs = 300
        self.dirs = dirs or screenshot_dirs()
        self.shelf = Shelf(self)
        self.q = queue.Queue()
        self.recent = []
        self.ignore_clip_until = 0.0
        self.last_clip_hash = None
        self.state_file = os.path.join(data_dir(), "line.json")
        self.known = set()
        for d in self.dirs:
            for n in os.listdir(d):
                self.known.add(os.path.join(d, n))
 
        self.ready.connect(self.on_ready)
        threading.Thread(target=self._worker, daemon=True).start()
 
        # file watcher (+ slow poll as a safety net)
        self.watcher = QFileSystemWatcher(self.dirs)
        self.scan_timer = QTimer(self, singleShot=True, interval=200, timeout=self.scan)
        self.watcher.directoryChanged.connect(lambda _: self.scan_timer.start())
        self.poll = QTimer(self, interval=1500, timeout=self.scan)
        self.poll.start()
 
        # clipboard watcher
        self.clip_timer = QTimer(self, singleShot=True, interval=160, timeout=self.check_clipboard)
        QGuiApplication.clipboard().dataChanged.connect(lambda: self.clip_timer.start())
 
        # hover / auto-hide loop
        self.ticker = QTimer(self, interval=33, timeout=self.shelf.tick)
        self.ticker.start()
 
        self.hk = HotkeyFilter(self.shelf.toggle)
        app.installNativeEventFilter(self.hk)
        labels = self.hk.register()
        self._setup_tray(labels)
        self.restore_state()
        self.cleanup_temp()
        QTimer.singleShot(500, lambda: self.shelf.peek(3.5))
        app.aboutToQuit.connect(self.shutdown)
 
    # ---- tray
    def _setup_tray(self, labels):
        self.tray = QSystemTrayIcon(make_icon(), self)
        hk = " / ".join(labels) if labels else "tray icon"
        self.tray.setToolTip(f"Clothesline v1.3 - toggle with {hk}")
        m = QMenu()
        m.addAction(f"Show / hide the line ({hk})").triggered.connect(self.shelf.toggle)
        a = m.addAction("Reveal when mouse hits the top edge")
        a.setCheckable(True); a.setChecked(True)
        a.toggled.connect(lambda v: setattr(self, "hover_reveal", v))
        b = m.addAction("Ask before moving to the Recycle Bin")
        b.setCheckable(True); b.setChecked(self.confirm_delete)
        b.toggled.connect(lambda v: setattr(self, "confirm_delete", v))
        sub = m.addMenu("Auto-dismiss from the line (keeps the file)")
        grp = QActionGroup(sub)
        for label, secs in (("Never", 0), ("After 1 minute", 60), ("After 5 minutes", 300),
                            ("After 15 minutes", 900), ("After 1 hour", 3600)):
            act = sub.addAction(label)
            act.setCheckable(True); act.setActionGroup(grp)
            act.setChecked(secs == self.auto_keep_secs)
            act.triggered.connect(lambda _=False, v=secs: setattr(self, "auto_keep_secs", v))
        m.addSeparator()
        m.addAction("Clear the line").triggered.connect(self.shelf.clear_all)
        m.addAction("Open screenshots folder").triggered.connect(lambda: self.open_image(self.dirs[0]))
        m.addSeparator()
        m.addAction("Quit Clothesline").triggered.connect(self.qapp.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.shelf.toggle() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._menu = m
        self.tray.showMessage("Clothesline is running",
                              f"Move the mouse to the top edge or press {hk}.",
                              QSystemTrayIcon.Information, 4000)
 
    # ---- ingest pipeline (decoding runs off the UI thread, so animations stay smooth)
    def scan(self):
        for d in self.dirs:
            try: names = os.listdir(d)
            except OSError: continue
            for n in names:
                if os.path.splitext(n)[1].lower() not in EXTS:
                    continue
                fp = os.path.join(d, n)
                if fp not in self.known:
                    self.known.add(fp)
                    self.q.put((fp, "file", None, True))
 
    def check_clipboard(self):
        if time.time() < self.ignore_clip_until:
            return
        cb = QGuiApplication.clipboard()
        md = cb.mimeData()
        if md is None or not md.hasImage():
            return
        img = cb.image()
        if img.isNull():
            return
        h = img_hash(img)
        if h == self.last_clip_hash:
            return
        self.last_clip_hash = h
        name = "clip_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".png"
        self.q.put((os.path.join(clip_dir(), name), "clipboard", img, True))
 
    def _worker(self):
        while True:
            try:
                path, source, img, peek = self.q.get()
                if img is not None:
                    if not img.save(path, "PNG"):
                        continue
                elif source == "restore":
                    img = QImage(path)
                else:
                    last = -1
                    for _ in range(25):              # wait until the file is fully written
                        try: size = os.path.getsize(path)
                        except OSError: size = -1
                        if size > 0 and size == last:
                            img = QImage(path)
                            if not img.isNull():
                                break
                        last = size
                        time.sleep(0.2)
                if img is None or img.isNull():
                    continue
                tw, th = int(THUMB_W * DPR), int(THUMB_H * DPR)
                s = img.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                thumb = s.copy((s.width() - tw) // 2, (s.height() - th) // 2, tw, th)
                self.ready.emit(path, thumb, img.width(), img.height(), img_hash(img), source, peek)
            except Exception:
                pass
 
    def on_ready(self, path, thumb, w, h, hsh, source, peek):
        now = time.time()
        if source != "restore":
            for t, w2, h2, hh, src2, p2 in self.recent:
                same_size_other_source = (src2 != source and now - t < 8 and (w2, h2) == (w, h))
                if (now - t < 90 and hh == hsh) or same_size_other_source:
                    if source == "clipboard":
                        try: os.remove(path)
                        except OSError: pass
                    elif src2 == "clipboard":
                        self.adopt_file(p2, path)     # point the card at the real saved file
                    return
            self.recent = (self.recent + [(now, w, h, hsh, source, path)])[-20:]
        pm = QPixmap.fromImage(thumb)
        pm.setDevicePixelRatio(DPR)
        visible = self.shelf.state in ("shown", "showing")
        self.shelf.add_card(path, pm, source == "clipboard", 0 if visible else 300)
        if peek:
            self.shelf.peek(2.6)
        self.save_state()
 
    def adopt_file(self, temp_path, real_path):
        for c in self.shelf.cards:
            if c.path == temp_path:
                c.path, c.temp = real_path, False
                try: os.remove(temp_path)
                except OSError: pass
                self.save_state()
                return
 
    # ---- actions
    def copy_image(self, card, pos):
        if pos is not None:
            card.flash(pos)
        else:
            card.flash(QPoint(card.x() + card.width() // 2, card.y() + PADT + CARD_H // 2))
        self.shelf.hold_until = max(self.shelf.hold_until, time.time() + 1.3)
 
        def do():
            img = QImage(card.path)
            if not img.isNull():
                self.ignore_clip_until = time.time() + 1.5
                QGuiApplication.clipboard().setImage(img)
        QTimer.singleShot(0, do)
 
    def request_delete(self, card):
        if self.confirm_delete:
            card.ask_confirm()
        else:
            self.shelf.remove_card(card, trash=True)
 
    def trash_file(self, card):
        if card.temp:                                  # our own clipboard copy: removed after the fade
            return
        if not move_to_recycle_bin(card.path):
            self.tray.showMessage("Clothesline", "Couldn't move that file to the Recycle Bin.",
                                  QSystemTrayIcon.Warning, 3000)
 
    def open_image(self, path):
        try:
            if IS_WIN: os.startfile(path)
            else: subprocess.Popen(["xdg-open", path])
        except Exception:
            pass
 
    def show_in_folder(self, path):
        try:
            if IS_WIN: subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else: subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass
 
    # ---- persistence
    def save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump([c.path for c in self.shelf.cards], f)
        except OSError:
            pass
 
    def restore_state(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                paths = json.load(f)
        except (OSError, ValueError):
            return
        for p in reversed(paths):                     # oldest first, newest ends up leftmost
            if os.path.isfile(p):
                self.known.add(p)
                self.q.put((p, "restore", None, False))
 
    def cleanup_temp(self):
        keep = set()
        try:
            with open(self.state_file, encoding="utf-8") as f:
                keep = set(json.load(f))
        except (OSError, ValueError):
            pass
        d, cutoff = clip_dir(), time.time() - 3 * 86400
        for n in os.listdir(d):
            fp = os.path.join(d, n)
            try:
                if fp not in keep and os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except OSError:
                pass
 
    def shutdown(self):
        self.hk.unregister()
        self.save_state()
 
 
def main():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Clothesline")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "clothesline.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):                         # already running
        QMessageBox.information(None, "Clothesline",
                                "Clothesline is already running.\n\nRight-click its tray icon (near the "
                                "clock, maybe under the ^ arrow), choose Quit, then start it again.")
        sys.exit(0)
    clothesline = ClotheslineApp(app)                     # noqa: F841 (keeps references alive)
    sys.exit(app.exec())
 
 
if __name__ == "__main__":
    main()
 
