"""Read-only native destination inspection for an AI automatic-setup candidate.

This is a prerequisite for a future approval, never an approval itself.
No assets, actors, levels, sequences or candidate files are created here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import studio_ai_verifier
from studio_ai_execution_auth import FRESH_LEVEL, fresh_map_path_available

ROOT = Path(__file__).resolve().parents[2]


def _snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def _same_project(first: str, second: str) -> bool:
    return os.path.normcase(str(Path(first).resolve())) == os.path.normcase(
        str(Path(second).resolve())
    )


def preflight_new_level(api, *, expected_project, expected_level, observed_level):
    """Confirm a fresh map is safe to create, without changing the editor."""
    if expected_level != FRESH_LEVEL or not observed_level or observed_level == expected_level:
        raise ValueError("Refusing noncanonical or already loaded automatic level path.")
    if not fresh_map_path_available({'target_project': expected_project, 'level_path': expected_level}):
        raise ValueError("Target map or related content already exists on disk.")
    if api.EditorAssetLibrary.does_asset_exist(expected_level):
        raise ValueError("Target level already exists; no overwrite.")
    try:
        world = api.get_editor_subsystem(api.UnrealEditorSubsystem).get_editor_world()
        saving = getattr(api, 'EditorLoadingAndSavingUtils', None)
        dirty_maps = getattr(saving, 'get_dirty_map_packages', None)
        if world is None or str(world.get_path_name()).split('.')[0] != observed_level:
            raise ValueError('Loaded world changed during fresh-map inspection.')
        if callable(dirty_maps):
            dirty = bool(list(dirty_maps()))
        else:
            dirty = world.get_outermost().is_dirty()
            if not isinstance(dirty, bool):
                raise TypeError('Unknown world dirty state.')
    except Exception as exc:
        raise RuntimeError("Cannot confirm current Unreal map is saved.") from exc
    if dirty:
        raise ValueError("Current Unreal map contains unsaved changes; save it first.")
    subsystem_type = getattr(api, 'LevelEditorSubsystem', None)
    editor_level = api.get_editor_subsystem(subsystem_type) if subsystem_type else None
    creator = getattr(editor_level, 'new_level', None)
    if not callable(creator):
        creator = getattr(getattr(api, 'EditorLevelLibrary', None), 'new_level', None)
    if not callable(creator) or not callable(getattr(api.EditorAssetLibrary, 'make_directory', None)):
        raise TypeError("Unreal level creation API unavailable; save an empty map manually.")
    return {'current_world_clean': True, 'target_map_absent': True,
            'level_creation_api_available': True}


def inspect_candidate(
    candidate: str | Path, *, expected_project: str, expected_level: str,
    unreal_api: Any, create_level: bool = False,
) -> dict[str, Any]:
    """Replay evidence, then inspect an existing or proposed staging level.

    Actual map creation and imported asset readback remain separate stages.
    Caller must run on the editor thread. No model calls or mutations.
    """
    folder = Path(candidate).resolve()
    session_path = folder / "session.json"
    setup_path = folder / "automatic-setup.json"
    session, session_hash = _snapshot(session_path)
    setup, setup_hash = _snapshot(setup_path)
    target = session["target"]
    project = target.get("project_path")
    if not project or not _same_project(project, expected_project):
        raise ValueError("AI candidate is not bound to the expected Unreal project.")
    if not expected_level.startswith("/Game/"):
        raise ValueError("Expected a selected Unreal staging level.")

    proof = studio_ai_verifier.verify_candidate(folder, require_setup=True)
    if proof["session_id"] != session["session_id"]:
        raise ValueError("Candidate session changed during AI replay.")
    if _snapshot(session_path)[1] != session_hash or _snapshot(setup_path)[1] != setup_hash:
        raise ValueError("Candidate session or automatic setup changed during AI replay.")

    import studio_auto_scene as scene

    if Path(str(getattr(scene, "__file__", ""))).resolve() != (
        ROOT / "integrations" / "unreal" / "studio_auto_scene.py"
    ):
        raise RuntimeError("Unreal automatic scene adapter is from another checkout.")
    api = unreal_api
    observed_project = scene._project(api)
    observed_level = scene._level(api)
    if not _same_project(observed_project, expected_project):
        raise ValueError("Wrong Unreal staging project is loaded.")
    if not create_level and observed_level != expected_level:
        raise ValueError("Open the selected staging level before inspection.")

    for name in ("AssetImportTask", "AssetToolsHelpers", "FbxImportUI", "FBXImportType",
                 "EditorActorSubsystem", "EditorAssetLibrary"):
        if not hasattr(api, name):
            raise RuntimeError("Required Unreal setup API unavailable: " + name)
    registry = api.EditorAssetLibrary
    new_level = (preflight_new_level(api, expected_project=expected_project,
                                    expected_level=expected_level, observed_level=observed_level)
                 if create_level else None)
    if not callable(getattr(registry, "does_directory_exist", None)):
        raise TypeError("Unreal namespace inspection API unavailable.")
    if registry.does_directory_exist(setup["target_folder"]):
        raise ValueError("Automatic setup target namespace already exists.")
    sequence = target["sequence_asset_path"]
    if registry.does_asset_exist(sequence):
        raise ValueError("Level Sequence path already occupied.")
    imports = [row["target_asset_path"] for row in setup["imports"]]
    if len(imports) != len(set(imports)):
        raise ValueError("Duplicate target import paths.")
    if imports and not callable(getattr(api.AssetToolsHelpers, "get_asset_tools", None)):
        raise RuntimeError("Unreal asset importer unavailable.")
    for asset in imports:
        if registry.does_asset_exist(asset):
            raise ValueError("Existing target import asset: " + asset)
    labels = [row["label"] for row in setup["actors"]]
    if len(labels) != len(set(labels)):
        raise ValueError("Duplicate planned actor labels.")
    actors = api.get_editor_subsystem(api.EditorActorSubsystem)
    existing = {str(actor.get_actor_label()) for actor in actors.get_all_level_actors()}
    # Old-world actors do not carry over; the scene adapter checks the new map again.
    if not create_level:
        for label in labels:
            if label in existing:
                raise ValueError("Existing actor label: " + label)
    for row in setup["actors"]:
        kind = row["kind"]
        required = None
        if kind == "entity.light":
            required = row.get("target_light_class")
            if required not in {"DirectionalLight", "PointLight", "SpotLight"}:
                raise ValueError("Light lacks a supported source-identified native class.")
        elif kind == "entity.camera":
            required = "CineCameraActor"
        elif kind == "entity.prop" and not row.get("mesh_path"):
            required = "Actor"
        if required and not hasattr(api, required):
            raise RuntimeError("Required Unreal actor class unavailable: " + required)
    primitives = scene.preflight_primitive_meshes(setup, api)
    if (_snapshot(session_path)[1] != session_hash
            or _snapshot(setup_path)[1] != setup_hash
            or scene._project(api) != observed_project
            or scene._level(api) != observed_level):
        raise ValueError("Candidate or destination changed during native inspection.")
    if create_level:
        preflight_new_level(api, expected_project=expected_project,
                            expected_level=expected_level, observed_level=observed_level)
    return {
        **({'create_level': True, 'expected_level': expected_level,
            'new_level_preflight': new_level} if create_level else {}),
        "kind": "cutsceneai.studio.ai_native_preflight",
        "status": "AI_NATIVE_SETUP_PREFLIGHT_PASSED",
        "session_id": proof["session_id"],
        "session_sha256": session_hash,
        "automatic_setup_sha256": setup_hash,
        "artifact_sha256": proof["artifact_sha256"],
        "observed_project": observed_project,
        "observed_level": observed_level,
        "sequence_path": sequence,
        "planned_actor_count": len(labels),
        "planned_import_count": len(imports),
        "verified_native_mesh_paths": sorted(primitives),
        "native_import_readback_pending": True,
        "execution_authorized": False,
        "engine_generation_executed": False,
        "behavioral_fidelity_established": False,
    }
