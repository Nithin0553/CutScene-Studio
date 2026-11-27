"""Read-only native skeletal asset identity checks; no retargeting or pose claims."""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class RigIdentityError(ValueError):
    pass


def asset_identity(asset, expected_class):
    if asset is None:
        raise RigIdentityError("Missing native " + expected_class)
    actual = str(asset.get_class().get_name())
    path = str(asset.get_path_name())
    if actual != expected_class or not path.startswith("/"):
        raise RigIdentityError("Invalid native " + expected_class + " identity.")
    return path


def skeleton_identity(asset):
    return asset_identity(asset.get_editor_property("skeleton"), "Skeleton")


def actor_mesh(actor, api):
    """Require exactly one skeletal component; never guess between body meshes."""
    cls = getattr(api, "SkeletalMeshComponent", None)
    if cls is None:
        raise RigIdentityError("SkeletalMeshComponent API unavailable.")
    components = list(actor.get_components_by_class(cls))
    if len(components) != 1:
        raise RigIdentityError("Expected exactly one destination skeletal mesh component.")
    component = components[0]
    for name in ("get_skeletal_mesh_asset", "get_skinned_asset"):
        getter = getattr(component, name, None)
        if callable(getter):
            mesh = getter()
            asset_identity(mesh, "SkeletalMesh")
            return mesh
    mesh = component.get_editor_property("skeletal_mesh_asset")
    asset_identity(mesh, "SkeletalMesh")
    return mesh


def verify_mesh(actor, expected_mesh, api):
    observed = actor_mesh(actor, api)
    expected_path = asset_identity(expected_mesh, "SkeletalMesh")
    observed_path = asset_identity(observed, "SkeletalMesh")
    if expected_path != observed_path:
        raise RigIdentityError("Spawned actor uses the wrong skeletal mesh.")
    expected_skeleton = skeleton_identity(expected_mesh)
    if skeleton_identity(observed) != expected_skeleton:
        raise RigIdentityError("Spawned actor uses the wrong mesh skeleton.")
    return {"mesh_path": observed_path, "skeleton_path": expected_skeleton}


def verify_animation(actor, animation, api):
    """Strict exact-skeleton policy; compatible but distinct rigs need an adapter."""
    mesh = actor_mesh(actor, api)
    mesh_path = asset_identity(mesh, "SkeletalMesh")
    animation_path = asset_identity(animation, "AnimSequence")
    mesh_skeleton = skeleton_identity(mesh)
    animation_skeleton = skeleton_identity(animation)
    if mesh_skeleton != animation_skeleton:
        raise RigIdentityError("Animation and destination actor use different skeletons; explicit retargeting required.")
    return {"mesh_path": mesh_path, "animation_path": animation_path,
            "skeleton_path": mesh_skeleton}


def observe(actor, mesh, animations, api):
    """Compare independent native identities; failed reads are incomplete."""
    try:
        expected_mesh = asset_identity(mesh, "SkeletalMesh")
        observed_mesh = actor_mesh(actor, api)
        observed_path = asset_identity(observed_mesh, "SkeletalMesh")
        mesh_skeleton = skeleton_identity(mesh)
        actor_skeleton = skeleton_identity(observed_mesh)
    except Exception:
        LOGGER.debug("Native skeletal mesh identity unavailable", exc_info=True)
        return {"status": "INCOMPLETE", "animations": []}
    result = {"status": "PASS", "expected_mesh_path": expected_mesh,
              "observed_mesh_path": observed_path, "expected_skeleton_path": mesh_skeleton,
              "observed_skeleton_path": actor_skeleton, "animations": []}
    if observed_path != expected_mesh or actor_skeleton != mesh_skeleton:
        result["status"] = "FAIL"
    for animation in animations:
        try:
            path = asset_identity(animation, "AnimSequence")
            skeleton = skeleton_identity(animation)
            status = "PASS" if skeleton == mesh_skeleton else "FAIL"
            row = {"status": status, "animation_path": path, "skeleton_path": skeleton}
        except Exception:
            LOGGER.debug("Native animation skeleton identity unavailable", exc_info=True)
            row = {"status": "INCOMPLETE"}
        result["animations"].append(row)
        if row["status"] == "FAIL":
            result["status"] = "FAIL"
        elif row["status"] == "INCOMPLETE" and result["status"] == "PASS":
            result["status"] = "INCOMPLETE"
    return result
