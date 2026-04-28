import sys
import os
import math
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel,
    QSizePolicy, QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal,
    QPointF, QRectF, QSize, QPoint,
)
from PyQt6.QtGui import (
    QColor, QPainter, QPen, QBrush, QFont,
    QRadialGradient, QLinearGradient,
    QTextCursor, QCursor,
)

# ── Palette ───────────────────────────────────────────────────────────────────
_NEON       = QColor(57,  255,  20)
_NEON_A60   = QColor(57,  255,  20,  60)
_NEON_A25   = QColor(57,  255,  20,  25)
_BLUE       = QColor(59,  130, 246)
_BLUE_A40   = QColor(59,  130, 246,  40)
_BG         = QColor( 6,    6,   6, 238)
_BG_PANEL   = QColor(12,   12,  22, 200)
_BORDER     = QColor(57,  255,  20,  35)
_BORDER_DIM = QColor(255, 255, 255,  14)
_TEXT       = QColor(226, 232, 240)
_DIM        = QColor(100, 116, 139)

# ── Stylesheet ────────────────────────────────────────────────────────────────
_QSS = """
QWidget { color: #e2e8f0; }

QPushButton#closeBtn, QPushButton#minBtn {
    background: transparent;
    border: none;
    color: #64748b;
    font-size: 14px;
    min-width: 28px;
    min-height: 28px;
    border-radius: 14px;
}
QPushButton#closeBtn:hover { background: rgba(239,68,68,0.25); color: #ef4444; }
QPushButton#minBtn:hover   { background: rgba(255,255,255,0.08); color: #e2e8f0; }

QPushButton#activateBtn {
    border-radius: 10px;
    font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 15px;
    font-weight: bold;
    letter-spacing: 4px;
    padding: 15px 52px;
    min-width: 200px;
}
QPushButton#activateBtn[active="false"] {
    background-color: rgba(70, 70, 80, 0.70);
    border: 2px solid rgba(100,100,115,0.50);
    color: #64748b;
}
QPushButton#activateBtn[active="false"]:hover {
    background-color: rgba(90, 90,105, 0.80);
    border-color: rgba(140,140,160,0.65);
    color: #94a3b8;
}
QPushButton#activateBtn[active="true"] {
    background-color: rgba(57,255,20,0.10);
    border: 2px solid #39FF14;
    color: #39FF14;
}
QPushButton#activateBtn[active="true"]:hover {
    background-color: rgba(57,255,20,0.18);
}

QLabel#logo {
    color: #39FF14;
    font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 15px;
    font-weight: bold;
    letter-spacing: 6px;
}
QLabel#stateLbl {
    font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 9px;
    letter-spacing: 3px;
    color: #64748b;
}

QTextEdit#terminal {
    background-color: rgba(0, 0, 0, 0.50);
    border: 1px solid rgba(57,255,20,0.18);
    border-radius: 10px;
    color: #22d3ee;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 11px;
    padding: 8px 10px;
    selection-background-color: rgba(57,255,20,0.25);
}
QScrollBar:vertical {
    background: rgba(255,255,255,0.02);
    width: 4px;
    border-radius: 2px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(57,255,20,0.35);
    border-radius: 2px;
    min-height: 14px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QLabel#termHdr {
    font-family: "JetBrains Mono", "Cascadia Code", "Consolas", monospace;
    font-size: 8px;
    letter-spacing: 3px;
    color: rgba(57,255,20,0.55);
}
"""


# ── Root widget (draws dark rounded background) ───────────────────────────────
class _RootWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Outer glow ring
        glow = QColor(57, 255, 20, 18)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(glow, 3))
        p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 18, 18)

        # Main dark background
        p.setBrush(QBrush(_BG))
        p.setPen(QPen(_BORDER, 1))
        p.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 16, 16)
        p.end()


