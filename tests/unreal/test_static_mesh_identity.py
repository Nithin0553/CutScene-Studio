"""Source-bound static mesh identity checks without launching Unreal."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/unreal"))
import static_mesh_identity as identity


@pytest.mark.parametrize("expected,observed,kind,status", [
    ("/Game/Tree", "/Game/Tree.Tree", "StaticMesh", "PASS"),
    ("/Game/Tree", "/Game/Rock.Rock", "StaticMesh", "FAIL"),
    ("/Game/Tree", "/Game/Tree.Tree", "SkeletalMesh", "FAIL"),
    ("/Engine/BasicShapes/Cube.Cube", "/Engine/BasicShapes/Cube.Cube", "StaticMesh", "PASS"),
    ("/Engine/BasicShapes/Cube.Cube", "/Engine/BasicShapes/Cube.Other", "StaticMesh", "FAIL"),
])
def test_native_mesh_identity(expected, observed, kind, status):
    mesh = SimpleNamespace(get_class=lambda: SimpleNamespace(get_name=lambda: kind),
                           get_path_name=lambda: observed)
    component = SimpleNamespace(get_editor_property=lambda name: mesh)
    actor = SimpleNamespace(get_components_by_class=lambda cls: [component])
    api = SimpleNamespace(StaticMeshComponent=object())
    assert identity.observe(actor, expected, api)["status"] == status


@pytest.mark.parametrize("count", [0, 2])
def test_missing_or_ambiguous_components_are_failed(count):
    actor = SimpleNamespace(get_components_by_class=lambda cls: [object()] * count)
    api = SimpleNamespace(StaticMeshComponent=object())
    assert identity.observe(actor, "/Game/Tree", api)["status"] == "FAIL"
    with pytest.raises(identity.StaticMeshIdentityError):
        identity.verify(actor, "/Game/Tree", api)


def test_missing_native_measurement_is_incomplete():
    api = SimpleNamespace(StaticMeshComponent=object())
    assert identity.observe(object(), "/Game/Tree", api)["status"] == "INCOMPLETE"


def test_missing_component_api_blocks_preflight():
    with pytest.raises(identity.StaticMeshIdentityError, match="API unavailable"):
        identity.preflight({"actors": [{"mesh_path": "/Game/Tree"}]}, object())
    identity.preflight({"actors": [{"kind": "entity.prop"}]}, object())
