"""v3.5 EvalCase 与轻量报告测试。

测试目标：
- EvalCase 可以稳定 JSONL roundtrip
- 三类 fixture 可以用同一 schema 加载
- run_evals 能生成不依赖外部服务的摘要报告
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.cases import EvalCase, load_jsonl, write_jsonl
from evals.run_evals import build_report, load_cases_from_paths


def test_eval_case_roundtrip():
    case = EvalCase(
        id="case_001",
        query="布洛芬和华法林能一起吃吗？",
        tags=["tool_call", "medication_safety"],
        expected_route="maker_checker",
        expected_tools=["drug_safety_lookup"],
        expected_evidence_types=["drug_safety"],
        expected_checker_issues=["TOOL_GAP"],
    )
    temp_dir = Path(__file__).parent.parent / "_tmp_test_eval_cases"
    path = temp_dir / f"cases-{uuid.uuid4().hex}.jsonl"

    write_jsonl(path, [case])
    loaded = load_jsonl(path)

    assert loaded == [case]


def test_real_eval_fixtures_share_schema():
    root = Path(__file__).parent.parent / "evals"
    cases = load_cases_from_paths(
        [
            root / "tool_call_cases.jsonl",
            root / "rag_cases.jsonl",
            root / "checker_seeded_cases.jsonl",
        ]
    )

    assert len(cases) >= 8
    assert all(case.id and case.query for case in cases)
    assert {"assess_risk", "drug_safety_lookup", "lab_reference_lookup"} <= {
        tool for case in cases for tool in case.expected_tools
    }


def test_build_report_summarizes_expected_labels():
    cases = [
        EvalCase(
            id="a",
            query="胸痛怎么办？",
            tags=["tool_call"],
            expected_route="maker_checker",
            expected_tools=["assess_risk"],
        ),
        EvalCase(
            id="b",
            query="尿酸 520？",
            tags=["checker"],
            expected_route="maker_checker",
            expected_tools=["lab_reference_lookup"],
            expected_checker_issues=["EVIDENCE_GAP"],
        ),
    ]

    report = build_report(cases)

    assert report["total_cases"] == 2
    assert report["expected_routes"]["maker_checker"] == 2
    assert report["expected_tools"]["assess_risk"] == 1
    assert report["expected_checker_issues"]["EVIDENCE_GAP"] == 1
