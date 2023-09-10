"""Support for JLR InControl Sensors."""
import logging

from homeassistant.components.sensor import SensorDeviceClass

# from homeassistant.const import STATE_OFF, UNIT_PERCENTAGE
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfPressure, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import icon
from homeassistant.util import dt, unit_conversion

from .const import (
    DATA_ATTRS_CAR_INFO,
    DATA_ATTRS_CLIMATE,
    DATA_ATTRS_SERVICE_INFO,
    DATA_ATTRS_SERVICE_STATUS,
    DATA_ATTRS_TYRE_PRESSURE,
    DATA_ATTRS_TYRE_STATUS,
    DATA_ATTRS_WINDOW_STATUS,
    DOMAIN,
    FUEL_TYPE_BATTERY,
    FUEL_TYPE_HYBRID,
    FUEL_TYPE_ICE,
    JLR_CHARGE_METHOD_TO_HA,
    JLR_CHARGE_STATUS_TO_HA,
    JLR_DATA,
    SERVICE_STATUS_OK,
)
from .entity import JLREntity
from .util import to_local_datetime

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    """Setup sensor entities"""
    component = hass.data[DOMAIN]
    coordinator = component[config_entry.entry_id][JLR_DATA]

    devices = []
    _LOGGER.debug("Loading Sensors")

    for vehicle in coordinator.vehicles:
        _LOGGER.debug(
            "Setting Up Sensors for - %s",
            coordinator.vehicles[vehicle].attributes.get("nickname"),
        )

        devices.append(JLRVehicleSensor(coordinator, vehicle))
        devices.append(JLRVehicleWindowSensor(coordinator, vehicle))
        devices.append(JLRVehicleAlarmSensor(coordinator, vehicle))
        devices.append(JLRVehicleTyreSensor(coordinator, vehicle))
        devices.append(JLRVehicleServiceSensor(coordinator, vehicle))
        devices.append(JLRVehicleRangeSensor(coordinator, vehicle))
        devices.append(JLRVehicleStatusSensor(coordinator, vehicle))
        devices.append(JLRVehicleClimateSensor(coordinator, vehicle))
        devices.append(JLRVehicleAllDataSensor(coordinator, vehicle))

        # If EV/PHEV show Battery Sensor
        if coordinator.vehicles[vehicle].engine_type in [
            FUEL_TYPE_BATTERY,
            FUEL_TYPE_HYBRID,
        ]:
            devices.append(JLREVBatterySensor(coordinator, vehicle))

        # Show last trip sensor is privacy mode off and data exists
        if coordinator.vehicles[vehicle].last_trip:
            devices.append(JLRVehicleLastTripSensor(coordinator, vehicle))
        else:
            _LOGGER.debug(
                "Last Trip sensor not loaded for %s",
                (
                    "%s due to privacy mode or no data",
                    coordinator.vehicles[vehicle].attributes.get("nickname"),
                ),
            )

    # data.entities.extend(devices)
    async_add_entities(devices, True)


class JLRVehicleAllDataSensor(JLREntity):
    """All info sensor"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "all info")
        self._icon = "mdi:cloud"

    @property
    def state(self):
        if self.vehicle.last_updated:
            last_contacted = to_local_datetime(self.vehicle.last_updated)
            return dt.get_age(last_contacted) + " ago"
        return "Unknown"

    @property
    def extra_state_attributes(self):
        attrs = {}

        # Vehicle Attributes
        attributes = self.vehicle.attributes.copy()

        # Remove Capabilities
        if attributes.get("capabilities"):
            del attributes["capabilities"]

        # Remove Services
        if attributes.get("availableServices"):
            del attributes["availableServices"]

        attrs["attributes"] = dict(sorted(attributes.items()))

        # Vehicle Status
        status = {}
        for key, value in self.vehicle.status.copy().items():
            key = key[0].lower() + key.title().replace("_", "")[1:]
            status[key] = value
        attrs["core status"] = dict(sorted(status.items()))

        if self.vehicle.engine_type in [FUEL_TYPE_BATTERY, FUEL_TYPE_HYBRID]:
            status = {}
            for key, value in self.vehicle.status_ev.copy().items():
                key = key[0].lower() + key.title().replace("_", "")[1:]
                status[key] = value
            attrs["ev status"] = dict(sorted(status.items()))

        # Vehicle Position
        attrs["position"] = dict(sorted(self.vehicle.position.items()))

        return attrs


class JLRVehicleSensor(JLREntity):
    """Vehicle info sensor"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "info")
        self._icon = "mdi:car-info"

    @property
    def state(self):
        return self.vehicle.attributes.get("registrationNumber")

    @property
    def extra_state_attributes(self):
        attributes = self.vehicle.attributes
        attrs = {}
        attrs["Engine Type"] = self.vehicle.engine_type

        for key, value in DATA_ATTRS_CAR_INFO.items():
            if attributes.get(value):
                attrs[key.title()] = attributes.get(value)

        attrs["Odometer"] = (
            int(int(self.vehicle.status.get("ODOMETER_METER")) / 1000)
            if self.coordinator.user.user_preferences.distance
            == UnitOfLength.KILOMETERS
            else int(self.vehicle.status.get("ODOMETER_MILES"))
        )

        if self.vehicle.status.get("lastUpdatedTime"):
            last_contacted = to_local_datetime(
                self.vehicle.status.get("lastUpdatedTime")
            )
            attrs["Last Contacted"] = last_contacted
            attrs["Last Contacted Age"] = dt.get_age(last_contacted) + " ago"
        return attrs