# ── Glass section panel ───────────────────────────────────────────────────────
class _Panel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(_BG_PANEL))
        p.setPen(QPen(_BORDER_DIM, 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 12, 12)
        p.end()


# ── Voice orb ─────────────────────────────────────────────────────────────────
class VoiceOrb(QWidget):
    _CORE_R     = 44
    _MAX_WAVE_R = 92
    _WAVE_SPEED = 1.8
    _SPAWN_MS   = 560

    def __init__(self, parent=None):
        super().__init__(parent)
        self._speaking = False
        self._waves: list[float] = []
        self._t = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(210, 210)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(20)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start()

        self._spawn_timer = QTimer(self)
        self._spawn_timer.setInterval(self._SPAWN_MS)
        self._spawn_timer.timeout.connect(self._spawn)

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        if speaking:
            self._spawn()
            self._spawn_timer.start()
        else:
            self._spawn_timer.stop()

    def _spawn(self) -> None:
        self._waves.append(float(self._CORE_R))

    def _tick(self) -> None:
        speed = 0.06 if self._speaking else 0.022
        self._t += speed

        new_waves = [r + self._WAVE_SPEED for r in self._waves
                     if r + self._WAVE_SPEED < self._MAX_WAVE_R]
        dirty = new_waves != self._waves or self._speaking
        self._waves = new_waves
        if dirty:
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width()  / 2.0
        cy = self.height() / 2.0
        travel = float(self._MAX_WAVE_R - self._CORE_R)

        # ── Waves ──────────────────────────────────────────────────
        for r in self._waves:
            frac         = (r - self._CORE_R) / travel
            alpha_stroke = int((1.0 - frac) * 160)
            alpha_fill   = int((1.0 - frac) *  28)
            p.setBrush(QBrush(QColor(57, 255, 20, alpha_fill)))
            p.setPen(QPen(QColor(57, 255, 20, alpha_stroke), 1.3))
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # ── Outer halo ─────────────────────────────────────────────
        pulse = math.sin(self._t)
        if self._speaking:
            halo_r   = self._CORE_R * (1.55 + 0.12 * pulse)
            halo_col = QColor(57, 255, 20, int(55 + 20 * pulse))
            core_col = _NEON
        else:
            halo_r   = self._CORE_R * (1.38 + 0.04 * pulse)
            halo_col = QColor(59, 130, 246, int(35 + 12 * pulse))
            core_col = _BLUE

        rg = QRadialGradient(cx, cy, halo_r)
        rg.setColorAt(0.0, halo_col)
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - halo_r, cy - halo_r, halo_r * 2, halo_r * 2))

        # ── Core fill ──────────────────────────────────────────────
        core_r = self._CORE_R * (1.0 + (0.10 if self._speaking else 0.03) * pulse)
        rg2 = QRadialGradient(cx - core_r * 0.3, cy - core_r * 0.3, core_r)
        rg2.setColorAt(0.0, core_col.lighter(160))
        rg2.setColorAt(1.0, core_col.darker(140))
        p.setBrush(QBrush(rg2))
        p.setPen(QPen(core_col, 1.5))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))

        # ── "A" glyph ──────────────────────────────────────────────
        font = QFont("JetBrains Mono", int(core_r * 0.46))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255, 210)))
        p.drawText(
            QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2),
            Qt.AlignmentFlag.AlignCenter, "A",
        )
        p.end()

    def sizeHint(self) -> QSize:
        return QSize(230, 230)


