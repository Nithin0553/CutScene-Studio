"""Source-bound mapping proposals from a validated Unity CSIR snapshot.

This is read-only evidence gathering, not a replacement for the native planner.
A proposed primary action never certifies full track or scene fidelity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from packages.studio import ced_preflight
from packages.studio.mapping_resources import MappingEvidence, MappingResources
from packages.studio.transfer_agent import MappingDecision, TransferAgent

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts/csir/csir-v0.1.schema.json"
_TRANSFORM_CHANNELS = {
    *(f"transform.position.{axis}" for axis in "xyz"),
    *(f"transform.rotation.{axis}" for axis in "xyzw"),
}
_EULER_CHANNELS = {
    f"{prefix}.{axis}" for prefix in ("localeuleranglesraw", "m_localeulerangleshint")
    for axis in "xyz"
}


@dataclass(frozen=True)
class SourceTrackDecision:
    source_sha256: str
    track_id: str
    binding_type: str | None
    mapping_evidence: MappingEvidence
    source_alerts: tuple[str, ...]
    decision: MappingDecision
    eligible_mapping_ids: tuple[str, ...] = ()


def _has_transform_keys(section: dict[str, Any]) -> bool:
    animation = section["payload"].get("animation", {})
    if not isinstance(animation, dict):
        return False
    curves = animation.get("curves", [])
    return isinstance(curves, list) and any(
        isinstance(curve, dict)
        and isinstance(curve.get("keys"), list)
        and bool(curve["keys"])
        and (
            curve.get("canonical_semantic") in _TRANSFORM_CHANNELS
            or str(curve.get("property_name", "")).lower() in _EULER_CHANNELS
        )
        for curve in curves
    )


def _unique_index(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    index = {row[key]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError(f"Duplicate source identity: {key}")
    return index


class SourceEvidence:
    """Hold one validated snapshot and its existing CED audit."""

    def __init__(self, csir: dict[str, Any], resources: MappingResources) -> None:
        raw = json.dumps(csir, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self.csir = json.loads(raw)
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))
        Draft202012Validator(schema).validate(self.csir)
        if self.csir["source"]["engine"] != "unity":
            raise ValueError("Source must be Unity CSIR")
        self.source_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.resources = resources
        self.entities = _unique_index(self.csir["entities"], "entity_id")
        self.assets = _unique_index(self.csir["assets"], "asset_id")
        self.tracks = _unique_index(self.csir["tracks"], "track_id")
        self.report = ced_preflight.audit(
            self.csir, {}, ced=resources.catalog, capabilities=resources.capabilities
        )

    def _primary_action(
        self, track: dict[str, Any], binding_type: str | None
    ) -> str | None:
        sections = track["sections"]
        feature = track["ced_type"]
        if (
            feature == "camera.cut"
            and binding_type == "entity.camera"
            and all(section["ced_type"] == "camera.cut" for section in sections)
        ):
            return "camera_cut"
        if feature == "camera.transform":
            if binding_type != "entity.camera":
                return None
            if all(
                section["ced_type"] in {"camera.transform", "animation.section"}
                and _has_transform_keys(section)
                for section in sections
            ):
                return "transform"
            return None
        if feature != "animation.track":
            return None
        if not all(section["ced_type"] == "animation.section" for section in sections):
            return None
        if binding_type == "entity.character":
            if all(
                isinstance(section["payload"].get("asset_id"), str)
                and self.assets.get(section["payload"]["asset_id"], {}).get("ced_type")
                == "animation.clip"
                and "source_offset" in section
                for section in sections
            ):
                return "skeletal_animation"
        elif (
            binding_type in {"entity.prop", "entity.actor", "entity.camera"}
            and all(_has_transform_keys(section) for section in sections)
        ):
            return "transform"
        return None

    def propose_track(self, agent: TransferAgent, track_id: str) -> SourceTrackDecision:
        if track_id not in self.tracks:
            raise ValueError("Unknown source track ID")
        track = self.tracks[track_id]
        index = list(self.tracks).index(track_id)
        prefix = f"tracks[{index}]"
        findings = [
            row for row in self.report["findings"]
            if row["active"] and (
                row["source_location"] == prefix
                or row["source_location"].startswith(prefix + ".")
            )
        ]
        alerts = tuple(sorted({
            row["state"] for row in findings if row["state"] in ced_preflight.BLOCKING_STATES
        }))
        feature = track["ced_type"]
        evidence = self.resources.retrieve(feature, "track")
        binding = self.entities.get(track.get("binding_entity_id"), {})
        binding_type = binding.get("ced_type")
        eligible = ()
        if track.get("muted") or not track["sections"]:
            decision = MappingDecision("unsupported", None, "Inactive source track.")
        elif not evidence.candidates:
            decision = MappingDecision(
                "unsupported", None, f"No eligible strict mapping ({evidence.capability_state})."
            )
        else:
            primary = self._primary_action(track, binding_type)
            eligible = tuple(item for item in evidence.candidates if item.mapping_id == primary)
            if len(eligible) != 1:
                decision = MappingDecision(
                    "failed", None, "Insufficient source binding or payload evidence."
                )
            else:
                decision = agent.select_mapping(feature, eligible)
        return SourceTrackDecision(
            self.source_sha256, track_id, binding_type, evidence, alerts, decision,
            tuple(item.mapping_id for item in eligible),
        )


    def analyze_scene(self, agent: TransferAgent) -> dict[str, Any]:
        """Collect one read-only report, retaining every track and CED finding.

        Stop further inference after a provider failure. Unvisited tracks remain
        explicitly unanalysed, not unsupported or successfully transferred.
        """
        counts = {"proposed": 0, "unsupported": 0, "failed": 0, "not_analyzed": 0}
        rows: list[dict[str, Any]] = []
        provider_failed = False
        for track_id, track in self.tracks.items():
            row: dict[str, Any] = {
                "track_id": track_id,
                "name": track.get("name", ""),
                "source_feature": track["ced_type"],
                "active": not track.get("muted", False) and bool(track["sections"]),
            }
            if provider_failed:
                row.update(
                    status="not_analyzed",
                    reason="Not analyzed after local model inference failure.",
                    result=None,
                )
            else:
                result = self.propose_track(agent, track_id)
                row.update(
                    status=result.decision.status,
                    reason=result.decision.reason,
                    result=asdict(result),
                )
                provider_failed = (
                    result.decision.status == "failed"
                    and result.decision.reason.startswith("Local model inference failed:")
                )
            counts[row["status"]] += 1
            rows.append(row)

        report = {
            "kind": "cutsceneai.source_analysis",
            "version": "0.1.0",
            "source_cutscene_id": self.csir["cutscene_id"],
            "source_sha256": self.source_sha256,
            "catalog_sha256": self.resources.catalog["_sha256"],
            "capabilities_sha256": self.resources.capabilities_sha256,
            "source_counts": {
                "entities": len(self.entities),
                "assets": len(self.assets),
                "tracks": len(self.tracks),
            },
            "analysis_status": "INCOMPLETE" if counts["not_analyzed"] else "COMPLETE",
            "provider_failed": provider_failed,
            "execution_authorized": False,
            "decision_counts": counts,
            "tracks": rows,
            "ced_preflight": self.report,
        }
        # Return a detached JSON-compatible snapshot, not mutable audit references.
        return json.loads(json.dumps(report, allow_nan=False))
