# macOS Arctis Manager (v1) Design

**Date:** 2026-06-23
**Status:** Approved for planning
**Target device:** SteelSeries Arctis Nova Pro Wireless (base station)

## Summary

A macOS menu-bar app to read status from and control a SteelSeries Arctis Nova
Pro Wireless headset over USB HID. It is a focused port of the protocol layer
from the [Linux Arctis Manager](https://github.com/elegos/Linux-Arctis-Manager),
keeping that project's declarative per-device YAML as-is and replacing only the
parts that are Linux-specific (USB transport, audio routing, daemon/D-Bus/systemd
plumbing).

This is a personal-first project. It may be polished and distributed later, so
the protocol logic is kept pure and hardware-free to make an eventual Swift
rewrite cheap. That is a future option, not part of v1.

## Goals (v1)

Display (read from headset, refreshed on a poll):

- Headset battery %
- Spare-battery % (battery sitting in the base-station charge slot)
- Online / cable-charging / offline status
- Mic muted / unmuted
- ANC mode (off / transparent / on)
- Wireless mode (speed / range)

Control (write to headset):

- Sidetone: off / low / medium / high
- Mic volume
- Gain: low / high
- Mic LED brightness
- Auto-off timer
- Wireless mode: speed / range

## Non-goals (v1)

- **ChatMix.** On the Nova Pro Wireless the dock presents a single USB audio
  device to macOS (confirmed on the target machine: one "Arctis Nova Pro
  Wireless" output, 2 channels). Native Game/Chat separation is not present, so
  reproducing ChatMix would require a virtual audio driver (a signed system
  extension). Out of scope. Dropped entirely, not even a read-only balance
  display.
- **EQ and ANC toggle.** The upstream YAML sends EQ and ANC bytes only in its
  init burst; neither is exposed as a writable user setting. Adding them would
  need protocol reverse-engineering beyond what the YAML provides. Deferred.
- **Daemon / IPC / autostart.** No separate daemon, no D-Bus equivalent, no
  launchd LaunchAgent in v1. Single process. Autostart is a later nicety.
- **Other Arctis models.** Only the Nova Pro Wireless is targeted. The YAML
  approach leaves the door open to more models later, but v1 ships one.

## Device facts (extracted from upstream `nova_pro_wireless.yaml`)

- Vendor id: `0x1038`. Product ids: `0x12e0`, `0x12e5`, `0x225d`.
- Control interface: `bInterfaceNumber 4`, `bAlternateSetting 0`. Status is also
  read from interface `4`.
- Commands are 64 bytes, right-padded with `0x00`.
- An init burst must be sent on startup (sets EQ preset, mic defaults, etc.)
  before status reads are reliable.
- Status request: `0x06b0`. The response whose payload `starts_with 0x06b0`
  carries status as a byte array. Relevant byte offsets:
  - `0x06` headset battery charge (raw 0..8, mapped to percentage)
  - `0x07` charge-slot (spare) battery charge (raw 0..8)
  - `0x09` mic status (`0x00` unmuted, `0x01` muted)
  - `0x0a` noise cancelling (`0x00` off, `0x01` transparent, `0x02` on)
  - `0x0f` headset power status (`0x01` offline, `0x02` cable charging, `0x08` online)
  - plus wireless mode/pairing, mic LED brightness, auto-off time, bluetooth bits
- Writable settings (each is a byte sequence with a `value` slot):
  - gain: `[0x06, 0x27, value]` (`0x01` low, `0x02` high)
  - mic volume: `[0x06, 0x37, value]` (`0x01`..`0x0a`)
  - sidetone: `[0x06, 0x39, value]` (`0x00`..`0x03`)
  - mic LED brightness: `[0x06, 0xbf, value]` (`0x01`..`0x0a`)
  - auto-off (`pm_shutdown`): `[0x06, 0xc1, value]`
  - wireless mode: `[0x06, 0xc3, value]` (`0x00` speed, `0x01` range)
- Status value decoders used by the YAML: `percentage`, `on_off`,
  `int_str_mapping`, `int_int_mapping`.

## Architecture

One process. A `rumps` menu-bar app with a background polling thread. Three
internal pieces with clear boundaries:

```
menu click ──► protocol.build(setting, value) ──► transport.send(bytes)
poll thread ──► transport.read_status() ──► protocol.parse(bytes) ──► menu labels update
```

### `arctis/nova_pro_wireless.yaml`

Copied verbatim from upstream. Single source of truth for the device protocol.
Kept as a data file (not code) so a future Swift port reuses it directly.

### `arctis/protocol.py` (reused logic, hardware-free)

Ported from upstream `core.py` + `status_parser_fn.py`, with all pyusb and
PulseAudio code removed. Pure functions over bytes:

- `load(yaml_path) -> DeviceSpec` parses the YAML.
- `init_commands(spec) -> list[bytes]` the startup burst.
- `build(spec, setting_name, value) -> bytes` builds and pads a write command
  from a setting's `update_sequence`.
- `status_request(spec) -> bytes`.
- `parse_status(spec, payload) -> dict` decodes a status response into named,
  human-readable values using the YAML's `status_parse` decoders.

No imports of hidapi or any OS API. This is the unit-tested core.

### `arctis/transport.py` (the only real macOS porting work)

Thin wrapper over hidapi (`hid` package, which uses IOKit `IOHIDManager` on
macOS). Isolates every macOS-specific detail:

- `open() -> bool` enumerate HID devices, match vendor `0x1038` + a known
  product id, select the control interface (upstream interface `4`), open it.
- `send(data: bytes)` write a command report.
- `read_status(timeout) -> bytes | None` read a status response.
- `close()`.

Two device-specific unknowns to resolve by testing on the physical headset
(documented as risks below): output vs feature report, and the report-ID prefix.

### `arctis/menubar.py` (new)

The `rumps.App`. On launch: open transport, send init burst, build menu items
from the YAML's declared settings (a submenu per setting, options from its
`values_mapping` or slider range). A background thread polls `read_status`
every few seconds and updates the menu title (battery %) and item labels.
Clicking a control calls `protocol.build` then `transport.send`.

### `main.py`

Entry point: wire the three pieces and run the app.

## Data flow

- **Control:** user picks a menu option, app maps it to the setting's raw value,
  `protocol.build` produces the padded 64-byte command, `transport.send` writes
  it.
- **Status:** poll thread sends `status_request`, reads the response,
  `protocol.parse_status` decodes it, the app updates labels on the main thread
  (rumps timer or thread-safe update).

## Error handling

- **Headset off / dongle unplugged:** `transport.read_status` returns `None` or
  `open` fails. Menu shows a "Disconnected" state. Poll keeps retrying; no crash.
- **hidapi open / permission failure:** surfaced as a visible menu item with the
  error text so it is debuggable rather than silent.
- **Short or unexpected status payload:** `parse_status` decodes the fields it
  can and marks the rest unknown. No exception bubbles to the UI.

## Testing

- **Hardware-free unit tests** (`tests/test_protocol.py`): feed known status byte
  arrays and assert decoded values (battery %, mic state, power status, etc.);
  assert exact command bytes for representative writes (e.g. sidetone = high
  produces `[0x06, 0x39, 0x03, 0x00...]` padded to 64). This is where protocol
  correctness is pinned down, and it needs no device.
- **One manual on-device pass** for `transport.py` once the HID interface, report
  type, and report-ID prefix are confirmed.

## File layout

```
macos-arctis-manager/
  arctis/
    nova_pro_wireless.yaml   # copied from upstream, verbatim
    protocol.py              # YAML interpreter: build + parse (pure)
    transport.py             # hidapi over IOKit
    menubar.py               # rumps app
  tests/
    test_protocol.py
  main.py
  pyproject.toml
  README.md
```

## Dependencies

- `hidapi` (the `hid` PyPI package) for HID over IOKit.
- `rumps` for the native menu-bar app.
- `pyyaml` to read the device YAML.

## Risks and open questions

1. **HID report type.** Upstream pyusb uses control transfers (SET_REPORT).
   hidapi maps to output reports (`hid_write`) or feature reports
   (`hid_send_feature_report`). Which one the dock expects is unknown until
   tested. Isolated entirely inside `transport.py`.
2. **Report-ID prefix.** hidapi may require a leading report-ID byte (`0x00`)
   before the 64-byte payload. To verify on-device.
3. **Interface selection.** macOS exposes each HID interface as a separate device
   path. We must select interface `4` (likely matched by its vendor-defined
   usage page). To confirm by enumerating on the target machine.
4. **Init burst.** Whether the full init burst is required on macOS, or only a
   subset, is unconfirmed. Start by sending it all.
5. **macOS HID permissions.** Vendor-specific HID generally needs no special
   entitlement, but if access is blocked the error path (above) must make it
   obvious.

These risks are confined to `transport.py`. The protocol core and the menu UI do
not depend on how they resolve.
