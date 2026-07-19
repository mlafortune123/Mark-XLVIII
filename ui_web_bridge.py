"""ui_web_bridge.py — the QWebChannel contract between ui_web/hud.js and MainWindow.

One `Bridge(QObject)` instance is registered on the QWebEngineView's page as
"bridge" (see MainWindow._init_webview in ui.py). Every method the new HTML
HUD needs to call into Python is a `pyqtSlot` here; every push Python needs
to make into the page is a `pyqtSignal` here. Keeping this in its own file
(rather than inline in MainWindow) makes the JS<->Python contract reviewable
without wading through the rest of ui.py's widget/window-management code.

Slots forward straight to the MainWindow methods that already implement the
corresponding behaviour (the pre-redesign QPushButton .clicked handlers) —
this file has no business logic of its own beyond that dispatch.

Boot-order race: MainWindow starts emitting log/state/stats the moment it's
constructed (e.g. "SYS: Initialised..." during the setup flow), but the
QWebEngineView's page load + QWebChannel JS handshake are asynchronous —
early pushes would otherwise be lost since nothing in JS is listening yet.
`push_log`/`push_state`/`push_muted`/`push_stats` (called by MainWindow
instead of emitting the signals directly) keep the latest state in a small
buffer; `requestSync()` (called once by hud.js right after it connects) then
replays it so the page always ends up consistent no matter when it finishes
loading relative to Python's early emits.
"""

from __future__ import annotations

import json

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

_LOG_BUFFER_CAP = 200


class Bridge(QObject):
    # ---- Python -> JS pushes ----
    logAppended   = pyqtSignal(str, str)   # (who, text) — who in {SYS, YOU, JARVIS}
    stateChanged  = pyqtSignal(str)        # raw state string, e.g. SPEAKING/LISTENING/THINKING/SLEEPING
    mutedChanged  = pyqtSignal(bool)
    # JSON-encoded {"stats": [...], "uptime": str, "proc": str, "os": str} — sent as a
    # str, not a dict: pyqtSignal(dict) with this nested list-of-dicts shape doesn't
    # marshal cleanly through QWebChannel (JS ends up with the Python repr() string,
    # not a usable object), so this is JSON-encoded manually instead.
    statsUpdated  = pyqtSignal(str)
    remoteConnected = pyqtSignal()

    def __init__(self, window, parent=None):
        super().__init__(parent)
        self._win = window
        self._log_buffer: list[tuple[str, str]] = []
        self._last_state = "INITIALISING"
        self._last_muted = False
        self._last_stats: dict | None = None

    # ---- buffered pushes (call these from MainWindow instead of emitting directly) ----
    def push_log(self, who: str, text: str) -> None:
        self._log_buffer.append((who, text))
        del self._log_buffer[:-_LOG_BUFFER_CAP]
        self.logAppended.emit(who, text)

    def push_state(self, state: str) -> None:
        self._last_state = state
        self.stateChanged.emit(state)

    def push_muted(self, muted: bool) -> None:
        self._last_muted = muted
        self.mutedChanged.emit(muted)

    def push_stats(self, payload: dict) -> None:
        self._last_stats = payload
        self.statsUpdated.emit(json.dumps(payload))

    # ---- JS -> Python calls ----
    @pyqtSlot()
    def requestSync(self) -> None:
        for who, text in self._log_buffer:
            self.logAppended.emit(who, text)
        self.stateChanged.emit(self._last_state)
        self.mutedChanged.emit(self._last_muted)
        if self._last_stats is not None:
            self.statsUpdated.emit(json.dumps(self._last_stats))

    @pyqtSlot(str)
    def sendText(self, text: str) -> None:
        self._win._send_text(text)

    @pyqtSlot()
    def toggleMute(self) -> None:
        self._win._toggle_mute()

    @pyqtSlot()
    def clickInterrupt(self) -> None:
        self._win._do_interrupt()

    @pyqtSlot()
    def clickRemote(self) -> None:
        self._win._open_remote()

    @pyqtSlot()
    def requestFileDialog(self) -> None:
        self._win._browse_for_file()

    @pyqtSlot()
    def openPreferences(self) -> None:
        self._win._show_preferences()

    @pyqtSlot()
    def toggleFullscreen(self) -> None:
        self._win._toggle_fullscreen()
