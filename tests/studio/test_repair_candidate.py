"""Pure repair plan delta and lineage safety tests."""
import pytest

from packages.studio import repair_candidate as repair


def evidence(tmp_path):
    return {"parent": tmp_path / "original", "job": {"job_id": "a" * 32, "expected_level": "/Game/Original"},
            "mapping": {"sequence_asset_path": "/Game/OriginalSequence", "assets": {"Walk": "/Game/Walk"}},
            "plan": {"sequence_asset_path": "/Game/OriginalSequence", "actions": [
                {"kind": "skeletal_animation", "entity_name": "Hero", "unreal_asset_path": "/Game/Walk"}]},
            "binding": {"session_sha256": "session"}, "job_sha256": "job",
            "proposal_sha256": "proposal", "feedback_sha256": "feedback", "setup_sha256": "setup",
            "entities": ["Hero"]}


def test_repair_relocates_assets_and_only_adds_selected_root_lock(tmp_path):
    old = evidence(tmp_path)
    mapping, namespace = repair.derive(old, "repair_abcdef012345", "/Game/Staging")
    assert mapping[repair.ROOT_LOCK] is True
    assert mapping[repair.LINEAGE]["attempt"] == 1
    assert mapping["assets"]["Walk"].startswith(namespace + "/")
    plan = {"sequence_asset_path": mapping["sequence_asset_path"], "actions": [
        {"kind": "skeletal_animation", "entity_name": "Hero", "unreal_asset_path": mapping["assets"]["Walk"]},
        {"kind": "skeletal_world_root_lock", "entity_name": "Hero"}]}
    repair.validate_delta(old, mapping, plan)
    assert repair.ROOT_LOCK not in old["mapping"]


@pytest.mark.parametrize("level", ["/Game/Original", "/Game/../Original", "/Engine/Other", ""])
def test_repair_rejects_unsafe_or_original_level(tmp_path, level):
    with pytest.raises(ValueError):
        repair.derive(evidence(tmp_path), "repair_abcdef012345", level)


@pytest.mark.parametrize("case", ["missing", "other", "changed", "duplicate"])
def test_repair_refuses_unrelated_or_missing_action_delta(tmp_path, case):
    old = evidence(tmp_path)
    mapping, _ = repair.derive(old, "repair_abcdef012345", "/Game/Staging")
    actions = [{"kind": "skeletal_animation", "entity_name": "Hero", "unreal_asset_path": mapping["assets"]["Walk"]}]
    if case != "missing":
        actions.append({"kind": "skeletal_world_root_lock", "entity_name": "Other" if case == "other" else "Hero"})
    if case == "changed":
        actions[0]["play_rate"] = 2
    if case == "duplicate":
        actions.append(dict(actions[-1]))
    with pytest.raises(ValueError, match="unrelated"):
        repair.validate_delta(old, mapping, {"sequence_asset_path": mapping["sequence_asset_path"], "actions": actions})


def test_attempt_claim_cannot_be_replaced(tmp_path):
    path = tmp_path / "repair-attempt.json"
    repair.write_new(path, {"attempt": 1})
    with pytest.raises(FileExistsError):
        repair.write_new(path, {"attempt": 2})
    assert repair.snapshot(path)[0] == {"attempt": 1}


