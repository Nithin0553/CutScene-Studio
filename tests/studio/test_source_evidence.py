"""Source-bound retrieval tests with schema-valid synthetic CSIR."""

import copy

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
        return MappingDecision("proposed", candidates[0].mapping_id, "Fixture proposal")


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
