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
