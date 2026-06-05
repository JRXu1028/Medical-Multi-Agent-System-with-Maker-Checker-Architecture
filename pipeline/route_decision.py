"""Router 决策结果 dataclass。

Router 只负责"监督层级选择"——决定是否需要更严格的审查。
不输出 risk_level（Generator 的职责，通过 assess_risk Skill 完成）。
不输出 confidence（Phase 1 纯规则，无不确定性）。
"""

from dataclasses import dataclass, field
from typing import List, Literal

RouteMode   = Literal["simple", "maker_checker"]          # 路由模式
RouteSource = Literal["rule", "semantic", "llm", "rule_degraded"]  # 决策来源


@dataclass(frozen=True)
class RouteDecision:
    """Router 的结构化决策。

    Parameters
    ----------
    mode : RouteMode
        "simple"       — Generator → SafetyGate → ResponseRenderer
        "maker_checker" — Generator → Reviewer → SafetyGate → ResponseRenderer
    reason : str
        人类可读的决策原因，用于日志和终端展示。
    triggers : list of str
        触发了哪些规则，用于调试和可解释性。
    source : RouteSource
        "rule" — 确定性规则匹配。
        "semantic" — 语义层召回。
        "rule_degraded" — 语义层不可用，仅规则层决策。
    degraded : bool
        True 表示系统以降级模式运行（语义层不可用）。
    """

    mode: RouteMode
    reason: str
    triggers: List[str] = field(default_factory=list)
    source: RouteSource = "rule"
    degraded: bool = False

    @property
    def is_simple(self) -> bool:
        return self.mode == "simple"

    @property
    def is_maker_checker(self) -> bool:
        return self.mode == "maker_checker"
