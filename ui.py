from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import Qt, QRectF, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGraphicsBlurEffect, QGraphicsPixmapItem,
    QGraphicsScene, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel

from core import fonts as jfonts
from ui_web_bridge import Bridge

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if sys.platform == "darwin":
            # See main.py::get_base_dir() — PyInstaller's macOS BUNDLE step
            # puts non-binary `datas` (ui_web/, core/prompt.txt, ...) under
            # Contents/Resources, not next to the executable in Contents/MacOS.
            resources = exe_dir.parent / "Resources"
            if resources.exists():
                return resources
        return exe_dir
    return Path(__file__).resolve().parent

def _user_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Packaged installs commonly live under Program Files, which standard
        # users can't write to — keep user data in the per-user app data dir.
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "JARVIS"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "JARVIS"
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = _user_data_dir() / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

# TEMP debug logging for the QWebEngineView "file may have moved" launch
# issue on Windows — remove once root-caused (see CLAUDE.md bugfixing rule).
_DEBUG_LOG_PATH = _user_data_dir() / "webview_debug.log"

def _debug_log(msg: str) -> None:
    try:
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

_DEFAULT_W, _DEFAULT_H = 1600, 1000
_MIN_W,     _MIN_H     = 820, 580

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    BG        = "#00060a"
    PANEL     = "#010d14"
    PANEL2    = "#010f18"
    BORDER    = "#0d3347"
    BORDER_B  = "#1a5c7a"
    BORDER_A  = "#0f4060"
    PRI       = "#14c8ff"
    PRI_DIM   = "#0d5aa8"
    PRI_GHO   = "#001f2e"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    MUTED_C   = "#ff3366"
    MIST      = "#0accff"
    BLOCK     = "#19aae6"
    CORE      = "#ddeeff"
    TEXT      = "#bfe0ff"
    TEXT_DIM  = "#2a6ea8"
    TEXT_MED  = "#5aa8e0"
    WHITE     = "#ddeeff"
    DARK      = "#000d14"
    BAR_BG    = "#011520"


class G:
    """Palette matching the new glass HUD (ui_web/hud.css) — used by the
    native Preferences overlay (OnboardingOverlay), the one Qt-widget
    surface still shown on top of the web-based main window."""
    PANEL_BG   = "rgba(6, 11, 19, 250)"
    PANEL_BG2  = "rgba(4, 8, 14, 250)"
    BORDER     = "rgba(120, 210, 255, 70)"
    BORDER_HI  = "rgba(140, 215, 255, 130)"
    HAIRLINE   = "rgba(140, 200, 255, 40)"
    ACCENT     = "#4fd8ff"
    ACCENT_DIM = "#2a86ab"
    ACCENT_GHO = "rgba(79, 216, 255, 30)"
    TEXT       = "#e8f4ff"
    TEXT_DIM   = "rgba(170, 215, 250, 145)"
    TEXT_FAINT = "rgba(160, 210, 245, 110)"
    FIELD_BG   = "rgba(3, 7, 13, 235)"
    GREEN      = "#54e6a8"
    AMBER      = "#ffb454"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


