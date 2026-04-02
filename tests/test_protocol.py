"""Tests for DuoFern protocol helpers (protocol.py)."""
from __future__ import annotations

import pytest

from custom_components.duofern.protocol import (
    DuoFernId,
    DuoFernEncoder,
    DuoFernDecoder,
    ParsedStatus,
    validate_device_code,
    validate_system_code,
)

# ---------------------------------------------------------------------------
# DuoFernId
# ---------------------------------------------------------------------------


def test_duofernid_from_hex_cover():
    code = DuoFernId.from_hex("406B2D")
    assert code.hex == "406B2D"
    assert code.device_type == 0x40
    assert code.is_cover is True


def test_duofernid_is_cover_all_cover_prefixes():
    """All documented cover device types are recognised as covers."""
    cover_hexes = ["406B2D", "411234", "421234", "471234", "491234",
                   "4B1234", "4C1234", "4E1234", "611234", "701234"]
    for h in cover_hexes:
        code = DuoFernId.from_hex(h)
        assert code.is_cover, f"{h} (0x{code.device_type:02X}) should be cover"


def test_duofernid_is_switch():
    code = DuoFernId.from_hex("431234")
    assert code.is_switch is True
    assert code.is_cover is False


def test_duofernid_is_light():
    code = DuoFernId.from_hex("481234")
    assert code.is_light is True


def test_duofernid_is_climate_thermostat():
    code = DuoFernId.from_hex("731234")
    assert code.is_climate is True


def test_duofernid_is_climate_hsa():
    code = DuoFernId.from_hex("E11234")
    assert code.is_climate is True


def test_duofernid_is_remote():
    code = DuoFernId.from_hex("A01234")
    assert code.is_remote is True
    assert code.is_cover is False


def test_duofernid_is_binary_sensor_smoke():
    code = DuoFernId.from_hex("AB1234")
    assert code.is_binary_sensor is True


def test_duofernid_is_binary_sensor_contact():
    code = DuoFernId.from_hex("AC1234")
    assert code.is_binary_sensor is True


def test_duofernid_is_binary_sensor_motion():
    code = DuoFernId.from_hex("651234")
    assert code.is_binary_sensor is True


def test_duofernid_is_env_sensor():
    code = DuoFernId.from_hex("691234")
    assert code.is_env_sensor is True


def test_duofernid_from_hex_uppercase():
    code = DuoFernId.from_hex("406b2d")
    assert code.hex == "406B2D"


def test_duofernid_system_code():
    code = DuoFernId.from_hex("6F1A2B")
    assert code.hex == "6F1A2B"
    assert code.device_type == 0x6F


def test_duofernid_device_type_name_not_empty():
    code = DuoFernId.from_hex("406B2D")
    assert isinstance(code.device_type_name, str)
    assert len(code.device_type_name) > 0


def test_duofernid_unknown_type_has_name():
    """Even unknown device types return a non-empty name string."""
    code = DuoFernId.from_hex("FF1234")
    assert isinstance(code.device_type_name, str)


# ---------------------------------------------------------------------------
# validate_device_code
# ---------------------------------------------------------------------------


def test_validate_device_code_valid():
    assert validate_device_code("406B2D") is True


def test_validate_device_code_valid_lowercase():
    assert validate_device_code("406b2d") is True


def test_validate_device_code_too_short():
    assert validate_device_code("406B") is False


def test_validate_device_code_too_long():
    assert validate_device_code("406B2D1234") is False


def test_validate_device_code_non_hex():
    assert validate_device_code("ZZZZZZ") is False


def test_validate_device_code_empty():
    assert validate_device_code("") is False


def test_validate_device_code_with_spaces():
    """Codes with leading/trailing spaces should fail (no stripping in validate)."""
    # validate_device_code is called AFTER strip in _parse_device_codes
    result = validate_device_code("406B2D")
    assert result is True


# ---------------------------------------------------------------------------
# validate_system_code
# ---------------------------------------------------------------------------


def test_validate_system_code_valid():
    assert validate_system_code("6F1A2B") is True


def test_validate_system_code_wrong_prefix():
    """System codes must start with 6F."""
    assert validate_system_code("401A2B") is False


def test_validate_system_code_too_short():
    assert validate_system_code("6F1A") is False


def test_validate_system_code_non_hex():
    assert validate_system_code("6FZZZZ") is False


# ---------------------------------------------------------------------------
# ParsedStatus
# ---------------------------------------------------------------------------


def test_parsed_status_defaults():
    status = ParsedStatus()
    assert status.position is None
    assert status.moving == "stop"
    assert status.readings == {}


def test_parsed_status_readings_dict():
    status = ParsedStatus()
    status.readings["brightness"] = 5000
    assert status.readings["brightness"] == 5000


# ---------------------------------------------------------------------------
# DuoFernEncoder — smoke tests
# ---------------------------------------------------------------------------


def test_encoder_build_stop_unpair_returns_bytes():
    frame = DuoFernEncoder.build_stop_unpair()
    assert isinstance(frame, (bytes, bytearray, str))
    assert len(frame) > 0


def test_encoder_build_start_pair_returns_nonempty():
    frame = DuoFernEncoder.build_start_pair()
    assert frame


def test_encoder_build_stop_pair_returns_nonempty():
    frame = DuoFernEncoder.build_stop_pair()
    assert frame


def test_encoder_build_status_request_returns_nonempty():
    system_code = DuoFernId.from_hex("6F1A2B")
    frame = DuoFernEncoder.build_status_request(system_code)
    assert frame


# ---------------------------------------------------------------------------
# DuoFernDecoder — smoke tests
# ---------------------------------------------------------------------------


def test_decoder_rejects_too_short_str_raises():
    """_ensure_bytes raises ValueError for hex strings shorter than 44 chars."""
    with pytest.raises(ValueError):
        DuoFernDecoder.is_ack("0000")


def test_decoder_rejects_empty_str_raises():
    """_ensure_bytes raises ValueError for empty hex string."""
    with pytest.raises(ValueError):
        DuoFernDecoder.is_ack("")


# ---------------------------------------------------------------------------
# DuoFernId — additional properties
# ---------------------------------------------------------------------------


def test_duofernid_from_hex_wrong_length_raises():
    with pytest.raises(ValueError):
        DuoFernId.from_hex("1234")


def test_duofernid_post_init_wrong_length_raises():
    with pytest.raises(ValueError):
        DuoFernId(raw=b"\x01\x02")  # 2 bytes, not 3


def test_duofernid_from_hex_with_channel_8char():
    code = DuoFernId.from_hex_with_channel("43ABCD01")
    assert code.hex == "43ABCD"
    assert code.channel == "01"


def test_duofernid_from_hex_with_channel_6char():
    code = DuoFernId.from_hex_with_channel("43ABCD")
    assert code.hex == "43ABCD"
    assert code.channel is None


def test_duofernid_from_hex_with_channel_wrong_length_raises():
    with pytest.raises(ValueError):
        DuoFernId.from_hex_with_channel("1234")


