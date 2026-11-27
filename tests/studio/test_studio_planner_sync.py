"""Regression: Unreal's long-lived Python VM must not use a cached 25-action
planner to verify a newly prepared 29-action adaptive CED candidate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "integrations" / "unreal" / "studio_planner_sync.py"
BUILDER = ROOT / "integrations" / "unreal" / "build_level_sequence.py"
WORKER = ROOT / "integrations" / "unreal" / "studio_local_editor_worker.py"


def test_stale_embedded_python_planner_is_reloaded_from_canonical_checkout():
    script = f"""
import sys
from pathlib import Path
root = Path({str(ROOT)!r})
sys.path.insert(0, str(root / 'integrations' / 'unreal'))
for sub in ('packages/studio', 'packages/cinetwin', 'packages/learning'):
    sys.path.insert(0, str(root / sub))
import transfer_backend
import prepared_transfer
import studio_planner_sync
old_compose = transfer_backend.compose_files
transfer_backend.compose_files = lambda *a, **k: (
    {{'actions':[{{'kind':'legacy'}}] * 25}}, {{}}, {{}}
)
prepared_transfer.verify = lambda _: 'STALE'
assert transfer_backend.compose_files(None, None)[0]['actions'][0]['kind'] == 'legacy'
loaded = studio_planner_sync.synchronize()
assert len(loaded) == len(studio_planner_sync.MODULES)
assert transfer_backend.compose_files is not old_compose
assert transfer_backend.compose_files.__module__ == 'transfer_backend'
assert prepared_transfer.verify.__module__ == 'prepared_transfer'
print('PLANNER_RELOADED')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PLANNER_RELOADED" in result.stdout


def test_verification_runs_sync_before_mutating_unreal_or_using_cached_modules():
    worker = WORKER.read_text(encoding="utf-8")
    builder = BUILDER.read_text(encoding="utf-8")
    assert "studio_planner_sync.synchronize()" in worker
    assert "studio_planner_sync.synchronize()" in builder
    assert worker.index("studio_planner_sync.synchronize()") < worker.index(
        "prepared_transfer.verify(candidate_dir)")
    assert worker.index("prepared_transfer.verify(candidate_dir)") < worker.index(
        "\n    _ensure_target_level(job)")
    assert builder.index("studio_planner_sync.synchronize()") < builder.index(
        "transfer_backend.compose_files(")
    assert "transfer_backend.verify_prepared_artifacts(" in builder


def test_source_hash_artifacts_are_not_modified_by_planner_sync():
    source = SYNC.read_text(encoding="utf-8")
    assert "ROOT = Path(__file__).resolve().parents[2]" in source
    assert "importlib.reload(existing)" in source
    assert "Path(actual_raw).resolve() != expected" in source
    for prohibited in (
        "unlink(", "write_text(", "write_bytes(", "open('w'", 'open("w"',
        "exec(", "eval(", "subprocess.", "unreal.",
    ):
        assert prohibited not in source



def test_stale_asset_inspector_reloads_without_losing_native_module_reference():
    """Regression: Studio host and long-lived Unreal must use identical adapters."""
    script = f"""
import sys
from pathlib import Path
root = Path({str(ROOT)!r})
sys.path.insert(0, str(root / 'integrations' / 'unreal'))
sys.path.insert(0, str(root / 'tools'))
import studio_auto_scene
import studio_auto_assets
import studio_source_identity
import studio_source_materials
import studio_planner_sync

# Simulate Unreal retaining cached old code after Studio/branch updates.
alias = studio_auto_scene.assets_plan
assert alias is studio_auto_assets
alias.inspect = lambda *a, **k: {{'actors': [{{'kind': 'old-point-light'}}]}}
studio_source_identity.resolve = lambda *a, **k: 'STALE'
studio_source_materials.candidates = lambda *a, **k: 'STALE'
assert alias.inspect()['actors'][0]['kind'] == 'old-point-light'
origins = studio_planner_sync.synchronize()
assert origins['studio_auto_assets'] == str(root / 'tools' / 'studio_auto_assets.py')
assert origins['studio_source_identity'] == str(root / 'tools' / 'studio_source_identity.py')
assert origins['studio_source_materials'] == str(root / 'tools' / 'studio_source_materials.py')
assert alias is studio_auto_scene.assets_plan
assert alias.verify.__module__ == 'studio_auto_assets'
assert alias.inspect.__module__ == 'studio_auto_assets'
assert studio_source_identity.resolve.__module__ == 'studio_source_identity'
assert studio_source_materials.candidates.__module__ == 'studio_source_materials'
print('ASSET_INSPECTOR_RELOADED')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ASSET_INSPECTOR_RELOADED" in result.stdout


def test_source_inspector_refresh_runs_before_native_setup_mutation():
    worker = WORKER.read_text(encoding="utf-8")
    sync = SYNC.read_text(encoding="utf-8")
    assert worker.index("studio_planner_sync.synchronize()") < worker.index(
        "studio_auto_scene.run("
    )
    assert sync.index('"studio_source_identity", "tools"') < sync.index(
        '"studio_auto_assets", "tools"'
    )
    assert sync.index('"studio_source_materials", "tools"') < sync.index(
        '"studio_auto_assets", "tools"'
    )



def test_auto_asset_manifest_preflight_precedes_any_unreal_level_creation():
    worker = WORKER.read_text(encoding="utf-8")
    start = worker.index("def _execute(job):")
    end = worker.index("def _update_destination_readiness():")
    segment = worker[start:end]
    assert segment.index("studio_planner_sync.synchronize()") < segment.index(
        "studio_auto_assets.verify("
    )
    assert segment.index("job['execution_stage'] = 'VERIFYING_SOURCE_ASSET_MANIFEST'") < segment.index(
        "studio_auto_assets.verify("
    )
    assert segment.index("studio_auto_assets.verify(") < segment.index(
        "_ensure_target_level(job)"
    )
    assert segment.index("_ensure_target_level(job)") < segment.index(
        "studio_auto_scene.run("
    )
    assert segment.index("studio_auto_scene.run(") < segment.index(
        "build_level_sequence.build_prepared_files("
    )


def test_worker_heartbeat_pins_running_python_code_not_current_disk_only():
    worker = WORKER.read_text(encoding="utf-8")
    assert "WORKER_PROTOCOL = 'studio-editor-v0.6'" in worker
    assert "WORKER_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()" in worker
    assert "'worker_source_sha256': WORKER_SOURCE_SHA256" in worker
    assert "'checkout_root': str(ROOT.resolve())" in worker
    assert "job['failure_stage'] = job.get('execution_stage'" in worker


@pytest.mark.parametrize("case", ["stale", "shadowed", "missing_dependency"])
def test_ai_replay_sync_in_isolated_python(tmp_path, case):
    script = f"""
