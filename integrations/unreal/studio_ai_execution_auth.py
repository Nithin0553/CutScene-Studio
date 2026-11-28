"""Candidate-specific execution intent shared by the local host and editor.

This is a consistency and single-use gate for the trusted local workspace,
not cryptographic authentication against an attacker controlling the disk.
No engine APIs or model inference are used here.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

MAX_AGE = 120
FRESH_LEVEL = '/Game/CutSceneAI/AutoTransfer/L_Studio_Fresh'
APPROVAL_FILE = 'ai-execution-authorization.json'
PROOF_KEYS = (
    'kind', 'status', 'session_id', 'session_sha256', 'automatic_setup_sha256',
    'artifact_sha256', 'observed_project', 'observed_level', 'sequence_path',
    'planned_actor_count', 'planned_import_count', 'verified_native_mesh_paths',
    'native_import_readback_pending', 'execution_authorized',
    'engine_generation_executed', 'behavioral_fidelity_established',
)


def snapshot(path):
    raw = path.read_bytes()
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise TypeError('Expected an authorization evidence object.')
    return value, hashlib.sha256(raw).hexdigest()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh(timestamp):
    age = (datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds()
    return 0 <= age < MAX_AGE


def valid_id(value):
    return isinstance(value, str) and len(value) == 32 and all(
        ch in '0123456789abcdef' for ch in value)


def fresh_map_path_available(config):
    """Read-only check for a canonical, unoccupied destination on disk."""
    if config['level_path'] != FRESH_LEVEL:
        return False
    content = Path(config['target_project']).parent / 'Content'
    stem = content / 'CutSceneAI' / 'AutoTransfer' / 'L_Studio_Fresh'
    external = [content / name / 'CutSceneAI' / 'AutoTransfer' / 'L_Studio_Fresh'
                for name in ('__ExternalActors__', '__ExternalObjects__')]
    return not any(path.exists() or path.is_symlink() for path in (
        stem.with_suffix('.umap'), stem.with_suffix('.uasset'), *external))


def level_binding_matches(config, request, report):
    """Match existing-map evidence or an explicit fresh-map request."""
    if not config.get('auto_create_level'):
        return (report.get('observed_level') == config['level_path']
                and report.get('create_level', False) is False
                and report.get('expected_level', config['level_path']) == config['level_path'])
    observed = report.get('observed_level')
    return (fresh_map_path_available(config)
            and isinstance(observed, str) and bool(observed)
            and observed != config['level_path']
            and request.get('create_level') is True
            and request.get('expected_level') == config['level_path']
            and request.get('observed_level') == observed
            and report.get('create_level') is True
            and report.get('expected_level') == config['level_path']
            and report.get('new_level_preflight') == {
                'current_world_clean': True, 'target_map_absent': True,
                'level_creation_api_available': True})


def binding(folder, candidate_id, worker_instance, worker_hash):
    """Recheck the exact records that an explicit inspection authorized."""
    folder = Path(folder)
    if (not isinstance(candidate_id, str) or not candidate_id.isascii()
            or not candidate_id.replace('_', '').isalnum()):
        raise ValueError('Invalid AI candidate identity.')
    active, active_hash = snapshot(folder / 'active-candidate.json')
    config, config_hash = snapshot(folder / 'connection.json')
    root = (folder / 'candidates').resolve()
    candidate = (root / candidate_id).resolve()
    if (active.get('candidate_id') != candidate_id or not active.get('ai_analysis')
            or candidate.parent != root
            or candidate != Path(active['candidate_dir']).resolve()
            or active.get('automatic_setup', {}).get('ready') is not True
            or config.get('source_rights_confirmed') is not True):
        raise ValueError('AI execution requires the current automatic-setup candidate and source rights.')
    request, request_hash = snapshot(folder / 'ai-native-preflight-request.json')
    response, response_hash = snapshot(folder / 'ai-native-preflight-response.json')
    report, report_hash = snapshot(folder / 'ai-native-preflight.json')
    request_id = request.get('request_id')
    if (not valid_id(request_id)
            or request.get('kind') != 'cutsceneai.studio.ai_native_preflight_request'
            or request.get('candidate_id') != candidate_id
            or response.get('request_id') != request_id
            or report.get('request_id') != request_id
            or response.get('status') != 'AI_NATIVE_PREFLIGHT_COMPLETED'
            or response.get('execution_authorized') is not False
            or report.get('kind') != 'cutsceneai.studio.ai_native_preflight'
            or report.get('status') != 'AI_NATIVE_SETUP_PREFLIGHT_PASSED'
            or report.get('candidate_id') != candidate_id
            or not fresh(report['checked_at'])
            or not fresh(request['requested_at'])):
        raise ValueError('A fresh, explicitly requested native inspection is required.')
    for record in (request, report):
        if (not worker_instance or record.get('worker_instance_id') != worker_instance
                or record.get('worker_source_sha256') != worker_hash
                or record.get('candidate_record_sha256') != active_hash
                or record.get('connection_sha256') != config_hash):
            raise ValueError('Inspection belongs to a different worker or candidate.')
    if any(report.get(key) is not False for key in (
            'execution_authorized', 'engine_generation_executed',
            'behavioral_fidelity_established')):
        raise ValueError('Inspection must remain read-only evidence.')
    session, session_hash = snapshot(candidate / 'session.json')
    setup_hash = digest(candidate / 'automatic-setup.json')
    target = session['target']
    if (not session.get('ai_analysis')
            or session_hash != report.get('session_sha256')
            or setup_hash != report.get('automatic_setup_sha256')
            or session['session_id'] != report.get('session_id')
            or session['source']['csir_path'] != config['csir']
            or target['mapping_path'] != active['mapping_copy']
            or target['sequence_asset_path'] != active['sequence_path']
            or target['sequence_asset_path'] != report.get('sequence_path')
            or os.path.normcase(str(target.get('project_path') or '')) != os.path.normcase(config['target_project'])
            or os.path.normcase(str(report.get('observed_project') or '')) != os.path.normcase(config['target_project'])
            or not level_binding_matches(config, request, report)):
        raise ValueError('Inspected session or destination changed.')
    mapping, _ = snapshot(Path(target['mapping_path']))
    lineage = mapping.get('studio_repair_lineage')
    if lineage is not None and (config.get('auto_create_level') or lineage.get('target_level') != config['level_path']):
        raise ValueError('Repair execution requires its separate approved staging level.')
    artifacts = session['artifact_sha256']
    if (set(artifacts) != {'ai-handoff.json', 'coverage-report.json', 'evidence.json', 'transfer-plan.json'}
            or artifacts != report.get('artifact_sha256')
            or any(digest(candidate / name) != sha for name, sha in artifacts.items())):
        raise ValueError('Inspected artifact changed.')
    inputs = [(session['source']['csir_path'], session['source']['sha256']),
              (target['mapping_path'], target['mapping_sha256']),
              (session['ai_analysis']['path'], session['ai_analysis']['sha256'])]
    capture = session.get('source_capture')
    if (capture['path'] if capture else '') != (config.get('capture') or ''):
        raise ValueError('Source capture differs from connection.')
    if capture:
        inputs.append((capture['path'], capture['sha256']))
    if any(digest(Path(path)) != sha for path, sha in inputs):
        raise ValueError('Inspected source evidence changed.')
    hashes = {
        'active-candidate.json': active_hash, 'connection.json': config_hash,
        'ai-native-preflight-request.json': request_hash,
        'ai-native-preflight-response.json': response_hash,
        'ai-native-preflight.json': report_hash,
    }
    if any(digest(folder / name) != sha for name, sha in hashes.items()):
        raise ValueError('Inspection records changed during authorization.')
    if digest(candidate / 'session.json') != session_hash or digest(candidate / 'automatic-setup.json') != setup_hash:
        raise ValueError('Inspected session changed during authorization.')
    return {
        'candidate_id': candidate_id, 'request_id': request_id,
        'worker_instance_id': worker_instance, 'worker_source_sha256': worker_hash,
        'record_sha256': hashes, 'session_sha256': session_hash,
        'automatic_setup_sha256': setup_hash, 'artifact_sha256': artifacts,
    }, report, config, session


def validate(folder, candidate_id, worker_instance, worker_hash, approval_id):
    """Validate a persisted explicit authorization and all current bindings."""
    if not valid_id(approval_id):
        raise ValueError('AI candidate native execution is not enabled without explicit authorization.')
    approval, approval_hash = snapshot(Path(folder) / APPROVAL_FILE)
    if (approval.get('kind') != 'cutsceneai.studio.ai_execution_authorization'
            or approval.get('approval_id') != approval_id
            or not fresh(approval['approved_at'])):
        raise ValueError('AI execution authorization is stale or invalid.')
    current, report, config, session = binding(folder, candidate_id, worker_instance, worker_hash)
    if approval.get('binding') != current:
        raise ValueError('AI execution authorization no longer matches inspected evidence.')
    if digest(Path(folder) / APPROVAL_FILE) != approval_hash:
        raise ValueError('AI execution authorization changed during verification.')
    return approval_hash, report, config, session


def match_fresh_proof(report, proof):
    """Compare an independent editor inspection with the authorized report."""
    keys = PROOF_KEYS
    if report.get('create_level') or proof.get('create_level'):
        keys += ('create_level', 'expected_level', 'new_level_preflight')
    if any(key not in report or key not in proof or report[key] != proof[key]
           for key in keys):
        raise ValueError('Fresh native inspection differs from authorized inspection.')
