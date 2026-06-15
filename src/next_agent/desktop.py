"""Single-process Windows desktop launcher for NextAgentGUI."""

from __future__ import annotations

import os
import sys
import threading
import ctypes
import time
import webbrowser
from pathlib import Path

import webview

from .gui_server import bundled_path, create_server


HOST = "127.0.0.1"
PORT = 0
SETUP_SIZE = (740, 720)
WORKSPACE_SIZE = (1340, 940)
SPLASH_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    * { box-sizing: border-box; }
    html, body { width: 100%; height: 100%; margin: 0; background: #f8f8f6; }
    body { display: grid; place-items: center; color: #252522; font-family: "Segoe UI", sans-serif; }
    main { display: grid; justify-items: center; gap: 12px; }
    .spinner {
      width: 34px; height: 34px; border: 3px solid #dfe3ff; border-top-color: #586cff;
      border-radius: 50%; animation: spin .8s linear infinite; box-shadow: 0 0 28px #6678ff33;
    }
    h1 { margin: 4px 0 0; font-family: Georgia, serif; font-size: 22px; }
    p { margin: 0; color: #8a8a83; font-size: 12px; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body><main><div class="spinner"></div><h1>Starting NextAgent</h1><p>Checking core files and DeepSeek API connection...</p></main></body>
</html>"""
MONITOR_DEFAULTTONEAREST = 2
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004


class Rect(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", Rect),
        ("rcWork", Rect),
        ("dwFlags", ctypes.c_ulong),
    ]


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def centered_position(width: int, height: int) -> tuple[int, int]:
    user32 = ctypes.windll.user32
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)
    return max(0, (screen_width - width) // 2), max(0, (screen_height - height) // 2)


def center_native_window(title: str = "NextAgent") -> None:
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return
    window_rect = Rect()
    user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    width = window_rect.right - window_rect.left
    height = window_rect.bottom - window_rect.top
    x = info.rcWork.left + (info.rcWork.right - info.rcWork.left - width) // 2
    y = info.rcWork.top + (info.rcWork.bottom - info.rcWork.top - height) // 2
    user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER)


class DesktopBridge:
    def __init__(self):
        self._window = None

    def _resize_centered(self, size: tuple[int, int]):
        def resize():
            if not self._window:
                return
            self._window.resize(*size)
            time.sleep(0.05)
            center_native_window()

        threading.Timer(0.1, resize).start()

    def enter_workspace(self):
        self._resize_centered(WORKSPACE_SIZE)

    def enter_setup(self):
        self._resize_centered(SETUP_SIZE)

    def choose_folder(self):
        if not self._window:
            return ""
        selected = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return selected[0] if selected else ""

    def choose_files(self):
        if not self._window:
            return []
        selected = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True)
        return list(selected or [])

    def open_external(self, url: str):
        if url.startswith(("https://", "http://")):
            webbrowser.open(url)
            return True
        return False

    def open_path(self, path: str):
        candidate = Path(path).expanduser()
        if not candidate.exists():
            return False
        os.startfile(str(candidate.resolve()))
        return True


def default_workdir() -> str:
    if getattr(sys, "frozen", False):
        path = Path.home() / "Documents" / "NextAgentWorkspace"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return os.getcwd()


def main() -> None:
    enable_dpi_awareness()
    static_dir = bundled_path("NextAgentGUI", "dist")
    os.environ.setdefault("NEXT_BUNDLED_COMMANDS", str(bundled_path("next_agent", "commands")))
    server = create_server(HOST, PORT, default_workdir(), static_dir)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    bridge = DesktopBridge()
    setup_width, setup_height = SETUP_SIZE
    setup_x, setup_y = centered_position(setup_width, setup_height)
    bridge._window = webview.create_window(
        "NextAgent",
        html=SPLASH_HTML,
        js_api=bridge,
        width=setup_width,
        height=setup_height,
        x=setup_x,
        y=setup_y,
        min_size=(640, 600),
        background_color="#f8f8f6",
        hidden=True,
    )

    def load_application():
        bridge._window.events.loaded.wait(15)
        bridge._window.show()
        center_native_window()
        time.sleep(0.2)
        bridge._window.load_url(f"http://{HOST}:{port}")

    webview.start(load_application, debug=False)
    server.shutdown()


if __name__ == "__main__":
    main()
