"""Basic smoke tests for Next Agent."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from next_agent.tools.registry import dispatch


def test_imports():
    """All core modules import cleanly."""
    from next_agent import Agent, LLMAdapter, LLMConfig, PrefixManager
    from next_agent.llm import ToolCall, LLMResponse
    from next_agent.validate import ToolValidator
    from next_agent.reasoning import ReasoningExtractor
    from next_agent.cache_dash import CacheDashboard
    from next_agent.lang_router import LanguageRouter
    from next_agent.turbo import ModelRouter
    from next_agent.compress import ProgressiveCompressor
    from next_agent.cross_file import CrossFileGuard
    from next_agent.workspace import build_snapshot
    from next_agent.tools.registry import ALL_TOOL_SCHEMAS, dispatch


def test_tool_dispatch():
    """Basic tool dispatch works."""
    result = dispatch("project_info", {})
    assert result.get("ok"), f"project_info failed: {result}"

    result = dispatch("list_dir", {"path": "."})
    assert result.get("ok"), f"list_dir failed: {result}"


def test_safety():
    """Safety checks block dangerous commands."""
    from next_agent.tools.registry import is_safe_bash
    ok, reason = is_safe_bash("rm -rf /")
    assert not ok, "rm -rf / should be blocked"

    ok, _ = is_safe_bash("ls -la")
    assert ok, "ls -la should be allowed"


def test_language_detection():
    """Language detection works."""
    from next_agent.lang_router import LanguageRouter
    assert LanguageRouter.detect("你好世界") == "zh"
    assert LanguageRouter.detect("hello world") == "en"


def test_model_router():
    """Model router chooses appropriate models."""
    from next_agent.turbo import ModelRouter
    router = ModelRouter()

    # Simple task → flash
    sel = router.select("fix typo in readme", file_count=10)
    assert sel.model == "deepseek-v4-flash"

    # Complex task → pro
    sel2 = router.select("设计一个新的支付系统架构", file_count=600)
    assert sel2.model == "deepseek-v4-pro"


def test_prefix_manager():
    """Prefix manager builds frozen prefix."""
    from next_agent.prefix import PrefixManager
    pm = PrefixManager()
    pm.build("test system prompt", [{"type": "function", "function": {"name": "x"}}])
    assert pm.is_frozen
    assert len(pm.prefix_hash) > 0


def test_constitution():
    """Constitution loads."""
    from next_agent.constitution import Constitution
    c = Constitution()
    assert len(c.authority) > 0
    assert len(c.protected_invariants) > 0