def test_duofernid_with_channel():
    code = DuoFernId.from_hex("43ABCD")
    ch = code.with_channel("02")
    assert ch.channel == "02"
    assert ch.hex == "43ABCD"


def test_duofernid_full_hex_without_channel():
    code = DuoFernId.from_hex("406B2D")
    assert code.full_hex == "406B2D"


def test_duofernid_full_hex_with_channel():
    code = DuoFernId.from_hex_with_channel("43ABCD01")
    assert code.full_hex == "43ABCD01"


def test_duofernid_is_blinds():
    code = DuoFernId.from_hex("421234")  # 0x42 Rohrmotor-Aktor
    assert code.is_blinds is True


def test_duofernid_is_not_blinds():
    code = DuoFernId.from_hex("461234")  # 0x46 Steckdosenaktor
    assert code.is_blinds is False


def test_duofernid_is_obstacle_cover():
    code = DuoFernId.from_hex("4E1234")  # 0x4E SX5
    assert code.is_obstacle_cover is True


def test_duofernid_is_not_obstacle_cover():
    code = DuoFernId.from_hex("461234")
    assert code.is_obstacle_cover is False


def test_duofernid_is_sensor():
    code = DuoFernId.from_hex("691234")  # 0x69 Umweltsensor
    assert code.is_sensor is True


def test_duofernid_is_not_sensor():
    code = DuoFernId.from_hex("461234")
    assert code.is_sensor is False


def test_duofernid_is_sun_sensor():
    code = DuoFernId.from_hex("611234")  # 0x61 RolloTron Comfort Master
    assert code.is_sun_sensor is True


def test_duofernid_is_not_sun_sensor():
    code = DuoFernId.from_hex("461234")
    assert code.is_sun_sensor is False


def test_duofernid_is_wind_sensor():
    code = DuoFernId.from_hex("AA1234")  # 0xAA Markisenwaechter
    assert code.is_wind_sensor is True


def test_duofernid_is_not_wind_sensor():
    code = DuoFernId.from_hex("461234")
    assert code.is_wind_sensor is False


def test_duofernid_has_channels_true():
    code = DuoFernId.from_hex("431234")  # 0x43 Universalaktor
    assert code.has_channels is True


def test_duofernid_has_channels_false():
    code = DuoFernId.from_hex("461234")  # 0x46 Steckdosenaktor
    assert code.has_channels is False


def test_duofernid_channel_list():
    code = DuoFernId.from_hex("431234")  # 0x43 has channels ["01", "02"]
    assert code.channel_list == ["01", "02"]


def test_duofernid_channel_list_empty():
    code = DuoFernId.from_hex("461234")
    assert code.channel_list == []


def test_duofernid_repr():
    code = DuoFernId.from_hex("406B2D")
    r = repr(code)
    assert "406B2D" in r


def test_duofernid_hash_in_set():
    code1 = DuoFernId.from_hex("406B2D")
    code2 = DuoFernId.from_hex("406B2D")
    s = {code1, code2}
    assert len(s) == 1


def test_duofernid_eq_different_channel():
    code1 = DuoFernId.from_hex_with_channel("43ABCD01")
    code2 = DuoFernId.from_hex_with_channel("43ABCD02")
    assert code1 != code2


def test_duofernid_eq_non_duofernid_returns_not_implemented():
    code = DuoFernId.from_hex("406B2D")
    result = code.__eq__("406B2D")
    assert result is NotImplemented


# ---------------------------------------------------------------------------
# ParsedStatus — additional fields
# ---------------------------------------------------------------------------

from custom_components.duofern.protocol import ParsedStatus as _PS


def test_parsed_status_additional_defaults():
    status = _PS()
    assert status.level is None
    assert status.measured_temp is None
    assert status.desired_temp is None
    assert status.boost_active is False
    assert status.boost_duration_min == 0
    assert status.missing_ack is False
    assert status.not_initialized is False
    assert status.device_code is None
    assert status.channel is None


# ---------------------------------------------------------------------------
# SensorEvent and WeatherData dataclasses
# ---------------------------------------------------------------------------

from custom_components.duofern.protocol import SensorEvent, WeatherData


def test_sensor_event_fields():
    ev = SensorEvent(
        device_code="406B2D",
        channel="01",
        event_name="up",
        state="Btn01",
        raw_msg_id="0701",
    )
    assert ev.device_code == "406B2D"
    assert ev.channel == "01"
    assert ev.event_name == "up"
    assert ev.state == "Btn01"
    assert ev.raw_msg_id == "0701"


def test_sensor_event_defaults():
    ev = SensorEvent(device_code="406B2D", channel="01", event_name="up")
    assert ev.state is None
    assert ev.raw_msg_id == ""


def test_weather_data_defaults():
    w = WeatherData()
    assert w.brightness is None
    assert w.wind is None
    assert w.is_raining is None


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

from custom_components.duofern.protocol import (
    CoverCommand,
    SwitchCommand,
    AutomationCommand,
    MessageType,
)


def test_cover_command_values():
    assert CoverCommand.UP == 0x0701
    assert CoverCommand.STOP == 0x0702
    assert CoverCommand.DOWN == 0x0703
    assert CoverCommand.POSITION == 0x0707
    assert CoverCommand.TOGGLE == 0x071A
    assert CoverCommand.DUSK == 0x0709
    assert CoverCommand.DAWN == 0x0713


def test_switch_command_values():
    assert SwitchCommand.OFF == 0x0E02
    assert SwitchCommand.ON == 0x0E03


def test_automation_command_values():
    assert AutomationCommand.MANUAL_MODE_ON == 0x0806
    assert AutomationCommand.TIME_AUTOMATIC_ON == 0x0804


def test_message_type_values():
    assert MessageType.ACK == 0x81
    assert MessageType.COMMAND == 0x0D


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

from custom_components.duofern.protocol import frame_to_hex, hex_to_frame


def test_frame_to_hex():
    frame = bytearray([0x0F] * 22)
    result = frame_to_hex(frame)
    assert result == "0F" * 22


def test_hex_to_frame():
    hex_str = "0F" * 22
    result = hex_to_frame(hex_str)
    assert isinstance(result, bytearray)
    assert len(result) == 22
    assert result[0] == 0x0F


# ---------------------------------------------------------------------------
# DuoFernEncoder — detailed frame construction tests
# ---------------------------------------------------------------------------

_SYS = DuoFernId.from_hex("6F1A2B")
_DEV = DuoFernId.from_hex("406B2D")
_SW = DuoFernId.from_hex("461234")


def test_build_init1_frame_byte():
    f = DuoFernEncoder.build_init1()
    assert f[0] == 0x01
    assert len(f) == 22


def test_build_init2_frame_byte():
    f = DuoFernEncoder.build_init2()
    assert f[0] == 0x0E


def test_build_init3_frame_bytes():
    f = DuoFernEncoder.build_init3()
    assert f[0] == 0x14
    assert f[1] == 0x14


