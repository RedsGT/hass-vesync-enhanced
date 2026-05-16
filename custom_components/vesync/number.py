"""Support for VeSync numeric entities."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging

from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.device_container import DeviceContainer

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .common import is_air_fryer, is_humidifier, fryer_start_cook, fryer_end_cook, device_temp_as_c, device_temp_as_f
from .const import VS_DEVICES, VS_DISCOVERY
from .coordinator import VesyncConfigEntry, VeSyncDataCoordinator
from .entity import VeSyncBaseEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


def _mist_levels(device: VeSyncBaseDevice) -> list[int]:
    """Check if the device supports mist level adjustment."""
    if is_humidifier(device):
        return device.mist_levels
    raise HomeAssistantError("Device does not support mist level adjustment.")


def _set_mist_level(device: VeSyncBaseDevice, value: float) -> Awaitable[bool]:
    """Set mist level on humidifier."""
    if is_humidifier(device):
        return device.set_mist_level(int(value))
    raise HomeAssistantError("Device does not support mist level adjustment.")



_DEFAULT_TEMP_C = 175.0
_DEFAULT_TIME_MIN = 15
_DEFAULT_PRESET = "Air Fry"


def _wfon_set_temp(device, value: float):
    time_min = getattr(device.state, "cook_set_time", None) or _DEFAULT_TIME_MIN
    preset   = getattr(device.state, "cook_mode", None) or _DEFAULT_PRESET
    return fryer_start_cook(device, float(value), int(time_min), preset)


def _wfon_set_time(device, value: float):
    temp_c = getattr(device.state, "cook_set_temp", None) or _DEFAULT_TEMP_C
    preset = getattr(device.state, "cook_mode", None) or _DEFAULT_PRESET
    return fryer_start_cook(device, float(temp_c), int(value), preset)


from . import _wfon_pending


_ACTIVE_COOK_STATES = ("cooking", "preheating", "heating", "ready")


def _is_cooking(device) -> bool:
    return getattr(device.state, "cook_status", None) in _ACTIVE_COOK_STATES


def _current_time_min(device) -> int:
    rem = getattr(device.state, "cook_last_time", None)
    return int(rem) // 60 if rem else int(_wfon_pending.get(device, "time_min"))


def _current_temp_c(device) -> float:
    c = getattr(device.state, "cook_set_temp", None)
    if c is not None:
        return float(c)
    return (_wfon_pending.get(device, "temp_f") - 32) * 5 / 9


def _current_preset(device) -> str:
    return getattr(device.state, "cook_mode", None) or _wfon_pending.get(device, "preset")


async def _wfon_stage_temp(device, value: float) -> bool:
    _wfon_pending.set(device, "temp_f", int(value))
    if not _is_cooking(device):
        return True
    return await fryer_start_cook(device, 
        (float(value) - 32) * 5 / 9,
        _current_time_min(device),
        _current_preset(device),
    )


async def _wfon_stage_time(device, value: float) -> bool:
    _wfon_pending.set(device, "time_min", int(value))
    if not _is_cooking(device):
        return True
    return await fryer_start_cook(device, 
        _current_temp_c(device),
        int(value),
        _current_preset(device),
    )


@dataclass(frozen=True, kw_only=True)
class VeSyncNumberEntityDescription(NumberEntityDescription):
    """Class to describe a Vesync number entity."""

    exists_fn: Callable[[VeSyncBaseDevice], bool] = lambda _: True
    value_fn: Callable[[VeSyncBaseDevice], float]
    native_min_value_fn: Callable[[VeSyncBaseDevice], float]
    native_max_value_fn: Callable[[VeSyncBaseDevice], float]
    set_value_fn: Callable[[VeSyncBaseDevice, float], Awaitable[bool]]


NUMBER_DESCRIPTIONS: list[VeSyncNumberEntityDescription] = [
    VeSyncNumberEntityDescription(
        key="mist_level",
        translation_key="mist_level",
        native_min_value_fn=lambda device: min(_mist_levels(device)),
        native_max_value_fn=lambda device: max(_mist_levels(device)),
        native_step=1,
        mode=NumberMode.SLIDER,
        exists_fn=is_humidifier,
        set_value_fn=_set_mist_level,
        value_fn=lambda device: device.state.mist_virtual_level,
    ),
    VeSyncNumberEntityDescription(
        key="cook_temp",
        translation_key="cook_temp",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        native_min_value_fn=lambda _: 175.0,
        native_max_value_fn=lambda _: 400.0,
        native_step=1,
        mode=NumberMode.BOX,
        exists_fn=lambda device: is_air_fryer(device) and hasattr(device, "set_mode_from_recipe"),
        value_fn=lambda device: (
            int(round(device_temp_as_f(device, device.state.cook_set_temp)))
            if getattr(device.state, "cook_set_temp", None) is not None
            else _wfon_pending.get(device, "temp_f")
        ),
        set_value_fn=_wfon_stage_temp,
    ),
    VeSyncNumberEntityDescription(
        key="cook_time",
        translation_key="cook_time",
        native_unit_of_measurement="min",
        native_min_value_fn=lambda _: 1.0,
        native_max_value_fn=lambda _: 60.0,
        native_step=1,
        mode=NumberMode.BOX,
        exists_fn=lambda device: is_air_fryer(device) and hasattr(device, "set_mode_from_recipe"),
        value_fn=lambda device: (int(device.state.cook_set_time // 60) if getattr(device.state, "cook_set_time", None) else _wfon_pending.get(device, "time_min")),
        set_value_fn=_wfon_stage_time,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VesyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities."""

    coordinator = config_entry.runtime_data

    @callback
    def discover(devices: list[VeSyncBaseDevice]) -> None:
        """Add new devices to platform."""
        _setup_entities(devices, async_add_entities, coordinator)

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, VS_DISCOVERY.format(VS_DEVICES), discover)
    )

    _setup_entities(
        config_entry.runtime_data.manager.devices, async_add_entities, coordinator
    )


@callback
def _setup_entities(
    devices: DeviceContainer | list[VeSyncBaseDevice],
    async_add_entities: AddConfigEntryEntitiesCallback,
    coordinator: VeSyncDataCoordinator,
) -> None:
    """Add number entities."""

    async_add_entities(
        VeSyncNumberEntity(dev, description, coordinator)
        for dev in devices
        for description in NUMBER_DESCRIPTIONS
        if description.exists_fn(dev)
    )


class VeSyncNumberEntity(VeSyncBaseEntity, NumberEntity):
    """A class to set numeric options on Vesync device."""

    entity_description: VeSyncNumberEntityDescription

    def __init__(
        self,
        device: VeSyncBaseDevice,
        description: VeSyncNumberEntityDescription,
        coordinator: VeSyncDataCoordinator,
    ) -> None:
        """Initialize the VeSync number device."""
        super().__init__(device, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}-{description.key}"

    @property
    def native_value(self) -> float:
        """Return the value reported by the number."""
        return self.entity_description.value_fn(self.device)

    @property
    def native_min_value(self) -> float:
        """Return the value reported by the number."""
        return self.entity_description.native_min_value_fn(self.device)

    @property
    def native_max_value(self) -> float:
        """Return the value reported by the number."""
        return self.entity_description.native_max_value_fn(self.device)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        if not await self.entity_description.set_value_fn(self.device, value):
            raise HomeAssistantError(self.device.last_response.message)
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()
