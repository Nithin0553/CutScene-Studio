"""Source-bound retrieval tests with schema-valid synthetic CSIR."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import ValidationError

from packages.studio.mapping_resources import MappingResources
from packages.studio.source_evidence import SourceEvidence
from packages.studio.transfer_agent import MappingDecision


def _time(value):
    return {"value": value, "rate": {"numerator": 1, "denominator": 1}}


@pytest.fixture
def csir():
    def track(identity, binding, payload):
        return {
            "track_id": identity,
            "ced_type": "animation.track",
            "binding_entity_id": binding,
            "sections": [{
                "section_id": identity + "-section",
                "ced_type": "animation.section",
                "start": _time(0),
                "end": _time(1),
                "source_offset": _time(0),
                "payload": payload,
            }],
        }

    return {
        "schema_version": "0.1.0",
        "cutscene_id": "test-cutscene",
        "source": {
            "engine": "unity",
            "engine_version": "6000.0",
            "project_fingerprint": "fixture",
            "sequence_ref": "fixture",
        },
        "coordinate_system": {
            "handedness": "RIGHT_HANDED",
            "up_axis": "+Y",
            "forward_axis": "-Z",
            "right_axis": "+X",
            "linear_unit": "METER",
            "rotation_representation": "QUATERNION_XYZW",
        },
        "timing": {
            "source_rate": {"numerator": 24, "denominator": 1},
            "playback_start": _time(0),
            "playback_end": _time(1),
            "duration_seconds": 1,
        },
        "assets": [{
            "asset_id": "clip",
            "ced_type": "animation.clip",
            "source_ref": "fixture-clip",
        }],
        "entities": [
            {"entity_id": "character", "ced_type": "entity.character"},
            {"entity_id": "prop", "ced_type": "entity.prop"},
            {"entity_id": "camera", "ced_type": "entity.camera"},
        ],
        "tracks": [
            track("character-track", "character", {"asset_id": "clip"}),
            track("prop-track", "prop", {"animation": {"curves": [{
                "canonical_semantic": "transform.position.x",
                "keys": [{"time_seconds": 0, "value": 1}],
            }]}}),
            {
                "track_id": "cut",
                "ced_type": "camera.cut",
                "binding_entity_id": "camera",
                "sections": [{
                    "section_id": "cut-section",
                    "ced_type": "camera.cut",
                    "start": _time(0),
                    "end": _time(1),
                    "payload": {},
                }],
            },
        ],
        "relationships": [],
        "provenance": {"extractor": "fixture", "extracted_at_utc": "2026-11-26T00:00:00Z"},
    }


class FakeAgent:
    def __init__(self):
        self.calls = []

    def select_mapping(self, feature, candidates):
        self.calls.append((feature, candidates))
        assert len(candidates) == 1
        return MappingDecision(
            "proposed", candidates[0].mapping_id,
            "Selected from eligible mappings; native preflight still required.",
        )


@pytest.mark.parametrize(
    ("track_id", "mapping"),
    [
        ("character-track", "skeletal_animation"),
        ("prop-track", "transform"),
        ("cut", "camera_cut"),
    ],
)
def test_resolves_source_bound_actions(csir, track_id, mapping):
    analyzer = SourceEvidence(csir, MappingResources())
    agent = FakeAgent()
    result = analyzer.propose_track(agent, track_id)
    assert result.decision.status == "proposed"
    assert result.decision.mapping_id == mapping
    assert result.source_sha256 == analyzer.source_sha256
    assert "MISSING_TARGET_MAPPING" in result.source_alerts
    assert len(agent.calls) == 1


@pytest.mark.parametrize("change", ["missing_binding", "missing_asset", "muted", "empty"])
def test_missing_source_evidence_skips_inference(csir, change):
    track = csir["tracks"][0]
    if change == "missing_binding":
        track["binding_entity_id"] = "not-present"
    elif change == "missing_asset":
        track["sections"][0]["payload"]["asset_id"] = "not-present"
    elif change == "muted":
        track["muted"] = True
    else:
        track["sections"] = []
    analyzer = SourceEvidence(csir, MappingResources())
    agent = FakeAgent()
    result = analyzer.propose_track(agent, "character-track")
    assert result.decision.status != "proposed"
    assert not agent.calls


def test_missing_transform_keys_skips_inference(csir):
    csir["tracks"][1]["sections"][0]["payload"] = {}
    agent = FakeAgent()
    result = SourceEvidence(csir, MappingResources()).propose_track(agent, "prop-track")
    assert result.decision.status == "failed"
    assert not agent.calls


def test_duplicate_binding_id_rejected(csir):
    csir["entities"].append(copy.deepcopy(csir["entities"][0]))
    with pytest.raises(ValueError, match="Duplicate source identity"):
        SourceEvidence(csir, MappingResources())


def test_wrong_source_engine_rejected(csir):
    csir["source"]["engine"] = "unreal"
    with pytest.raises(ValueError, match="Unity"):
        SourceEvidence(csir, MappingResources())


def test_schema_invalid_source_rejected(csir):
    del csir["timing"]
    with pytest.raises(ValidationError):
        SourceEvidence(csir, MappingResources())


def test_source_snapshot_not_changed_by_caller(csir):
    analyzer = SourceEvidence(csir, MappingResources())
    csir["tracks"][0]["muted"] = True
    result = analyzer.propose_track(FakeAgent(), "character-track")
    assert result.decision.status == "proposed"


@pytest.mark.parametrize("section_type", ["camera.transform", "animation.section"])
def test_camera_transform_uses_source_curve_evidence(csir, section_type):
    track = csir["tracks"][1]
    track["ced_type"] = "camera.transform"
    track["binding_entity_id"] = "camera"
    track["sections"][0]["ced_type"] = section_type
    agent = FakeAgent()
    result = SourceEvidence(csir, MappingResources()).propose_track(agent, "prop-track")
    assert result.decision.status == "proposed"
    assert result.decision.mapping_id == "transform"
    assert "MISSING_TARGET_MAPPING" in result.source_alerts
    assert len(agent.calls) == 1


@pytest.mark.parametrize("change", ["wrong_binding", "missing_keys", "fov_only", "wrong_section"])
def test_camera_transform_withholds_without_matching_evidence(csir, change):
    track = csir["tracks"][1]
    track["ced_type"] = "camera.transform"
    track["binding_entity_id"] = "camera"
    section = track["sections"][0]
    section["ced_type"] = "camera.transform"
    if change == "wrong_binding":
        track["binding_entity_id"] = "prop"
    elif change == "missing_keys":
        section["payload"]["animation"]["curves"][0]["keys"] = []
    elif change == "fov_only":
        section["payload"]["animation"]["curves"][0]["canonical_semantic"] = "camera.fov"
    else:
        section["ced_type"] = "camera.cut"
    agent = FakeAgent()
    result = SourceEvidence(csir, MappingResources()).propose_track(agent, "prop-track")
    assert result.decision.status == "failed"
    assert result.decision.mapping_id is None
    assert not agent.calls


def test_scene_report_accounts_for_every_track_and_finding(csir):
    audio = copy.deepcopy(csir["tracks"][1])
    audio["track_id"] = "audio"
    audio["ced_type"] = "audio.track"
    audio["sections"][0]["section_id"] = "audio-section"
    audio["sections"][0]["ced_type"] = "audio.section"
    csir["tracks"].append(audio)
    source = SourceEvidence(csir, MappingResources())
    agent = FakeAgent()
    report = source.analyze_scene(agent)
    assert report["analysis_status"] == "COMPLETE"
    assert report["execution_authorized"] is False
    assert report["source_sha256"] == source.source_sha256
    assert report["source_counts"] == {"entities": 3, "assets": 1, "tracks": 4}
    assert report["decision_counts"] == {
        "proposed": 3, "unsupported": 1, "failed": 0, "not_analyzed": 0,
    }
    assert report["ced_preflight"] == source.report
    assert [row["track_id"] for row in report["tracks"]] == list(source.tracks)
    character = report["tracks"][0]["result"]
    assert character["eligible_mapping_ids"] == ["skeletal_animation"]
    assert len(character["mapping_evidence"]["candidates"]) == 2
    assert report["tracks"][-1]["result"]["eligible_mapping_ids"] == []
    assert len(agent.calls) == 3


def test_scene_report_stops_after_provider_failure(csir):
    class FailingAgent(FakeAgent):
        def select_mapping(self, feature, candidates):
            self.calls.append((feature, candidates))
            return MappingDecision("failed", None, "Local model inference failed: HTTP 500")

    source = SourceEvidence(csir, MappingResources())
    agent = FailingAgent()
    report = source.analyze_scene(agent)
    assert report["analysis_status"] == "INCOMPLETE"
    assert report["provider_failed"] is True
    assert report["execution_authorized"] is False
    assert report["decision_counts"] == {
        "proposed": 0, "unsupported": 0, "failed": 1, "not_analyzed": 2,
    }
    assert len(agent.calls) == 1
    assert [row["status"] for row in report["tracks"]] == [
        "failed", "not_analyzed", "not_analyzed",
    ]
    assert report["tracks"][1]["result"] is None
    assert report["ced_preflight"] == source.report


def test_scene_report_continues_after_source_evidence_failure(csir):
    csir["tracks"][0]["binding_entity_id"] = "missing"
    agent = FakeAgent()
    report = SourceEvidence(csir, MappingResources()).analyze_scene(agent)
    assert report["analysis_status"] == "COMPLETE"
    assert report["provider_failed"] is False
    assert report["decision_counts"]["failed"] == 1
    assert report["decision_counts"]["proposed"] == 2
    assert len(agent.calls) == 2


def test_scene_report_with_no_tracks_still_retains_audit(csir):
    csir["tracks"] = []
    source = SourceEvidence(csir, MappingResources())
    agent = FakeAgent()
    report = source.analyze_scene(agent)
    assert report["analysis_status"] == "COMPLETE"
    assert report["execution_authorized"] is False
    assert sum(report["decision_counts"].values()) == 0
    assert report["tracks"] == []
    assert report["ced_preflight"] == source.report
    assert not agent.calls


def test_scene_report_is_detached_from_source_audit(csir):
    source = SourceEvidence(csir, MappingResources())
    report = source.analyze_scene(FakeAgent())
    report["ced_preflight"]["findings"].clear()
    assert source.report["findings"]
    assert report["execution_authorized"] is False


@pytest.fixture
def handoff_files(csir, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    for part in ("integrations/unreal", "packages/cinetwin", "packages/studio"):
        monkeypatch.syspath_prepend(str(root / part))
    import transfer_backend

    csir = copy.deepcopy(csir)
    csir["tracks"] = [csir["tracks"][1]]
    csir["tracks"][0]["name"] = "Prop movement"
    csir["entities"] = [
        {"entity_id": "prop", "ced_type": "entity.prop", "name": "Prop"},
    ]
    csir["assets"] = []
    mapping = {
        "entities": {"Prop": {"actor_label": "PropUE"}},
        "assets": {},
        "sequence_asset_path": "/Game/Staging/LS_Test",
        "overwrite_sequence": False,
    }
    source = SourceEvidence(csir, MappingResources())
    report = source.analyze_scene(FakeAgent())
    paths = [tmp_path / name for name in ("source.json", "mapping.json", "analysis.json")]
    for path, data in zip(paths, (csir, mapping, report), strict=True):
        path.write_text(json.dumps(data), encoding="utf-8")
    return transfer_backend, paths, report


def test_ai_handoff_uses_existing_backend(handoff_files):
    backend, paths, report = handoff_files
    result = backend.inspect_ai_handoff(*paths)
    assert result["source_sha256"] == report["source_sha256"]
    assert result["execution_authorized"] is False
    assert result["behavioral_fidelity_established"] is False
    assert result["backend_actions"]["transform"] == 1
    assert result["tracks"][0]["ai_mapping_id"] == "transform"
    assert result["tracks"][0]["proposal_attributed"] is True
    assert result["tracks"][0]["backend_outcome"] != "SKIPPED"


@pytest.mark.parametrize(
    "change", ["hash", "mapping", "audit", "track", "authorization", "source"]
)
def test_ai_handoff_rejects_changed_evidence(handoff_files, change):
    backend, paths, report = handoff_files
    if change == "hash":
        report["catalog_sha256"] = "changed"
    elif change == "mapping":
        report["tracks"][0]["result"]["decision"]["mapping_id"] = "skeletal_animation"
    elif change == "audit":
        report["ced_preflight"]["findings"].clear()
    elif change == "track":
        report["tracks"][0]["track_id"] = "changed"
    elif change == "authorization":
        report["execution_authorized"] = True
    else:
        source = json.loads(paths[0].read_text(encoding="utf-8"))
        source["tracks"][0]["name"] = "Changed"
        paths[0].write_text(json.dumps(source), encoding="utf-8")
    paths[2].write_text(json.dumps(report), encoding="utf-8")
    expected_error = {
        "hash": "snapshot, resources or audit differ",
        "mapping": "not source-eligible",
        "audit": "snapshot, resources or audit differ",
        "track": "track identity differs",
        "authorization": "complete, advisory source analysis",
        "source": "decision or evidence differs",
    }
    with pytest.raises(backend.TransferBackendError, match=expected_error[change]):
        backend.inspect_ai_handoff(*paths)


def test_ai_candidate_binds_analysis_and_preserves_deterministic_plan(handoff_files, tmp_path):
    import prepared_transfer

    backend, paths, _ = handoff_files
    source, mapping, analysis = paths
    before = [path.read_bytes() for path in paths]
    legacy = tmp_path / "legacy"
    candidate = tmp_path / "ai"
    plain = prepared_transfer.prepare(source, mapping, legacy)
    session = prepared_transfer.prepare(source, mapping, candidate, analysis_path=analysis)
    assert "ai_analysis" not in plain
    assert session["session_id"] != plain["session_id"]
    assert session["ai_analysis"]["sha256"] == prepared_transfer._sha(analysis)
    assert session["stage"] == "AWAITING_UNREAL_PREFLIGHT"
    assert session["engine_generation_executed"] is False
    assert session["behavioral_fidelity_established"] is False
    assert prepared_transfer.verify(candidate) == session
    assert prepared_transfer.verify(legacy) == plain
    assert set(session["artifact_sha256"]) == set(plain["artifact_sha256"]) | {
        "ai-handoff.json"
    }
    for name in plain["artifact_sha256"]:
        assert (candidate / name).read_bytes() == (legacy / name).read_bytes()
    saved = json.loads((candidate / "ai-handoff.json").read_text(encoding="utf-8"))
    assert saved == backend.inspect_ai_handoff(*paths)
    assert saved["tracks"][0]["proposal_attributed"] is True
    assert saved["execution_authorized"] is False
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("change", [
    "analysis_bytes", "inspection_bytes", "inspection_rehashed",
    "detached_analysis", "missing_manifest_entry",
])
def test_ai_candidate_rejects_changed_evidence(handoff_files, tmp_path, change):
    import prepared_transfer

    _, paths, _ = handoff_files
    source, mapping, analysis = paths
    candidate = tmp_path / "ai"
    session = prepared_transfer.prepare(source, mapping, candidate, analysis_path=analysis)
    inspection_path = candidate / "ai-handoff.json"
    if change == "analysis_bytes":
        analysis.write_bytes(analysis.read_bytes() + b"\n")
        expected = "AI source analysis changed"
    elif change in {"inspection_bytes", "inspection_rehashed"}:
        inspection = json.loads(inspection_path.read_text(encoding="utf-8"))
        inspection["execution_authorized"] = True
        inspection_path.write_text(json.dumps(inspection), encoding="utf-8")
        expected = "Prepared artifact modified"
        if change == "inspection_rehashed":
            session["artifact_sha256"]["ai-handoff.json"] = prepared_transfer._sha(
                inspection_path
            )
            expected = "Prepared AI handoff differs"
    elif change == "detached_analysis":
        del session["ai_analysis"]
        expected = "Session identity mismatch"
    else:
        del session["artifact_sha256"]["ai-handoff.json"]
        expected = "artifact manifest"
    (candidate / "session.json").write_text(json.dumps(session), encoding="utf-8")
    with pytest.raises(prepared_transfer.PreparedTransferError, match=expected):
        prepared_transfer.verify(candidate)


def test_ai_candidate_rejects_unmatched_proposal_before_output(
    handoff_files, csir, tmp_path,
):
    import prepared_transfer

    _, paths, _ = handoff_files
    source_path, mapping_path, analysis_path = paths
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["entities"].append({
        "entity_id": "camera", "ced_type": "entity.camera", "name": "Camera",
    })
    source["tracks"].append(csir["tracks"][2])
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping["entities"] = {"Camera": {"actor_label": "CameraUE"}}
    report = SourceEvidence(source, MappingResources()).analyze_scene(FakeAgent())
    source_path.write_text(json.dumps(source), encoding="utf-8")
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    analysis_path.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "blocked"
    with pytest.raises(prepared_transfer.PreparedTransferError, match="matching backend action"):
        prepared_transfer.prepare(source_path, mapping_path, out, analysis_path=analysis_path)
    assert not out.exists()


def test_ai_candidate_rejects_invalid_analysis_before_output(handoff_files, tmp_path):
    import prepared_transfer

    backend, paths, report = handoff_files
    source, mapping, analysis = paths
    report["execution_authorized"] = True
    analysis.write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "blocked"
    with pytest.raises(backend.TransferBackendError, match="complete, advisory source analysis"):
        prepared_transfer.prepare(source, mapping, out, analysis_path=analysis)
    assert not out.exists()


def test_studio_candidate_command_prepares_and_verifies_saved_ai_report(
    handoff_files, tmp_path, monkeypatch, capsys,
):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "tools"))
    import studio_candidate

    _, paths, _ = handoff_files
    source, mapping, analysis = paths
    original = mapping.read_bytes()
    out = tmp_path / "command_candidate"
    result = studio_candidate.main([
        "--csir", str(source), "--mapping", str(mapping),
        "--analysis", str(analysis), "--sequence", "/Game/Staging/LS_Candidate",
        "--out", str(out),
    ])
    assert result == 0
    assert "Immutable verification passed." in capsys.readouterr().out
    session = studio_candidate.prepared_transfer.verify(out)
    assert session["ai_analysis"]["path"] == str(analysis.resolve())
    assert session["source_capture"] is None
    assert session["target"]["sequence_asset_path"] == "/Game/Staging/LS_Candidate"
    assert session["engine_generation_executed"] is False
    assert len(session["artifact_sha256"]) == 4
    assert mapping.read_bytes() == original


def test_studio_candidate_requires_capture_for_world_lock(
    handoff_files, tmp_path, monkeypatch,
):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "tools"))
    import studio_candidate

    _, paths, _ = handoff_files
    source, mapping, analysis = paths
    out = tmp_path / "blocked_candidate"
    with pytest.raises(ValueError, match="requires source CineTwin capture"):
        studio_candidate.prepare_candidate(
            source, mapping, None, "/Game/Staging/LS_Blocked", out,
            skeletal_root_world_lock=True, analysis_path=analysis,
        )
    assert not out.exists()
    assert not out.with_suffix(".mapping.json").exists()


@pytest.fixture
def bridge_ai_fixture(handoff_files, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "tools"))
    import studio_local_bridge as bridge

    from packages.studio import ollama_provider, transfer_agent

    _, paths, _ = handoff_files
    source, mapping, _ = paths
    target = tmp_path / "Test.uproject"
    target.write_text("{}", encoding="utf-8")
    work = tmp_path / "work"
    bridge.atomic_json(work / "connection.json", bridge.config_check({
        "csir": str(source),
        "mapping": str(mapping),
        "target_project": str(target),
        "level_path": "/Game/Staging/L_Test",
        "source_rights_confirmed": True,
    }))

    class LocalProvider:
        model = "fixture-model"

        def models(self):
            return (self.model,)

    agent = FakeAgent()
    monkeypatch.setattr(ollama_provider, "OllamaProvider", LocalProvider)
    monkeypatch.setattr(transfer_agent, "TransferAgent", lambda provider: agent)
    return bridge, work, agent


def test_studio_prepare_automatically_attaches_ai_analysis_and_blocks_execution(bridge_ai_fixture):
    bridge, work, agent = bridge_ai_fixture
    result = bridge.prepare(work, {"enable_ai_agent": True})
    assert len(agent.calls) == 1
    assert result["ai_analysis"]["decision_counts"]["proposed"] == 1
    assert result["ai_analysis"]["execution_enabled"] is False
    assert result["engine_generation_executed"] is False
    assert result["behavioral_fidelity_established"] is False
    assert result["prepared_options"] == {}
    candidate = Path(result["candidate_dir"])
    import prepared_transfer

    session = prepared_transfer.verify(candidate)
    assert Path(session["ai_analysis"]["path"]).is_file()
    assert len(session["artifact_sha256"]) == 4
    assert bridge.load_json(work / "active-candidate.json") == result
    with pytest.raises(ValueError, match="native execution is not enabled"):
        bridge.approve_one_click(result["candidate_id"], work)
    with pytest.raises(ValueError, match="native execution is not enabled"):
        bridge.queue_trial(result["candidate_id"], work)
    assert not (work / "active-job.json").exists()


def test_studio_ai_failure_preserves_report_without_preparing_candidate(bridge_ai_fixture, monkeypatch):
    bridge, work, agent = bridge_ai_fixture

    def fail(feature, candidates):
        return MappingDecision("failed", None, "Local model inference failed: fixture")

    monkeypatch.setattr(agent, "select_mapping", fail)
    with pytest.raises(ValueError, match="AI source analysis requires review"):
        bridge.prepare(work, {"enable_ai_agent": True})
    reports = list((work / "candidates").glob("*.source-analysis.json"))
    assert len(reports) == 1
    report = bridge.load_json(reports[0])
    assert report["provider_failed"] is True
    assert report["execution_authorized"] is False
    assert not (work / "active-candidate.json").exists()
    assert not list((work / "candidates").glob("*/session.json"))
    assert not (work / "active-job.json").exists()


@pytest.mark.parametrize("enabled", [False, "true"])
def test_studio_ai_opt_in_requires_boolean_and_does_not_infer_when_disabled(
    bridge_ai_fixture, enabled,
):
    bridge, work, agent = bridge_ai_fixture
    if enabled is False:
        result = bridge.prepare(work, {"enable_ai_agent": False})
        assert "ai_analysis" not in result
        assert not list((work / "candidates").glob("*.source-analysis.json"))
    else:
        with pytest.raises(TypeError, match="enable_ai_agent must be Boolean"):
            bridge.prepare(work, {"enable_ai_agent": enabled})
        assert not (work / "active-candidate.json").exists()
    assert not agent.calls


@pytest.mark.parametrize("mode", ["valid", "tampered", "legacy", "missing_setup"])
def test_editor_ai_verifier_in_fresh_isolated_python(handoff_files, tmp_path, mode):
    import prepared_transfer

    _, paths, _ = handoff_files
    source, mapping, analysis = paths
    candidate = tmp_path / "editor-replay"
    session = prepared_transfer.prepare(
        source, mapping, candidate,
        analysis_path=None if mode == "legacy" else analysis,
    )
    if mode == "tampered":
        report = candidate / "ai-handoff.json"
        report.write_bytes(report.read_bytes() + b"\n")
    before = {path: path.read_bytes() for path in [*paths, *candidate.iterdir()]}
    root = Path(__file__).resolve().parents[2]
    script = f"""
