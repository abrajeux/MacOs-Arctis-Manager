"""Pure protocol layer for the Arctis Nova Pro Wireless.

Faithful port of the relevant parts of the upstream Linux project
(``config.py``, ``status_parser_fn.py`` and the command-padding logic from
``core.py``), with no hardware or OS dependencies. Everything here operates on
plain ``list[int]`` byte arrays so it can be unit-tested without a device and
reused directly by a future native port.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

_DEFAULT_YAML = Path(__file__).parent / "devices" / "nova_pro_wireless.yaml"


# --- value decoders (port of status_parser_fn.py) -------------------------

def _percentage(value: int, perc_min: int, perc_max: int) -> int:
    if perc_max < perc_min:
        value = perc_min - value
        return 100 - (value - perc_min) * 100 // (perc_max - perc_min)
    return (value - perc_min) * 100 // (perc_max - perc_min)


def _on_off(value: int, on: int, off: int) -> str:
    return "on" if value == on else "off"


def _mapping(value: int, values: dict[int, Any]) -> Any:
    return values.get(value)


_DECODERS = {
    "percentage": _percentage,
    "on_off": _on_off,
    "int_str_mapping": _mapping,
    "int_int_mapping": _mapping,
}


def parse_value(parse_type: str, value: int, **kwargs: Any) -> Any:
    """Decode a raw status byte into a human-readable value."""
    decoder = _DECODERS.get(parse_type)
    if decoder is None:
        return value
    return decoder(value=value, **kwargs)


# --- command padding (port of core.py send_command) -----------------------

def pad_command(command: list[int], length: int, filler: int) -> list[int]:
    """Encode a command and right/left-pad it to ``length`` bytes.

    A single element may be a multi-byte int (e.g. the status request
    ``0x06b0`` becomes the two bytes ``06 b0``), matching upstream behaviour.
    """
    hex_str = "".join(f"{b:02x}" for b in command)
    if len(hex_str) % 2 != 0:
        hex_str = "0" + hex_str

    filler_hex = f"{filler:02x}"
    if len(filler_hex) % 2 != 0:
        filler_hex = "0" + filler_hex

    n_bytes = len(hex_str) // 2
    if n_bytes < length:
        hex_str = hex_str + filler_hex * (length - n_bytes)

    return [int(hex_str[i:i + 2], 16) for i in range(0, len(hex_str), 2)]


# --- config model ---------------------------------------------------------

@dataclass
class Setting:
    name: str
    type: str
    default: int | None
    update_sequence: list[int | str]
    options: dict[str, Any] = field(default_factory=dict)

    def resolve(self, value: int) -> list[int]:
        out: list[int] = []
        for b in self.update_sequence:
            out.append(value if b == "value" else int(b))
        return out


class DeviceConfig:
    name: str
    vendor_id: int
    product_ids: list[int]
    command_interface: tuple[int, int]
    listen_interfaces: list[int]
    padding_length: int
    padding_filler: int
    device_init: list[list[int | str]]
    status_request: int | None
    response_mapping: list[tuple[int, dict[str, int]]]
    status_parse: dict[str, tuple[str, dict[str, Any]]]
    online_status: tuple[str, Any] | None
    settings: dict[str, Setting]
    sections: dict[str, list[str]]

    def __init__(self, raw: dict[str, Any]):
        dev = raw.get("device")
        if not dev:
            raise ValueError("Invalid configuration: missing 'device' section")

        self.name = dev["name"]
        self.vendor_id = dev["vendor_id"]
        self.product_ids = list(dev["product_ids"])
        ci = dev["command_interface_index"]
        self.command_interface = (ci[0], ci[1])
        self.listen_interfaces = list(dev["listen_interface_indexes"])

        padding = dev["command_padding"]
        self.padding_length = padding["length"]
        self.padding_filler = padding["filler"]

        self.device_init = dev.get("device_init", []) or []

        status = dev.get("status") or {}
        self.status_request = status.get("request")
        self.response_mapping = []
        for mapping in status.get("response_mapping", []):
            fields = {k: v for k, v in mapping.items() if k != "starts_with"}
            self.response_mapping.append((mapping["starts_with"], fields))

        self.status_parse = {}
        for name, raw_parse in (dev.get("status_parse") or {}).items():
            kwargs = {k: v for k, v in raw_parse.items() if k != "type"}
            self.status_parse[name] = (raw_parse["type"], kwargs)

        online = dev.get("online_status")
        self.online_status = (
            (online["status_variable"], online["online_value"]) if online else None
        )

        self.settings = {}
        self.sections = {}
        for section, settings in (dev.get("settings") or {}).items():
            self.sections[section] = []
            for name, values in settings.items():
                self.settings[name] = Setting(
                    name=name,
                    type=values["type"],
                    default=values.get("default"),
                    update_sequence=values.get("update_sequence", []),
                    options={
                        k: v
                        for k, v in values.items()
                        if k not in ("type", "default", "update_sequence")
                    },
                )
                self.sections[section].append(name)

    @classmethod
    def load(cls, path: str | Path = _DEFAULT_YAML) -> "DeviceConfig":
        yaml = YAML(typ="safe")
        return cls(yaml.load(Path(path)))

    # -- command building --

    def _pad(self, command: list[int]) -> list[int]:
        return pad_command(command, self.padding_length, self.padding_filler)

    def status_request_command(self) -> list[int]:
        if self.status_request is None:
            raise ValueError("Device has no status request")
        return self._pad([self.status_request])

    def setting_command(self, name: str, value: int) -> list[int]:
        return self._pad(self.settings[name].resolve(value))

    def init_commands(self) -> list[list[int]]:
        return [self._pad(self._resolve_init(entry)) for entry in self.device_init]

    def _resolve_init(self, entry: list[int | str]) -> list[int]:
        out: list[int] = []
        for b in entry:
            if isinstance(b, int):
                out.append(b)
            elif b == "status.request":
                if self.status_request is not None:
                    out.append(self.status_request)
            elif isinstance(b, str) and b.startswith("settings."):
                setting = self.settings[b.split(".", 1)[1]]
                out.append(int(setting.default))
            else:
                raise ValueError(f"Invalid init sequence value: {b!r}")
        return out

    # -- status decoding --

    def decode_response(self, raw: list[int]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        hex_str = "".join(f"{b:02x}" for b in raw)
        for starts_with, fields in self.response_mapping:
            prefix = f"{starts_with:02x}"
            if len(prefix) % 2 != 0:
                prefix = "0" + prefix
            if not hex_str.startswith(prefix):
                continue
            for name, index in fields.items():
                if 0 <= index < len(raw):
                    result[name] = self._parse_field(name, raw[index])
        return result

    def _parse_field(self, name: str, raw_value: int) -> Any:
        parse = self.status_parse.get(name)
        if parse is None:
            return raw_value
        parse_type, kwargs = parse
        return parse_value(parse_type, raw_value, **kwargs)
