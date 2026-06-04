"""v3.5 轻量评估报告入口。

第一版报告不调用 LLM，也不连接 Milvus；它只读取统一 EvalCase fixtures，
输出样本数量、标签分布和期望工具/证据/Checker issue 分布。
后续接真实 runner 时，可以在这个稳定 schema 上继续扩展指标。
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from evals.cases import EvalCase, load_jsonl


def build_report(cases: Iterable[EvalCase]) -> Dict[str, Any]:
    """构建不依赖外部服务的 eval fixture 摘要报告。"""

    case_list = list(cases)
    tags = Counter(tag for case in case_list for tag in case.tags)
    tools = Counter(tool for case in case_list for tool in case.expected_tools)
    evidence_types = Counter(
        item for case in case_list for item in case.expected_evidence_types
    )
    checker_issues = Counter(
        item for case in case_list for item in case.expected_checker_issues
    )
    routes = Counter(
        case.expected_route for case in case_list if case.expected_route
    )

    return {
        "total_cases": len(case_list),
        "tags": dict(tags),
        "expected_routes": dict(routes),
        "expected_tools": dict(tools),
        "expected_evidence_types": dict(evidence_types),
        "expected_checker_issues": dict(checker_issues),
    }


def load_cases_from_paths(paths: Iterable[str | Path]) -> List[EvalCase]:
    """从多个 JSONL 路径加载并合并 EvalCase。"""

    cases: List[EvalCase] = []
    for path in paths:
        cases.extend(load_jsonl(path))
    return cases


def main() -> None:
    """命令行入口：读取 JSONL fixtures 并打印 JSON 报告。"""

    parser = argparse.ArgumentParser(description="Run lightweight v3.5 eval report.")
    parser.add_argument("paths", nargs="+", help="EvalCase JSONL fixture paths.")
    args = parser.parse_args()

    report = build_report(load_cases_from_paths(args.paths))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
