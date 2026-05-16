"""Pending cook settings for WFON air fryers, keyed by device cid.

The numbers/select entities just write into this dict; the cooking switch
reads from it when starting a cook. This way changing temp/time/preset
doesn't kick off a cook on its own.
"""

_DEFAULTS = {"temp_f": 350, "time_min": 15, "preset": "Air Fry",
             "cook_end_time": None, "cook_start_time": None, "last_status": None,
             "last_cook_temp_c": None}
_PENDING: dict[str, dict] = {}


def get(device, key: str):
    """Return the pending value, falling back to the device default."""
    return _PENDING.setdefault(device.cid, dict(_DEFAULTS))[key]


def set(device, key: str, value) -> None:
    """Stage a pending value. Does not communicate with the device."""
    _PENDING.setdefault(device.cid, dict(_DEFAULTS))[key] = value


import math as _math
import time as _time

_ACTIVE_COOK_STATES = ("cooking", "preheating", "heating", "ready", "keeping")
_AMBIENT_C = 22.0
_SAFE_C = 43.0
_COOLING_K = 0.06


def update_tracking(device) -> None:
    """Run once per coordinator poll. Snapshots cook setpoint and end time."""
    status = getattr(getattr(device, "state", None), "cook_status", None)
    last_status = get(device, "last_status")
    set(device, "last_status", status)
    # cook_start_time: stamp on transition into an active cook state;
    # clear once the device returns fully to standby.
    if last_status not in _ACTIVE_COOK_STATES and status in _ACTIVE_COOK_STATES:
        set(device, "cook_start_time", _time.time())
    if status == "standby":
        set(device, "cook_start_time", None)
    if status in _ACTIVE_COOK_STATES:
        set(device, "cook_end_time", None)
        set_temp = getattr(device.state, "cook_set_temp", None)
        if set_temp is not None:
            set(device, "last_cook_temp_c", float(set_temp))
        return
    if last_status in _ACTIVE_COOK_STATES and status not in _ACTIVE_COOK_STATES:
        set(device, "cook_end_time", _time.time())


def cooldown_seconds_remaining(device) -> float | None:
    """Seconds until estimated safe-to-handle, or None if not in cooldown."""
    end_time = get(device, "cook_end_time")
    if end_time is None:
        return None
    initial_c = get(device, "last_cook_temp_c")
    if initial_c is None or initial_c <= _SAFE_C:
        return None
    cooldown_min = -_math.log(
        (_SAFE_C - _AMBIENT_C) / (initial_c - _AMBIENT_C)
    ) / _COOLING_K
    remaining = cooldown_min * 60 - (_time.time() - end_time)
    return max(0.0, remaining)
