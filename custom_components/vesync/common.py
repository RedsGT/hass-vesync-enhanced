"""Common utilities for VeSync Component."""

import logging
from typing import TypeGuard

from pyvesync.base_devices import VeSyncHumidifier
from pyvesync.base_devices.fan_base import VeSyncFanBase
from pyvesync.base_devices.fryer_base import VeSyncFryer
from pyvesync.base_devices.outlet_base import VeSyncOutlet
from pyvesync.base_devices.purifier_base import VeSyncPurifier
from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.const import ProductTypes
from pyvesync.devices.vesyncswitch import VeSyncWallSwitch

_LOGGER = logging.getLogger(__name__)


def rgetattr(obj: object, attr: str) -> object | str | None:
    """Return a string in the form word.1.2.3 and return the item as 3. Note that this last value could be in a dict as well."""
    _this_func = rgetattr
    sp = attr.split(".", 1)
    if len(sp) == 1:
        left, right = sp[0], ""
    else:
        left, right = sp

    if isinstance(obj, dict):
        obj = obj.get(left)
    elif hasattr(obj, left):
        obj = getattr(obj, left)
    else:
        return None

    if right:
        obj = _this_func(obj, right)

    return obj


def is_humidifier(device: VeSyncBaseDevice) -> TypeGuard[VeSyncHumidifier]:
    """Check if the device represents a humidifier."""

    return device.product_type == ProductTypes.HUMIDIFIER


def is_fan(device: VeSyncBaseDevice) -> TypeGuard[VeSyncFanBase]:
    """Check if the device represents a fan."""

    return device.product_type == ProductTypes.FAN


def is_outlet(device: VeSyncBaseDevice) -> TypeGuard[VeSyncOutlet]:
    """Check if the device represents an outlet."""

    return device.product_type == ProductTypes.OUTLET


def is_wall_switch(device: VeSyncBaseDevice) -> TypeGuard[VeSyncWallSwitch]:
    """Check if the device represents a wall switch, note this doessn't include dimming switches."""
    if device.product_type != ProductTypes.SWITCH:
        return False

    return getattr(device, "supports_dimmable", False) is False


def is_purifier(device: VeSyncBaseDevice) -> TypeGuard[VeSyncPurifier]:
    """Check if the device represents an air purifier."""

    return device.product_type == ProductTypes.PURIFIER


def is_air_fryer(device: VeSyncBaseDevice) -> TypeGuard[VeSyncFryer]:
    """Check if the device represents an air fryer."""

    return device.product_type == ProductTypes.AIR_FRYER


# -- Air-fryer cook helpers (TurboBlaze / Dual Blaze native interface) -----
from dataclasses import replace as _dc_replace
from pyvesync.const import AirFryerPresets as _AirFryerPresets

# Both display form ("Air Fry") and API form ("AirFry") accepted so we can
# round-trip between the select entity's option names and what the device
# state reports.
_FRYER_PRESET_BY_NAME = {
    "Air Fry":      _AirFryerPresets.air_fry,    "AirFry":       _AirFryerPresets.air_fry,
    "Broil":        _AirFryerPresets.broil,
    "Roast":        _AirFryerPresets.roast,
    "Bake":         _AirFryerPresets.bake,
    "Reheat":       _AirFryerPresets.reheat,
    "Steak":        _AirFryerPresets.steak,
    "Seafood":      _AirFryerPresets.seafood,
    "Veggies":      _AirFryerPresets.veggies,
    "French Fries": _AirFryerPresets.french_fries, "FrenchFries":  _AirFryerPresets.french_fries,
    "Frozen":       _AirFryerPresets.frozen,
    "Chicken":      _AirFryerPresets.chicken,
}


async def fryer_start_cook(device, set_temp_c: float, set_time_min: int,
                           preset: str = "Air Fry") -> bool:
    """Start a cook on a TurboBlaze-style air fryer.

    Looks up the preset recipe from pyvesync.const.AirFryerPresets, overrides
    target_temp (Fahrenheit, converted from the caller's Celsius) and
    cook_time (seconds, from the caller's minutes), and calls
    set_mode_from_recipe. Returns True on success.
    """
    template = _FRYER_PRESET_BY_NAME.get(preset, _AirFryerPresets.air_fry)
    target_temp_f = round(set_temp_c * 9 / 5 + 32)
    cook_time_sec = int(set_time_min * 60)
    recipe = _dc_replace(template, target_temp=target_temp_f, cook_time=cook_time_sec)
    return await device.set_mode_from_recipe(recipe)


async def fryer_end_cook(device) -> bool:
    """End the current cook on an air fryer."""
    return await device.end()


# pyvesync 3.4+ stores fryer state in the device's native API units
# (Fahrenheit + seconds for US TurboBlaze/Dual Blaze fryers). The
# integration's helpers and entity descriptions historically assumed
# normalized units. These helpers bridge the gap.

def device_temp_unit_name(device) -> str | None:
    """Return 'celsius' or 'fahrenheit' for the device's temp unit, or None."""
    unit = getattr(device, "temp_unit", None)
    if unit is None:
        return None
    name = getattr(unit, "name", None)
    if name is not None:
        return name.lower()
    return str(unit).lower()


def device_temp_as_f(device, value):
    """Convert a temperature value from the device's native unit to Fahrenheit."""
    if value is None:
        return None
    if device_temp_unit_name(device) == "celsius":
        return float(value) * 9 / 5 + 32
    return float(value)


def device_temp_as_c(device, value):
    """Convert a temperature value from the device's native unit to Celsius."""
    if value is None:
        return None
    if device_temp_unit_name(device) == "fahrenheit":
        return (float(value) - 32) * 5 / 9
    return float(value)


# Inverse of _FRYER_PRESET_BY_NAME for entities that need to map a
# device-reported cook_mode value back to the SELECT entity's option
# label. Only the camelCase mismatches need explicit entries;
# identical names (Broil, Roast, Bake, Reheat, Steak, Seafood, Veggies,
# Frozen, Chicken) pass through.
_COOK_MODE_TO_PRESET_NAME = {
    "AirFry":      "Air Fry",
    "FrenchFries": "French Fries",
}

# Set of pyvesync cook_mode values that map to a known display preset
# (built once from _FRYER_PRESET_BY_NAME so additions stay in sync).
_KNOWN_FRYER_COOK_MODES = {r.cook_mode for r in _FRYER_PRESET_BY_NAME.values()}


def fryer_display_preset(device):
    """Return the SELECT option label for the device's current cook_mode,
    or None if cook_mode is missing / does not map (e.g. 'normal', 'Custom').
    """
    cm = getattr(getattr(device, "state", None), "cook_mode", None)
    if not cm:
        return None
    if cm in _COOK_MODE_TO_PRESET_NAME:
        return _COOK_MODE_TO_PRESET_NAME[cm]
    if cm in _KNOWN_FRYER_COOK_MODES:
        return cm
    return None
