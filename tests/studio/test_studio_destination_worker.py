"""Verify actual editor snapshot is used before generating Unreal sequence."""
import importlib.util
import json
import sys

import pytest
from pathlib import Path
from types import SimpleNamespace

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'integrations/unreal/studio_local_editor_worker.py').exists())


def test_worker_reports_missing_mapped_actors_without_modifying_scene(tmp_path, monkeypatch):
    class Skel: pass
    class Cam: pass
    class Actor:
        def get_actor_label(self): return 'CSAI_Old_CAM_A_Wide'
        def get_class(self): return SimpleNamespace(get_name=lambda:'CineCameraActor')
        def get_component_by_class(self, component):
            return object() if component == Cam else None
    class World:
        def get_path_name(self): return '/Game/Tests/L_Test.L_Test'
    class EditorActorSubsystem:
        def get_all_level_actors(self): return [Actor()]
    class UnrealEditorSubsystem:
        def get_editor_world(self): return World()
    class Assets:
        @staticmethod
        def does_asset_exist(path): return path=='/Game/Assets/Anim'
    fake = SimpleNamespace(
        SkeletalMeshComponent=Skel, CineCameraComponent=Cam,
        EditorAssetLibrary=Assets, EditorActorSubsystem=EditorActorSubsystem,
        UnrealEditorSubsystem=UnrealEditorSubsystem,
        get_editor_subsystem=lambda klass: klass(),
        load_asset=lambda path:SimpleNamespace(get_class=lambda:SimpleNamespace(get_name=lambda:'AnimSequence')),
        Paths=SimpleNamespace(get_project_file_path=lambda:str(tmp_path/'New.uproject')),
    )
    monkeypatch.setitem(sys.modules,'unreal',fake)
    folder=ROOT/'integrations/unreal'
    monkeypatch.syspath_prepend(str(folder))
    spec=importlib.util.spec_from_file_location('studio_local_editor_worker_for_test', folder/'studio_local_editor_worker.py')
    worker=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.WORKSPACE=tmp_path/'runs'
    cid='20261031T123456Z_abcdef01'
    target=worker.WORKSPACE/'candidates'/cid
    target.mkdir(parents=True)
    (target/'transfer-plan.json').write_text(json.dumps({
        'sequence_asset_path':'/Game/Tests/LS_New',
        'bindings':{'CAM_A_Wide':'CSAI_Old_CAM_A_Wide','Ch26_nonPBR':'CSAI_Old_Ch26_nonPBR'},
        'actions':[{'kind':'camera_setup','entity_name':'CAM_A_Wide'},
                   {'kind':'skeletal_animation','entity_name':'Ch26_nonPBR','unreal_asset_path':'/Game/Assets/Anim'}],
    }))
    worker._save(worker.WORKSPACE/'active-candidate.json', {'candidate_id':cid,'sequence_path':'/Game/Tests/LS_New'})
    worker._save(worker.WORKSPACE/'connection.json', {'target_project':str(tmp_path/'New.uproject'),
                                                    'level_path':'/Game/Tests/L_Test'})
    worker._update_destination_readiness()
    result=worker._load(worker.WORKSPACE/'destination-readiness.json')
    assert result['status']=='SCENE_SETUP_REQUIRED'
    assert result['ready'] is False
    assert [x['entity_name'] for x in result['missing_actors']]==['Ch26_nonPBR']
    assert result['found_actor_count']==1
    assert result['scene_modified'] is False
    assert result['candidate_id']==cid


