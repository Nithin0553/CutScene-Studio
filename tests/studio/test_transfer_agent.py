"""Single-agent graph tests; Ollama and game engines are not required."""

import pytest

from packages.studio.ollama_provider import InferenceResult, OllamaError
from packages.studio.transfer_agent import MappingCandidate, TransferAgent

CANDIDATES = (
    MappingCandidate("skeletal_animation", "animation.clip", "Skeletal animation track"),
    MappingCandidate("audio_track", "audio.track", "Audio track"),
)


class FakeProvider:
    def __init__(self, mapping_id="skeletal_animation", fail=False):
        self.mapping_id = mapping_id
        self.fail = fail
        self.calls = []

    def generate(self, prompt, schema):
        self.calls.append((prompt, schema))
        if self.fail:
            raise OllamaError("Local model unavailable")
        return InferenceResult({"mapping_id": self.mapping_id}, 1.9, 0.25, 0.2, 1.2, 12)


@pytest.fixture(autouse=True)
def require_langgraph():
    pytest.importorskip("langgraph.graph")


def test_selects_only_eligible_mapping():
    provider = FakeProvider()
    decision = TransferAgent(provider).select_mapping("animation.clip", CANDIDATES)
    assert decision.status == "proposed"
    assert decision.mapping_id == "skeletal_animation"
    assert decision.total_seconds == 1.9
    assert len(provider.calls) == 1
    prompt, schema = provider.calls[0]
    assert "audio_track" not in prompt
    assert schema["properties"]["mapping_id"]["enum"] == ["skeletal_animation", "unsupported"]


def test_no_eligible_candidates_skips_inference():
    provider = FakeProvider()
    decision = TransferAgent(provider).select_mapping("physics.collider", CANDIDATES)
    assert decision.status == "unsupported"
    assert decision.mapping_id is None
    assert not provider.calls


def test_model_can_abstain():
    provider = FakeProvider("unsupported")
    decision = TransferAgent(provider).select_mapping("animation.clip", CANDIDATES)
    assert decision.status == "unsupported"
    assert decision.mapping_id is None


@pytest.mark.parametrize("mapping_id", ["audio_track", "invented", None])
def test_rejects_invalid_model_decisions(mapping_id):
    provider = FakeProvider(mapping_id)
    decision = TransferAgent(provider).select_mapping("animation.clip", CANDIDATES)
    assert decision.status == "failed"
    assert decision.mapping_id is None


def test_inference_failure_is_not_unsupported():
    provider = FakeProvider(fail=True)
    decision = TransferAgent(provider).select_mapping("animation.clip", CANDIDATES)
    assert decision.status == "failed"
    assert decision.mapping_id is None
    assert decision.reason == "Local model inference failed: Local model unavailable"


def test_duplicate_ids_rejected():
    provider = FakeProvider()
    with pytest.raises(ValueError, match="duplicate"):
        TransferAgent(provider).select_mapping("animation.clip", (CANDIDATES[0], CANDIDATES[0]))
    assert not provider.calls


def test_reserved_id_rejected():
    provider = FakeProvider()
    with pytest.raises(ValueError, match="candidate"):
        TransferAgent(provider).select_mapping(
            "animation.clip", (MappingCandidate("unsupported", "animation.clip", "reserved"),)
        )
    assert not provider.calls


def test_repeated_calls_do_not_reuse_prior_decision():
    provider = FakeProvider()
    agent = TransferAgent(provider)
    assert agent.select_mapping("animation.clip", CANDIDATES).status == "proposed"
    assert agent.select_mapping("physics.collider", CANDIDATES).status == "unsupported"
    assert len(provider.calls) == 1
