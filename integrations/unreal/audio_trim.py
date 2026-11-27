"""Audio source trim contract for Sequencer's native tick-resolution offsets.

No engine import, inference, mutation at preflight, or pitch-based time scaling.
"""
from __future__ import annotations

import logging
import math

LOGGER = logging.getLogger(__name__)


class AudioTrimError(ValueError):
    pass


def source_offset(action):
    try:
        seconds = float(action.get("source_offset_seconds", 0.0))
        speed = float(action.get("time_scale", 1.0))
    except (TypeError, ValueError) as exc:
        raise AudioTrimError("Invalid audio source timing.") from exc
    if not math.isfinite(seconds) or seconds < 0:
        raise AudioTrimError("Audio source offset must be finite and nonnegative.")
    if speed != 1.0:
        raise AudioTrimError("Non-unit audio playback speed requires a dedicated time-scale adapter.")
    return seconds


def preflight(actions, api):
    """Check action values and reflected API before any editor mutation."""
    for action in actions:
        if action.get("kind") != "audio" or not source_offset(action):
            continue
        section = getattr(api, "MovieSceneAudioSection", None)
        sequence = getattr(api, "MovieSceneSequenceExtensions", None)
        if not all(callable(method) for method in (
            getattr(section, "set_start_offset", None),
            getattr(section, "get_start_offset", None),
            getattr(sequence, "get_tick_resolution", None),
            getattr(api, "FrameNumber", None),
        )):
            raise AudioTrimError("Native audio trim API unavailable; no transfer permitted.")


def tick_resolution(sequence, api):
    rate = api.MovieSceneSequenceExtensions.get_tick_resolution(sequence)
    numerator, denominator = rate.numerator, rate.denominator
    if type(numerator) is not int or type(denominator) is not int:
        raise TypeError("Native audio tick resolution must use integer fields.")
    if numerator <= 0 or denominator <= 0:
        raise AudioTrimError("Native audio tick resolution must be positive.")
    return {"numerator": numerator, "denominator": denominator}


def offset_ticks(seconds, rate):
    ticks = round(seconds * rate["numerator"] / rate["denominator"])
    if not 0 <= ticks <= 2147483647:
        raise AudioTrimError("Audio trim exceeds native FrameNumber range.")
    if seconds > 0 and ticks == 0:
        raise AudioTrimError("Audio trim is below native tick resolution.")
    return ticks


def read_ticks(section):
    try:
        value = section.get_start_offset()
        raw = value if type(value) is int else value.value
        if type(raw) is int and raw >= 0:
            return raw
    except Exception:
        LOGGER.debug("Native audio trim measurement unavailable", exc_info=True)
    return None


def apply(section, sequence, action, api):
    seconds = source_offset(action)
    if not seconds:
        return
    rate = tick_resolution(sequence, api)
    ticks = offset_ticks(seconds, rate)
    section.set_start_offset(api.FrameNumber(ticks))
    if read_ticks(section) != ticks:
        raise AudioTrimError("Native audio trim setter did not preserve the requested ticks.")