import sys
import importlib.abc
import socket

class NoEngineOrInference(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('langgraph', 'unreal'):
            raise ImportError('Unexpected engine or inference import: ' + fullname)
        return None

def no_network(*args, **kwargs):
    raise AssertionError('Replay must not make network requests')

sys.meta_path.insert(0, NoEngineOrInference())
socket.create_connection = no_network
socket.socket.connect = no_network
sys.path.insert(0, {str(root / "integrations" / "unreal")!r})
import studio_ai_verifier
args = ['--candidate', {str(candidate)!r}]
if {mode == "missing_setup"!r}:
    args.append('--require-setup')
raise SystemExit(studio_ai_verifier.main(args))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script], cwd=tmp_path,
        text=True, capture_output=True, check=False,
    )
    if mode == "valid":
        assert result.returncode == 0, result.stdout + result.stderr
        proof = json.loads(result.stdout)
        assert proof["status"] == "AI_EVIDENCE_REPLAY_VERIFIED"
        assert proof["session_id"] == session["session_id"]
        assert proof["proposed_mappings"] == proof["attributed_proposals"] == 1
        assert proof["backend_actions"]["transform"] == 1
        assert len(proof["artifact_sha256"]) == 4
        assert proof["automatic_setup"] is None
        assert proof["execution_authorized"] is False
        assert proof["engine_generation_executed"] is False
        assert proof["behavioral_fidelity_established"] is False
        assert "packages.studio.source_evidence" in proof["canonical_modules"]
    else:
        assert result.returncode == 2, result.stdout + result.stderr
        proof = json.loads(result.stderr)
        assert proof["status"] == "AI_EVIDENCE_REPLAY_BLOCKED"
        assert proof["execution_authorized"] is False
        expected = {
            "tampered": "Prepared artifact modified",
            "legacy": "Expected an AI-assisted",
            "missing_setup": "automatic-setup.json",
        }[mode]
        assert expected in proof["reason"]
    assert set(candidate.iterdir()) == {path for path in before if path.parent == candidate}
    assert all(path.read_bytes() == data for path, data in before.items())
