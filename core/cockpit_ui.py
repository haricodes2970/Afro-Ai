import sys
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QCheckBox,
    QSizePolicy, QSpacerItem, QFrame,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal,
    QPointF, QRectF, QSize,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont, QFontDatabase,
    QRadialGradient, QLinearGradient,
    QTextCursor,
)

# ── Palette ───────────────────────────────────────────────────────────────────
_C_BG_0      = QColor( 8,  8, 18)
_C_BG_1      = QColor( 7, 13, 30)
_C_BG_2      = QColor( 5,  9, 22)
_C_ACCENT    = QColor(59, 130, 246)       # blue
_C_NEON      = QColor(57, 255,  20)       # #39FF14
_C_NEON_DIM  = QColor(57, 255,  20, 80)
_C_PANEL     = QColor(255, 255, 255,  10)
_C_BORDER    = QColor(255, 255, 255,  20)
_C_TEXT      = QColor(226, 232, 240)
_C_DIM       = QColor(100, 116, 139)
_C_TERM      = QColor( 34, 211, 238)      # cyan terminal text

# ── Stylesheet ────────────────────────────────────────────────────────────────
_QSS = """
QWidget { color: #e2e8f0; }

QTextEdit#terminal {
    background-color: rgba(0, 0, 0, 0.40);
    border: 1px solid rgba(59, 130, 246, 0.30);
    border-radius: 10px;
    color: #22d3ee;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    padding: 8px 10px;
    selection-background-color: rgba(59,130,246,0.35);
}
QScrollBar:vertical {
    background: rgba(255,255,255,0.03);
    width: 5px;
    margin: 0;
    border-radius: 2px;
}
QScrollBar::handle:vertical {
    background: rgba(59,130,246,0.45);
    border-radius: 2px;
    min-height: 16px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }

QPushButton#startBtn {
    border-radius: 9px;
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 3px;
    padding: 14px 48px;
    min-width: 190px;
}
QPushButton#startBtn[active="false"] {
    background-color: rgba(80, 80, 90, 0.75);
    border: 2px solid rgba(110,110,125,0.60);
    color: #94a3b8;
}
QPushButton#startBtn[active="false"]:hover {
    background-color: rgba(100,100,115,0.85);
    border-color: rgba(160,160,175,0.75);
    color: #e2e8f0;
}
QPushButton#startBtn[active="true"] {
    background-color: rgba(57,255,20,0.10);
    border: 2px solid #39FF14;
    color: #39FF14;
}
QPushButton#startBtn[active="true"]:hover {
    background-color: rgba(57,255,20,0.20);
}

QLabel#logo {
    color: #3b82f6;
    font-size: 17px;
    font-weight: bold;
    letter-spacing: 5px;
}
QLabel#versionLbl {
    color: rgba(100,116,139,0.75);
    font-size: 9px;
    letter-spacing: 2px;
}
QLabel#sectionLbl {
    color: #64748b;
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 3px;
    text-transform: uppercase;
}

QCheckBox#topHint {
    color: #64748b;
    font-size: 10px;
    letter-spacing: 1px;
    spacing: 5px;
}
QCheckBox#topHint::indicator {
    width: 13px;
    height: 13px;
    border-radius: 3px;
    border: 1px solid rgba(255,255,255,0.18);
    background: rgba(255,255,255,0.04);
}
QCheckBox#topHint::indicator:checked {
    background: rgba(59,130,246,0.55);
    border-color: #3b82f6;
}
"""


# ── Background widget ─────────────────────────────────────────────────────────
class _BackgroundWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, _C_BG_0)
        grad.setColorAt(0.5, _C_BG_1)
        grad.setColorAt(1.0, _C_BG_2)
        p.fillRect(self.rect(), QBrush(grad))

        rg = QRadialGradient(w * 0.18, h * 0.12, w * 0.55)
        rg.setColorAt(0.0, QColor(59, 130, 246, 18))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg))

        rg2 = QRadialGradient(w * 0.82, h * 0.82, w * 0.45)
        rg2.setColorAt(0.0, QColor(139, 92, 246, 13))
        rg2.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), QBrush(rg2))
        p.end()


# ── Status dot ────────────────────────────────────────────────────────────────
class _StatusDot(QWidget):
    _SIZE = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._glow   = 0.0
        self._glow_dir = 1
        self.setFixedSize(self._SIZE + 8, self._SIZE + 8)

        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_active(self, active: bool):
        self._active = active
        self.update()

    def _tick(self):
        if self._active:
            self._glow += 0.05 * self._glow_dir
            if self._glow >= 1.0:
                self._glow_dir = -1
            elif self._glow <= 0.0:
                self._glow_dir = 1
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r  = self._SIZE / 2

        if self._active:
            color = _C_NEON
            glow_alpha = int(60 + 50 * self._glow)
            glow_r = r * (1.8 + 0.4 * self._glow)
            rg = QRadialGradient(cx, cy, glow_r)
            rg.setColorAt(0.0, QColor(57, 255, 20, glow_alpha))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(rg))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))
        else:
            color = _C_DIM

        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.end()


