"""
Maker-Checker 架构入口 — 双路径执行。

simple:       Generator → SafetyGate → ResponseRenderer
maker_checker: Generator → Reviewer → (Round2) → SafetyGate → ResponseRenderer
"""

import time
from typing import Any, Dict, Optional
from loguru import logger

from .router import route_async
from .safety_gate import SafetyGate, apply_gate_override
from .orchestrator import MakerCheckerOrchestrator
from .response_renderer import ResponseRenderer
from agents.generator import GeneratorAgent
from agents.reviewer import ReviewerAgent


async def process_with_maker_checker(
    question: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """使用 Maker-Checker 架构处理问题。"""
    import uuid
    from datetime import datetime
    total_start = time.perf_counter()
    timings: Dict[str, Any] = {
        "total_ms": 0.0,
        "router_ms": 0.0,
        "agent_init_ms": 0.0,
        "generator_ms": 0.0,
        "safety_gate_ms": 0.0,
        "response_renderer_ms": 0.0,
        "orchestrator": {},
    }

    if session_id is None:
        session_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    t_router = time.perf_counter()
    decision = await route_async(question)
    timings["router_ms"] = _elapsed_ms(t_router)
    logger.info(
        f"Route → {decision.mode} | {decision.reason} "
        f"| source={decision.source} degraded={decision.degraded} "
        f"| triggers={decision.triggers} | {question[:40]}"
    )

    t_init = time.perf_counter()
    gen  = GeneratorAgent()
    gate = SafetyGate()
    renderer = ResponseRenderer()
    timings["agent_init_ms"] = _elapsed_ms(t_init)

    if decision.is_simple:
        t_generator = time.perf_counter()
        gen_result = await gen.generate(question)
        timings["generator_ms"] = _elapsed_ms(t_generator)
        t_gate = time.perf_counter()
        gr = gate.check(question, gen_result)
        timings["safety_gate_ms"] = _elapsed_ms(t_gate)
        terminal = "simple"
        if not gr.passed:
            gen_result = apply_gate_override(gen_result)
            terminal = "gate_override"
        t_render = time.perf_counter()
        answer = renderer.render(
            user_query=question,
            maker_answer=gen_result.get("answer", ""),
            maker_output=gen_result,
            terminal=terminal,
            gate_result=gr,
        )
        timings["response_renderer_ms"] = _elapsed_ms(t_render)
        timings["generator_agent_loop"] = (
            gen_result.get("process_trace", {}) or {}
        ).get("timings", {})
        timings["total_ms"] = _elapsed_ms(total_start)
        return {
            "answer": answer, "session_id": session_id,
            "maker_checker": True, "route": decision.mode, "route_reason": decision.reason,
            "terminal": terminal,
            "rounds": 0, "agents_involved": ["generator"],
            "gate_result": {"passed": gr.passed, "gate": gr.gate},
            "disclaimer": "以上分析基于 Maker-Checker 架构（简单路径），仅供参考，不能替代医生诊断。",
            "suggestions": [],
            "timings": timings,
        }

    t_init_reviewer = time.perf_counter()
    rev  = ReviewerAgent()
    timings["agent_init_ms"] += _elapsed_ms(t_init_reviewer)
    orch = MakerCheckerOrchestrator(
        gen,
        rev,
        gate,
        response_renderer=renderer,
        max_retries=1,
    )
    t_orch = time.perf_counter()
    result = await orch.run(question)
    timings["orchestrator_ms"] = _elapsed_ms(t_orch)
    timings["orchestrator"] = result.get("timings", {})
    timings["total_ms"] = _elapsed_ms(total_start)
    return {
        "answer": result["final_answer"], "session_id": session_id,
        "maker_checker": True, "route": decision.mode, "route_reason": decision.reason,
        "terminal": result["terminal"], "rounds": len(result["rounds"]),
        "agents_involved": ["generator", "reviewer"],
        "gate_result": result.get("gate_result"),
        "disclaimer": "以上分析基于 Maker-Checker 双 Agent 对抗架构，仅供参考，不能替代医生诊断。",
        "suggestions": [],
        "timings": timings,
    }


def _elapsed_ms(start: float) -> float:
    """返回从 start 到当前的毫秒耗时，统一保留 2 位小数。"""
    return round((time.perf_counter() - start) * 1000, 2)
