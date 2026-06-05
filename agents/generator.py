"""
Generator Agent —— Maker-Checker 管道中的"构建者"。

=============================================================================
作用
=============================================================================
Generator 是 Maker-Checker 中的 Maker（生成者）。它的唯一职责是：

1. 调用所有必要的 Skills 收集医学证据
2. 基于证据做出综合分析
3. 产出结构化 ActionSignal（含 result/evidence/confidence/proposed_action）

它不负责验证自己的输出 —— 那是 Reviewer 和 SafetyGate 的工作。

=============================================================================
数据流向
=============================================================================

Orchestrator
    │  调用 generate(user_query)
    ▼
Generator.generate()
    │  通过 AgentLoop 运行 LLM → 调 tools → 生成回答
    │  post_process_result 从 tool_results 中提取结构化数据
    ▼
返回:
    {
        "answer":        "...",   # LLM 的完整自然语言回答
        "action_signal": {...},   # ActionSignal.to_dict()
        "evidence_records": [...], # 顶层结构化证据实体
        "process_trace": {...}     # loaded_skills/tool_trace/tool_summary
    }

=============================================================================
关联模块
=============================================================================
· pipeline.action_signal — ActionSignal, ActionType, RISK_TO_ACTION, CONFIDENCE_BASE
· agents.base_agent  — BaseAgent（AgentLoop, LLMClient）
· agents.skill_registry_mixin — register_all_skills()
· agents.reviewer — Reviewer 消费此输出

=============================================================================
设计原则
=============================================================================
· 只构建，不验证 —— 职责单一
· 从 tool_results 提取结构化数据，不做 NLP 解析
· 置信度计算使用 CONFIDENCE_BASE 配置字典，消除魔法数字
· RISK_TO_ACTION 是唯一的 risk→action 映射源

@new  Maker-Checker 架构 (2026-06)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

# 导入基础组件
from agents.base import BaseAgent
from agents.evidence_extractor import (
    extract_evidence_records,
    merge_evidence_record_summaries,
)
from agents.skill_registry_mixin import SkillRegistryMixin
from core.llm_client import LLMClient

from pipeline.action_signal import (
    ActionSignal,
    ActionType,
    RISK_TO_ACTION,
    CONFIDENCE_BASE,
    CONFIDENCE_BONUS_GUIDELINE,
    CONFIDENCE_PENALTY_NO_EVIDENCE,
)


# ============================================================================
# GeneratorAgent — Maker
# ============================================================================

class GeneratorAgent(BaseAgent, SkillRegistryMixin):
    """临床综合分析 Agent —— Maker-Checker 的 Maker。

    调用全部 9 个 Skills 收集证据，产出综合分析 + ActionSignal。
    输出将被 Reviewer 严格审查。

    Parameters
    ----------
    agent_id : str
        Agent 标识，默认 "generator"。
    config : dict, optional
        配置项，包含 model / max_iterations / temperature 等。
    llm_client : LLMClient, optional
        复用的 LLM 客户端。默认创建新实例。
    """

    def __init__(
        self,
        agent_id: str = "generator",          # Agent 标识
        config: Optional[Dict[str, Any]] = None,  # 配置项
        llm_client=None                        # LLM 客户端（可选复用）
    ):
        # ---- 默认配置 -------------------------------------------------------
        config = config or {}
        config.setdefault("llm_profile", "generator")
        config.setdefault("max_iterations", 5)       # 允许足够的 tool 调用
        config.setdefault("max_tool_calls", 3)       # Generator 需要更多 tool 调用
        config.setdefault("temperature", 0.3)        # 生成温度：医疗综合回答需要稳，不宜过高
        config.setdefault("progressive_skills_enabled", True)  # v3.2: 启用 SKILL.md 渐进加载
        config.setdefault("skill_docs_dir", "skills")          # v3.2: 方法论 Skill 文档目录
        config.setdefault("skill_selection_llm_profile", "skill_selector")  # 轻量模型选择 Skills
        config.setdefault("repair_llm_profile", "generator_repair")  # REJECT 返修轮升级推理预算

        # ---- 初始化基类 -----------------------------------------------------
        BaseAgent.__init__(self, agent_id, config, llm_client)
        SkillRegistryMixin.__init__(self)

        logger.debug(
            f"GeneratorAgent initialized (id={agent_id})"
        )

    # =========================================================================
    # 工具注册
    # =========================================================================

    def register_tools(self) -> None:
        """注册全部 9 个 Skills（委托给 SkillRegistryMixin）。"""
        self.register_all_skills()
        self.register_structured_tools()

    # =========================================================================
    # 系统提示词 — 综合分析 + 结构化输出
    # =========================================================================

    def get_system_prompt(self) -> str:
        """返回系统提示词：定义综合分析框架和结构化输出要求。"""
        return """你是临床综合分析专家（Generator Agent）。你的任务是：

