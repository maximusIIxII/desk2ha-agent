# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for desk2ha-agent standalone binary."""

import sys
from pathlib import Path

block_cipher = None
src = Path("desk2ha_agent")

# Collect all collector modules as hidden imports
collector_modules = [
    f"desk2ha_agent.collector.{p.stem}"
    for p in (src / "collector").glob("*.py")
    if p.stem not in ("__init__", "base")
]

hidden_imports = [
    *collector_modules,
    "desk2ha_agent.transport.http",
    "desk2ha_agent.transport.mqtt",
    "desk2ha_agent.transport.zeroconf",
    "desk2ha_agent.lifecycle.phone_home",
    "desk2ha_agent.lifecycle.self_update",
    "desk2ha_agent.lifecycle.service_manager",
    "desk2ha_agent.lifecycle.system_actions",
    "desk2ha_agent.lifecycle.config_api",
    "desk2ha_agent.lifecycle.version_check",
    "desk2ha_agent.tray.tray_helper",
    "desk2ha_agent.helper.__main__",
    "pydantic",
    "aiohttp",
    "psutil",
    "zeroconf",
]

# Platform-specific hidden imports
if sys.platform == "win32":
    hidden_imports += [
        "wmi",
        "win32api",
        "win32com",
        "win32con",
        "win32gui",
        "win32process",
        "pystray",
        "PIL",
        "PIL.Image",
    ]
elif sys.platform == "darwin":
    hidden_imports += [
        "objc",
    ]

a = Analysis(
    ["desk2ha_agent/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("desk2ha_agent/setup_wizard", "desk2ha_agent/setup_wizard"),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="desk2ha-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="brand/icon.ico" if sys.platform == "win32" else None,
)

# macOS: create .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Desk2HA Agent.app",
        icon="brand/icon.icns",
        bundle_identifier="com.desk2ha.agent",
        info_plist={
            "CFBundleShortVersionString": "0.7.0",
            "LSUIElement": True,  # Hide from Dock
        },
    )
