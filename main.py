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
            print(r["answer"][:1500])
            print(f"\n{r.get('disclaimer', '')}")
            print("\n" + "-" * 50 + "\n")

        except KeyboardInterrupt:
            print("\n再见!\n")
            break
        except Exception as e:
            logger.error(f"错误: {e}")
            print(f"\n出错: {e}\n")


if __name__ == "__main__":
    asyncio.run(main_loop())
