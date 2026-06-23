"""HID transport for the Arctis control interface.

A thin adapter over the cython ``hidapi`` package. All the real logic
(command building, status decoding) lives in :mod:`protocol`; this module only
opens the right HID interface and moves bytes. It is validated by an on-device
probe rather than mocks, since there is no branching logic worth faking.

Resolved empirically against an Arctis Nova Pro Wireless (pid 0x12e0):

* the control interface is ``interface_number == 4`` (usage page 0xffc0/0xff00);
* writes are output reports with a leading 0x00 report-id byte;
* reads return the response with no leading offset (it starts at 0x06).
"""

from __future__ import annotations

import logging
import time

import hid

from .protocol import DeviceConfig

log = logging.getLogger(__name__)


class Transport:
    def __init__(self, config: DeviceConfig | None = None):
        self._cfg = config or DeviceConfig.load()
        self._dev: hid.device | None = None

    @property
    def config(self) -> DeviceConfig:
        return self._cfg

    @property
    def is_open(self) -> bool:
        return self._dev is not None

    def _find_path(self) -> bytes | None:
        iface = self._cfg.command_interface[0]
        for d in hid.enumerate(self._cfg.vendor_id, 0):
            if d["product_id"] in self._cfg.product_ids and d["interface_number"] == iface:
                return d["path"]
        return None

    def open(self, attempts: int = 3) -> bool:
        """Open the control interface. Returns False if the device is absent.

        macOS sometimes refuses the open transiently (handle release race,
        exclusivity), so retry a few times before giving up.
        """
        if self._dev is not None:
            return True
        for attempt in range(attempts):
            # Re-enumerate every attempt: a path from a previous enumeration can
            # go stale and make open_path fail even while the device is present.
            path = self._find_path()
            if path is not None:
                dev = hid.device()
                try:
                    dev.open_path(path)
                    self._dev = dev
                    return True
                except (OSError, IOError) as e:
                    try:
                        dev.close()
                    except Exception:
                        pass
                    del dev
                    if attempt == attempts - 1:
                        log.warning("Failed to open Arctis HID interface: %s", e)
            if attempt < attempts - 1:
                time.sleep(0.25)
        return False

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def send(self, command: list[int]) -> None:
        if self._dev is None:
            raise RuntimeError("Transport not open")
        self._dev.write([0x00] + list(command))

    def request_status(self) -> None:
        self.send(self._cfg.status_request_command())

    def read_status(self, timeout_ms: int = 300) -> dict | None:
        """Read one status report and decode it, or None on timeout/no match."""
        if self._dev is None:
            return None
        data = self._dev.read(64, timeout_ms)
        if not data:
            return None
        return self._cfg.decode_response(list(data)) or None

    def set_setting(self, name: str, value: int) -> None:
        self.send(self._cfg.setting_command(name, value))

    def init_device(self) -> None:
        """Send the full init burst.

        Not called on launch: status reads and setting writes work without it,
        and the burst would reset device state (sidetone, EQ, etc.) to the YAML
        defaults. Kept available for parity / troubleshooting.
        """
        for cmd in self._cfg.init_commands():
            self.send(cmd)
