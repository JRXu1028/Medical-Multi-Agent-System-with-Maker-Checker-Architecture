"""
Reviewer Agent —— Maker-Checker 管道中的"证伪者"。

=============================================================================
作用
=============================================================================
Reviewer 是 Maker-Checker 中的 Checker（审查者）。它的唯一目标是：

**证伪 Generator 的结论，而非提供替代答案。**

它接收 Generator 的结构化输出（action_signal + skill_trace），
从空白上下文开始审查，不受 Generator 推理路径的影响。
可以重新调用验证类 Skills 做独立交叉验证。

=============================================================================
数据流向
=============================================================================

Orchestrator
    │  调用 review(generator_output)
    │  传入: {answer, action_signal, skill_trace}
    ▼
Reviewer.review()
    │  构建结构化审查 prompt
    │  通过 AgentLoop 运行 LLM → 可选调验证 Skills → 输出审查结论
    │  post_process_result 提取结构化 verdict
    ▼
返回:
    {
        "verdict":              "PASS" | "CHALLENGE" | "REJECT",
        "challenges":           [{type, description, severity, suggested_fix}],
        "confidence_adjusted":  0.65
    }

=============================================================================
关联模块
=============================================================================
· pipeline.action_signal        — ActionType（用于比较 proposed_action）
· agents.generator      — 消费其输出
· pipeline.orchestrator — 被其调用，verdict 被其强制执行
· agents.base_agent          — BaseAgent（AgentLoop, LLMClient）
· agents.skill_registry_mixin — register_all_skills()

=============================================================================
设计原则
=============================================================================
· 只审查，不构建 —— 职责单一，绝不输出治疗建议
· 上下文隔离 —— 从空白 AgentLoop 开始，不接触 Generator 的推理历史
· 执行权归 Orchestrator —— Reviewer 只输出 verdict，
  Orchestrator 的 Python 代码强制执行判决
· Phase 1 靠 prompt 约束不调用推荐类 Skills，
  Phase 2 改用 register_all_skills(exclude={...}) 硬约束

@new  Maker-Checker 架构 (2026-06)
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

# 复用基础组件
from agents.base import BaseAgent
from agents.skill_registry_mixin import SkillRegistryMixin

from pipeline.action_signal import ActionType


# ============================================================================
# ReviewerVerdict — 结构化审查结果
# ============================================================================

class ReviewerVerdict:
    """Reviewer 的结构化审查结论。

    由 post_process_result 从 LLM 输出中解析构建。
    Orchestrator 根据此对象的 verdict 字段决定后续路由。

    Parameters
    ----------
    verdict : str
        判决类型。取值约束为 PASS / CHALLENGE / REJECT。
    challenges : list of dict
        审查发现的问题列表。每项含 type/description/severity/suggested_fix。
        仅 CHALLENGE 和 REJECT 时非空。
    confidence_adjusted : float, optional
        Reviewer 调整后的置信度评估。
    """

    VALID_VERDICTS = frozenset({"PASS", "CHALLENGE", "REJECT"})  # 合法判决值

    def __init__(
        self,
        verdict: str,                             # PASS | CHALLENGE | REJECT
        challenges: Optional[List[Dict[str, str]]] = None,  # 审查问题列表
        confidence_adjusted: Optional[float] = None         # 调整后置信度
    ):
        if verdict not in self.VALID_VERDICTS:
            raise ValueError(
                f"Invalid verdict '{verdict}'. "
                f"Must be one of {self.VALID_VERDICTS}."
            )
        self.verdict = verdict
        self.challenges = challenges or []
        self.confidence_adjusted = confidence_adjusted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict":              self.verdict,
            "challenges":           self.challenges,
            "confidence_adjusted":  self.confidence_adjusted,
        }

    # ---- 便捷判断 -----------------------------------------------------------
    @property
    def is_pass(self) -> bool:
        return self.verdict == "PASS"

    @property
    def is_challenge(self) -> bool:
        return self.verdict == "CHALLENGE"

    @property
    def is_reject(self) -> bool:
        return self.verdict == "REJECT"

    @property
    def challenge_count(self) -> int:
        return len(self.challenges)


# ============================================================================
# ReviewerAgent — Checker
# ============================================================================

class ReviewerAgent(BaseAgent, SkillRegistryMixin):
    """对抗式临床安全审查 Agent —— Maker-Checker 的 Checker。

    从空白上下文开始审查 Generator 的结构化输出。
    可重新调用验证 Skills 做独立交叉验证。
    不输出治疗建议 —— 只输出结构化 verdict。

    Parameters
    ----------
    agent_id : str
        Agent 标识，默认 "reviewer"。
    config : dict, optional
        配置项。通常设置较低的 temperature（审查要求一致性）。
    llm_client : LLMClient, optional
        复用的 LLM 客户端。默认创建新实例。
    """

    def __init__(
        self,
        agent_id: str = "reviewer",                     # Agent 标识
        config: Optional[Dict[str, Any]] = None,         # 配置项
        llm_client=None                                   # LLM 客户端（可选复用）
    ):
        # ---- 默认配置 -------------------------------------------------------
        config = config or {}
        config.setdefault("llm_profile", "reviewer")
        config.setdefault("max_iterations", 4)            # 审查可能调 2-3 验证 Skills + 1 轮输出
        config.setdefault("temperature", 0.3)             # 低温度 — 审查要求一致性

        # ---- 初始化基类 -----------------------------------------------------
        BaseAgent.__init__(self, agent_id, config, llm_client)
        SkillRegistryMixin.__init__(self)

        logger.debug(f"ReviewerAgent initialized (id={agent_id})")

    # =========================================================================
    # 工具注册
    # =========================================================================

    def register_tools(self) -> None:
        """Register verification Skills only; Reviewer must not generate advice."""
        self.register_all_skills(exclude={"recommend_lifestyle", "disease_code"})

    # =========================================================================
    # 系统提示词 — 对抗式证伪立场
    # =========================================================================

    def get_system_prompt(self) -> str:
        """返回系统提示词：对抗式证伪 + 审查维度 + 结构化输出。"""
        return """你是临床安全审查专家（Reviewer Agent）。

