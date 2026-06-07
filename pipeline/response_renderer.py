"""Deterministic final response renderer.

The renderer does not call an LLM and does not rewrite a checked Maker answer.
It only chooses between the Maker answer and fixed safety templates.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .terminal import Terminal


class ResponseRenderer:
    _FALLBACK_ANSWER = (
        "抱歉，当前结果不完整，无法生成可靠回答。"
        "如果症状明显、持续加重或你感到不安，请及时线下就医。"
    )

    def render(
        self,
        *,
        user_query: str,
        maker_answer: str,
        maker_output: Optional[Dict[str, Any]] = None,
        action_signal: Optional[Dict[str, Any]] = None,
        terminal: str,
        challenges: Optional[List[Dict[str, Any]]] = None,
        gate_result: Optional[Any] = None,
    ) -> str:
        _ = user_query
        maker_output = maker_output or action_signal or {}

        if terminal == Terminal.FORCED_SAFE:
            return self._render_forced_safe(maker_output)

        if terminal == Terminal.GATE_OVERRIDE:
            return self._render_gate_override(maker_output, gate_result)

        base_answer = (maker_answer or "").strip() or self._FALLBACK_ANSWER

        if terminal == Terminal.CHALLENGED:
            return self._append_challenge_note(base_answer, challenges or [])

        return base_answer

    def _append_challenge_note(
        self,
        answer: str,
        challenges: Iterable[Dict[str, Any]],
    ) -> str:
        descriptions = [
            str(item.get("description", "")).strip()
            for item in challenges
            if str(item.get("description", "")).strip()
        ]
        lines = [
            "",
            "补充说明：Checker 对这个回答仍保留一定不确定性。",
        ]
        if descriptions:
            lines.append("主要原因：" + "；".join(descriptions[:3]) + "。")
        lines.append("如果症状持续、加重，或你的情况与上述描述不完全一致，请优先线下就医确认。")
        return answer.rstrip() + "\n".join(lines)

    def _render_gate_override(
        self,
        maker_output: Dict[str, Any],
        gate_result: Optional[Any],
    ) -> str:
        reason = getattr(gate_result, "reason", "") if gate_result is not None else ""
        evidence = self._format_evidence_records(maker_output.get("evidence_records", []))
        lines = [
            "目前无法可靠排除较高风险。基于安全原则，建议你尽快线下就医评估；",
            "如果正在出现胸痛、呼吸困难、意识模糊、晕厥、严重出血等急症表现，请立即联系急救或前往急诊。",
        ]
        if evidence:
            lines.append(f"系统触发安全覆盖时可见的证据包括：{evidence}")
        if reason:
            lines.append(f"安全门控原因：{reason}")
        return "\n".join(lines)

    def _render_forced_safe(self, maker_output: Dict[str, Any]) -> str:
        evidence = self._format_evidence_records(maker_output.get("evidence_records", []))
        lines = [
            "目前信息不足，无法可靠排除风险；基于安全原则，建议你尽快线下就医或咨询专业医生。",
            "由于系统未能生成通过审查的低风险结论，请不要仅依据线上回答自行处理。",
        ]
        if evidence:
            lines.append(f"兜底前可见证据包括：{evidence}")
        lines.append("如果症状明显、持续加重或涉及急症表现，请立即联系急救或前往急诊。")
        return "\n".join(lines)

    def _format_evidence_records(self, evidence_records: Any) -> str:
        if not isinstance(evidence_records, list):
            return ""

        compact: List[str] = []
        for item in evidence_records:
            if isinstance(item, dict):
                text = item.get("title") or item.get("citation") or item.get("snippet")
            else:
                text = str(item)
            text = str(text or "").strip()
            if text:
                compact.append(text)

        return "；".join(compact[:3])


def render_urgency(urgency: Any) -> str:
    labels = {
        "emergency": "立即急救/急诊",
        "urgent": "尽快线下评估",
        "routine": "普通门诊或复查",
        "self_care": "自我护理和观察",
        "education_only": "健康科普",
        "uncertain": "信息不足",
    }
    return labels.get(str(urgency or ""), str(urgency or ""))