# ── Main window ───────────────────────────────────────────────────────────────
class CockpitUI(QMainWindow):
    listener_start_requested = pyqtSignal()
    listener_stop_requested  = pyqtSignal()
    _log_signal              = pyqtSignal(str)   # thread-safe log relay

    def __init__(self, parent=None):
        super().__init__(parent)
        self._agent_state = "STANDBY"
        self._drag_pos: QPoint | None = None
        self._btn_glow: QGraphicsDropShadowEffect | None = None

        self._configure_window()
        self._build_ui()
        self._log_signal.connect(self._do_append_log)
        self.setStyleSheet(_QSS)

    # ── Window setup ─────────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        self.setWindowTitle("Afro Cockpit")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(580, 760)
        self.resize(640, 820)

        root = _RootWidget(self)
        self.setCentralWidget(root)
        self._layout = QVBoxLayout(root)
        self._layout.setContentsMargins(18, 14, 18, 18)
        self._layout.setSpacing(12)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._build_titlebar()
        self._build_orb_section()
        self._build_terminal()

    def _build_titlebar(self) -> None:
        bar = QWidget()
        bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 0, 4, 0)
        row.setSpacing(8)

        logo = QLabel("⬡  AFRO")
        logo.setObjectName("logo")
        row.addWidget(logo)

        row.addStretch()

        self._state_lbl = QLabel("STANDBY")
        self._state_lbl.setObjectName("stateLbl")
        row.addWidget(self._state_lbl)

        row.addSpacing(10)

        min_btn = QPushButton("─")
        min_btn.setObjectName("minBtn")
        min_btn.setFixedSize(28, 28)
        min_btn.clicked.connect(self.showMinimized)
        row.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.clicked.connect(self._safe_close)
        row.addWidget(close_btn)

        self._layout.addWidget(bar)

        # Thin divider line
        line = QWidget()
        line.setFixedHeight(1)
        line.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        line.setStyleSheet("background: rgba(57,255,20,0.18); border-radius:1px;")
        self._layout.addWidget(line)

    def _build_orb_section(self) -> None:
        panel = _Panel()
        col   = QVBoxLayout(panel)
        col.setContentsMargins(20, 24, 20, 24)
        col.setSpacing(20)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._orb = VoiceOrb()
        col.addWidget(self._orb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._btn = QPushButton("ACTIVATE")
        self._btn.setObjectName("activateBtn")
        self._btn.setProperty("active", "false")
        self._btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._btn.clicked.connect(self._on_toggle)

        self._btn_glow = QGraphicsDropShadowEffect()
        self._btn_glow.setBlurRadius(0)
        self._btn_glow.setOffset(0, 0)
        self._btn_glow.setColor(QColor(57, 255, 20, 0))
        self._btn.setGraphicsEffect(self._btn_glow)

        col.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._layout.addWidget(panel, stretch=3)

    def _build_terminal(self) -> None:
        wrap = QWidget()
        wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        col  = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(5)

        hdr = QLabel("▸ ACTION LOG")
        hdr.setObjectName("termHdr")
        col.addWidget(hdr)

        self._terminal = QTextEdit()
        self._terminal.setObjectName("terminal")
        self._terminal.setReadOnly(True)
        self._terminal.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        font = QFont()
        font.setFamilies(["JetBrains Mono", "Cascadia Code", "Fira Code",
                          "Consolas", "Courier New"])
        font.setPointSize(11)
        self._terminal.setFont(font)
        col.addWidget(self._terminal)

        self._layout.addWidget(wrap, stretch=2)

    # ── Drag (frameless window move) ──────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event) -> None:
        if (event.buttons() == Qt.MouseButton.LeftButton
                and self._drag_pos is not None):
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_pos = None

    # ── Button toggle ─────────────────────────────────────────────────────────

    def _on_toggle(self) -> None:
        if self._agent_state == "STANDBY":
            self.listener_start_requested.emit()
            self.set_agent_state("ACTIVE")
        else:
            self.listener_stop_requested.emit()
            self.set_agent_state("STANDBY")

    # ── Public API ────────────────────────────────────────────────────────────

    def set_agent_state(self, state: str) -> None:
        if state not in ("ACTIVE", "STANDBY"):
            return
        self._agent_state = state
        active = state == "ACTIVE"

        self._btn.setText("STANDBY" if active else "ACTIVATE")
        self._btn.setProperty("active", "true" if active else "false")
        self._btn.style().unpolish(self._btn)
        self._btn.style().polish(self._btn)

        self._state_lbl.setText(state)
        self._state_lbl.setStyleSheet(
            f"color: {'#39FF14' if active else '#64748b'};"
            "font-family: 'JetBrains Mono','Consolas',monospace;"
            "font-size: 9px; letter-spacing: 3px;"
        )

        if self._btn_glow:
            self._btn_glow.setBlurRadius(28 if active else 0)
            self._btn_glow.setColor(
                QColor(57, 255, 20, 180 if active else 0)
            )

    def set_speaking(self, speaking: bool) -> None:
        self._orb.set_speaking(speaking)

    def append_log(self, text: str) -> None:
        """Thread-safe — can be called from any thread."""
        self._log_signal.emit(text)

    def start_listener(self) -> None:
        if self._agent_state == "STANDBY":
            self._on_toggle()

    def stop_listener(self) -> None:
        if self._agent_state == "ACTIVE":
            self._on_toggle()

    # ── Internal slot (Qt thread only) ───────────────────────────────────────

    def _do_append_log(self, text: str) -> None:
        ts   = datetime.now().strftime("%H:%M:%S")
        self._terminal.moveCursor(QTextCursor.MoveOperation.End)
        self._terminal.insertPlainText(f"[{ts}]  {text}\n")
        self._terminal.moveCursor(QTextCursor.MoveOperation.End)
        self._terminal.ensureCursorVisible()

        doc = self._terminal.document()
        while doc.blockCount() > 400:
            cur = QTextCursor(doc.begin())
            cur.select(QTextCursor.SelectionType.BlockUnderCursor)
            cur.movePosition(
                QTextCursor.MoveOperation.NextBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cur.removeSelectedText()

    # ── Safe close ────────────────────────────────────────────────────────────

    def _safe_close(self) -> None:
        if self._agent_state == "ACTIVE":
            self.listener_stop_requested.emit()
        self._orb._tick_timer.stop()
        self._orb._spawn_timer.stop()
        self.close()

    def closeEvent(self, event) -> None:
        self._safe_close()
        event.accept()


# ── Entry point ───────────────────────────────────────────────────────────────

def launch_cockpit(
    on_start=None,
    on_stop=None,
) -> tuple["QApplication", "CockpitUI"]:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    ui = CockpitUI()
    if on_start:
        ui.listener_start_requested.connect(on_start)
    if on_stop:
        ui.listener_stop_requested.connect(on_stop)

    ui.show()
    return app, ui


if __name__ == "__main__":
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    app, ui = launch_cockpit()
    ui.append_log("Cockpit initialized.")
    ui.append_log("Awaiting activation...")
    sys.exit(app.exec())
