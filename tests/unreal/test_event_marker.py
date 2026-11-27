"""Display-rate marker adapter tests; no engine or gameplay execution."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/unreal"))
import event_marker


class MarkedFrame:
    def __init__(self):
        self.properties = {}

    def set_editor_property(self, name, value):
        self.properties[name] = value

    def get_editor_property(self, name):
        return self.properties[name]


class Sequence:
    def __init__(self):
        self.markers = []

    def add_marked_frame_to_sequence(self, marker, unit):
        assert unit == "display"
        self.markers.append(marker)
        return len(self.markers) - 1

    def get_marked_frames_from_sequence(self, unit):
        assert unit == "display"
        return self.markers


def native_api():
    return SimpleNamespace(
        LevelSequence=Sequence,
        MovieSceneMarkedFrame=MarkedFrame,
        FrameNumber=lambda value: SimpleNamespace(value=value),
        MovieSceneTimeUnit=SimpleNamespace(DISPLAY_RATE="display"),
    )


@pytest.mark.parametrize("route", ["direct", "extension"])
def test_marker_round_trip_retains_duplicate_annotations(route):
    api = native_api()
    sequence = Sequence()
    if route == "extension":
        api.MovieSceneSequenceExtensions = SimpleNamespace(
            add_marked_frame_to_sequence=lambda seq, marker, unit:
                seq.add_marked_frame_to_sequence(marker, unit),
            get_marked_frames_from_sequence=lambda seq, unit:
                seq.get_marked_frames_from_sequence(unit),
        )
    action = {"kind": "marker", "frame": 42, "label": "Cue"}
    event_marker.preflight([action], api)
    assert sequence.markers == []
    event_marker.add(sequence, action, api)
    event_marker.add(sequence, action, api)
    assert event_marker.read(sequence, api) == [
        {"frame": 42, "label": "Cue"}, {"frame": 42, "label": "Cue"}]


@pytest.mark.parametrize("action", [
    {"kind": "marker", "frame": -1, "label": "Cue"},
    {"kind": "marker", "frame": True, "label": "Cue"},
    {"kind": "marker", "frame": 4, "label": ""},
])
def test_invalid_marker_is_rejected_before_native_mutation(action):
    with pytest.raises(event_marker.MarkerError):
        event_marker.preflight([action], native_api())


def test_legacy_unqualified_marker_api_is_not_used():
    api = native_api()
    api.LevelSequence = SimpleNamespace(add_marked_frame=lambda marker: None)
    with pytest.raises(event_marker.MarkerError, match="Display-rate-aware"):
        event_marker.preflight([{"kind": "marker", "frame": 1, "label": "Cue"}], api)


def test_empty_native_marker_list_is_distinct_from_failed_probe():
    api = native_api()
    assert event_marker.read(Sequence(), api) == []
    assert event_marker.read(object(), api) is None


def test_failed_native_marker_insertion_is_not_success():
    api = native_api()
    sequence = Sequence()
    sequence.add_marked_frame_to_sequence = lambda marker, unit: -1
    with pytest.raises(event_marker.MarkerError, match="valid index"):
        event_marker.add(sequence, {"kind": "marker", "frame": 1, "label": "Cue"}, api)
