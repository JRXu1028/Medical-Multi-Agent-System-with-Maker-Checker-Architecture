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
5. 将最终结果交给 LeadAgent 表达

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
    │     ├── PASS       → SafetyGate → LeadAgent
    │     ├── CHALLENGE  → 追加 evidence → SafetyGate → LeadAgent
    │     └── REJECT     → Round 2
    │
    ├── Round 2: Generator.regenerate(challenges) → Reviewer.review()
    │     │
    │     ├── PASS/CHALLENGE → SafetyGate → LeadAgent
    │     └── REJECT         → FORCED_SAFE_MODE（跳过 Gate）
    │
    └── LeadAgent.express() → Final Answer

=============================================================================
关联模块
=============================================================================
· agents.generator          — GeneratorAgent
· agents.reviewer           — ReviewerAgent, ReviewerVerdict
· pipeline.safety_gate              — SafetyGate, GateResult, apply_gate_override
· pipeline.action_signal            — ActionSignal（用于数据传递）
· agents.lead               — LeadAgent（最终表达）
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

from typing import Any, Dict, List, Optional

from loguru import logger

from .action_signal import ActionType
from .safety_gate import SafetyGate, GateResult, apply_gate_override
from .terminal import Terminal


# ============================================================================
# MakerCheckerOrchestrator
# ============================================================================

class MakerCheckerOrchestrator:
    """对抗式 Maker-Checker 流程的总编排器。

    管理完整的 Maker-Checker 管道：
    Round 1 → 判决路由 → Round 2（可选）→ SafetyGate → LeadAgent。

    Parameters
    ----------
    generator : GeneratorAgent
        综合分析生成 Agent。
    reviewer : ReviewerAgent
        对抗式审查 Agent。
    safety_gate : SafetyGate
        确定性安全门控。
    lead_agent : LeadAgent
        最终表达 Agent（可选，可用简单的 LLM 调用替代）。
    max_retries : int
        最大修正次数，默认 1（即最多 2 轮）。
    """

    def __init__(
        self,
        generator,        # GeneratorAgent 实例
        reviewer,         # ReviewerAgent 实例
        safety_gate: SafetyGate,  # 确定性安全检查器
        lead_agent=None,  # LeadAgent 实例（可选，用于最终表达）
        max_retries: int = 1  # 最大 Reviewer 修正次数
    ):
        self.generator   = generator
        self.reviewer    = reviewer
        self.safety_gate = safety_gate
        self.lead_agent  = lead_agent
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

        # =====================================================================
        # Round 1: 初始生成 + 审查
        # =====================================================================
        logger.info(f"MK-CHECK Round 1 START | query={user_query[:60]}")

        gen_output = await self.generator.generate(user_query)
        # v3.3: Checker precheck 需要原始用户问题；真实 Generator 已写入，
        # 这里再兜底一次，保证 mock / legacy Generator 也满足契约。
        gen_output.setdefault("user_query", user_query)

        verdict    = await self.reviewer.review(gen_output)

        rounds_log.append({
            "round": 1,
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
            gen_output = await self.generator.regenerate(
                user_query,
                challenges=verdict.get("challenges", [])
            )
            gen_output.setdefault("user_query", user_query)

            # Reviewer 再审查
            verdict = await self.reviewer.review(gen_output)

            rounds_log.append({
                "round": 1 + retry_count,
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
            return await self._handle_forced_safe(user_query, rounds_log)

        # =====================================================================
        # CHALLENGE: 追加 evidence，标记 uncertainty
        # =====================================================================
        signal = gen_output.get("action_signal", {})
        if verdict.get("verdict") == "CHALLENGE":
            challenges = verdict.get("challenges", [])
            evidence = signal.get("evidence", [])
            for c in challenges:
                desc = c.get("description", "")
                if desc and desc not in evidence:
                    evidence.append(desc)
            signal["evidence"] = evidence
            signal["uncertainty"] = True
            logger.info(
                f"MK-CHECK: CHALLENGE — merged {len(challenges)} notes into evidence"
            )

        # =====================================================================
        # SafetyGate: 确定性安全检查
        # =====================================================================
        gate_result = self.safety_gate.check(user_query, signal)
        terminal = Terminal.NORMAL

        if not gate_result.passed:
            # Gate 硬覆盖 —— 不是驳回，是直接覆盖结论
            logger.warning(
                f"MK-CHECK: SafetyGate BLOCK → GATE OVERRIDE "
                f"({gate_result.gate})"
            )
            signal = apply_gate_override(signal)
            terminal = Terminal.GATE_OVERRIDE

        if verdict.get("verdict") == "CHALLENGE":
            # 保持 challenged 终态（即使 Gate PASS）
            terminal = Terminal.CHALLENGED

        # =====================================================================
        # LeadAgent 表达
        # =====================================================================
        final_answer = await self._express(
            user_query, signal, terminal, rounds_log
        )

        # 结构化日志
        logger.info(
            f"MK-CHECK COMPLETE | terminal={terminal} | "
            f"rounds={len(rounds_log)} | "
            f"action={signal.get('proposed_action','?')}"
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
        }

    # =========================================================================
    # 终态处理
    # =========================================================================

    async def _handle_forced_safe(
        self,
        user_query: str,
        rounds_log: List[Dict]
    ) -> Dict[str, Any]:
        """FORCED_SAFE_MODE: R2 仍 REJECT → 强制输出 urgent_care。

        跳过 SafetyGate（因为 action 已是 urgent_care，Gate 隐含通过）。
        不经过 Generator 或 Reviewer —— 直接构造安全兜底回答。
        """

        signal: Dict[str, Any] = {
            "result":          "目前无法可靠排除风险，基于安全原则建议立即就医。",
            "evidence":        ["系统未能确认低风险，按安全原则建议及时就医"],
            "confidence":      "forced_safe_mode",    # 非浮点数，标记来源
            "proposed_action": ActionType.RECOMMEND_URGENT_CARE,
        }

        final_answer = await self._express(
            user_query, signal, Terminal.FORCED_SAFE, rounds_log
        )

        return {
            "final_answer": final_answer,
            "terminal":     Terminal.FORCED_SAFE,
            "rounds":       rounds_log,
            "gate_result":  None,  # FORCED_SAFE_MODE 跳过 Gate
        }

    async def _express(
        self,
        user_query: str,          # 用户原始问题
        signal: Dict[str, Any],   # 最终 action_signal
        terminal: str,            # 终态类型
        rounds_log: List[Dict]    # 轮次记录
    ) -> str:
        """通过 LeadAgent 将 action_signal 表达为自然语言。"""

        if self.lead_agent is None:
            # 无 LeadAgent → 直接返回 action_signal.result
            return signal.get("result", "抱歉，无法生成回答。")

        try:
            return await self.lead_agent.express(
                user_query=user_query,
                action_signal=signal,
                terminal=terminal,
                rounds=rounds_log,
            )
        except Exception as e:
            logger.error(f"LeadAgent express failed: {e}")
            return signal.get("result", "抱歉，无法生成回答。")

