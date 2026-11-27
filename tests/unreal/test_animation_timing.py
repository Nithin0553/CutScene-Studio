"""Native animation timing contract tests without Unreal Editor."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/unreal"))
import animation_timing as timing


def action():
    return {"source_start_seconds": 0.5, "source_end_seconds": 2.5,
            "source_offset_seconds": 0.5, "time_scale": 2.0,
            "start_frame": 24, "end_frame": 48}


def asset(length=3.0, rate=1.0):
    return SimpleNamespace(get_editor_property=lambda name:
                           {"sequence_length": length, "rate_scale": rate}[name])


def test_trim_and_playback_rate_fit_actual_imported_clip():
    result = timing.verify_imported_clip(action(), {"numerator": 24, "denominator": 1}, asset())
    assert result["required_source_end_seconds"] == 2.5
    assert result["imported_duration_seconds"] == 3
    assert result["asset_rate_scale"] == 1


@pytest.mark.parametrize("length,rate", [(1.0, 1.0), (0.0, 1.0), (None, 1.0),
                                         (3.0, 2.0), (3.0, None), (float("nan"), 1.0)])
def test_incompatible_or_unavailable_native_timing_blocks(length, rate):
    with pytest.raises(timing.AnimationTimingError):
        timing.verify_imported_clip(action(), {"numerator": 24, "denominator": 1},
                                    asset(length, rate))


@pytest.mark.parametrize("update", [
    {"source_start_seconds": -1}, {"source_offset_seconds": 0},
    {"source_end_seconds": 4}, {"time_scale": 0}, {"end_frame": 24},
])
def test_malformed_or_conflicting_plan_timing_is_rejected(update):
    with pytest.raises(timing.AnimationTimingError):
        timing.required_interval({**action(), **update}, {"numerator": 24, "denominator": 1})


def test_duration_getter_fallback_uses_native_property():
    animation = asset()

    def unavailable():
        raise RuntimeError("Native method unavailable")

    animation.get_play_length = unavailable
    assert timing.observed_length(animation) == 3.0
    assert timing.observed_length(None) is None