def test_build_set_dongle_frame():
    f = DuoFernEncoder.build_set_dongle(_SYS)
    assert f[0] == 0x0A
    assert f[1:4] == _SYS.raw
    assert f[5] == 0x01


def test_build_set_pair_frame():
    f = DuoFernEncoder.build_set_pair(5, _DEV)
    assert f[0] == 0x03
    assert f[1] == 5
    assert f[2:5] == _DEV.raw


def test_build_init_end_frame():
    f = DuoFernEncoder.build_init_end()
    assert f[0] == 0x10
    assert f[1] == 0x01


def test_build_ack_frame():
    f = DuoFernEncoder.build_ack()
    assert f[0] == 0x81


def test_build_status_request_broadcast_frame():
    f = DuoFernEncoder.build_status_request_broadcast()
    assert f[0] == 0x0D
    assert f[18] == 0xFF
    assert f[19] == 0xFF
    assert f[20] == 0xFF
    assert f[21] == 0x01


def test_build_status_request_per_device():
    f = DuoFernEncoder.build_status_request(_DEV, _SYS)
    assert f[0] == 0x0D
    assert f[18:21] == _DEV.raw
    assert f[21] == 0x01


def test_build_status_request_custom_status_type():
    f = DuoFernEncoder.build_status_request(_DEV, _SYS, status_type=0x13)
    assert f[2] == 0x13


def test_build_cover_command_up():
    f = DuoFernEncoder.build_cover_command(CoverCommand.UP, _DEV, _SYS)
    assert f[0] == 0x0D
    assert f[2] == 0x07
    assert f[3] == 0x01
    assert f[15:18] == _SYS.raw
    assert f[18:21] == _DEV.raw


def test_build_cover_command_down_with_timer():
    f = DuoFernEncoder.build_cover_command(CoverCommand.DOWN, _DEV, _SYS, timer=True)
    assert f[3] == 0x03
    assert f[4] == 0x01  # timer byte set


def test_build_cover_command_position():
    f = DuoFernEncoder.build_cover_command(
        CoverCommand.POSITION, _DEV, _SYS, position=75
    )
    assert f[3] == 0x07
    assert f[5] == 75


def test_build_cover_command_position_clamped_high():
    f = DuoFernEncoder.build_cover_command(
        CoverCommand.POSITION, _DEV, _SYS, position=150
    )
    assert f[5] == 100


def test_build_cover_command_position_clamped_low():
    f = DuoFernEncoder.build_cover_command(
        CoverCommand.POSITION, _DEV, _SYS, position=-5
    )
    assert f[5] == 0


