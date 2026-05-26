from __future__ import annotations

import subprocess
import sys
import winreg
from collections.abc import Callable
from pathlib import Path

import pystray
from PIL import Image
from platformdirs import user_config_dir
from pydantic import BaseModel
from winotify import Notification, audio

CONFIG_PATH = Path(user_config_dir("winks")) / "config.json"

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "Winks"

_START_MENU = (
    Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
)
_VBS_PATH = _START_MENU / "Winks.vbs"
_LNK_PATH = _START_MENU / "Winks.lnk"

_ICON_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent.parent)) / "assets" / "icon.png"


class Config(BaseModel):
    device_address: str | None = None
    probed_at: str | None = None  # ISO 8601

    @classmethod
    def load(cls) -> "Config":
        try:
            return cls.model_validate_json(CONFIG_PATH.read_text())
        except FileNotFoundError:
            return cls()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(self.model_dump_json(indent=2))


def add_startup_task() -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, f'"{_exe()}" run')


def remove_startup_task() -> None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _RUN_VALUE)
    except FileNotFoundError:
        pass


def startup_task_exists() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
        return True
    except FileNotFoundError:
        return False


def add_start_menu_entry() -> None:
    """Create a Start Menu shortcut that launches winks without a console window."""
    exe = _exe()
    _VBS_PATH.write_text(
        f'CreateObject("WScript.Shell").Run "{exe} run", 0, False\n',
        encoding="utf-8",
    )
    icon = str(_ICON_PATH) if _ICON_PATH.exists() else str(exe)
    ps = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{_LNK_PATH}");'
        f'$s.TargetPath="wscript.exe";'
        f'$s.Arguments=\'"{_VBS_PATH}"\';'
        f'$s.IconLocation="{icon}";'
        f'$s.Description="Winks - iPhone notifications on Windows";'
        f'$s.Save()'
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def remove_start_menu_entry() -> None:
    _LNK_PATH.unlink(missing_ok=True)
    _VBS_PATH.unlink(missing_ok=True)


def start_menu_entry_exists() -> bool:
    return _LNK_PATH.exists()


def _exe() -> Path:
    return Path(sys.executable).parent / "winks.exe"


def _icon_image() -> Image.Image:
    if _ICON_PATH.exists():
        return Image.open(_ICON_PATH)
    img = Image.new("RGBA", (64, 64), (30, 100, 200, 255))
    return img


class Tray:
    def __init__(self) -> None:
        self._icon: pystray.Icon | None = None
        self._connected = False
        self._device_name: str | None = None
        self._on_probe: Callable[[], None] | None = None
        self._on_disconnect: Callable[[], None] | None = None
        self._on_reconnect: Callable[[], None] | None = None
        self._on_quit: Callable[[], None] | None = None

    def update_status(self, connected: bool, device_name: str | None) -> None:
        self._connected = connected
        self._device_name = device_name
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def run(
        self,
        on_probe: Callable[[], None],
        on_disconnect: Callable[[], None],
        on_reconnect: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_probe = on_probe
        self._on_disconnect = on_disconnect
        self._on_reconnect = on_reconnect
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "winks",
            icon=_icon_image(),
            title="Winks",
            menu=self._build_menu(),
        )
        self._icon.run()

    def _build_menu(self) -> pystray.Menu:
        if self._connected:
            status_label = self._device_name or "Connected"
            toggle = pystray.MenuItem(
                "Disconnect",
                lambda icon, item: self._on_disconnect and self._on_disconnect(),
            )
        else:
            status_label = "Not connected"
            toggle = pystray.MenuItem(
                "Reconnect",
                lambda icon, item: self._on_reconnect and self._on_reconnect(),
            )

        def do_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            if self._on_quit:
                self._on_quit()
            icon.stop()

        return pystray.Menu(
            pystray.MenuItem(status_label, None, enabled=False),
            toggle,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Probe device", lambda icon, item: self._on_probe and self._on_probe()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", do_quit),
        )


def show_toast(category: str, title: str, subtitle: str, message: str) -> None:
    heading = title or subtitle or "(no title)"
    body_bits = [p for p in ([subtitle] if title and subtitle else []) + [message] if p]
    body = " — ".join(body_bits) or "(no content)"
    icon_arg = str(_ICON_PATH) if _ICON_PATH.exists() else ""
    toast = Notification(
        app_id="Winks",
        title=f"[{category}] {heading}",
        msg=body,
        duration="short",
        icon=icon_arg,
    )
    toast.set_audio(audio.Default, loop=False)
    toast.show()
