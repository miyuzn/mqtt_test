from __future__ import annotations

import json
from typing import Iterable, List, Tuple

MAX_ANALOG = 11
MAX_SELECT = 13
MAX_SENSORS = MAX_ANALOG * MAX_SELECT
VAL_MIN = 0
VAL_MAX = 255
MAX_BYTES = 512


class ConfigValidationError(ValueError):
    """Raised when incoming configuration is invalid."""


def _validate_pins(name: str, pins: Iterable[int], max_len: int) -> List[int]:
    pin_list = list(pins)
    if len(pin_list) == 0 or len(pin_list) > max_len:
        raise ConfigValidationError(f"{name} 数量必须在 1..{max_len} 之间")
    if any((not isinstance(x, int)) for x in pin_list):
        raise ConfigValidationError(f"{name} 只能包含整数")
    if any(x < VAL_MIN or x > VAL_MAX for x in pin_list):
        raise ConfigValidationError(f"{name} 取值需在 {VAL_MIN}..{VAL_MAX}")
    if len(set(pin_list)) != len(pin_list):
        raise ConfigValidationError(f"{name} 出现重复值")
    return pin_list


def build_payload(
    *,
    analog: Iterable[int],
    select: Iterable[int],
) -> Tuple[dict, str]:
    analog_pins = _validate_pins("analog", analog, MAX_ANALOG)
    select_pins = _validate_pins("select", select, MAX_SELECT)
    if len(analog_pins) * len(select_pins) > MAX_SENSORS:
        raise ConfigValidationError("analog × select 数量超过 11×13 限制")

    payload_obj = {
        "analog": analog_pins,
        "select": select_pins,
    }
    payload_str = json.dumps(payload_obj, separators=(",", ":"))
    payload_with_newline = payload_str + "\n"
    if len(payload_with_newline.encode("utf-8")) > MAX_BYTES:
        raise ConfigValidationError("JSON 总长度超过 512 字节限制")
    return payload_obj, payload_with_newline
    if len(analog) * len(select) > MAX_SENSORS:
        raise ConfigValidationError("readIO × selectIO 数量超过 11×13 限制")
    if not isinstance(sample_frequency, int):
        raise ConfigValidationError("sampleFrequency 必须是整数")
    if sample_frequency < sample_min or sample_frequency > sample_max:
        raise ConfigValidationError(f"sampleFrequency 需在 {sample_min}..{sample_max} Hz")

    payload_obj = {
        "dn": dn,
        "readIO": analog,
        "selectIO": select,
        "sampleFrequency": sample_frequency,
    }
    payload_str = json.dumps(payload_obj, separators=(",", ":"), ensure_ascii=False)
    if len(payload_str.encode("utf-8")) > MAX_BYTES:
        raise ConfigValidationError("JSON 总长度超过 512 字节限制")
    return payload_obj, payload_str


__all__ = [
    "ConfigValidationError",
    "build_payload",
]
