"""
LeadAgent — Maker-Checker 管道的最终表达层。

只负责将已裁决的 action_signal 渲染为面向患者的自然语言。
不仲裁、不修改风险等级、不修改就医建议。
"""

from typing import Any, Dict, List, Optional
from loguru import logger
from core.llm_client import LLMClient


class LeadAgent:
    """最终表达 Agent —— 将已裁决结果转为自然语言。

    关键约束：LLM 只表达，不仲裁。
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient(profile="lead")

    async def express(
        self,
        user_query: str,                # 用户原始问题
        action_signal: Dict[str, Any],  # 裁决后的最终 action_signal
        terminal: str = "",             # 终态类型
        rounds: Optional[List[Dict]] = None  # 轮次记录
    ) -> str:
        """将 action_signal 表达为面向患者的自然语言。"""
        is_overridden = action_signal.get("confidence") in (
            "overridden", "forced_safe_mode"
        )
        is_uncertain = action_signal.get("uncertainty", False)

        lines = [
            "你是最终答案的表达者。用通俗语言表达以下已裁决的结论。",
            f"用户问题: {user_query}",
            f"最终结论: {action_signal.get('result', '')}",
            f"建议行动: {action_signal.get('proposed_action', '')}",
            f"证据: {action_signal.get('evidence', [])}",
            "## 表达要求",
        ]
        if is_overridden:
            lines.append(
                "此结论来自安全保护路径。请只用简洁、克制的方式说明："
                "目前无法可靠排除风险，基于安全原则建议立即就医。"
                "不要描述系统内部流程或实现细节。"
            )
        if is_uncertain:
            lines.append("此结论存在不确定性。在回答中明确说明不确定性，建议线下就医确认。")
        lines += [
            "## 绝对禁止: 改变风险等级、改变就医建议、重新评判对错、添加未裁决的新建议",
            "## 必须包含: 医学免责声明",
        ]
        try:
            return await self.llm_client.chat([{"role": "user", "content": "\n".join(lines)}])
        except Exception as e:
            logger.error(f"LeadAgent express failed: {e}")
            return action_signal.get("result", "抱歉，无法生成回答。如有疑虑，请及时就医。")
