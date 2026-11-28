"""Independent bounded repair comparison from native CineTwin frame evidence."""
from __future__ import annotations

import math
import ntpath
import re
from pathlib import Path

from packages.studio.repair_candidate import snapshot
from packages.studio.repair_candidate import write_new as write_new

EPSILON_CM = 0.01
MAX_FRAMES = 3000
METRICS = ("max_absolute_error_cm", "max_offset_removed_motion_error_cm")


def _position(value):
    if (not isinstance(value, (tuple, list)) or len(value) != 3
            or any(type(item) not in (int, float) or not math.isfinite(item) for item in value)):
        raise ValueError("Invalid native pose position.")
    return tuple(value)


def _samples(rows, frames, *, skeletal):
    if not isinstance(rows, list) or len(rows) != len(frames):
        raise ValueError("Incomplete native pose samples.")
    source, target, bones = [], [], set()
    for row, frame in zip(rows, frames, strict=True):
        if not isinstance(row, dict) or type(row.get("frame")) is not int or row["frame"] != frame:
            raise ValueError("Native pose frame identity differs.")
        source.append(_position(row["source_cm"]))
        target.append(_position(row["target_cm"]))
        if skeletal:
            pair = (row.get("source_bone_id"), row.get("target_bone_name"))
            if not all(isinstance(item, str) and item for item in pair):
                raise ValueError("Skeletal root sample identity unavailable.")
            bones.add(pair)
    if skeletal and len(bones) != 1:
        raise ValueError("Skeletal root identity varies across frames.")
    return source, target, bones


def _metrics(source, target):
    absolute = [math.dist(a, b) for a, b in zip(source, target, strict=True)]
    relative = [math.dist(tuple(x - origin for x, origin in zip(a, source[0], strict=True)),
                          tuple(x - origin for x, origin in zip(b, target[0], strict=True)))
                for a, b in zip(source, target, strict=True)]
    if not all(math.isfinite(value) for value in absolute + relative):
        raise ValueError("Nonfinite native pose error.")
    return dict(zip(METRICS, (max(absolute), max(relative)), strict=True))


def _range(report):
    start, end = report["target"]["sequence_playback_frames"]
    if type(start) is not int or type(end) is not int or not 0 < end - start <= MAX_FRAMES:
        raise ValueError("Invalid native playback range.")
    source = report["source"]
    rate = report["target"]["display_rate"]
    n, d = rate["numerator"], rate["denominator"]
    if (type(n) is not int or type(d) is not int or n <= 0 or d <= 0
            or not math.isclose(n / d, source["fps"], rel_tol=1e-9, abs_tol=0)
            or source["evaluated_playback_frames"] != end - start
            or source["missing_source_frames"] or report["errors"]):
        raise ValueError("Native diagnostic timing or coverage incomplete.")
    return list(range(start, end))


def compare(before, after, *, bindings, selected, skeletal_entities):
    """Recompute both position metrics on exactly the same source frames."""
    rows = []
    incomplete = []
    regressed = False
    improved = set()
    try:
        if not selected or not set(selected) <= set(skeletal_entities) <= set(bindings):
            raise ValueError("Repair selection differs from source skeletal bindings.")
        frames = _range(before)
        if _range(after) != frames:
            raise ValueError("Playback ranges differ.")
        for key in ("csir_sha256", "capture_sha256", "cutscene_id", "fps",
                    "source_frames", "excluded_frames_outside_playback"):
            if before["source"][key] != after["source"][key]:
                raise ValueError("Source diagnostic evidence differs: " + key)
        for report in (before, after):
            if set(report["entities"]) != set(bindings) or set(report["frames"]) != set(bindings):
                raise ValueError("Diagnostic actor inventory differs from plan.")
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        return {"status": "INCOMPLETE", "metrics": [], "incomplete": [str(exc)],
                "fidelity_verified": False}

    for name, label in sorted(bindings.items()):
        a, b = before["entities"][name], after["entities"][name]
        if (any(not isinstance(row, dict) or row.get("status") != "READY"
                or type(row.get("actor_match_count")) is not int or row["actor_match_count"] != 1
                or row.get("target_actor_label") != label for row in (a, b))
                or not a.get("source_entity_id") or a["source_entity_id"] != b.get("source_entity_id")):
            incomplete.append(name + ": actor correspondence unavailable")
            continue
        for domain in ("actor", "root_bone"):
            skeletal = domain == "root_bone"
            first_record = before["frames"][name]
            second_record = after["frames"][name]
            first = first_record.get(domain) if isinstance(first_record, dict) else None
            second = second_record.get(domain) if isinstance(second_record, dict) else None
            if skeletal and name not in skeletal_entities and first == [] and second == []:
                continue
            try:
                src, old_target, old_bones = _samples(first, frames, skeletal=skeletal)
                new_src, new_target, new_bones = _samples(second, frames, skeletal=skeletal)
                if src != new_src or old_bones != new_bones:
                    raise ValueError("Source positions or root bone correspondence differ.")
                old, new = _metrics(src, old_target), _metrics(src, new_target)
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                incomplete.append(name + "/" + domain + ": " + str(exc))
                continue
            is_selected = skeletal and name in selected
            worse = any(new[key] > old[key] + EPSILON_CM for key in METRICS)
            better = is_selected and old[METRICS[1]] - new[METRICS[1]] > EPSILON_CM
            regressed = regressed or worse
            if better and not worse:
                improved.add(name)
            rows.append({"entity": name, "domain": domain, "selected": is_selected,
                         "sample_count": len(frames), "before": old, "after": new,
                         "status": "REGRESSED" if worse else "IMPROVED" if better else "NO_REGRESSION"})
    if regressed:
        status = "REGRESSION_DETECTED"
    elif incomplete:
        status = "INCOMPLETE"
    elif improved == set(selected):
        status = "MEASURED_ROOT_MOTION_IMPROVED"
    else:
        status = "NO_MEASURED_IMPROVEMENT"
    return {"status": status, "metrics": rows, "incomplete": incomplete, "fidelity_verified": False}


