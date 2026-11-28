"""Independent before/after world-pose evidence, without engine launches."""
from copy import deepcopy

import pytest

from packages.studio import repair_outcome as outcome


def report(error):
    frames = [0, 1, 2]
    points = [{"frame": frame, "source_cm": [frame * 10, 0, 0],
               "target_cm": [frame * 10 + error * frame / 2, 0, 0],
               "source_bone_id": "Rig/Hips[0]", "target_bone_name": "Hips"}
              for frame in frames]
    actor = [{**row, "target_cm": row["source_cm"][:]} for row in points]
    entity = {"status": "READY", "actor_match_count": 1, "source_entity_id": "hero",
              "target_actor_label": "Hero"}
    return {"source": {"csir_sha256": "source", "capture_sha256": "capture",
                       "cutscene_id": "scene", "fps": 24, "source_frames": 4,
                       "evaluated_playback_frames": 3, "excluded_frames_outside_playback": [3],
                       "missing_source_frames": []},
            "target": {"sequence_playback_frames": [0, 3],
                       "display_rate": {"numerator": 24, "denominator": 1}},
            "entities": {"Hero": entity},
            "frames": {"Hero": {"actor": actor, "root_bone": points}}, "errors": []}


def compare(before, after):
    return outcome.compare(before, after, bindings={"Hero": "Hero"},
                           selected=["Hero"], skeletal_entities={"Hero"})


@pytest.mark.parametrize("error,status", [(2, "MEASURED_ROOT_MOTION_IMPROVED"),
                                          (8, "NO_MEASURED_IMPROVEMENT"),
                                          (10, "REGRESSION_DETECTED")])
def test_root_comparison_recomputes_actual_native_errors(error, status):
    before, after = report(8), report(error)
    before["entities"]["Hero"]["skeletal_root_world"] = {"max_absolute_error_cm": 1000}
    result = compare(before, after)
    assert result["status"] == status
    row = next(row for row in result["metrics"] if row["selected"])
    assert row["before"]["max_offset_removed_motion_error_cm"] == 8
    assert row["after"]["max_offset_removed_motion_error_cm"] == error
    assert result["fidelity_verified"] is False


def test_root_improvement_with_actor_regression_is_not_accepted():
    before, after = report(8), report(1)
    after["frames"]["Hero"]["actor"][-1]["target_cm"] = [30, 0, 0]
    assert compare(before, after)["status"] == "REGRESSION_DETECTED"


def test_absolute_offset_regression_blocks_relative_improvement():
    before, after = report(8), report(1)
    for row in after["frames"]["Hero"]["root_bone"]:
        row["target_cm"][0] += 20
    assert compare(before, after)["status"] == "REGRESSION_DETECTED"


@pytest.mark.parametrize("case", ["missing_frame", "wrong_frame", "wrong_bone", "source_point",
                                  "source_hash", "wrong_rate", "missing_source", "nan",
                                  "actor_mapping", "native_error", "range"])
def test_incompatible_native_measurements_never_claim_improvement(case):
    before, after = report(8), deepcopy(report(1))
    rows = after["frames"]["Hero"]["root_bone"]
    if case == "missing_frame":
        rows.pop()
    elif case == "wrong_frame":
        rows[-1]["frame"] = 1
    elif case == "wrong_bone":
        rows[-1]["source_bone_id"] = "Other/Hips"
    elif case == "source_point":
        rows[-1]["source_cm"] = [22, 0, 0]
    elif case == "source_hash":
        after["source"]["capture_sha256"] = "other"
    elif case == "wrong_rate":
        after["target"]["display_rate"]["numerator"] = 30
    elif case == "missing_source":
        after["source"]["missing_source_frames"] = [1]
    elif case == "nan":
        rows[-1]["target_cm"] = [float("nan"), 0, 0]
    elif case == "actor_mapping":
        after["entities"]["Hero"]["actor_match_count"] = 2
    elif case == "native_error":
        after["errors"] = ["Native evaluation failed"]
    else:
        after["target"]["sequence_playback_frames"] = [0, 2]
        after["source"]["evaluated_playback_frames"] = 2
    assert compare(before, after)["status"] == "INCOMPLETE"


def test_comparison_preserves_evidence_and_never_overwrites(tmp_path):
    path = tmp_path / "outcome.json"
    result = compare(report(8), report(1))
    outcome.write_new(path, result)
    with pytest.raises(FileExistsError):
        outcome.write_new(path, result)


