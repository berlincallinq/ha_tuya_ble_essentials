"""The Tuya BLE integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
)
from homeassistant.components.climate.const import (
    PRESET_NONE,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo
from .tuya_ble import TuyaBLEDataPoint, TuyaBLEDataPointType, TuyaBLEDevice

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaBLEClimateMapping:
    """Mapping between a Tuya BLE device and a Home Assistant climate entity."""

    description: ClimateEntityDescription

    hvac_mode_dp_id: int = 0
    hvac_modes: list[str] | None = None

    hvac_switch_dp_id: int = 0
    hvac_switch_mode: HVACMode | None = None

    preset_mode_dp_ids: dict[str, int] | None = None

    # Enum based preset support.
    preset_mode_enum_dp_id: int = 0
    preset_mode_enum_values: list[str] | None = None

    temperature_unit: str = UnitOfTemperature.CELSIUS

    current_temperature_dp_id: int = 0
    current_temperature_coefficient: float = 1.0

    target_temperature_dp_id: int = 0
    target_temperature_coefficient: float = 1.0

    target_temperature_max: float = 30.0
    target_temperature_min: float = 5.0
    target_temperature_step: float = 1.0

    current_humidity_dp_id: int = 0
    current_humidity_coefficient: float = 1.0

    target_humidity_dp_id: int = 0
    target_humidity_coefficient: float = 1.0
    target_humidity_max: float = 100.0
    target_humidity_min: float = 0.0


@dataclass
class TuyaBLECategoryClimateMapping:
    """Climate mappings for a Tuya BLE category."""

    products: dict[str, list[TuyaBLEClimateMapping]] | None = None
    mapping: list[TuyaBLEClimateMapping] | None = None


mapping: dict[str, TuyaBLECategoryClimateMapping] = {
    # Existing supported TRVs.
    "wk": TuyaBLECategoryClimateMapping(
        products={
            **{
                key: [
                    TuyaBLEClimateMapping(
                        description=ClimateEntityDescription(
                            key="thermostatic_radiator_valve"
                        ),
                        hvac_switch_dp_id=101,
                        hvac_switch_mode=HVACMode.HEAT,
                        hvac_modes=[
                            HVACMode.OFF,
                            HVACMode.HEAT,
                        ],
                        preset_mode_dp_ids={
                            "away": 106,
                            PRESET_NONE: 106,
                        },
                        current_temperature_dp_id=102,
                        current_temperature_coefficient=10.0,
                        target_temperature_dp_id=103,
                        target_temperature_coefficient=10.0,
                        target_temperature_step=0.5,
                        target_temperature_min=5.0,
                        target_temperature_max=30.0,
                    )
                ]
                for key in [
                    "drlajpqc",
                    "nhj2j7su",
                ]
            },
        },
    ),

    # Essentials Radiator Thermostat Round Bluetooth
    #
    # Product:
    #   ftduq25v
    #
    # Category:
    #   wkf
    #
    # Tuya DPs:
    #   2  = mode
    #   8  = window_check
    #   13 = battery_percentage
    #   16 = temp_set
    #   24 = temp_current
    #   32 = holiday_temp_set
    #   40 = child_lock
    #
    # Mode enum:
    #   auto
    #   manual
    #   holiday
    #   holidayready
    #
    "wkf": TuyaBLECategoryClimateMapping(
        products={
            "ftduq25v": [
                TuyaBLEClimateMapping(
                    description=ClimateEntityDescription(
                        key="essentials_tv02"
                    ),

                    # The Essentials TV02 does not have a separate
                    # on/off DP. It is always represented as HEAT
                    # in Home Assistant.
                    hvac_modes=[
                        HVACMode.HEAT,
                    ],

                    # Tuya mode DP.
                    preset_mode_enum_dp_id=2,

                    # Exact enum order reported by Tuya.
                    preset_mode_enum_values=[
                        "auto",
                        "manual",
                        "holiday",
                        "holidayready",
                    ],

                    # Current temperature:
                    # 171 = 17.1 °C
                    current_temperature_dp_id=24,
                    current_temperature_coefficient=10.0,

                    # Target temperature:
                    # 170 = 17.0 °C
                    target_temperature_dp_id=16,
                    target_temperature_coefficient=10.0,
                    target_temperature_step=0.5,
                    target_temperature_min=5.0,
                    target_temperature_max=30.0,
                )
            ]
        },
    ),
}


def get_mapping_by_device(
    device: TuyaBLEDevice,
) -> list[TuyaBLEClimateMapping]:
    """Return climate mappings for a device."""

    category = mapping.get(device.category)

    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)

        if product_mapping is not None:
            return product_mapping

        if category.mapping is not None:
            return category.mapping

    return []


class TuyaBLEClimate(TuyaBLEEntity, ClimateEntity):
    """Representation of a Tuya BLE Climate device."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEClimateMapping,
    ) -> None:
        """Initialize the climate entity."""

        super().__init__(
            hass,
            coordinator,
            device,
            product,
            mapping.description,
        )

        self._mapping = mapping

        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_hvac_action = HVACAction.IDLE
        self._attr_preset_mode = PRESET_NONE

        if mapping.hvac_modes:
            self._attr_hvac_modes = mapping.hvac_modes

        if mapping.hvac_switch_dp_id and mapping.hvac_switch_mode:
            self._attr_hvac_modes = [
                HVACMode.OFF,
                mapping.hvac_switch_mode,
            ]

        if mapping.preset_mode_dp_ids:
            self._attr_supported_features |= (
                ClimateEntityFeature.PRESET_MODE
            )

            self._attr_preset_modes = list(
                mapping.preset_mode_dp_ids.keys()
            )

        if (
            mapping.preset_mode_enum_dp_id
            and mapping.preset_mode_enum_values
        ):
            self._attr_supported_features |= (
                ClimateEntityFeature.PRESET_MODE
            )

            self._attr_preset_modes = (
                mapping.preset_mode_enum_values
            )

        if mapping.target_temperature_dp_id:
            self._attr_supported_features |= (
                ClimateEntityFeature.TARGET_TEMPERATURE
            )

            self._attr_temperature_unit = (
                mapping.temperature_unit
            )

            self._attr_max_temp = (
                mapping.target_temperature_max
            )

            self._attr_min_temp = (
                mapping.target_temperature_min
            )

            self._attr_target_temperature_step = (
                mapping.target_temperature_step
            )

        if mapping.target_humidity_dp_id:
            self._attr_supported_features |= (
                ClimateEntityFeature.TARGET_HUMIDITY
            )

            self._attr_max_humidity = (
                mapping.target_humidity_max
            )

            self._attr_min_humidity = (
                mapping.target_humidity_min
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        # Current temperature.
        if self._mapping.current_temperature_dp_id:
            datapoint = self._device.datapoints[
                self._mapping.current_temperature_dp_id
            ]

            if datapoint and datapoint.value is not None:
                self._attr_current_temperature = (
                    datapoint.value
                    / self._mapping.current_temperature_coefficient
                )

        # Target temperature.
        if self._mapping.target_temperature_dp_id:
            datapoint = self._device.datapoints[
                self._mapping.target_temperature_dp_id
            ]

            if datapoint and datapoint.value is not None:
                self._attr_target_temperature = (
                    datapoint.value
                    / self._mapping.target_temperature_coefficient
                )

        # Humidity.
        if self._mapping.current_humidity_dp_id:
            datapoint = self._device.datapoints[
                self._mapping.current_humidity_dp_id
            ]

            if datapoint and datapoint.value is not None:
                self._attr_current_humidity = (
                    datapoint.value
                    / self._mapping.current_humidity_coefficient
                )

        if self._mapping.target_humidity_dp_id:
            datapoint = self._device.datapoints[
                self._mapping.target_humidity_dp_id
            ]

            if datapoint and datapoint.value is not None:
                self._attr_target_humidity = (
                    datapoint.value
                    / self._mapping.target_humidity_coefficient
                )

        # Normal HVAC switch handling for existing devices.
        if (
            self._mapping.hvac_switch_dp_id
            and self._mapping.hvac_switch_mode
        ):
            datapoint = self._device.datapoints[
                self._mapping.hvac_switch_dp_id
            ]

            if datapoint:
                self._attr_hvac_mode = (
                    self._mapping.hvac_switch_mode
                    if datapoint.value
                    else HVACMode.OFF
                )

        # Enum based preset/mode handling for the Essentials TV02.
        if (
            self._mapping.preset_mode_enum_dp_id
            and self._mapping.preset_mode_enum_values
        ):
            datapoint = self._device.datapoints[
                self._mapping.preset_mode_enum_dp_id
            ]

            if datapoint and datapoint.value is not None:
                try:
                    index = int(datapoint.value)

                    if (
                        0 <= index
                        < len(
                            self._mapping.preset_mode_enum_values
                        )
                    ):
                        self._attr_preset_mode = (
                            self._mapping.preset_mode_enum_values[
                                index
                            ]
                        )

                except (TypeError, ValueError):
                    _LOGGER.debug(
                        "Unable to decode TV02 mode value: %s",
                        datapoint.value,
                    )

        # Boolean preset handling for existing devices.
        elif self._mapping.preset_mode_dp_ids:
            current_preset_mode = PRESET_NONE

            for (
                preset_mode,
                dp_id,
            ) in self._mapping.preset_mode_dp_ids.items():
                datapoint = self._device.datapoints[dp_id]

                if datapoint and datapoint.value:
                    current_preset_mode = preset_mode
                    break

            self._attr_preset_mode = current_preset_mode

        # Determine heating state.
        try:
            if (
                self._attr_hvac_mode == HVACMode.OFF
                or (
                    self._attr_target_temperature
                    <= self._attr_current_temperature
                )
            ):
                self._attr_hvac_action = HVACAction.IDLE
            else:
                self._attr_hvac_action = HVACAction.HEATING

        except (AttributeError, TypeError):
            self._attr_hvac_action = HVACAction.IDLE

        self.async_write_ha_state()

    async def async_set_temperature(
        self,
        **kwargs,
    ) -> None:
        """Set a new target temperature."""

        if not self._mapping.target_temperature_dp_id:
            return

        temperature = kwargs.get("temperature")

        if temperature is None:
            return

        int_value = int(
            temperature
            * self._mapping.target_temperature_coefficient
        )

        datapoint = self._device.datapoints.get_or_create(
            self._mapping.target_temperature_dp_id,
            TuyaBLEDataPointType.DT_VALUE,
            int_value,
        )

        if datapoint:
            self._hass.create_task(
                datapoint.set_value(int_value)
            )

    async def async_set_humidity(
        self,
        humidity: int,
    ) -> None:
        """Set a new target humidity."""

        if not self._mapping.target_humidity_dp_id:
            return

        int_value = int(
            humidity
            * self._mapping.target_humidity_coefficient
        )

        datapoint = self._device.datapoints.get_or_create(
            self._mapping.target_humidity_dp_id,
            TuyaBLEDataPointType.DT_VALUE,
            int_value,
        )

        if datapoint:
            self._hass.create_task(
                datapoint.set_value(int_value)
            )

    async def async_set_hvac_mode(
        self,
        hvac_mode: HVACMode,
    ) -> None:
        """Set the HVAC mode."""

        if (
            self._mapping.hvac_switch_dp_id
            and self._mapping.hvac_switch_mode
        ):
            bool_value = (
                hvac_mode
                == self._mapping.hvac_switch_mode
            )

            datapoint = self._device.datapoints.get_or_create(
                self._mapping.hvac_switch_dp_id,
                TuyaBLEDataPointType.DT_BOOL,
                bool_value,
            )

            if datapoint:
                self._hass.create_task(
                    datapoint.set_value(bool_value)
                )

    async def async_set_preset_mode(
        self,
        preset_mode: str,
    ) -> None:
        """Set a Tuya preset/mode."""

        # Enum based preset handling.
        if (
            self._mapping.preset_mode_enum_dp_id
            and self._mapping.preset_mode_enum_values
        ):
            if (
                preset_mode
                not in self._mapping.preset_mode_enum_values
            ):
                return

            enum_index = (
                self._mapping.preset_mode_enum_values.index(
                    preset_mode
                )
            )

            datapoint = self._device.datapoints.get_or_create(
                self._mapping.preset_mode_enum_dp_id,
                TuyaBLEDataPointType.DT_ENUM,
                enum_index,
            )

            if datapoint:
                self._hass.create_task(
                    datapoint.set_value(enum_index)
                )

            return

        # Boolean preset handling for existing devices.
        if self._mapping.preset_mode_dp_ids:
            datapoint: TuyaBLEDataPoint | None = None
            bool_value = False

            keys = list(
                self._mapping.preset_mode_dp_ids.keys()
            )

            values = list(
                self._mapping.preset_mode_dp_ids.values()
            )

            if (
                values
                and all(
                    values[0] == element
                    for element in values
                )
                and keys
                and keys[0] == "away"
            ):
                bool_value = (
                    preset_mode == "away"
                )

                datapoint = (
                    self._device.datapoints.get_or_create(
                        values[0],
                        TuyaBLEDataPointType.DT_BOOL,
                        bool_value,
                    )
                )

            else:
                for (
                    dp_preset_mode,
                    dp_id,
                ) in self._mapping.preset_mode_dp_ids.items():
                    bool_value = (
                        dp_preset_mode == preset_mode
                    )

                    datapoint = (
                        self._device.datapoints.get_or_create(
                            dp_id,
                            TuyaBLEDataPointType.DT_BOOL,
                            bool_value,
                        )
                    )

            if datapoint:
                self._hass.create_task(
                    datapoint.set_value(bool_value)
                )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE climate entities."""

    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]

    mappings = get_mapping_by_device(
        data.device
    )

    entities = [
        TuyaBLEClimate(
            hass,
            data.coordinator,
            data.device,
            data.product,
            climate_mapping,
        )
        for climate_mapping in mappings
    ]

    async_add_entities(entities)
