"""Tests for the pure protocol layer (no hardware)."""

from macos_arctis_manager.protocol import (
    DeviceConfig,
    pad_command,
    parse_value,
)


def cfg() -> DeviceConfig:
    return DeviceConfig.load()


# --- config loading -------------------------------------------------------

def test_load_exposes_device_identity():
    c = cfg()
    assert c.name == "SteelSeries Arctis Nova Pro Wireless"
    assert c.vendor_id == 0x1038
    assert 0x12E0 in c.product_ids
    assert 0x12E5 in c.product_ids
    assert 0x225D in c.product_ids
    assert c.command_interface == (4, 0)
    assert c.listen_interfaces == [4]


# --- command padding ------------------------------------------------------

def test_pad_command_pads_to_length_with_filler():
    out = pad_command([0x06, 0x39, 0x03], length=64, filler=0x00)
    assert len(out) == 64
    assert out[:3] == [0x06, 0x39, 0x03]
    assert all(b == 0x00 for b in out[3:])


def test_status_request_splits_two_byte_int_into_bytes():
    # 0x06b0 is stored as a single int in YAML and must become bytes 06 b0
    out = cfg().status_request_command()
    assert len(out) == 64
    assert out[:2] == [0x06, 0xB0]
    assert all(b == 0x00 for b in out[2:])


# --- settings -> command --------------------------------------------------

def test_setting_command_resolves_value_slot():
    out = cfg().setting_command("mic_side_tone", 0x03)
    assert len(out) == 64
    assert out[:3] == [0x06, 0x39, 0x03]


def test_init_commands_resolve_setting_defaults_and_status_request():
    cmds = cfg().init_commands()
    # mic_side_tone default is 0x00 -> [0x06, 0x39, 0x00]
    assert any(c[:3] == [0x06, 0x39, 0x00] for c in cmds)
    # the 'status.request' entry becomes [0x06, 0xb0]
    assert any(c[:2] == [0x06, 0xB0] for c in cmds)
    assert all(len(c) == 64 for c in cmds)


# --- value decoders -------------------------------------------------------

def test_parse_value_percentage():
    assert parse_value("percentage", 4, perc_min=0, perc_max=8) == 50
    assert parse_value("percentage", 8, perc_min=0, perc_max=8) == 100
    assert parse_value("percentage", 0, perc_min=0, perc_max=8) == 0


def test_parse_value_on_off():
    assert parse_value("on_off", 1, on=1, off=0) == "on"
    assert parse_value("on_off", 0, on=1, off=0) == "off"


def test_parse_value_int_str_mapping():
    values = {1: "offline", 2: "cable_charging", 8: "online"}
    assert parse_value("int_str_mapping", 0x08, values=values) == "online"
    assert parse_value("int_str_mapping", 0x99, values=values) is None


# --- full response decode -------------------------------------------------

def test_decode_response_maps_named_status_fields():
    raw = [0x00] * 64
    raw[0x00] = 0x06
    raw[0x01] = 0xB0  # payload starts with 0x06b0
    raw[0x06] = 4     # headset battery: 4/8 -> 50%
    raw[0x07] = 8     # spare battery: 8/8 -> 100%
    raw[0x09] = 1     # mic muted
    raw[0x0A] = 2     # ANC on
    raw[0x0F] = 8     # power status online

    decoded = cfg().decode_response(raw)

    assert decoded["headset_battery_charge"] == 50
    assert decoded["charge_slot_battery_charge"] == 100
    assert decoded["mic_status"] == "muted"
    assert decoded["noise_cancelling"] == "on"
    assert decoded["headset_power_status"] == "online"


def test_decode_response_returns_empty_when_no_mapping_matches():
    raw = [0xFF] * 64  # starts with 0xff, no mapping
    assert cfg().decode_response(raw) == {}
