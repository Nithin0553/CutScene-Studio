"""Software-only native audio trim contract with a reflected API test double."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/unreal"))
import audio_trim


class Section:
    def __init__(self):
        self.offset = 0

    def set_start_offset(self, value):
        self.offset = value.value

    def get_start_offset(self):
        return SimpleNamespace(value=self.offset)


def api():
    return SimpleNamespace(
        MovieSceneAudioSection=Section,
        FrameNumber=lambda value: SimpleNamespace(value=value),
        MovieSceneSequenceExtensions=SimpleNamespace(
            get_tick_resolution=lambda sequence: SimpleNamespace(numerator=24000, denominator=1)),
    )


def test_trim_uses_native_ticks_and_reads_back_without_loading_editor():
    section = Section()
    action = {"kind": "audio", "source_offset_seconds": 0.125}
    fake = api()
    audio_trim.preflight([action], fake)
    assert section.offset == 0
    audio_trim.apply(section, object(), action, fake)
    assert section.offset == 3000
    assert audio_trim.read_ticks(section) == 3000


@pytest.mark.parametrize("missing", ["MovieSceneAudioSection", "FrameNumber",
                                    "MovieSceneSequenceExtensions"])
def test_trim_preflight_refuses_missing_native_api(missing):
    fake = api()
    delattr(fake, missing)
    with pytest.raises(audio_trim.AudioTrimError, match="API unavailable"):
        audio_trim.preflight([{"kind": "audio", "source_offset_seconds": 0.5}], fake)


def test_trim_zero_needs_no_extra_native_api():
    audio_trim.preflight([{"kind": "audio"}], object())


def test_trim_refuses_incorrect_native_setter_readback():
    section = Section()
    section.set_start_offset = lambda value: None
    with pytest.raises(audio_trim.AudioTrimError, match="did not preserve"):
        audio_trim.apply(section, object(), {"source_offset_seconds": 0.5}, api())


@pytest.mark.parametrize("seconds", [1e-10, 1e8])
def test_trim_rejects_unrepresentable_native_frame_number(seconds):
    with pytest.raises(audio_trim.AudioTrimError):
        audio_trim.offset_ticks(seconds, {"numerator": 24000, "denominator": 1})


def test_trim_unavailable_native_measurement_is_not_zero():
    assert audio_trim.read_ticks(object()) is None
