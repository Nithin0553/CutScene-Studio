"""Native marked-frame adapter; markers are annotations, never callbacks."""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


class MarkerError(ValueError):
    pass


def _method(api, owner, name):
    method = getattr(getattr(api, "MovieSceneSequenceExtensions", None), name, None)
    if callable(method):
        return method, True
    method = getattr(owner, name, None)
    if callable(method):
        return method, False
    raise MarkerError("Display-rate-aware marker API unavailable: " + name)


def _time_unit(api):
    unit = getattr(getattr(api, "MovieSceneTimeUnit", None), "DISPLAY_RATE", None)
    if unit is None:
        raise MarkerError("Native display-rate marker time unit unavailable.")
    return unit


def preflight(actions, api):
    """Reject unsupported native marker APIs before mutation."""
    for action in actions:
        if action.get("kind") != "marker":
            continue
        frame, label = action.get("frame"), action.get("label")
        if type(frame) is not int or not 0 <= frame <= 2147483647:
            raise MarkerError("Invalid marker display frame.")
        if not isinstance(label, str) or not label.strip():
            raise MarkerError("Missing marker identity.")
        _time_unit(api)
        if not callable(getattr(api, "MovieSceneMarkedFrame", None)):
            raise MarkerError("Native marked-frame type unavailable.")
        if not callable(getattr(api, "FrameNumber", None)):
            raise MarkerError("Native frame-number type unavailable.")
        owner = getattr(api, "LevelSequence", None)
        for name in ("add_marked_frame_to_sequence", "get_marked_frames_from_sequence"):
            _method(api, owner, name)


def add(sequence, action, api):
    """Use the explicit display-rate API, never the ambiguous legacy method."""
    preflight([action], api)
    marked = api.MovieSceneMarkedFrame()
    marked.set_editor_property("frame_number", api.FrameNumber(action["frame"]))
    marked.set_editor_property("label", action["label"])
    method, extension = _method(api, sequence, "add_marked_frame_to_sequence")
    unit = _time_unit(api)
    index = method(sequence, marked, unit) if extension else method(marked, unit)
    if type(index) is not int or index < 0:
        raise MarkerError("Native marker insertion did not return a valid index.")


def read(sequence, api):
    """Return observed marker records, or None when measurement is unavailable."""
    try:
        method, extension = _method(api, sequence, "get_marked_frames_from_sequence")
        unit = _time_unit(api)
        frames = method(sequence, unit) if extension else method(unit)
        result = []
        for marked in frames:
            number = marked.get_editor_property("frame_number")
            frame = number if type(number) is int else number.value
            label = marked.get_editor_property("label")
            if type(frame) is not int or not isinstance(label, str):
                raise MarkerError("Invalid native marker readback.")
            result.append({"frame": frame, "label": label})
        return result
    except Exception:
        LOGGER.debug("Native marked-frame measurement unavailable", exc_info=True)
        return None
