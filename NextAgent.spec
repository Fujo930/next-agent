# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

webview_data, webview_binaries, webview_hiddenimports = collect_all("webview")

a = Analysis(
    ["desktop_entry.py"],
    pathex=["src"],
    binaries=webview_binaries,
    datas=webview_data + [
        ("NextAgentGUI/dist", "NextAgentGUI/dist"),
        ("next_agent/commands", "next_agent/commands"),
    ],
    hiddenimports=webview_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NextAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
