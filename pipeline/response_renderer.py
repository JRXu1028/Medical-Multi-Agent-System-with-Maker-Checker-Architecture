"""
确定性响应渲染器 —— Maker-Checker 管道的最终输出层。

本模块替代旧的最终 LLM 表达层。它不调用 LLM、不重新判断医学问题、
不改写已经通过 Checker 和 SafetyGate 的 Maker 答案，只根据终态选择最终输出：

1. normal/simple: 直接返回 Maker answer
2. challenged: 返回 Maker answer，并追加固定的不确定性说明
3. gate_override: 丢弃 Maker answer，返回 SafetyGate 安全覆盖模板
4. forced_safe: 返回强制安全兜底模板

这样做的目的：
· 降低延迟：最终输出层不再多一次 LLM 调用
· 降低风险：避免最后一个 LLM 改写已审查过的医学含义
· 明确职责：Maker 负责生成，Checker 负责审查，SafetyGate 负责硬覆盖
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .action_signal import ActionType
from .terminal import Terminal


class ResponseRenderer:
    """把已裁决结果渲染为最终用户答案的确定性组件。

    注意：这个类不是 Agent，也不是 Tool。它只做终态分发和固定模板渲染。
    """

    _FALLBACK_ANSWER = (
        "抱歉，当前结果不完整，无法生成可靠回答。"
        "如果症状明显、持续加重或你感到不安，请及时线下就医。"
    )

    def render(
        self,
        *,
        user_query: str,
        maker_answer: str,
        action_signal: Dict[str, Any],
        terminal: str,
        challenges: Optional[List[Dict[str, Any]]] = None,
        gate_result: Optional[Any] = None,
    ) -> str:
        """根据终态渲染最终答案。

        Parameters
        ----------
        user_query:
            用户原始问题。模板中通常不复述，仅保留给未来个性化模板使用。
        maker_answer:
            Maker 已生成、并通过审查路径的原始答案。
        action_signal:
            经过 Checker / SafetyGate 后的结构化动作信号。
        terminal:
            管道终态，取值见 pipeline.terminal.Terminal。
        challenges:
            Checker 在 CHALLENGE 场景下给出的质疑点。
        gate_result:
            SafetyGate 的检查结果。仅用于安全模板中的调试友好描述。
        """

        _ = user_query  # 当前模板不直接使用 query，保留参数让调用契约完整。

        if terminal == Terminal.FORCED_SAFE:
            return self._render_forced_safe(action_signal)

        if terminal == Terminal.GATE_OVERRIDE:
            return self._render_gate_override(action_signal, gate_result)

        base_answer = self._select_maker_answer(maker_answer, action_signal)

        if terminal == Terminal.CHALLENGED:
            return self._append_challenge_note(base_answer, challenges or [])

        return base_answer

    def _select_maker_answer(
        self,
        maker_answer: str,
        action_signal: Dict[str, Any],
    ) -> str:
        """正常路径优先使用 Maker answer，缺失时降级到 action_signal.result。"""

        answer = (maker_answer or "").strip()
        if answer:
            return answer

        result = str(action_signal.get("result") or "").strip()
        return result or self._FALLBACK_ANSWER

    def _append_challenge_note(
        self,
        answer: str,
        challenges: Iterable[Dict[str, Any]],
    ) -> str:
        """为 CHALLENGE 终态追加固定说明，避免重新改写 Maker 正文。"""

        challenge_descriptions = [
            str(item.get("description", "")).strip()
            for item in challenges
            if str(item.get("description", "")).strip()
        ]

        note_lines = [
            "",
            "补充说明：Checker 对这个回答仍保留一定不确定性。",
        ]
        if challenge_descriptions:
            # 只展示前 3 条，避免把审查日志原样灌给用户。
            note_lines.append("主要原因：" + "；".join(challenge_descriptions[:3]) + "。")
        note_lines.append("如果症状持续、加重，或你的情况与上述描述不完全一致，请优先线下就医确认。")

        return answer.rstrip() + "\n".join(note_lines)

    def _render_gate_override(
        self,
        action_signal: Dict[str, Any],
        gate_result: Optional[Any],
    ) -> str:
        """SafetyGate BLOCK 后的安全覆盖模板。

        此时不复述 Maker answer，因为 Maker 的原建议已经被安全门判定为不够安全。
        """

        reason = getattr(gate_result, "reason", "") if gate_result is not None else ""
        evidence = self._format_evidence(action_signal.get("evidence", []))

        lines = [
            "目前无法可靠排除较高风险。基于安全原则，建议你尽快线下就医评估；",
            "如果正在出现胸痛、呼吸困难、意识模糊、晕厥、严重出血等急症表现，请立即联系急救或前往急诊。",
        ]
        if evidence:
            lines.append(f"系统触发安全覆盖的依据包括：{evidence}")
        if reason:
            lines.append(f"安全门控原因：{reason}")

        return "\n".join(lines)

    def _render_forced_safe(self, action_signal: Dict[str, Any]) -> str:
        """Checker 连续 REJECT 后的强制安全兜底模板。"""

        result = str(action_signal.get("result") or "").strip()
        evidence = self._format_evidence(action_signal.get("evidence", []))

        lines = [
            result or "目前无法可靠排除风险，基于安全原则建议立即就医。",
            "由于系统未能生成通过审查的低风险结论，请不要仅依据线上回答自行处理。",
        ]
        if evidence:
            lines.append(f"兜底依据：{evidence}")
        lines.append("如果症状明显、持续加重或涉及急症表现，请立即联系急救或前往急诊。")

        return "\n".join(lines)

    def _format_evidence(self, evidence: Any) -> str:
        """把 evidence 简短格式化为用户可读片段。"""

        if not isinstance(evidence, list):
            return ""

        compact = [str(item).strip() for item in evidence if str(item).strip()]
        if not compact:
            return ""

        return "；".join(compact[:3])


def render_action_type(action_type: Any) -> str:
    """把 ActionType 渲染为简短中文标签，供未来 UI 或日志使用。"""

    labels = {
        ActionType.RECOMMEND_URGENT_CARE: "建议立即就医",
        ActionType.RECOMMEND_TEST: "建议进一步检查",
        ActionType.FOLLOW_GUIDELINE: "遵循指南",
        ActionType.RECOMMEND_SELF_CARE: "居家自护",
        ActionType.RECOMMEND_LIFESTYLE: "生活方式调整",
        ActionType.OBSERVE: "观察随访",
        ActionType.CITE_EVIDENCE: "引用证据",
        ActionType.NO_TEST_NEEDED: "无需检查",
    }
    return labels.get(action_type, str(action_type or ""))
