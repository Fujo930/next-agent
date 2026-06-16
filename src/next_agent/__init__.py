"""Next Agent — The best DeepSeek agent for everyone."""

__version__ = "0.2.3"
__author__ = "Next Agent Contributors"

from .agent import Agent
from .llm import LLMAdapter, LLMConfig
from .prefix import PrefixManager
from .skills import SkillManager
from .memory import MemoryManager

__all__ = ["Agent", "LLMAdapter", "LLMConfig", "PrefixManager", "SkillManager", "MemoryManager"]
