"""One bounded, advisory repair decision through the existing single agent.

The assessment is pinned to a completed candidate/job. The model selects an
allowlisted review strategy; it cannot supply code, paths, patches or approval.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from packages.studio.transfer_agent import MappingCandidate, TransferAgent

FEATURE = "cinetwin.repair_review"
MOTION = "review_motion_mapping"
MATERIAL = "review_source_albedo"
MAX_REPORT_BYTES = 8 * 1024 * 1024


def _snapshot(path: Path) -> tuple[dict[str, Any], str]:
    if path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Repair evidence exceeds size limit.")
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("Repair evidence must be a JSON object.")
    return data, hashlib.sha256(raw).hexdigest()


def _write_new(path: Path, data: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, allow_nan=False)
        handle.write("\n")


def eligible(assessment, plan, setup):
    """Select fixed review strategies only for measured, source-bound gaps."""
    bindings = plan.get("bindings", {})
    scoped = setup.get("source_albedo_actor_candidates", {})
    actors = {row["name"] for row in setup.get("actors", [])
              if row.get("kind") in {"entity.character", "entity.prop"}
              and not row.get("source_primitive")}
    issues = assessment.get("issues", [])
    motion = []
    material = []
    for index, issue in enumerate(issues):
        error = issue.get("error_cm")
        tolerance = issue.get("tolerance_cm")
        if (issue.get("category") == "CED_ANIMATION_TRANSFORM_FIDELITY"
                and issue.get("status") == "MEASURED_MISMATCH"
                and issue.get("source") in bindings
                and issue.get("domain") in {"actor_world", "skeletal_root_world"}
                and type(error) in (int, float) and math.isfinite(error)
                and type(tolerance) in (int, float) and math.isfinite(tolerance)
                and error > tolerance > 0):
            motion.append(index)
        elif (issue.get("category") == "VISUAL_NATIVE_READBACK"
              and issue.get("status") == "NATIVE_GAP"
              and issue.get("code") == "RENDER_MATERIALS_MISSING_OR_ENGINE_DEFAULT"
              and isinstance(scoped, dict)
              and any(scoped.get(name) for name in actors)):
            material.append(index)
    result = {}
    if motion:
        result[MOTION] = motion
    if material:
        result[MATERIAL] = material
    return result


def propose(folder: Path, job_id: str, agent: TransferAgent, *, verify_candidate):
    """One immutable decision per completed job; no native mutations or queue."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid repair job identity.")
    active, _ = _snapshot(folder / "active-job.json")
    if active.get("job_id") != job_id:
        raise ValueError("Repair must refer to the active completed job.")
    job_path = folder / "jobs" / (job_id + ".json")
    job, job_hash = _snapshot(job_path)
    if (job.get("job_id") != job_id or not job.get("ai_authorization")
            or job.get("repair_feedback_ready") is not True
            or job.get("status") not in {
                "GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED",
                "GENERATED_DIAGNOSTIC_INCOMPLETE",
            }):
        raise ValueError("Completed AI transfer feedback is required.")
    candidate_id = job.get("candidate_id")
    if not isinstance(candidate_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", candidate_id):
        raise ValueError("Invalid repair candidate identity.")
    root = (folder / "candidates").resolve()
    candidate = root / candidate_id
    if candidate.resolve().parent != root or Path(job["candidate_dir"]).resolve() != candidate.resolve():
        raise ValueError("Repair candidate path differs from the active job.")
    session = verify_candidate(candidate)
    mapping, _ = _snapshot(Path(session["target"]["mapping_path"])) if "mapping_path" in session["target"] else ({}, "")
    if "studio_repair_lineage" in mapping:
        raise ValueError("Repair lineage budget exhausted.")
    _, session_hash = _snapshot(candidate / "session.json")
    plan, plan_hash = _snapshot(candidate / "transfer-plan.json")
    setup, setup_hash = _snapshot(candidate / "automatic-setup.json")
    if (not session.get("ai_analysis")
            or session["artifact_sha256"]["transfer-plan.json"] != plan_hash
            or session["target"]["sequence_asset_path"] != job["sequence_path"]):
        raise ValueError("Repair candidate evidence differs from prepared transfer.")
    report_path = candidate / ("closed-loop-evaluation-" + job_id + ".json")
    report, report_hash = _snapshot(report_path)
    binding = {"job_id": job_id, "candidate_id": candidate_id,
               "sequence_path": job["sequence_path"], "session_sha256": session_hash,
               "transfer_plan_sha256": plan_hash}
    if (Path(job["closed_loop_report_file"]).resolve() != report_path.resolve()
            or report_hash != job.get("closed_loop_report_sha256")
            or report.get("kind") != "cutsceneai.studio.closed_loop_evaluation"
            or report.get("feedback_binding") != binding
            or report.get("repair_iterations_executed") != 0):
        raise ValueError("Repair feedback identity or hash mismatch.")
    # The setup is reverified by the host before inference and again after it.
    # A claim is consumed even on provider failure: no unbounded retry loop.
    claim = candidate / ("ai-repair-claim-" + job_id + ".json")
    output = candidate / ("ai-repair-proposal-" + job_id + ".json")
    if claim.exists() or output.exists():
        raise ValueError("Repair decision budget already consumed for this job.")
    choices = eligible(report, plan, setup)
    _write_new(claim, {**binding, "feedback_sha256": report_hash,
                       "setup_sha256": setup_hash, "decision_budget": 1})
    descriptions = {
        MOTION: "Review measured source/target world motion mismatch and existing animation/transform mappings.",
        MATERIAL: "Review source-backed actor-scoped albedo candidates for observed fallback material slots.",
    }
    candidates = tuple(MappingCandidate(key, FEATURE, descriptions[key]) for key in choices)
    decision = agent.select_mapping(FEATURE, candidates)
    if (verify_candidate(candidate) != session
            or _snapshot(job_path)[1] != job_hash
            or _snapshot(folder / "active-job.json")[0].get("job_id") != job_id
            or _snapshot(candidate / "session.json")[1] != session_hash
            or _snapshot(candidate / "transfer-plan.json")[1] != plan_hash
            or _snapshot(candidate / "automatic-setup.json")[1] != setup_hash
            or _snapshot(report_path)[1] != report_hash):
        raise ValueError("Repair evidence changed during decision; no proposal published.")
    selected = decision.mapping_id if decision.status == "proposed" else None
    if selected is not None and selected not in choices:
        raise ValueError("Repair selection outside eligible strategies.")
    result = {
        "kind": "cutsceneai.studio.ai_repair_proposal", "schema_version": "0.1.0",
        "feedback_binding": binding, "feedback_sha256": report_hash,
        "setup_sha256": setup_hash, "eligible_strategies": list(choices),
        "selected_strategy": selected, "issue_indices": choices.get(selected, []),
        "decision_status": decision.status, "decision_budget": 1,
        "execution_authorized": False, "automatic_repair_executed": False,
        "fresh_candidate_required": True, "fidelity_verified": False,
    }
    _write_new(output, result)
    return result