# ── Voice pulse widget ────────────────────────────────────────────────────────
class VoicePulseWidget(QWidget):
    _CORE_R      = 38
    _MAX_WAVE_R  = 85
    _WAVE_SPEED  = 1.6     # px per 16ms tick
    _SPAWN_MS    = 480

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speaking  = False
        self._waves: list[float] = []   # each entry: current radius
        self._core_t    = 0.0           # 0→2π oscillator for core pulse
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(220, 220)

        self._anim = QTimer(self)
        self._anim.setInterval(16)
        self._anim.timeout.connect(self._tick)
        self._anim.start()

        self._spawn = QTimer(self)
        self._spawn.setInterval(self._SPAWN_MS)
        self._spawn.timeout.connect(self._spawn_wave)

    def set_speaking(self, speaking: bool):
        self._speaking = speaking
        if speaking:
            self._spawn_wave()
            self._spawn.start()
        else:
            self._spawn.stop()

    def _spawn_wave(self):
        self._waves.append(float(self._CORE_R))

    def _tick(self):
        if self._speaking:
            self._core_t += 0.08
        else:
            self._core_t += 0.02

        new_waves = []
        for r in self._waves:
            r += self._WAVE_SPEED
            if r < self._MAX_WAVE_R:
                new_waves.append(r)
        needs_repaint = self._waves != new_waves or self._speaking
        self._waves = new_waves
        if needs_repaint or self._waves:
            self.update()

    def paintEvent(self, _event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width()  / 2.0
        cy = self.height() / 2.0
        travel = self._MAX_WAVE_R - self._CORE_R

        # ── Rings ─────────────────────────────────────────────────
        for r in self._waves:
            t = (r - self._CORE_R) / travel          # 0 → 1
            alpha_fill   = int((1.0 - t) * 35)
            alpha_stroke = int((1.0 - t) * 140)
            p.setBrush(QBrush(QColor(57, 255, 20, alpha_fill)))
            p.setPen(QPen(QColor(57, 255, 20, alpha_stroke), 1.2))
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # ── Core glow ─────────────────────────────────────────────
        pulse  = math.sin(self._core_t) * 0.12
        core_r = self._CORE_R * (1.0 + pulse if self._speaking else 1.0)
        glow_r = core_r * 1.9

        if self._speaking:
            core_col = _C_NEON
            glow_col = QColor(57, 255, 20, 55)
        else:
            core_col = _C_ACCENT
            glow_col = QColor(59, 130, 246, 40)

        rg = QRadialGradient(cx, cy, glow_r)
        rg.setColorAt(0.0, glow_col)
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

        # ── Core fill ─────────────────────────────────────────────
        rg2 = QRadialGradient(cx - core_r * 0.28, cy - core_r * 0.28, core_r)
        rg2.setColorAt(0.0, core_col.lighter(140))
        rg2.setColorAt(1.0, core_col.darker(130))
        p.setBrush(QBrush(rg2))
        p.setPen(QPen(core_col, 1.8))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))

        # ── Inner "A" label ────────────────────────────────────────
        font = QFont("Segoe UI", int(core_r * 0.5), QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255, 200)))
        p.drawText(
            QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2),
            Qt.AlignmentFlag.AlignCenter,
            "A",
        )
        p.end()

    def sizeHint(self) -> QSize:
        return QSize(240, 240)