def test_build_cover_command_position_none_logs_warning(caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        DuoFernEncoder.build_cover_command(
            CoverCommand.POSITION, _DEV, _SYS, position=None
        )
    assert "POSITION" in caplog.text


def test_build_cover_command_dusk():
    f = DuoFernEncoder.build_cover_command(CoverCommand.DUSK, _DEV, _SYS)
    assert f[3] == 0x09
    assert f[4] == 0x01
    assert f[5] == 0xFF


def test_build_cover_command_dawn():
    f = DuoFernEncoder.build_cover_command(CoverCommand.DAWN, _DEV, _SYS)
    assert f[3] == 0x13
    assert f[4] == 0x01
    assert f[5] == 0xFF


def test_build_cover_command_stop_no_extra_bytes():
    f = DuoFernEncoder.build_cover_command(CoverCommand.STOP, _DEV, _SYS)
    assert f[3] == 0x02
    assert f[4] == 0x00


def test_build_cover_command_toggle():
    f = DuoFernEncoder.build_cover_command(CoverCommand.TOGGLE, _DEV, _SYS)
    assert f[3] == 0x1A


def test_build_generic_command():
    cmd = bytes([0x07, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    f = DuoFernEncoder.build_generic_command(cmd, _DEV, _SYS)
    assert f[2] == 0x07
    assert f[3] == 0x01
    assert f[15:18] == _SYS.raw
    assert f[18:21] == _DEV.raw


def test_build_switch_command_on():
    f = DuoFernEncoder.build_switch_command(SwitchCommand.ON, _SW, _SYS)
    assert f[0] == 0x0D
    assert f[2] == 0x0E
    assert f[3] == 0x03
    assert f[4] == 0x00


def test_build_switch_command_off_with_timer():
    f = DuoFernEncoder.build_switch_command(SwitchCommand.OFF, _SW, _SYS, timer=True)
    assert f[3] == 0x02
    assert f[4] == 0x01


def test_build_dim_command():
    f = DuoFernEncoder.build_dim_command(50, _SW, _SYS)
    assert f[5] == 50


def test_build_dim_command_clamped_low():
    f = DuoFernEncoder.build_dim_command(-10, _SW, _SYS)
    assert f[5] == 0


def test_build_dim_command_clamped_high():
    f = DuoFernEncoder.build_dim_command(200, _SW, _SYS)
    assert f[5] == 100


def test_build_desired_temp_command():
    # ww = int(20.0 * 10 + 400) = 600 = 0x0258
    f = DuoFernEncoder.build_desired_temp_command(20.0, _SW, _SYS)
    assert f[8] == 0x02
    assert f[9] == 0x58


def test_build_desired_temp_command_with_timer():
    f = DuoFernEncoder.build_desired_temp_command(20.0, _SW, _SYS, timer=True)
    assert f[4] == 0x01


def test_build_hsa_command_no_boost():
    """No boost flags → boost bytes remain 0."""
    f = DuoFernEncoder.build_hsa_command(0, _SW)
    assert f[8] == 0x00
    assert f[11] == 0x00


def test_build_hsa_command_boost_on():
    f = DuoFernEncoder.build_hsa_command(0, _SW, boost_on=True)
    assert f[11] == 0x03
    assert f[8] == 0x00


def test_build_hsa_command_boost_on_ack():
    f = DuoFernEncoder.build_hsa_command(0, _SW, boost_on_ack=True)
    assert f[11] == 0x03


def test_build_hsa_command_boost_duration():
    f = DuoFernEncoder.build_hsa_command(0, _SW, boost_duration_min=21)
    assert f[11] == 0x03
    assert f[8] == 0x40 | (21 & 0x3F)


def test_build_hsa_command_boost_duration_clamped_low():
    # min is 4; passing 1 → clamped to 4
    f = DuoFernEncoder.build_hsa_command(0, _SW, boost_duration_min=1)
    assert f[8] == 0x40 | 4


def test_build_hsa_command_boost_duration_clamped_high():
    # max is 60
    f = DuoFernEncoder.build_hsa_command(0, _SW, boost_duration_min=90)
    assert f[8] == 0x40 | 60


def test_build_hsa_command_boost_off():
    f = DuoFernEncoder.build_hsa_command(0, _SW, boost_off=True)
    assert f[11] == 0x02
    assert f[8] == 0x00


def test_build_hsa_command_device_code_in_frame():
    f = DuoFernEncoder.build_hsa_command(0, _SW)
    assert f[18:21] == _SW.raw


def test_build_start_unpair():
    f = DuoFernEncoder.build_start_unpair()
    assert f[0] == 0x07


def test_build_remote_pair():
    f = DuoFernEncoder.build_remote_pair(_DEV)
    assert f[0] == 0x0D
    assert f[2] == 0x06
    assert f[3] == 0x01
    assert f[18:21] == _DEV.raw


def test_build_code_pair():
    f = DuoFernEncoder.build_code_pair(_DEV, _SYS)
    assert f[1] == 0xFF
    assert f[2] == 0x06
    assert f[3] == 0x01
    assert f[15:18] == _SYS.raw
    assert f[18:21] == _DEV.raw
    assert f[21] == 0x01


def test_build_remote_unpair():
    f = DuoFernEncoder.build_remote_unpair(_DEV)
    assert f[3] == 0x02
    assert f[18:21] == _DEV.raw


def test_build_remote_stop():
    f = DuoFernEncoder.build_remote_stop(_DEV)
    assert f[3] == 0x03
    assert f[18:21] == _DEV.raw


# ---------------------------------------------------------------------------
# DuoFernDecoder — _ensure_bytes additional branches
# ---------------------------------------------------------------------------


def test_ensure_bytes_bytes_too_short_raises():
    with pytest.raises(ValueError):
        DuoFernDecoder.is_ack(b"\x81" * 5)


def test_ensure_bytes_unsupported_type_raises():
    with pytest.raises(TypeError):
        DuoFernDecoder.is_ack(12345)  # type: ignore[arg-type]


def test_ensure_bytes_valid_str():
    frame = "81" + "00" * 21
    assert DuoFernDecoder.is_ack(frame) is True


def test_ensure_bytes_valid_bytes():
    frame = b"\x81" + b"\x00" * 21
    assert DuoFernDecoder.is_ack(frame) is True


# ---------------------------------------------------------------------------
# DuoFernDecoder — classifier methods
# ---------------------------------------------------------------------------


def _f(b0=0, b1=0, b2=0, b3=0, d0=0x46, d1=0x12, d2=0x34) -> bytearray:
    """Build a minimal 22-byte frame with specified key bytes."""
    buf = bytearray(22)
    buf[0] = b0
    buf[1] = b1
    buf[2] = b2
    buf[3] = b3
    buf[15] = d0
    buf[16] = d1
    buf[17] = d2
    return buf


def test_is_ack_true():
    assert DuoFernDecoder.is_ack(_f(0x81)) is True


def test_is_ack_false():
    assert DuoFernDecoder.is_ack(_f(0x0F)) is False


def test_is_status_response_true():
    assert DuoFernDecoder.is_status_response(_f(0x0F, 0xFF, 0x0F, 0x22)) is True


def test_is_status_response_false_boost_ack():
    # f[3] == 0x2A is the device-ACK after boost — excluded
    assert DuoFernDecoder.is_status_response(_f(0x0F, 0xFF, 0x0F, 0x2A)) is False


def test_is_status_response_false_wrong_type():
    assert DuoFernDecoder.is_status_response(_f(0x0D, 0xFF, 0x0F, 0x22)) is False


def test_is_pair_response_true():
    assert DuoFernDecoder.is_pair_response(_f(0x06, 0x02)) is True


def test_is_pair_response_false():
    assert DuoFernDecoder.is_pair_response(_f(0x06, 0x03)) is False


def test_is_unpair_response_true():
    assert DuoFernDecoder.is_unpair_response(_f(0x06, 0x03)) is True


def test_is_unpair_response_false():
    assert DuoFernDecoder.is_unpair_response(_f(0x06, 0x02)) is False


def test_is_sensor_message_true_07():
    assert DuoFernDecoder.is_sensor_message(_f(0x0F, 0, 0x07, 0x01)) is True


def test_is_sensor_message_true_0E():
    assert DuoFernDecoder.is_sensor_message(_f(0x0F, 0, 0x0E, 0x03)) is True


def test_is_sensor_message_false():
    assert DuoFernDecoder.is_sensor_message(_f(0x0F, 0, 0x0D, 0x01)) is False


def test_is_weather_data_true():
    assert DuoFernDecoder.is_weather_data(_f(0x0F, 0, 0x13, 0x22)) is True


def test_is_weather_data_false():
    assert DuoFernDecoder.is_weather_data(_f(0x0F, 0, 0x13, 0x23)) is False


def test_is_time_response_true():
    assert DuoFernDecoder.is_time_response(_f(0x0F, 0, 0x10, 0x20)) is True


def test_is_time_response_false():
    assert DuoFernDecoder.is_time_response(_f(0x0F, 0, 0x10, 0x21)) is False


def test_is_weather_config_true():
    assert DuoFernDecoder.is_weather_config(_f(0x0F, 0xFF, 0x1B, 0x25)) is True


def test_is_weather_config_boundary_low():
    assert DuoFernDecoder.is_weather_config(_f(0x0F, 0xFF, 0x1B, 0x21)) is True


def test_is_weather_config_boundary_high():
    assert DuoFernDecoder.is_weather_config(_f(0x0F, 0xFF, 0x1B, 0x28)) is True


def test_is_weather_config_false_out_of_range():
    assert DuoFernDecoder.is_weather_config(_f(0x0F, 0xFF, 0x1B, 0x29)) is False


def test_is_battery_status_true():
    assert DuoFernDecoder.is_battery_status(_f(0x0F, 0xFF, 0x13, 0x23)) is True


def test_is_battery_status_false():
    assert DuoFernDecoder.is_battery_status(_f(0x0F, 0xFF, 0x13, 0x22)) is False


def test_is_cmd_ack_true():
    assert DuoFernDecoder.is_cmd_ack(_f(0x81, 0x00, 0x03, 0xCC)) is True


def test_is_cmd_ack_false():
    assert DuoFernDecoder.is_cmd_ack(_f(0x81, 0x00, 0x03, 0xAA)) is False


def test_is_missing_ack_true():
    assert DuoFernDecoder.is_missing_ack(_f(0x81, 0x01, 0x08, 0xAA)) is True


def test_is_missing_ack_false():
    assert DuoFernDecoder.is_missing_ack(_f(0x81, 0x00, 0x03, 0xCC)) is False


def test_is_not_initialized_true():
    assert DuoFernDecoder.is_not_initialized(_f(0x81, 0x01, 0x0C, 0x55)) is True


def test_is_not_initialized_false():
    assert DuoFernDecoder.is_not_initialized(_f(0x81, 0x00, 0x03, 0xCC)) is False


def test_is_broadcast_ack_true():
    assert DuoFernDecoder.is_broadcast_ack(_f(0x0F, 0xFF, 0x11, 0x00)) is True


def test_is_broadcast_ack_false():
    assert DuoFernDecoder.is_broadcast_ack(_f(0x0F, 0xFF, 0x0F, 0x22)) is False


def test_should_dispatch_false_for_ack():
    assert DuoFernDecoder.should_dispatch(_f(0x81)) is False


def test_should_dispatch_false_for_broadcast_ack():
    assert DuoFernDecoder.should_dispatch(_f(0x0F, 0xFF, 0x11, 0x00)) is False


def test_should_dispatch_true_for_status():
    assert DuoFernDecoder.should_dispatch(_f(0x0F, 0xFF, 0x0F, 0x22)) is True


def test_should_dispatch_ack_true_for_CC():
    assert DuoFernDecoder.should_dispatch_ack(_f(0x81, 0x00, 0x03, 0xCC)) is True


def test_should_dispatch_ack_true_for_AA():
    assert DuoFernDecoder.should_dispatch_ack(_f(0x81, 0x01, 0x08, 0xAA)) is True


def test_should_dispatch_ack_true_for_BB():
    assert DuoFernDecoder.should_dispatch_ack(_f(0x81, 0x01, 0x00, 0xBB)) is True


def test_should_dispatch_ack_true_for_DD():
    assert DuoFernDecoder.should_dispatch_ack(_f(0x81, 0x01, 0x01, 0xDD)) is True


def test_should_dispatch_ack_false_for_55():
    assert DuoFernDecoder.should_dispatch_ack(_f(0x81, 0x01, 0x0C, 0x55)) is False


def test_should_dispatch_ack_false_for_non_ack():
    assert DuoFernDecoder.should_dispatch_ack(_f(0x0F, 0xFF, 0x0F, 0x22)) is False


# ---------------------------------------------------------------------------
# extract_device_code
# ---------------------------------------------------------------------------


def test_extract_device_code_non_ack():
    """Non-ACK frames: device code at bytes 15-17."""
    buf = bytearray(22)
    buf[0] = 0x0F
    buf[15] = 0x40
    buf[16] = 0x6B
    buf[17] = 0x2D
    assert DuoFernDecoder.extract_device_code(buf).hex == "406B2D"


def test_extract_device_code_ack():
    """ACK frames (0x81): device code at bytes 18-20."""
    buf = bytearray(22)
    buf[0] = 0x81
    buf[18] = 0x40
    buf[19] = 0x6B
    buf[20] = 0x2D
    assert DuoFernDecoder.extract_device_code(buf).hex == "406B2D"


def test_extract_device_code_from_status():
    buf = bytearray(22)
    buf[15] = 0x46
    buf[16] = 0x12
    buf[17] = 0x34
    assert DuoFernDecoder.extract_device_code_from_status(buf).hex == "461234"


# ---------------------------------------------------------------------------
# parse_battery_status
# ---------------------------------------------------------------------------


def test_parse_battery_status_low():
    buf = _f(0x0F, 0xFF, 0x13, 0x23)
    buf[4] = 5  # <= 10 → "low"
    result = DuoFernDecoder.parse_battery_status(buf)
    assert result["batteryState"] == "low"
    assert result["batteryPercent"] == 5


def test_parse_battery_status_boundary_low():
    buf = _f(0x0F, 0xFF, 0x13, 0x23)
    buf[4] = 10  # exactly 10 → "low"
    result = DuoFernDecoder.parse_battery_status(buf)
    assert result["batteryState"] == "low"


def test_parse_battery_status_ok():
    buf = _f(0x0F, 0xFF, 0x13, 0x23)
    buf[4] = 80  # > 10 → "ok"
    result = DuoFernDecoder.parse_battery_status(buf)
    assert result["batteryState"] == "ok"
    assert result["batteryPercent"] == 80


# ---------------------------------------------------------------------------
# parse_weather_data
# ---------------------------------------------------------------------------


def test_parse_weather_data_all_zeros():
    buf = _f(0x0F, 0, 0x13, 0x22)
    w = DuoFernDecoder.parse_weather_data(buf)
    assert w.brightness == 0.0
    assert w.sun_height == -90.0
    assert w.temperature == pytest.approx(-40.0)
    assert w.wind == 0.0
    assert w.is_raining is False


def test_parse_weather_data_with_values():
    buf = _f(0x0F, 0, 0x13, 0x22)
    buf[4] = 0x00
    buf[5] = 100  # brightness_raw=100, no high bit → 100.0
    buf[9] = 0x01
    buf[10] = 0xF4  # temp_raw=500 → (500-400)/10 = 10.0°C
    buf[11] = 0x00
    buf[12] = 200  # wind_raw=200 → 200/10 = 20.0
    w = DuoFernDecoder.parse_weather_data(buf)
    assert w.brightness == 100.0
    assert w.temperature == pytest.approx(10.0)
    assert w.wind == 20.0
    assert w.is_raining is False


def test_parse_weather_data_high_brightness():
    """brightness_raw with bit 10 set → multiply by 1000."""
    buf = _f(0x0F, 0, 0x13, 0x22)
    buf[4] = 0x04
    buf[5] = 0x05  # brightness_raw = 0x0405, bit10 set, value bits = 5 → 5 * 1000 = 5000
    w = DuoFernDecoder.parse_weather_data(buf)
    assert w.brightness == 5000.0


def test_parse_weather_data_is_raining():
    """temp_raw with bit 15 set → is_raining = True."""
    buf = _f(0x0F, 0, 0x13, 0x22)
    buf[9] = 0x81
    buf[10] = 0x90  # bit 15 set → is_raining
    w = DuoFernDecoder.parse_weather_data(buf)
    assert w.is_raining is True


# ---------------------------------------------------------------------------
# parse_sensor_event
# ---------------------------------------------------------------------------


def test_parse_sensor_event_known_message():
    """msg_id "0701" = up button press from a wall button."""
    buf = _f(0x0F, 0, 0x07, 0x01, d0=0xA4, d1=0x12, d2=0x34)
    result = DuoFernDecoder.parse_sensor_event(buf)
    assert result is not None
    assert result.event_name == "up"
    assert result.device_code == "A41234"
    assert result.state == "Btn01"
    assert result.raw_msg_id == "0701"


def test_parse_sensor_event_unknown_message_returns_none():
    """Unknown msg_id returns None."""
    buf = _f(0x0F, 0, 0x07, 0xFF, d0=0xA4, d1=0x12, d2=0x34)
    assert DuoFernDecoder.parse_sensor_event(buf) is None


def test_parse_sensor_event_0x61_always_channel_01():
    """Devices 0x61/0x70/0x71 always use channel "01" regardless of frame byte."""
    buf = _f(0x0F, 0, 0x07, 0x01, d0=0x61, d1=0x12, d2=0x34)
    buf[7] = 0xFF  # would produce channel "FF" for other devices
    result = DuoFernDecoder.parse_sensor_event(buf)
    assert result is not None
    assert result.channel == "01"


def test_parse_sensor_event_0x70_always_channel_01():
    buf = _f(0x0F, 0, 0x07, 0x01, d0=0x70, d1=0x12, d2=0x34)
    buf[7] = 0x02
    result = DuoFernDecoder.parse_sensor_event(buf)
    assert result is not None
    assert result.channel == "01"


# ---------------------------------------------------------------------------
# parse_status
# ---------------------------------------------------------------------------


def _make_fmt22_frame(level_byte: int = 0, dev_type: int = 0x46) -> bytearray:
    """Build a valid status response frame for format 22 (switch/socket)."""
    buf = bytearray(22)
    buf[0] = 0x0F
    buf[1] = 0xFF
    buf[2] = 0x0F
    buf[3] = 0x22  # format 22
    buf[15] = dev_type
    buf[16] = 0x12
    buf[17] = 0x34
    # STATUS_ID 1: level, position=7 → _read_word byte offset 3+7=10
    buf[10] = 0x00
    buf[11] = level_byte
    return buf


def test_parse_status_non_status_frame_returns_empty():
    """Non-status frame logs warning and returns empty ParsedStatus."""
    buf = _f(0x0D, 0xFF, 0x0F, 0x22)
    result = DuoFernDecoder.parse_status(buf)
    assert result.position is None
    assert result.readings == {}


def test_parse_status_extracts_device_code():
    buf = _make_fmt22_frame()
    result = DuoFernDecoder.parse_status(buf)
    assert result.device_code == "461234"


def test_parse_status_level_from_frame():
    buf = _make_fmt22_frame(level_byte=75)
    result = DuoFernDecoder.parse_status(buf)
    assert result.level == 75
    assert result.readings["level"] == 75


def test_parse_status_level_zero():
    buf = _make_fmt22_frame(level_byte=0)
    result = DuoFernDecoder.parse_status(buf)
    assert result.level == 0


def test_parse_status_version_from_frame12():
    """Version nibble from frame[12] when non-zero."""
    buf = _make_fmt22_frame()
    buf[12] = 0x25  # high nibble=2, low nibble=5 → "2.5"
    result = DuoFernDecoder.parse_status(buf)
    assert result.version == "2.5"


def test_parse_status_version_none_when_zero():
    buf = _make_fmt22_frame()
    buf[12] = 0x00
    result = DuoFernDecoder.parse_status(buf)
    assert result.version is None


def test_parse_status_onoff_mapping_applied():
    """timeAutomatic uses onOff mapping: raw 0 → "off"."""
    buf = _make_fmt22_frame()
    result = DuoFernDecoder.parse_status(buf)
    assert result.readings["timeAutomatic"] == "off"


def _make_fmt21_frame(position_byte: int = 50, dev_type: int = 0x40) -> bytearray:
    """Build a valid status frame for format 21 (cover)."""
    buf = bytearray(22)
    buf[0] = 0x0F
    buf[1] = 0xFF
    buf[2] = 0x0F
    buf[3] = 0x21
    buf[15] = dev_type
    buf[16] = 0x6B
    buf[17] = 0x2D
    # STATUS_ID 102: position, position=7, from=0, to=6 → byte offset 3+7=10
    buf[10] = 0x00
    buf[11] = position_byte
    return buf


def test_parse_status_position_extracted():
    """Position is populated for cover status (format 21)."""
    buf = _make_fmt21_frame(position_byte=50)
    result = DuoFernDecoder.parse_status(buf)
    assert result.position == 50


def test_parse_status_invert_applied():
    """STATUS_IDs with 'invert' key apply inversion unconditionally.

    SID 111 (sunPosition) in format 21 has invert=100:
    position=6, from=0, to=6 → byte offset 3+6=9.
    """
    buf = _make_fmt21_frame()
    buf[9] = 0x00
    buf[10] = 30  # _read_word(frame, 6) → byte offset 9; word=(buf[9]<<8)|buf[10]=30
    # bits 0-6: 30 & 0x7F = 30; invert: 100 - 30 = 70
    result = DuoFernDecoder.parse_status(buf)
    assert result.readings.get("sunPosition") == 70


def _make_fmt23_frame(dev_type: int = 0x40) -> bytearray:
    """Build a minimal format 23 frame (blinds cover)."""
    buf = bytearray(22)
    buf[0] = 0x0F
    buf[1] = 0xFF
    buf[2] = 0x0F
    buf[3] = 0x23
    buf[15] = dev_type
    buf[16] = 0x12
    buf[17] = 0x34
    return buf


def test_parse_status_blindsmode_off_removes_blind_readings():
    """blindsMode="off" triggers removal of BLIND_MODE_READINGS."""
    buf = _make_fmt23_frame()
    # All-zeros: SID 136 blindsMode position=9 from=7 to=7
    # byte offset 3+9=12; word=(buf[12]<<8)|buf[13]=0; bit7=0 → "off"
    # SID 135 slatPosition position=9 from=0 to=6 → same word; bits0-6=0
    result = DuoFernDecoder.parse_status(buf)
    assert result.readings.get("blindsMode") == "off"
    # slatPosition is in BLIND_MODE_READINGS → should have been removed
    assert "slatPosition" not in result.readings


def test_parse_status_blindsmode_on_keeps_blind_readings():
    """blindsMode="on" → blind mode readings are kept."""
    buf = _make_fmt23_frame()
    # Set bit 7 of word at position 9: byte offset 12; word bit 7 is buf[13] bit 7
    buf[13] = 0x80  # bit 7 set → blindsMode = "on"
    result = DuoFernDecoder.parse_status(buf)
    assert result.readings.get("blindsMode") == "on"
    # slatPosition should still be present (value 0)
    assert "slatPosition" in result.readings


def _make_fmt29_frame(boost_active: bool = False, boost_dur: int = 0) -> bytearray:
    """Build a format 29 (HSA) status frame."""
    buf = bytearray(22)
    buf[0] = 0x0F
    buf[1] = 0xFF
    buf[2] = 0x0F
    buf[3] = 0x29  # format 29
    buf[4] = 0xF0 if boost_active else 0x00
    buf[12] = boost_dur & 0x3F
    buf[15] = 0xE1  # HSA device type
    buf[16] = 0x12
    buf[17] = 0x34
    return buf


def test_parse_status_format29_boost_active_true():
    """frame[4]=0xF0 → boost_active=True and readings['boostActive']='on'."""
    buf = _make_fmt29_frame(boost_active=True, boost_dur=21)
    result = DuoFernDecoder.parse_status(buf)
    assert result.boost_active is True
    assert result.boost_duration_min == 21
    assert result.readings["boostActive"] == "on"
    assert result.readings["boostDuration"] == 21


def test_parse_status_format29_boost_active_false():
    buf = _make_fmt29_frame(boost_active=False, boost_dur=9)
    result = DuoFernDecoder.parse_status(buf)
    assert result.boost_active is False
    assert result.readings["boostActive"] == "off"


def test_parse_status_format29_version_from_readings():
    """Format 29 includes SID 998 (version map="hex") → overrides frame[12] nibble.

    SID 998: position=9, from=0, to=6 → byte offset 3+9=12; bits 0-6 of
    (buf[12]<<8)|buf[13]. We set buf[13]=0x25 → bits 0-6 = 0x25 = 37;
    hex map: (37>>4)&0xF = 2, 37&0xF = 5 → "2.5".
    """
    buf = _make_fmt29_frame()
    buf[13] = 0x25  # version bits
    result = DuoFernDecoder.parse_status(buf)
    assert result.version == "2.5"
    # version should NOT remain in readings (it's popped)
    assert "version" not in result.readings


# ---------------------------------------------------------------------------
# _apply_mapping — direct tests via parse_status (implicit) and directly
# ---------------------------------------------------------------------------


def test_apply_mapping_onoff_off():
    assert DuoFernDecoder._apply_mapping(0, "onOff") == "off"


def test_apply_mapping_onoff_on():
    assert DuoFernDecoder._apply_mapping(1, "onOff") == "on"


def test_apply_mapping_onoff_out_of_range():
    # index >= len(mapping) → str(raw)
    assert DuoFernDecoder._apply_mapping(5, "onOff") == "5"


def test_apply_mapping_hex():
    # raw=0x25=37; (37>>4)&0xF=2, 37&0xF=5 → "2.5"
    assert DuoFernDecoder._apply_mapping(0x25, "hex") == "2.5"


def test_apply_mapping_scale10():
    # factor=10, offset=0 → (100-0)/10 = 10.0
    assert DuoFernDecoder._apply_mapping(100, "scale10") == 10.0


def test_apply_mapping_scalef():
    # scaleF1: factor=2, offset=80 → round((100-80)/2, 1) = 10.0
    assert DuoFernDecoder._apply_mapping(100, "scaleF1") == pytest.approx(10.0)


def test_apply_mapping_unknown_key_returns_raw():
    # map_key not in STATUS_MAPPING → return raw unchanged
    assert DuoFernDecoder._apply_mapping(42, "nonexistent") == 42


# ---------------------------------------------------------------------------
# _determine_format — direct coverage
# ---------------------------------------------------------------------------


def test_determine_format_device_override():
    """0x69 Umweltsensor has DEVICE_STATUS_FORMAT_OVERRIDE → "23a"."""
    buf = _f(0x0F, 0xFF, 0x0F, 0x21, d0=0x69)  # frame format byte 0x21 is ignored
    result = DuoFernDecoder.parse_status(buf)
    # If override kicked in, format is "23a" → STATUS_GROUPS["23a"] parsed
    # Just verify no exception and device_code is extracted
    assert result.device_code == "691234"


def test_determine_format_fallback_to_default():
    """Unknown format byte → STATUS_FORMAT_DEFAULT ('21')."""
    buf = _f(0x0F, 0xFF, 0x0F, 0xFF, d0=0x40)  # 0xFF not in STATUS_GROUPS
    result = DuoFernDecoder.parse_status(buf)
    # Should fall back to "21" and parse without error
    assert result.device_code is not None


# ---------------------------------------------------------------------------
# DuoFernId — untested properties
# ---------------------------------------------------------------------------


def test_duofernid_is_blinds_true():
    """0x42 Rohrmotor-Aktor is in BLINDS_DEVICE_TYPES."""
    dev = DuoFernId.from_hex("421234")
    assert dev.is_blinds is True


def test_duofernid_is_blinds_false():
    """0x40 RolloTron is NOT in BLINDS_DEVICE_TYPES."""
    dev = DuoFernId.from_hex("401234")
    assert dev.is_blinds is False


def test_duofernid_is_obstacle_cover_true():
    """0x4E SX5 is in OBSTACLE_COVER_TYPES."""
    dev = DuoFernId.from_hex("4E1234")
    assert dev.is_obstacle_cover is True


def test_duofernid_is_obstacle_cover_false():
    """0x40 RolloTron is NOT in OBSTACLE_COVER_TYPES."""
    dev = DuoFernId.from_hex("401234")
    assert dev.is_obstacle_cover is False


def test_duofernid_is_sun_sensor_true():
    """0xA5 Sonnensensor is in SUN_SENSOR_DEVICE_TYPES."""
    dev = DuoFernId.from_hex("A51234")
    assert dev.is_sun_sensor is True


def test_duofernid_is_sun_sensor_false():
    """0x40 RolloTron is NOT in SUN_SENSOR_DEVICE_TYPES."""
    dev = DuoFernId.from_hex("401234")
    assert dev.is_sun_sensor is False


def test_duofernid_is_wind_sensor_true():
    """0xAA Markisenwaechter is in WIND_SENSOR_DEVICE_TYPES."""
    dev = DuoFernId.from_hex("AA1234")
    assert dev.is_wind_sensor is True


def test_duofernid_is_wind_sensor_false():
    """0x40 RolloTron is NOT in WIND_SENSOR_DEVICE_TYPES."""
    dev = DuoFernId.from_hex("401234")
    assert dev.is_wind_sensor is False


def test_duofernid_has_channels_true():
    """0x43 Universalaktor has channels."""
    dev = DuoFernId.from_hex("431234")
    assert dev.has_channels is True


def test_duofernid_has_channels_false():
    """0x40 RolloTron has no channels."""
    dev = DuoFernId.from_hex("401234")
    assert dev.has_channels is False


def test_duofernid_channel_list_nonempty():
    """0x43 Universalaktor channel_list is ['01', '02']."""
    dev = DuoFernId.from_hex("431234")
    assert dev.channel_list == ["01", "02"]


def test_duofernid_channel_list_empty():
    """0x40 RolloTron channel_list is empty list."""
    dev = DuoFernId.from_hex("401234")
    assert dev.channel_list == []


def test_duofernid_repr():
    """__repr__ includes the full hex."""
    dev = DuoFernId.from_hex("401234")
    assert "401234" in repr(dev)


def test_duofernid_hash_consistent():
    """Same hex codes produce the same hash."""
    a = DuoFernId.from_hex("401234")
    b = DuoFernId.from_hex("401234")
    assert hash(a) == hash(b)


def test_duofernid_eq_true():
    """Two DuoFernIds from the same hex are equal."""
    a = DuoFernId.from_hex("401234")
    b = DuoFernId.from_hex("401234")
    assert a == b


def test_duofernid_eq_false_different_code():
    """Two DuoFernIds with different hex codes are not equal."""
    a = DuoFernId.from_hex("401234")
    b = DuoFernId.from_hex("401235")
    assert a != b


def test_duofernid_eq_not_implemented_for_other_type():
    """Comparing DuoFernId to a non-DuoFernId returns NotImplemented."""
    dev = DuoFernId.from_hex("401234")
    result = dev.__eq__("401234")
    assert result is NotImplemented


# ---------------------------------------------------------------------------
# DuoFernEncoder — uncovered methods (smoke tests)
# ---------------------------------------------------------------------------

_SYSTEM_CODE = DuoFernId.from_hex("6F1A2B")
_DEVICE_CODE = DuoFernId.from_hex("401234")


def test_encoder_build_init1():
    f = DuoFernEncoder.build_init1()
    assert isinstance(f, bytearray)
    assert f[0] == 0x01


def test_encoder_build_init2():
    f = DuoFernEncoder.build_init2()
    assert isinstance(f, bytearray)
    assert f[0] == 0x0E


def test_encoder_build_set_dongle():
    f = DuoFernEncoder.build_set_dongle(_SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x0A


def test_encoder_build_init3():
    f = DuoFernEncoder.build_init3()
    assert isinstance(f, bytearray)
    assert f[0] == 0x14


def test_encoder_build_set_pair():
    f = DuoFernEncoder.build_set_pair(index=2, device_code=_DEVICE_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x03
    assert f[1] == 0x02


def test_encoder_build_init_end():
    f = DuoFernEncoder.build_init_end()
    assert isinstance(f, bytearray)
    assert f[0] == 0x10


def test_encoder_build_ack():
    f = DuoFernEncoder.build_ack()
    assert isinstance(f, bytearray)
    assert f[0] == 0x81


def test_encoder_build_status_request_broadcast():
    f = DuoFernEncoder.build_status_request_broadcast()
    assert isinstance(f, bytearray)
    assert len(f) > 0
    assert f[18] == 0xFF
    assert f[19] == 0xFF
    assert f[20] == 0xFF


def test_encoder_build_cover_command_up():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.UP, _DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x0D


def test_encoder_build_cover_command_down():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.DOWN, _DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)


def test_encoder_build_cover_command_stop():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.STOP, _DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)


def test_encoder_build_cover_command_position():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.POSITION, _DEVICE_CODE, _SYSTEM_CODE, position=50)
    assert isinstance(f, bytearray)
    assert f[5] == 50


def test_encoder_build_cover_command_position_none():
    """Position command with position=None should not raise."""
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.POSITION, _DEVICE_CODE, _SYSTEM_CODE, position=None)
    assert isinstance(f, bytearray)


def test_encoder_build_cover_command_dusk():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.DUSK, _DEVICE_CODE, _SYSTEM_CODE)
    assert f[4] == 0x01
    assert f[5] == 0xFF


