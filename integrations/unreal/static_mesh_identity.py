"""Read-only verification of source-bound static mesh assignments."""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class StaticMeshIdentityError(ValueError):
    pass


def preflight(manifest, api):
    """Check required reflected component type before importing or spawning."""
    if (any(row.get("mesh_path") for row in manifest["actors"])
            and getattr(api, "StaticMeshComponent", None) is None):
        raise StaticMeshIdentityError("StaticMeshComponent API unavailable.")


def _identity(asset):
    if asset is None:
        return None
    kind = str(asset.get_class().get_name())
    path = str(asset.get_path_name())
    if not path.startswith("/"):
        raise StaticMeshIdentityError("Native mesh path unavailable.")
    return {"class": kind, "object_path": path}


def observe(actor, expected_path, api):
    """Check actual component membership, asset class and package/object identity."""
    result = {"status": "INCOMPLETE", "expected_mesh_path": expected_path,
              "observed_mesh": None}
    try:
        cls = getattr(api, "StaticMeshComponent", None)
        if cls is None:
            return result
        components = list(actor.get_components_by_class(cls))
        result["component_count"] = len(components)
        if len(components) != 1:
            result["status"] = "FAIL"
            return result
        mesh = components[0].get_editor_property("static_mesh")
        identity = _identity(mesh)
        result["observed_mesh"] = identity
        if identity is None:
            result["status"] = "FAIL"
            return result
        path = identity["object_path"]
        # Imported paths are package paths; built-in primitive references are
        # full object paths and must not match another object in that package.
        observed = path if "." in expected_path else path.split(".", 1)[0]
        result["status"] = (
            "PASS" if identity["class"] == "StaticMesh" and observed == expected_path else "FAIL"
        )
    except Exception:
        LOGGER.debug("Native static mesh assignment unavailable", exc_info=True)
    return result


def verify(actor, expected_path, api):
    result = observe(actor, expected_path, api)
    if result["status"] != "PASS":
        raise StaticMeshIdentityError(
            "Spawned static mesh readback differs or is unavailable: " + expected_path
        )
    return result