def _diagnostic(candidate, job, session):
    path = Path(job["diagnostic_file"])
    if (path.resolve().parent != candidate.resolve()
            or not re.fullmatch(r"CineTwin_WorldPose_Diagnosis_[A-Za-z0-9]+\.json", path.name)
            or path.stat().st_size > 128 * 1024 * 1024):
        raise ValueError("Unsafe native diagnostic path.")
    report, digest = snapshot(path)
    source = report["source"]
    target = report["target"]
    if (digest != job.get("diagnostic_sha256")
            or report.get("kind") != "cutsceneai.cinetwin.unreal_world_pose_diagnostic"
            or source["csir_sha256"] != session["source"]["sha256"]
            or source["capture_sha256"] != session["source_capture"]["sha256"]
            or source["mapping_sha256"] != session["target"]["mapping_sha256"]
            or source["cutscene_id"] != session["cutscene_id"]
            or target["sequence_path"].split(".", 1)[0] != session["target"]["sequence_asset_path"]
            or target["level"] != job["expected_level"]
            or ntpath.normcase(ntpath.normpath(target["project"])) !=
               ntpath.normcase(ntpath.normpath(job["expected_project"]))):
        raise ValueError("Native diagnostic differs from verified job/session evidence.")
    return report, digest


def _candidate(folder, job):
    root = (folder / "candidates").resolve()
    candidate = (root / job["candidate_id"]).resolve()
    if candidate.parent != root or candidate != Path(job["candidate_dir"]).resolve():
        raise ValueError("Repair outcome candidate is outside workspace.")
    return candidate


def compare_jobs(folder, job, session, lineage):
    """Bind original and repaired observations to the verified repair lineage."""
    folder = Path(folder)
    parent_id = lineage["parent_job_id"]
    if not re.fullmatch(r"[0-9a-f]{32}", parent_id) or parent_id == job["job_id"]:
        raise ValueError("Invalid repair comparison parent.")
    parent, parent_hash = snapshot(folder / "jobs" / (parent_id + ".json"))
    parent_dir = _candidate(folder, parent)
    child_dir = _candidate(folder, job)
    baseline, baseline_hash = snapshot(parent_dir / "session.json")
    child_session, child_hash = snapshot(child_dir / "session.json")
    if (parent_hash != lineage["parent_job_sha256"] or baseline_hash != lineage["parent_session_sha256"]
            or parent["job_id"] != parent_id or parent_dir.name != lineage["parent_candidate_id"]
            or child_dir.name != lineage["child_candidate_id"] or child_session != session
            or job["expected_level"] != lineage["target_level"]
            or parent["expected_level"] == job["expected_level"]
            or parent["sequence_path"] != baseline["target"]["sequence_asset_path"]
            or job["sequence_path"] != session["target"]["sequence_asset_path"]
            or baseline["source"] != session["source"] or baseline["source_capture"] != session["source_capture"]
            or baseline["target"]["project_path"] != session["target"]["project_path"]):
        raise ValueError("Repair outcome lineage differs from prepared evidence.")
    before, before_hash = _diagnostic(parent_dir, parent, baseline)
    after, after_hash = _diagnostic(child_dir, job, session)
    plan, plan_hash = snapshot(child_dir / "transfer-plan.json")
    if plan_hash != session["artifact_sha256"]["transfer-plan.json"]:
        raise ValueError("Repair comparison plan changed.")
    skeletal = {row["entity_name"] for row in plan["actions"] if row["kind"] == "skeletal_animation"}
    result = compare(before, after, bindings=plan["bindings"], selected=lineage["entities"],
                     skeletal_entities=skeletal)
    # Even favorable motion measurements cannot establish native structure.
    keys = ("generation_readback_status", "generation_hierarchy_status")
    native = {"parent": {key: parent.get(key) for key in keys},
              "child": {key: job.get(key) for key in keys}}
    if "FAIL" in native["child"].values():
        result["status"] = "REGRESSION_DETECTED"
    elif (result["status"] == "MEASURED_ROOT_MOTION_IMPROVED"
          and any(set(side.values()) != {"PASS"} for side in native.values())):
        result["status"] = "INCOMPLETE"
        result["incomplete"].append("Original or repaired native structure/hierarchy readback not passed.")
    return {"kind": "cutsceneai.studio.repair_outcome", "schema_version": "0.1.0",
            "parent_job_id": parent_id, "child_job_id": job["job_id"],
            "parent_session_sha256": baseline_hash, "child_session_sha256": child_hash,
            "parent_diagnostic_sha256": before_hash, "child_diagnostic_sha256": after_hash,
            "native_readback": native, "comparison_epsilon_cm": EPSILON_CM,
            "automatic_retry_allowed": False,
            "limitations": ["Only maximum absolute and offset-removed world position error on matching frames.",
                            "No full pose, visual, audio, event, restart or runtime fidelity claim."],
            **result}
