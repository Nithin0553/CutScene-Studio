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

ROOT = Path(__file__).resolve().parents[2]


def _snapshot(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), hashlib.sha256(raw).hexdigest()


def _same_project(first: str, second: str) -> bool:
    return os.path.normcase(str(Path(first).resolve())) == os.path.normcase(
        str(Path(second).resolve())
    )


def inspect_candidate(
    candidate: str | Path, *, expected_project: str, expected_level: str,
    unreal_api: Any,
) -> dict[str, Any]:
    """Replay evidence, then inspect the already-loaded staging level.

    Fresh-map creation and imported asset readback remain separate stages.
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
    if observed_level != expected_level:
        raise ValueError("Open the selected staging level; new-map preflight is not enabled.")

    for name in ("AssetImportTask", "AssetToolsHelpers", "FbxImportUI", "FBXImportType",
                 "EditorActorSubsystem", "EditorAssetLibrary"):
        if not hasattr(api, name):
            raise RuntimeError("Required Unreal setup API unavailable: " + name)
    registry = api.EditorAssetLibrary
    if not callable(getattr(registry, "does_directory_exist", None)):
        raise RuntimeError("Unreal namespace inspection API unavailable.")
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
    return {
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
