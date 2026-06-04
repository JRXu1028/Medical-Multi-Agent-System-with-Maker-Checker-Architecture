"""Router fixture-based regression tests."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.router import _semantic_risk_score, route
from pipeline.router import route_async


FIXTURE = Path(__file__).parent / "fixtures" / "router_eval_cases.jsonl"


def _load_cases():
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["question"])
def test_router_eval_cases(case):
    """固定误报/漏报边界样例，避免 Router 退化成裸关键词匹配。"""

    decision = route(case["question"])
    assert decision.mode == case["expected"], (
        f"{case['reason']} | got={decision.mode} "
        f"source={decision.source} reason={decision.reason}"
    )


def test_semantic_layer_available_or_degraded():
    """语义层可不可用都必须显式表现，不能静默失败。"""

    score = _semantic_risk_score("测试")
    if score is None:
        decision = route("多喝水有什么好处")
        assert decision.degraded
        assert decision.source == "rule_degraded"
    else:
        assert isinstance(score, float)


@pytest.mark.asyncio
async def test_route_async_inside_running_event_loop():
    """异步主流程里调用 Router 不应触发嵌套 asyncio.run()。"""

    decision = await route_async("成人一天喝多少水")
    assert decision.is_simple
    assert decision.source == "rule"
