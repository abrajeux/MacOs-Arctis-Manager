"""macOS menu-bar app for the Arctis Nova Pro Wireless.

A single rumps process: a status poll on a main-loop timer plus submenus built
from the device YAML's settings. No daemon, no IPC.
"""

from __future__ import annotations

import logging

import rumps

from .protocol import DeviceConfig, Setting
from .transport import Transport

log = logging.getLogger(__name__)

POLL_SECONDS = 3

# status fields shown in the menu: (status key, label, formatter)
INFO_FIELDS = [
    ("headset_battery_charge", "Battery", lambda v: f"{v}%"),
    ("charge_slot_battery_charge", "Spare battery", lambda v: f"{v}%"),
    ("headset_power_status", "Status", str),
    ("mic_status", "Mic", str),
    ("noise_cancelling", "ANC", str),
    ("wireless_mode", "Wireless", str),
]


def _humanize(text: str) -> str:
    return text.replace("_", " ").strip().capitalize()


class ArctisApp(rumps.App):
    def __init__(self):
        super().__init__("Arctis", title="🎧 …", quit_button="Quit")
        self.transport = Transport()
        self.config: DeviceConfig = self.transport.config
        # hid.enumerate() pumps the run loop, which can fire the poll timer
        # re-entrantly mid-refresh. This guard keeps only one refresh active.
        self._busy = False
        self.current: dict[str, int | None] = {}
        self._info_items: dict[str, rumps.MenuItem] = {}
        # name -> list of (menu item, raw value) for checkmark management
        self._option_items: dict[str, list[tuple[rumps.MenuItem, int]]] = {}

        self._build_menu()
        # Poll on the run loop. The first connection happens on the first tick,
        # not in __init__: a synchronous HID open inside the App constructor is
        # unreliable on macOS, and blocking I/O in __init__ is bad practice.
        self._timer = rumps.Timer(self._refresh, POLL_SECONDS)
        self._timer.start()

    # -- menu construction --

    def _build_menu(self) -> None:
        for key, label, _ in INFO_FIELDS:
            item = rumps.MenuItem(f"{label}: …")  # no callback => disabled/info
            self._info_items[key] = item
            self.menu.add(item)

        self.menu.add(rumps.separator)

        for section, names in self.config.sections.items():
            for name in names:
                setting = self.config.settings[name]
                self.current[name] = setting.default
                self.menu.add(self._build_setting_submenu(setting))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh now", callback=self._refresh))

    def _build_setting_submenu(self, setting: Setting) -> rumps.MenuItem:
        parent = rumps.MenuItem(_humanize(setting.name))
        self._option_items[setting.name] = []
        for raw, label in self._options(setting):
            item = rumps.MenuItem(
                label, callback=self._make_setter(setting.name, raw)
            )
            item.state = 1 if raw == setting.default else 0
            parent.add(item)
            self._option_items[setting.name].append((item, raw))
        return parent

    def _options(self, setting: Setting) -> list[tuple[int, str]]:
        opts = setting.options
        if setting.type == "discrete_map":
            return [(raw, _humanize(str(label)))
                    for raw, label in opts["values_mapping"].items()]
        if setting.type == "slider":
            lo, hi, step = opts["min"], opts["max"], opts.get("step", 1)
            return [(raw, f"{round(raw / hi * 100)}%")
                    for raw in range(lo, hi + 1, step)]
        return []

    def _make_setter(self, name: str, raw: int):
        def callback(_item):
            try:
                self.transport.set_setting(name, raw)
            except Exception as e:  # device may have vanished
                log.warning("Failed to set %s=%s: %s", name, raw, e)
                rumps.notification("Arctis", "Could not apply setting", str(e))
                return
            self.current[name] = raw
            self._sync_checks(name)
        return callback

    def _sync_checks(self, name: str) -> None:
        for item, raw in self._option_items.get(name, []):
            item.state = 1 if raw == self.current[name] else 0

    # -- polling --

    def _refresh(self, _sender) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            if not self.transport.is_open and not self.transport.open():
                self._set_disconnected()
                return
            try:
                self.transport.request_status()
                status = None
                for _ in range(5):
                    status = self.transport.read_status(timeout_ms=150)
                    if status:
                        break
            except Exception as e:
                log.warning("Status read failed, will reconnect: %s", e)
                self.transport.close()
                self._set_disconnected()
                return

            if status:
                self._apply_status(status)
        finally:
            self._busy = False

    def _apply_status(self, status: dict) -> None:
        battery = status.get("headset_battery_charge")
        power = status.get("headset_power_status")
        if power == "online" and battery is not None:
            self.title = f"🎧 {battery}%"
        elif power == "cable_charging":
            self.title = "🎧 ⚡"
        else:
            self.title = "🎧 –"

        for key, label, fmt in INFO_FIELDS:
            value = status.get(key)
            shown = fmt(value) if value is not None else "—"
            self._info_items[key].title = f"{label}: {shown}"

    def _set_disconnected(self) -> None:
        self.title = "🎧 ⚠"
        for key, label, _ in INFO_FIELDS:
            self._info_items[key].title = f"{label}: —"


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Run as a menu-bar-only accessory: no Dock icon, no app menu. Done in code
    # so it holds regardless of how we're launched (terminal or .app wrapper).
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
    except Exception:
        pass
    ArctisApp().run()


if __name__ == "__main__":
    main()
