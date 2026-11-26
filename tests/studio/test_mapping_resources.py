"""Retrieval tests using the real versioned CED resources."""

import hashlib

import pytest

from packages.studio import ced_preflight, feature_dispatch
from packages.studio.mapping_resources import MappingResources
from packages.studio.transfer_agent import MappingDecision


@pytest.fixture
def resources():
    return MappingResources()


def test_animation_track_retrieves_registered_actions(resources):
    evidence = resources.retrieve("animation.track", "track")
    assert evidence.capability_state == "SUPPORTED_UNVERIFIED"
    assert {item.mapping_id for item in evidence.candidates} == {
        "transform", "skeletal_animation",
    }
    assert all(item.source_feature == "animation.track" for item in evidence.candidates)
    assert evidence.catalog_sha256 == hashlib.sha256(
        feature_dispatch.CATALOG_PATH.read_bytes()
    ).hexdigest()
    assert evidence.capabilities_sha256 == hashlib.sha256(
        ced_preflight.CAPABILITIES_PATH.read_bytes()
    ).hexdigest()


@pytest.mark.parametrize(
    ("feature", "kind", "state"),
    [
        ("audio.track", "track", "KNOWN_PARTIAL"),
        ("event.trigger", "section", "KNOWN_PARTIAL"),
        ("event.state", "track", "KNOWN_UNSUPPORTED"),
        ("physics.collider", "track", "KNOWN_UNSUPPORTED"),
        ("animation.clip", "track", "KNOWN_UNSUPPORTED"),
        ("not.registered", "track", "UNKNOWN_CED"),
        ("camera.fov", "track", "KNOWN_UNSUPPORTED"),
    ],
)
def test_strict_retrieval_does_not_widen_capabilities(resources, feature, kind, state):
    evidence = resources.retrieve(feature, kind)
    assert evidence.capability_state == state
    assert not evidence.candidates


def test_curve_retrieval_is_kind_specific(resources):
    evidence = resources.retrieve("camera.fov", "curve")
    assert evidence.capability_state == "SUPPORTED_UNVERIFIED"
    assert tuple(item.mapping_id for item in evidence.candidates) == ("camera_fov",)


def test_invalid_kind_rejected(resources):
    with pytest.raises(ValueError, match="source kind"):
        resources.retrieve("animation.clip", "asset")


def test_agent_receives_only_retrieved_candidates(resources):
    class FakeAgent:
        def select_mapping(self, feature, candidates):
            assert feature == "camera.cut"
            assert tuple(item.mapping_id for item in candidates) == ("camera_cut",)
            return MappingDecision("proposed", "camera_cut", "Test proposal")

    result = resources.propose(FakeAgent(), "camera.cut", "track")
    assert result.decision.mapping_id == "camera_cut"
    assert result.evidence.capability_state == "SUPPORTED_UNVERIFIED"


def test_blocked_feature_does_not_invoke_agent(resources):
    class FakeAgent:
        def select_mapping(self, feature, candidates):
            pytest.fail("Blocked features must not invoke the agent")

    result = resources.propose(FakeAgent(), "audio.track", "track")
    assert result.decision.status == "unsupported"
    assert result.evidence.capability_state == "KNOWN_PARTIAL"
    assert result.decision.mapping_id is None
