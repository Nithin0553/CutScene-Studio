"""Two-folder Studio connection tests; no installed Unity/Unreal required."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import studio_project_discovery as d


def _projects(tmp_path, count=1):
    unity = tmp_path/'Unity'; (unity/'Assets'/'Benchmark002').mkdir(parents=True)
    (unity/'ProjectSettings').mkdir()
    exports=unity/'CutsceneAI'/'Exports';exports.mkdir(parents=True)
    unreal=tmp_path/'Unreal';(unreal/'Content'/'CutSceneAI'/'Tests').mkdir(parents=True)
    (unreal/'Trial.uproject').write_text('{}')
    (unreal/'Content'/'CutSceneAI'/'Tests'/'L_Fresh.umap').write_bytes(b'level')
    csirs=[]
    for ix in range(count):
        obj={'schema_version':'0.1.0','source':{'engine':'unity'},'cutscene_id':f'cut-{ix}',
             'name':f'Cut {ix}', 'entities':[
                 {'entity_id':'char','name':'CharacterA','ced_type':'entity.character'},
                 {'entity_id':'cam','name':'CAM_A','ced_type':'entity.camera'},
                 {'entity_id':'prop','name':'PROP_MOVING','ced_type':'entity.prop'},
                 {'entity_id':'child','name':'PROP_CHILD','ced_type':'entity.prop','parent_entity_id':'prop'},
                 {'entity_id':'other','name':'Renderer','ced_type':'entity.mesh'}],
             'tracks':[{'ced_type':'animation.track','binding_entity_id':'char','sections':[
                 {'payload':{'asset_id':'walk'},'start':{'value':0,'rate':{'numerator':1,'denominator':1}},'end':{'value':1,'rate':{'numerator':1,'denominator':1}}}]},
                 {'ced_type':'camera.cut','binding_entity_id':'cam','sections':[{}]},
                 {'ced_type':'animation.track','binding_entity_id':'prop','sections':[{}]}],
             'assets':[{'asset_id':'walk','name':'Walk'}]}
        p=exports/f'Timeline{ix}.csir.json';p.write_text(json.dumps(obj));csirs.append(p)
    return unity,unreal,csirs


def test_two_folders_detect_exports_maps_and_generate_source_mapping(tmp_path):
    u, ue, csirs = _projects(tmp_path)
    x=d.discover(str(u),str(ue))
    assert x['ready'] and len(x['unity']['cutscenes'])==1
    assert x['unreal']['levels']==['/Game/CutSceneAI/Tests/L_Fresh']
    connection=d.build_connection(str(u),str(ue),str(csirs[0]),x['unreal']['levels'][0],workspace=tmp_path/'workspace',source_rights_confirmed=True)
    generated=json.loads(Path(connection['mapping']).read_text())
    assert connection['source_scope']=='Assets'
    assert generated['overwrite_sequence'] is False
    assert set(generated['entities']) == {'CharacterA','CAM_A','PROP_MOVING','PROP_CHILD'}
    assert all(x['actor_label'].startswith('CSAI_') for x in generated['entities'].values())
    assert generated['assets']['Walk'].endswith('/Animations/CSAI_Walk')
    assert not (u/'CutsceneAI'/'Exports'/'mapping.json').exists()
    assert not (ue/'Content'/'mapping.json').exists()
    # Repeat connection does not alter the frozen generated mapping.
    assert d.build_connection(str(u),str(ue),str(csirs[0]),x['unreal']['levels'][0],workspace=tmp_path/'workspace')['mapping']==connection['mapping']


def test_multiple_timelines_return_choices_not_guessed(tmp_path):
    u, ue, csirs=_projects(tmp_path,2)
    result=d.discover(str(u),str(ue))
    assert len(result['unity']['cutscenes'])==2
    for file in csirs:
        assert any(x['path']==str(file.resolve()) for x in result['unity']['cutscenes'])
    with pytest.raises(d.DiscoveryError,match='not a verified export'):
        d.build_connection(str(u),str(ue),str(tmp_path/'foreign.csir.json'),result['unreal']['levels'][0],workspace=tmp_path/'runs')


def test_wrong_folder_missing_export_or_missing_map_not_faked(tmp_path):
    u, ue, csirs=_projects(tmp_path)
    assert d.scan_unity(str(u/'Assets'))['folder'] == str(u.resolve())
    csirs[0].unlink()
    assert not d.scan_unity(str(u))['cutscenes']
    (ue/'Content'/'CutSceneAI'/'Tests'/'L_Fresh.umap').unlink()
    candidate=d.scan_unreal(str(ue))
    assert candidate['new_level_required']
    assert candidate['levels']==['/Game/CutSceneAI/AutoTransfer/L_Studio_Fresh']


def test_invalid_level_and_ambiguous_unreal_project_are_refused(tmp_path):
    u, ue, csirs=_projects(tmp_path)
    with pytest.raises(d.DiscoveryError,match='not part'):
        d.build_connection(str(u),str(ue),str(csirs[0]),'/Game/Other',workspace=tmp_path/'runs')
    (ue/'Other.uproject').write_text('{}')
    choices=d.scan_unreal(str(ue))
    assert len(choices['project_options'])==2 and not choices['project']
    assert not d.discover(str(u),str(ue))['ready']
    assert d.discover(str(u),str(ue),unreal_project=str(ue/'Trial.uproject'))['ready']


def test_folder_picker_cancel_and_no_non_windows_secret_path(monkeypatch):
    monkeypatch.setattr(d.sys,'platform','linux')
    with pytest.raises(d.DiscoveryError,match='Windows'):
        d.browse_project_folder('unity')
    with pytest.raises(d.DiscoveryError,match='Unity or Unreal'):
        d.browse_project_folder('credentials')


def test_discovery_selects_owned_static_geometry_and_lights_not_renderer_children(tmp_path):
    unity, unreal, csirs = _projects(tmp_path)
    src = json.loads(csirs[0].read_text())
    pose = {'position': {'x': 0, 'y': 0, 'z': 0},
            'rotation': {'x': 0, 'y': 0, 'z': 0, 'w': 1},
            'scale': {'x': 1, 'y': 1, 'z': 1}}

    def actor(eid, name, kind, path, parent='', active=True, mesh=False):
        metadata = {'hierarchy_path': path, 'active_self': active, 'world_transform': pose}
        if mesh:
            metadata['source_model_assets'] = [{
                'asset_path': 'Library/unity default resources',
                'guid': '0000000000000000e000000000000000',
                'renderer_path': path, 'mesh_name': 'Cube',
            }]
        return {'entity_id': eid, 'name': name, 'ced_type': kind,
                'parent_entity_id': parent, 'metadata': metadata}

    group = actor('group', 'Set', 'entity.prop', 'Set')
    floor = actor('floor', 'Ground', 'entity.prop', 'Set/Ground', 'group', mesh=True)
    group['metadata']['source_model_assets'] = floor['metadata']['source_model_assets']
    light = actor('sun', 'Sun', 'entity.light', 'Sun')
    light['metadata']['light'] = {'light_type': 'Directional'}
    inactive = actor('inactive', 'Hidden', 'entity.prop', 'Hidden', active=False)
    child = actor('hidden_mesh', 'HiddenMesh', 'entity.prop', 'Hidden/Mesh',
                  'inactive', mesh=True)
    renderer = actor('render', 'Body', 'entity.character', 'CharacterA/Body', 'char', mesh=True)
    rig_prop = actor('rigprop', 'RigMesh', 'entity.prop', 'CharacterA/Body/RigMesh',
                     'render', mesh=True)
    audio = actor('audio', 'Audio', 'entity.audio_source', 'Audio')
    ambiguous = actor('ambiguous', 'MultiMesh', 'entity.prop', 'MultiMesh', mesh=True)
    ambiguous['metadata']['source_model_assets'].append({
        'renderer_path': 'MultiMesh/Child', 'mesh_name': 'Cube',
        'asset_path': 'Library/unity default resources',
        'guid': '0000000000000000e000000000000000',
    })
    src['entities'].extend([group, floor, light, inactive, child, renderer, rig_prop, audio,
                            ambiguous])
    csirs[0].write_text(json.dumps(src))
    workspace = tmp_path / 'runs'
    connection = d.build_connection(
        str(unity), str(unreal), str(csirs[0]), '/Game/CutSceneAI/Tests/L_Fresh',
        workspace=workspace, source_rights_confirmed=True,
    )
    path = Path(connection['mapping'])
    mapping = json.loads(path.read_text())
    assert set(mapping['entities']) == {
        'CharacterA', 'CAM_A', 'PROP_MOVING', 'PROP_CHILD', 'Ground', 'Sun',
    }
    old_bytes = path.read_bytes()
    # A changed source/mapping creates a new file, never rewriting the old mapping.
    floor['metadata']['active_self'] = False
    csirs[0].write_text(json.dumps(src))
    next_connection = d.build_connection(
        str(unity), str(unreal), str(csirs[0]), '/Game/CutSceneAI/Tests/L_Fresh',
        workspace=workspace, source_rights_confirmed=True,
    )
    assert next_connection['mapping'] != connection['mapping']
    assert path.read_bytes() == old_bytes
    assert 'Ground' not in json.loads(Path(next_connection['mapping']).read_text())['entities']