## 唯一目标
**证伪 Generator 的临床分析结论。你不是来提供替代答案的。**

## 审查维度（按优先级）
1. **遗漏风险**: Generator 是否遗漏了高危症状或关键证据？
2. **证据充分性**: 每个结论是否有足够证据支撑？
3. **逻辑一致性**: 证据 → 结论的推理链是否完整？
4. **时效性**: 引用的指南/文献是否是最新版本？
5. **边界情况**: 是否有特殊人群（孕妇/儿童/老人）的例外？

## Skills 使用（仅验证用）
如果需要独立验证 Generator 的证据，可以调用以下 Skills：
- **assess_risk**: 重新评估风险评分（检查是否遗漏症状）
- **clinical_guideline**: 查是否有更新版本或遗漏的禁忌症
- **search_knowledge**: 查反例、边界情况
- **analyze_symptoms**: 检查是否有遗漏的症状类别
- **deep_research**: 查最新研究是否推翻旧结论

**禁止调用**: recommend_lifestyle（你不负责给建议）、disease_code

## 判决标准
- **PASS**: 证据充分，推理链完整，无遗漏 → 直接放行
- **CHALLENGE**: 有可修复的疑问（遗漏证据、confidence偏高、边界情况未说明）
  → 问题追加到 evidence 后放行，标记 uncertainty
- **REJECT**: 有严重问题（高危症状遗漏、指南误读、逻辑矛盾）
  → 返回 Generator 附带 suggested_fix，要求修正

## 输出格式（必须严格遵守）
审查完成后，以 JSON 格式输出判决结果：
```json
{
  "verdict": "PASS",
  "challenges": [],
  "confidence_adjusted": 0.85
}
```
如果是 CHALLENGE 或 REJECT，challenges 数组中每项必须包含：
type（missed_symptom/insufficient_evidence/outdated_guideline/logic_gap/edge_case）、
description、severity（high/medium/low）、suggested_fix"""

    # =========================================================================
    # 公共 API
    # =========================================================================

    async def review(self, generator_output: Dict[str, Any]) -> Dict[str, Any]:
        """接收 Generator 的结构化输出，返回审查结论。

        Parameters
        ----------
        generator_output : dict
            Generator.generate() 的返回值，包含:
            · answer        — 自然语言回答
            · action_signal — ActionSignal.to_dict()
            · skill_trace   — [{skill, key_finding}, ...]

        Returns
        -------
        dict
            ReviewerVerdict.to_dict() + skill_trace（审查过程中调用的 Skills）。
        """
        # 构建结构化审查 prompt（不接触 Generator 的原始上下文）
        review_question = self._build_review_prompt(generator_output)

        # 运行 AgentLoop（LLM 可能调验证 Skills 做交叉验证）
        result = await self.run_loop({"question": review_question})

        # post_process_result 已从 LLM 输出中解析出 verdict
        return {
            "verdict":              result.get("verdict", "PASS"),
            "challenges":           result.get("challenges", []),
            "confidence_adjusted":  result.get("confidence_adjusted"),
            "reviewer_skill_trace": result.get("skill_trace", []),
        }

    def _build_review_prompt(self, gen_output: Dict[str, Any]) -> str:
        """将 Generator 的结构化输出转化为审查 prompt。

        关键设计：只传结构化字段，不传 Generator 的完整对话历史。
        这保证了 Reviewer 的上下文隔离 ——
        它看到的是 action_signal + skill_trace，而非原始推理过程。
        """
        signal = gen_output.get("action_signal", {})
        trace  = gen_output.get("skill_trace", [])

        # 格式化 skill_trace 为可读文本
        trace_lines = []
        for t in trace:
            trace_lines.append(
                f"  · {t.get('skill', '?')}: {t.get('key_finding', '')}"
            )
        trace_text = "\n".join(trace_lines) if trace_lines else "（无 Skill 调用记录）"

        return f"""请审查以下临床分析：

