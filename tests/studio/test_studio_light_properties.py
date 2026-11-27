"""Static light setup and observation using software-only native test doubles."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import studio_light_properties as lights


class Component:
    def __init__(self):
        self.properties = {}

    def set_editor_property(self, name, value):
        self.properties[name] = value

    def get_editor_property(self, name):
        return self.properties[name]


class Actor:
    def __init__(self):
        self.component = Component()

    def get_components_by_class(self, cls):
        return [self.component]


def native_api():
    return SimpleNamespace(
        PointLight=Actor, SpotLight=Actor, DirectionalLight=Actor,
        LightComponentBase=Component, Color=lambda **kwargs: SimpleNamespace(**kwargs),
    )


def source():
    return {"intensity": 2.5, "color": {"r": 1.0, "g": 0.5, "b": 0.0},
            "shadows_enabled": False, "range": 12.5,
            "spot_angle_degrees": 60.0, "inner_spot_angle_degrees": 20.0}


@pytest.mark.parametrize("kind", ["Directional", "Point", "Spot"])
def test_static_light_converts_only_applicable_properties(kind):
    fields = lights.plan(source(), kind)
    assert fields["intensity"] == 2.5
    assert fields["light_color"] == [255, 128, 0]
    assert fields["cast_shadows"] is False
    if kind == "Directional":
        assert "attenuation_radius" not in fields
    else:
        assert fields["attenuation_radius"] == 1250
    if kind == "Spot":
        assert fields["inner_cone_angle"] == 10
        assert fields["outer_cone_angle"] == 30
    else:
        assert "outer_cone_angle" not in fields


@pytest.mark.parametrize("update", [
    {"intensity": -1}, {"intensity": float("nan")}, {"shadows_enabled": "false"},
    {"range": 0}, {"spot_angle_degrees": 180}, {"inner_spot_angle_degrees": 80},
    {"color": {"r": 1.5, "g": 0, "b": 0}}, {"color": {"r": 0, "g": 0}},
])
def test_invalid_static_light_properties_refuse_guessing(update):
    with pytest.raises((ValueError, TypeError)):
        lights.plan({**source(), **update}, "Spot")


def test_missing_fields_do_not_generate_default_light_properties():
    assert lights.plan({}, "Point") == {}


def test_native_light_setup_round_trip_is_independent():
    actor = Actor()
    row = {"target_light_class": "SpotLight", "light_setup": lights.plan(source(), "Spot")}
    api = native_api()
    lights.preflight(row, api)
    assert actor.component.properties == {}
    result = lights.apply(actor, row, api)
    assert result["status"] == "PASS"
    assert result["observed"] == row["light_setup"]
    actor.component.properties["attenuation_radius"] = 20
    assert lights.observe(actor, row["light_setup"], api)["status"] == "FAIL"


def test_missing_native_property_does_not_count_as_zero():
    actor = Actor()
    assert lights.observe(actor, {"intensity": 0}, native_api())["status"] == "INCOMPLETE"


def test_missing_native_api_blocks_before_mutation():
    with pytest.raises(lights.LightPropertyError, match="API unavailable"):
        lights.preflight({"target_light_class": "PointLight", "light_setup": {"intensity": 2}}, object())


def test_failed_native_write_is_not_success():
    actor = Actor()
    actor.component.set_editor_property = lambda name, value: None
    with pytest.raises(lights.LightPropertyError, match="readback"):
        lights.apply(actor, {"target_light_class": "PointLight",
                            "light_setup": {"intensity": 2}}, native_api())


def test_animated_properties_are_not_misclassified_as_saved_base_state():
    row = {"label": "Light", "light_setup": lights.plan(source(), "Spot")}
    actions = [{"kind": "light_intensity", "actor_label": "Light"},
               {"kind": "property_bool", "actor_label": "Light", "target_property_name": "CastShadows"},
               {"kind": "property_float", "actor_label": "Other", "target_property_name": "AttenuationRadius"}]
    fields = lights.static_fields(row, actions)
    assert "intensity" not in fields and "cast_shadows" not in fields
    assert fields["attenuation_radius"] == 1250
