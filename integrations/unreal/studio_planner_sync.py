"""Pin and refresh the active Studio planner before Unreal source verification.

Unreal embeds a long-lived Python interpreter. Importing transfer_backend once
can leave an older module (25 actions) cached after a developer pulls changes
and prepares a new candidate (29 actions). This module synchronizes the *local
repository code* on disk, verifies canonical module origins and reloads the
dependency chain before any Unreal asset/actor creation. No project data or
saved candidate evidence is mutated.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from importlib.util import find_spec

ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    ("csir_plan", "integrations/unreal"),
    ("source_surface_gap", "packages/studio"),
    ("feature_dispatch", "packages/studio"),
    ("scalar_property_adapter", "packages/studio"),
    ("visual_activation", "packages/studio"),
    ("adaptive_components", "packages/studio"),
    ("transfer_backend", "packages/studio"),
    ("prepared_transfer", "packages/studio"),
    # The automatic asset manifest is created by the Studio host Python
    # process, then re-verified by Unreal's long-lived Python process.
    # A stale cached asset inspector changes its actor/import plan even when
    # the Unity source and immutable candidate are unchanged.
    ("studio_source_identity", "tools"),
    ("studio_source_materials", "tools"),
    ("studio_auto_assets", "tools"),
)


# Qualified imports are separate Python module instances from the bare planner.
# Replay needs these modules, but does not construct a LangGraph or contact Ollama.
AI_MODULES = (
    "ced_preflight",
    "feature_dispatch",
    "ollama_provider",
    "transfer_agent",
    "mapping_resources",
    "source_evidence",
)


class PlannerSyncError(RuntimeError):
    """A stale or shadowed editor planner cannot be trusted for transfer."""


def synchronize() -> dict[str, str]:
    """Refresh all local source/target planning modules, fail closed on shadowing.

    The module file paths are fixed repository code, never taken from a
    candidate plan or user-supplied path. Loading this pipeline is an explicit
    step before any actual engine mutation.
    """
    # transfer_backend and prepared_transfer also depend on these core
    # module roots. Preserve their known directory order and avoid importing
    # unrelated plugins from a different checkout.
    # sys.path.insert(0, ...) reverses this order. Keep the generic tools/
    # directory BELOW packages/studio; tools/transfer_backend.py is a
    # similarly named entrypoint, NOT the trusted Python planner module.
    for relative in (
        "tools", "packages/learning", "packages/cinetwin",
        "integrations/unreal", "packages/studio",
    ):
        path = str(ROOT / relative)
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    importlib.invalidate_caches()
    return {
        name: _refresh(name, ROOT / relative / (name + ".py"))
        for name, relative in MODULES
    }


def _refresh(name: str, expected: Path) -> str:
    expected = expected.resolve()
    existing: ModuleType | None = sys.modules.get(name)
    if existing is not None:
        actual_raw = getattr(existing, "__file__", None)
        if not actual_raw or Path(actual_raw).resolve() != expected:
            raise PlannerSyncError(
                "Unreal cached a shadowed " + name + " module. "
                "Restart Unreal Editor and load the canonical Studio companion."
            )
    # Check resolution BEFORE import/reload, not after executing foreign code.
    try:
        spec = find_spec(name)
        if spec is None or not spec.origin or Path(spec.origin).resolve() != expected:
            raise PlannerSyncError("Studio planner resolved outside the repository: " + name)
        module = importlib.reload(existing) if existing is not None \
            else importlib.import_module(name)
    except PlannerSyncError:
        raise
    except Exception as exc:
        raise PlannerSyncError(
            "Cannot refresh current Studio planner module " + name
            + "; restart Unreal with the updated repository: " + str(exc)
        ) from exc
    if Path(str(getattr(module, "__file__", ""))).resolve() != expected:
        raise PlannerSyncError("Studio planner imported from a non-repository path: " + name)
    return str(expected)


def _check_namespace(name: str, expected: Path) -> None:
    """Reject a foreign package or mixed namespace before importing children."""
    expected = expected.resolve()
    existing = sys.modules.get(name)
    if existing is None:
        spec = find_spec(name)
        locations = spec.submodule_search_locations if spec is not None else None
        origin = spec.origin if spec is not None else None
    else:
        locations = getattr(existing, "__path__", None)
        origin = getattr(existing, "__file__", None)
    if origin is not None or locations is None or {
        Path(location).resolve() for location in locations
    } != {expected}:
        raise PlannerSyncError("Noncanonical Studio namespace: " + name)
    module = importlib.import_module(name)
    if {Path(location).resolve() for location in module.__path__} != {expected}:
        raise PlannerSyncError("Noncanonical Studio namespace: " + name)


def synchronize_ai() -> dict[str, str]:
    """Refresh only the replay dependencies, independently of native execution."""
    root = str(ROOT.resolve())
    while root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    importlib.invalidate_caches()
    _check_namespace("packages", ROOT / "packages")
    _check_namespace("packages.studio", ROOT / "packages" / "studio")
    try:
        from jsonschema import Draft202012Validator
        if not callable(getattr(Draft202012Validator, "validate", None)):
            raise ImportError("Draft 2020-12 validator unavailable")
    except ImportError as exc:
        raise PlannerSyncError(
            "AI replay requires jsonschema (>=4.23,<5) in this Python interpreter. "
            "Install it into the intended interpreter before retrying verification."
        ) from exc
    return {
        "packages.studio." + name: _refresh(
            "packages.studio." + name, ROOT / "packages" / "studio" / (name + ".py")
        )
        for name in AI_MODULES
    }