def _parent_fixture(folder):
    job_id = "a" * 32
    parent = folder / "candidates" / "original"
    parent.mkdir(parents=True)
    (folder / "jobs").mkdir()
    old = evidence(folder)
    mapping_path = parent / "mapping.json"
    repair.write_new(mapping_path, old["mapping"])
    plan = old["plan"]
    plan["bindings"] = {"Hero": "Hero"}
    repair.write_new(parent / "transfer-plan.json", plan)
    _, plan_hash = repair.snapshot(parent / "transfer-plan.json")
    session = {"source": {"csir_path": "source"}, "source_capture": {"path": "capture"},
               "ai_analysis": {"path": "analysis"},
               "target": {"mapping_path": str(mapping_path), "project_path": "project",
                          "sequence_asset_path": old["mapping"]["sequence_asset_path"]},
               "artifact_sha256": {"transfer-plan.json": plan_hash}}
    repair.write_new(parent / "session.json", session)
    _, session_hash = repair.snapshot(parent / "session.json")
    setup = {"source_project": "unity", "source_scope": "Assets", "actors": [],
             "source_albedo_actor_candidates": {}}
    repair.write_new(parent / "automatic-setup.json", setup)
    _, setup_hash = repair.snapshot(parent / "automatic-setup.json")
    binding = {"job_id": job_id, "candidate_id": parent.name,
               "sequence_path": session["target"]["sequence_asset_path"],
               "session_sha256": session_hash, "transfer_plan_sha256": plan_hash}
    report_path = parent / ("closed-loop-evaluation-" + job_id + ".json")
    repair.write_new(report_path, {"kind": "cutsceneai.studio.closed_loop_evaluation",
                                   "feedback_binding": binding, "repair_iterations_executed": 0,
                                   "issues": [{"category": "CED_ANIMATION_TRANSFORM_FIDELITY",
                                               "status": "MEASURED_MISMATCH", "source": "Hero",
                                               "domain": "skeletal_root_world",
                                               "error_cm": 8.0, "tolerance_cm": 2.0}]})
    _, report_hash = repair.snapshot(report_path)
    claim = {**binding, "feedback_sha256": report_hash, "setup_sha256": setup_hash, "decision_budget": 1}
    repair.write_new(parent / ("ai-repair-claim-" + job_id + ".json"), claim)
    repair.write_new(parent / ("ai-repair-proposal-" + job_id + ".json"), {
        "kind": "cutsceneai.studio.ai_repair_proposal", "feedback_binding": binding,
        "feedback_sha256": report_hash, "setup_sha256": setup_hash, "decision_status": "proposed",
        "selected_strategy": repair.STRATEGY, "issue_indices": [0], "execution_authorized": False})
    repair.write_new(folder / "jobs" / (job_id + ".json"), {
        "job_id": job_id, "candidate_id": parent.name, "candidate_dir": str(parent),
        "status": "GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED", "ai_authorization": {"approved": True},
        "repair_feedback_ready": True, "sequence_path": binding["sequence_path"],
        "expected_level": "/Game/Original", "closed_loop_report_sha256": report_hash})
    repair.write_new(folder / "active-job.json", {"job_id": job_id})
    return job_id, parent, session, plan


def test_file_backed_repair_replay_and_single_attempt(tmp_path):
    job_id, parent, original, original_plan = _parent_fixture(tmp_path)
    before = (parent / "transfer-plan.json").read_bytes()

    def verify(candidate):
        assert candidate == parent
        return original

    def prepare_transfer(_source, mapping_path, child, **_options):
        mapping, _ = repair.snapshot(mapping_path)
        child.mkdir()
        plan = {**original_plan, "sequence_asset_path": mapping["sequence_asset_path"],
                "actions": [{**original_plan["actions"][0], "unreal_asset_path": mapping["assets"]["Walk"]},
                            {"kind": "skeletal_world_root_lock", "entity_name": "Hero"}]}
        repair.write_new(child / "transfer-plan.json", plan)
        return {**original, "target": {**original["target"], "mapping_path": str(mapping_path),
                                       "sequence_asset_path": mapping["sequence_asset_path"]}}

    def inspect_setup(*args):
        return {"ready": True, "target_folder": args[-1]}

    kwargs = {"verify_parent": verify, "prepare_transfer": prepare_transfer, "inspect_setup": inspect_setup}
    child, _mapping, session, _setup = repair.prepare(
        tmp_path, job_id, "repair_abcdef012345", "/Game/Staging", **kwargs)
    repair.verify_child(child, session, verify)
    assert (parent / "transfer-plan.json").read_bytes() == before
    assert (tmp_path / "active-job.json").is_file()
    with pytest.raises(ValueError, match="budget"):
        repair.prepare(tmp_path, job_id, "repair_123456abcdef", "/Game/Staging", **kwargs)
    proposal_path = parent / ("ai-repair-proposal-" + job_id + ".json")
    proposal, _ = repair.snapshot(proposal_path)
    proposal["changed"] = True
    proposal_path.unlink()
    repair.write_new(proposal_path, proposal)
    with pytest.raises(ValueError, match="lineage"):
        repair.verify_child(child, session, verify)