def test_worker_start_writes_presence_and_repeated_start_does_not_register_twice(tmp_path, monkeypatch):
    callbacks = []
    messages = []
    fake = SimpleNamespace(
        register_slate_post_tick_callback=lambda cb: callbacks.append(cb) or 1,
        unregister_slate_post_tick_callback=lambda handle: None,
        log_warning=messages.append,
    )
    monkeypatch.setitem(sys.modules, 'unreal', fake)
    spec = importlib.util.spec_from_file_location('worker_start_test', ROOT/'integrations/unreal/studio_local_editor_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setattr(worker, '_loaded_project', lambda: str(tmp_path/'Target.uproject'))
    monkeypatch.setattr(worker, '_loaded_level', lambda: '/Game/Maps/Test')
    workspace = tmp_path/'runs'
    worker.start(workspace)
    worker.start(workspace)
    record = json.loads((workspace/'unreal-worker.json').read_text(encoding='utf-8'))
    assert record['level'] == '/Game/Maps/Test'
    assert record['checkout_root'] == str(ROOT.resolve())
    assert len(callbacks) == 1
    assert 'Already connected' in messages[-1]
    assert not (workspace/'jobs').exists()


@pytest.mark.parametrize('case', ['valid', 'expired', 'wrong_instance', 'wrong_code', 'failure', 'active_job'])
def test_worker_consumes_only_read_only_native_preflight_request(tmp_path, monkeypatch, case):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setitem(sys.modules, 'unreal', SimpleNamespace())
    spec = importlib.util.spec_from_file_location(
        'worker_ai_request_test', ROOT/'integrations/unreal/studio_local_editor_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.WORKSPACE = tmp_path
    request = {
        'kind': 'cutsceneai.studio.ai_native_preflight_request',
        'request_id': 'a' * 32,
        'worker_instance_id': ('old' if case == 'wrong_instance' else worker.WORKER_INSTANCE_ID),
        'worker_source_sha256': ('old' if case == 'wrong_code' else worker.WORKER_SOURCE_SHA256),
        'requested_at': (datetime.now(timezone.utc) - timedelta(
            seconds=121 if case == 'expired' else 0)).isoformat(),
    }
    worker._save(tmp_path/'ai-native-preflight-request.json', request)
    if case == 'active_job':
        worker._save(tmp_path/'active-job.json', {'job_id': 'existing'})
    calls = []

    def inspect(received):
        calls.append(received)
        if case == 'failure':
            raise RuntimeError('Native probe failed')

    monkeypatch.setattr(worker, 'inspect_active_ai_candidate', inspect)
    worker._process_ai_preflight_request()
    worker._process_ai_preflight_request()
    response = tmp_path/'ai-native-preflight-response.json'
    if case == 'wrong_instance':
        assert not response.exists()
    else:
        result = worker._load(response)
        assert result['request_id'] == request['request_id']
        assert result['execution_authorized'] is False
        assert result['status'] == ('AI_NATIVE_PREFLIGHT_COMPLETED' if case == 'valid'
                                    else 'AI_NATIVE_PREFLIGHT_FAILED')
    assert calls == ([request] if case in {'valid', 'failure'} else [])
    assert not (tmp_path/'jobs').exists()
    assert not (tmp_path/'one-click-approval.json').exists()


@pytest.mark.parametrize('case', ['valid', 'not_verified', 'wrong_world', 'wrong_project',
                                  'dirty', 'unknown_dirty', 'occupied'])
def test_ai_fresh_map_rechecks_before_creating_level(tmp_path, monkeypatch, case):
    """Exercise the actual level-creation boundary with a fake editor only."""
    editor_dir = ROOT / 'integrations/unreal'
    monkeypatch.syspath_prepend(str(editor_dir))
    from studio_ai_execution_auth import FRESH_LEVEL

    target = tmp_path / 'Target.uproject'
    target.write_text('{}', encoding='utf-8')
    old_level = '/Temp/Untitled'
    loaded = ['/Temp/Other' if case == 'wrong_world' else old_level]
    project = tmp_path / 'Wrong.uproject' if case == 'wrong_project' else target
    assets = {FRESH_LEVEL} if case == 'occupied' else set()
    mutations = []
    world = SimpleNamespace(get_path_name=lambda: loaded[0] + '.World')
    editor_type = object()
    level_type = object()

    def new_level(path):
        mutations.append(('new_level', path))
        assets.add(path)
        loaded[0] = path
        return True

    editor = SimpleNamespace(get_editor_world=lambda: world)
    level_editor = SimpleNamespace(new_level=new_level)
    fake = SimpleNamespace(
        Paths=SimpleNamespace(get_project_file_path=lambda: str(project)),
        UnrealEditorSubsystem=editor_type, LevelEditorSubsystem=level_type,
        get_editor_subsystem=lambda klass: editor if klass is editor_type else level_editor,
        EditorLoadingAndSavingUtils=SimpleNamespace(get_dirty_map_packages=lambda: (
            None if case == 'unknown_dirty' else [object()] if case == 'dirty' else [])),
        EditorAssetLibrary=SimpleNamespace(
            does_asset_exist=lambda path: path in assets,
            make_directory=lambda path: mutations.append(('directory', path))),
        log=lambda _: None,
    )
    monkeypatch.setitem(sys.modules, 'unreal', fake)
    spec = importlib.util.spec_from_file_location(
        'fresh_map_boundary_worker_test', editor_dir / 'studio_local_editor_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    job = {
        'expected_project': str(target.resolve()), 'expected_level': FRESH_LEVEL,
        'create_level': True, 'ai_authorization': {'approval_id': 'fixture'},
        'ai_execution_preflight_verified': case != 'not_verified',
        'ai_approved_observed_level': old_level,
    }
    if case == 'valid':
        worker._ensure_target_level(job)
        assert mutations == [('directory', '/Game/CutSceneAI/AutoTransfer'),
                             ('new_level', FRESH_LEVEL)]
        assert loaded[0] == FRESH_LEVEL
    else:
        expected = {
            'not_verified': 'preflight is required',
            'wrong_world': 'level changed',
            'wrong_project': 'project changed',
            'dirty': 'unsaved changes',
            'unknown_dirty': 'Cannot confirm',
            'occupied': 'Target level already exists',
        }[case]
        with pytest.raises((ValueError, RuntimeError), match=expected):
            worker._ensure_target_level(job)
        assert not mutations
