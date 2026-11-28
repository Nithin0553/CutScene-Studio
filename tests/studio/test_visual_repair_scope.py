"""Legacy deterministic repair must never use another actor's material."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations/unreal"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import studio_auto_assets
import studio_visual_repair


@pytest.mark.parametrize("scoped", [True, False])
def test_legacy_visual_repair_only_uses_actor_specific_candidates(monkeypatch, tmp_path, scoped):
    manifest = {
        "actors": [{"name": "A", "label": "CSAI_A", "kind": "entity.character"},
                   {"name": "B", "label": "CSAI_B", "kind": "entity.prop"},
                   {"name": "Cube", "label": "Cube", "kind": "entity.prop", "source_primitive": "cube"}],
        "source_albedo_material_candidates": [{"slot_name": "Body", "target_material": "/Game/Wrong"}],
    }
    sources = {"A": [{"slot_name": "Body", "target_material": "/Game/A"}],
               "B": [{"slot_name": "Body", "target_material": "/Game/B"}],
               "Cube": [{"slot_name": "Body", "target_material": "/Game/Cube"}]}
    if scoped:
        manifest["source_albedo_actor_candidates"] = sources
    monkeypatch.setattr(studio_auto_assets, "verify", lambda *args: manifest)
    actors = [SimpleNamespace(get_actor_label=lambda label=label: label)
              for label in ("CSAI_A", "CSAI_B", "Cube")]
    api = SimpleNamespace(EditorActorSubsystem=object(), get_editor_subsystem=lambda cls:
                          SimpleNamespace(get_all_level_actors=lambda: actors))
    calls = []
    def restore(_api, actor, candidates, *, existing_assets):
        calls.append((actor.get_actor_label(), candidates))
        return []
    monkeypatch.setattr(studio_visual_repair.studio_material_restore, "restore", restore)
    job = {"automatic_setup": True, "candidate_dir": str(tmp_path),
           "automatic_setup_manifest": "manifest", "csir": "source", "mapping": "mapping"}
    setup = {"actors_created": [{"name": name} for name in sources]}
    studio_visual_repair.attempt(job, setup, api)
    assert calls == ([("CSAI_A", sources["A"]), ("CSAI_B", sources["B"])] if scoped else [])
