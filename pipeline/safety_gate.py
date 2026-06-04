"""
确定性安全门控 —— Maker-Checker 管道的最后硬防线。

=============================================================================
作用
=============================================================================
SafetyGate 是纯 Python 代码。它永不调用 LLM，永不读取 prompt，
也永不依赖"是哪个 Agent 产出了这个 action_signal"。

它运行在 Reviewer 之后（或简单路径中 Generator 之后）。
它可以 GATE-OVERRIDE（硬覆盖 proposed_action）—— 但不能 REJECT 回 Generator。

三个独立的检查门，按优先级顺序执行，首次 BLOCK 即停止：

1. 高危症状扫描        — query 含高危症状但 action 不是 urgent_care → BLOCK
2. 证据充分性阈值      — confidence 高但 evidence 为空 → BLOCK
3. 格式合规检查        — action_signal 缺少 proposed_action → BLOCK

=============================================================================
数据流向
=============================================================================

Orchestrator
    │  调用 safety_gate.check(user_query, action_signal)
    │  传入: 用户原始 query + Generator（或修正后）的 action_signal
    ▼
SafetyGate.check()
    │  依次执行三个门检查
    │  ┌─ _check_high_risk_symptom    — 扫描 query 中的高危症状
    │  ├─ _check_evidence_sufficiency — 检查 confidence vs evidence
    │  └─ _check_format_compliance    — 检查字段完整性
    │
    ▼
GateResult
    │  .passed = True  → Orchestrator 放行到 LeadAgent
    │  .passed = False → Orchestrator 调用 apply_gate_override()
    │                    硬覆盖 proposed_action 为 urgent_care
    ▼
LeadAgent.express()
    │  读取被覆盖后的 action_signal
    │  用克制语言说明无法可靠排除风险，建议及时就医
    ▼
Final Answer

=============================================================================
关联模块
=============================================================================
· pipeline.action_signal  — 导入 ActionType（用于比较 proposed_action）
· pipeline.orchestrator — 调用 check() 和 apply_gate_override()
· agents.lead      — 读取被 Gate 覆盖的 action_signal

=============================================================================
设计原则
=============================================================================
· 每个门是独立方法 —— 可单独单元测试
· 高危症状表可配置 —— 构造函数注入或子类覆盖
· 中英文双语匹配 —— 覆盖双语医疗查询
· 永不依赖 LLM —— 所有逻辑是确定性的 if/else

@new  Maker-Checker 架构 (2026-06)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, FrozenSet, Optional

from .action_signal import ActionType  # 用于比较 proposed_action


# ============================================================================
# GateResult — 单次门检查的结果
# ============================================================================

@dataclass
class GateResult:
    """单次 SafetyGate 检查的结果。

    Parameters
    ----------
    passed : bool
        是否通过检查。True = 放行，False = BLOCK（硬覆盖）。
    reason : str
        未通过时的具体原因描述，用于日志和调试。
        通过时为空字符串。
    gate : str
        触发 BLOCK 的门标识（如 "high_risk_symptom_check"）。
        通过时为空字符串。
    """

    passed: bool                     # True = PASS, False = BLOCK
    reason: str = ""                 # 未通过原因（日志/调试用）
    gate:   str = ""                 # 触发 BLOCK 的门标识

    @classmethod
    def ok(cls) -> "GateResult":
        """快速构造一个 PASS 结果。"""
        return cls(passed=True)


# ============================================================================
# SafetyGate — 确定性安全检查器
# ============================================================================

class SafetyGate:
    """确定性安全门控。不调 LLM，不读 prompt，不做外部 I/O。

    运行在 Reviewer 之后（或简单路径中 Generator 之后）。
    硬覆盖 proposed_action —— 不将控制权交还给 Generator。

    论文依据
    --------
    · CareGuardAI (arXiv 2604.26959, 2026) — 双轴安全评估 SRA + 幻觉
    · OncoAgent   (May 2026)               — 确定性代码 Critic 节点

    Parameters
    ----------
    high_risk_symptoms : frozenset of str, optional
        高危症状列表。默认使用 DEFAULT_HIGH_RISK_SYMPTOMS。
        可通过此参数注入自定义列表（测试或扩展用途）。
    """

    # =========================================================================
    # 门标识常量 —— 调用方和日志使用
    # =========================================================================

    GATE_HIGH_RISK_SYMPTOM:    ClassVar[str] = "high_risk_symptom_check"     # 高危症状扫描门
    GATE_EVIDENCE_SUFFICIENCY: ClassVar[str] = "evidence_sufficiency_check"  # 证据充分性门
    GATE_FORMAT_COMPLIANCE:    ClassVar[str] = "format_compliance_check"     # 格式合规门

    # =========================================================================
    # 默认高危症状表 —— 可通过构造函数覆盖
    # =========================================================================

    DEFAULT_HIGH_RISK_SYMPTOMS: ClassVar[FrozenSet[str]] = frozenset({
        # 中文高危症状
        "胸痛", "呼吸困难", "意识模糊", "剧烈头痛",
        "严重出血", "持续呕吐", "高热不退", "突然晕厥",
        "面部下垂", "言语不清", "单侧肢体无力",
        "咳血", "黑便", "呕血", "视力突然丧失",
    })

    # =========================================================================
    # 实例化
    # =========================================================================

    def __init__(
        self,
        high_risk_symptoms: Optional[FrozenSet[str]] = None  # 自定义高危症状表（None=使用默认）
    ) -> None:
        # 存储原始症状表
        self._high_risk_symptoms: FrozenSet[str] = (
            high_risk_symptoms
            if high_risk_symptoms is not None
            else self.DEFAULT_HIGH_RISK_SYMPTOMS
        )
        # 小写版本 —— 用于英文/大小写不敏感匹配
        self._high_risk_symptoms_lower: FrozenSet[str] = frozenset(
            s.lower() for s in self._high_risk_symptoms
        )

    # =========================================================================
    # 公共入口
    # =========================================================================

    def check(
        self,
        user_query: str,              # 用户原始查询文本
        action_signal: Dict[str, Any] # Generator 或修正后的 action_signal dict
    ) -> GateResult:
        """按优先级顺序执行所有门检查，返回第一个 BLOCK 或最终 PASS。

        三个门的优先级：
        1. 高危症状扫描（安全最高优先级）
        2. 证据充分性（质量保证）
        3. 格式合规（完整性检查）
        """

        # 门 1: 高危症状扫描 —— 安全最高优先级
        result = self._check_high_risk_symptom(user_query, action_signal)
        if not result.passed:
            return result

        # 门 2: 证据充分性 —— 高置信必须有证据支撑
        result = self._check_evidence_sufficiency(action_signal)
        if not result.passed:
            return result

        # 门 3: 格式合规 —— 缺少必需字段
        return self._check_format_compliance(action_signal)

    # =========================================================================
    # 门 1: 高危症状硬编码扫描
    # =========================================================================

    def _check_high_risk_symptom(
        self,
        user_query: str,              # 用户原始查询文本（中英文均可）
        action_signal: Dict[str, Any] # 当前 action_signal dict
    ) -> GateResult:
        """扫描 query 是否包含高危症状。

        BLOCK 条件: query 匹配到高危症状 且 proposed_action 不是
        recommend_urgent_care。

        支持中文原文和小写英文双重匹配。
        """

        query_lower = user_query.lower()  # 用于英文/大小写不敏感匹配

        for symptom in self._high_risk_symptoms:
            # 中文原文匹配 或 英文小写匹配
            hit = (
                symptom in user_query
                or symptom.lower() in query_lower
            )
            if not hit:
                continue

            proposed = action_signal.get("proposed_action", "")
            if proposed != ActionType.RECOMMEND_URGENT_CARE:
                return GateResult(
                    passed=False,
                    gate=self.GATE_HIGH_RISK_SYMPTOM,
                    reason=(
                        f"查询含高危症状 '{symptom}'，"
                        f"但 proposed_action = '{proposed}'，"
                        f"期望 '{ActionType.RECOMMEND_URGENT_CARE}'。"
                    ),
                )

        return GateResult.ok()

    # =========================================================================
    # 门 2: 证据充分性阈值
    # =========================================================================

    def _check_evidence_sufficiency(
        self,
        action_signal: Dict[str, Any]  # 当前 action_signal dict
    ) -> GateResult:
        """检查高置信度结论是否有对应证据支撑。

        BLOCK 条件: confidence > 0.7 且 evidence 列表为空。
        高置信度必须有至少一条证据，否则置信度是空心的。
        """

        evidence   = action_signal.get("evidence", [])    # 证据列表
        confidence = action_signal.get("confidence", 0)   # 当前置信度

        # 有证据 → 放行；低置信 → 放行（低置信度本身说明不确定性）
        if evidence or confidence <= 0.7:
            return GateResult.ok()

        return GateResult(
            passed=False,
            gate=self.GATE_EVIDENCE_SUFFICIENCY,
            reason=(
                f"confidence = {confidence}（> 0.7），"
                f"但 evidence 列表为空。"
                f"高置信度必须有支持性证据。"
            ),
        )

    # =========================================================================
    # 门 3: 格式合规检查
    # =========================================================================

    def _check_format_compliance(
        self,
        action_signal: Dict[str, Any]  # 当前 action_signal dict
    ) -> GateResult:
        """检查 action_signal 是否包含必需的 proposed_action 字段。

        BLOCK 条件: proposed_action 缺失或为空字符串。
        没有 action 的信号是无法执行的。
        """

        proposed = action_signal.get("proposed_action")  # 待检查字段

        if not proposed:
            return GateResult(
                passed=False,
                gate=self.GATE_FORMAT_COMPLIANCE,
                reason="action_signal 缺少 'proposed_action' 字段。",
            )

        return GateResult.ok()


# ============================================================================
# apply_gate_override — Gate 硬覆盖辅助函数
# ============================================================================

def apply_gate_override(action_signal: Dict[str, Any]) -> Dict[str, Any]:
    """将 action_signal 强制覆盖为安全兜底值。

    当 SafetyGate 返回 BLOCK 时由 Orchestrator 调用。
    不是驳回重做 —— 是直接硬覆盖结论。

    Parameters
    ----------
    action_signal : dict
        当前的 action_signal dict（将被浅拷贝后覆盖）。

    Returns
    -------
    dict
        覆盖后的 action_signal:
        · proposed_action 强制为 recommend_urgent_care
        · confidence 标记为 "overridden"（LeadAgent 据此标注）

    注意
    ----
    confidence 被设为字符串 "overridden" 而非浮点数。
    这有意为之 —— LeadAgent 检查此标记来决定是否采用安全保护表达。
    """

    overridden = dict(action_signal)                              # 浅拷贝，不动原始 dict
    overridden["proposed_action"] = ActionType.RECOMMEND_URGENT_CARE  # 强制覆盖
    overridden["confidence"]      = "overridden"                      # 标记覆盖来源
    return overridden

