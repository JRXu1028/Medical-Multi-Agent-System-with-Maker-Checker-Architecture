"""医学知识库模块入口。

这里使用延迟导入，避免仅导入 knowledge.evidence_service 时就加载 pymilvus
和 embedding 模型。这样单元测试可以用假知识库验证 RAG 证据规范化逻辑。
"""

__all__ = ["MedicalKnowledgeBase"]


def __getattr__(name):
    """按需暴露 MedicalKnowledgeBase，保持旧的导入方式兼容。"""
    if name == "MedicalKnowledgeBase":
        from .milvus_kb import MedicalKnowledgeBase

        return MedicalKnowledgeBase
    raise AttributeError(f"module 'knowledge' has no attribute {name!r}")