class JLRVehicleTyreSensor(JLREntity):
    """Tyre status sensor"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "tyres")
        self._icon = "mdi:car-tire-alert"

    @property
    def state(self):
        # Convert to list of values from dict
        if all(
            [
                self.vehicle.status.get(value) == "NORMAL"
                for key, value in DATA_ATTRS_TYRE_STATUS.items()
            ]
        ):
            return "Ok"
        else:
            return "Warning"

    @property
    def extra_state_attributes(self):
        status = self.vehicle.status
        attrs = {}

        # Statuses
        for key, value in DATA_ATTRS_TYRE_STATUS.items():
            if status.get(value):
                attrs[key.title() + " Status"] = status.get(value).title()

        # Pressures
        for key, value in DATA_ATTRS_TYRE_PRESSURE.items():
            if status.get(value):
                tyre_pressure = int(status.get(value))

                # Some vehicles send in kPa*10, others in kPa. Ensure in kPa
                if tyre_pressure > 1000:
                    tyre_pressure = tyre_pressure / 10

                # Convert to local units - metric = bar, imperial = psi
                units = self.coordinator.user.user_preferences.pressure
                attrs[f"{key.title()} Pressure ({units})"] = round(
                    unit_conversion.PressureConverter.convert(
                        tyre_pressure, UnitOfPressure.KPA, units
                    ),
                    1,
                )

        return attrs


class JLRVehicleWindowSensor(JLREntity):
    """Window status entity"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "windows")
        self._icon = "mdi:car-door"

    @property
    def state(self):
        if all(
            [
                self.vehicle.status.get(v) in ["CLOSED", "FALSE", "UNUSED"]
                for k, v in DATA_ATTRS_WINDOW_STATUS.items()
            ]
        ):
            return "Closed"
        else:
            return "Open"

    @property
    def extra_state_attributes(self):
        status = self.vehicle.status
        attrs = {}
        for key, value in DATA_ATTRS_WINDOW_STATUS.items():
            # Add sunroof status if applicable
            if key == "sunroof":
                if self.vehicle.attributes.get("roofType") == "SUNROOF":
                    attrs[key.title()] = (
                        "Open"
                        if self.vehicle.status.get("IS_SUNROOF_OPEN") == "TRUE"
                        else "Closed"
                    )
            else:
                attrs[key.title() + " Position"] = status.get(value).title()

        return attrs


class JLRVehicleAlarmSensor(JLREntity):
    """Alarm info entity"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "alarm")
        self._icon = "mdi:security"

    @property
    def state(self):
        status = self.vehicle.status.get("THEFT_ALARM_STATUS")
        if status:
            status = status.replace("ALARM_", "")
            return status.replace("_", "").title()
        else:
            return "Not Supported"


class JLRVehicleServiceSensor(JLREntity):
    """Service status entity"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "service info")
        self._units = self.coordinator.user.user_preferences.distance
        self._icon = "mdi:wrench"

    @property
    def state(self):
        if all(
            [
                self.vehicle.status.get(value) in SERVICE_STATUS_OK
                or self.vehicle.status.get(value) is None
                for key, value in DATA_ATTRS_SERVICE_STATUS.items()
            ]
        ):
            return "Ok"
        else:
            return "Warning"

    @property
    def extra_state_attributes(self):
        status = self.vehicle.status
        attrs = {}
        for key, value in DATA_ATTRS_SERVICE_STATUS.items():
            if status.get(value):
                attrs[key.title()] = status.get(value).replace("_", " ").title()

        # Add metric sensors
        # TODO: Remove fixed string
        for key, value in DATA_ATTRS_SERVICE_INFO.items():
            if status.get(value):
                if key == "exhaust fluid fill":
                    attrs[key.title()] = int(
                        unit_conversion.DistanceConverter.convert(
                            int(status.get(value).title()),
                            UnitOfVolume.LITERS,
                            self._units,
                        )
                    )
                else:
                    attrs[key.title()] = int(
                        unit_conversion.DistanceConverter.convert(
                            int(status.get(value).title()),
                            UnitOfLength.KILOMETERS,
                            self._units,
                        )
                    )
        return attrs


