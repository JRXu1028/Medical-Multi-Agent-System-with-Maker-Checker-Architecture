"""Deterministic final safety gate.

SafetyGate checks the final machine-readable MakerOutput fields. It does not
audit tool path or evidence path; those are Checker/PreStopPolicy concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, FrozenSet, Optional

from .maker_output import URGENT_URGENCIES, normalize_urgency


@dataclass
class GateResult:
    passed: bool
    reason: str = ""
    gate: str = ""

    @classmethod
    def ok(cls) -> "GateResult":
        return cls(passed=True)


class SafetyGate:
    """Final deterministic guard for user-visible medical safety."""

    GATE_HIGH_RISK_SYMPTOM: ClassVar[str] = "high_risk_symptom_check"
    GATE_EVIDENCE_SUFFICIENCY: ClassVar[str] = "evidence_sufficiency_check"
    GATE_FORMAT_COMPLIANCE: ClassVar[str] = "format_compliance_check"

    DEFAULT_HIGH_RISK_SYMPTOMS: ClassVar[FrozenSet[str]] = frozenset(
        {
            "胸痛",
            "呼吸困难",
            "意识模糊",
            "剧烈头痛",
            "严重出血",
            "突然晕厥",
            "晕厥",
            "单侧肢体无力",
            "语言不清",
            "咳血",
            "黑便",
            "呕血",
            "自杀",
            "自残",
            "不想活",
        }
    )

    def __init__(self, high_risk_symptoms: Optional[FrozenSet[str]] = None) -> None:
        self._high_risk_symptoms = (
            high_risk_symptoms
            if high_risk_symptoms is not None
            else self.DEFAULT_HIGH_RISK_SYMPTOMS
        )

    def check(self, user_query: str, maker_output: Dict[str, Any]) -> GateResult:
        """Run final output-safety checks against MakerOutput."""

        maker_output = self._normalize_legacy_action_signal(maker_output)

        result = self._check_format_compliance(maker_output)
        if not result.passed:
            return result

        result = self._check_high_risk_symptom(user_query, maker_output)
        if not result.passed:
            return result

        return self._check_legacy_evidence_sufficiency(maker_output)

    def _normalize_legacy_action_signal(self, maker_output: Dict[str, Any]) -> Dict[str, Any]:
        if maker_output.get("urgency"):
            return maker_output
        if "proposed_action" not in maker_output and isinstance(maker_output.get("action_signal"), dict):
            normalized = dict(maker_output)
            normalized.update(maker_output["action_signal"])
            maker_output = normalized
        if "proposed_action" not in maker_output:
            return maker_output
        normalized = dict(maker_output)
        action = str(normalized.get("proposed_action") or "").lower()
        if "urgent" in action:
            normalized["urgency"] = "emergency"
        elif "self_care" in action or "lifestyle" in action:
            normalized["urgency"] = "self_care"
        else:
            normalized["urgency"] = "routine"
        return normalized

    def _check_format_compliance(self, maker_output: Dict[str, Any]) -> GateResult:
        urgency = str(maker_output.get("urgency") or "").strip()
        if not urgency:
            return GateResult(
                passed=False,
                gate=self.GATE_FORMAT_COMPLIANCE,
                reason="MakerOutput is missing top-level urgency.",
            )
        return GateResult.ok()

    def _check_legacy_evidence_sufficiency(self, maker_output: Dict[str, Any]) -> GateResult:
        if "confidence" not in maker_output:
            return GateResult.ok()
        try:
            confidence = float(maker_output.get("confidence", 0))
        except (TypeError, ValueError):
            return GateResult.ok()
        if confidence <= 0.7 or maker_output.get("evidence"):
            return GateResult.ok()
        return GateResult(
            passed=False,
            gate=self.GATE_EVIDENCE_SUFFICIENCY,
            reason="Legacy action_signal has high confidence but no evidence.",
        )

    def _check_high_risk_symptom(
        self,
        user_query: str,
        maker_output: Dict[str, Any],
    ) -> GateResult:
        urgency = normalize_urgency(maker_output.get("urgency"))
        query_lower = user_query.lower()

        for symptom in self._high_risk_symptoms:
            if symptom not in user_query and symptom.lower() not in query_lower:
                continue
            if urgency not in URGENT_URGENCIES:
                return GateResult(
                    passed=False,
                    gate=self.GATE_HIGH_RISK_SYMPTOM,
                    reason=(
                        f"Query contains high-risk symptom '{symptom}', "
                        f"but urgency='{urgency}'."
                    ),
                )

        return GateResult.ok()


def apply_gate_override(maker_output: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copied MakerOutput with final safety override markers."""

    overridden = dict(maker_output)
    overridden["urgency"] = "emergency"
    overridden["safety_override"] = "gate_override"
    if "proposed_action" in overridden:
        overridden["proposed_action"] = "recommend_urgent_care"
        overridden["confidence"] = "overridden"
    return overridden