def _paint_glass_panel(widget: QWidget, bg: QColor, border: QColor, radius: int) -> None:
    """Fill+stroke a rounded rect covering `widget` — the actual background
    for every floating overlay in this file (SetupOverlay, OnboardingOverlay,
    RemoteKeyOverlay). These are frameless, WA_TranslucentBackground
    top-level QWidgets; relying on WA_StyledBackground + a QSS `background`/
    `border-radius` alone to paint that top-level fill was found to render
    fully transparent (confirmed on macOS — the stylesheet-driven primitive
    paint for a frameless translucent top-level widget's own background
    doesn't reliably composite, independent of WA_TranslucentBackground
    being set correctly). Painting the fill directly via QPainter in each
    overlay's paintEvent, called before its child widgets paint, sidesteps
    the style engine for this one shape and is the guaranteed-to-render
    fallback. Child widgets (labels, fields, buttons) keep using their own
    QSS as normal — only the outer panel shape needed this."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, QBrush(bg))
    pen = QPen(border)
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.drawPath(path)
    painter.end()


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0   
        self.gpu  = -1.0  
        self.tmp  = -1.0  
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free, works on all platforms if installed
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess)
        if _OS == "Windows":
            try:
                import wmi  # type: ignore
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class _CameraStreamWindow(QWidget):
    """Top-level floating window showing the live camera feed.

    The new HTML HUD has no camera panel (design gap, see plan) — this stays
    a native floating window, migrated verbatim from the old embedded
    `_hud_cam_stack` page-1 widget in MainWindow.__init__.
    """

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #000308;")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 5, 8, 5)
        title = QLabel("◈  CAMERA FEED")
        title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕  CLOSE")
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        close_btn.clicked.connect(self.closed.emit)
        hdr.addWidget(close_btn)
        v.addLayout(hdr)
        self._live_lbl = QLabel()
        self._live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._live_lbl.setStyleSheet("background: transparent;")
        self._live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        v.addWidget(self._live_lbl, stretch=1)

    def set_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._live_lbl.width(), self._live_lbl.height()
            if w > 1 and h > 1:
                self._live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def clear(self) -> None:
        self._live_lbl.clear()


class SetupOverlay(QWidget):
    # Emits a single dict: {"provider": str, "gemini_key": str, "openai_key": str,
    # "anthropic_key": str, "os": str}
    done = pyqtSignal(dict)

    _OW, _OH = 460, 560
    _PROVIDERS = [("gemini", "Gemini"), ("openai", "OpenAI"), ("anthropic", "Claude")]

    def __init__(self, parent=None):
        super().__init__(parent)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected
        self._sel_provider = "gemini"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            family = jfonts.HEADER_BOLD_FAMILY if bold else "Courier New"
            w.setFont(QFont(family, font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        def _key_field(placeholder: str) -> QLineEdit:
            field = QLineEdit()
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText(placeholder)
            field.setFont(QFont("Courier New", 10))
            field.setFixedHeight(32)
            field.setStyleSheet(f"""
                QLineEdit {{
                    background: #000d12; color: {C.TEXT};
                    border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
                }}
                QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
            """)
            return field

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure J.A.R.V.I.S. before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        # ── AI provider picker ──────────────────────────────────────────────
        layout.addWidget(_lbl("AI PROVIDER", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        _provider_note = _lbl(
            "Gemini also powers voice — its key is required no matter which "
            "provider you pick as the AI brain (Claude has no voice API).",
            7, color=C.PRI_DIM, align=Qt.AlignmentFlag.AlignLeft
        )
        _provider_note.setWordWrap(True)
        layout.addWidget(_provider_note)

        provider_row = QHBoxLayout(); provider_row.setSpacing(6)
        self._provider_btns: dict[str, QPushButton] = {}
        for key, label in self._PROVIDERS:
            btn = QPushButton(label)
            btn.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel_ai(k))
            provider_row.addWidget(btn)
            self._provider_btns[key] = btn
        layout.addLayout(provider_row)
        layout.addSpacing(8)

        # ── API key fields (Gemini always visible; OpenAI/Claude conditional) ──
        layout.addWidget(_lbl("GEMINI API KEY  (required — powers voice)", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = _key_field("AIza…")
        layout.addWidget(self._key_input)
        layout.addSpacing(6)

        self._openai_label = _lbl("OPENAI API KEY", 8, color=C.TEXT_DIM,
                                   align=Qt.AlignmentFlag.AlignLeft)
        self._openai_input = _key_field("sk-…")
        layout.addWidget(self._openai_label)
        layout.addWidget(self._openai_input)
        layout.addSpacing(6)

        self._anthropic_label = _lbl("ANTHROPIC API KEY", 8, color=C.TEXT_DIM,
                                      align=Qt.AlignmentFlag.AlignLeft)
        self._anthropic_input = _key_field("sk-ant-…")
        layout.addWidget(self._anthropic_label)
        layout.addWidget(self._anthropic_input)
        layout.addSpacing(6)

        self._sel_ai(self._sel_provider)  # applies styling + initial field visibility

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {G.HAIRLINE};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("OPERATING SYSTEM", 8, color=C.TEXT_DIM,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows","⊞  Windows"),("mac","  macOS"),("linux","🐧  Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def paintEvent(self, event) -> None:
        _paint_glass_panel(self, QColor(0, 6, 10, 245), qcol(C.BORDER_B), 6)
        super().paintEvent(event)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows":(C.PRI,"#001a22"),"mac":(C.ACC2,"#1a1400"),"linux":(C.GREEN,"#001a0d")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _sel_ai(self, key: str):
        self._sel_provider = key
        pal = {"gemini":(C.PRI,"#001a22"),"openai":(C.GREEN,"#001a0d"),"anthropic":(C.ACC2,"#1a1400")}
        for k, btn in self._provider_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: #000d12; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

        # Gemini's key field is always visible (voice always needs it). Only show
        # the OpenAI/Claude fields when that provider is the selected AI brain.
        self._openai_label.setVisible(key == "openai")
        self._openai_input.setVisible(key == "openai")
        self._anthropic_label.setVisible(key == "anthropic")
        self._anthropic_input.setVisible(key == "anthropic")

    def _mark_invalid(self, field: QLineEdit) -> None:
        field.setStyleSheet(
            field.styleSheet() + f" QLineEdit {{ border: 1px solid {C.RED}; }}"
        )

    def _submit(self):
        gemini_key    = self._key_input.text().strip()
        openai_key    = self._openai_input.text().strip()
        anthropic_key = self._anthropic_input.text().strip()

        ok = True
        if not gemini_key:
            self._mark_invalid(self._key_input)
            ok = False
        if self._sel_provider == "openai" and not openai_key:
            self._mark_invalid(self._openai_input)
            ok = False
        if self._sel_provider == "anthropic" and not anthropic_key:
            self._mark_invalid(self._anthropic_input)
            ok = False
        if not ok:
            return

        self.done.emit({
            "provider":       self._sel_provider,
            "gemini_key":     gemini_key,
            "openai_key":     openai_key,
            "anthropic_key":  anthropic_key,
            "os":             self._sel_os,
        })


class OnboardingOverlay(QWidget):
    # Emits a single dict: {"startup_news": bool, "startup_weather": bool,
    # "weather_city": str, "followed_topics": list[str], "language": str, "voice": str}
    done   = pyqtSignal(dict)
    closed = pyqtSignal()   # cancelled without changes (only used when closable=True)

    _OW, _OH = 460, 900  # wide/tall enough for the language + voice + accent/style/pace dropdowns + vault path

    def __init__(self, parent=None, initial: dict | None = None, closable: bool = False):
        super().__init__(parent)

        initial = initial or {}
        self._closable     = closable
        self._sel_news     = initial.get("startup_news", True)
        self._sel_weather  = initial.get("startup_weather", False)
        self._init_city    = initial.get("weather_city", "")
        self._init_topics  = ", ".join(initial.get("followed_topics", []))

        from memory import vault_manager as _vm
        self._init_vault_path = str(_vm.get_vault_path())

        # The panel's content can exceed a small/laptop screen's height (it
        # has grown to include language + voice + accent/style/pace +
        # topics + vault path), so everything scrolls inside a QScrollArea
        # rather than being clipped. The outer widget keeps the panel's
        # background/border; the scroll area and its inner content widget
        # stay transparent so that background shows through.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                border: none;
                margin: 4px 2px 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {G.BORDER_HI};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(8)

        def _lbl(txt, font_size=9, bold=False, color=G.ACCENT,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            family = jfonts.HEADER_BOLD_FAMILY if bold else "Courier New"
            w.setFont(QFont(family, font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        def _text_field(placeholder: str) -> QLineEdit:
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            field.setFont(QFont("Courier New", 10))
            field.setFixedHeight(34)
            field.setStyleSheet(f"""
                QLineEdit {{
                    background: {G.FIELD_BG}; color: {G.TEXT};
                    border: 1px solid {G.BORDER}; border-radius: 10px; padding: 4px 10px;
                }}
                QLineEdit:focus {{ border: 1px solid {G.ACCENT}; }}
            """)
            return field

        def _combo_field() -> QComboBox:
            combo = QComboBox()
            combo.setFont(QFont("Courier New", 10))
            combo.setFixedHeight(34)
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            combo.setStyleSheet(f"""
                QComboBox {{
                    background: {G.FIELD_BG}; color: {G.TEXT};
                    border: 1px solid {G.BORDER}; border-radius: 10px; padding: 4px 10px;
                }}
                QComboBox:focus {{ border: 1px solid {G.ACCENT}; }}
                QComboBox::drop-down {{ border: none; width: 22px; }}
                QComboBox QAbstractItemView {{
                    background: {G.PANEL_BG2}; color: {G.TEXT};
                    border: 1px solid {G.BORDER_HI};
                    selection-background-color: {G.ACCENT_GHO};
                    selection-color: {G.ACCENT};
                    outline: none;
                }}
            """)
            return combo

        layout.addWidget(_lbl("PREFERENCES" if closable else "PERSONALISE J.A.R.V.I.S.", 14, True))
        layout.addWidget(_lbl("Choose what Jarvis does when it starts up.", 9, color=G.TEXT_DIM))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {G.HAIRLINE};"); layout.addWidget(sep)
        layout.addSpacing(4)

        # ── News toggle ──────────────────────────────────────────────────────
        layout.addWidget(_lbl("DAILY NEWS SUMMARY", 8, color=G.TEXT_FAINT,
                               align=Qt.AlignmentFlag.AlignLeft))
        news_row = QHBoxLayout(); news_row.setSpacing(6)
        self._news_btns: dict[bool, QPushButton] = {}
        for val, label in [(True, "Yes"), (False, "No")]:
            btn = QPushButton(label)
            btn.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 9, QFont.Weight.Bold))
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, v=val: self._sel_news_toggle(v))
            news_row.addWidget(btn)
            self._news_btns[val] = btn
        layout.addLayout(news_row)
        layout.addSpacing(8)

        # ── Weather toggle + city field ──────────────────────────────────────
        layout.addWidget(_lbl("DAILY WEATHER REPORT", 8, color=G.TEXT_FAINT,
                               align=Qt.AlignmentFlag.AlignLeft))
        weather_row = QHBoxLayout(); weather_row.setSpacing(6)
        self._weather_btns: dict[bool, QPushButton] = {}
        for val, label in [(True, "Yes"), (False, "No")]:
            btn = QPushButton(label)
            btn.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 9, QFont.Weight.Bold))
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, v=val: self._sel_weather_toggle(v))
            weather_row.addWidget(btn)
            self._weather_btns[val] = btn
        layout.addLayout(weather_row)
        layout.addSpacing(6)

        self._city_label = _lbl("CITY", 8, color=G.TEXT_FAINT, align=Qt.AlignmentFlag.AlignLeft)
        self._city_input = _text_field("e.g. New York")
        self._city_input.setText(self._init_city)
        layout.addWidget(self._city_label)
        layout.addWidget(self._city_input)
        layout.addSpacing(8)

        self._sel_news_toggle(self._sel_news)
        self._sel_weather_toggle(self._sel_weather)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {G.HAIRLINE};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        # ── Preferred language ──────────────────────────────────────────────
        layout.addWidget(_lbl("PREFERRED LANGUAGE", 8, color=G.TEXT_FAINT,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._lang_combo = _combo_field()
        from core.languages import SUPPORTED_LANGUAGES
        init_lang = initial.get("language", "auto")
        for code, name, _locale in SUPPORTED_LANGUAGES:
            self._lang_combo.addItem(name, userData=code)
        idx = self._lang_combo.findData(init_lang)
        self._lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self._lang_combo)
        layout.addSpacing(8)

        # ── Voice ─────────────────────────────────────────────────────────────
        layout.addWidget(_lbl("VOICE", 8, color=G.TEXT_FAINT,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._voice_combo = _combo_field()
        from core.cloud_llm import get_provider
        from core.voices import (
            SUPPORTED_VOICES, DEFAULT_VOICE,
            OPENAI_VOICES, DEFAULT_OPENAI_VOICE,
        )
        # Gemini and OpenAI each have their own voice catalog — show
        # whichever one applies to the currently configured AI provider.
        self._voice_provider = get_provider()
        if self._voice_provider == "openai":
            voice_choices, default_voice = OPENAI_VOICES, DEFAULT_OPENAI_VOICE
        else:
            voice_choices, default_voice = SUPPORTED_VOICES, DEFAULT_VOICE
        init_voice = initial.get("voice", default_voice)
        for name, style in voice_choices:
            self._voice_combo.addItem(f"{name}  —  {style}", userData=name)
        idx = self._voice_combo.findData(init_voice)
        self._voice_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self._voice_combo)
        layout.addSpacing(8)

        # ── Accent / Style / Pace ────────────────────────────────────────────────
        # All three are Gemini-only: implemented as natural-language prompt
        # instructions to Gemini's speech APIs (no structured field exists —
        # see core/accents.py, core/styles.py, core/pace.py), so they have no
        # effect on OpenAI's Realtime API voices. Hidden entirely rather than
        # shown-but-inert when OpenAI is the active provider.
        self._delivery_label = _lbl("ACCENT", 8, color=G.TEXT_FAINT,
                                     align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._delivery_label)
        self._accent_combo = _combo_field()
        from core.accents import SUPPORTED_ACCENTS, DEFAULT_ACCENT
        init_accent = initial.get("accent", DEFAULT_ACCENT)
        for code, name, _instr in SUPPORTED_ACCENTS:
            self._accent_combo.addItem(name, userData=code)
        idx = self._accent_combo.findData(init_accent)
        self._accent_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self._accent_combo)
        layout.addSpacing(8)

        self._style_label = _lbl("STYLE", 8, color=G.TEXT_FAINT,
                                  align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._style_label)
        self._style_combo = _combo_field()
        from core.styles import SUPPORTED_STYLES, DEFAULT_STYLE
        init_style = initial.get("style", DEFAULT_STYLE)
        for code, name, _instr in SUPPORTED_STYLES:
            self._style_combo.addItem(name, userData=code)
        idx = self._style_combo.findData(init_style)
        self._style_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self._style_combo)
        layout.addSpacing(8)

        self._pace_label = _lbl("PACE", 8, color=G.TEXT_FAINT,
                                 align=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._pace_label)
        self._pace_combo = _combo_field()
        from core.pace import SUPPORTED_PACES, DEFAULT_PACE
        init_pace = initial.get("pace", DEFAULT_PACE)
        for code, name, _instr in SUPPORTED_PACES:
            self._pace_combo.addItem(name, userData=code)
        idx = self._pace_combo.findData(init_pace)
        self._pace_combo.setCurrentIndex(idx if idx >= 0 else 0)
        layout.addWidget(self._pace_combo)
        layout.addSpacing(8)

        if self._voice_provider == "openai":
            for w in (self._delivery_label, self._accent_combo,
                      self._style_label, self._style_combo,
                      self._pace_label, self._pace_combo):
                w.setVisible(False)

        # Connected after every combo's setCurrentIndex() so restoring saved
        # prefs on open doesn't itself trigger a preview — only user changes
        # do. Shared timer: changing voice, accent, style, or pace previews
        # the resulting combination.
        self._voice_preview_timer = QTimer(self)
        self._voice_preview_timer.setSingleShot(True)
        self._voice_preview_timer.timeout.connect(self._play_voice_preview)
        for combo in (self._voice_combo, self._accent_combo, self._style_combo, self._pace_combo):
            combo.currentIndexChanged.connect(lambda _: self._voice_preview_timer.start(250))

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"color: {G.HAIRLINE};"); layout.addWidget(sep3)
        layout.addSpacing(4)

        # ── Followed topics ──────────────────────────────────────────────────
        layout.addWidget(_lbl("TOPICS TO FOLLOW (optional)", 8, color=G.TEXT_FAINT,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._topics_input = _text_field("e.g. F1, AI research, Bitcoin")
        self._topics_input.setText(self._init_topics)
        layout.addWidget(self._topics_input)
        layout.addSpacing(8)

        # ── Vault location ────────────────────────────────────────────────────
        layout.addWidget(_lbl("MEMORY VAULT FOLDER", 8, color=G.TEXT_FAINT,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._vault_input = _text_field("Path to Obsidian vault folder")
        self._vault_input.setText(self._init_vault_path)
        layout.addWidget(self._vault_input)
        layout.addWidget(_lbl(
            "Repoints Jarvis here — existing notes are NOT moved or copied.",
            7, color=G.TEXT_FAINT, align=Qt.AlignmentFlag.AlignLeft
        ))
        layout.addSpacing(12)

        start_btn = QPushButton("▸  START" if not closable else "▸  SAVE")
        start_btn.setFont(QFont(jfonts.HEADER_BOLD_FAMILY, 10, QFont.Weight.Bold))
        start_btn.setFixedHeight(38)
        start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {G.ACCENT_GHO}; color: {G.ACCENT};
                border: 1px solid {G.BORDER_HI}; border-radius: 12px;
            }}
            QPushButton:hover {{
                background: rgba(79, 216, 255, 55); border: 1px solid {G.ACCENT};
            }}
        """)
        start_btn.clicked.connect(self._submit)
        layout.addWidget(start_btn)

        skip_btn = QPushButton("Cancel" if closable else "Skip for now")
        skip_btn.setFont(QFont("Courier New", 8))
        skip_btn.setFlat(True)
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {G.TEXT_DIM}; border: none; }}
            QPushButton:hover {{ color: {G.TEXT}; }}
        """)
        skip_btn.clicked.connect(self._cancel if closable else self._skip)
        layout.addWidget(skip_btn)

    def paintEvent(self, event) -> None:
        _paint_glass_panel(self, QColor(6, 11, 19, 250), QColor(120, 210, 255, 70), 20)
        super().paintEvent(event)

    def _toggle_style(self, btns: dict, selected):
        for k, btn in btns.items():
            if k == selected:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {G.ACCENT}; color: #001522;
                        border: none; border-radius: 10px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {G.FIELD_BG}; color: {G.TEXT_DIM};
                        border: 1px solid {G.BORDER}; border-radius: 10px;
                    }}
                    QPushButton:hover {{ color: {G.TEXT}; border: 1px solid {G.BORDER_HI}; }}
                """)

    def _sel_news_toggle(self, val: bool):
        self._sel_news = val
        self._toggle_style(self._news_btns, val)

    def _sel_weather_toggle(self, val: bool):
        self._sel_weather = val
        self._toggle_style(self._weather_btns, val)
        self._city_label.setVisible(val)
        self._city_input.setVisible(val)

    def _play_voice_preview(self):
        from memory.config_manager import get_gemini_key

        # OpenAI's Realtime API has no cheap one-shot preview endpoint (only
        # a full streaming session) — and OpenAI voice names aren't valid
        # Gemini voice IDs anyway, so previewing is only supported for the
        # Gemini catalog.
        if self._voice_provider == "openai":
            return

        voice_name = self._voice_combo.currentData()
        accent     = self._accent_combo.currentData()
        style      = self._style_combo.currentData()
        pace       = self._pace_combo.currentData()
        api_key    = get_gemini_key()
        if not voice_name or not api_key:
            return

        def _run():
            try:
                from core.voice_preview import play_preview
                play_preview(api_key, voice_name, accent, style, pace)
            except Exception as e:
                print(f"[VoicePreview] Error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _collect(self) -> dict:
        topics = [t.strip() for t in self._topics_input.text().split(",")]
        topics = list(dict.fromkeys(t for t in topics if t))  # dedupe, drop empties
        return {
            "startup_news":    self._sel_news,
            "startup_weather": self._sel_weather,
            "weather_city":    self._city_input.text().strip() if self._sel_weather else "",
            "followed_topics": topics,
            "language":        self._lang_combo.currentData(),
            "voice":           self._voice_combo.currentData(),
            "accent":          self._accent_combo.currentData(),
            "style":           self._style_combo.currentData(),
            "pace":            self._pace_combo.currentData(),
            "vault_path":      self._vault_input.text().strip() or self._init_vault_path,
        }

    def _submit(self):
        self.done.emit(self._collect())

    def _skip(self):
        from core.voices import DEFAULT_VOICE, DEFAULT_OPENAI_VOICE
        from core.accents import DEFAULT_ACCENT
        from core.styles import DEFAULT_STYLE
        from core.pace import DEFAULT_PACE
        skip_voice = DEFAULT_OPENAI_VOICE if self._voice_provider == "openai" else DEFAULT_VOICE
        self.done.emit({
            "startup_news":    True,
            "startup_weather": False,
            "weather_city":    "",
            "followed_topics": [],
            "language":        "auto",
            "voice":           skip_voice,
            "accent":          DEFAULT_ACCENT,
            "style":           DEFAULT_STYLE,
            "pace":            DEFAULT_PACE,
            "vault_path":      self._init_vault_path,
        })

    def _cancel(self):
        self.closed.emit()


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont(jfonts.DISPLAY_FAMILY, 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def paintEvent(self, event) -> None:
        _paint_glass_panel(self, QColor(0, 4, 12, 242), qcol(C.BORDER_B), 14)
        super().paintEvent(event)

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont(jfonts.DISPLAY_FAMILY, 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class LoadingOverlay(QWidget):
    """Opaque splash shown while ui_web/index.html loads in the
    QWebEngineView. Chromium paints the HTML/CSS/JS page progressively
    (fonts, canvas waveform, stat tiles each arriving on their own frame),
    which reads as the HUD "popping in piece by piece" — this covers the
    whole window with a single static screen until loading has settled,
    so the user sees nothing until the real HUD is fully painted.
    Deliberately opaque (unlike every other overlay in this file, which is
    WA_TranslucentBackground) — it needs to fully hide the webview
    underneath while that's still rendering.

    Renders an Apple-style frosted-glass backdrop rather than a flat QSS
    color: relying on WA_StyledBackground + a stylesheet `background` on a
    frameless top-level QWidget was observed rendering fully transparent
    (a Cocoa layer-backing quirk on macOS — frameless windows don't always
    get an opaque backing store from a stylesheet fill alone), so this
    paints its own background directly in paintEvent to guarantee it's
    actually opaque regardless of platform. set_backdrop() (called by
    MainWindow right before this splash is shown) supplies a blurred grab
    of whatever was on screen behind the window at that moment — a
    one-shot still, not a live vibrancy surface, which is enough for a
    splash this short-lived."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Every other floating overlay in this file gets this via
        # _make_floating() (LoadingOverlay manages its own window flags
        # separately, since it isn't positioned via _reposition_floats).
        # Without it, a frameless top-level QWidget on macOS never gets a
        # real alpha-compositing surface at all, so nothing paints through
        # — not the old QSS background, not this class's own paintEvent
        # fill either. Painting fully-opaque (alpha 255) pixels inside a
        # translucent-capable window still reads as solid, so this is safe
        # to combine with the "opaque splash" intent.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._backdrop: QPixmap | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch()

        title = QLabel("J.A.R.V.I.S")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont(jfonts.DISPLAY_FAMILY, 32, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {G.ACCENT}; background: transparent; letter-spacing: 6px;")
        lay.addWidget(title)

        self._sub = QLabel("INITIALISING SYSTEMS")
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub.setFont(QFont("Courier New", 10))
        self._sub.setStyleSheet(f"color: {G.TEXT_DIM}; background: transparent; letter-spacing: 3px; margin-top: 14px;")
        lay.addWidget(self._sub)

        bar_row = QHBoxLayout()
        bar_row.addStretch()
        self._bar = QProgressBar()
        self._bar.setFixedWidth(220)
        self._bar.setFixedHeight(3)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 0)   # indeterminate/marquee
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {G.FIELD_BG};
                border: none;
                border-radius: 1px;
                margin-top: 18px;
            }}
            QProgressBar::chunk {{
                background: {G.ACCENT};
                border-radius: 1px;
            }}
        """)
        bar_row.addWidget(self._bar)
        bar_row.addStretch()
        lay.addLayout(bar_row)

        lay.addStretch()

    def set_backdrop(self, pixmap: QPixmap | None) -> None:
        """Blur `pixmap` (a grab of whatever was on screen behind this
        window, taken by the caller right before this splash appears) and
        use it as the glass backdrop. Falls back to a flat fill in
        paintEvent if this is never called or the grab failed/was empty."""
        if pixmap is None or pixmap.isNull():
            self._backdrop = None
            self.update()
            return
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(pixmap)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(48)
        item.setGraphicsEffect(blur)
        scene.addItem(item)
        blurred = QPixmap(pixmap.size())
        blurred.fill(Qt.GlobalColor.black)
        painter = QPainter(blurred)
        scene.render(painter)
        painter.end()
        self._backdrop = blurred
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._backdrop is not None:
            painter.drawPixmap(self.rect(), self._backdrop)
        else:
            painter.fillRect(self.rect(), QColor(6, 11, 19, 255))
        # glass tint over the blurred backdrop, matching G.PANEL_BG's hue,
        # so text stays legible regardless of what was behind the window
        painter.fillRect(self.rect(), QColor(6, 11, 19, 205))
        painter.end()


class MainWindow(QMainWindow):
    _log_sig     = pyqtSignal(str)
    _state_sig   = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _reconfig_sig = pyqtSignal()          # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)   # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)   # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)  # live camera frame → HUD area

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path
        self.setWindowTitle("J.A.R.V.I.S V1")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_settings_saved = None   # callable: () -> None — Preferences panel saved
        self._muted            = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._prefs_muted_before = False
        self._overlay: SetupOverlay | OnboardingOverlay | None = None

        # The whole HUD is now an HTML/CSS/JS page (ui_web/index.html) rendered
        # by a QWebEngineView, bridged to this class via QWebChannel — see
        # ui_web_bridge.py::Bridge. All existing Python logic (main.py,
        # actions/*) is unchanged; only this presentation layer changed.
        self.setAcceptDrops(True)  # file drop — the new design has no visible
                                    # drop zone, so this keeps drag-and-drop
                                    # working invisibly over the whole window
        self._webview = QWebEngineView()
        self.setCentralWidget(self._webview)

        self._bridge = Bridge(self)
        self._channel = QWebChannel(self._webview.page())
        self._channel.registerObject("bridge", self._bridge)
        self._webview.page().setWebChannel(self._channel)

        # Loading splash — covers the window while the web HUD paints
        # progressively underneath, then gets torn down once it's settled.
        # See LoadingOverlay's docstring for why it's opaque rather than
        # translucent like every other overlay here.
        self._loading = LoadingOverlay()
        self._loading.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._web_retried = False
        self._webview.loadFinished.connect(self._on_web_load_finished)
        index_path = BASE_DIR / "ui_web" / "index.html"
        _debug_log(
            f"BASE_DIR={BASE_DIR} index_path={index_path} exists={index_path.exists()} "
            f"frozen={getattr(sys, 'frozen', False)} executable={sys.executable}"
        )
        self._webview.setUrl(QUrl.fromLocalFile(str(index_path)))
        self._loading.setGeometry(self.geometry())
        # One-shot grab of whatever's on screen behind the splash, blurred
        # in LoadingOverlay.set_backdrop() for the Apple-glass look — taken
        # right before show() since it needs to capture the desktop as it
        # currently is, not this (not-yet-painted) window.
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            g = self._loading.geometry()
            self._loading.set_backdrop(screen.grabWindow(0, g.x(), g.y(), g.width(), g.height()))
        self._loading.show()

        # Camera windows (native, floating — see plan: the new design has no
        # camera panel, so these stay outside the web view entirely)
        self._cam_preview = _CameraPreview(self)
        self._make_floating(self._cam_preview, tool=True)
        self._cam_stream_win = _CameraStreamWindow(self)
        self._make_floating(self._cam_stream_win)
        self._cam_stream_win.closed.connect(self.stop_camera_stream)

        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._on_log)
        self._state_sig.connect(self._apply_state)
        self._content_sig.connect(self._on_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._cam_stop = threading.Event()

        self._ready = False   # flips to True in _finish_ready(); the setup-
                                # overlay check itself waits for the web HUD
                                # to finish loading, see _on_web_load_finished

    def _on_web_load_finished(self, ok: bool):
        """QWebEngineView.loadFinished — the DOM has parsed, but hud.js is
        still wiring the bridge/rendering the waveform/stat tiles for another
        frame or two, so a short settle delay before dropping the loading
        splash keeps the reveal from showing that pop-in too."""
        index_path = BASE_DIR / "ui_web" / "index.html"
        _debug_log(
            f"loadFinished ok={ok} current_url={self._webview.url().toString()} "
            f"index_exists_now={index_path.exists()}"
        )
        if not ok and not self._web_retried:
            self._web_retried = True
            _debug_log("load failed — retrying once")
            QTimer.singleShot(500, lambda: self._webview.setUrl(
                QUrl.fromLocalFile(str(index_path))
            ))
            return
        QTimer.singleShot(300, self._dismiss_loading)

    def _dismiss_loading(self):
        if self._loading is not None:
            self._loading.hide()
            self._loading.deleteLater()
            self._loading = None
        if not self._ready:
            self._ready = self._check_config()
            if not self._ready:
                self._show_setup()

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        self._reposition_floats()

    # --- Live camera stream — native floating window ------------------------
    def _on_cam_stream(self, start: bool) -> None:
        if start:
            self._cam_stream_win.setGeometry(self.geometry())
            self._cam_stream_win.show()
            self._cam_stream_win.raise_()
        else:
            self._cam_stream_win.hide()
            self._cam_stream_win.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        self._cam_stream_win.set_frame(data)

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = Path.home() / "Desktop"

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "J.A.R.V.I.S.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "J.A.R.V.I.S.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._bridge.push_log("SYS", "Desktop shortcut created.")
        except Exception as e:
            self._bridge.push_log("ERR", f"Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _make_floating(self, widget: QWidget, *, tool: bool = False) -> None:
        """Convert a widget that used to be a child-stacked overlay
        (positioned via setGeometry() over the old QWidget central-widget
        tree) into a genuine top-level floating window. Needed because
        native child widgets don't reliably composite on top of a
        QWebEngineView (it owns its own native/GPU surface) — see plan
        "Overlay windowing"."""
        flags = (Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint)
        if tool:
            flags |= Qt.WindowType.Tool
        widget.setWindowFlags(flags)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _reposition_floats(self) -> None:
        """Keep every native floating window aligned over the main window —
        top-level windows don't auto-follow a 'parent' the way child
        widgets did, so this must be called on move/resize."""
        if self._loading is not None and self._loading.isVisible():
            self._loading.setGeometry(self.geometry())
        if self._overlay is not None and self._overlay.isVisible():
            ow = getattr(type(self._overlay), "_OW", 460)
            oh = getattr(type(self._overlay), "_OH", 390)
            self._position_overlay(self._overlay, ow, oh)
        if self._remote_overlay is not None and self._remote_overlay.isVisible():
            self._position_overlay(self._remote_overlay, RemoteKeyOverlay._OW, RemoteKeyOverlay._OH)
        g = self.geometry()
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            g.x() + g.width()  - pw - 24,
            g.y() + g.height() - ph - 90,
            pw, ph,
        )
        if self._cam_stream_win.isVisible():
            self._cam_stream_win.setGeometry(g)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_floats()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._reposition_floats()

    # --- File drop — the new design has no visible drop zone, so this is
    # the only affordance for it besides the click-to-browse icon in the
    # HTML pill (see _browse_for_file / Bridge.requestFileDialog). ---------
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._on_file_selected(path)

    def _update_metrics(self):
        snap = _metrics.snapshot()
        cpu, mem, net, gpu, tmp = snap["cpu"], snap["mem"], snap["net"], snap["gpu"], snap["tmp"]

        if net < 1.0:
            net_str = f"{net*1024:.0f} KB/s"
        else:
            net_str = f"{net:.1f} MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = 100%

        stats = [
            {"label": "CPU", "value": f"{cpu:.0f}%", "pct": cpu},
            {"label": "MEM", "value": f"{mem:.0f}%", "pct": mem, "warn": mem > 75},
            {"label": "NET", "value": net_str, "pct": net_pct},
        ]
        if gpu >= 0:
            stats.append({"label": "GPU", "value": f"{gpu:.0f}%", "pct": gpu})
        else:
            stats.append({"label": "GPU", "value": "N/A", "pct": 0, "na": True})
        if tmp >= 0:
            stats.append({"label": "TMP", "value": f"{tmp:.0f}°C", "pct": min(100, tmp)})
        else:
            stats.append({"label": "TMP", "value": "N/A", "pct": 0, "na": True})

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            uptime = f"{h:02d}:{m:02d}"
        except Exception:
            uptime = "--:--"

        try:
            proc = str(len(psutil.pids()))
        except Exception:
            proc = "--"

        os_display = {"Darwin": "macOS"}.get(_OS, _OS)
        self._bridge.push_stats({"stats": stats, "uptime": uptime, "proc": proc, "os": os_display})

    def _send_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._bridge.push_log("YOU", text)
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()

    def _on_log(self, text: str) -> None:
        """Slot for _log_sig — splits main.py/actions' prefixed strings
        ("You: ...", "Jarvis: ...", everything else) into (who, text) for
        the HTML activity card's tag coloring."""
        if text.startswith("You: "):
            who, body = "YOU", text[5:]
        elif text.startswith("Jarvis: "):
            who, body = "JARVIS", text[8:]
        else:
            who, body = "SYS", text
        self._bridge.push_log(who, body)

    def _on_content(self, title: str, text: str) -> None:
        """Slot for _content_sig. The new design has no dedicated content
        panel (design gap, see plan) — folded into the ACTIVITY log as a
        JARVIS-tagged entry instead."""
        body = f"{title}\n{text}" if title else text
        self._bridge.push_log("JARVIS", body)

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        size = _fmt_size(p.stat().st_size)
        self._bridge.push_log("SYS", f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _browse_for_file(self) -> None:
        """Bridge.requestFileDialog() — click-to-browse icon in the input pill."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._on_file_selected(path)

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()
        self._bridge.remoteConnected.emit()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._bridge.push_log("SYS", "Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._bridge.push_log("SYS", "Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        ov = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=self)
        self._make_floating(ov)
        ov.set_new_key_callback(self.on_remote_clicked)
        self._position_overlay(ov, RemoteKeyOverlay._OW, RemoteKeyOverlay._OH)
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._bridge.push_log("SYS", f"Remote key generated — manual: {manual or url}")

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mute(self):
        self._muted = not self._muted
        self._bridge.push_muted(self._muted)
        if self._muted:
            self._apply_state("MUTED")
            self._bridge.push_log("SYS", "Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._bridge.push_log("SYS", "Microphone active.")

    def _apply_state(self, state: str):
        self._bridge.push_state(state)

    def _check_config(self) -> bool:
        from memory.config_manager import is_configured
        from memory.vault_manager import is_onboarded
        try:
            return is_configured() and is_onboarded()
        except Exception:
            return False

    def _position_overlay(self, ov, ow, oh):
        """Center `ov` (a top-level floating window) over this window at its
        preferred (ow, oh) size, shrinking to fit whenever the window is
        smaller than that (small/laptop screens) — content that doesn't fit
        still scrolls internally (see OnboardingOverlay's QScrollArea), this
        only prevents the overlay itself from being clipped by or
        overflowing the window."""
        g = self.geometry()
        margin = 24
        ow = max(240, min(ow, g.width()  - margin))
        oh = max(240, min(oh, g.height() - margin))
        ov.setGeometry(
            g.x() + (g.width()  - ow) // 2,
            g.y() + (g.height() - oh) // 2,
            ow, oh,
        )

    def _close_overlay(self):
        if self._overlay is not None:
            from core.voice_preview import stop_preview
            stop_preview()
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None

    def _show_setup(self):
        from memory.config_manager import is_configured
        try:
            configured = is_configured()
        except Exception:
            configured = False

        self._close_overlay()

        if not configured:
            ov = SetupOverlay(self)
            ow, oh = SetupOverlay._OW, SetupOverlay._OH
            ov.done.connect(self._on_setup_done)
        else:
            ov = OnboardingOverlay(self)
            ow, oh = OnboardingOverlay._OW, OnboardingOverlay._OH
            ov.done.connect(self._on_onboarding_done)

        self._make_floating(ov)
        self._position_overlay(ov, ow, oh)
        ov.show()
        self._overlay = ov

    def _show_onboarding(self):
        from memory import vault_manager
        self._close_overlay()
        ov = OnboardingOverlay(self, initial=vault_manager.DEFAULT_SETTINGS)
        self._make_floating(ov)
        ow, oh = OnboardingOverlay._OW, OnboardingOverlay._OH
        self._position_overlay(ov, ow, oh)
        ov.done.connect(self._on_onboarding_done)
        ov.show()
        self._overlay = ov

    def _show_preferences(self):
        from memory import vault_manager

        self._close_overlay()

        # The voice preview (one-shot Gemini TTS) and the live session's own
        # mic capture/speaker output can talk over each other — mic picks up
        # the preview audio, and both fight over the output device at once.
        # Force-mute for the duration of the panel; restore whatever the
        # mute state was beforehand once it closes.
        self._prefs_muted_before = self._muted
        if not self._muted:
            self._toggle_mute()

        ov = OnboardingOverlay(self, initial=vault_manager.get_settings(), closable=True)
        self._make_floating(ov)
        ow, oh = OnboardingOverlay._OW, OnboardingOverlay._OH
        self._position_overlay(ov, ow, oh)
        ov.done.connect(self._on_preferences_saved)
        ov.closed.connect(self._close_preferences)
        ov.show()
        self._overlay = ov

    def _close_preferences(self):
        self._close_overlay()
        if not self._prefs_muted_before and self._muted:
            self._toggle_mute()

    def _on_preferences_saved(self, result: dict):
        from memory import vault_manager
        result = dict(result)
        vault_path = result.pop("vault_path", None)
        if vault_path:
            vault_manager.set_vault_path(vault_path)
        topics = result.pop("followed_topics", None)
        if topics is not None:
            vault_manager.set_followed_topics(topics)
        vault_manager.save_settings(result)
        self._close_preferences()
        self._bridge.push_log("SYS", "Preferences updated.")
        if self.on_settings_saved:
            self.on_settings_saved()

    def _on_setup_done(self, result: dict):
        from memory.config_manager import save_api_key, save_ai_provider
        from memory.vault_manager import is_onboarded

        provider = result.get("provider", "gemini")
        save_api_key("gemini", result.get("gemini_key", ""))
        if result.get("openai_key"):
            save_api_key("openai", result["openai_key"])
        if result.get("anthropic_key"):
            save_api_key("anthropic", result["anthropic_key"])
        save_ai_provider(provider)

        os_name = result.get("os", "windows")
        os.makedirs(CONFIG_DIR, exist_ok=True)
        cfg = {}
        if API_FILE.exists():
            try:
                cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
            except Exception:
                cfg = {}
        cfg["os_system"] = os_name
        API_FILE.write_text(json.dumps(cfg, indent=4), encoding="utf-8")

        self._bridge.push_log(
            "SYS", f"Initialised. Provider={provider.upper()}. OS={os_name.upper()}."
        )

        if not is_onboarded():
            self._show_onboarding()
        else:
            self._finish_ready()

    def _on_onboarding_done(self, result: dict):
        from memory import vault_manager
        result = dict(result)
        vault_path = result.pop("vault_path", None)
        if vault_path:
            vault_manager.set_vault_path(vault_path)
        vault_manager.complete_onboarding(result)
        self._finish_ready()

    def _finish_ready(self):
        self._ready = True
        self._close_overlay()
        self._apply_state("LISTENING")
        self._bridge.push_log("SYS", "JARVIS online.")


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        jfonts.load_fonts()
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._current_file

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_settings_saved(self):
        return self._win.on_settings_saved

    @on_settings_saved.setter
    def on_settings_saved(self, cb):
        self._win.on_settings_saved = cb

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    @property
    def is_ready(self) -> bool:
        return self._win._ready

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")