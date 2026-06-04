"""
Maker-Checker 架构入口 — 双路径执行。

simple:       Generator → SafetyGate → LeadAgent
maker_checker: Generator → Reviewer → (Round2) → SafetyGate → LeadAgent
"""

from typing import Any, Dict, Optional
from loguru import logger

from .router import route_async
from .safety_gate import SafetyGate, apply_gate_override
from .orchestrator import MakerCheckerOrchestrator
from agents.generator import GeneratorAgent
from agents.reviewer import ReviewerAgent
from agents.lead import LeadAgent


async def process_with_maker_checker(
    question: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """使用 Maker-Checker 架构处理问题。"""
    import uuid
    from datetime import datetime

    if session_id is None:
        session_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    decision = await route_async(question)
    logger.info(
        f"Route → {decision.mode} | {decision.reason} "
        f"| source={decision.source} degraded={decision.degraded} "
        f"| triggers={decision.triggers} | {question[:40]}"
    )

    gen  = GeneratorAgent()
    gate = SafetyGate()
    lead = LeadAgent()

    if decision.is_simple:
        gen_result = await gen.generate(question)
        signal = gen_result["action_signal"]
        gr = gate.check(question, signal)
        if not gr.passed:
            signal = apply_gate_override(signal)
        answer = await lead.express(question, signal, terminal="simple")
        return {
            "answer": answer, "session_id": session_id,
            "maker_checker": True, "route": decision.mode, "route_reason": decision.reason,
            "terminal": "gate_override" if not gr.passed else "simple",
            "rounds": 0, "agents_involved": ["generator"],
            "gate_result": {"passed": gr.passed, "gate": gr.gate},
            "disclaimer": "以上分析基于 Maker-Checker 架构（简单路径），仅供参考，不能替代医生诊断。",
            "suggestions": [],
        }

    rev  = ReviewerAgent()
    orch = MakerCheckerOrchestrator(gen, rev, gate, lead, max_retries=1)
    result = await orch.run(question)
    return {
        "answer": result["final_answer"], "session_id": session_id,
        "maker_checker": True, "route": decision.mode, "route_reason": decision.reason,
        "terminal": result["terminal"], "rounds": len(result["rounds"]),
        "agents_involved": ["generator", "reviewer"],
        "gate_result": result.get("gate_result"),
        "disclaimer": "以上分析基于 Maker-Checker 双 Agent 对抗架构，仅供参考，不能替代医生诊断。",
        "suggestions": [],
    }
