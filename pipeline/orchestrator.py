"""
Maker-Checker Orchestrator —— 对抗式双 Agent 管道的总编排器。

=============================================================================
作用
=============================================================================
MakerCheckerOrchestrator 是 Maker-Checker 管道的中央控制器。它：

1. 管理 Generator → Reviewer 循环（最多 2 轮）
2. 根据三种 verdict（PASS/CHALLENGE/REJECT）路由到正确的处理分支
3. 在 REJECT 超限时触发 FORCED_SAFE_MODE
4. 调用 SafetyGate 进行确定性安全检查
5. 使用 ResponseRenderer 做确定性最终渲染

Orchestrator 使用 Python 代码强制执行判决 ——
Reviewer 的建议不是"建议"，是被硬编码执行的。

=============================================================================
数据流向
=============================================================================

Router (pipeline.entry)
    │  判断为复杂/高危 → 启动 Maker-Checker
    ▼
MakerCheckerOrchestrator.run(user_query)
    │
    ├── Round 1: Generator.generate() → Reviewer.review()
    │     │
    │     ├── PASS       → SafetyGate → ResponseRenderer
    │     ├── CHALLENGE  → 追加 evidence → SafetyGate → ResponseRenderer
    │     └── REJECT     → Round 2
    │
    ├── Round 2: Generator.regenerate(challenges) → Reviewer.review()
    │     │
    │     ├── PASS/CHALLENGE → SafetyGate → ResponseRenderer
    │     └── REJECT         → FORCED_SAFE_MODE（跳过 Gate）
    │
    └── ResponseRenderer.render() → Final Answer

=============================================================================
关联模块
=============================================================================
· agents.generator          — GeneratorAgent
· agents.reviewer           — ReviewerAgent, ReviewerVerdict
· pipeline.safety_gate              — SafetyGate, GateResult, apply_gate_override
· pipeline.action_signal            — ActionSignal（用于数据传递）
· pipeline.response_renderer        — ResponseRenderer（确定性最终渲染）
· agents.reviewer           — 内部持有 PreStopPolicy，先做确定性预检再做 LLM 审查

=============================================================================
设计原则
=============================================================================
· 执行权归编排器 —— Reviewer 输出 verdict，Orchestrator 强制执行
· 确定性的失败处理 —— 2 轮上限，FORCED_SAFE_MODE 兜底
· 四种终态路径 —— 正常通过 / 带质疑通过 / Gate 硬覆盖 / 强制安全兜底
· 结构化日志 —— 每轮决策都记录为 MAKER_CHECKER_TRACE

@new  Maker-Checker 架构 (2026-06)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from loguru import logger

from .safety_gate import SafetyGate, GateResult, apply_gate_override
from .terminal import Terminal
from .response_renderer import ResponseRenderer


# ============================================================================
# MakerCheckerOrchestrator
# ============================================================================

class MakerCheckerOrchestrator:
    """对抗式 Maker-Checker 流程的总编排器。

    管理完整的 Maker-Checker 管道：
    Round 1 → 判决路由 → Round 2（可选）→ SafetyGate → ResponseRenderer。

    Parameters
    ----------
    generator : GeneratorAgent
        综合分析生成 Agent。
    reviewer : ReviewerAgent
        对抗式审查 Agent。
    safety_gate : SafetyGate
        确定性安全门控。
    response_renderer : ResponseRenderer
        确定性最终渲染器，不调用 LLM，不改写已通过审查的 Maker answer。
    max_retries : int
        最大修正次数，默认 1（即最多 2 轮）。
    """

    def __init__(
        self,
        generator,        # GeneratorAgent 实例
        reviewer,         # ReviewerAgent 实例
        safety_gate: SafetyGate,  # 确定性安全检查器
        response_renderer: Optional[ResponseRenderer] = None,  # 确定性最终渲染器
        max_retries: int = 1  # 最大 Reviewer 修正次数
    ):
        self.generator   = generator
        self.reviewer    = reviewer
        self.safety_gate = safety_gate
        self.response_renderer = response_renderer or ResponseRenderer()
        self.max_retries = max_retries

    # =========================================================================
    # 主入口
    # =========================================================================

    async def run(self, user_query: str) -> Dict[str, Any]:
        """执行完整的 Maker-Checker 管道。

        Parameters
        ----------
        user_query : str
            用户的原始医学问题。

        Returns
        -------
        dict
            {
                "final_answer": str,       # 最终自然语言回答
                "terminal":     str,       # 终态标识（Terminal.* 之一）
                "rounds":       list,      # 每轮的 Generator/Reviewer 输出
                "gate_result":  dict,      # SafetyGate 检查结果
            }
        """
        retry_count = 0          # 已修正次数
        rounds_log: List[Dict] = []  # 轮次记录
        total_start = time.perf_counter()
        timings: Dict[str, Any] = {
            "orchestrator_total_ms": 0.0,
            "rounds": [],
            "safety_gate_ms": 0.0,
            "response_renderer_ms": 0.0,
        }

        # =====================================================================
        # Round 1: 初始生成 + 审查
        # =====================================================================
        logger.info(f"MK-CHECK Round 1 START | query={user_query[:60]}")

        t_generator = time.perf_counter()
        gen_output = await self.generator.generate(user_query)
        generator_ms = self._elapsed_ms(t_generator)
        # v3.3: Checker precheck 需要原始用户问题；真实 Generator 已写入，
        # 这里再兜底一次，保证 mock / legacy Generator 也满足契约。
        gen_output.setdefault("user_query", user_query)

        t_reviewer = time.perf_counter()
        verdict    = await self.reviewer.review(gen_output)
        reviewer_ms = self._elapsed_ms(t_reviewer)
        round_timing = self._build_round_timing(
            round_index=1,
            generator_ms=generator_ms,
            reviewer_ms=reviewer_ms,
            gen_output=gen_output,
            verdict=verdict,
        )
        timings["rounds"].append(round_timing)

        rounds_log.append({
            "round": 1,
            "timings": round_timing,
            "answer": gen_output.get("answer", ""),
            "urgency": gen_output.get("urgency"),
            "evidence_records": gen_output.get("evidence_records", []),
            "action_signal": gen_output.get("action_signal"),
            "prestop_result": verdict.get("prestop_result"),
            "verdict": verdict.get("verdict"),
            "challenges": verdict.get("challenges", []),
            "reject_type": verdict.get("reject_type"),
        })

        logger.info(
            f"MK-CHECK Round 1 END | verdict={verdict.get('verdict')}"
        )

        # =====================================================================
        # 循环: REJECT + 未达上限 → Round 2
        # =====================================================================
        while (
            verdict.get("verdict") == "REJECT"
            and retry_count < self.max_retries
        ):
            retry_count += 1
            logger.info(
                f"MK-CHECK Round 2 START | retry={retry_count}/{self.max_retries}"
            )

            # Generator 根据 challenges 修正
            t_generator = time.perf_counter()
            gen_output = await self.generator.regenerate(
                user_query,
                challenges=verdict.get("challenges", [])
            )
            generator_ms = self._elapsed_ms(t_generator)
            gen_output.setdefault("user_query", user_query)

            # Reviewer 再审查
            t_reviewer = time.perf_counter()
            verdict = await self.reviewer.review(gen_output)
            reviewer_ms = self._elapsed_ms(t_reviewer)
            round_timing = self._build_round_timing(
                round_index=1 + retry_count,
                generator_ms=generator_ms,
                reviewer_ms=reviewer_ms,
                gen_output=gen_output,
                verdict=verdict,
            )
            timings["rounds"].append(round_timing)

            rounds_log.append({
                "round": 1 + retry_count,
                "timings": round_timing,
                "answer": gen_output.get("answer", ""),
                "urgency": gen_output.get("urgency"),
                "evidence_records": gen_output.get("evidence_records", []),
                "action_signal": gen_output.get("action_signal"),
                "prestop_result": verdict.get("prestop_result"),
                "verdict": verdict.get("verdict"),
                "challenges": verdict.get("challenges", []),
                "reject_type": verdict.get("reject_type"),
            })

            logger.info(
                f"MK-CHECK Round 2 END | verdict={verdict.get('verdict')}"
            )

        # =====================================================================
        # 分支: REJECT 超限 → 强制安全兜底
        # =====================================================================
        if verdict.get("verdict") == "REJECT":
            logger.warning(
                f"MK-CHECK: REJECT after {retry_count + 1} rounds → "
                f"FORCED_SAFE_MODE"
            )
            return await self._handle_forced_safe(
                user_query,
                rounds_log,
                timings=timings,
                total_start=total_start,
            )

        # =====================================================================
        # CHALLENGE: 追加 evidence，标记 uncertainty
        # =====================================================================
        signal = gen_output
        if verdict.get("verdict") == "CHALLENGE":
            challenges = verdict.get("challenges", [])
            signal["checker_challenged"] = True
            legacy_signal = signal.get("action_signal")
            if isinstance(legacy_signal, dict):
                evidence = legacy_signal.get("evidence", [])
                for c in challenges:
                    desc = c.get("description", "")
                    if desc and desc not in evidence:
                        evidence.append(desc)
                legacy_signal["evidence"] = evidence
            logger.info(
                f"MK-CHECK: CHALLENGE | challenges={len(challenges)}"
            )

        # =====================================================================
        # SafetyGate: 确定性安全检查
        # =====================================================================
        t_gate = time.perf_counter()
        gate_result = self.safety_gate.check(user_query, signal)
        timings["safety_gate_ms"] += self._elapsed_ms(t_gate)
        terminal = Terminal.NORMAL

        if not gate_result.passed:
            # Gate 硬覆盖 —— 不是驳回，是直接覆盖结论
            logger.warning(
                f"MK-CHECK: SafetyGate BLOCK → GATE OVERRIDE "
                f"({gate_result.gate})"
            )
            signal = apply_gate_override(signal)
            terminal = Terminal.GATE_OVERRIDE

        if gate_result.passed and verdict.get("verdict") == "CHALLENGE":
            # Gate override 的安全优先级高于 challenged，只有 Gate PASS 才保留 challenged。
            terminal = Terminal.CHALLENGED

        # =====================================================================
        # ResponseRenderer 确定性最终渲染
        # =====================================================================
        t_render = time.perf_counter()
        final_answer = self._render_final_answer(
            user_query=user_query,
            maker_answer=gen_output.get("answer", ""),
            maker_output=signal,
            terminal=terminal,
            rounds_log=rounds_log,
            challenges=verdict.get("challenges", []),
            gate_result=gate_result,
        )
        timings["response_renderer_ms"] += self._elapsed_ms(t_render)
        timings["orchestrator_total_ms"] = self._elapsed_ms(total_start)

        # 结构化日志
        logger.info(
            f"MK-CHECK COMPLETE | terminal={terminal} | "
            f"rounds={len(rounds_log)} | "
            f"urgency={signal.get('urgency','?')}"
        )

        return {
            "final_answer": final_answer,
            "terminal":     terminal,
            "rounds":       rounds_log,
            "gate_result": {
                "passed": gate_result.passed,
                "gate":   gate_result.gate,
                "reason": gate_result.reason,
            },
            "timings": timings,
        }

    # =========================================================================
    # 终态处理
    # =========================================================================

    async def _handle_forced_safe(
        self,
        user_query: str,
        rounds_log: List[Dict],
        timings: Optional[Dict[str, Any]] = None,
        total_start: Optional[float] = None,
    ) -> Dict[str, Any]:
        """FORCED_SAFE_MODE: R2 仍 REJECT → 强制输出 urgent_care。

        跳过 SafetyGate（因为 action 已是 urgent_care，Gate 隐含通过）。
        不经过 Generator 或 Reviewer —— 直接构造安全兜底回答。
        """

        signal: Dict[str, Any] = {
            "user_query": user_query,
            "answer": "",
            "urgency": "emergency",
            "evidence_records": [],
            "process_trace": {},
            "safety_override": "forced_safe",
        }

        timings = timings or {
            "orchestrator_total_ms": 0.0,
            "rounds": [
                item.get("timings", {}) for item in rounds_log
                if isinstance(item, dict)
            ],
            "safety_gate_ms": 0.0,
            "response_renderer_ms": 0.0,
        }
        t_render = time.perf_counter()
        final_answer = self._render_final_answer(
            user_query=user_query,
            maker_answer="",
            maker_output=signal,
            terminal=Terminal.FORCED_SAFE,
            rounds_log=rounds_log,
            challenges=[],
            gate_result=None,
        )
        timings["response_renderer_ms"] = self._elapsed_ms(t_render)
        if total_start is not None:
            timings["orchestrator_total_ms"] = self._elapsed_ms(total_start)

        return {
            "final_answer": final_answer,
            "terminal":     Terminal.FORCED_SAFE,
            "rounds":       rounds_log,
            "gate_result":  None,  # FORCED_SAFE_MODE 跳过 Gate
            "timings":      timings,
        }

    def _render_final_answer(
        self,
        user_query: str,                   # 用户原始问题
        maker_answer: str,                 # Maker 已生成的原始答案
        maker_output: Dict[str, Any],      # 最终 MakerOutput
        terminal: str,                     # 终态类型
        rounds_log: List[Dict],            # 轮次记录
        challenges: Optional[List[Dict[str, Any]]] = None,
        gate_result: Optional[GateResult] = None,
    ) -> str:
        """用确定性 ResponseRenderer 生成最终答案。

        rounds_log 当前只用于保留调用契约和未来 trace 扩展；渲染器不会读取内部过程
        来重新生成医学结论，避免最终输出层越权。
        """

        _ = rounds_log
        return self.response_renderer.render(
            user_query=user_query,
            maker_answer=maker_answer,
            maker_output=maker_output,
            terminal=terminal,
            challenges=challenges,
            gate_result=gate_result,
        )

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        """返回从 start 到当前的毫秒耗时，统一保留 2 位小数。"""
        return round((time.perf_counter() - start) * 1000, 2)

    @staticmethod
    def _build_round_timing(
        *,
        round_index: int,
        generator_ms: float,
        reviewer_ms: float,
        gen_output: Dict[str, Any],
        verdict: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构造单轮 Maker/Checker 耗时摘要。"""

        generator_trace = gen_output.get("process_trace", {}) or {}
        reviewer_timing = verdict.get("timings", {}) or {}
        return {
            "round": round_index,
            "generator_ms": generator_ms,
            "generator_agent_loop": generator_trace.get("timings", {}),
            "reviewer_ms": reviewer_ms,
            "reviewer": reviewer_timing,
        }

