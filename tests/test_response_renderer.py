"""
ResponseRenderer 单元测试。

验证最终输出层不调用 LLM，只根据管道终态做确定性渲染：
正常路径保留 Maker 答案，安全路径使用固定模板覆盖。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.action_signal import ActionType
from pipeline.response_renderer import ResponseRenderer
from pipeline.terminal import Terminal


def _signal(**overrides):
    """构造测试用 action_signal。"""

    base = {
        "result": "结构化结论",
        "evidence": ["胸痛", "呼吸困难"],
        "confidence": 0.8,
        "proposed_action": ActionType.OBSERVE,
    }
    base.update(overrides)
    return base


def test_normal_returns_maker_answer_without_rewrite():
    renderer = ResponseRenderer()

    answer = renderer.render(
        user_query="普通问题",
        maker_answer="Maker 的完整回答",
        action_signal=_signal(),
        terminal=Terminal.NORMAL,
    )

    assert answer == "Maker 的完整回答"


def test_challenged_appends_fixed_uncertainty_note():
    renderer = ResponseRenderer()

    answer = renderer.render(
        user_query="复杂问题",
        maker_answer="Maker 的完整回答",
        action_signal=_signal(),
        terminal=Terminal.CHALLENGED,
        challenges=[{"description": "证据仍不充分"}],
    )

    assert answer.startswith("Maker 的完整回答")
    assert "Checker 对这个回答仍保留一定不确定性" in answer
    assert "证据仍不充分" in answer


def test_gate_override_hides_maker_answer():
    renderer = ResponseRenderer()

    answer = renderer.render(
        user_query="我胸痛呼吸困难",
        maker_answer="Maker 原本建议先观察",
        action_signal=_signal(confidence="overridden"),
        terminal=Terminal.GATE_OVERRIDE,
    )

    assert "无法可靠排除较高风险" in answer
    assert "Maker 原本建议先观察" not in answer


def test_forced_safe_uses_safe_fallback_template():
    renderer = ResponseRenderer()

    answer = renderer.render(
        user_query="复杂高风险问题",
        maker_answer="",
        action_signal=_signal(
            result="目前无法可靠排除风险，基于安全原则建议立即就医。",
            confidence="forced_safe_mode",
            proposed_action=ActionType.RECOMMEND_URGENT_CARE,
        ),
        terminal=Terminal.FORCED_SAFE,
    )

    assert "无法可靠排除风险" in answer
    assert "不要仅依据线上回答自行处理" in answer
