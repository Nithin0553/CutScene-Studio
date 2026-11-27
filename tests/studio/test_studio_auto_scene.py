"""Exercise the automatic importer without requiring a running Unreal Editor."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'integrations'/'unreal'))
sys.path.insert(0,str(ROOT/'tools'))
import studio_auto_assets
import studio_auto_scene as scene
from test_studio_auto_assets import create


class Asset:
    def __init__(self,klass,path):
        self.klass,self.path=klass,path
        self.skeleton=None
    def get_class(self): return SimpleNamespace(get_name=lambda:self.klass)
    def get_editor_property(self,name):
        if name=='skeleton': return self.skeleton
        raise ValueError(name)
    def get_path_name(self): return self.path


class Task:
    def __init__(self): self.props={}
    def set_editor_property(self,name,value): self.props[name]=value


class Actor:
    def __init__(self,label=''):
        self.label=label
    def get_actor_label(self): return self.label
    def set_actor_label(self,label,mark_dirty=False): self.label=label


class Actors:
    def __init__(self): self.actors=[]
    def get_all_level_actors(self): return self.actors
    def spawn_actor_from_object(self,obj,loc,rot):
        x=Actor();self.actors.append(x);return x
    def spawn_actor_from_class(self,cls,loc,rot):
        x=Actor();x.native_class=cls;self.actors.append(x);return x


class FakeUnreal:
    def __init__(self,project):
        self.project=project
        self.assets={}
        self.actor_sys=Actors()
        self.asset_tools=SimpleNamespace(import_asset_tasks=self.imports)
        self.Paths=SimpleNamespace(get_project_file_path=lambda:self.project)
        self.UnrealEditorSubsystem=object()
        self.EditorActorSubsystem=object()
        self.EditorAssetLibrary=SimpleNamespace(does_asset_exist=lambda p:p in self.assets)
        self.AssetToolsHelpers=SimpleNamespace(get_asset_tools=lambda:self.asset_tools)
        self.AssetImportTask=Task
        self.FbxImportUI=Task
        self.FBXImportType=SimpleNamespace(FBXIT_ANIMATION=1,FBXIT_SKELETAL_MESH=2,FBXIT_STATIC_MESH=3)
        self.CineCameraActor=object()
        self.PointLight=type('PointLight', (), {})
        self.SpotLight=type('SpotLight', (), {})
        self.DirectionalLight=type('DirectionalLight', (), {})
        self.Actor=object()
        self.Vector=lambda *args:args
        self.Rotator=lambda *args:args
        self.LevelEditorSubsystem=object()
        self.levelsaver=SimpleNamespace(save_current_level=lambda:True)
        self.world=SimpleNamespace(get_path_name=lambda:'/Game/Tests/L_Test.L_Test')
    def get_editor_subsystem(self,kind):
        if kind is self.UnrealEditorSubsystem: return SimpleNamespace(get_editor_world=lambda:self.world)
        if kind is self.EditorActorSubsystem: return self.actor_sys
        if kind is self.LevelEditorSubsystem: return self.levelsaver
        raise AssertionError('Unknown subsystem')
    def load_asset(self,path): return self.assets.get(path)
    def imports(self,tasks):
        for task in tasks:
            opt=task.props.get('options')
            cls=('AnimSequence' if opt and opt.props.get('import_animations') else ('SkeletalMesh' if opt.props.get('import_as_skeletal') else 'StaticMesh') if opt else
                 'SoundWave' if task.props['filename'].endswith(('.wav', '.mp3')) else 'Texture2D')
            path=task.props['destination_path']+'/'+task.props['destination_name']
            asset=Asset(cls,path)
            if cls=='SkeletalMesh':
                skeleton=Asset('Skeleton',path+'_Skeleton')
                asset.skeleton=skeleton
            if cls=='AnimSequence': asset.skeleton=opt.props['skeleton']
            self.assets[path]=asset


def test_auto_setup_imports_and_spawns_without_prior_unreal_actors(tmp_path):
    root,files=create(tmp_path)
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002','/Game/CutSceneAI/AutoTransfer/T_ABC')
    manifest=tmp_path/'auto-setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    unreal=FakeUnreal(str(project))
    receipt=scene.run(str(manifest),str(tmp_path/'auto-receipt.json'),
                      csir_path=str(files[0]),mapping_path=str(files[1]),plan_path=str(files[2]),
                      expected_project=str(project),expected_level='/Game/Tests/L_Test',unreal_api=unreal)
    assert receipt['status']=='SETUP_SAVED_UNVERIFIED'
    assert receipt['level_saved']
    assert len(receipt['actors_created'])==5
    assert len(receipt['assets_imported'])==6
    assert len(unreal.actor_sys.actors)==5
    assert receipt['fidelity_verified'] is False


def test_wrong_project_never_starts_import(tmp_path):
    root,files=create(tmp_path)
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002','/Game/CutSceneAI/AutoTransfer/T_ABC')
    manifest=tmp_path/'auto-setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    output=tmp_path/'auto-receipt.json'
    with pytest.raises(scene.AutomaticSetupError,match='Wrong Unreal project'):
        scene.run(str(manifest),str(output),csir_path=str(files[0]),mapping_path=str(files[1]),
                  plan_path=str(files[2]),expected_project=str(tmp_path/'Other.uproject'),
                  expected_level='/Game/Tests/L_Test',unreal_api=fake)
    assert json.loads(output.read_text())['status']=='BLOCKED'
    assert not fake.actor_sys.actors and not fake.assets


def test_collision_is_detected_before_any_mutation(tmp_path):
    root,files=create(tmp_path)
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002','/Game/CutSceneAI/AutoTransfer/T_ABC')
    manifest=tmp_path/'auto-setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    collision=stage['imports'][0]['target_asset_path'];fake.assets[collision]=Asset('SkeletalMesh',collision)
    output=tmp_path/'auto-receipt.json'
    with pytest.raises(scene.AutomaticSetupError,match='refuses existing target asset'):
        scene.run(str(manifest),str(output),csir_path=str(files[0]),mapping_path=str(files[1]),
                  plan_path=str(files[2]),expected_project=str(project),
                  expected_level='/Game/Tests/L_Test',unreal_api=fake)
    assert json.loads(output.read_text())['status']=='BLOCKED'
    assert not fake.actor_sys.actors


def test_prop_mesh_staged_as_static_mesh_when_source_is_identified(tmp_path):
    root, files = create(tmp_path)
    (root/'Assets'/'Benchmark002'/'Characters'/'PROP_MOVING.fbx').write_bytes(b'prop-mesh')
    stage=studio_auto_assets.inspect(*files,root,'Assets','/Game/CutSceneAI/AutoTransfer/T_ABC')
    manifest=tmp_path/'auto-setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    unreal=FakeUnreal(str(project))
    receipt=scene.run(str(manifest),str(tmp_path/'auto-receipt.json'),
                      csir_path=str(files[0]),mapping_path=str(files[1]),plan_path=str(files[2]),
                      expected_project=str(project),expected_level='/Game/Tests/L_Test',unreal_api=unreal)
    assert receipt['status']=='SETUP_SAVED_UNVERIFIED'
    assert any(a['kind']=='StaticMesh' for a in receipt['assets_imported'])


def test_mp3_source_imports_directly_without_ffmpeg(tmp_path):
    root, files=create(tmp_path, missing_audio=True)
    (root/'Assets'/'Benchmark002'/'Audio'/'Cue.mp3').write_bytes(b'ID3'+bytes(20))
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002',
                                     '/Game/CutSceneAI/AutoTransfer/T_ABC')
    manifest=tmp_path/'auto-setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    receipt=scene.run(str(manifest),str(tmp_path/'receipt.json'),
                      csir_path=str(files[0]),mapping_path=str(files[1]),
                      plan_path=str(files[2]),expected_project=str(project),
                      expected_level='/Game/Tests/L_Test',unreal_api=fake)
    assert receipt['status']=='SETUP_SAVED_UNVERIFIED'
    assert any(row['kind']=='SoundWave' for row in receipt['assets_imported'])
    assert len(fake.actor_sys.actors)==5


def test_duplicate_planned_label_blocks_before_any_import(tmp_path):
    root, files=create(tmp_path)
    plan=json.loads(files[2].read_text())
    plan['bindings']['CAM_A_Wide']=plan['bindings']['Ch26_nonPBR']
    files[2].write_text(json.dumps(plan))
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002',
                                     '/Game/CutSceneAI/AutoTransfer/T_SAFE')
    assert not stage['ready']
    assert any('Duplicate planned Unreal actor label' in x for x in stage['blockers'])
    manifest=tmp_path/'setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    receipt=tmp_path/'receipt.json'
    with pytest.raises(scene.AutomaticSetupError,match='cannot be automatically staged'):
        scene.run(str(manifest),str(receipt),csir_path=str(files[0]),
                  mapping_path=str(files[1]),plan_path=str(files[2]),
                  expected_project=str(project),expected_level='/Game/Tests/L_Test',
                  unreal_api=fake)
    assert not fake.assets and not fake.actor_sys.actors
    assert json.loads(receipt.read_text())['status']=='BLOCKED'


def test_existing_target_namespace_is_blocked_before_mutation(tmp_path):
    root,files=create(tmp_path)
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002',
                                     '/Game/CutSceneAI/AutoTransfer/T_SAFE')
    manifest=tmp_path/'setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    fake.EditorAssetLibrary.does_directory_exist=lambda path:path==stage['target_folder']
    receipt=tmp_path/'receipt.json'
    with pytest.raises(scene.AutomaticSetupError,match='namespace already exists'):
        scene.run(str(manifest),str(receipt),csir_path=str(files[0]),
                  mapping_path=str(files[1]),plan_path=str(files[2]),
                  expected_project=str(project),expected_level='/Game/Tests/L_Test',
                  unreal_api=fake)
    result=json.loads(receipt.read_text())
    assert result['status']=='BLOCKED' and not result['changes_possible']
    assert not fake.assets and not fake.actor_sys.actors


def test_partial_import_failure_keeps_precise_no_retry_receipt(tmp_path):
    root,files=create(tmp_path)
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002',
                                     '/Game/CutSceneAI/AutoTransfer/T_SAFE')
    manifest=tmp_path/'setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    native_import=fake.imports
    calls=[0]

    def fail_on_second(tasks):
        calls[0]+=1
        if calls[0]==2:
            raise RuntimeError('Native import failed halfway')
        return native_import(tasks)

    fake.asset_tools=SimpleNamespace(import_asset_tasks=fail_on_second)
    receipt_path=tmp_path/'partial.json'
    with pytest.raises(RuntimeError,match='failed halfway'):
        scene.run(str(manifest),str(receipt_path),csir_path=str(files[0]),
                  mapping_path=str(files[1]),plan_path=str(files[2]),
                  expected_project=str(project),expected_level='/Game/Tests/L_Test',
                  unreal_api=fake)
    receipt=json.loads(receipt_path.read_text())
    assert receipt['status']=='PARTIAL_SETUP_MUST_INSPECT'
    assert receipt['changes_possible']
    assert len(receipt['assets_imported'])==1
    assert receipt['asset_operations'][0]['status']=='NATIVE_CLASS_CHECKED'
    assert receipt['asset_operations'][1]['status']=='IMPORT_STARTED'
    assert len([x for x in receipt['asset_operations'] if x['status']=='NOT_STARTED'])==4
    assert all(x['status']=='NOT_STARTED' for x in receipt['actor_operations'])
    assert receipt['failed_step']['phase']=='asset_import'
    assert 'Do not rerun' in receipt['recovery']
    assert not fake.actor_sys.actors


def test_success_receipt_has_no_unreported_operations(tmp_path):
    root,files=create(tmp_path)
    stage=studio_auto_assets.inspect(*files,root,'Assets/Benchmark002',
                                     '/Game/CutSceneAI/AutoTransfer/T_SAFE')
    manifest=tmp_path/'setup.json';manifest.write_text(json.dumps(stage))
    project=tmp_path/'NewProject.uproject';project.write_text('{}')
    fake=FakeUnreal(str(project))
    receipt=scene.run(str(manifest),str(tmp_path/'receipt.json'),
                      csir_path=str(files[0]),mapping_path=str(files[1]),plan_path=str(files[2]),
                      expected_project=str(project),expected_level='/Game/Tests/L_Test',
                      unreal_api=fake)
    assert receipt['status']=='SETUP_SAVED_UNVERIFIED'
    assert receipt['failed_step'] is None
    assert all(x['status']=='NATIVE_CLASS_CHECKED' for x in receipt['asset_operations'])
    assert all(x['status']=='ACTOR_LABEL_CHECKED' for x in receipt['actor_operations'])
    assert len(receipt['assets_imported'])==len(receipt['asset_operations'])
    assert len(receipt['actors_created'])==len(receipt['actor_operations'])


def test_optin_fbx_material_import_only_changes_fresh_mesh_imports(tmp_path):
    root, files = create(tmp_path)
    mapping_path = Path(files[1])
    original = mapping_path.read_text(encoding="utf-8")
    src = json.loads(original)
    src["enable_fbx_embedded_material_import"] = True
    mapping_path.write_text(json.dumps(src), encoding="utf-8")
    stage = studio_auto_assets.inspect(
        *files, root, "Assets/Benchmark002", "/Game/CutSceneAI/AutoTransfer/T_VISUAL"
    )
    assert stage["fbx_embedded_material_import_requested"] is True
    assert any("Opt-in FBX material import" in warning for warning in stage["warnings"])
    manifest = tmp_path / "visual-setup.json"
    manifest.write_text(json.dumps(stage))
    project = tmp_path / "VisualProject.uproject"
    project.write_text("{}")
    fake = FakeUnreal(str(project))
    imported = []
    original_import = fake.imports

    def record(tasks):
        imported.extend(tasks)
        return original_import(tasks)

    fake.asset_tools.import_asset_tasks = record
    receipt = scene.run(
        str(manifest), str(tmp_path / "visual-receipt.json"),
        csir_path=str(files[0]), mapping_path=str(files[1]),
        plan_path=str(files[2]), expected_project=str(project),
        expected_level="/Game/Tests/L_Test", unreal_api=fake,
    )
    assert receipt["fbx_embedded_material_import_requested"] is True
    assert receipt["status"] == "SETUP_SAVED_UNVERIFIED"
    options = [t.props.get("options") for t in imported if t.props.get("options")]
    assert options
    for option in options:
        mesh = option.props["import_mesh"]
        assert option.props["import_materials"] is bool(mesh)
        assert option.props["import_textures"] is bool(mesh)
    assert receipt["fidelity_verified"] is False


def test_default_fbx_material_import_remains_off_for_existing_workflows():
    fake = FakeUnreal("C:/Unreal/Mock.uproject")
    for kind in ("SkeletalMesh", "StaticMesh", "AnimSequence"):
        task = scene._task(fake, "C:/Original.fbx", "/Game/Candidate/Mesh", kind)
        options = task.props["options"]
        assert options.props["import_materials"] is False
        assert options.props["import_textures"] is False


def test_material_optin_is_only_accepted_as_explicit_boolean():
    import studio_ui_features

    assert studio_ui_features.validate_options(
        {}, {"enable_fbx_embedded_material_import": True}
    ) == {"enable_fbx_embedded_material_import": True}
    with pytest.raises(ValueError, match="must be Boolean"):
        studio_ui_features.validate_options(
            {}, {"enable_fbx_embedded_material_import": "yes"}
        )



@pytest.mark.parametrize(("source_type", "target_class"), [
    ("Directional", "DirectionalLight"),
    ("Spot", "SpotLight"),
    ("Point", "PointLight"),
])
def test_source_light_type_controls_native_unreal_actor_class(
    tmp_path, source_type, target_class,
):
    root, files = create(tmp_path)
    csir = json.loads(files[0].read_text())
    for item in csir["entities"]:
        if item["ced_type"] == "entity.light":
            item["metadata"] = {"light": {"light_type": source_type}}
    files[0].write_text(json.dumps(csir))
    stage = studio_auto_assets.inspect(
        *files, root, "Assets/Benchmark002", "/Game/CutSceneAI/AutoTransfer/T_ABC",
    )
    assert stage["ready"] is True
    light = next(row for row in stage["actors"] if row["kind"] == "entity.light")
    assert light["source_light_type"] == source_type
    assert light["target_light_class"] == target_class
    manifest = tmp_path / "auto-setup.json"
    manifest.write_text(json.dumps(stage))
    project = tmp_path / "NewProject.uproject"
    project.write_text("{}")
    api = FakeUnreal(str(project))
    receipt = scene.run(
        str(manifest), str(tmp_path / "auto-receipt.json"),
        csir_path=str(files[0]), mapping_path=str(files[1]),
        plan_path=str(files[2]), expected_project=str(project),
        expected_level="/Game/Tests/L_Test", unreal_api=api,
    )
    assert receipt["status"] == "SETUP_SAVED_UNVERIFIED"
    native = next(actor for actor in api.actor_sys.actors if actor.label == light["label"])
    assert native.native_class is getattr(api, target_class)
    assert receipt["fidelity_verified"] is False


def test_missing_native_light_class_blocks_before_import_or_spawn(tmp_path):
    root, files = create(tmp_path)
    csir = json.loads(files[0].read_text())
    next(item for item in csir["entities"] if item["ced_type"] == "entity.light")[
        "metadata"
    ] = {"light": {"light_type": "Directional"}}
    files[0].write_text(json.dumps(csir))
    stage = studio_auto_assets.inspect(
        *files, root, "Assets/Benchmark002", "/Game/CutSceneAI/AutoTransfer/T_ABC",
    )
    manifest = tmp_path / "auto-setup.json"
    manifest.write_text(json.dumps(stage))
    project = tmp_path / "NewProject.uproject"
    project.write_text("{}")
    api = FakeUnreal(str(project))
    del api.DirectionalLight
    with pytest.raises(scene.AutomaticSetupError, match="native light class unavailable"):
        scene.run(
            str(manifest), str(tmp_path / "auto-receipt.json"),
            csir_path=str(files[0]), mapping_path=str(files[1]),
            plan_path=str(files[2]), expected_project=str(project),
            expected_level="/Game/Tests/L_Test", unreal_api=api,
        )
    assert not api.assets
    assert not api.actor_sys.actors


def test_unsupported_source_light_type_is_source_asset_blocker(tmp_path):
    root, files = create(tmp_path)
    csir = json.loads(files[0].read_text())
    next(item for item in csir["entities"] if item["ced_type"] == "entity.light")[
        "metadata"
    ] = {"light": {"light_type": "Area"}}
    files[0].write_text(json.dumps(csir))
    stage = studio_auto_assets.inspect(
        *files, root, "Assets/Benchmark002", "/Game/CutSceneAI/AutoTransfer/T_ABC",
    )
    assert stage["ready"] is False
    assert any("Unsupported Unity light type" in v for v in stage["blockers"])


@pytest.mark.parametrize("variant", ["valid", "missing", "wrong_class", "wrong_bounds"])
def test_builtin_cube_is_verified_before_any_import_or_spawn(tmp_path, variant):
    root, files = create(tmp_path)
    csir = json.loads(files[0].read_text())
    prop = next(e for e in csir['entities'] if e['ced_type'] == 'entity.prop')
    prop['metadata'] = {
        'hierarchy_path': prop['name'],
        'source_model_assets': [{
            'asset_path': 'Library/unity default resources',
            'guid': '0000000000000000e000000000000000',
            'renderer_path': prop['name'], 'mesh_name': 'Cube',
        }],
    }
    files[0].write_text(json.dumps(csir))
    stage = studio_auto_assets.inspect(
        *files, root, 'Assets/Benchmark002', '/Game/CutSceneAI/AutoTransfer/T_CUBE',
    )
    path = '/Engine/BasicShapes/Cube.Cube'
    row = next(r for r in stage['actors'] if r['name'] == prop['name'])
    assert stage['ready']
    assert row['source_primitive'] == 'unity_builtin_cube'
    assert row['mesh_path'] == path
    assert all(item['target_asset_path'] != path for item in stage['imports'])
    assert not any('transform-only' in item for item in stage['warnings'])
    manifest = tmp_path / 'cube-setup.json'
    manifest.write_text(json.dumps(stage))
    project = tmp_path / 'Trial.uproject'
    project.write_text('{}')
    fake = FakeUnreal(str(project))
    fake.StaticMeshComponent = object()
    if variant != 'missing':
        obj = Asset('SkeletalMesh' if variant == 'wrong_class' else 'StaticMesh', path)
        obj.get_bounds = lambda: SimpleNamespace(
            origin=SimpleNamespace(x=0, y=0, z=0),
            box_extent=SimpleNamespace(x=49 if variant == 'wrong_bounds' else 50, y=50, z=50),
        )
        fake.assets[path] = obj
    spawn = fake.actor_sys.spawn_actor_from_object

    def spawn_with_mesh(obj, loc, rot):
        actor = spawn(obj, loc, rot)
        actor.get_component_by_class = lambda _: SimpleNamespace(
            get_editor_property=lambda _: obj,
        )
        return actor

    fake.actor_sys.spawn_actor_from_object = spawn_with_mesh
    receipt_file = tmp_path / 'receipt.json'

    def run():
        return scene.run(
            str(manifest), str(receipt_file), csir_path=str(files[0]),
            mapping_path=str(files[1]), plan_path=str(files[2]),
            expected_project=str(project), expected_level='/Game/Tests/L_Test',
            unreal_api=fake,
        )

    if variant == 'valid':
        receipt = run()
        assert receipt['status'] == 'SETUP_SAVED_UNVERIFIED'
        assert len(receipt['actors_created']) == 5
        assert all(item['path'] != path for item in receipt['assets_imported'])
        assert fake.assets[path] is obj
        assert not receipt['fidelity_verified']
    else:
        before = dict(fake.assets)
        with pytest.raises(scene.AutomaticSetupError, match='Cube'):
            run()
        assert fake.assets == before
        assert not fake.actor_sys.actors
        assert not json.loads(receipt_file.read_text())['changes_possible']


@pytest.mark.parametrize("change", ["guid", "mesh_name", "renderer_path"])
def test_builtin_cube_identity_does_not_guess_from_names(change):
    record = {
        'asset_path': 'Library/unity default resources',
        'guid': '0000000000000000e000000000000000',
        'renderer_path': 'CubeObject', 'mesh_name': 'Cube',
    }
    entity = {'name': 'CubeObject', 'ced_type': 'entity.prop', 'metadata': {
        'hierarchy_path': 'CubeObject', 'source_model_assets': [record],
    }}
    assert studio_auto_assets.source_identity.is_unity_builtin_cube(entity)
    record[change] = 'unverified'
    assert not studio_auto_assets.source_identity.is_unity_builtin_cube(entity)


@pytest.mark.parametrize("case", [
    "valid", "unbound_project", "wrong_project", "wrong_level", "namespace",
    "sequence", "asset", "actor", "wrong_bounds",
    "new_valid", "new_dirty", "new_unknown_dirty", "new_exists", "new_disk_exists",
    "new_external_content", "new_wrong_path", "new_missing_api", "new_current_actor",
])
def test_read_only_ai_native_setup_preflight(tmp_path, monkeypatch, case):
    import studio_ai_native_preflight as preflight

    project = tmp_path / 'Staging.uproject'
    project.write_text('{}')
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    sequence = '/Game/Tests/LS_Fresh'
    asset = '/Game/Tests/Stage/Character'
    mesh_path = '/Engine/BasicShapes/Cube.Cube'
    session = {
        'session_id': 'fixture-session',
        'target': {
            'project_path': None if case == 'unbound_project' else str(project),
            'sequence_asset_path': sequence,
        },
    }
    setup = {
        'target_folder': '/Game/Tests/Stage',
        'imports': [{'target_asset_path': asset}],
        'actors': [
            {'label': 'Floor', 'kind': 'entity.prop', 'mesh_path': mesh_path,
             'source_primitive': 'unity_builtin_cube'},
            {'label': 'Sun', 'kind': 'entity.light', 'target_light_class': 'DirectionalLight'},
            {'label': 'Camera', 'kind': 'entity.camera'},
        ],
    }
    (candidate / 'session.json').write_text(json.dumps(session))
    (candidate / 'automatic-setup.json').write_text(json.dumps(setup))
    plan_path = candidate / 'transfer-plan.json'
    plan_path.write_text(json.dumps({'actions': []}))
    proof = {'session_id': 'fixture-session', 'artifact_sha256': {
        'ai-handoff.json': 'fixture', 'transfer-plan.json': preflight._snapshot(plan_path)[1]}}
    calls = []

    def replay(folder, *, require_setup):
        assert folder == candidate and require_setup is True
        calls.append(folder)
        return proof

    monkeypatch.setattr(preflight.studio_ai_verifier, 'verify_candidate', replay)
    fake = FakeUnreal(str(project))
    fake.EditorAssetLibrary.does_directory_exist = lambda _: case == 'namespace'
    fake.StaticMeshComponent = object()
    cube = Asset('StaticMesh', mesh_path)
    extent = 49 if case == 'wrong_bounds' else 50
    cube.get_bounds = lambda: SimpleNamespace(
        origin=SimpleNamespace(x=0, y=0, z=0),
        box_extent=SimpleNamespace(x=extent, y=50, z=50),
    )
    fake.assets[mesh_path] = cube
    if case == 'wrong_project':
        fake.project = str(tmp_path / 'Other.uproject')
    if case == 'wrong_level':
        fake.world.get_path_name = lambda: '/Game/Tests/Other.Other'
    if case == 'sequence':
        fake.assets[sequence] = Asset('LevelSequence', sequence)
    if case == 'asset':
        fake.assets[asset] = Asset('SkeletalMesh', asset)
    if case == 'actor':
        fake.actor_sys.actors.append(Actor('Floor'))

    new_level = case.startswith('new_')
    mutations = []
    if new_level:
        fake.world.get_outermost = lambda: SimpleNamespace(is_dirty=lambda: case == 'new_dirty')
        fake.EditorAssetLibrary.make_directory = lambda path: mutations.append(path)
        if case != 'new_missing_api':
            fake.levelsaver.new_level = lambda path: mutations.append(path)
        if case == 'new_unknown_dirty':
            del fake.world.get_outermost
        if case == 'new_exists':
            fake.assets[preflight.FRESH_LEVEL] = Asset('World', preflight.FRESH_LEVEL)
        if case == 'new_disk_exists':
            target = tmp_path / 'Content/CutSceneAI/AutoTransfer/L_Studio_Fresh.umap'
            target.parent.mkdir(parents=True)
            target.write_text('existing map')
        if case == 'new_external_content':
            (tmp_path / 'Content/__ExternalActors__/CutSceneAI/AutoTransfer/L_Studio_Fresh').mkdir(parents=True)
        if case == 'new_current_actor':
            fake.actor_sys.actors.append(Actor('Floor'))

    before = {p: p.read_bytes() for p in candidate.iterdir()}
    before_assets = dict(fake.assets)
    before_actors = list(fake.actor_sys.actors)
    kwargs = {
        'expected_project': str(project),
        'expected_level': '/Game/Tests/L_Test',
        'unreal_api': fake,
    }
    if new_level:
        kwargs.update(create_level=True, expected_level=(
            '/Game/Wrong' if case == 'new_wrong_path' else preflight.FRESH_LEVEL))
    if case in {'valid', 'new_valid', 'new_current_actor'}:
        result = preflight.inspect_candidate(candidate, **kwargs)
        if new_level:
            assert result['create_level'] is True
            assert result['expected_level'] == preflight.FRESH_LEVEL
            assert result['observed_level'] == '/Game/Tests/L_Test'
            assert result['new_level_preflight']['current_world_clean'] is True
        assert result['status'] == 'AI_NATIVE_SETUP_PREFLIGHT_PASSED'
        assert result['session_id'] == 'fixture-session'
        assert result['planned_actor_count'] == 3
        assert result['planned_import_count'] == 1
        assert result['verified_native_mesh_paths'] == [mesh_path]
        assert result['native_import_readback_pending'] is True
        assert result['execution_authorized'] is False
        assert result['engine_generation_executed'] is False
        assert result['behavioral_fidelity_established'] is False
    else:
        expected = {
            'unbound_project': 'not bound',
            'wrong_project': 'Wrong Unreal staging project',
            'wrong_level': 'Open the selected staging level',
            'namespace': 'namespace already exists',
            'sequence': 'Sequence path already occupied',
            'asset': 'Existing target import asset',
            'actor': 'Existing actor label',
            'wrong_bounds': 'Cube bounds differ',
            'new_dirty': 'unsaved changes',
            'new_unknown_dirty': 'Cannot confirm',
            'new_exists': 'Target level already exists',
            'new_disk_exists': 'already exists on disk',
            'new_external_content': 'already exists on disk',
            'new_wrong_path': 'noncanonical',
            'new_missing_api': 'level creation API unavailable',
        }[case]
        error_type = TypeError if case == 'new_missing_api' else (ValueError, RuntimeError, scene.AutomaticSetupError)
        with pytest.raises(error_type, match=expected):
            preflight.inspect_candidate(candidate, **kwargs)
    assert calls == ([] if case == 'unbound_project' else [candidate])
    assert {p: p.read_bytes() for p in candidate.iterdir()} == before
    assert fake.assets == before_assets
    assert fake.actor_sys.actors == before_actors
    assert not mutations


@pytest.mark.parametrize("case", ["valid", "missing_api", "invalid_source"])
def test_source_static_light_setup_is_manifest_bound_and_native_checked(tmp_path, case):
    from test_studio_light_properties import Actor as LightActor, Component

    root, files = create(tmp_path)
    csir = json.loads(files[0].read_text())
    light = next(row for row in csir["entities"] if row["ced_type"] == "entity.light")
    light["metadata"] = {"light": {
        "light_type": "Spot", "intensity": 3.0, "range": 5.0,
        "spot_angle_degrees": 60, "inner_spot_angle_degrees": 20,
        "shadows_enabled": case != "invalid_source" if case != "invalid_source" else "false",
        "color": {"r": 0.5, "g": 1.0, "b": 0.0},
    }}
    files[0].write_text(json.dumps(csir))
    stage = studio_auto_assets.inspect(
        *files, root, "Assets/Benchmark002", "/Game/CutSceneAI/AutoTransfer/T_ABC")
    if case == "invalid_source":
        assert not stage["ready"]
        assert any("Cannot stage Unity light" in reason for reason in stage["blockers"])
        return
    spec = next(row for row in stage["actors"] if row["kind"] == "entity.light")
    assert spec["light_setup"]["attenuation_radius"] == 500
    assert spec["light_setup"]["outer_cone_angle"] == 30
    manifest = tmp_path / "auto-setup.json"
    manifest.write_text(json.dumps(stage))
    project = tmp_path / "NewProject.uproject"
    project.write_text("{}")
    api = FakeUnreal(str(project))
    if case == "valid":
        class SpawnedLight(LightActor, Actor):
            def __init__(self):
                Actor.__init__(self)
                LightActor.__init__(self)

        api.SpotLight = SpawnedLight
        api.LightComponentBase = Component
        api.Color = lambda **kwargs: SimpleNamespace(**kwargs)
        original = api.actor_sys.spawn_actor_from_class

        def spawn(cls, loc, rot):
            if cls is not SpawnedLight:
                return original(cls, loc, rot)
            actor = cls()
            api.actor_sys.actors.append(actor)
            return actor

        api.actor_sys.spawn_actor_from_class = spawn
    output = tmp_path / "receipt.json"
    kwargs = dict(csir_path=str(files[0]), mapping_path=str(files[1]),
                  plan_path=str(files[2]), expected_project=str(project),
                  expected_level="/Game/Tests/L_Test", unreal_api=api)
    if case == "missing_api":
        with pytest.raises(scene.AutomaticSetupError, match="Native light component"):
            scene.run(str(manifest), str(output), **kwargs)
        assert not api.assets and not api.actor_sys.actors
        assert json.loads(output.read_text())["status"] == "BLOCKED"
    else:
        result = scene.run(str(manifest), str(output), **kwargs)
        assert result["light_property_setup"][0]["status"] == "PASS"
        assert result["light_property_setup"][0]["observed"] == spec["light_setup"]
        assert result["fidelity_verified"] is False
