"""Router 决策结果契约。

Router 只负责“监督等级选择”：判断用户问题走快速 simple 路径，
还是进入更严格的 maker_checker 路径。它不输出 risk_level、intent、
skills 或 tools，避免把 Maker 退化成固定工作流执行器。
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional


RouteMode = Literal["simple", "maker_checker"]
"""路由模式：simple 表示快速路径，maker_checker 表示进入审查链路。"""

RouteSource = Literal["rule", "semantic", "llm"]
"""决策来源：只表示“谁做出了路由决策”，不混入降级状态。"""


@dataclass(frozen=True)
class RouteDecision:
    """Router 的结构化决策。

    Parameters
    ----------
    mode:
        路由模式。
    reason:
        人类可读的决策原因，用于日志、终端展示和 trace。
    triggers:
        触发该决策的信号。规则层通常记录命中的标签和关键词；
        semantic/llm 层通常记录语义分数、LLM 模式或失败原因。
    source:
        决策来源，只能是 rule / semantic / llm。
    degraded:
        系统是否在降级状态下完成决策，例如语义层或 LLM fallback 不可用。
    degraded_reason:
        可选的降级原因。它和 source 解耦：source 仍表示谁做决策，
        degraded_reason 表示哪些能力不可用。
    """

    mode: RouteMode
    reason: str
    triggers: List[str] = field(default_factory=list)
    source: RouteSource = "rule"
    degraded: bool = False
    degraded_reason: Optional[str] = None

    @property
    def is_simple(self) -> bool:
        return self.mode == "simple"

    @property
    def is_maker_checker(self) -> bool:
        return self.mode == "maker_checker"
