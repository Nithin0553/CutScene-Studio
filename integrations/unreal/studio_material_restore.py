"""Conservative native Unreal albedo restoration on newly staged actors.

Only exact FBX material-slot names with source-backed Unity .mat/PNG GUIDs
qualify. Does not translate arbitrary Unity/URP shaders or prove render parity.
"""
from __future__ import annotations

import logging

LOGGER = logging.getLogger(__name__)


def _name(value):
    return str(value)


def _fallback(material):
    if material is None:
        return True
    try:
        path = str(material.get_path_name()).lower()
    except Exception:
        LOGGER.debug("Native material identity unavailable", exc_info=True)
        return False
    return ("/enginematerials/worldgridmaterial" in path
            or "/enginematerials/defaultmaterial" in path)


def _slots(component):
    """Return list of (slot name, index) from the *actual* imported mesh."""
    mesh = None
    for property_name in ("skeletal_mesh_asset", "static_mesh"):
        try:
            mesh = component.get_editor_property(property_name)
        except Exception:
            LOGGER.debug("Native component mesh property unavailable: %s", property_name, exc_info=True)
        if mesh is not None:
            break
    if mesh is None:
        return []
    # SkeletalMesh exposes "materials", while StaticMesh exposes
    # "static_materials" (the inherited "materials" property is protected).
    # Probe both without changing the mesh or its original material slots.
    raw = None
    for property_name in ("materials", "static_materials"):
        try:
            raw = mesh.get_editor_property(property_name)
        except Exception:
            LOGGER.debug("Native mesh slot property unavailable: %s", property_name, exc_info=True)
            continue
        if raw is not None:
            break
    if raw is None:
        return []
    slots = []
    for index, item in enumerate(raw):
        try:
            slots.append((_name(item.get_editor_property("material_slot_name")), index))
        except Exception:
            LOGGER.debug("Native material slot identity unavailable", exc_info=True)
            continue
    return slots


def _package_path(asset):
    if asset is None:
        return None
    return str(asset.get_path_name()).split(".", 1)[0]


def observe_slot(api, actor, entry):
    """Measure an assigned component slot, never substitute a receipt value."""
    observed = None
    try:
        cls = getattr(api, entry["component_class"], None)
        if cls is None:
            raise RuntimeError("Native component class unavailable.")
        components = list(actor.get_components_by_class(cls))
        index = entry["component_index"]
        if len(components) != entry["component_count"] or index >= len(components):
            return {"status": "FAIL", "observed_material": None}
        component = components[index]
        slots = _slots(component)
        if (entry["slot_name"], entry["index"]) not in slots:
            return {"status": "INCOMPLETE" if not slots else "FAIL", "observed_material": None}
        observed = _package_path(component.get_material(entry["index"]))
    except Exception:
        LOGGER.debug("Native assigned material slot readback unavailable", exc_info=True)
        return {"status": "INCOMPLETE", "observed_material": observed}
    return {"status": "PASS" if observed == entry["target_material"] else "FAIL",
            "observed_material": observed}


def restore(api, actor, candidates, *, existing_assets=None):
    """Assign only unique source-backed exact slot matches to fallback slots.

    Returns explicit per-slot evidence; throws for native material construction
    failure so calling setup records partial mutations rather than false success.
    """
    by_name = {}
    for candidate in candidates:
        by_name.setdefault(candidate["slot_name"], []).append(candidate)
    results = []
    cache = existing_assets if existing_assets is not None else {}
    for klass in ("SkeletalMeshComponent", "StaticMeshComponent"):
        component_type = getattr(api, klass, None)
        if component_type is None or not hasattr(actor, "get_components_by_class"):
            continue
        components = list(actor.get_components_by_class(component_type) or [])
        for component_index, component in enumerate(components):
            for name, index in _slots(component):
                matching = by_name.get(name, [])
                entry = {"slot_name": name, "index": index,
                         "component_class": klass, "component_index": component_index,
                         "component_count": len(components)}
                if len(matching) != 1:
                    entry["status"] = "NO_UNIQUE_SOURCE_MATERIAL_MATCH"
                elif not _fallback(component.get_material(index)):
                    entry["status"] = "EXISTING_NONDEFAULT_PRESERVED"
                else:
                    item = matching[0]
                    path = item["target_material"]
                    if path not in cache:
                        if api.EditorAssetLibrary.does_asset_exist(path):
                            raise RuntimeError("Material destination already occupied: " + path)
                        texture = api.load_asset(item["target_texture"])
                        if texture is None or str(texture.get_class().get_name()) != "Texture2D":
                            raise RuntimeError("Imported source texture unavailable: " + item["target_texture"])
                        factory = api.MaterialFactoryNew()
                        asset_tools = api.AssetToolsHelpers.get_asset_tools()
                        folder, asset_name = path.rsplit("/", 1)
                        material = asset_tools.create_asset(asset_name, folder, api.Material, factory)
                        if material is None:
                            raise RuntimeError("Native MaterialFactoryNew failed: " + path)
                        # Creation may persist even if any subsequent step fails.
                        expression = api.MaterialEditingLibrary.create_material_expression(
                            material, api.MaterialExpressionTextureSample, -320, 0
                        )
                        if expression is None:
                            raise RuntimeError("TextureSample creation failed: " + path)
                        expression.set_editor_property("texture", texture)
                        if api.MaterialEditingLibrary.connect_material_property(
                            expression, "RGB", api.MaterialProperty.MP_BASE_COLOR
                        ) is not True:
                            raise RuntimeError("Native Base Color connection failed: " + path)
                        api.MaterialEditingLibrary.recompile_material(material)
                        if not api.EditorAssetLibrary.save_loaded_asset(material):
                            raise RuntimeError("Unable to persist recovered material: " + path)
                        cache[path] = material
                    component.set_material(index, cache[path])
                    entry["status"] = "SOURCE_ALBEDO_ASSIGNED_RENDER_PARITY_UNVERIFIED"
                    entry["target_material"] = path
                    entry["source_material_sha256"] = item["source_material_sha256"]
                    measurement = observe_slot(api, actor, entry)
                    if measurement["status"] != "PASS":
                        raise RuntimeError("Native material assignment readback differs: " + path)
                    entry["observed_material"] = measurement["observed_material"]
                results.append(entry)
    return results
