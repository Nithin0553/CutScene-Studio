"""Bounded skeletal source timing and independent native duration measurements."""
from __future__ import annotations

import logging
import math

LOGGER = logging.getLogger(__name__)


class AnimationTimingError(ValueError):
    pass


def positive_number(value):
    if type(value) not in (int, float):
        raise TypeError("Animation timing must be numeric.")
    if not math.isfinite(value) or value <= 0:
        raise AnimationTimingError("Animation timing must be finite and positive.")
    return float(value)


def observed_length(animation):
    """No source-derived or fabricated native duration."""
    if animation is None:
        return None
    getter = getattr(animation, "get_play_length", None)
    if callable(getter):
        try:
            return positive_number(getter())
        except Exception:
            LOGGER.debug("Native animation duration getter unavailable", exc_info=True)
    try:
        return positive_number(animation.get_editor_property("sequence_length"))
    except Exception:
        LOGGER.debug("Native animation sequence length unavailable", exc_info=True)
        return None


def observed_rate_scale(animation):
    try:
        return positive_number(animation.get_editor_property("rate_scale"))
    except Exception:
        LOGGER.debug("Native animation rate scale unavailable", exc_info=True)
        return None


def required_interval(action, display_rate):
    """Check source interval and its independently quantized timeline interval."""
    start = action["source_start_seconds"]
    end = action["source_end_seconds"]
    offset = action["source_offset_seconds"]
    speed = positive_number(action["time_scale"])
    if any(type(value) not in (int, float) or not math.isfinite(value)
           for value in (start, end, offset)):
        raise AnimationTimingError("Invalid skeletal source interval.")
    if start < 0 or end <= start or abs(start - offset) > 1e-9:
        raise AnimationTimingError("Conflicting or invalid skeletal source trim.")
    fps = positive_number(display_rate["numerator"]) / positive_number(display_rate["denominator"])
    frames = action["end_frame"] - action["start_frame"]
    if frames <= 0:
        raise AnimationTimingError("Skeletal section is shorter than one display frame.")
    quantized_end = start + frames / fps * speed
    # Each rounded endpoint can contribute half a display frame.
    tolerance = speed / fps + 1e-6
    if abs(quantized_end - end) > tolerance:
        raise AnimationTimingError("Skeletal source and timeline intervals disagree.")
    return max(end, quantized_end), tolerance


def verify_imported_clip(action, display_rate, animation):
    required_end, tolerance = required_interval(action, display_rate)
    length = observed_length(animation)
    rate_scale = observed_rate_scale(animation)
    if length is None or rate_scale is None:
        raise AnimationTimingError("Imported animation timing could not be independently measured.")
    if abs(rate_scale - 1.0) > 1e-6:
        raise AnimationTimingError("Non-unit imported animation rate scale requires a dedicated adapter.")
    if action["source_start_seconds"] >= length or required_end > length + tolerance:
        raise AnimationTimingError(
            "Imported animation is too short for source interval; loop/extrapolation evidence required.")
    return {"required_source_end_seconds": required_end,
            "imported_duration_seconds": length, "asset_rate_scale": rate_scale}
