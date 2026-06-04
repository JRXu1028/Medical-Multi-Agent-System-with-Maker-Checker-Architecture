"""v3.5 评估基础设施包。

本包提供轻量但可运行的 EvalCase、JSONL fixture 加载和报告入口。
它的目标不是第一天做复杂医学人工标注，而是把 tool-call、RAG、Checker seeded case
放到统一数据契约里，方便后续逐步扩展指标。
"""

from .cases import EvalCase, load_jsonl, write_jsonl

__all__ = ["EvalCase", "load_jsonl", "write_jsonl"]
