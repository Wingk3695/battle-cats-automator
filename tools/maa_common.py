from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from maa.controller import AdbController
from maa.define import MaaAdbInputMethodEnum, MaaAdbScreencapMethodEnum
from maa.toolkit import Toolkit


ROOT = Path(__file__).resolve().parents[1]
USER_PATH = ROOT / ".maa"
CAPTURE_DIR = ROOT / "captures"
RESOURCE_DIR = ROOT / "resource"
DEFAULT_ADB_CANDIDATES = [
    Path(r"D:\Custom Programs\scrcpy-win64-v3.3.3\adb.exe"),
]


def init_toolkit() -> None:
    USER_PATH.mkdir(exist_ok=True)
    Toolkit.init_option(str(USER_PATH))


def make_adb_controller(index: int = 0) -> AdbController:
    init_toolkit()
    adb_path = find_adb_path()
    devices = Toolkit.find_adb_devices(adb_path) if adb_path else Toolkit.find_adb_devices()
    if not devices:
        raise RuntimeError(
            "No ADB device found. Confirm scrcpy works, then set BCA_ADB_PATH to scrcpy's adb.exe if needed."
        )

    device = devices[index]
    controller = AdbController(
        adb_path=device.adb_path,
        address=device.address,
        screencap_methods=MaaAdbScreencapMethodEnum.EncodeToFileAndPull,
        input_methods=MaaAdbInputMethodEnum.AdbShell,
        config=device.config,
    )
    controller.post_connection().wait()
    if not controller.connected:
        raise RuntimeError(f"Failed to connect ADB device: {device.address}")
    return controller


def describe_device(device: Any) -> str:
    return f"{device.address} via {device.adb_path}"


def find_adb_path() -> Path | None:
    env_path = os.environ.get("BCA_ADB_PATH")
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(f"BCA_ADB_PATH does not exist: {path}")
        return path

    for path in DEFAULT_ADB_CANDIDATES:
        if path.exists():
            return path

    return None