class JLRVehicleRangeSensor(JLREntity):
    """Fuel/Battery range entity"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "range")
        self._units = self.coordinator.user.user_preferences.distance
        self._icon = (
            "mdi:speedometer"
            if self.vehicle.fuel == FUEL_TYPE_BATTERY
            else "mdi:gas-station"
        )

    @property
    def state(self):
        # Has battery
        if self.vehicle.engine_type == FUEL_TYPE_BATTERY:
            return (
                self.vehicle.status_ev.get("EV_RANGE_ON_BATTERY_KM", "0")
                if self._units == UnitOfLength.KILOMETERS
                else self.vehicle.status_ev.get("EV_RANGE_ON_BATTERY_MILES", "0")
            )
        if self.vehicle.engine_type == FUEL_TYPE_HYBRID:
            return (
                self.vehicle.status_ev.get("EV_PHEV_RANGE_COMBINED_KM", "0")
                if self._units == UnitOfLength.KILOMETERS
                else self.vehicle.status_ev.get("EV_PHEV_RANGE_COMBINED_MILES", "0")
            )
        # Fuel only
        return round(
            unit_conversion.DistanceConverter.convert(
                int(self.vehicle.status.get("DISTANCE_TO_EMPTY_FUEL")),
                UnitOfLength.KILOMETERS,
                self._units,
            )
        )

    @property
    def unit_of_measurement(self):
        return self._units

    @property
    def extra_state_attributes(self):
        attrs = {}
        attrs["Fuel Type"] = self.vehicle.fuel

        if self.vehicle.engine_type in [FUEL_TYPE_ICE, FUEL_TYPE_HYBRID]:
            attrs["Fuel Level"] = (
                self.vehicle.status.get("FUEL_LEVEL_PERC", "0") + PERCENTAGE
            )

        if self.vehicle.engine_type in [FUEL_TYPE_BATTERY, FUEL_TYPE_HYBRID]:
            attrs["Battery Level"] = (
                self.vehicle.status_ev.get("EV_STATE_OF_CHARGE", "0") + PERCENTAGE
            )
        # If hybrid
        if self.vehicle.engine_type == FUEL_TYPE_HYBRID:
            attrs["Fuel Range"] = round(
                unit_conversion.DistanceConverter.convert(
                    int(self.vehicle.status.get("DISTANCE_TO_EMPTY_FUEL")),
                    UnitOfLength.KILOMETERS,
                    self._units,
                )
            )

            attrs["Battery Range"] = (
                self.vehicle.status_ev.get("EV_RANGE_ON_BATTERY_KM", "0")
                if self._units == UnitOfLength.KILOMETERS
                else self.vehicle.status_ev.get("EV_RANGE_ON_BATTERY_MILES", "0")
            )

        return attrs


class JLREVBatterySensor(JLREntity):
    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "battery")
        self._units = self.coordinator.user.user_preferences.distance
        self._charging_state = False

    @property
    def state(self):
        return self.vehicle.status_ev.get("EV_STATE_OF_CHARGE", 0)

    @property
    def device_class(self):
        """Return the class of the sensor."""
        return SensorDeviceClass.BATTERY

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity."""
        return "%"

    @property
    def icon(self):
        return icon.icon_for_battery_level(
            int(self.vehicle.status_ev.get("EV_STATE_OF_CHARGE", 0)),
            self._charging_state,
        )

    @property
    def extra_state_attributes(self):
        attrs = {}
        status = self.vehicle.status_ev

        # Charging status
        self._charging_state = (
            True
            if status.get("EV_CHARGING_STATUS")
            in ["CHARGING", "WAITINGTOCHARGE", "INITIALIZATION"]
            else False
        )
        attrs["Charging"] = self._charging_state

        # Max SOC Values Set
        if (
            status.get("EV_ONE_OFF_MAX_SOC_CHARGE_SETTING_CHOICE")
            and status.get("EV_ONE_OFF_MAX_SOC_CHARGE_SETTING_CHOICE") != "CLEAR"
        ):
            attrs["Max SOC"] = status.get("EV_ONE_OFF_MAX_SOC_CHARGE_SETTING_CHOICE")
        elif (
            status.get("EV_PERMANENT_MAX_SOC_CHARGE_SETTING_CHOICE")
            and status.get("EV_PERMANENT_MAX_SOC_CHARGE_SETTING_CHOICE") != "CLEAR"
        ):
            attrs["Max SOC"] = status.get("EV_PERMANENT_MAX_SOC_CHARGE_SETTING_CHOICE")

        attrs["Charging State"] = JLR_CHARGE_STATUS_TO_HA.get(
            status.get("EV_CHARGING_STATUS"),
            status.get("EV_CHARGING_STATUS", "Unknown").title(),
        )

        attrs["Charging Method"] = JLR_CHARGE_METHOD_TO_HA.get(
            status.get("EV_CHARGING_METHOD"),
            status.get("EV_CHARGING_METHOD", "Unknown").title(),
        )

        attrs["Minutes to Full Charge"] = status.get(
            "EV_MINUTES_TO_FULLY_CHARGED", "Unknown"
        )

        attrs[f"Charging Rate ({self._units.lower()}/h)"] = status.get(
            f"EV_CHARGING_RATE_{self._units}_PER_HOUR", "Unknown"
        )

        attrs["Charging Rate (%/h)"] = status.get(
            "EV_CHARGING_RATE_SOC_PER_HOUR", "Unknown"
        )

        # Last Charge Amount
        attrs["Last Charge Energy (kWh)"] = round(
            int(status.get("EV_ENERGY_CONSUMED_LAST_CHARGE_KWH", 0)) / 10, 1
        )

        return attrs


