"""Shared Skill registration helpers for Maker-Checker agents."""

from pathlib import Path
from typing import Iterable, Optional
import inspect

from loguru import logger

from core.skill_loader import discover_skills
from core.skill_registry import SkillParameter


class SkillRegistryMixin:
    """Auto-discover and register Anthropic-style project Skills."""

    def register_all_skills(self, exclude: Optional[Iterable[str]] = None) -> None:
        """Register all discovered Skills, optionally excluding selected ones.

        Args:
            exclude: Skill names to skip. Both kebab-case directory names
                (``recommend-lifestyle``) and snake_case function names
                (``recommend_lifestyle``) are accepted.
        """
        project_root = Path(__file__).parent.parent
        discovered = discover_skills(project_root)
        excluded = self._normalize_excluded_skills(exclude or [])

        for skill_info in discovered:
            function_name = skill_info["function_name"]
            skill_name = skill_info["name"]
            if function_name in excluded or skill_name in excluded:
                logger.debug(f"Skipping excluded skill: {skill_name}")
                continue

            metadata = skill_info["metadata"]
            func = skill_info["function"]
            description = metadata.get("description", f"Skill: {skill_name}")
            parameters = self._infer_skill_parameters(skill_info)

            self.skill_registry.register(
                name=function_name,
                function=func,
                description=description,
                parameters=parameters,
            )
            logger.debug(f"Registered skill: {function_name}")

        logger.debug(f"Total {len(self.skill_registry.get_all())} skills registered")

    @staticmethod
    def _normalize_excluded_skills(exclude: Iterable[str]) -> set:
        """Support both kebab-case skill names and snake_case function names."""
        normalized = set()
        for name in exclude:
            normalized.add(name)
            normalized.add(name.replace("-", "_"))
            normalized.add(name.replace("_", "-"))
        return normalized

    def _infer_skill_parameters(self, skill_info: dict) -> list:
        """Infer OpenAI-tool parameters from a Skill function signature."""
        func = skill_info["function"]
        sig = inspect.signature(func)
        parameters = []

        for param_name, param in sig.parameters.items():
            if param_name in ["self", "args", "kwargs"]:
                continue

            required = param.default == inspect.Parameter.empty
            param_type = "string"
            if any(token in param_name for token in ["count", "limit", "max", "iterations"]):
                param_type = "number"

            parameters.append(
                SkillParameter(
                    param_name,
                    param_type,
                    param_name.replace("_", " ").title(),
                    required,
                )
            )

        return parameters
