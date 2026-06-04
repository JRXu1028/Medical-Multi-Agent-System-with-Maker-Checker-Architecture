"""检查生成的语义阈值评估集是否保持稳定。"""

import json
from collections import Counter
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "router_threshold_eval_1000.jsonl"


def test_router_threshold_fixture_shape():
    rows = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labels = Counter(row["expected"] for row in rows)
    queries = [row["query"] for row in rows]

    assert len(rows) == 1000
    assert labels == {"simple": 500, "maker_checker": 500}
    assert len(set(queries)) == len(queries)
    assert all(row.get("category") for row in rows)
