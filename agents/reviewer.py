"""
Reviewer Agent —— Maker-Checker 管道中的"证伪者"。

=============================================================================
作用
=============================================================================
Reviewer 是 Maker-Checker 中的 Checker（审查者）。它的唯一目标是：

**证伪 Generator 的结论，而非提供替代答案。**

它接收 Generator 的结构化输出（action_signal + evidence_records + process_trace），
从空白上下文开始审查，不受 Generator 推理路径的影响。
可以重新调用验证类 Skills 做独立交叉验证。

=============================================================================
数据流向
=============================================================================

Orchestrator
    │  调用 review(generator_output)
    │  传入: {answer, action_signal, evidence_records, process_trace}
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
import time
from typing import Any, Dict, List, Optional

from loguru import logger

# 复用基础组件
from agents.base import BaseAgent
from agents.skill_registry_mixin import SkillRegistryMixin
from core.prestop_policy import PreStopPolicy, PreStopResult

from pipeline.action_signal import ActionType


CHECKER_ISSUE_TYPES = frozenset({
    "TOOL_GAP",
    "EVIDENCE_GAP",
    "SAFETY_RISK",
    "CONTEXT_GAP",
    "OUTPUT_BOUNDARY",
})


CHECKER_SYSTEM_PROMPT = """你是 Maker-Checker 架构中的 Checker Agent。

你的职责是审查 Maker 的过程和输出，不生成替代医学答案。

## Two-stage Audit

Reviewer.review() 在调用你之前已经运行 deterministic PreStopPolicy：
- Tool Path Audit: required tools 是否明显漏调
- Evidence Path Audit: action_signal / proposed_action / 高置信 evidence 是否存在硬缺口
- Safety Process Audit: 高风险问题是否走过必要安全流程

你现在负责 LLM semantic audit，不重复 deterministic precheck 已经能稳定判断的事情。

## Issue Types

只能使用以下 5 类 issue type：
- TOOL_GAP: 工具路径、工具参数、loaded_skills 与 tool_trace 不一致
- EVIDENCE_GAP: 证据不足、不支撑结论、过旧、低相关或把非医学证据当证据
- SAFETY_RISK: 红旗症状、特殊人群、停药/处方/剂量等医疗安全风险
- CONTEXT_GAP: 关键信息不足但 Maker 强行回答或置信度过高
- OUTPUT_BOUNDARY: 最终表达缺少边界说明、就医提示或非诊断声明

## Required Cross-check

必须交叉审查：
- loaded_skills: Maker 加载了哪些 SKILL.md 方法论
- tool_trace: Maker 实际调用了哪些工具
- evidence_records: RAG/医学工具返回了哪些结构化证据
- action_signal: Maker 最终结论、置信度和 proposed_action

示例：
- loaded_skills 包含 symptom_triage 且用户有高危症状，应看到风险评估或足够安全降级。
- loaded_skills 包含 medication_safety，应看到药物安全或知识库查证。
- loaded_skills 包含 lab_report，应看到指标/报告参考查证。

## Memory Boundary

- memory_context_lookup / memory_context 只能作为用户上下文，不能作为医学证据。
- 如果 Maker 把 memory_context 当成 guideline、drug_safety、lab_reference 或 clinical evidence，标记 EVIDENCE_GAP。

## Verdict

- PASS: 没有实质问题，可以进入 SafetyGate。
- CHALLENGE: 有可接受的不确定性或轻中度问题，应降低置信度或补充边界，但不需要重做。
- REJECT: 关键工具路径、证据链或安全边界存在严重问题，应退回 Maker 修正。

## Output JSON

只能输出 JSON，不要输出自然语言解释：