import sys
import importlib.abc
from pathlib import Path
root = Path({str(ROOT)!r})
sys.path.insert(0, str(root / 'integrations/unreal'))
import studio_planner_sync as sync

case = {case!r}
if case == 'missing_dependency':
    class MissingSchema(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'jsonschema':
                raise ModuleNotFoundError('fixture: jsonschema unavailable')
            return None
    sys.meta_path.insert(0, MissingSchema())
    # Ordinary deterministic planner sync must not require AI dependencies.
    assert sync.synchronize()
    try:
        sync.synchronize_ai()
    except sync.PlannerSyncError as exc:
        assert 'jsonschema' in str(exc)
    else:
        raise AssertionError('Missing AI dependency was accepted')
else:
    sync.synchronize_ai()
    from packages.studio import source_evidence
    if case == 'stale':
        source_evidence.SourceEvidence = None
        origins = sync.synchronize_ai()
        assert source_evidence.SourceEvidence is not None
        assert origins['packages.studio.source_evidence'] == str(
            root / 'packages/studio/source_evidence.py'
        )
    else:
        source_evidence.__file__ = str(Path.cwd() / 'foreign.py')
        try:
            sync.synchronize_ai()
        except sync.PlannerSyncError as exc:
            assert 'shadowed packages.studio.source_evidence' in str(exc)
        else:
            raise AssertionError('Foreign replay module was accepted')
print('AI_SYNC_CHECKED')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script], cwd=tmp_path,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AI_SYNC_CHECKED" in result.stdout


def test_worker_checks_ai_replay_and_blocks_before_native_mutation():
    worker = WORKER.read_text(encoding="utf-8")
    segment = worker[worker.index("def _execute(job):"):]
    assert segment.index("studio_planner_sync.synchronize_ai()") < segment.index(
        "prepared_transfer.verify(candidate_dir)"
    ) < segment.index(
        "AI evidence verified; native AI execution is not enabled yet."
    ) < segment.index("\n    _ensure_target_level(job)")


@pytest.mark.parametrize("case", ["available", "isolated", "empty", "cached_foreign"])
def test_ai_dependency_bootstrap_is_local_and_fail_closed(tmp_path, case):
    script = f"""
import sys
from pathlib import Path
from types import ModuleType

root = Path({str(ROOT)!r})
sys.path.insert(0, str(root / 'integrations/unreal'))
import studio_planner_sync as sync

case = {case!r}
bundle = Path.cwd() / 'runtime-dependencies' / 'unreal-python311'
bundle.mkdir(parents=True)
sync._runtime_dependency_path = lambda: bundle
assert sync.find_spec('jsonschema') is None

if case == 'available':
    existing = Path.cwd() / 'existing'
    existing.mkdir()
    (existing / 'jsonschema.py').write_text('MARKER = 1')
    sys.path.insert(0, str(existing))
    assert sync.configure_ai_dependencies() is None
    assert str(bundle) not in sys.path
elif case == 'isolated':
    (bundle / 'jsonschema.py').write_text('MARKER = 2')
    assert sync.configure_ai_dependencies() == bundle.resolve()
    assert sys.path[0] == str(bundle.resolve())
    import jsonschema
    assert jsonschema.MARKER == 2
    assert sync.configure_ai_dependencies() is None
    assert sys.path.count(str(bundle.resolve())) == 1
else:
    if case == 'cached_foreign':
        (bundle / 'jsonschema.py').write_text('MARKER = 3')
        foreign = ModuleType('rpds')
        foreign.__file__ = str(Path.cwd() / 'foreign.py')
        sys.modules['rpds'] = foreign
    try:
        sync.configure_ai_dependencies()
    except sync.PlannerSyncError as exc:
        assert ('already loaded outside' if case == 'cached_foreign'
                else 'no usable jsonschema') in str(exc)
    else:
        raise AssertionError('Unsafe dependency bundle was accepted')
    assert str(bundle.resolve()) not in sys.path
    assert 'jsonschema' not in sys.modules
print('DEPENDENCY_BOOTSTRAP_CHECKED')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script], cwd=tmp_path,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DEPENDENCY_BOOTSTRAP_CHECKED" in result.stdout
