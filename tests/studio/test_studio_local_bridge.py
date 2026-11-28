"""End-to-end localhost API boundary tests, no Unity or Unreal runtime required."""
import hashlib
import importlib.util
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / 'tools/studio_local_bridge.py').is_file())
MODULE = ROOT / 'tools/studio_local_bridge.py'
spec = importlib.util.spec_from_file_location('studio_local_bridge', MODULE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


@pytest.fixture
def service(tmp_path):
    web = tmp_path / 'web'
    web.mkdir()
    (web / 'index.html').write_text('studio test')
    server = ThreadingHTTPServer(('127.0.0.1', 0), bridge.create_handler(web, tmp_path / 'work'))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}', tmp_path
    server.shutdown()
    server.server_close()
    thread.join()


def call(url, payload=None, key=None, origin=None):
    headers = {}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        if key:
            headers['X-CSAI-Token'] = key
        if origin:
            headers['Origin'] = origin
    req = Request(url, headers=headers,
                  data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urlopen(req, timeout=5) as result:
            return result.status, json.loads(result.read())
    except HTTPError as err:
        return err.code, json.loads(err.read())


def fixture_files(tmp_path):
    csir = tmp_path / 'source.csir.json'
    csir.write_text(json.dumps({
        'schema_version': '0.1.0',
        'cutscene_id': 'known', 'source': {'engine': 'unity'},
        'tracks': [{}, {}], 'entities': [{}, {}, {}],
    }))
    capture = tmp_path / 'source.cinetwin.behavior.json'
    capture.write_text(json.dumps({'kind': 'cinetwin.behavior_capture', 'cutscene_id': 'known'}))
    mapping = tmp_path / 'target_mapping.json'
    mapping.write_text(json.dumps({
        'sequence_asset_path': '/Game/Trials/LS_BenchmarkV8',
        'overwrite_sequence': False,
    }))
    project = tmp_path / 'Game.uproject'
    project.write_text('{}')
    return {'csir': str(csir), 'capture': str(capture),
            'mapping': str(mapping), 'target_project': str(project),
            'level_path': '/Game/Level'}


def test_local_connection_and_source_listing(service):
    base, tmp = service
    status, initial = call(base + '/api/status')
    assert status == 200 and initial['connected'] is False
    config = fixture_files(tmp)
    status, blocked = call(base + '/api/connect', config)
    assert status == 403 and 'token' in blocked['error'].lower()
    status, result = call(base + '/api/connect', config, initial['token'])
    assert status == 200 and result['source_track_count'] == 2
    assert result['source_entity_count'] == 3
    assert result['skeletal_root_world_lock'] is False
    status, source = call(base + '/api/cutscenes')
    assert status == 200 and source['cutscenes'][0]['cutscene_id'] == 'known'
    status, current = call(base + '/api/status')
    assert status == 200 and current['connected'] is True


def test_rejects_cross_site_post_and_wrong_capture(service):
    base, tmp = service
    token = call(base + '/api/status')[1]['token']
    config = fixture_files(tmp)
    status, blocked = call(base + '/api/connect', config, token, origin='https://attacker.example')
    assert status == 403
    Path(config['capture']).write_text(json.dumps({'cutscene_id': 'another'}))
    status, blocked = call(base + '/api/connect', config, token)
    assert status == 422 and 'does not match' in blocked['error']
    assert not (tmp / 'work/connection.json').exists()


def test_no_target_overwrite_and_no_execution_without_worker(service):
    base, tmp = service
    token = call(base + '/api/status')[1]['token']
    config = fixture_files(tmp)
    Path(config['mapping']).write_text(json.dumps({
        'sequence_asset_path': '/Game/Level/Old', 'overwrite_sequence': True,
    }))
    status, res = call(base + '/api/connect', config, token)
    assert status == 422 and 'overwriting' in res['error']
    Path(config['mapping']).write_text(json.dumps({
        'sequence_asset_path': '/Game/Level/Old', 'overwrite_sequence': False,
    }))
    assert call(base + '/api/connect', config, token)[0] == 200
    status, res = call(base + '/api/execute', {'candidate_id': 'not_a_candidate'}, token)
    assert status == 422 and 'not found' in res['error'].lower()


def test_report_path_is_confined_to_candidates(tmp_path):
    work = tmp_path / 'work'
    jobs = work / 'jobs'
    jobs.mkdir(parents=True)
    job_id = 'a' * 32
    external = tmp_path / 'untrusted-report.json'
    external.write_text('{}')
    bridge.atomic_json(jobs / (job_id+'.json'), {'job_id': job_id, 'diagnostic_file': str(external)})
    with pytest.raises(ValueError, match='outside'):
        bridge.diagnostic_summary(job_id, work)


def test_prepare_calls_existing_candidate_backend_without_changing_original(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    config = fixture_files(tmp_path)
    work = tmp_path / 'runs'
    bridge.atomic_json(work / 'connection.json', bridge.config_check(config))
    original_mapping = Path(config['mapping']).read_bytes()

    def fake_prepare(csir, mapping, capture, sequence, out, *, skeletal_root_world_lock,
                     hierarchy_transfer):
        assert Path(csir) == Path(config['csir'])
        assert Path(mapping) == Path(config['mapping'])
        assert Path(capture) == Path(config['capture'])
        assert sequence.startswith('/Game/Trials/LS_BenchmarkV8_STUDIO_')
        assert skeletal_root_world_lock is False
        assert hierarchy_transfer is False
        out.mkdir(parents=True)
        (out / 'transfer-plan.json').write_text(json.dumps({'actions':[{'kind':'camera_cut'},{'kind':'transform'}]}))
        copy = out.with_suffix('.mapping.json')
        copy.write_text(json.dumps({'sequence_asset_path': sequence}))
        return copy, {'ced_preflight': 'REVIEW_REQUIRED',
                      'track_coverage': {'NATIVE_UNVERIFIED': 2}}

    monkeypatch.setitem(sys.modules, 'studio_candidate', SimpleNamespace(prepare_candidate=fake_prepare))
    result = bridge.prepare(work)
    assert result['engine_generation_executed'] is False
    assert result['behavioral_fidelity_established'] is False
    assert result['track_coverage'] == {'NATIVE_UNVERIFIED': 2}
    assert Path(config['mapping']).read_bytes() == original_mapping


def test_queue_requires_alive_editor_and_immutable_handoff(tmp_path, monkeypatch):
    import sys
    from datetime import UTC, datetime
    from types import SimpleNamespace

    config = fixture_files(tmp_path)
    work = tmp_path / 'runs'
    checked = bridge.config_check(config)
    bridge.atomic_json(work / 'connection.json', checked)
    candidate_id = '20261030T123456Z_deadbeef'
    folder = work / 'candidates' / candidate_id
    folder.mkdir(parents=True)
    (folder / 'session.json').write_text('{}')
    with pytest.raises(ValueError, match='not connected'):
        # No editor heartbeat => fail-closed even with a valid session.
        session = {'source': {'csir_path': config['csir']},
                   'source_capture': {'path': config['capture']},
                   'target': {'mapping_path': config['mapping'],
                              'sequence_asset_path': '/Game/Trials/LS_New'}}
        monkeypatch.setitem(sys.modules, 'prepared_transfer', SimpleNamespace(verify=lambda _: session))
        bridge.queue_trial(candidate_id, work)

    bridge.atomic_json(work / 'unreal-worker.json', {
        'heartbeat': datetime.now(UTC).isoformat(), 'project': config['target_project'], 'level': config['level_path']
    })
    # Valid editor heartbeat is insufficient when its scene is missing actors.
    with pytest.raises(ValueError, match='Destination not ready'):
        bridge.queue_trial(candidate_id, work)
    import hashlib
    bridge.atomic_json(work / 'active-candidate.json', {
        'candidate_id': candidate_id, 'sequence_path': '/Game/Trials/LS_New'
    })
    (folder / 'transfer-plan.json').write_text('{}')
    bridge.atomic_json(work / 'destination-readiness.json', {
        'kind': 'cutsceneai.studio.destination_readiness',
        'checked_at': datetime.now(UTC).isoformat(),
        'candidate_id': candidate_id, 'sequence_path': '/Game/Trials/LS_New',
        'plan_sha256': hashlib.sha256((folder / 'transfer-plan.json').read_bytes()).hexdigest(),
        'expected_project': config['target_project'], 'observed_project': config['target_project'],
        'expected_level': config['level_path'], 'observed_level': config['level_path'],
        'status': 'SCENE_SETUP_REQUIRED', 'ready': False, 'missing_actors': [{'actor_label':'CSAI_Test_CAM_A'}],
        'next_action': 'Create the required actors.'
    })
    with pytest.raises(ValueError, match='missing actors'):
        bridge.queue_trial(candidate_id, work)
    valid = bridge.load_json(work / 'destination-readiness.json')
    valid['status'] = 'READY'
    valid['ready'] = True
    valid['missing_actors'] = []
    valid['next_action'] = 'Ready.'
    bridge.atomic_json(work / 'destination-readiness.json', valid)
    assert bridge.destination_readiness(work)['ready'] is True
    # With a verified ready-scene report, a new job can now be queued.
    result = bridge.queue_trial(candidate_id, work)
    assert result['status'] == 'QUEUED'
    job = bridge.job_status(result['job_id'], work)
    assert job['generation_status'] == 'NOT_STARTED'
    assert job['fidelity_verified'] is False


def test_source_capture_optional_during_connection(service):
    base, tmp = service
    token = call(base + '/api/status')[1]['token']
    config = fixture_files(tmp)
    config['capture'] = ''
    status, connected = call(base + '/api/connect', config, token)
    assert status == 200
    assert connected['capture'] == ''
    assert connected['source_capture_available'] is False
    assert connected['track_types'] == {'unknown': 2}


def test_worker_must_match_project_and_level(tmp_path, monkeypatch):
    import sys
    from datetime import UTC, datetime
    from types import SimpleNamespace
    config = fixture_files(tmp_path)
    work = tmp_path / 'runs'
    bridge.atomic_json(work / 'connection.json', bridge.config_check(config))
    candidate_id = '20261030T123456Z_deadbeef'
    candidate_dir = work / 'candidates' / candidate_id
    candidate_dir.mkdir(parents=True)
    (candidate_dir / 'session.json').write_text('{}')
    session = {'source': {'csir_path': config['csir']},
               'source_capture': {'path': config['capture']},
               'target': {'mapping_path': config['mapping'],
                          'sequence_asset_path': '/Game/Trials/LS_New'}}
    monkeypatch.setitem(sys.modules, 'prepared_transfer', SimpleNamespace(verify=lambda _: session))
    bridge.atomic_json(work / 'unreal-worker.json', {
        'heartbeat': datetime.now(UTC).isoformat(),
        'project': config['target_project'], 'level': '/Game/Wrong'})
    with pytest.raises(ValueError, match='different project or level'):
        bridge.queue_trial(candidate_id, work)


def test_target_observation_source_identity(tmp_path):
    import hashlib
    cfg = fixture_files(tmp_path)
    cfg['capture'] = ''
    source = Path(cfg['csir'])
    obs = tmp_path / 'target_observation.json'
    obs.write_text(json.dumps({
        'kind': 'cinetwin.target_behavior_observation',
        'cutscene_id': 'known',
        'source': {'csir_sha256': hashlib.sha256(source.read_bytes()).hexdigest()},
        'target': {'sequence_asset_path': '/Game/Tests/LS_Candidate'},
        'coverage': {'sample_count': 2, 'full_temporal_coverage': True,
                     'mapped_entity_count': 1, 'source_entity_count': 3,
                     'skeletal_rig_count': 0, 'unmapped_source_entities': [{}, {}]},
        'samples': [{'time_seconds': 0, 'entities': [{'entity_id':'actor1','actor_label':'Hero','world_transform':{'position_m':[0,0,0]}}], 'skeletal_poses':[]}, {'time_seconds': 1, 'entities': [{'entity_id':'actor1','actor_label':'Hero','world_transform':{'position_m':[0,0,1]}}], 'skeletal_poses':[]}]
    }))
    checked = bridge.config_check(cfg)
    summary = bridge.observation_summary(str(obs), checked)
    assert summary['sample_count'] == 2
    assert summary['fidelity'] == 'NOT_ESTABLISHED'
    data = json.loads(obs.read_text())
    data['source']['csir_sha256'] = 'wrong'
    obs.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='hash'):
        bridge.observation_summary(str(obs), checked)


def test_no_execution_without_candidate_file(service):
    base, tmp = service
    token = call(base + '/api/status')[1]['token']
    config = fixture_files(tmp)
    assert call(base + '/api/connect', config, token)[0] == 200
    status, res = call(base + '/api/observation', {'path': str(tmp / 'missing.json')}, token)
    assert status == 422
    assert 'observation' in res['error'].lower()


def test_prepare_without_unity_behavior_capture(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    cfg = fixture_files(tmp_path)
    cfg['capture'] = ''
    work = tmp_path / 'runs'
    bridge.atomic_json(work / 'connection.json', bridge.config_check(cfg))
    original = Path(cfg['mapping']).read_bytes()
    def fake_prep(csir, mapping, output, *, target_project=None):
        assert str(csir) == cfg['csir']
        assert target_project == cfg['target_project']
        assert Path(mapping).is_file()
        assert load_file(mapping)['overwrite_sequence'] is False
        assert load_file(mapping)['sequence_asset_path'] != '/Game/Trials/LS_BenchmarkV8'
        Path(output).mkdir()
        (Path(output)/'transfer-plan.json').write_text(json.dumps({
            'actions':[{'kind':'camera_cut'}, {'kind':'camera_cut'}, {'kind':'skeletal_animation'}]}))
        return {'ced_preflight':'REVIEW_REQUIRED', 'track_coverage':{'NATIVE_UNVERIFIED':2,'SKIPPED':1}}
    def load_file(p):
        return json.loads(Path(p).read_text())
    monkeypatch.setitem(sys.modules,'studio_candidate',SimpleNamespace(prepare_candidate=lambda *a,**k: None))
    monkeypatch.setitem(sys.modules,'prepared_transfer',SimpleNamespace(prepare=fake_prep))
    result = bridge.prepare(work)
    assert result['action_total'] == 3
    assert result['action_counts'] == {'camera_cut':2,'skeletal_animation':1}
    assert result['source_capture_available'] is False
    assert Path(cfg['mapping']).read_bytes() == original
    assert (work/'active-candidate.json').is_file()


def test_review_flags_expose_cross_namespace_and_unverified_audio():
    cfg = {'base_sequence': '/Game/OldAssets/LS_Demo',
           'level_path': '/Game/Tests/L_Target'}
    flags = bridge.review_flags(cfg, {'audio': 2, 'transform': 5})
    assert len(flags) == 2
    assert flags[0].startswith('MAPPING_NAMESPACE_DIFFERENCE:')
    assert 'AUDIO_TARGETS_UNVERIFIED' in flags[1]
    assert bridge.review_flags({'base_sequence':'/Game/Tests/LS_Demo',
                                'level_path':'/Game/Tests/L_Target'},
                               {'audio':0}) == []


def test_readiness_refuses_stale_or_different_candidate(tmp_path):
    import hashlib
    from datetime import UTC, datetime, timedelta
    cfg = fixture_files(tmp_path)
    work = tmp_path / 'runs'
    work.mkdir(parents=True)
    bridge.atomic_json(work / 'connection.json', bridge.config_check(cfg))
    cid = '20261031T123456Z_aaaabbbb'
    folder = work / 'candidates' / cid
    folder.mkdir(parents=True)
    plan = folder / 'transfer-plan.json'
    plan.write_text('{"actions":[]}', encoding='utf-8')
    bridge.atomic_json(work / 'active-candidate.json', {'candidate_id':cid, 'sequence_path':'/Game/New'})
    bridge.atomic_json(work / 'unreal-worker.json', {'heartbeat':datetime.now(UTC).isoformat(),
                                                  'project':cfg['target_project'],'level':cfg['level_path']})
    report = {'kind':'cutsceneai.studio.destination_readiness',
              'candidate_id':cid, 'sequence_path':'/Game/New',
              'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),
              'expected_project':cfg['target_project'], 'observed_project':cfg['target_project'],
              'expected_level':cfg['level_path'], 'observed_level':cfg['level_path'],
              'checked_at':datetime.now(UTC).isoformat(), 'ready':True,'status':'READY'}
    bridge.atomic_json(work / 'destination-readiness.json', report)
    assert bridge.destination_readiness(work)['ready'] is True
    report['candidate_id'] = 'different'
    bridge.atomic_json(work / 'destination-readiness.json', report)
    assert bridge.destination_readiness(work)['status'] == 'INSPECTION_UNAVAILABLE'
    report['candidate_id'] = cid
    report['checked_at'] = (datetime.now(UTC)-timedelta(minutes=1)).isoformat()
    bridge.atomic_json(work / 'destination-readiness.json', report)
    assert bridge.destination_readiness(work)['status'] == 'INSPECTION_UNAVAILABLE'
    report['checked_at'] = datetime.now(UTC).isoformat()
    bridge.atomic_json(work / 'destination-readiness.json', report)
    plan.write_text('{"actions":["tampered"]}', encoding='utf-8')
    assert bridge.destination_readiness(work)['status'] == 'INSPECTION_UNAVAILABLE'


def test_status_exposes_readiness_before_generate(service):
    base, tmp = service
    cfg = fixture_files(tmp)
    token=call(base+'/api/status')[1]['token']
    assert call(base+'/api/connect',cfg,token)[0]==200
    status, data=call(base+'/api/status')
    assert status==200 and data['destination_readiness']['ready'] is False
    assert data['destination_readiness']['status']=='WAITING_FOR_PLAN'


def test_live_editor_without_report_is_not_endless_checking(tmp_path):
    """Connected and heartbeating worker cannot leave UI in checking forever."""
    from datetime import UTC, datetime
    cfg = fixture_files(tmp_path)
    work = tmp_path / 'runs'
    bridge.atomic_json(work / 'connection.json', bridge.config_check(cfg))
    cid = '20261101T012000Z_aaaabbbb'
    path = work / 'candidates' / cid / 'transfer-plan.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"actions":[]}', encoding='utf-8')
    bridge.atomic_json(work / 'active-candidate.json', {
        'candidate_id': cid, 'sequence_path': '/Game/Tests/LS_New',
    })
    bridge.atomic_json(work / 'unreal-worker.json', {
        'heartbeat': datetime.now(UTC).isoformat(),
        'project': cfg['target_project'], 'level': cfg['level_path'],
        'worker': 'studio-editor-v0.5',
    })
    report = bridge.destination_readiness(work)
    assert report['status'] == 'INSPECTION_UNAVAILABLE'
    assert report['ready'] is False
    assert 'Python log' in report['next_action']


def test_connected_old_companion_explains_restart(tmp_path):
    from datetime import UTC, datetime
    cfg = fixture_files(tmp_path)
    work = tmp_path / 'runs'
    connected = bridge.config_check(cfg)
    connected['unity_project'] = str(tmp_path)
    bridge.atomic_json(work / 'connection.json', connected)
    bridge.atomic_json(work / 'active-candidate.json', {
        'candidate_id': '20261101T012000Z_aaaabbbb', 'sequence_path': '/Game/New',
    })
    bridge.atomic_json(work / 'unreal-worker.json', {
        'heartbeat': datetime.now(UTC).isoformat(),
        'project': cfg['target_project'], 'level': cfg['level_path'],
        'worker': 'studio-editor-v0.3',
    })
    report = bridge.destination_readiness(work)
    assert report['status'] == 'UPGRADE_COMPANION'
    assert 'restart unreal' in report['next_action'].lower()


def test_automatic_studio_preparation_requests_safe_hierarchy_reconstruction(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    config = fixture_files(tmp_path)
    unity = tmp_path / "Unity"
    (unity / "Assets").mkdir(parents=True)
    config["unity_project"] = str(unity)
    config["source_scope"] = "Assets"
    work = tmp_path / "runs"
    bridge.atomic_json(work / "connection.json", bridge.config_check(config))
    original = Path(config["mapping"]).read_bytes()

    def fake_prepare(csir, mapping, capture, sequence, out, *,
                     skeletal_root_world_lock, hierarchy_transfer):
        assert hierarchy_transfer is True
        assert skeletal_root_world_lock is False
        out.mkdir(parents=True)
        (out / "transfer-plan.json").write_text(json.dumps({
            "sequence_asset_path": sequence, "actions": [], "bindings": {}
        }))
        copied = out.with_suffix(".mapping.json")
        copied.write_text(json.dumps({"sequence_asset_path": sequence,
                                      "enable_cinetwin_hierarchy": True}))
        return copied, {"ced_preflight": "REVIEW_REQUIRED",
                        "track_coverage": {"NATIVE_UNVERIFIED": 1}}

    monkeypatch.setitem(sys.modules, "studio_candidate",
                        SimpleNamespace(prepare_candidate=fake_prepare))
    result = bridge.prepare(work)
    assert result["engine_generation_executed"] is False
    assert Path(config["mapping"]).read_bytes() == original


def test_source_only_studio_candidate_uses_hierarchy_enabled_mapping_copy(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    config = fixture_files(tmp_path)
    config.pop("capture")
    unity = tmp_path / "Unity"
    (unity / "Assets").mkdir(parents=True)
    config["unity_project"] = str(unity)
    config["source_scope"] = "Assets"
    work = tmp_path / "runs"
    bridge.atomic_json(work / "connection.json", bridge.config_check(config))
    original = Path(config["mapping"]).read_bytes()
    observed = {}

    def fake_prepared(csir, copied_mapping, output, *, target_project):
        mapping = json.loads(Path(copied_mapping).read_text(encoding="utf-8"))
        observed["hierarchy"] = mapping.get("enable_cinetwin_hierarchy")
        assert mapping["overwrite_sequence"] is False
        assert mapping["sequence_asset_path"].startswith("/Game/Trials/LS_BenchmarkV8_STUDIO_")
        output.mkdir(parents=True)
        (output / "transfer-plan.json").write_text(json.dumps({
            "sequence_asset_path": mapping["sequence_asset_path"],
            "bindings": {}, "actions": [],
        }))
        return {"ced_preflight": "REVIEW_REQUIRED",
                "track_coverage": {"NATIVE_UNVERIFIED": 1}}

    # Exercise the mixed-suite import order: the wrapper has not been loaded
    # yet and the source-only planner is temporarily replaced by a test double.
    # Importing the unused wrapper here would retain the fake planner even
    # after monkeypatch restores sys.modules.
    monkeypatch.delitem(sys.modules, "studio_candidate", raising=False)
    monkeypatch.setitem(sys.modules, "prepared_transfer",
                        SimpleNamespace(prepare=fake_prepared))
    result = bridge.prepare(work)
    assert "studio_candidate" not in sys.modules
    assert observed["hierarchy"] is True
    assert result["engine_generation_executed"] is False
    assert Path(config["mapping"]).read_bytes() == original



def test_failed_job_exposes_native_stage_and_exact_safe_setup_receipt(tmp_path):
    work = tmp_path / "work"
    candidate = work / "candidates" / "candidate_001"
    candidate.mkdir(parents=True)
    job_id = "d" * 32
    receipt = candidate / ("automatic-setup-receipt-" + job_id + ".json")
    receipt.write_text(json.dumps({
        "kind": "cutsceneai.studio.automatic_setup_receipt",
        "status": "PARTIAL_SETUP_MUST_INSPECT",
        "failed_step": {"phase": "asset_import", "path": "/Game/Studio/CharacterA"},
        "recovery": "Do not rerun; inspect imported assets.",
        "error": {"type": "AutomaticSetupError", "message": "FBX import failed"},
    }))
    job = {
        "job_id": job_id, "candidate_id": "candidate_001",
        "candidate_dir": str(candidate), "created_at": "2026-11-09T17:00:00Z",
        "status": "PARTIAL_SETUP_MUST_INSPECT",
        "generation_status": "NOT_STARTED",
        "failure_stage": "IMPORTING_ASSETS_AND_CREATING_ACTORS",
        "error": "FBX import failed",
        "setup_receipt_file": str(receipt),
        "setup_status": "PARTIAL_SETUP_MUST_INSPECT",
    }
    bridge.atomic_json(work / "jobs" / (job_id + ".json"), job)
    result = bridge.job_status(job_id, work)
    assert result["error"] == "FBX import failed"
    assert result["failure_stage"] == "IMPORTING_ASSETS_AND_CREATING_ACTORS"
    assert result["created_at"] == "2026-11-09T17:00:00Z"
    assert result["candidate_id"] == "candidate_001"
    assert result["setup_failed_step"]["phase"] == "asset_import"
    assert result["setup_recovery"].startswith("Do not rerun")
    assert result["setup_error"] == "FBX import failed"
    assert "traceback" not in result

    # A forged receipt path cannot read arbitrary files outside the candidate.
    external = tmp_path / "outside.json"
    external.write_text(receipt.read_text())
    job["setup_receipt_file"] = str(external)
    bridge.atomic_json(work / "jobs" / (job_id + ".json"), job)
    blocked = bridge.job_status(job_id, work)
    assert blocked["error"] == "FBX import failed"
    assert "setup_failed_step" not in blocked
    assert "setup_recovery" not in blocked


def test_old_failed_job_keeps_original_error_without_new_stage(tmp_path):
    work = tmp_path / "work"
    job_id = "e" * 32
    bridge.atomic_json(work / "jobs" / (job_id + ".json"), {
        "job_id": job_id,
        "status": "BLOCKED_OR_FAILED",
        "generation_status": "NOT_STARTED",
        "error": "Target already exists; refusing to overwrite or rerun.",
    })
    report = bridge.job_status(job_id, work)
    assert report["error"].startswith("Target already exists")
    assert report["failure_stage"] is None
    assert "setup_failed_step" not in report



def _current_editor_heartbeat(config):
    import hashlib
    from datetime import UTC, datetime

    worker_file = (bridge.ROOT / 'integrations/unreal' /
                   'studio_local_editor_worker.py')
    return {
        'heartbeat': datetime.now(UTC).isoformat(),
        'project': config['target_project'],
        'level': config['level_path'],
        'worker': bridge.REQUIRED_WORKER_PROTOCOL,
        'checkout_root': str(bridge.ROOT.resolve()),
        'worker_source_sha256': hashlib.sha256(worker_file.read_bytes()).hexdigest(),
    }


def test_unreal_companion_handshake_rejects_old_cached_or_foreign_worker(tmp_path):
    config = fixture_files(tmp_path)
    good = _current_editor_heartbeat(config)
    result = bridge.worker_code_mismatch({
        'worker_version': good['worker'],
        'checkout_root': good['checkout_root'],
        'worker_source_sha256': good['worker_source_sha256'],
    })
    assert result is None
    for changed, expected in [
        ({'worker_version': 'studio-editor-v0.5'}, 'requires'),
        ({'worker_source_sha256': '0' * 64}, 'cached an outdated'),
        ({'checkout_root': str(tmp_path / 'OtherCheckout')}, 'different'),
        ({'worker_source_sha256': None}, 'cached an outdated'),
        ({'checkout_root': None}, 'valid'),
        ({'checkout_root': '.'}, 'absolute'),
    ]:
        worker = {
            'worker_version': good['worker'],
            'checkout_root': good['checkout_root'],
            'worker_source_sha256': good['worker_source_sha256'],
        }
        worker.update(changed)
        assert expected in bridge.worker_code_mismatch(worker)


def test_destination_readiness_blocks_older_editor_for_source_studio(tmp_path):
    config = fixture_files(tmp_path)
    config = bridge.config_check(config)
    # A source-project Studio connection is subject to the stronger
    # module-origin handshake; target-only legacy trials are unaffected.
    config['unity_project'] = str(tmp_path / 'Unity')
    work = tmp_path / 'runs'
    bridge.atomic_json(work / 'connection.json', config)
    bridge.atomic_json(work / 'active-candidate.json', {
        'candidate_id': 'candidate_new', 'sequence_path': '/Game/Fresh',
    })
    old = _current_editor_heartbeat(config)
    old['worker'] = 'studio-editor-v0.5'
    bridge.atomic_json(work / 'unreal-worker.json', old)
    report = bridge.destination_readiness(work)
    assert report['status'] == 'UPGRADE_COMPANION'
    assert report['ready'] is False
    assert 'completely close Unreal Editor' in report['next_action']
    assert 'new transfer candidate' in report['next_action']
    current = _current_editor_heartbeat(config)
    bridge.atomic_json(work / 'unreal-worker.json', current)
    followup = bridge.destination_readiness(work)
    assert followup['status'] != 'UPGRADE_COMPANION'


def test_queue_refuses_stale_worker_before_job_or_asset_mutation(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    cfg = bridge.config_check(fixture_files(tmp_path))
    cfg['unity_project'] = str(tmp_path / 'Unity')
    work = tmp_path / 'runs'
    bridge.atomic_json(work / 'connection.json', cfg)
    candidate = 'candidate_no_stale_worker'
    path = work / 'candidates' / candidate
    path.mkdir(parents=True)
    (path / 'session.json').write_text('{}')
    session = {
        'source': {'csir_path': cfg['csir']},
        'source_capture': {'path': cfg['capture']},
        'target': {'mapping_path': cfg['mapping'],
                   'sequence_asset_path': '/Game/CutSceneAI/New'},
    }
    monkeypatch.setitem(sys.modules, 'prepared_transfer',
                        SimpleNamespace(verify=lambda _: session))
    monkeypatch.setattr(bridge, 'config_check', lambda current: current)
    heartbeat = _current_editor_heartbeat(cfg)
    heartbeat['worker'] = 'studio-editor-v0.5'
    bridge.atomic_json(work / 'unreal-worker.json', heartbeat)
    with pytest.raises(ValueError, match='Unreal companion update required'):
        bridge.queue_trial(candidate, work)
    assert not (work / 'jobs').exists() or not list((work / 'jobs').glob('*.json'))
    assert not (work / 'active-job.json').exists()

    # A new-protocol worker that reports an old imported code hash also blocks.
    heartbeat['worker'] = bridge.REQUIRED_WORKER_PROTOCOL
    heartbeat['worker_source_sha256'] = 'f' * 64
    bridge.atomic_json(work / 'unreal-worker.json', heartbeat)
    with pytest.raises(ValueError, match='cached an outdated Python worker'):
        bridge.queue_trial(candidate, work)
    assert not (work / 'active-job.json').exists()


def test_invalid_ai_toggle_and_non_object_request_return_422(service):
    base, tmp = service
    token = call(base + '/api/status')[1]['token']
    assert call(base + '/api/connect', fixture_files(tmp), token)[0] == 200
    status, result = call(base + '/api/prepare', {'enable_ai_agent': 'true'}, token)
    assert status == 422
    assert 'enable_ai_agent must be Boolean' in result['error']
    status, result = call(base + '/api/prepare', [], token)
    assert status == 422
    assert 'Expected JSON request object' in result['error']
    assert not (tmp / 'work/active-candidate.json').exists()


@pytest.mark.parametrize('case', [
    'valid', 'expired', 'restart', 'wrong_level', 'changed_connection',
    'changed_candidate', 'changed_session', 'changed_setup', 'changed_artifact',
    'changed_source', 'authorization_flag', 'missing_report',
    'request_pending', 'request_completed', 'request_failed', 'wrong_request',
])
def test_ai_native_preflight_report_is_read_only_and_candidate_bound(service, case):
    base, tmp = service
    work = tmp / 'work'
    candidate_id = 'candidate_fixture'
    candidate = work / 'candidates' / candidate_id
    candidate.mkdir(parents=True)
    cfg = fixture_files(tmp)
    cfg['source_rights_confirmed'] = True
    cfg['capture'] = ''
    mapping = candidate.with_suffix('.mapping.json')
    mapping.write_bytes(Path(cfg['mapping']).read_bytes())
    analysis = candidate.with_suffix('.source-analysis.json')
    analysis.write_text('{}', encoding='utf-8')
    sequence = '/Game/Trials/LS_Fresh'

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    artifacts = {}
    for name in ('ai-handoff.json', 'coverage-report.json', 'evidence.json',
                 'transfer-plan.json'):
        path = candidate / name
        path.write_text('{}', encoding='utf-8')
        artifacts[name] = sha(path)
    setup = candidate / 'automatic-setup.json'
    setup.write_text('{}', encoding='utf-8')
    session_path = candidate / 'session.json'
    bridge.atomic_json(session_path, {
        'session_id': 'session_fixture',
        'source': {'csir_path': cfg['csir'], 'sha256': sha(Path(cfg['csir']))},
        'target': {'mapping_path': str(mapping), 'mapping_sha256': sha(mapping),
                   'project_path': cfg['target_project'], 'sequence_asset_path': sequence},
        'source_capture': None,
        'ai_analysis': {'path': str(analysis), 'sha256': sha(analysis)},
        'artifact_sha256': artifacts,
    })
    active = work / 'active-candidate.json'
    config = work / 'connection.json'
    bridge.atomic_json(active, {
        'candidate_id': candidate_id, 'candidate_dir': str(candidate),
        'mapping_copy': str(mapping), 'sequence_path': sequence,
        'ai_analysis': {'status': 'PREPARED_ADVISORY'},
    })
    bridge.atomic_json(config, cfg)
    now = datetime.now(UTC)
    worker_sha = sha(ROOT / 'integrations/unreal/studio_local_editor_worker.py')
    bridge.atomic_json(work / 'unreal-worker.json', {
        'heartbeat': now.isoformat(), 'project': cfg['target_project'],
        'level': '/Game/Other' if case == 'wrong_level' else cfg['level_path'],
        'worker': bridge.REQUIRED_WORKER_PROTOCOL,
        'checkout_root': str(ROOT.resolve()), 'worker_source_sha256': worker_sha,
        'worker_instance_id': 'new_worker' if case == 'restart' else 'worker_fixture',
    })
    report_path = work / 'ai-native-preflight.json'
    report = {
        'kind': 'cutsceneai.studio.ai_native_preflight',
        'status': 'AI_NATIVE_SETUP_PREFLIGHT_PASSED',
        'candidate_id': candidate_id, 'session_id': 'session_fixture',
        'session_sha256': sha(session_path), 'automatic_setup_sha256': sha(setup),
        'artifact_sha256': artifacts,
        'observed_project': cfg['target_project'], 'observed_level': cfg['level_path'],
        'sequence_path': sequence, 'worker_instance_id': 'worker_fixture',
        'worker_source_sha256': worker_sha, 'connection_sha256': sha(config),
        'candidate_record_sha256': sha(active),
        'checked_at': (now - timedelta(seconds=121) if case == 'expired' else now).isoformat(),
        'execution_authorized': case == 'authorization_flag',
        'engine_generation_executed': False, 'behavioral_fidelity_established': False,
    }
    if case != 'missing_report':
        bridge.atomic_json(report_path, report)
    changed = {
        'changed_connection': config, 'changed_candidate': active,
        'changed_session': session_path, 'changed_setup': setup,
        'changed_artifact': candidate / 'transfer-plan.json',
        'changed_source': Path(cfg['csir']),
    }.get(case)
    if changed:
        changed.write_bytes(changed.read_bytes() + b'\n')
    if case.startswith('request_') or case == 'wrong_request':
        request_id = 'a' * 32
        bridge.atomic_json(work / 'ai-native-preflight-request.json', {
            'kind': 'cutsceneai.studio.ai_native_preflight_request',
            'request_id': request_id, 'candidate_id': candidate_id,
            'worker_instance_id': 'worker_fixture',
            'worker_source_sha256': worker_sha,
            'candidate_record_sha256': sha(active), 'connection_sha256': sha(config),
            'requested_at': now.isoformat(),
        })
        if case != 'request_pending':
            bridge.atomic_json(work / 'ai-native-preflight-response.json', {
                'request_id': request_id,
                'status': ('AI_NATIVE_PREFLIGHT_FAILED' if case == 'request_failed'
                           else 'AI_NATIVE_PREFLIGHT_COMPLETED'),
                'execution_authorized': False, 'reason': 'Native test failure',
            })
        report['request_id'] = 'b' * 32 if case == 'wrong_request' else request_id
        bridge.atomic_json(report_path, report)
    status, result = call(base + '/api/ai-native-preflight')
    assert status == 200
    assert result['execution_authorized'] is False
    assert result['verified'] is (case in {'valid', 'request_completed'})
    assert result['status'] == (
        'AI_NATIVE_SETUP_PREFLIGHT_PASSED' if case in {'valid', 'request_completed'}
        else 'AI_NATIVE_PREFLIGHT_REQUESTED' if case == 'request_pending'
        else 'AI_NATIVE_PREFLIGHT_REQUIRED'
    )
    assert not (work / 'active-job.json').exists()
    assert not (work / 'one-click-approval.json').exists()


@pytest.mark.parametrize('case', ['valid', 'unauthorized', 'wrong_candidate', 'no_rights',
                                  'not_ready', 'wrong_level', 'active_job'])
def test_request_native_preflight_never_submits_execution(service, case):
    base, tmp = service
    work = tmp / 'work'
    candidate_id = 'ai_candidate'
    candidate = work / 'candidates' / candidate_id
    candidate.mkdir(parents=True)
    cfg = fixture_files(tmp)
    cfg['source_rights_confirmed'] = case != 'no_rights'
    bridge.atomic_json(work / 'connection.json', cfg)
    bridge.atomic_json(work / 'active-candidate.json', {
        'candidate_id': candidate_id, 'candidate_dir': str(candidate),
        'ai_analysis': {'status': 'PREPARED_ADVISORY'},
        'automatic_setup': {'ready': case != 'not_ready'},
    })
    bridge.atomic_json(work / 'unreal-worker.json', {
        'heartbeat': datetime.now(UTC).isoformat(),
        'project': cfg['target_project'],
        'level': '/Game/Other' if case == 'wrong_level' else cfg['level_path'],
        'worker': bridge.REQUIRED_WORKER_PROTOCOL, 'checkout_root': str(ROOT.resolve()),
        'worker_source_sha256': hashlib.sha256(
            (ROOT / 'integrations/unreal/studio_local_editor_worker.py').read_bytes()).hexdigest(),
        'worker_instance_id': 'fixture_instance',
    })
    if case == 'active_job':
        bridge.atomic_json(work / 'active-job.json', {'job_id': 'existing'})
    payload = {'candidate_id': 'wrong' if case == 'wrong_candidate' else candidate_id}
    token = None if case == 'unauthorized' else bridge.TOKEN
    status, result = call(base + '/api/ai-native-preflight', payload, token)
    request = work / 'ai-native-preflight-request.json'
    if case == 'valid':
        assert status == 200
        assert result['status'] == 'AI_NATIVE_PREFLIGHT_REQUESTED'
        assert result['execution_authorized'] is False
        saved = bridge.load_json(request)
        assert saved['candidate_id'] == candidate_id
        assert saved['worker_instance_id'] == 'fixture_instance'
        assert saved['request_id'] == result['request_id']
        assert call(base + '/api/ai-native-preflight', payload, token)[1] == result
    else:
        assert status == (403 if case == 'unauthorized' else 422)
        assert not request.exists()
    assert not (work / 'jobs').exists()
    assert not (work / 'one-click-approval.json').exists()


@pytest.fixture
def ai_execution_fixture(service, monkeypatch, request):
    """Synthetic persisted evidence; host authorization and worker gate are real."""
    import sys
    from types import SimpleNamespace

    base, tmp = service
    work = tmp / 'work'
    candidate_id = 'ai_execution_fixture'
    candidate = work / 'candidates' / candidate_id
    candidate.mkdir(parents=True)
    fields = fixture_files(tmp)
    fields.update(source_rights_confirmed=True, capture='')
    new_map = getattr(request, 'param', False)
    if new_map:
        fields.update(auto_create_level=True, level_path='/Game/CutSceneAI/AutoTransfer/L_Studio_Fresh')
    cfg = bridge.config_check(fields)
    observed_level = '/Temp/Untitled' if new_map else cfg['level_path']
    mapping = candidate.with_suffix('.mapping.json')
    mapping.write_bytes(Path(cfg['mapping']).read_bytes())
    analysis = candidate.with_suffix('.source-analysis.json')
    analysis.write_text('{}', encoding='utf-8')
    sequence = '/Game/Trials/LS_Fresh'
    auth = bridge._ai_auth_module()

    artifacts = {}
    for name in ('ai-handoff.json', 'coverage-report.json', 'evidence.json',
                 'transfer-plan.json'):
        path = candidate / name
        path.write_text('{}', encoding='utf-8')
        artifacts[name] = auth.digest(path)
    setup = candidate / 'automatic-setup.json'
    setup.write_text('{}', encoding='utf-8')
    session = {
        'session_id': 'session_fixture',
        'source': {'csir_path': cfg['csir'], 'sha256': auth.digest(Path(cfg['csir']))},
        'target': {'mapping_path': str(mapping), 'mapping_sha256': auth.digest(mapping),
                   'project_path': cfg['target_project'], 'sequence_asset_path': sequence},
        'source_capture': None,
        'ai_analysis': {'path': str(analysis), 'sha256': auth.digest(analysis)},
        'artifact_sha256': artifacts,
    }
    bridge.atomic_json(candidate / 'session.json', session)
    bridge.atomic_json(work / 'connection.json', cfg)
    bridge.atomic_json(work / 'active-candidate.json', {
        'candidate_id': candidate_id, 'candidate_dir': str(candidate),
        'mapping_copy': str(mapping), 'sequence_path': sequence,
        'ai_analysis': {'status': 'PREPARED_ADVISORY'},
        'automatic_setup': {'available': True, 'ready': True, 'blockers': []},
    })
    worker = {
        'heartbeat': datetime.now(UTC).isoformat(), 'project': cfg['target_project'],
        'level': observed_level, 'worker': bridge.REQUIRED_WORKER_PROTOCOL,
        'checkout_root': str(ROOT.resolve()),
        'worker_source_sha256': auth.digest(ROOT / 'integrations/unreal/studio_local_editor_worker.py'),
        'worker_instance_id': 'fixture_instance',
    }
    bridge.atomic_json(work / 'unreal-worker.json', worker)
    token = bridge.TOKEN
    status, request = call(base + '/api/ai-native-preflight',
                           {'candidate_id': candidate_id}, token)
    assert status == 200, request
    request_id = request['request_id']
    report = {
        'kind': 'cutsceneai.studio.ai_native_preflight',
        'status': 'AI_NATIVE_SETUP_PREFLIGHT_PASSED',
        'candidate_id': candidate_id, 'request_id': request_id,
        'session_id': session['session_id'],
        'session_sha256': auth.digest(candidate / 'session.json'),
        'automatic_setup_sha256': auth.digest(setup), 'artifact_sha256': artifacts,
        'observed_project': cfg['target_project'], 'observed_level': observed_level,
        'sequence_path': sequence, 'worker_instance_id': worker['worker_instance_id'],
        'worker_source_sha256': worker['worker_source_sha256'],
        'connection_sha256': auth.digest(work / 'connection.json'),
        'candidate_record_sha256': auth.digest(work / 'active-candidate.json'),
        'checked_at': datetime.now(UTC).isoformat(), 'planned_actor_count': 1,
        'planned_import_count': 0, 'verified_native_mesh_paths': [],
        'native_import_readback_pending': True, 'execution_authorized': False,
        'engine_generation_executed': False, 'behavioral_fidelity_established': False,
    }
    if new_map:
        report.update(create_level=True, expected_level=cfg['level_path'], new_level_preflight={
            'current_world_clean': True, 'target_map_absent': True,
            'level_creation_api_available': True})
    bridge.atomic_json(work / 'ai-native-preflight.json', report)
    bridge.atomic_json(work / 'ai-native-preflight-response.json', {
        'request_id': request_id, 'status': 'AI_NATIVE_PREFLIGHT_COMPLETED',
        'execution_authorized': False,
    })
    status, inspected = call(base + '/api/ai-native-preflight')
    assert status == 200 and inspected['verified'], inspected
    payload = {'candidate_id': candidate_id, 'request_id': request_id,
               'report_sha256': inspected['report_sha256']}
    # Keep the real authorization and HTTP boundary; synthetic planner and
    # native asset-manifest results isolate the gate from actual engine data.
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    monkeypatch.setitem(sys.modules, 'prepared_transfer',
                        SimpleNamespace(verify=lambda _: session))
    import studio_auto_assets

    manifest_calls = []

    def verify_manifest(*args):
        manifest_calls.append(args)
        return {'ready': True}

    monkeypatch.setattr(studio_auto_assets, 'verify', verify_manifest)
    monkeypatch.setattr(bridge, 'ai_model_memory_status', lambda: {
        'status': 'NO_RESIDENT_MODELS', 'ready': True, 'running_models': []})
    monkeypatch.setattr(bridge, 'destination_readiness',
                        lambda _: {'status': 'NEW_LEVEL_REQUIRED' if new_map else 'SCENE_SETUP_REQUIRED',
                                   'ready': False})
    return SimpleNamespace(base=base, work=work, candidate=candidate, cid=candidate_id,
                           cfg=cfg, session=session, report=report, worker=worker,
                           token=token, payload=payload, auth=auth, manifest_calls=manifest_calls)


def _approve_fixture(f):
    status, approved = call(f.base + '/api/approve-ai-execution', f.payload, f.token)
    assert status == 200, approved
    assert approved['approved'] is True
    assert approved['execution_queued'] is False
    assert not (f.work / 'active-job.json').exists()
    assert not list((f.work / 'jobs').glob('*.json'))
    return approved['approval_id']


def _queue_fixture(f, approval_id):
    return call(f.base + '/api/execute',
                {'candidate_id': f.cid, 'approval_id': approval_id}, f.token)


@pytest.mark.parametrize('case', ['valid', 'no_token', 'wrong_report', 'wrong_request',
                                  'wrong_candidate', 'manual_report', 'legacy_approval'])
def test_ai_explicit_authorization_is_bound_and_never_queues(ai_execution_fixture, case):
    f = ai_execution_fixture
    if case == 'valid':
        approval_id = _approve_fixture(f)
        approval = bridge.load_json(f.work / f.auth.APPROVAL_FILE)
        assert approval['approval_id'] == approval_id
        assert approval['binding']['candidate_id'] == f.cid
        assert approval['binding']['record_sha256']['ai-native-preflight.json'] == f.payload['report_sha256']
        assert approval['binding']['worker_instance_id'] == f.worker['worker_instance_id']
    else:
        payload = dict(f.payload)
        route = '/api/approve-ai-execution'
        if case == 'wrong_report':
            payload['report_sha256'] = 'f' * 64
        elif case == 'wrong_request':
            payload['request_id'] = 'f' * 32
        elif case == 'wrong_candidate':
            payload['candidate_id'] = 'other_candidate'
        elif case == 'manual_report':
            (f.work / 'ai-native-preflight-request.json').unlink()
            (f.work / 'ai-native-preflight-response.json').unlink()
        elif case == 'legacy_approval':
            route = '/api/approve-one-click'
        status, result = call(f.base + route, payload, None if case == 'no_token' else f.token)
        assert status == (403 if case == 'no_token' else 422), result
        assert not (f.work / f.auth.APPROVAL_FILE).exists()
    assert not (f.work / 'active-job.json').exists()
    assert not list((f.work / 'jobs').glob('*.json'))


@pytest.mark.parametrize('case', [
    'valid', 'no_approval', 'wrong_approval', 'expired_approval', 'worker_restart',
    'wrong_project', 'wrong_level', 'changed_report', 'changed_response', 'changed_source',
    'changed_manifest', 'collision', 'manifest_failure', 'duplicate', 'revoked_during_manifest',
])
def test_ai_queue_revalidates_authorization_and_manifest(ai_execution_fixture, monkeypatch, case):
    f = ai_execution_fixture
    approval_id = '' if case == 'no_approval' else _approve_fixture(f)
    if case == 'wrong_approval':
        approval_id = 'f' * 32
    elif case == 'expired_approval':
        path = f.work / f.auth.APPROVAL_FILE
        approval = bridge.load_json(path)
        approval['approved_at'] = (datetime.now(UTC) - timedelta(seconds=121)).isoformat()
        bridge.atomic_json(path, approval)
    elif case in {'worker_restart', 'wrong_project', 'wrong_level'}:
        key, value = {
            'worker_restart': ('worker_instance_id', 'restarted'),
            'wrong_project': ('project', str(f.work / 'Other.uproject')),
            'wrong_level': ('level', '/Game/Other'),
        }[case]
        bridge.atomic_json(f.work / 'unreal-worker.json', {**f.worker, key: value})
    elif case in {'changed_report', 'changed_response', 'changed_source', 'changed_manifest'}:
        path = {
            'changed_report': f.work / 'ai-native-preflight.json',
            'changed_response': f.work / 'ai-native-preflight-response.json',
            'changed_source': Path(f.cfg['csir']),
            'changed_manifest': f.candidate / 'automatic-setup.json',
        }[case]
        path.write_bytes(path.read_bytes() + b' ')
    elif case == 'collision':
        monkeypatch.setattr(bridge, 'destination_readiness',
                            lambda _: {'status': 'TARGET_EXISTS', 'ready': False})
    elif case in {'manifest_failure', 'revoked_during_manifest'}:
        import studio_auto_assets

        def verify_manifest(*args):
            if case == 'revoked_during_manifest':
                (f.work / f.auth.APPROVAL_FILE).unlink()
                return {'ready': True}
            return {'ready': False}

        monkeypatch.setattr(studio_auto_assets, 'verify', verify_manifest)
    elif case == 'duplicate':
        bridge.atomic_json(f.work / 'jobs' / ('e' * 32 + '.json'),
                           {'candidate_id': f.cid, 'status': 'BLOCKED_OR_FAILED'})
    status, result = _queue_fixture(f, approval_id)
    if case == 'valid':
        assert status == 200, result
        assert result['status'] == 'QUEUED'
        job = bridge.load_json(f.work / 'jobs' / (result['job_id'] + '.json'))
        assert job['ai_authorization'] == {
            'approval_id': approval_id,
            'approval_sha256': f.auth.digest(f.work / f.auth.APPROVAL_FILE),
        }
        assert job['automatic_setup'] is True and job['create_level'] is False
        assert job['generation_status'] == 'NOT_STARTED' and job['fidelity_verified'] is False
        assert len(f.manifest_calls) == 1
        assert _queue_fixture(f, approval_id)[0] == 422
        assert len(list((f.work / 'jobs').glob('*.json'))) == 1
    else:
        assert status == 422, result
        assert not (f.work / 'active-job.json').exists()
        assert len(list((f.work / 'jobs').glob('*.json'))) == (1 if case == 'duplicate' else 0)


@pytest.mark.parametrize('case', [
    'valid', 'missing_approval', 'wrong_approval_hash', 'restart', 'wrong_job_level',
    'wrong_job_project', 'wrong_manifest', 'no_automatic_setup', 'new_map', 'duplicate',
    'collision', 'changed_proof', 'changed_during_probe', 'consumed',
])
def test_worker_claim_requires_fresh_native_proof(ai_execution_fixture, monkeypatch, case):
    import sys
    from types import SimpleNamespace

    f = ai_execution_fixture
    approval_id = _approve_fixture(f)
    status, result = _queue_fixture(f, approval_id)
    assert status == 200, result
    job_id = result['job_id']
    job = bridge.load_json(f.work / 'jobs' / (job_id + '.json'))
    fake_unreal = SimpleNamespace()
    monkeypatch.setitem(sys.modules, 'unreal', fake_unreal)
    worker_path = ROOT / 'integrations/unreal/studio_local_editor_worker.py'
    spec = importlib.util.spec_from_file_location('ai_execution_gate_worker_test', worker_path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.WORKSPACE = f.work
    worker.WORKER_INSTANCE_ID = f.worker['worker_instance_id']
    import studio_ai_native_preflight as inspector

    # Only the read-only native probe is mocked. Keep real authorization,
    # file hashes, job identity and exclusive claim behavior.
    calls = []

    def probe(candidate, **kwargs):
        calls.append((candidate, kwargs))
        assert candidate == f.candidate.resolve()
        assert kwargs['expected_project'] == f.cfg['target_project']
        assert kwargs['expected_level'] == f.cfg['level_path']
        assert kwargs['unreal_api'] is fake_unreal
        if case == 'collision':
            raise ValueError('Existing actor label: fixture')
        if case == 'changed_during_probe':
            path = f.work / 'connection.json'
            path.write_bytes(path.read_bytes() + b' ')
        if case == 'changed_proof':
            return {**f.report, 'planned_actor_count': 2}
        return f.report.copy()

    monkeypatch.setattr(inspector, 'inspect_candidate', probe)
    real_reload = worker.importlib.reload
    monkeypatch.setattr(worker.importlib, 'reload',
                        lambda module: module if module is inspector else real_reload(module))
    claim = f.work / 'jobs' / (f.cid + '.ai-execution.used')
    if case == 'missing_approval':
        job.pop('ai_authorization')
    elif case == 'wrong_approval_hash':
        job['ai_authorization']['approval_sha256'] = 'f' * 64
    elif case == 'restart':
        worker.WORKER_INSTANCE_ID = 'restarted'
    elif case == 'wrong_job_level':
        job['expected_level'] = '/Game/Other'
    elif case == 'wrong_job_project':
        job['expected_project'] = str(f.work / 'Other.uproject')
    elif case == 'wrong_manifest':
        job['automatic_setup_manifest'] = str(f.candidate / 'other.json')
    elif case == 'no_automatic_setup':
        job['automatic_setup'] = False
    elif case == 'new_map':
        job['create_level'] = True
    elif case == 'duplicate':
        bridge.atomic_json(f.work / 'jobs' / ('e' * 32 + '.json'),
                           {'candidate_id': f.cid, 'status': 'QUEUED'})
    elif case == 'consumed':
        claim.write_text(job_id, encoding='utf-8')
    if case == 'valid':
        worker._verify_and_claim_ai_execution(job, f.candidate.resolve())
        assert job['ai_execution_preflight_verified'] is True
        assert claim.read_text(encoding='utf-8').strip() == job_id
        with pytest.raises(RuntimeError, match='already consumed'):
            worker._verify_and_claim_ai_execution(job, f.candidate.resolve())
        assert len(calls) == 1
    else:
        expected = {
            'missing_approval': 'explicit execution authorization',
            'wrong_approval_hash': 'differs from persisted approval',
            'restart': 'different worker',
            'wrong_job_level': 'not the exact authorized',
            'wrong_job_project': 'not the exact authorized',
            'wrong_manifest': 'not the exact authorized',
            'no_automatic_setup': 'not the exact authorized',
            'new_map': 'not the exact authorized',
            'duplicate': 'Duplicate AI candidate',
            'collision': 'Existing actor label',
            'changed_proof': 'Fresh native inspection differs',
            'changed_during_probe': 'different worker or candidate',
            'consumed': 'already consumed',
        }[case]
        with pytest.raises((ValueError, RuntimeError), match=expected):
            worker._verify_and_claim_ai_execution(job, f.candidate.resolve())
        assert claim.exists() is (case == 'consumed')
        assert not job.get('ai_execution_preflight_verified')
        assert len(calls) == (1 if case in {'collision', 'changed_proof', 'changed_during_probe'} else 0)
    # Calling the gate alone must not run setup or generation.
    assert job['generation_status'] == 'NOT_STARTED'
    assert job['fidelity_verified'] is False


@pytest.mark.parametrize('ai_execution_fixture', [True], indirect=True)
@pytest.mark.parametrize('case', ['valid', 'switched_world', 'map_created', 'bad_report',
                                  'wrong_request_world'])
def test_ai_new_map_authorization_is_bound_to_current_world(ai_execution_fixture, case):
    f = ai_execution_fixture
    request = bridge.load_json(f.work / 'ai-native-preflight-request.json')
    assert request['create_level'] is True
    assert request['observed_level'] == '/Temp/Untitled'
    assert request['expected_level'] == f.cfg['level_path']
    approval_id = _approve_fixture(f)
    if case == 'switched_world':
        bridge.atomic_json(f.work / 'unreal-worker.json', {**f.worker, 'level': '/Temp/Other'})
    elif case == 'map_created':
        path = Path(f.cfg['target_project']).parent / 'Content/CutSceneAI/AutoTransfer/L_Studio_Fresh.umap'
        path.parent.mkdir(parents=True)
        path.write_text('existing')
    elif case == 'bad_report':
        report = dict(f.report)
        report['new_level_preflight'] = {'current_world_clean': False}
        bridge.atomic_json(f.work / 'ai-native-preflight.json', report)
    elif case == 'wrong_request_world':
        bridge.atomic_json(f.work / 'ai-native-preflight-request.json',
                           {**request, 'observed_level': '/Temp/Other'})
    status, result = _queue_fixture(f, approval_id)
    if case == 'valid':
        assert status == 200, result
        job = bridge.load_json(f.work / 'jobs' / (result['job_id'] + '.json'))
        assert job['create_level'] is True
        assert job['expected_level'] == f.cfg['level_path']
        assert job['automatic_setup'] is True
        assert job['generation_status'] == 'NOT_STARTED'
    else:
        assert status == 422, result
        assert not (f.work / 'active-job.json').exists()
        assert not list((f.work / 'jobs').glob('*.json'))


@pytest.mark.parametrize('ai_execution_fixture', [True], indirect=True)
@pytest.mark.parametrize('case', ['valid', 'dirty_after_approval', 'switched_world'])
def test_new_map_worker_claim_requires_matching_fresh_probe(ai_execution_fixture, monkeypatch, case):
    import sys
    from types import SimpleNamespace

    f = ai_execution_fixture
    approval_id = _approve_fixture(f)
    status, result = _queue_fixture(f, approval_id)
    assert status == 200, result
    job = bridge.load_json(f.work / 'jobs' / (result['job_id'] + '.json'))
    monkeypatch.setitem(sys.modules, 'unreal', SimpleNamespace())
    spec = importlib.util.spec_from_file_location(
        'new_map_worker_test', ROOT / 'integrations/unreal/studio_local_editor_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.WORKSPACE = f.work
    worker.WORKER_INSTANCE_ID = f.worker['worker_instance_id']
    import studio_ai_native_preflight as inspector

    def probe(candidate, **kwargs):
        assert candidate == f.candidate.resolve()
        assert kwargs['create_level'] is True
        if case == 'dirty_after_approval':
            raise ValueError('Current Unreal map contains unsaved changes')
        return {**f.report, 'observed_level': '/Temp/Other'} if case == 'switched_world' else f.report

    monkeypatch.setattr(inspector, 'inspect_candidate', probe)
    real_reload = worker.importlib.reload
    monkeypatch.setattr(worker.importlib, 'reload',
                        lambda module: module if module is inspector else real_reload(module))
    claim = f.work / 'jobs' / (f.cid + '.ai-execution.used')
    if case == 'valid':
        worker._verify_and_claim_ai_execution(job, f.candidate.resolve())
        assert claim.exists()
        assert job['ai_approved_observed_level'] == '/Temp/Untitled'
        assert job['ai_execution_preflight_verified'] is True
    else:
        with pytest.raises(ValueError, match='unsaved changes|Fresh native inspection differs'):
            worker._verify_and_claim_ai_execution(job, f.candidate.resolve())
        assert not claim.exists()
    assert job['generation_status'] == 'NOT_STARTED'


@pytest.mark.parametrize('case', ['idle', 'offline', 'resident', 'unknown', 'reloaded'])
def test_ai_queue_checks_model_memory_before_publishing(ai_execution_fixture, monkeypatch, case):
    f = ai_execution_fixture
    approval_id = _approve_fixture(f)
    calls = []

    def memory():
        calls.append(True)
        state = {
            'idle': 'NO_RESIDENT_MODELS', 'offline': 'SERVICE_OFFLINE',
            'resident': 'MODELS_RESIDENT', 'unknown': 'MEMORY_STATUS_UNKNOWN',
            'reloaded': 'NO_RESIDENT_MODELS' if len(calls) == 1 else 'MODELS_RESIDENT',
        }[case]
        return {'status': state, 'ready': state in {'NO_RESIDENT_MODELS', 'SERVICE_OFFLINE'},
                'reason': 'Ollama memory not ready.'}

    monkeypatch.setattr(bridge, 'ai_model_memory_status', memory)
    status, result = _queue_fixture(f, approval_id)
    if case in {'idle', 'offline'}:
        assert status == 200, result
        assert len(calls) == 2
        assert (f.work / 'active-job.json').exists()
    else:
        assert status == 422 and 'Ollama memory not ready' in result['error']
        assert not (f.work / 'active-job.json').exists()
        assert not list((f.work / 'jobs').glob('*.json'))
        assert len(calls) == (2 if case == 'reloaded' else 1)


def test_ai_model_memory_status_endpoint_is_read_only(ai_execution_fixture):
    f = ai_execution_fixture
    status, result = call(f.base + '/api/ai-model-memory')
    assert status == 200
    assert result['status'] == 'NO_RESIDENT_MODELS'
    assert result['ready'] is True
    assert not (f.work / f.auth.APPROVAL_FILE).exists()
    assert not (f.work / 'active-job.json').exists()


def test_repair_outcome_endpoint_checks_exact_report_hash(service):
    base, tmp = service
    folder = tmp / 'work'
    job_id = 'd' * 32
    candidate = folder / 'candidates' / 'repair_fixture'
    candidate.mkdir(parents=True)
    (folder / 'jobs').mkdir()
    report = {'kind': 'cutsceneai.studio.repair_outcome', 'child_job_id': job_id,
              'status': 'MEASURED_ROOT_MOTION_IMPROVED', 'fidelity_verified': False}
    path = candidate / ('repair-outcome-' + job_id + '.json')
    path.write_text(json.dumps(report), encoding='utf-8')
    job = {'job_id': job_id, 'candidate_id': candidate.name, 'candidate_dir': str(candidate),
           'repair_outcome_file': str(path), 'repair_outcome_status': report['status'],
           'repair_outcome_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (folder / 'jobs' / (job_id + '.json')).write_text(json.dumps(job), encoding='utf-8')
    status, body = call(base + '/api/repair-outcome/' + job_id)
    assert status == 200 and body['available'] is True
    assert body['fidelity_verified'] is False
    path.write_text('{}', encoding='utf-8')
    status, body = call(base + '/api/repair-outcome/' + job_id)
    assert status == 409 and 'changed' in body['error']
