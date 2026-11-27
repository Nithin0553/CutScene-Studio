import copy
import sys
from pathlib import Path

import pytest

VALIDATION_DIR = Path(__file__).resolve().parents[2] / "packages" / "validation"
sys.path.insert(0, str(VALIDATION_DIR))

import core


def _snapshot() -> dict:
    return {
        "schema_version": "0.1.0",
        "engine": {"name": "unreal", "version": "test"},
        "sequence_asset_path": "/Game/CutSceneAI/Benchmark001/LS_Benchmark001",
        "display_rate": {"numerator": 60, "denominator": 1},
        "playback": {"start_frame": 0, "end_frame": 600},
        "bindings": [
            {
                "name": "Floor",
                "binding_id": "floor",
                "canonical_world_transform": {
                    "position_m": [0.0, -0.1, -5.0],
                    "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                    "scale_xyz": [8.0, 0.2, 12.0],
                },
                "tracks": [],
            },
            {
                "name": "CHARACTER_Guard",
                "binding_id": "guard",
                "tracks": [
                    {
                        "kind": "skeletal_animation",
                        "start_frame": 0,
                        "end_frame": 195,
                        "asset_path": "/Game/CutSceneAI/Benchmark001/Animations/A_CatwalkWalkTurn180",
                        "post_roll_frames": 405,
                        "play_rate": 1.0,
                        "effective_root_delta_cm": [-150.0, 0.0, 0.0],
                        "root_motion_source_profile": {
                            "horizontal_end_distance_cm": 150.0,
                            "vertical_net_displacement_cm": 0.0,
                            "vertical_excursion_cm": 2.5,
                            "sample_count": 40.0,
                        },
                    }
                ],
            },
            {
                "name": "MOVING_PROP",
                "binding_id": "prop",
                "tracks": [
                    {
                        "kind": "transform",
                        "keys": [
                            {
                                "frame": 120,
                                "position_m": [-2.0, 0.5, -5.0],
                                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                            },
                            {
                                "frame": 420,
                                "position_m": [2.0, 0.5, -5.0],
                                "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                            },
                        ],
                    }
                ],
            },
            {
                "name": "CAM_A_Wide",
                "binding_id": "cam-a",
                "camera_state": {
                    "vertical_fov_degrees": 60.0,
                    "target_output_aspect": 16.0 / 9.0,
                },
                "tracks": [],
            },
            {
                "name": "CAM_B_Close",
                "binding_id": "cam-b",
                "camera_state": {
                    "vertical_fov_degrees": 35.0,
                    "target_output_aspect": 16.0 / 9.0,
                },
                "tracks": [
                    {
                        "kind": "camera_lens",
                        "keys": [
                            {"frame": 300, "vertical_fov_degrees": 35.0},
                            {"frame": 599, "vertical_fov_degrees": 25.0},
                        ],
                    }
                ],
            },
        ],
        "camera_cuts": [
            {"start_frame": 0, "end_frame": 300, "camera_binding": "CAM_A_Wide"},
            {"start_frame": 300, "end_frame": 600, "camera_binding": "CAM_B_Close"},
        ],
        "audio_sections": [
            {
                "start_frame": 298,
                "end_frame": 600,
                "asset_path": "/Game/CutSceneAI/Benchmark001/Audio/A_Ominous",
                "loop": False,
            }
        ],
        "markers": [{"frame": 390, "label": "Benchmark_Event_01"}],
    }


def test_exact_readback_passes_all_validation_layers() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actual["engine"]["version"] = "5.8.3"

    report = core.compare(expected, actual)

    assert report["status"] == "PASS"
    assert report["summary"]["failed"] == 0
    assert report["summary"]["incomplete"] == 0


def test_camera_cut_regression_fails() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actual["camera_cuts"][1]["start_frame"] = 301

    report = core.compare(expected, actual)

    assert report["status"] == "FAIL"
    failed_ids = {item["id"] for item in report["checks"] if item["status"] == "FAIL"}
    assert "camera.cuts" in failed_ids


def test_missing_root_motion_measurement_is_incomplete_not_false_pass() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    del actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"]

    report = core.compare(expected, actual)

    assert report["status"] == "INCOMPLETE"
    item = next(check for check in report["checks"] if check["id"] == "animation.root_motion.CHARACTER_Guard")
    assert item["status"] == "INCOMPLETE"


def test_root_motion_subcentimeter_import_difference_passes_semantic_gate() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        -150.02,
        0.01,
        0.39,
    ]

    report = core.compare(expected, actual)

    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )
    assert item["status"] == "PASS"
    assert item["actual"]["metrics"]["horizontal_endpoint_error_cm"] < 0.5


