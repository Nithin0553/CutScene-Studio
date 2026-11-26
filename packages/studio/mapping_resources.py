"""Read-only retrieval from the existing CED and Unreal builder contracts.

A registered action is a candidate, not proof of conversion or fidelity.
Strict retrieval deliberately excludes partial and unsupported capabilities.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from packages.studio import ced_preflight, feature_dispatch
from packages.studio.transfer_agent import MappingCandidate, MappingDecision, TransferAgent

_GROUPS = {"track": "tracks", "section": "sections", "curve": "curve_semantics"}


@dataclass(frozen=True)
class MappingEvidence:
    source_feature: str
    source_kind: str
    capability_state: str
    detail: str
    catalog_sha256: str
    capabilities_sha256: str
    candidates: tuple[MappingCandidate, ...]


@dataclass(frozen=True)
class GroundedDecision:
    evidence: MappingEvidence
    decision: MappingDecision


class MappingResources:
    """Retrieve exact CED semantics without inventing or widening mappings."""

    def __init__(
        self,
        catalog_path: Path = feature_dispatch.CATALOG_PATH,
        capabilities_path: Path = ced_preflight.CAPABILITIES_PATH,
    ) -> None:
        self.catalog = feature_dispatch.catalog(catalog_path)
        raw = capabilities_path.read_bytes()
        self.capabilities = json.loads(raw.decode("utf-8-sig"))
        if (
            self.capabilities.get("version") != "0.2.0"
            or self.capabilities.get("source_engine") != "unity"
            or self.capabilities.get("target_engine") != "unreal"
        ):
            raise ValueError("Unexpected CED capability version or engine pair")
        for group in _GROUPS.values():
            if not isinstance(self.capabilities.get(group), dict):
                raise TypeError("Missing or invalid CED capability group")
        self.capabilities_sha256 = hashlib.sha256(raw).hexdigest()

    def retrieve(self, source_feature: str, source_kind: str) -> MappingEvidence:
        if source_kind not in _GROUPS:
            raise ValueError("Expected a track, section or curve source kind")
        if not source_feature.strip() or len(source_feature) > 128:
            raise ValueError("Invalid source feature")

        recipe = feature_dispatch.recipe(source_feature, features=self.catalog)
        configured = self.capabilities[_GROUPS[source_kind]].get(source_feature)
        if isinstance(configured, dict):
            state = configured.get("state")
            detail = str(configured.get("detail", ""))
        else:
            state = configured
            detail = ""
        if not recipe["registered"]:
            state = "UNKNOWN_CED"
            detail = "Feature is absent from the canonical CED catalog."
        elif not state:
            state = "KNOWN_UNSUPPORTED"
            detail = "No capability registered for this source kind."
        actions = recipe.get("potential_builder_actions", [])
        candidates = ()
        if state == ced_preflight.SUPPORTED:
            candidates = tuple(
                MappingCandidate(
                    action,
                    source_feature,
                    f"Unreal builder action {action}; "
                    f"route {recipe['candidate_route']}; native verification required.",
                )
                for action in actions
                if action in feature_dispatch.BUILDER_ACTIONS
            )
            if not candidates:
                detail = "No explicit registered builder action for this feature."
        return MappingEvidence(
            source_feature=source_feature,
            source_kind=source_kind,
            capability_state=state,
            detail=detail,
            catalog_sha256=self.catalog["_sha256"],
            capabilities_sha256=self.capabilities_sha256,
            candidates=candidates,
        )

    def propose(
        self, agent: TransferAgent, source_feature: str, source_kind: str
    ) -> GroundedDecision:
        evidence = self.retrieve(source_feature, source_kind)
        if not evidence.candidates:
            decision = MappingDecision(
                "unsupported", None,
                f"No eligible strict mapping ({evidence.capability_state}).",
            )
        elif len(evidence.candidates) > 1:
            decision = MappingDecision(
                "failed", None,
                "Multiple builder actions require source binding or payload evidence.",
            )
        else:
            decision = agent.select_mapping(source_feature, evidence.candidates)
        return GroundedDecision(evidence, decision)
