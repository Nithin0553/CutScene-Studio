"""Source-backed static light setup; numeric properties are not render parity."""
from __future__ import annotations

import logging
import math

LOGGER = logging.getLogger(__name__)


class LightPropertyError(ValueError):
    pass


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise LightPropertyError("Invalid finite Unity light property: " + name)
    return float(value)


def plan(light, source_type):
    """Convert only captured values; never synthesize missing source properties."""
    target = {}
    if "intensity" in light:
        value = _number(light["intensity"], "intensity")
        if value < 0:
            raise LightPropertyError("Negative light intensity.")
        target["intensity"] = value
    if "shadows_enabled" in light:
        value = light["shadows_enabled"]
        if type(value) is not bool:
            raise TypeError("Unity shadows_enabled must be Boolean.")
        target["cast_shadows"] = value
    if "color" in light:
        color = light["color"]
        if not isinstance(color, dict):
            raise TypeError("Unity light color must be a record.")
        rgb = [_number(color.get(channel), "color." + channel) for channel in ("r", "g", "b")]
        if any(not 0 <= value <= 1 for value in rgb):
            raise LightPropertyError("HDR or out-of-range light color needs a color-space adapter.")
        # Raw stored-channel approximation, not a linear/sRGB conversion.
        target["light_color"] = [round(value * 255) for value in rgb]
    if source_type in {"Point", "Spot"} and "range" in light:
        value = _number(light["range"], "range")
        if value <= 0 or not math.isfinite(value * 100):
            raise LightPropertyError("Local light range must be positive and representable.")
        target["attenuation_radius"] = value * 100
    if source_type == "Spot" and any(
        name in light for name in ("spot_angle_degrees", "inner_spot_angle_degrees")
    ):
        outer = _number(light.get("spot_angle_degrees"), "spot_angle_degrees") / 2
        inner = _number(light.get("inner_spot_angle_degrees"), "inner_spot_angle_degrees") / 2
        if not 0 <= inner <= outer <= 89 or outer <= 0:
            raise LightPropertyError("Spot cone angles exceed supported Unreal half-angle bounds.")
        # Inner first (zero), then outer, then authored inner; avoids clamping
        # against either the default inner or default outer angle.
        target["outer_cone_angle"] = outer
        target["inner_cone_angle"] = inner
    return target


def preflight(row, api):
    """Read-only reflection probe; actual property writes are checked after spawn."""
    fields = row.get("light_setup")
    if not fields:
        return
    actor_type = getattr(api, row["target_light_class"], None)
    component_type = getattr(api, "LightComponentBase", None)
    if not all(callable(method) for method in (
        getattr(actor_type, "get_components_by_class", None),
        getattr(component_type, "get_editor_property", None),
        getattr(component_type, "set_editor_property", None),
    )):
        raise LightPropertyError("Native light component property API unavailable.")
    if "light_color" in fields and not callable(getattr(api, "Color", None)):
        raise LightPropertyError("Native light Color type unavailable.")


def _component(actor, api):
    components = list(actor.get_components_by_class(api.LightComponentBase))
    if len(components) != 1:
        raise LightPropertyError("Expected exactly one native light component.")
    return components[0]


def _read(component, name):
    value = component.get_editor_property(name)
    if name == "light_color":
        channels = [getattr(value, channel) for channel in ("r", "g", "b")]
        if not all(type(channel) is int and 0 <= channel <= 255 for channel in channels):
            raise LightPropertyError("Invalid native light color readback.")
        return channels
    if name == "cast_shadows":
        if type(value) is not bool:
            raise TypeError("Native shadow flag is not Boolean.")
        return value
    return _number(value, name)


def _matches(expected, observed):
    if type(expected) is bool or isinstance(expected, list):
        return observed == expected
    return math.isclose(expected, observed, rel_tol=1e-6, abs_tol=1e-4)


def observe(actor, fields, api):
    """Independent component measurement; unavailable evidence is not a match."""
    try:
        component = _component(actor, api)
    except Exception:
        LOGGER.debug("Native light component unavailable", exc_info=True)
        return {"status": "INCOMPLETE", "expected": fields, "observed": {}}
    observed = {}
    for name in fields:
        try:
            observed[name] = _read(component, name)
        except Exception:
            LOGGER.debug("Native light property unavailable: %s", name, exc_info=True)
    mismatch = any(not _matches(fields[name], value) for name, value in observed.items())
    status = "FAIL" if mismatch else "PASS" if len(observed) == len(fields) else "INCOMPLETE"
    return {"status": status, "expected": fields, "observed": observed}


def apply(actor, row, api):
    fields = row["light_setup"]
    preflight(row, api)
    component = _component(actor, api)
    if "outer_cone_angle" in fields:
        component.set_editor_property("inner_cone_angle", 0.0)
    for name, value in fields.items():
        if name == "light_color":
            value = api.Color(r=value[0], g=value[1], b=value[2], a=255)
        component.set_editor_property(name, value)
    result = observe(actor, fields, api)
    if result["status"] != "PASS":
        raise LightPropertyError("Native light setup readback did not match source-derived properties.")
    return result


def static_fields(row, actions):
    """Do not compare initial properties against a potentially animated actor."""
    fields = dict(row.get("light_setup", {}))
    for action in actions:
        if action.get("actor_label") != row["label"]:
            continue
        if action.get("kind") == "light_intensity":
            fields.pop("intensity", None)
        elif action.get("kind") in {"property_float", "property_bool"}:
            target = str(action.get("target_property_name", "")).replace("_", "").lower()
            for name in tuple(fields):
                if name.replace("_", "").lower() == target:
                    fields.pop(name)
    return fields