class JLRVehicleLastTripSensor(JLREntity):
    """Last trip info sensor"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "last trip")
        self._units = self.coordinator.user.user_preferences.distance
        self._icon = "mdi:map"

    @property
    def state(self):
        if self.vehicle.last_trip and self.vehicle.last_trip.get("tripDetails"):
            return round(
                unit_conversion.DistanceConverter.convert(
                    int(
                        self.vehicle.last_trip.get("tripDetails", "{}").get("distance")
                    ),
                    UnitOfLength.METERS,
                    self._units,
                )
            )
        else:
            return 0

    @property
    def unit_of_measurement(self):
        return self._units

    @property
    def extra_state_attributes(self):
        attrs = {}
        if self.vehicle.last_trip:
            trip = self.vehicle.last_trip.get("tripDetails")

            if trip:
                attrs["start"] = to_local_datetime(trip.get("startTime"))
                attrs["origin_latitude"] = trip.get("startPosition").get("latitude")
                attrs["origin_longitude"] = trip.get("startPosition").get("longitude")
                attrs["origin"] = trip.get("startPosition").get("address")

                attrs["end"] = to_local_datetime(trip.get("endTime"))
                attrs["destination_latitude"] = trip.get("endPosition").get("latitude")
                attrs["destination_longitude"] = trip.get("endPosition").get(
                    "longitude"
                )
                attrs["destination"] = trip.get("endPosition").get("address")
                if trip.get("totalEcoScore"):
                    attrs["eco_score"] = trip.get("totalEcoScore").get("score", 0)
                attrs["average_speed"] = round(
                    unit_conversion.DistanceConverter.convert(
                        int(trip.get("averageSpeed", 0)),
                        UnitOfLength.KILOMETERS,
                        self._units,
                    )
                )

                if self.vehicle.fuel == FUEL_TYPE_BATTERY:
                    avg_consumption = trip.get("averageEnergyConsumption", 0)
                    if not avg_consumption:
                        avg_consumption = 0
                    attrs["average_consumption"] = round(avg_consumption, 1)
                else:
                    if self._units == UnitOfLength.KILOMETERS:
                        attrs["average_consumption"] = round(
                            trip.get("averageFuelConsumption", 0), 1
                        )
                    else:
                        attrs["average_consumption"] = round(
                            int(trip.get("averageFuelConsumption", 0)) * 2.35215,
                            1,
                        )

            return attrs


class JLRVehicleStatusSensor(JLREntity):
    """Status sensor"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "status")
        self._icon = "mdi:car"

    @property
    def state(self):
        status = self.vehicle.status.get("VEHICLE_STATE_TYPE")

        if status:
            return status.replace("_", " ").title()
        else:
            return "Unknown"


class JLRVehicleClimateSensor(JLREntity):
    """Climate status sensor"""

    def __init__(self, coordinator, vin) -> None:
        super().__init__(coordinator, vin, "climate")
        self._icon = "mdi:air-conditioner"

    @property
    def state(self):
        return str(
            self.vehicle.status.get("CLIMATE_STATUS_OPERATING_STATUS", "Unknown")
        ).title()

    @property
    def extra_state_attributes(self):
        attrs = {}

        for name, attr in DATA_ATTRS_CLIMATE.items():
            if value := self.vehicle.status.get(attr):
                attrs[name] = value
        return attrs
