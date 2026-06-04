"""在生成的 1000 条评估集上扫描 Semantic Router 阈值。

该脚本只评估 Semantic Recall 层，不调用 LLM Router，
也不执行完整的 route() 管道。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "router_threshold_eval_1000.jsonl"
DEFAULT_THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.22, 0.24, 0.25, 0.30)

sys.path.insert(0, str(ROOT))

from pipeline import router  # noqa: E402


def _load_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _semantic_scores(queries: list[str]) -> list[float]:
    router._lazy_init_embeddings()
    query_embeddings = router._encoder.encode(queries, normalize_embeddings=True)
    high_scores = query_embeddings @ router._high_embeddings.T
    low_scores = query_embeddings @ router._low_embeddings.T
    scores = np.max(high_scores, axis=1) - np.max(low_scores, axis=1)
    return [round(float(score), 3) for score in scores]


def _metrics(rows: list[dict], threshold: float) -> dict:
    tp = sum(
        row["expected"] == "maker_checker" and row["semantic_score"] >= threshold
        for row in rows
    )
    fp = sum(
        row["expected"] == "simple" and row["semantic_score"] >= threshold
        for row in rows
    )
    fn = sum(
        row["expected"] == "maker_checker" and row["semantic_score"] < threshold
        for row in rows
    )
    tn = sum(
        row["expected"] == "simple" and row["semantic_score"] < threshold
        for row in rows
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "false_positive_rate": fpr,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument(
        "--thresholds",
        nargs="*",
        type=float,
        default=list(DEFAULT_THRESHOLDS),
    )
    args = parser.parse_args()

    rows = _load_rows(args.fixture)
    scores = _semantic_scores([row["query"] for row in rows])
    for row, score in zip(rows, scores):
        row["semantic_score"] = score

    simple_scores = [row["semantic_score"] for row in rows if row["expected"] == "simple"]
    maker_scores = [
        row["semantic_score"] for row in rows if row["expected"] == "maker_checker"
    ]

    print(f"fixture={args.fixture.relative_to(ROOT)}")
    print(
        f"n={len(rows)} simple={len(simple_scores)} maker_checker={len(maker_scores)}"
    )
    print(
        "score_summary "
        f"simple_max={max(simple_scores):.3f} "
        f"simple_p95={np.percentile(simple_scores, 95):.3f} "
        f"maker_p50={np.percentile(maker_scores, 50):.3f} "
        f"maker_p75={np.percentile(maker_scores, 75):.3f}"
    )
    print("threshold  tp   fp   fn   tn   precision  recall  fpr")
    for threshold in args.thresholds:
        metrics = _metrics(rows, threshold)
        print(
            f"{threshold:>8.2f}  "
            f"{metrics['tp']:>3}  {metrics['fp']:>3}  "
            f"{metrics['fn']:>3}  {metrics['tn']:>3}  "
            f"{metrics['precision']:.3f}      "
            f"{metrics['recall']:.3f}   "
            f"{metrics['false_positive_rate']:.3f}"
        )


if __name__ == "__main__":
    main()
