"""Fresh, single-retry skeletal-root repair candidates.

The original job, proposal and candidate stay immutable. Only the existing
source-captured root-lock adapter may add actions; no model-authored values.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MAX_REPAIR_ATTEMPTS = 1
STRATEGY = "review_motion_mapping"
LINEAGE = "studio_repair_lineage"
ROOT_LOCK = "enable_cinetwin_skeletal_world_lock"


def snapshot(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def _candidate(root, name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,128}", name):
        raise ValueError("Invalid repair candidate identity.")
    path = root / name
    if path.resolve().parent != root.resolve() or path.is_symlink():
        raise ValueError("Unsafe repair candidate path.")
    return path


def _level(level):
    if not isinstance(level, str) or not re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+", level):
        raise ValueError("Select a separate saved Unreal staging level.")
    return level


def parent_evidence(root, job_id, verify_parent):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid repair parent job.")
    job, job_hash = snapshot(root.parent / "jobs" / (job_id + ".json"))
    parent = _candidate(root, job["candidate_id"])
    if (job.get("job_id") != job_id or Path(job["candidate_dir"]).resolve() != parent.resolve()
            or not job.get("ai_authorization") or job.get("repair_feedback_ready") is not True
            or job.get("status") != "GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED"):
        raise ValueError("Measured completed AI parent job required.")
    raw_session, session_hash = snapshot(parent / "session.json")
    mapping, _ = snapshot(raw_session["target"]["mapping_path"])
    if LINEAGE in mapping or mapping.get(ROOT_LOCK):
        raise ValueError("Repair lineage budget exhausted or root correction already enabled.")
    session = verify_parent(parent)
    if session != raw_session or not session.get("source_capture") or not session.get("ai_analysis"):
        raise ValueError("Verified parent source capture and AI analysis required.")
    plan, plan_hash = snapshot(parent / "transfer-plan.json")
    setup, setup_hash = snapshot(parent / "automatic-setup.json")
    proposal, proposal_hash = snapshot(parent / ("ai-repair-proposal-" + job_id + ".json"))
    report, report_hash = snapshot(parent / ("closed-loop-evaluation-" + job_id + ".json"))
    claim, _ = snapshot(parent / ("ai-repair-claim-" + job_id + ".json"))
    binding = {"job_id": job_id, "candidate_id": parent.name, "sequence_path": job["sequence_path"],
               "session_sha256": session_hash, "transfer_plan_sha256": plan_hash}
    if (session["target"]["sequence_asset_path"] != job["sequence_path"]
            or session["artifact_sha256"]["transfer-plan.json"] != plan_hash
            or report_hash != job.get("closed_loop_report_sha256")
            or report.get("feedback_binding") != binding
            or report.get("kind") != "cutsceneai.studio.closed_loop_evaluation"
            or report.get("repair_iterations_executed") != 0
            or proposal.get("kind") != "cutsceneai.studio.ai_repair_proposal"
            or proposal.get("feedback_binding") != binding
            or proposal.get("feedback_sha256") != report_hash
            or proposal.get("setup_sha256") != setup_hash
            or claim != {**binding, "feedback_sha256": report_hash,
                         "setup_sha256": setup_hash, "decision_budget": 1}
            or proposal.get("execution_authorized") is not False
            or proposal.get("decision_status") != "proposed"
            or proposal.get("selected_strategy") != STRATEGY):
        raise ValueError("No verified executable root-motion repair proposal.")
    from packages.studio.repair_feedback import eligible

    indices = eligible(report, plan, setup).get(STRATEGY, [])
    if not indices or proposal.get("issue_indices") != indices:
        raise ValueError("Repair proposal differs from measured eligible issues.")
    issues = [report["issues"][index] for index in indices]
    if any(row.get("domain") != "skeletal_root_world" for row in issues):
        raise ValueError("Actor-world motion repair needs a different adapter.")
    names = sorted({row["source"] for row in issues})
    if not all(any(action.get("kind") == "skeletal_animation" and action.get("entity_name") == name
                   for action in plan["actions"]) for name in names):
        raise ValueError("No source-bound skeletal animation for repair.")
    return {"parent": parent, "session": session, "mapping": mapping, "plan": plan, "setup": setup,
            "job": job, "binding": binding, "job_sha256": job_hash, "proposal_sha256": proposal_hash,
            "feedback_sha256": report_hash, "setup_sha256": setup_hash, "entities": names}


def derive(evidence, child_id, level):
    """Deterministically relocate imports and enable only the existing adapter."""
    if not re.fullmatch(r"repair_[0-9a-f]{12}", child_id):
        raise ValueError("Invalid fresh repair identity.")
    if _level(level) == evidence["job"]["expected_level"]:
        raise ValueError("Repair must not reuse the original level.")
    namespace = "/Game/CutSceneAI/AutoTransfer/T_" + child_id.upper()
    mapping = dict(evidence["mapping"])
    assets = mapping.get("assets", {})
    if not isinstance(assets, dict) or len(set(assets.values())) != len(assets):
        raise ValueError("Repair asset identities are not unique.")
    mapped = {}
    for name, old in sorted(assets.items()):
        if not isinstance(old, str) or not old.startswith("/Game/"):
            raise ValueError("Repair requires fresh project-owned mapped assets.")
        suffix = re.sub(r"[^A-Za-z0-9_]", "_", name)
        mapped[name] = namespace + "/Mapped/CSAI_" + suffix
    if len(set(mapped.values())) != len(mapped):
        raise ValueError("Repair asset paths collide.")
    lineage = {"parent_job_id": evidence["job"]["job_id"],
               "parent_candidate_id": evidence["parent"].name,
               "child_candidate_id": child_id, "target_level": level,
               "parent_job_sha256": evidence["job_sha256"],
               "parent_session_sha256": evidence["binding"]["session_sha256"],
               "parent_setup_sha256": evidence["setup_sha256"],
               "proposal_sha256": evidence["proposal_sha256"],
               "feedback_sha256": evidence["feedback_sha256"],
               "entities": evidence["entities"], "attempt": MAX_REPAIR_ATTEMPTS}
    mapping.update(sequence_asset_path=namespace + "/LS_Repair", overwrite_sequence=False,
                   assets=mapped, **{ROOT_LOCK: True, LINEAGE: lineage})
    return mapping, namespace


def validate_delta(evidence, mapping, child_plan):
    """The old actions must be unchanged except for relocated asset paths."""
    replacements = {old: mapping["assets"][name] for name, old in evidence["mapping"]["assets"].items()}
    def relocate(value):
        if isinstance(value, dict):
            return {key: relocate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relocate(item) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value

    old = evidence["plan"]
    normal = dict(child_plan)
    actions = normal.pop("actions")
    expected = dict(relocate(old))
    baseline = expected.pop("actions")
    expected["sequence_asset_path"] = mapping["sequence_asset_path"]
    additions = [action for action in actions if action["kind"] == "skeletal_world_root_lock"]
    remaining = [action for action in actions if action["kind"] != "skeletal_world_root_lock"]
    if (normal != expected or remaining != baseline
            or sorted(action["entity_name"] for action in additions) != evidence["entities"]):
        raise ValueError("Repair would change unrelated actions or cannot correct every selected root.")


def verify_child(candidate, session, verify_parent):
    mapping, _ = snapshot(session["target"]["mapping_path"])
    lineage = mapping.get(LINEAGE)
    if lineage is None:
        return
    root = candidate.resolve().parent
    evidence = parent_evidence(root, lineage["parent_job_id"], verify_parent)
    expected, namespace = derive(evidence, candidate.name, lineage["target_level"])
    claim, _ = snapshot(evidence["parent"] / "repair-attempt.json")
    if (mapping != expected or claim != expected[LINEAGE]
            or session["source"] != evidence["session"]["source"]
            or session["source_capture"] != evidence["session"]["source_capture"]
            or session["ai_analysis"] != evidence["session"]["ai_analysis"]
            or session["target"]["project_path"] != evidence["session"]["target"]["project_path"]):
        raise ValueError("Repair lineage or source evidence differs.")
    plan, _ = snapshot(candidate / "transfer-plan.json")
    validate_delta(evidence, mapping, plan)
    setup_path = candidate / "automatic-setup.json"
    if setup_path.exists():
        setup, _ = snapshot(setup_path)
        if setup.get("target_folder") != namespace:
            raise ValueError("Repair setup namespace differs.")


def prepare(folder, job_id, child_id, level, *, verify_parent, prepare_transfer, inspect_setup):
    root = (folder / "candidates").resolve()
    active, _ = snapshot(folder / "active-job.json")
    if active.get("job_id") != job_id:
        raise ValueError("Repair requires the active completed parent job.")
    evidence = parent_evidence(root, job_id, verify_parent)
    mapping, namespace = derive(evidence, child_id, level)
    child = _candidate(root, child_id)
    mapping_path = child.with_suffix(".mapping.json")
    if child.exists() or mapping_path.exists():
        raise ValueError("Fresh repair candidate already exists.")
    write_new(evidence["parent"] / "repair-attempt.json", mapping[LINEAGE])
    write_new(mapping_path, mapping)
    parent = evidence["session"]
    session = prepare_transfer(parent["source"]["csir_path"], mapping_path, child,
                               capture_path=parent["source_capture"]["path"],
                               analysis_path=parent["ai_analysis"]["path"],
                               target_project=parent["target"]["project_path"])
    plan, _ = snapshot(child / "transfer-plan.json")
    validate_delta(evidence, mapping, plan)
    setup = inspect_setup(parent["source"]["csir_path"], mapping_path, child / "transfer-plan.json",
                          evidence["setup"]["source_project"], evidence["setup"]["source_scope"], namespace)
    if setup.get("ready") is not True:
        raise ValueError("Repair asset setup is blocked.")
    write_new(child / "automatic-setup.json", setup)
    verify_child(child, session, verify_parent)
    return child, mapping_path, session, setup