{
  "verdict": "PASS",
  "challenges": [
    {
      "type": "TOOL_GAP",
      "description": "具体问题",
      "severity": "high",
      "suggested_fix": "给 Maker 的修复要求"
    }
  ],
  "confidence_adjusted": 0.65
}
"""


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
        llm_client=None,                                  # LLM 客户端（可选复用）
        prestop_policy: Optional[PreStopPolicy] = None    # Checker 内部确定性预检策略
    ):
        # ---- 默认配置 -------------------------------------------------------
        config = config or {}
        config.setdefault("llm_profile", "reviewer")
        config.setdefault("max_iterations", 4)            # 审查可能调 2-3 验证 Skills + 1 轮输出
        config.setdefault("temperature", 0.0)             # 审查要求稳定和一致性

        # ---- 初始化基类 -----------------------------------------------------
        BaseAgent.__init__(self, agent_id, config, llm_client)
        SkillRegistryMixin.__init__(self)
        # v3.3: PreStopPolicy 归 Checker 管，作为 LLM 审查前的零 token 预检。
        # 规则模块保持独立，方便单元测试和后续替换 Signal Catalog。
        self.prestop_policy = prestop_policy or PreStopPolicy()

        logger.debug(f"ReviewerAgent initialized (id={agent_id})")

    # =========================================================================
    # 工具注册
    # =========================================================================

    def register_tools(self) -> None:
        """注册审查用工具；Checker 只能验证，不能生成治疗建议。"""
        self.register_all_skills(exclude={"recommend_lifestyle", "disease_code"})

    # =========================================================================
    # 系统提示词 — 对抗式证伪立场
    # =========================================================================

    def get_system_prompt(self) -> str:
        """返回 v3 Checker 统一系统提示词。"""
        return CHECKER_SYSTEM_PROMPT

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
            · evidence_records — 结构化证据实体
            · process_trace    — loaded_skills/tool_trace/tool_summary

        Returns
        -------
        dict
            ReviewerVerdict.to_dict() + reviewer_tool_summary（审查过程中调用的验证工具摘要）。
        """
        # 第一阶段：确定性预检。这里不调用 LLM，只检查过程是否满足最低门槛。
        # 如果失败，Checker 直接返回 REJECT，让 Orchestrator 驱动 Maker 返修。
        total_start = time.perf_counter()
        timings: Dict[str, Any] = {
            "review_total_ms": 0.0,
            "prestop_ms": 0.0,
            "llm_audit_ms": 0.0,
            "agent_loop": {},
        }
        t_precheck = time.perf_counter()
        precheck = self._run_prestop_precheck(generator_output)
        timings["prestop_ms"] = self._elapsed_ms(t_precheck)
        generator_output["prestop_result"] = precheck.to_dict()
        if not precheck.passed:
            logger.warning(
                "Reviewer precheck rejected draft before LLM audit | issues={}",
                len(precheck.issues),
            )
            result = self._precheck_reject(precheck)
            timings["review_total_ms"] = self._elapsed_ms(total_start)
            result["timings"] = timings
            return result

        # 第二阶段：构建结构化审查 prompt（不接触 Generator 的原始上下文）
        review_question = self._build_review_prompt(generator_output)

        # 运行 AgentLoop（LLM 可能调验证 Skills 做交叉验证）
        t_llm_audit = time.perf_counter()
        result = await self.run_loop({"question": review_question})
        timings["llm_audit_ms"] = self._elapsed_ms(t_llm_audit)
        timings["agent_loop"] = (result.get("process_trace", {}) or {}).get("timings", {})
        timings["review_total_ms"] = self._elapsed_ms(total_start)

        # post_process_result 已从 LLM 输出中解析出 verdict
        return {
            "verdict":              result.get("verdict", "PASS"),
            "challenges":           result.get("challenges", []),
            "confidence_adjusted":  result.get("confidence_adjusted"),
            "reviewer_tool_summary": result.get("review_tool_summary", []),
            "prestop_result":       precheck.to_dict(),
            "review_stage":         "llm_audit",
            "timings":              timings,
        }

    def _run_prestop_precheck(self, generator_output: Dict[str, Any]) -> PreStopResult:
        """运行 Checker 内部的确定性预检。

        PreStopPolicy 需要看到用户原问、工具轨迹、证据和 action_signal。
        这些输入来自 Maker 的结构化输出；Reviewer 不读取 Maker 的完整对话历史，
        因此仍然保持上下文隔离。
        """
        action_signal = generator_output.get("action_signal")
        evidence = list(generator_output.get("evidence_records", []) or [])
        if isinstance(action_signal, dict):
            evidence.extend(action_signal.get("evidence", []) or [])

        process_trace = generator_output.get("process_trace", {}) or {}

        return self.prestop_policy.before_review(
            user_query=str(generator_output.get("user_query", "")),
            route_decision=generator_output.get("route_decision"),
            tool_trace=process_trace.get("tool_trace", []) or [],
            evidence=evidence,
            action_signal=action_signal,
            draft_answer=generator_output.get("answer"),
        )

    @staticmethod
    def _precheck_reject(precheck: PreStopResult) -> Dict[str, Any]:
        """把 PreStopResult 转成 Checker verdict。

        Orchestrator 不需要理解 PreStopPolicy 的规则细节，只需要把这个
        REJECT 当作普通 Checker 驳回处理，并把 challenges 传给 Maker.regenerate。
        """
        return {
            "verdict": "REJECT",
            "reject_type": precheck.reject_type,
            "challenges": ReviewerAgent._prestop_challenges(precheck),
            "confidence_adjusted": None,
            "reviewer_tool_summary": [],
            "prestop_result": precheck.to_dict(),
            "review_stage": "precheck",
        }

    @staticmethod
    def _prestop_challenges(precheck: PreStopResult) -> List[Dict[str, str]]:
        """把确定性预检问题转成 Maker 可读的返修要求。"""
        challenges: List[Dict[str, str]] = []
        for issue in precheck.issues:
            challenges.append({
                "type": issue.type,
                "description": issue.description,
                "severity": issue.severity,
                "suggested_fix": precheck.repair_message,
            })
        return challenges

    def _render_checker_prompt(self, gen_output: Dict[str, Any]) -> str:
        """渲染 v3.4 Checker 语义审计 prompt。

        这里只传 Maker 的结构化输出，不传 Maker 的完整对话历史。
        Checker 可以看到 loaded_skills / tool_trace / evidence_records，
        因而能审查“加载的方法论”和“实际工具路径”是否一致。
        """
        signal = gen_output.get("action_signal", {}) or {}
        process_trace = gen_output.get("process_trace", {}) or {}
        loaded_skills = process_trace.get("loaded_skills", []) or []
        tool_trace = process_trace.get("tool_trace", []) or []
        evidence_records = gen_output.get("evidence_records", []) or []
        tool_summary = process_trace.get("tool_summary", []) or []
        prestop_result = gen_output.get("prestop_result", {}) or {}

        return f"""请审查以下 Maker 输出。你只能审查，不要生成替代医学答案。

## User Query
{gen_output.get("user_query", "")}

## Maker Draft Answer
{gen_output.get("answer", "")}

## Action Signal
{json.dumps(signal, ensure_ascii=False, indent=2)}

## Loaded Skills
{json.dumps(loaded_skills, ensure_ascii=False, indent=2)}

## Tool Trace
{json.dumps(tool_trace, ensure_ascii=False, indent=2)}

## Evidence Records
{json.dumps(evidence_records, ensure_ascii=False, indent=2)}

## Maker Tool Summary
{json.dumps(tool_summary, ensure_ascii=False, indent=2)}

## Deterministic Precheck Result
{json.dumps(prestop_result, ensure_ascii=False, indent=2)}

## Required Audit
1. 检查 loaded_skills 与 tool_trace 是否一致。
2. 检查 tool_trace 的参数和结果是否支持 action_signal。
3. 检查 evidence_records 是否支撑关键 claim 和 proposed_action。
4. 检查是否存在 SAFETY_RISK、CONTEXT_GAP 或 OUTPUT_BOUNDARY。
5. 不重复 PreStopPolicy 已经稳定检查过的缺失 required-tool 硬问题，除非工具参数或证据语义仍不合理。

## Allowed Issue Types
TOOL_GAP / EVIDENCE_GAP / SAFETY_RISK / CONTEXT_GAP / OUTPUT_BOUNDARY

## Output JSON Only
{{
  "verdict": "PASS",
  "challenges": [],
  "confidence_adjusted": 0.7
}}
"""

    def _build_review_prompt(self, gen_output: Dict[str, Any]) -> str:
        """将 Maker 输出渲染为 v3 Checker 审查 prompt。"""
        return self._render_checker_prompt(gen_output)

    # =========================================================================
    # post_process_result — 解析 LLM 输出为结构化 Verdict
    # =========================================================================

    async def post_process_result(
        self,
        result: Dict[str, Any],              # 初始 result dict
        final_response: str,                 # LLM 最终回答
        tool_results: Optional[List[Dict[str, Any]]] = None  # 本轮 tool 调用
    ) -> Dict[str, Any]:
        """从 LLM 的最终回答中解析结构化 verdict。

        LLM 被要求以 JSON 格式输出判决。
        这里尝试解析 JSON；解析失败则降级为保守判决（CHALLENGE）。
        """

        # ---- 构建 review_trace -----------------------------------------------
        trace = self._build_review_trace(tool_results or [])
        result["review_tool_summary"] = trace

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
        parsed = self._normalize_verdict_payload(parsed)

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
    def _normalize_verdict_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """规范化 Checker LLM 输出。

        v3.4 将 issue type 收敛为 5 类。模型如果沿用旧类型或输出未知类型，
        这里会保守归一到 CONTEXT_GAP，避免 eval/trace 出现无限类别。
        """
        verdict = str(payload.get("verdict", "CHALLENGE")).upper()
        if verdict not in ReviewerVerdict.VALID_VERDICTS:
            verdict = "CHALLENGE"

        raw_challenges = payload.get("challenges", []) or []
        if not isinstance(raw_challenges, list):
            raw_challenges = []

        normalized_challenges: List[Dict[str, Any]] = []
        for challenge in raw_challenges:
            if not isinstance(challenge, dict):
                continue
            issue_type = str(challenge.get("type", "CONTEXT_GAP")).upper()
            if issue_type not in CHECKER_ISSUE_TYPES:
                issue_type = "CONTEXT_GAP"

            normalized = dict(challenge)
            normalized["type"] = issue_type
            normalized.setdefault("severity", "medium")
            normalized.setdefault("description", "")
            normalized.setdefault("suggested_fix", "")
            normalized_challenges.append(normalized)

        return {
            "verdict": verdict,
            "challenges": normalized_challenges,
            "confidence_adjusted": payload.get("confidence_adjusted"),
        }

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
    def _elapsed_ms(start: float) -> float:
        """返回从 start 到当前的毫秒耗时，统一保留 2 位小数。"""
        return round((time.perf_counter() - start) * 1000, 2)

    @staticmethod
    def _build_review_trace(
        tool_results: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """构建审查过程中 Reviewer 自己的 tool 调用追踪。"""
        trace = []
        for sr in tool_results:
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
