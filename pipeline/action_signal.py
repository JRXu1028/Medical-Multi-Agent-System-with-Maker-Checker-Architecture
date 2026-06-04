"""
统一 action_signal 数据契约 —— Maker-Checker 管道的唯一结构化通信格式。

=============================================================================
作用
=============================================================================
Maker-Checker 系统中的每个 Agent 在后处理后产出一个 ActionSignal。
本模块定义：

1. ActionType     — Agent 可提出的标准化动作词汇（如 recommend_urgent_care）
2. ActionSignal   — 贯穿管道每一阶段的结构化输出 dataclass
3. CONFLICT_PAIRS — 只读的动作冲突对表
4. RISK_TO_ACTION — 风险等级 → 动作的单一映射源（所有 Agent 共用）
5. CONFIDENCE_BASE — 可配置的置信度启发值（消除魔法数字）

=============================================================================
数据流向（谁读 / 谁写）
=============================================================================

Generator.post_process_result()
    ↓  从 Skill 返回值构建 ActionSignal
    ↓  存入 result["action_signal"]
    ↓
Reviewer.review()
    ↓  读取 ActionSignal + skill_trace
    ↓  可选重新调用验证 Skills
    ↓  输出 verdict (PASS / CHALLENGE / REJECT)
    ↓
SafetyGate.check()
    ↓  读取 ActionSignal.proposed_action + user_query
    ↓  执行确定性安全检查
    ↓  返回 GateResult (PASS or BLOCK)
    ↓
LeadAgent.express()
    ↓  读取最终的 ActionSignal
    ↓  渲染为面向患者的自然语言
    ↓  标注是否被 Gate 覆盖或强制安全兜底

=============================================================================
关联模块
=============================================================================
· pipeline.safety_gate                  — 导入 ActionType
· agents.generator              — 导入 ActionSignal, RISK_TO_ACTION, CONFIDENCE_BASE
· agents.reviewer               — 导入 ActionSignal, ActionType
· pipeline.orchestrator   — 导入 ActionSignal, CONFLICT_PAIRS
· pipeline.conflict_resolver (旧)       — 保持不变，作为降级路径

=============================================================================
设计原则
=============================================================================
· 不做 NLP 解析 —— 所有下游消费者读取类型化字段，不猜测自然语言
· RISK_TO_ACTION 是唯一的 risk→action 映射点 —— 修改只需改一处
· CONFIDENCE_BASE 是纯 dict —— 测试或子类中可轻松覆盖

@new  Maker-Checker 架构 (2026-06)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List


# ============================================================================
# ActionType — 标准化的动作词汇表
# ============================================================================

class ActionType(str, Enum):
    """Agent 可在 ActionSignal 中提出的动作。

    继承 StrEnum，序列化时自动转为纯字符串，
    在 JSON / dict 上下文中保持互操作性。

    各值的含义
    ----------
    RECOMMEND_URGENT_CARE : 建议立即就医（急诊 / 拨打 120）
    RECOMMEND_TEST        : 建议进一步检查或专科转诊
    FOLLOW_GUIDELINE      : 建议遵循已发布的临床指南
    RECOMMEND_SELF_CARE   : 居家自护安全（休息 / 非处方药）
    RECOMMEND_LIFESTYLE   : 饮食、运动、睡眠等生活方式调整
    OBSERVE               : 观察症状变化，加重时就医
    CITE_EVIDENCE         : 仅提供证据 / 参考文献，不提出行动建议
    NO_TEST_NEEDED        : 明确表示不需要进一步检查
    """

    RECOMMEND_URGENT_CARE = "recommend_urgent_care"  # 建议立即就医
    RECOMMEND_TEST        = "recommend_test"         # 建议进一步检查
    FOLLOW_GUIDELINE      = "follow_guideline"       # 遵循临床指南
    RECOMMEND_SELF_CARE   = "recommend_self_care"    # 居家自护
    RECOMMEND_LIFESTYLE   = "recommend_lifestyle"    # 生活方式调整
    OBSERVE               = "observe"                # 观察随访
    CITE_EVIDENCE         = "cite_evidence"          # 仅提供证据
    NO_TEST_NEEDED        = "no_test_needed"         # 无需检查


# ============================================================================
# ActionSignal — 贯穿管道的唯一结构化契约
# ============================================================================

@dataclass
class ActionSignal:
    """Agent 在后处理阶段产出的结构化临床输出。

    这是 Maker-Checker 管道中**唯一的数据契约**。
    没有任何下游组件解析自由文本 —— 它们只读取这些类型化字段。

    Parameters
    ----------
    result : str
        自然语言总结（1-3 句），描述 Agent 的临床结论。
        **此文本中的每一项声明都必须被 evidence 中的至少一条证据支撑。**

    evidence : list of str
        从 Skill 返回值中提取的机器可读证据项。
        示例：
        · 症状名（"胸痛", "呼吸困难"）
        · 指南标题（"ESC 2024 胸痛指南"）
        · 风险关键词（"high", "emergency"）
        · 发布机构（"WHO", "中华医学会"）

    confidence : float
        自评置信度，范围 [0.0, 1.0]。
        由 Agent 根据以下因素计算：
        · assess_risk 返回的结构化 risk_level
        · clinical_guideline 是否找到权威来源
        · evidence 条目的数量和质量
        · 是否有 skill_results 可用（无则降级）

    proposed_action : str
        ActionType 之一。Agent 认为系统应采取的行动。
        通过 RISK_TO_ACTION 映射（风险类动作）
        或由 Agent 的领域逻辑直接设定（证据/生活方式类动作）。
    """

    # ---- 字段 ---------------------------------------------------------------
    result:          str       = ""   # 自然语言结论（1-3 句）
    evidence:        List[str] = field(default_factory=list)  # 机器可读证据项
    confidence:      float     = 0.0  # 自评置信度 [0.0, 1.0]
    proposed_action: str       = ""   # ActionType 之一

    # ========================================================================
    # 序列化
    # ========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """转为纯 dict，用于存入 Contribution.result 或管道间传递。"""
        return {
            "result":          self.result,
            "evidence":        self.evidence,
            "confidence":      self.confidence,
            "proposed_action": self.proposed_action,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActionSignal":
        """从纯 dict 重建 ActionSignal。

        缺失的 key 取安全默认值 ——
        即使数据不完整也始终可重建，不会抛异常。
        """
        return cls(
            result          = d.get("result", ""),
            evidence        = d.get("evidence", []),
            confidence      = float(d.get("confidence", 0.0)),
            proposed_action = d.get("proposed_action", ""),
        )

    # ========================================================================
    # 校验辅助属性
    # ========================================================================

    @property
    def is_valid(self) -> bool:
        """proposed_action 是否为合法的 ActionType 值。"""
        return self.proposed_action in ActionType._value2member_map_

    @property
    def evidence_count(self) -> int:
        """当前 evidence 条目数。"""
        return len(self.evidence)

    @property
    def has_evidence(self) -> bool:
        """是否至少有一条 evidence。"""
        return len(self.evidence) > 0

    # ========================================================================
    # 变更辅助方法
    # ========================================================================

    def merge_evidence(self, items: List[str]) -> None:
        """追加 items 中尚未存在的条目（去重）。

        Orchestrator 用于将 Reviewer 的 CHALLENGE 描述合并到
        evidence 列表中，然后传递给 SafetyGate 检查。
        """
        existing = set(self.evidence)
        for item in items:
            if item not in existing:
                self.evidence.append(item)
                existing.add(item)


# ============================================================================
# CONFLICT_PAIRS — 不可共存的冲突动作对
# ============================================================================

# 只读的 frozenset of frozenset。
# 每个内层 frozenset 表示一对不能同时成为最终建议的动作。
# 由冲突检测步骤使用，判断 Reviewer 是否需要升级处理。
CONFLICT_PAIRS: FrozenSet[FrozenSet[str]] = frozenset({
    # 紧急就医 与 居家自护/观察 不可共存
    frozenset({ActionType.RECOMMEND_URGENT_CARE, ActionType.RECOMMEND_SELF_CARE}),
    frozenset({ActionType.RECOMMEND_URGENT_CARE, ActionType.OBSERVE}),
    # 建议检查 与 明确无需检查 不可共存
    frozenset({ActionType.RECOMMEND_TEST,       ActionType.NO_TEST_NEEDED}),
})


# ============================================================================
# RISK_TO_ACTION — risk→action 的唯一映射源
# ============================================================================

# 将 assess_risk Skill 返回的结构化 risk_level 映射到标准 ActionType。
# 所有处理风险信息的 Agent 共用此表 ——
# 修改只需改一处，所有 Agent 自动同步。
RISK_TO_ACTION: Dict[str, str] = {
    "emergency": ActionType.RECOMMEND_URGENT_CARE,  # 紧急 → 立即就医
    "high":      ActionType.RECOMMEND_URGENT_CARE,  # 高危 → 立即就医
    "medium":    ActionType.RECOMMEND_TEST,         # 中危 → 建议检查
    "low":       ActionType.OBSERVE,                # 低危 → 观察随访
    "unknown":   ActionType.OBSERVE,                # 未知 → 保守观察
}


# ============================================================================
# CONFIDENCE_BASE — 可配置的置信度启发值
# ============================================================================

# 按场景键控的基础置信度值。
# Agent 在 post_process_result 中以此为基础，
# 加上下方的 BONUS 和 PENALTY 进行微调。
# 纯 dict —— 测试或子类中可轻松覆盖。

CONFIDENCE_BASE: Dict[str, float] = {
    # ---- 风险驱动 ------------------------------------------
    "emergency": 0.95,  # 紧急症状 → 极高置信
    "high":      0.85,  # 高危症状 → 高置信
    "medium":    0.70,  # 中危 → 中等置信
    "low":       0.55,  # 低危 → 较低置信
    "unknown":   0.50,  # 未知 → 最低置信
    # ---- 证据驱动 ------------------------------------------
    "guideline_found":     0.88,  # 找到权威指南
    "guideline_not_found": 0.60,  # 未找到指南
    # ---- Skill 使用驱动 ------------------------------------
    "skill_used": 0.70,  # 至少调用了一个 Skill
    "no_skill":   0.55,  # 未调用 Skill（纯 LLM 回答）
    # ---- 降级 fallback（无 skill_results，仅正则提取）-------
    "fallback": 0.45,
}

# 找到权威指南时加的奖励分
CONFIDENCE_BONUS_GUIDELINE: float = 0.05

# evidence 为空但 confidence 偏高时扣除的惩罚分
CONFIDENCE_PENALTY_NO_EVIDENCE: float = 0.10

