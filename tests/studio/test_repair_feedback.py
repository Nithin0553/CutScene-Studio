"""Repair proposals are advisory, source-bound and at most one per job."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.studio import repair_feedback as repair


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path):
    job_id = "a" * 32
    candidate = tmp_path / "candidates" / "fresh"
    plan_hash = write(candidate / "transfer-plan.json", {"bindings": {"Hero": "CSAI_Hero"}})
    mapping_path = candidate / "mapping.json"
    write(mapping_path, {})
    session = {"ai_analysis": {"sha256": "evidence"}, "artifact_sha256": {"transfer-plan.json": plan_hash},
               "target": {"sequence_asset_path": "/Game/Sequence", "mapping_path": str(mapping_path)}}
    session_hash = write(candidate / "session.json", session)
    write(candidate / "automatic-setup.json", {"actors": [], "source_albedo_actor_candidates": {}})
    binding = {"job_id": job_id, "candidate_id": "fresh", "sequence_path": "/Game/Sequence",
               "session_sha256": session_hash, "transfer_plan_sha256": plan_hash}
    report = {"kind": "cutsceneai.studio.closed_loop_evaluation", "feedback_binding": binding,
              "repair_iterations_executed": 0, "issues": [
                  {"category": "CED_ANIMATION_TRANSFORM_FIDELITY", "status": "MEASURED_MISMATCH",
                   "source": "Hero", "domain": "actor_world", "error_cm": 5.0, "tolerance_cm": 2.0}]}
    report_path = candidate / ("closed-loop-evaluation-" + job_id + ".json")
    report_hash = write(report_path, report)
    job = {"job_id": job_id, "candidate_id": "fresh", "candidate_dir": str(candidate),
           "ai_authorization": {"approval_id": "test"}, "repair_feedback_ready": True,
           "status": "GENERATED_AND_MEASURED_NOT_FIDELITY_VERIFIED",
           "sequence_path": "/Game/Sequence", "closed_loop_report_file": str(report_path),
           "closed_loop_report_sha256": report_hash}
    write(tmp_path / "jobs" / (job_id + ".json"), job)
    write(tmp_path / "active-job.json", {"job_id": job_id})
    return job_id, candidate, session, report_path


class Agent:
    def __init__(self, selected=repair.MOTION, callback=None):
        self.selected = selected
        self.calls = []
        self.callback = callback

    def select_mapping(self, feature, candidates):
        self.calls.append((feature, candidates))
        if self.callback:
            self.callback()
        return SimpleNamespace(status="proposed" if self.selected else "unsupported",
                               mapping_id=self.selected)


def test_single_decision_is_bound_and_never_authorizes_execution(tmp_path):
    job_id, candidate, session, _report = fixture(tmp_path)
    agent = Agent()
    result = repair.propose(tmp_path, job_id, agent, verify_candidate=lambda _: session)
    assert result["selected_strategy"] == repair.MOTION
    assert result["issue_indices"] == [0]
    assert result["execution_authorized"] is False
    assert result["automatic_repair_executed"] is False
    assert result["fresh_candidate_required"] is True
    assert len(agent.calls) == 1
    assert len(list(candidate.glob("ai-repair-proposal-*.json"))) == 1
    with pytest.raises(ValueError, match="budget"):
        repair.propose(tmp_path, job_id, agent, verify_candidate=lambda _: session)
    assert len(agent.calls) == 1


@pytest.mark.parametrize("case", ["report", "active", "unfinished", "foreign_candidate"])
def test_invalid_feedback_refused_before_model_call(tmp_path, case):
    job_id, candidate, session, report = fixture(tmp_path)
    if case == "report":
        report.write_text("{}")
    elif case == "active":
        write(tmp_path / "active-job.json", {"job_id": "b" * 32})
    else:
        path = tmp_path / "jobs" / (job_id + ".json")
        job = json.loads(path.read_text())
        if case == "unfinished":
            job["repair_feedback_ready"] = False
        else:
            job["candidate_dir"] = str(tmp_path)
        write(path, job)
    agent = Agent()
    with pytest.raises(ValueError):
        repair.propose(tmp_path, job_id, agent, verify_candidate=lambda _: session)
    assert not agent.calls
    assert not list(candidate.glob("ai-repair-claim-*.json"))


def test_evidence_changed_during_inference_consumes_budget_without_proposal(tmp_path):
    job_id, candidate, session, report = fixture(tmp_path)
    agent = Agent(callback=lambda: report.write_text("{}"))
    with pytest.raises(ValueError, match="changed"):
        repair.propose(tmp_path, job_id, agent, verify_candidate=lambda _: session)
    assert len(list(candidate.glob("ai-repair-claim-*.json"))) == 1
    assert not list(candidate.glob("ai-repair-proposal-*.json"))


def test_invented_strategy_cannot_be_published(tmp_path):
    job_id, candidate, session, _report = fixture(tmp_path)
    with pytest.raises(ValueError, match="outside eligible"):
        repair.propose(tmp_path, job_id, Agent("arbitrary_code"), verify_candidate=lambda _: session)
    assert not list(candidate.glob("ai-repair-proposal-*.json"))


def test_material_strategy_requires_actor_scoped_source_evidence():
    report = {"issues": [{"category": "VISUAL_NATIVE_READBACK", "status": "NATIVE_GAP",
                          "code": "RENDER_MATERIALS_MISSING_OR_ENGINE_DEFAULT"}]}
    setup = {"actors": [{"name": "Hero", "kind": "entity.character"}],
             "source_albedo_actor_candidates": {"Other": [{"slot_name": "Body"}]}}
    assert repair.eligible(report, {}, setup) == {}
    setup["source_albedo_actor_candidates"]["Hero"] = [{"slot_name": "Body"}]
    assert repair.eligible(report, {}, setup) == {repair.MATERIAL: [0]}