## Generator 的结论
{signal.get("result", "（无）")}

## 建议行动
{signal.get("proposed_action", "（未指定）")}

## 置信度
{signal.get("confidence", 0)}

## 证据列表
{signal.get("evidence", [])}

## 调用的 Skills 及其关键发现
{trace_text}

## 审查要求
逐项检查:
1. 用户的每个症状是否都被分析覆盖？
2. 每条证据是否真的支撑结论？是否有遗漏的反面证据？
3. 引用的指南/文献是否是最新版本？是否需要重新查询？
4. 置信度是否与证据的强度匹配？
5. 是否有特殊人群（孕妇/儿童/老人）的例外情况未说明？

如果需要，可以调用验证 Skills 做独立交叉验证。
审查完成后，请以 JSON 格式输出判决结果。"""

    # =========================================================================
    # post_process_result — 解析 LLM 输出为结构化 Verdict
    # =========================================================================

    async def post_process_result(
        self,
        result: Dict[str, Any],              # 初始 result dict
        final_response: str,                 # LLM 最终回答
        skill_results: Optional[List[Dict[str, Any]]] = None  # 本轮 Skill 调用
    ) -> Dict[str, Any]:
        """从 LLM 的最终回答中解析结构化 verdict。

        LLM 被要求以 JSON 格式输出判决。
        这里尝试解析 JSON；解析失败则降级为保守判决（CHALLENGE）。
        """

        # ---- 构建 skill_trace -------------------------------------------------
        trace = self._build_review_trace(skill_results or [])
        result["skill_trace"] = trace

        # ---- 解析 JSON 判决 ---------------------------------------------------
        parsed = self._parse_verdict_json(final_response)

        # ---- 保底：解析失败时的保守策略 ---------------------------------------
        if parsed is None:
            logger.warning(
                "Reviewer LLM did not produce valid JSON verdict, "
                "falling back to CHALLENGE"
            )
            parsed = {
                "verdict": "CHALLENGE",
                "challenges": [{
                    "type": "logic_gap",
                    "description": "Reviewer 未能生成结构化判决，"
                                   "自动标记为 CHALLENGE 以保留不确定性",
                    "severity": "medium",
                    "suggested_fix": "请 Review 流程重新执行",
                }],
                "confidence_adjusted": 0.50,
            }

        # ---- 写入 result ------------------------------------------------------
        result["verdict"]              = parsed.get("verdict", "CHALLENGE")
        result["challenges"]           = parsed.get("challenges", [])
        result["confidence_adjusted"]  = parsed.get("confidence_adjusted")

        logger.info(
            f"Reviewer verdict: {result['verdict']}, "
            f"challenges={len(result['challenges'])}"
        )

        return result

    # =========================================================================
    # 解析辅助
    # =========================================================================

    @staticmethod
    def _parse_verdict_json(text: str) -> Optional[Dict[str, Any]]:
        """尝试从文本中提取 JSON 判决。

        支持三种格式：
        1. 纯 JSON 代码块 (```json ... ```)
        2. 纯 JSON 代码块 (``` ... ```)
        3. 内联 JSON 对象 ({ ... })
        """
        # 格式 1 & 2: 代码块
        for pattern in [r'```json\s*([\s\S]*?)```', r'```\s*([\s\S]*?)```']:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

        # 格式 3: 内联 JSON（找到第一个 { 和对应的 }）
        start = text.find("{")
        if start == -1:
            return None

        # 从 start 开始找匹配的结束括号
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    @staticmethod
    def _build_review_trace(
        skill_results: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """构建审查过程中的 Skill 调用追踪。"""
        trace = []
        for sr in skill_results:
            name = sr.get("name", "unknown")
            r    = sr.get("result", {})
            if not isinstance(r, dict):
                trace.append({"skill": name, "key_finding": str(r)[:100]})
                continue

            finding = ""
            if name == "assess_risk":
                finding = f"独立复查: risk_level={r.get('risk_level', '?')}"
            elif name == "clinical_guideline":
                finding = f"重新查询: {r.get('guideline_title', r.get('answer', ''))}"
            elif name == "search_knowledge":
                finding = str(r.get("answer", ""))[:100]
            else:
                finding = str(r.get("answer", ""))[:100]

            trace.append({"skill": name, "key_finding": finding})

        return trace


