"""Agent implementations for the Maker-Checker system.

Import concrete agents from their modules, for example:
    from agents.generator import GeneratorAgent
    from agents.reviewer import ReviewerAgent

Keeping package initialization light avoids circular imports between agents
and pipeline modules.
"""

__all__ = [
    "base",
    "skill_registry_mixin",
    "generator",
    "reviewer",
    "lead",
]
