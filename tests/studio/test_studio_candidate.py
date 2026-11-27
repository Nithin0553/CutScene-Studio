"""Unique V9 trial preparation must never overwrite the original mapping or V8."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import studio_candidate


def test_candidate_copies_mapping_without_touching_original(tmp_path, monkeypatch):
    original = tmp_path / "original.json"
    original.write_text(json.dumps({
        "entities": {"CharacterA": {"actor_label": "CHARACTER_A"}},
        "assets": {}, "sequence_asset_path": "/Game/Test/LS_V8",
        "overwrite_sequence": False,
    }), encoding="utf-8")
    capture = tmp_path / "capture.json"
    capture.write_text("{}")
    csir = tmp_path / "source.json"
    csir.write_text("{}")
    original_contents = original.read_bytes()

    def fake_prepare(source, mapping, out, **kwargs):
        assert source == csir
        assert kwargs["capture_path"] == capture
        staged = json.loads(mapping.read_text())
        assert staged["sequence_asset_path"] == "/Game/Test/LS_V9"
        assert staged["overwrite_sequence"] is False
        assert staged["enable_cinetwin_skeletal_world_lock"] is True
        assert staged["entities"] == {"CharacterA": {"actor_label": "CHARACTER_A"}}
        out.mkdir()
        return {"track_coverage": {"NATIVE_PARTIAL": 1}}

    monkeypatch.setattr(studio_candidate.prepared_transfer, "prepare", fake_prepare)
    out = tmp_path / "V9_trial"
    mapping_copy, _session = studio_candidate.prepare_candidate(
        csir, original, capture, "/Game/Test/LS_V9", out,
        skeletal_root_world_lock=True,
    )
    assert mapping_copy.exists()
    assert original.read_bytes() == original_contents
    with pytest.raises(ValueError, match="reuse"):
        studio_candidate.prepare_candidate(
            csir, original, capture, "/Game/Test/LS_V9", out,
        )


def test_rejects_original_sequence_path_and_mapping_overwrite(tmp_path):
    original = tmp_path / "original.json"
    capture = tmp_path / "capture.json"
    capture.touch()
    original.write_text(json.dumps({
        "sequence_asset_path": "/Game/Level/Original",
        "overwrite_sequence": False,
    }))
    with pytest.raises(ValueError, match="original Level Sequence"):
        studio_candidate.prepare_candidate(
            tmp_path / "source", original, capture,
            "/Game/Level/Original", tmp_path / "trial",
        )
    original.write_text(json.dumps({
        "sequence_asset_path": "/Game/Level/Original",
        "overwrite_sequence": True,
    }))
    with pytest.raises(ValueError, match="overwrit"):
        studio_candidate.prepare_candidate(
            tmp_path / "source", original, capture,
            "/Game/Level/New", tmp_path / "trial",
        )


def test_candidate_import_prefers_real_backend_with_tools_first(tmp_path):
    # Reproduce the mixed-suite collection order in a fresh interpreter:
    # tools/ comes first while packages/studio is already on sys.path.
    code = """
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path[:0] = [
    str(root / 'tools'),
    str(root / 'packages/studio'),
    str(root / 'packages/cinetwin'),
    str(root / 'integrations/unreal'),
]
import studio_candidate
import transfer_backend
assert Path(transfer_backend.__file__).resolve() == (
    root / 'packages/studio/transfer_backend.py'
).resolve()
assert studio_candidate.prepared_transfer.transfer_backend is transfer_backend
assert callable(transfer_backend.compose_files)
assert callable(transfer_backend.compose_ai_handoff)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(ROOT)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_prepared_transfer_rejects_cached_shadowed_backend(tmp_path):
    code = """
import sys
from pathlib import Path
from types import ModuleType
root = Path(sys.argv[1])
sys.path[:0] = [
    str(root / 'tools'),
    str(root / 'packages/studio'),
    str(root / 'packages/cinetwin'),
    str(root / 'integrations/unreal'),
]
shadow = ModuleType('transfer_backend')
shadow.__file__ = str(root / 'tools/transfer_backend.py')
sys.modules['transfer_backend'] = shadow
try:
    import prepared_transfer
except ImportError as exc:
    assert 'Shadowed transfer_backend module' in str(exc)
else:
    raise AssertionError('Cached CLI module was accepted as the planner')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(ROOT)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
