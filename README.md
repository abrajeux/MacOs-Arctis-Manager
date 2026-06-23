# macOS Arctis Manager

A lightweight macOS **menu-bar** app to monitor and control the **SteelSeries
Arctis Nova Pro Wireless** without SteelSeries GG. It talks to the headset's
base station over USB HID.

## Credit

This is a macOS port of [**elegos/Linux-Arctis-Manager**](https://github.com/elegos/Linux-Arctis-Manager).
All of the reverse-engineered device protocol comes from that project, and this
repo is a fork of it. Huge thanks to the original authors.

Licensed under **GPL-3.0-or-later**, same as upstream (see `LICENSE`).

### Changes from upstream

- Added a self-contained `macos_arctis_manager` package (`src/`):
  - `protocol.py`: pure port of the YAML config loader, command padding and
    status decoders (no OS dependencies).
  - `transport.py`: USB HID via the cross-platform `hidapi` (IOKit on macOS),
    replacing the Linux `pyusb` transport.
  - `menubar.py`: a `rumps` menu-bar app, replacing the Qt GUI + daemon +
    D-Bus + systemd stack.
- Dropped, for this port: ChatMix / PulseAudio routing, udev, systemd, D-Bus,
  the Qt GUI and the multi-device support (only Nova Pro Wireless is wired up).
- The original Linux sources remain under `src/linux_arctis_manager/` for
  reference and are not built or run on macOS.

## Features (v1)

Reads (shown in the menu, refreshed every few seconds):

- Headset battery %
- Spare battery % (the pack in the base-station charge slot)
- Online / cable-charging status
- Mic muted state, ANC mode, wireless mode

Controls (write to the headset):

- Sidetone, mic volume, gain, mic LED brightness, auto-off timer, wireless mode

### Not included

- **ChatMix.** On the Nova Pro Wireless the dock exposes a single audio device
  to macOS, so software ChatMix would need a virtual audio driver. Out of scope.
- **EQ / ANC toggle.** Not exposed as writable settings by the device protocol.

## Requirements

- macOS, an Arctis Nova Pro Wireless connected via its base station
- [`uv`](https://docs.astral.sh/uv/)
- `hidapi` (installed automatically as a Python wheel; no Homebrew needed)

## Install and run

```sh
uv sync
uv run arctis-manager
```

A 🎧 icon appears in the menu bar showing the battery %. Click it for status and
settings. Quit from the menu.

> If SteelSeries GG / Sonar is running it may hold the HID device; quit it first.

## Develop / test

The protocol layer is covered by hardware-free unit tests:

```sh
uv run pytest
```

`transport.py` is validated against a real device rather than mocks (it is a
thin adapter over `hidapi`).
