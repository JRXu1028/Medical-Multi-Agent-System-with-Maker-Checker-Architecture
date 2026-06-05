#!/usr/bin/env python3
"""
Medical Multi-Agent System with Maker-Checker Architecture

双 Agent 对抗式临床决策系统:
  Generator 产出综合分析 → Reviewer 独立证伪 → SafetyGate 硬防线

用法:
    python main.py        # 默认
    python main.py -v     # 详细日志
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Dict
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from pipeline.entry import process_with_maker_checker


def setup_logger(verbose: bool = False):
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, format="<level>{level: <8}</level> | <level>{message}</level>", level=level)


async def main_loop():
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    setup_logger(verbose)

    print("\n" + "=" * 50)
    print("  Medical Multi-Agent System")
    print("  Maker-Checker Architecture")
    print("=" * 50)
    print("  exit 退出 | clear 清屏 | -v 详细日志\n" + "-" * 50 + "\n")

    import uuid
    from datetime import datetime
    sid = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8]}"

    while True:
        try:
            q = input("You: ").strip()
            if not q:
                continue
            if q.lower() in ("exit", "quit", "q"):
                print("再见!\n")
                break
            if q.lower() == "clear":
                print("\033[2J\033[H")
                continue

            t0 = time.time()
            r = await process_with_maker_checker(q, session_id=sid)
            t1 = time.time()

            route_icon = "🔍" if r.get("route") == "maker_checker" else "⚡"
            print(f"\n[{route_icon} {r.get('route', '?')}] "
                  f"[{r.get('terminal', '?')}] "
                  f"[{t1 - t0:.0f}s]\n")
            print_timing_report(r.get("timings", {}))
            print(r["answer"][:1500])
            print(f"\n{r.get('disclaimer', '')}")
            print("\n" + "-" * 50 + "\n")

        except KeyboardInterrupt:
            print("\n再见!\n")
            break
        except Exception as e:
            logger.error(f"错误: {e}")
            print(f"\n出错: {e}\n")


def print_timing_report(timings: Dict[str, Any]) -> None:
    """把 pipeline 返回的 timings 打印成人可读耗时树。

    这里不做业务判断，只负责展示。所有耗时单位统一为秒，方便直接定位慢点。
    """

    if not timings:
        return

    def sec(ms: Any) -> str:
        try:
            return f"{float(ms) / 1000:.2f}s"
        except (TypeError, ValueError):
            return "0.00s"

    print("耗时拆解:")
    print(f"  total:              {sec(timings.get('total_ms'))}")
    print(f"  router:             {sec(timings.get('router_ms'))}")
    print(f"  agent_init:         {sec(timings.get('agent_init_ms'))}")

    generator_loop = timings.get("generator_agent_loop") or {}
    if generator_loop:
        _print_agent_loop_timing("generator", generator_loop, indent="  ")
        print(f"  safety_gate:        {sec(timings.get('safety_gate_ms'))}")
        print(f"  response_renderer:  {sec(timings.get('response_renderer_ms'))}")
        print()
        return

    orchestrator = timings.get("orchestrator") or {}
    if orchestrator:
        print(f"  orchestrator:       {sec(timings.get('orchestrator_ms'))}")
        for round_timing in orchestrator.get("rounds", []) or []:
            round_id = round_timing.get("round", "?")
            print(f"    round {round_id}:")
            print(f"      generator:      {sec(round_timing.get('generator_ms'))}")
            _print_agent_loop_timing(
                "generator_loop",
                round_timing.get("generator_agent_loop") or {},
                indent="      ",
            )
            print(f"      checker:        {sec(round_timing.get('reviewer_ms'))}")
            _print_checker_timing(round_timing.get("reviewer") or {}, indent="      ")
        print(f"    safety_gate:      {sec(orchestrator.get('safety_gate_ms'))}")
        print(f"    renderer:         {sec(orchestrator.get('response_renderer_ms'))}")
    print()


def _print_agent_loop_timing(label: str, timing: Dict[str, Any], indent: str = "") -> None:
    """打印 AgentLoop 内部耗时。"""

    if not timing:
        return

    def sec(ms: Any) -> str:
        try:
            return f"{float(ms) / 1000:.2f}s"
        except (TypeError, ValueError):
            return "0.00s"

    print(f"{indent}{label}_loop_total: {sec(timing.get('agent_loop_total_ms'))}")
    print(f"{indent}  skill_select: {sec(timing.get('skill_selection_ms'))}")
    print(f"{indent}  llm_total:    {sec(timing.get('llm_total_ms'))}")
    print(f"{indent}  tools_total:  {sec(timing.get('tool_total_ms'))}")
    for tool in timing.get("tool_calls", []) or []:
        print(
            f"{indent}    tool {tool.get('name', '?')}: "
            f"{sec(tool.get('duration_ms'))}"
        )


def _print_checker_timing(timing: Dict[str, Any], indent: str = "") -> None:
    """打印 Checker 两阶段审查耗时。"""

    if not timing:
        return

    def sec(ms: Any) -> str:
        try:
            return f"{float(ms) / 1000:.2f}s"
        except (TypeError, ValueError):
            return "0.00s"

    print(f"{indent}  prestop:     {sec(timing.get('prestop_ms'))}")
    print(f"{indent}  llm_audit:   {sec(timing.get('llm_audit_ms'))}")
    _print_agent_loop_timing(
        "checker",
        timing.get("agent_loop") or {},
        indent=f"{indent}  ",
    )


if __name__ == "__main__":
    asyncio.run(main_loop())
