"""Read-only replay of an AI-assisted candidate in the intended Python runtime.

No engine API, model inference, job submission or candidate mutations.
This verifies saved evidence, not approval or native fidelity.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SYNC_PATH = ROOT / "integrations" / "unreal" / "studio_planner_sync.py"


def verify_candidate(
    candidate: str | Path, *, require_setup: bool = False,
) -> dict[str, Any]:
    folder = Path(candidate).resolve()
    # Explicit path also works when Python is launched with -I, outside the
    # repository, or embedded in the Unreal Editor.
    editor_dir = str(SYNC_PATH.parent)
    while editor_dir in sys.path:
        sys.path.remove(editor_dir)
    sys.path.insert(0, editor_dir)
    cached = sys.modules.get("studio_planner_sync")
    if cached is not None and Path(
        str(getattr(cached, "__file__", ""))
    ).resolve() != SYNC_PATH:
        raise RuntimeError("Shadowed Studio planner sync; restart this interpreter.")
    sync = importlib.import_module("studio_planner_sync")
    if Path(str(getattr(sync, "__file__", ""))).resolve() != SYNC_PATH:
        raise RuntimeError("Studio planner sync loaded from another checkout.")
    importlib.reload(sync)
    origins = sync.synchronize()
    origins.update(sync.synchronize_ai())

    import prepared_transfer

    session = prepared_transfer.verify(folder)
    if not session.get("ai_analysis"):
        raise ValueError("Expected an AI-assisted prepared candidate.")
    handoff = json.loads((folder / "ai-handoff.json").read_text(encoding="utf-8-sig"))
    proposed = [row for row in handoff["tracks"] if row["ai_status"] == "proposed"]
    if any(row["proposal_attributed"] is not True for row in proposed):
        raise ValueError("An AI proposal is not attributed to the verified plan.")

    setup_path = folder / "automatic-setup.json"
    setup_summary = None
    if require_setup or setup_path.exists():
        import studio_auto_assets

        setup = studio_auto_assets.verify(
            setup_path, session["source"]["csir_path"],
            session["target"]["mapping_path"], folder / "transfer-plan.json",
        )
        if setup["ready"] is not True:
            raise ValueError("Automatic setup has unresolved blockers: " +
                             "; ".join(setup["blockers"]))
        setup_summary = {
            "verified": True,
            "planned_actors": len(setup["actors"]),
            "planned_imports": len(setup["imports"]),
            "native_cube_references": sum(
                row.get("source_primitive") == "unity_builtin_cube"
                for row in setup["actors"]
            ),
        }
    return {
        "status": "AI_EVIDENCE_REPLAY_VERIFIED",
        "session_id": session["session_id"],
        "source_sha256": session["source"]["sha256"],
        "analysis_sha256": session["ai_analysis"]["sha256"],
        "artifact_sha256": session["artifact_sha256"],
        "proposed_mappings": len(proposed),
        "attributed_proposals": sum(row["proposal_attributed"] is True for row in proposed),
        "decision_counts": handoff["analysis_decision_counts"],
        "backend_actions": handoff["backend_actions"],
        "automatic_setup": setup_summary,
        "canonical_modules": sorted(origins),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "execution_authorized": False,
        "engine_generation_executed": False,
        "behavioral_fidelity_established": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--require-setup", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify_candidate(args.candidate, require_setup=args.require_setup)
    except Exception as exc:
        print(json.dumps({
            "status": "AI_EVIDENCE_REPLAY_BLOCKED",
            "reason": str(exc),
            "execution_authorized": False,
            "engine_generation_executed": False,
        }, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