def test_root_motion_wrong_direction_still_fails() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        150.0,
        0.0,
        0.0,
    ]

    report = core.compare(expected, actual)

    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )
    assert item["status"] == "FAIL"
    assert item["actual"]["metrics"]["direction_error_degrees"] > 179.0


def test_root_motion_large_endpoint_drift_fails() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        -148.0,
        0.0,
        0.0,
    ]

    report = core.compare(expected, actual)

    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )
    assert item["status"] == "FAIL"
    assert item["actual"]["metrics"]["horizontal_endpoint_error_cm"] > 0.5


def test_grounded_root_motion_allows_small_vertical_import_baseline_difference() -> None:
    expected = _snapshot()
    expected_track = expected["bindings"][1]["tracks"][0]
    expected_track["effective_root_delta_cm"] = [
        -143.279836831084,
        9.377430092622522,
        -0.3940307787440145,
    ]
    expected_track["root_motion_source_profile"] = {
        "horizontal_end_distance_cm": 143.586393,
        "vertical_net_displacement_cm": -0.3940307787440145,
        "vertical_excursion_cm": 2.565968,
        "sample_count": 75.0,
    }

    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        -143.2968983194817,
        9.378550322968488,
        -1.0808486938476562,
    ]

    report = core.compare(expected, actual)
    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )

    assert item["status"] == "PASS"
    assert item["actual"]["policy"]["mode"] == "grounded_low_vertical_excursion"
    assert item["actual"]["metrics"]["horizontal_endpoint_error_cm"] < 0.02
    assert item["actual"]["metrics"]["vertical_error_cm"] < 1.0


def test_negligible_root_drift_ignores_direction_and_relative_error() -> None:
    expected = _snapshot()
    expected_track = expected["bindings"][1]["tracks"][0]
    expected_track["effective_root_delta_cm"] = [-0.18, -0.24, -0.005]
    expected_track["root_motion_source_profile"] = {
        "horizontal_end_distance_cm": 0.30,
        "vertical_net_displacement_cm": -0.005,
        "vertical_excursion_cm": 6.0,
        "sample_count": 31.0,
    }

    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        0.28,
        -0.15,
        -0.018,
    ]

    report = core.compare(expected, actual)
    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )

    assert item["status"] == "PASS"
    assert item["actual"]["policy"]["mode"] == "negligible_horizontal_root_drift"
    assert item["actual"]["metrics"]["direction_error_degrees"] > 90.0
    assert item["actual"]["metrics"]["horizontal_endpoint_error_cm"] < 0.5


def test_small_idle_root_drift_uses_absolute_endpoint_error() -> None:
    expected = _snapshot()
    expected_track = expected["bindings"][1]["tracks"][0]
    expected_track["effective_root_delta_cm"] = [0.20, -4.60, 0.24]
    expected_track["root_motion_source_profile"] = {
        "horizontal_end_distance_cm": 4.60,
        "vertical_net_displacement_cm": 0.24,
        "vertical_excursion_cm": 0.24,
        "sample_count": 17.0,
    }

    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        0.52,
        -4.83,
        0.28,
    ]

    report = core.compare(expected, actual)
    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )

    assert item["status"] == "PASS"
    assert item["actual"]["policy"]["mode"] == "negligible_horizontal_root_drift"
    assert item["actual"]["metrics"]["horizontal_distance_relative_error"] > 0.05
    assert item["actual"]["metrics"]["horizontal_endpoint_error_cm"] < 0.5