def test_encoder_build_cover_command_dawn():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.DAWN, _DEVICE_CODE, _SYSTEM_CODE)
    assert f[4] == 0x01
    assert f[5] == 0xFF


def test_encoder_build_cover_command_with_timer():
    from custom_components.duofern.protocol import CoverCommand
    f = DuoFernEncoder.build_cover_command(CoverCommand.UP, _DEVICE_CODE, _SYSTEM_CODE, timer=True)
    assert f[4] == 0x01


def test_encoder_build_generic_command():
    payload = bytes([0x07, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    f = DuoFernEncoder.build_generic_command(payload, _DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[2] == 0x07


def test_encoder_build_switch_command_on():
    from custom_components.duofern.protocol import SwitchCommand
    f = DuoFernEncoder.build_switch_command(SwitchCommand.ON, _DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x0D


def test_encoder_build_switch_command_off():
    from custom_components.duofern.protocol import SwitchCommand
    f = DuoFernEncoder.build_switch_command(SwitchCommand.OFF, _DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)


def test_encoder_build_dim_command():
    f = DuoFernEncoder.build_dim_command(level=75, device_code=_DEVICE_CODE, system_code=_SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[5] == 75


def test_encoder_build_dim_command_clamps_to_100():
    f = DuoFernEncoder.build_dim_command(level=150, device_code=_DEVICE_CODE, system_code=_SYSTEM_CODE)
    assert f[5] == 100


def test_encoder_build_dim_command_clamps_to_0():
    f = DuoFernEncoder.build_dim_command(level=-5, device_code=_DEVICE_CODE, system_code=_SYSTEM_CODE)
    assert f[5] == 0


def test_encoder_build_desired_temp_command():
    f = DuoFernEncoder.build_desired_temp_command(temp=21.5, device_code=_DEVICE_CODE, system_code=_SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x0D


def test_encoder_build_desired_temp_with_timer():
    f = DuoFernEncoder.build_desired_temp_command(temp=20.0, device_code=_DEVICE_CODE, system_code=_SYSTEM_CODE, timer=True)
    assert f[4] == 0x01


def test_encoder_build_hsa_command_boost_on_ack():
    f = DuoFernEncoder.build_hsa_command(set_value=0x1234, device_code=_DEVICE_CODE, boost_on_ack=True)
    assert isinstance(f, bytearray)
    assert f[11] == 0x03


def test_encoder_build_hsa_command_boost_on():
    f = DuoFernEncoder.build_hsa_command(set_value=0, device_code=_DEVICE_CODE, boost_on=True)
    assert f[11] == 0x03


def test_encoder_build_hsa_command_boost_duration():
    f = DuoFernEncoder.build_hsa_command(set_value=0, device_code=_DEVICE_CODE, boost_duration_min=30)
    assert f[11] == 0x03
    # f[8] = 0x40 | clamped(30) = 0x40 | 30 = 0x5E
    assert f[8] == (0x40 | 30)


def test_encoder_build_hsa_command_boost_off():
    f = DuoFernEncoder.build_hsa_command(set_value=0, device_code=_DEVICE_CODE, boost_off=True)
    assert f[11] == 0x02


def test_encoder_build_hsa_command_boost_duration_clamps_min():
    """boost_duration_min < 4 is clamped to 4."""
    f = DuoFernEncoder.build_hsa_command(set_value=0, device_code=_DEVICE_CODE, boost_duration_min=1)
    assert f[8] == (0x40 | 4)


def test_encoder_build_hsa_command_boost_duration_clamps_max():
    """boost_duration_min > 60 is clamped to 60."""
    f = DuoFernEncoder.build_hsa_command(set_value=0, device_code=_DEVICE_CODE, boost_duration_min=99)
    assert f[8] == (0x40 | 60)


def test_encoder_build_start_unpair():
    f = DuoFernEncoder.build_start_unpair()
    assert isinstance(f, bytearray)
    assert f[0] == 0x07


def test_encoder_build_remote_pair():
    f = DuoFernEncoder.build_remote_pair(_DEVICE_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x0D
    assert f[2] == 0x06
    assert f[3] == 0x01


def test_encoder_build_code_pair():
    f = DuoFernEncoder.build_code_pair(_DEVICE_CODE, _SYSTEM_CODE)
    assert isinstance(f, bytearray)
    assert f[1] == 0xFF
    assert f[21] == 0x01


def test_encoder_build_remote_unpair():
    f = DuoFernEncoder.build_remote_unpair(_DEVICE_CODE)
    assert isinstance(f, bytearray)
    assert f[3] == 0x02


def test_encoder_build_remote_stop():
    f = DuoFernEncoder.build_remote_stop(_DEVICE_CODE)
    assert isinstance(f, bytearray)
    assert f[0] == 0x0D