def _job_pair(folder):
    from packages.studio.repair_candidate import snapshot, write_new

    (folder / "jobs").mkdir()
    jobs = []
    sessions = []
    for name, job_id, error in (("original", "a" * 32, 8), ("repair", "b" * 32, 1)):
        candidate = folder / "candidates" / name
        candidate.mkdir(parents=True)
        plan = {"bindings": {"Hero": "Hero"}, "actions": [
            {"kind": "skeletal_animation", "entity_name": "Hero"}]}
        write_new(candidate / "transfer-plan.json", plan)
        _, plan_hash = snapshot(candidate / "transfer-plan.json")
        session = {"source": {"sha256": "source"}, "source_capture": {"sha256": "capture"},
                   "cutscene_id": "scene", "target": {"mapping_sha256": name,
                   "sequence_asset_path": "/Game/" + name, "project_path": "/project/Game.uproject"},
                   "artifact_sha256": {"transfer-plan.json": plan_hash}}
        write_new(candidate / "session.json", session)
        diagnostic = report(error)
        diagnostic["kind"] = "cutsceneai.cinetwin.unreal_world_pose_diagnostic"
        diagnostic["source"]["mapping_sha256"] = name
        diagnostic["target"].update(sequence_path="/Game/" + name + "." + name,
                                    level="/Game/Level_" + name, project="/project/Game.uproject")
        path = candidate / "CineTwin_WorldPose_Diagnosis_20261128T000000Z.json"
        write_new(path, diagnostic)
        _, digest = snapshot(path)
        job = {"job_id": job_id, "candidate_id": name, "candidate_dir": str(candidate),
               "expected_level": "/Game/Level_" + name, "expected_project": "/project/Game.uproject",
               "sequence_path": "/Game/" + name, "diagnostic_file": str(path),
               "diagnostic_sha256": digest, "generation_readback_status": "PASS",
               "generation_hierarchy_status": "PASS"}
        write_new(folder / "jobs" / (job_id + ".json"), job)
        jobs.append(job)
        sessions.append(session)
    _, parent_hash = snapshot(folder / "jobs" / ("a" * 32 + ".json"))
    _, session_hash = snapshot(folder / "candidates" / "original" / "session.json")
    lineage = {"parent_job_id": jobs[0]["job_id"], "parent_job_sha256": parent_hash,
               "parent_session_sha256": session_hash, "parent_candidate_id": "original",
               "child_candidate_id": "repair", "target_level": "/Game/Level_repair",
               "entities": ["Hero"]}
    return jobs[0], jobs[1], sessions[1], lineage


@pytest.mark.parametrize("case,expected", [("valid", "MEASURED_ROOT_MOTION_IMPROVED"),
                                           ("incomplete_native", "INCOMPLETE"),
                                           ("failed_native", "REGRESSION_DETECTED")])
def test_job_bound_outcome_requires_native_readback(tmp_path, case, expected):
    _parent, child, session, lineage = _job_pair(tmp_path)
    if case == "incomplete_native":
        child["generation_hierarchy_status"] = "INCOMPLETE"
    elif case == "failed_native":
        child["generation_readback_status"] = "FAIL"
    result = outcome.compare_jobs(tmp_path, child, session, lineage)
    assert result["status"] == expected
    assert result["automatic_retry_allowed"] is False
    assert result["parent_job_id"] == "a" * 32


@pytest.mark.parametrize("case", ["parent_job", "diagnostic_hash", "foreign_file", "child_plan", "same_level"])
def test_job_bound_comparison_rejects_detached_evidence(tmp_path, case):
    from pathlib import Path

    parent, child, session, lineage = _job_pair(tmp_path)
    if case == "parent_job":
        (tmp_path / "jobs" / ("a" * 32 + ".json")).write_text("{}")
    elif case == "diagnostic_hash":
        child["diagnostic_sha256"] = "wrong"
    elif case == "foreign_file":
        child["diagnostic_file"] = parent["diagnostic_file"]
    elif case == "child_plan":
        (Path(child["candidate_dir"]) / "transfer-plan.json").write_text("{}")
    else:
        child["expected_level"] = parent["expected_level"]
    with pytest.raises(ValueError):
        outcome.compare_jobs(tmp_path, child, session, lineage)