1. 根据用户问题，调用合适的 Skills 收集医学证据
2. 基于证据进行多维度综合分析
3. 输出结构化的结论

## Skills 使用策略
- 优先调用 **assess_risk** 评估风险等级
- 使用 **analyze_symptoms** 分析症状模式
- 调用 **clinical_guideline** 或 **deep_research** 获取权威指南
- 使用 **search_knowledge** 补充医学知识
- 使用 **recommend_lifestyle** 获取生活方式建议
- 最多调用 **2-3 个 Skills**，然后必须给出最终分析

## 输出要求
你的分析将被 Reviewer 严格审查，因此：
- 每个结论必须有具体的证据支撑
- 如果证据不足，明确说明不确定性
- 宁可标注低 confidence，不要假装确定

## 最终回答格式
最终回答应包含：
【综合分析】
基于证据的临床分析...

【风险评估】
风险等级和紧急程度...

【建议】
就医建议或自我护理建议...

【免责声明】
以上分析仅供参考，不能替代专业医生诊断。如有疑虑，请及时就医。"""

    # =========================================================================
    # 公共 API
    # =========================================================================

    async def generate(self, user_query: str) -> Dict[str, Any]:
        """执行完整的生成流程：AgentLoop → 后处理 → 返回结构化输出。

        Parameters
        ----------
        user_query : str
            用户的原始医学问题（如 "我胸痛伴呼吸困难，需要就医吗？"）。

        Returns
        -------
        dict
            {
                "answer":         str,    # LLM 完整自然语言回答
                "action_signal":  dict,   # ActionSignal.to_dict()
                "evidence_records": list, # 顶层结构化证据实体
                "process_trace":  dict,   # loaded_skills/tool_trace/tool_summary
            }
        """
        input_data = {"question": user_query}
        result = await self.run_loop(input_data)

        # result 已被 post_process_result 增强，包含 action_signal
        return {
            # v3.3: Checker 内部的 PreStopPolicy 需要基于用户原问做规则扫描，
            # 不能依赖 regenerate 时拼出来的修正提示文本。
            "user_query":    user_query,
            "answer":        result.get("answer", ""),
            "action_signal": result.get("action_signal", {}),
            "evidence_records": result.get("evidence_records", []),
            "process_trace": result.get("process_trace", {}),
        }

    async def regenerate(
        self,
        user_query: str,          # 用户原始问题
        challenges: List[Dict[str, str]]  # Reviewer 的驳回理由
    ) -> Dict[str, Any]:
        """REJECT 后修正 —— 接收 Reviewer 的具体驳回理由，重新生成。

        Parameters
        ----------
        user_query : str
            用户原始医学问题。
        challenges : list of dict
            Reviewer 的 challenges 列表，每项含 type/description/suggested_fix。

        Returns
        -------
        dict
            同 generate() 的返回格式。
        """
        # 构建修正指令
        fix_text = self._format_challenges(challenges)
        regenerate_query = (
            f"原始问题：{user_query}\n\n"
            f"上轮分析的修正要求（必须逐条修正）：\n{fix_text}\n\n"
            f"请重新进行完整的临床分析，逐条修正上述问题后输出。"
        )

        regenerated = await self._generate_with_repair_profile(regenerate_query)
        # 保留原始用户问题，供 Checker precheck / SafetyGate / trace 使用。
        regenerated["user_query"] = user_query
        regenerated.setdefault("process_trace", {})
        regenerated["process_trace"]["repair_profile"] = self.config.get("repair_llm_profile")
        return regenerated

    async def _generate_with_repair_profile(self, regenerate_query: str) -> Dict[str, Any]:
        """使用 repair LLM profile 运行返修轮。

        Round 1 Maker 默认使用 non-thinking fast profile；只有 Checker / PreStop
        明确 REJECT 后，返修轮才临时切到 `generator_repair`。这把高成本
        thinking/strong 模型变成“被审查触发的修复资源”，而不是每次都默认消耗。

        如果测试注入了 fake llm_client，则不切换真实 profile，避免单元测试触发 API。
        """

        repair_profile = self.config.get("repair_llm_profile")
        if not repair_profile or getattr(self, "_external_llm_client", False):
            return await self.generate(regenerate_query)

        original_client = self.llm_client
        original_profile = self.config.get("llm_profile")
        self.llm_client = LLMClient(profile=repair_profile)
        self.config["llm_profile"] = repair_profile
        logger.info("Generator repair round using LLM profile: {}", repair_profile)
        try:
            return await self.generate(regenerate_query)
        finally:
            self.llm_client = original_client
            if original_profile is not None:
                self.config["llm_profile"] = original_profile

    def _format_challenges(self, challenges: List[Dict[str, str]]) -> str:
        """将 Reviewer 的 challenges 格式化为修正指令文本。"""
        lines = ["上一轮分析存在以下问题，请逐一修正："]
        for i, c in enumerate(challenges, 1):
            lines.append(
                f"{i}. [{c.get('type', 'unknown')}] "
                f"{c.get('description', '')}"
            )
            fix = c.get("suggested_fix", "")
            if fix:
                lines.append(f"   建议修正方案: {fix}")
        return "\n".join(lines)

    # =========================================================================
    # post_process_result — 从 tool 返回值提取 ActionSignal
    # =========================================================================

    async def post_process_result(
        self,
        result: Dict[str, Any],              # 初始 result dict
        final_response: str,                 # LLM 最终自然语言回答
        tool_results: Optional[List[Dict[str, Any]]] = None  # tool call 记录
    ) -> Dict[str, Any]:
        """从 tool 返回值中提取结构化信息，生成 ActionSignal。

        不解析自然语言 —— 直接读取 tool 返回的结构化字段。
        如果本轮没有工具结果，也会生成低证据强度的 ActionSignal，交给 Checker / SafetyGate 继续兜底。
        """

        _tr = tool_results or []

        # ---- 构建 process_trace.tool_summary（记录每个工具的关键发现）----
        process_trace = dict(result.get("process_trace", {}) or {})
        process_trace["tool_summary"] = self._build_tool_summary(_tr)
        result["process_trace"] = process_trace

        # ---- 从 tool_results 中提取关键数据 -------------------------------
        risk_level    = self._extract_risk_level(_tr)
        evidence_records = extract_evidence_records(_tr)
        evidence      = self._extract_evidence(_tr, final_response)
        evidence      = merge_evidence_record_summaries(
            evidence,
            evidence_records,
        )
        proposed_action = self._determine_action(risk_level, _tr)
        confidence    = self._calculate_confidence(
            risk_level, evidence, _tr
        )

        # ---- 构建 ActionSignal ----------------------------------------------
        signal = ActionSignal(
            result          = self._summarize_response(final_response),
            evidence        = evidence,
            confidence      = confidence,
            proposed_action = proposed_action,
        )

        action_signal = signal.to_dict()
        # 完整结构化证据只放顶层 evidence_records；action_signal 只保留引用 id 和短摘要。
        action_signal["evidence_ids"] = [
            str(item.get("id"))
            for item in evidence_records
            if item.get("id")
        ]
        result["action_signal"] = action_signal
        result["evidence_records"] = evidence_records

        logger.info(
            f"Generator action_signal: action={proposed_action}, "
            f"confidence={confidence}, evidence_count={signal.evidence_count}"
        )

        return result

    # =========================================================================
    # 提取辅助方法
    # =========================================================================

    def _build_tool_summary(
        self,
        tool_results: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """构建 tool_summary —— 每个 tool call 的关键发现摘要。

        tool_summary 属于 process_trace，不属于 action_signal。
        不记录完整返回值（太长），只提取关键的结构化字段。
        """
        trace = []
        for sr in tool_results:
            name   = sr.get("name", "unknown")
            r      = sr.get("result", {})
            if not isinstance(r, dict):
                trace.append({"tool": name, "key_finding": str(r)[:100]})
                continue

            # 根据 Skill 类型提取关键字段
            finding = ""
            if name == "assess_risk":
                finding = f"risk_level={r.get('risk_level', '?')}"
            elif name == "analyze_symptoms":
                patterns = r.get("patterns", [])
                diseases = r.get("possible_diseases", [])
                finding = f"patterns={patterns[:3]}, diseases={diseases[:3]}"
            elif name in ("clinical_guideline", "search_knowledge"):
                title = r.get("guideline_title") or r.get("answer", "")
                finding = str(title)[:120]
            elif name == "deep_research":
                finding = f"deep_research_completed"
            elif name == "recommend_lifestyle":
                finding = "lifestyle_recommendations_provided"
            elif name == "disease_code":
                finding = f"disease_code_lookup"
            else:
                finding = str(r.get("answer", ""))[:100]

            trace.append({"tool": name, "key_finding": finding})

        return trace

    def _extract_risk_level(
        self,
        tool_results: List[Dict[str, Any]]
    ) -> str:
        """从 tool_results 中提取 risk_level。

        优先读取 assess_risk tool 返回的结构化 risk_level 字段，
        无 tool 结果时返回 "unknown"。
        """
        for sr in tool_results:
            if sr.get("name") == "assess_risk":
                r = sr.get("result", {})
                if isinstance(r, dict):
                    level = r.get("risk_level", "")
                    if level in RISK_TO_ACTION:
                        return level
        return "unknown"

    def _extract_evidence(
        self,
        tool_results: List[Dict[str, Any]],
        final_response: str
    ) -> List[str]:
        """提取证据列表 —— 从 tool 返回值中收集结构化证据项。

        来源优先级：
        1. assess_risk 的 risk_level + recommendation
        2. clinical_guideline 的 guideline_title + organization
        3. analyze_symptoms 的 patterns + possible_diseases
        4. deep_research 表示已执行深度研究
        """
        evidence: List[str] = []

        for sr in tool_results:
            r = sr.get("result", {})
            if not isinstance(r, dict):
                continue

            name = sr.get("name", "")

            if name == "assess_risk":
                level = r.get("risk_level", "")
                rec   = r.get("recommendation", "")
                if level:
                    evidence.append(f"风险等级: {level}")
                if rec and rec != evidence[-1] if evidence else True:
                    evidence.append(f"就医建议: {rec}")

            elif name == "clinical_guideline":
                title = r.get("guideline_title", "")
                org   = r.get("organization", "")
                year  = r.get("year", "")
                if title:
                    evidence.append(f"指南: {title}")
                if org and org != "N/A":
                    evidence.append(f"发布机构: {org}")
                if year and year != "N/A":
                    evidence.append(f"发布年份: {year}")

            elif name == "analyze_symptoms":
                patterns = r.get("patterns", [])
                diseases = r.get("possible_diseases", [])
                for p in patterns[:3]:
                    evidence.append(p)
                for d in diseases[:3]:
                    evidence.append(f"可能关联: {d}")

            elif name == "deep_research":
                evidence.append("深度研究已完成")

            elif name == "recommend_lifestyle":
                evidence.append("生活方式建议已提供")

        # 去重保序
        seen = set()
        deduped = []
        for item in evidence:
            if item not in seen:
                deduped.append(item)
                seen.add(item)

        return deduped[:8]  # 最多 8 条，避免过长

    def _determine_action(
        self,
        risk_level: str,               # 提取到的风险等级
        tool_results: List[Dict[str, Any]]  # tool call 记录
    ) -> str:
        """根据 tool 返回值确定 proposed_action。

        优先级：
        1. assess_risk 的 risk_level → RISK_TO_ACTION 映射
        2. clinical_guideline 有结果 → follow_guideline
        3. recommend_lifestyle 有结果 → recommend_lifestyle
        4. 无结果 → observe
        """

        # 优先：风险驱动映射
        action = RISK_TO_ACTION.get(risk_level, ActionType.OBSERVE)

        # 如果有指南证据，优先 follow_guideline（除非风险已是 urgent）
        if action not in (
            ActionType.RECOMMEND_URGENT_CARE,
            ActionType.RECOMMEND_TEST,
        ):
            if self._has_tool_call(tool_results, "clinical_guideline"):
                action = ActionType.FOLLOW_GUIDELINE

        # 如果只有生活方式建议，映射为 lifestyle
        if action in (ActionType.OBSERVE, ActionType.FOLLOW_GUIDELINE):
            has_lifestyle = self._has_tool_call(
                tool_results, "recommend_lifestyle"
            )
            has_risk_info = self._has_tool_call(
                tool_results, "assess_risk"
            )
            if has_lifestyle and not has_risk_info:
                action = ActionType.RECOMMEND_LIFESTYLE

        return action

    def _calculate_confidence(
        self,
        risk_level: str,               # 风险等级
        evidence: List[str],           # 证据列表
        tool_results: List[Dict[str, Any]]  # tool call 记录
    ) -> float:
        """计算 self-assessed confidence。

        公式：
        base = CONFIDENCE_BASE[risk_level 或 有 tool 调用用]
        + 找到权威指南 → +CONFIDENCE_BONUS_GUIDELINE
        - 无证据 → -CONFIDENCE_PENALTY_NO_EVIDENCE
        最终 clamp 到 [0.0, 1.0]
        """

        # ---- 基础分 ---------------------------------------------------------
        if tool_results:
            # 有 tool 调用 → 用风险等级驱动的基础分
            base = CONFIDENCE_BASE.get(
                risk_level,
                CONFIDENCE_BASE["skill_used"]  # 有 tool 但未知风险 → 0.70
            )
        else:
            # 无 tool 调用 → 降级置信度
            base = CONFIDENCE_BASE["fallback"]

        # ---- 指南奖励 -------------------------------------------------------
        guideline_found = self._has_tool_call(
            tool_results, "clinical_guideline"
        ) or self._has_tool_call(tool_results, "deep_research")

        if guideline_found:
            base += CONFIDENCE_BONUS_GUIDELINE

        # ---- 无证据惩罚 -----------------------------------------------------
        if not evidence:
            base -= CONFIDENCE_PENALTY_NO_EVIDENCE

        return round(max(0.0, min(base, 1.0)), 2)

    # =========================================================================
    # 工具方法
    # =========================================================================

    @staticmethod
    def _has_tool_call(
        tool_results: List[Dict[str, Any]],
        tool_name: str
    ) -> bool:
        """检查是否调用了指定 tool 且有非空返回。"""
        for tr in tool_results:
            if tr.get("name") == tool_name:
                r = tr.get("result", {})
                if isinstance(r, dict) and r:
                    return True
        return False

    @staticmethod
    def _summarize_response(text: str, max_len: int = 200) -> str:
        """将 LLM 的完整回答压缩为简短摘要（用于 action_signal.result）。"""
        # 取前 max_len 个字符，在句号处截断
        truncated = text[:max_len]
        last_period = max(
            truncated.rfind("。"),
            truncated.rfind("？"),
            truncated.rfind("\n"),
        )
        if last_period > max_len // 2:
            return truncated[: last_period + 1]
        return truncated
