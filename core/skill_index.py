"""Progressive SKILL.md 加载器。

本模块负责 v3.2 的“方法论 Skill 文档”加载：
- 扫描 skills/*/SKILL.md
- 解析 YAML frontmatter 和 Markdown body
- 渲染给 Maker 首轮选择用的 Skill Index
- 渲染已加载 SKILL.md 的上下文文本

注意：这里不执行任何工具函数，也不处理 `.claude/skills` legacy function tools。
SKILL.md 是给 LLM 看的领域方法论；可执行工具仍由 SkillRegistry / tools 层负责。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml
from loguru import logger


SKILL_MD_NAME = "SKILL.md"


@dataclass(frozen=True)
class SkillDoc:
    """一个可渐进加载的 SKILL.md 文档。"""

    id: str
    description: str
    when_to_load: List[str] = field(default_factory=list)
    suggested_tools: List[str] = field(default_factory=list)
    body: str = ""
    path: str = ""

    def to_index_item(self) -> Dict[str, Any]:
        """返回 Skill Index 中的紧凑描述，不包含完整 Markdown body。"""
        return {
            "id": self.id,
            "description": self.description,
            "when_to_load": self.when_to_load,
            "suggested_tools": self.suggested_tools,
        }

    def render_for_context(self) -> str:
        """渲染完整 Skill 文档，注入 AgentLoop 后续上下文。"""
        sections = [
            f"## Skill: {self.id}",
            f"Description: {self.description}",
        ]
        if self.when_to_load:
            sections.append("When to load:")
            sections.extend(f"- {item}" for item in self.when_to_load)
        if self.suggested_tools:
            sections.append("Suggested tools:")
            sections.extend(f"- {tool}" for tool in self.suggested_tools)
        if self.body.strip():
            sections.append(self.body.strip())
        return "\n".join(sections)


class SkillDocLoader:
    """SKILL.md 文档加载器。

    只负责文档层 progressive disclosure，不承担工具注册、工具执行或安全硬约束。
    """

    def __init__(self, skills_dir: Path | str = "skills") -> None:
        self.skills_dir = Path(skills_dir)
        self._cache: Optional[Dict[str, SkillDoc]] = None

    def discover(self, *, refresh: bool = False) -> Dict[str, SkillDoc]:
        """扫描 skills_dir 并返回 {skill_id: SkillDoc}。"""
        if self._cache is not None and not refresh:
            return self._cache

        docs: Dict[str, SkillDoc] = {}
        if not self.skills_dir.exists():
            logger.debug("Skill docs dir does not exist: {}", self.skills_dir)
            self._cache = docs
            return docs

        for skill_md in sorted(self.skills_dir.glob(f"*/{SKILL_MD_NAME}")):
            doc = parse_skill_doc(skill_md)
            if doc is None:
                continue
            if doc.id in docs:
                logger.warning("Duplicate SkillDoc id ignored: {}", doc.id)
                continue
            docs[doc.id] = doc

        self._cache = docs
        return docs

    def get(self, skill_id: str) -> Optional[SkillDoc]:
        """按 id 获取 SkillDoc。"""
        return self.discover().get(skill_id)

    def render_index(self) -> str:
        """渲染紧凑 Skill Index，供 Maker 首轮选择需要加载的 Skills。"""
        docs = self.discover()
        items = [doc.to_index_item() for doc in docs.values()]
        return json.dumps(items, ensure_ascii=False, indent=2)

    def render_skill_context(self, skill_ids: Sequence[str]) -> Tuple[str, List[str]]:
        """渲染多个 SkillDoc 的完整上下文，并返回实际成功加载的 ids。"""
        loaded_docs: List[SkillDoc] = []
        loaded_ids: List[str] = []

        for skill_id in dedupe_preserve_order(skill_ids):
            doc = self.get(skill_id)
            if doc is None:
                logger.warning("Requested SkillDoc not found: {}", skill_id)
                continue
            loaded_docs.append(doc)
            loaded_ids.append(doc.id)

        if not loaded_docs:
            return "", []

        context = [
            "以下是本轮 Maker 已加载的 SKILL.md 方法论。",
            "这些内容用于指导推理和工具选择，不是可执行工具，也不是安全硬约束来源。",
        ]
        context.extend(doc.render_for_context() for doc in loaded_docs)
        return "\n\n".join(context), loaded_ids


def parse_skill_doc(path: Path | str) -> Optional[SkillDoc]:
    """解析单个 SKILL.md。

    SKILL.md 必须包含 YAML frontmatter，且 frontmatter 至少包含：
    - id
    - description
    """
    skill_path = Path(path)
    if not skill_path.exists():
        logger.warning("SkillDoc file not found: {}", skill_path)
        return None

    content = skill_path.read_text(encoding="utf-8")
    metadata, body = split_frontmatter(content)
    if metadata is None:
        logger.warning("SkillDoc missing frontmatter: {}", skill_path)
        return None

    skill_id = str(metadata.get("id") or "").strip()
    description = str(metadata.get("description") or "").strip()
    if not skill_id or not description:
        logger.warning("SkillDoc missing required fields: {}", skill_path)
        return None

    return SkillDoc(
        id=skill_id,
        description=description,
        when_to_load=normalize_string_list(metadata.get("when_to_load")),
        suggested_tools=normalize_string_list(metadata.get("suggested_tools")),
        body=body.strip(),
        path=str(skill_path),
    )


def split_frontmatter(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """拆分 YAML frontmatter 和 Markdown body。"""
    if not content.startswith("---\n"):
        return None, content

    end_index = content.find("\n---", 4)
    if end_index == -1:
        return None, content

    yaml_content = content[4:end_index].strip()
    body = content[end_index + len("\n---") :].lstrip("\n")

    try:
        metadata = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError as exc:
        logger.warning("Invalid SkillDoc YAML frontmatter: {}", exc)
        return None, body

    if not isinstance(metadata, dict):
        return None, body
    return metadata, body


def normalize_string_list(value: Any) -> List[str]:
    """把 frontmatter 中的 list/string/None 统一成 list[str]。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes)):
        return [str(item) for item in value if str(item).strip()]
    return []


def dedupe_preserve_order(items: Sequence[str]) -> List[str]:
    """保序去重，避免同一个 Skill 被重复注入上下文。"""
    seen = set()
    deduped: List[str] = []
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
