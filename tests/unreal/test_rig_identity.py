"""Exact native rig binding checks without launching an editor."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/unreal"))
import rig_identity


class Asset:
    def __init__(self, kind, path, skeleton=None):
        self.kind, self.path, self.skeleton = kind, path, skeleton

    def get_class(self):
        return SimpleNamespace(get_name=lambda: self.kind)

    def get_path_name(self):
        return self.path

    def get_editor_property(self, name):
        assert name == "skeleton"
        return self.skeleton


def fixture():
    skeleton = Asset("Skeleton", "/Game/Skeleton.Skeleton")
    mesh = Asset("SkeletalMesh", "/Game/Mesh.Mesh", skeleton)
    animation = Asset("AnimSequence", "/Game/Walk.Walk", skeleton)
    component = SimpleNamespace(get_skeletal_mesh_asset=lambda: mesh)
    actor = SimpleNamespace(get_components_by_class=lambda cls: [component])
    api = SimpleNamespace(SkeletalMeshComponent=object())
    return actor, mesh, animation, api


def test_exact_rig_identity_is_observed():
    actor, mesh, animation, api = fixture()
    assert rig_identity.verify_mesh(actor, mesh, api)["mesh_path"] == mesh.path
    assert rig_identity.verify_animation(actor, animation, api)["skeleton_path"] == mesh.skeleton.path
    assert rig_identity.observe(actor, mesh, [animation], api)["status"] == "PASS"


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_components_are_rejected(count):
    actor, mesh, animation, api = fixture()
    actor.get_components_by_class = lambda cls: [object()] * count
    with pytest.raises(rig_identity.RigIdentityError, match="exactly one"):
        rig_identity.verify_animation(actor, animation, api)
    assert rig_identity.observe(actor, mesh, [animation], api)["status"] == "INCOMPLETE"


def test_distinct_animation_skeleton_requires_explicit_retargeting():
    actor, mesh, animation, api = fixture()
    animation.skeleton = Asset("Skeleton", "/Game/Other.Other")
    with pytest.raises(rig_identity.RigIdentityError, match="retargeting"):
        rig_identity.verify_animation(actor, animation, api)
    assert rig_identity.observe(actor, mesh, [animation], api)["status"] == "FAIL"


def test_wrong_mesh_with_same_skeleton_is_not_a_match():
    actor, mesh, animation, api = fixture()
    other = Asset("SkeletalMesh", "/Game/Other.Other", mesh.skeleton)
    actor.get_components_by_class = lambda cls: [
        SimpleNamespace(get_skeletal_mesh_asset=lambda: other)]
    with pytest.raises(rig_identity.RigIdentityError, match="wrong skeletal mesh"):
        rig_identity.verify_mesh(actor, mesh, api)
    assert rig_identity.observe(actor, mesh, [animation], api)["status"] == "FAIL"


def test_missing_skeleton_is_not_a_successful_compatibility_check():
    actor, mesh, animation, api = fixture()
    animation.skeleton = None
    with pytest.raises(rig_identity.RigIdentityError):
        rig_identity.verify_animation(actor, animation, api)
    assert rig_identity.observe(actor, mesh, [animation], api)["status"] == "INCOMPLETE"


@pytest.mark.parametrize("method", ["get_skinned_asset", "skeletal_mesh_asset"])
def test_native_mesh_api_fallbacks(method):
    actor, mesh, _animation, api = fixture()
    component = SimpleNamespace()
    if method == "get_skinned_asset":
        component.get_skinned_asset = lambda: mesh
    else:
        component.get_editor_property = lambda name: mesh
    actor.get_components_by_class = lambda cls: [component]
    assert rig_identity.actor_mesh(actor, api) is mesh