def test_long_walk_with_small_relative_vertical_excursion_is_grounded() -> None:
    expected = _snapshot()
    expected_track = expected["bindings"][1]["tracks"][0]
    expected_track["effective_root_delta_cm"] = [-329.86, 0.0, -0.48]
    expected_track["root_motion_source_profile"] = {
        "horizontal_end_distance_cm": 329.86,
        "vertical_net_displacement_cm": -0.48,
        "vertical_excursion_cm": 5.08,
        "sample_count": 43.0,
    }

    actual = copy.deepcopy(expected)
    actual["bindings"][1]["tracks"][0]["effective_root_delta_cm"] = [
        -329.90,
        0.01,
        -0.30,
    ]

    report = core.compare(expected, actual)
    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )

    assert item["status"] == "PASS"
    assert item["actual"]["policy"]["mode"] == "grounded_low_vertical_excursion"
    assert item["actual"]["policy"]["vertical_excursion_relative"] < 0.02


def test_material_vertical_excursion_requires_sampled_trajectory_validation() -> None:
    expected = _snapshot()
    expected["bindings"][1]["tracks"][0]["root_motion_source_profile"] = {
        "horizontal_end_distance_cm": 120.0,
        "vertical_net_displacement_cm": 0.0,
        "vertical_excursion_cm": 85.0,
        "sample_count": 80.0,
    }
    actual = copy.deepcopy(expected)

    report = core.compare(expected, actual)
    item = next(
        check for check in report["checks"]
        if check["id"] == "animation.root_motion.CHARACTER_Guard"
    )

    assert item["status"] == "INCOMPLETE"
    assert item["actual"]["policy"]["mode"] == "requires_sampled_vertical_trajectory"


def test_light_intensity_track_is_not_silently_ignored() -> None:
    expected = _snapshot()
    expected["bindings"].append({
        "name": "LIGHT_KEY",
        "binding_id": "light",
        "tracks": [{"kind": "light_intensity", "keys": [
            {"frame": 0, "value": 1.0},
            {"frame": 24, "value": 2.0},
        ]}],
    })
    actual = copy.deepcopy(expected)
    actual["bindings"][-1]["tracks"][0]["keys"][-1]["value"] = 5.0
    report = core.compare(expected, actual)
    failed = {check["id"] for check in report["checks"] if check["status"] == "FAIL"}
    assert "light.intensity_keys.LIGHT_KEY" in failed


def test_skeletal_source_trim_and_easing_are_readback_gates() -> None:
    expected = _snapshot()
    track = expected["bindings"][1]["tracks"][0]
    track["source_offset_seconds"] = 0.5
    track["ease_in_frames"] = 6
    track["ease_out_frames"] = 12
    actual = copy.deepcopy(expected)
    actual_track = actual["bindings"][1]["tracks"][0]
    actual_track["source_offset_seconds"] = 0.0
    actual_track["ease_in_frames"] = 0
    actual_track["ease_out_frames"] = 0
    report = core.compare(expected, actual)
    failed = {check["id"] for check in report["checks"] if check["status"] == "FAIL"}
    assert {
        "animation.source_offset_seconds.CHARACTER_Guard",
        "animation.ease_in_frames.CHARACTER_Guard",
        "animation.ease_out_frames.CHARACTER_Guard",
    } <= failed



def test_partially_keyed_static_pose_verifies_position_and_rotation_only() -> None:
    """Saved Sequencer keys prove 6-DOF, not unkeyed scale or full fidelity."""
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actor = actual["bindings"][0]
    actor["canonical_world_transform"] = {
        "position_m": [0.000000001, -0.1, -5.0],
        "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
    }
    actor["canonical_world_transform_provenance"] = (
        "saved_sequence_single_frame_world_transform_key"
    )
    report = core.compare(expected, actual)
    checks = {item["id"]: item for item in report["checks"]}
    assert checks["spatial.position.Floor"]["status"] == "PASS"
    assert checks["spatial.rotation.Floor"]["status"] == "PASS"
    assert checks["spatial.scale.Floor"]["status"] == "INCOMPLETE"
    assert report["status"] == "INCOMPLETE"
    assert report["summary"]["failed"] == 0


def test_invalid_or_missing_static_vector_cannot_be_reported_as_pass() -> None:
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    actual["bindings"][0]["canonical_world_transform"] = {
        "position_m": [],
        "rotation_xyzw": [float("nan"), 0.0, 0.0, 1.0],
        "scale_xyz": [8.0, 0.2, 12.0],
    }
    report = core.compare(expected, actual)
    checks = {item["id"]: item for item in report["checks"]}
    assert checks["spatial.position.Floor"]["status"] == "INCOMPLETE"
    assert checks["spatial.rotation.Floor"]["status"] == "INCOMPLETE"
    assert checks["spatial.scale.Floor"]["status"] == "PASS"
    assert report["status"] == "INCOMPLETE"


