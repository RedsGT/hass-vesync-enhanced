"""Class to manage VeSync data updates."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from pyvesync import VeSync
from pyvesync.utils.errors import VeSyncError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import UPDATE_INTERVAL, UPDATE_INTERVAL_ENERGY

_LOGGER = logging.getLogger(__name__)

type VesyncConfigEntry = ConfigEntry[VeSyncDataCoordinator]


class VeSyncDataCoordinator(DataUpdateCoordinator[None]):
    """Class representing data coordinator for VeSync devices."""

    config_entry: VesyncConfigEntry
    update_time: datetime | None = None

    def __init__(
        self, hass: HomeAssistant, config_entry: VesyncConfigEntry, manager: VeSync
    ) -> None:
        """Initialize."""
        self.manager = manager

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="VeSyncDataCoordinator",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    def should_update_energy(self) -> bool:
        """Test if specified update interval has been exceeded."""
        if self.update_time is None:
            return True

        return datetime.now() - self.update_time >= timedelta(
            seconds=UPDATE_INTERVAL_ENERGY
        )

    # Dynamic polling: tighten the interval when an air fryer is actively cooking
    # so the live temperature/time-remaining sensors stay current. Relax to the
    # default when nothing is happening.
    _ACTIVE_INTERVAL = timedelta(seconds=10)
    _IDLE_INTERVAL = timedelta(seconds=UPDATE_INTERVAL)
    _ACTIVE_COOK_STATES = ("cooking", "preheating", "heating", "ready")

    def _adjust_interval(self) -> None:
        """Pick fast vs idle interval based on current air-fryer state."""
        active = any(
            getattr(getattr(d, "state", None), "cook_status", None) in self._ACTIVE_COOK_STATES
            for d in self.manager.devices.air_fryers
        )
        target = self._ACTIVE_INTERVAL if active else self._IDLE_INTERVAL
        if self.update_interval != target:
            self.update_interval = target
            # Reschedule the next refresh so the change takes effect now, not after
            # the in-flight wait completes at the old interval.
            try:
                self._schedule_refresh()
            except Exception:  # noqa: BLE001 — defensive; HA private API
                pass

    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint."""
        try:
            await self.manager.update_all_devices()

            if self.should_update_energy():
                self.update_time = datetime.now()
                for outlet in self.manager.devices.outlets:
                    await outlet.update_energy()
        except VeSyncError as err:
            raise UpdateFailed(f"The service is unavailable: {err}") from err
        finally:
            try:
                from . import _wfon_pending
                for af in self.manager.devices.air_fryers:
                    _wfon_pending.update_tracking(af)
            except Exception:
                pass
            self._adjust_interval()