# ── Glass panel helper ────────────────────────────────────────────────────────
class _Panel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(_C_PANEL))
        p.setPen(QPen(_C_BORDER, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.end()


# ── Main window ───────────────────────────────────────────────────────────────
class CockpitUI(QMainWindow):
    listener_start_requested = pyqtSignal()
    listener_stop_requested  = pyqtSignal()

    # internal — used for thread-safe log appending
    _log_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._agent_state: str  = "STANDBY"
        self._always_on_top     = False

        self._build_window()
        self._build_ui()
        self._log_signal.connect(self._do_append_log)
        self.setStyleSheet(_QSS)

    # ── Window setup ─────────────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowTitle("Afro — Cockpit")
        self.setMinimumSize(620, 780)
        self.resize(700, 860)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        bg = _BackgroundWidget(self)
        bg.setObjectName("centralWidget")
        self.setCentralWidget(bg)

        self._root_layout = QVBoxLayout(bg)
        self._root_layout.setContentsMargins(20, 18, 20, 18)
        self._root_layout.setSpacing(14)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_center()
        self._build_terminal()

    def _build_header(self):
        header = _Panel(self)
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(10)

        logo = QLabel("⬡ AFRO")
        logo.setObjectName("logo")
        row.addWidget(logo)

        ver = QLabel("v1.0")
        ver.setObjectName("versionLbl")
        row.addWidget(ver)

        row.addStretch()

        self._status_dot = _StatusDot()
        row.addWidget(self._status_dot)

        self._status_lbl = QLabel("STANDBY")
        self._status_lbl.setObjectName("sectionLbl")
        row.addWidget(self._status_lbl)

        row.addSpacing(16)

        self._top_hint = QCheckBox("ALWAYS ON TOP")
        self._top_hint.setObjectName("topHint")
        self._top_hint.setChecked(False)
        self._top_hint.toggled.connect(self._on_top_hint_toggled)
        row.addWidget(self._top_hint)

        self._root_layout.addWidget(header)

    def _build_center(self):
        center = _Panel(self)
        col = QVBoxLayout(center)
        col.setContentsMargins(24, 28, 24, 28)
        col.setSpacing(22)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._pulse = VoicePulseWidget()
        self._pulse.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        col.addWidget(self._pulse, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._btn = QPushButton("START AFRO")
        self._btn.setObjectName("startBtn")
        self._btn.setProperty("active", "false")
        self._btn.clicked.connect(self._on_toggle_clicked)
        self._btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        col.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._root_layout.addWidget(center, stretch=3)

    def _build_terminal(self):
        wrap = QWidget()
        wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        hdr = QLabel("▸ STATUS LOG")
        hdr.setObjectName("sectionLbl")
        col.addWidget(hdr)

        self._terminal = QTextEdit()
        self._terminal.setObjectName("terminal")
        self._terminal.setReadOnly(True)
        self._terminal.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        font = QFont()
        font.setFamilies(["Cascadia Code", "Fira Code", "Consolas", "Courier New"])
        font.setPointSize(11)
        self._terminal.setFont(font)
        col.addWidget(self._terminal)

        self._root_layout.addWidget(wrap, stretch=2)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_toggle_clicked(self):
        if self._agent_state == "STANDBY":
            self.listener_start_requested.emit()
            self.set_agent_state("ACTIVE")
        else:
            self.listener_stop_requested.emit()
            self.set_agent_state("STANDBY")

    def _on_top_hint_toggled(self, checked: bool):
        self._always_on_top = checked
        flags = self.windowFlags()
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_agent_state(self, state: str) -> None:
        """
        Call from any thread via signal or directly from the Qt thread.
        state: "STANDBY" | "ACTIVE"
        """
        if state not in ("STANDBY", "ACTIVE"):
            return
        self._agent_state = state
        active = state == "ACTIVE"

        self._btn.setText("STANDBY" if active else "START AFRO")
        self._btn.setProperty("active", "true" if active else "false")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)

        self._status_dot.set_active(active)
        self._status_lbl.setText(state)

    def set_speaking(self, speaking: bool) -> None:
        """Toggle voice pulse animation. Thread-safe — Qt will coalesce from any thread."""
        self._pulse.set_speaking(speaking)

    def append_log(self, text: str) -> None:
        """Thread-safe log append. Safe to call from worker threads."""
        self._log_signal.emit(text)

    def start_listener(self) -> None:
        """Programmatically start — identical to button press."""
        if self._agent_state == "STANDBY":
            self._on_toggle_clicked()

    def stop_listener(self) -> None:
        """Programmatically stop — identical to button press."""
        if self._agent_state == "ACTIVE":
            self._on_toggle_clicked()

    # ── Internal slot (Qt thread only) ───────────────────────────────────────

    def _do_append_log(self, text: str) -> None:
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {text}"
        self._terminal.moveCursor(QTextCursor.MoveOperation.End)
        self._terminal.insertPlainText(line + "\n")
        self._terminal.moveCursor(QTextCursor.MoveOperation.End)
        self._terminal.ensureCursorVisible()

        # Trim to 500 lines to prevent unbounded growth
        doc = self._terminal.document()
        while doc.blockCount() > 500:
            cursor = QTextCursor(doc.begin())
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.movePosition(
                QTextCursor.MoveOperation.NextBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._agent_state == "ACTIVE":
            self.listener_stop_requested.emit()
        self._pulse._anim.stop()
        self._pulse._spawn.stop()
        self._status_dot._timer.stop()
        event.accept()


# ── Entry point ───────────────────────────────────────────────────────────────

def launch_cockpit(
    on_start=None,
    on_stop=None,
    parent=None,
) -> tuple["QApplication", "CockpitUI"]:
    """
    Create and show the CockpitUI.

    on_start: callable() — invoked when listener_start_requested fires
    on_stop:  callable() — invoked when listener_stop_requested fires

    Returns (app, ui) so the caller can exec() when ready.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    ui = CockpitUI(parent)

    if on_start:
        ui.listener_start_requested.connect(on_start)
    if on_stop:
        ui.listener_stop_requested.connect(on_stop)

    ui.show()
    return app, ui


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    app, ui = launch_cockpit()
    ui.append_log("Cockpit UI initialized.")
    ui.append_log("Waiting for agent start...")
    sys.exit(app.exec())