@pytest.mark.parametrize("case,expected_status", [
    ("matching", "PASS"), ("lost_fade", "FAIL"), ("missing_api", "INCOMPLETE"),
    ("duplicate_match", "PASS"), ("duplicate_reuse", "FAIL"),
    ("crossed_pairs", "FAIL"), ("unexpected_extra", "FAIL"),
])
def test_audio_easing_requires_independent_occurrence_readback(case, expected_status):
    expected = _snapshot()
    first = expected["audio_sections"][0]
    first.update(ease_in_frames=12, ease_out_frames=24)
    if case.startswith("duplicate") or case == "crossed_pairs":
        expected["audio_sections"].append({**first, "ease_in_frames": 6, "ease_out_frames": 8})
    actual = copy.deepcopy(expected)
    observed = actual["audio_sections"]
    if case == "lost_fade":
        observed[0]["ease_in_frames"] = 0
    elif case == "missing_api":
        observed[0]["ease_out_frames"] = None
    elif case == "duplicate_match":
        observed.reverse()
    elif case == "duplicate_reuse":
        observed[1] = observed[0].copy()
    elif case == "crossed_pairs":
        observed[0]["ease_out_frames"], observed[1]["ease_out_frames"] = (
            observed[1]["ease_out_frames"], observed[0]["ease_out_frames"])
    elif case == "unexpected_extra":
        observed.append(observed[0].copy())
    report = core.compare(expected, actual)
    easing = next(item for item in report["checks"] if item["id"].startswith("audio.easing."))
    assert easing["status"] == expected_status
    assert report["status"] == expected_status


@pytest.mark.parametrize("case,expected_status", [
    ("match", "PASS"), ("wrong", "FAIL"), ("missing", "INCOMPLETE"),
    ("no_rate", "INCOMPLETE"), ("duplicate_swapped", "FAIL"),
])
def test_audio_source_trim_uses_native_ticks_and_occurrence_identity(case, expected_status):
    expected = _snapshot()
    first = expected["audio_sections"][0]
    first.update(source_offset_seconds=0.5)
    if case == "duplicate_swapped":
        first.update(ease_in_frames=2, ease_out_frames=4)
        expected["audio_sections"].append({
            **first, "source_offset_seconds": 0.25, "ease_in_frames": 8})
    actual = copy.deepcopy(expected)
    actual["audio_tick_resolution"] = {"numerator": 24000, "denominator": 1}
    observed = actual["audio_sections"]
    observed[0]["source_offset_ticks"] = 12000
    if case == "wrong":
        observed[0]["source_offset_ticks"] = 12
    elif case == "missing":
        observed[0]["source_offset_ticks"] = None
    elif case == "no_rate":
        actual.pop("audio_tick_resolution")
    elif case == "duplicate_swapped":
        observed[0]["source_offset_ticks"] = 6000
        observed[1]["source_offset_ticks"] = 12000
    result = core.compare(expected, actual)
    trim = next(row for row in result["checks"] if row["id"].startswith("audio.source_trim."))
    assert trim["status"] == expected_status
    assert result["status"] == expected_status


@pytest.mark.parametrize("case,status", [
    ("unknown_empty", "INCOMPLETE"), ("unknown_expected", "INCOMPLETE"),
    ("missing", "FAIL"), ("duplicate", "FAIL"), ("exact", "PASS"),
])
def test_marker_annotation_readback_distinguishes_unavailable_from_empty(case, status):
    expected = _snapshot()
    actual = copy.deepcopy(expected)
    if case == "unknown_empty":
        expected["markers"] = []
    if case.startswith("unknown"):
        actual["markers_readback_complete"] = False
        actual["markers"] = []
    elif case == "missing":
        actual["markers"] = []
        actual["markers_readback_complete"] = True
    elif case == "duplicate":
        actual["markers"].append(actual["markers"][0].copy())
    result = core.compare(expected, actual)
    row = next(item for item in result["checks"] if item["id"] == "event.markers")
    assert row["status"] == status
