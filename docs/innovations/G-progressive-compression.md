# G — 渐进式上下文压缩 (Progressive Context Compression)

## 解决的问题

DeepSeek 的上下文窗口是 128K，比 Claude 的 200K 少 36%。长时间会话中上下文快速填满，现有方案（Reasonix、CodeWhale）只是简单截断旧消息——丢失关键信息。

**我们的目标**：在保护关键信息的前提下，多级压缩旧消息。

## 方案：4 级压缩金字塔

```
┌─────────────────────────────────────────────────────────┐
│  Context Window (128K / ~120K usable)                    │
│                                                          │
│  ┌──────────────────────────────────────────────┐       │
│  │ Level 0: Full fidelity (last 5 turns)         │       │
│  │  完整对话 + 完整工具结果                          │       │
│  │  占 ~30% 上下文                                 │       │
│  └──────────────────────────────────────────────┘       │
│  ┌──────────────────────────────────────────────┐       │
│  │ Level 1: Summarized (turns 6-15)             │       │
│  │  工具结果压缩到 ~500 chars，保留关键事实          │       │
│  │  保留 LLM 的问题/决策                           │       │
│  └──────────────────────────────────────────────┘       │
│  ┌──────────────────────────────────────────────┐       │
│  │ Level 2: Facts only (turns 16-30)            │       │
│  │  每条只保留: "做了什么 → 什么结果"               │       │
│  │  e.g. "read auth.py → found login() fn"       │       │
│  └──────────────────────────────────────────────┘       │
│  ┌──────────────────────────────────────────────┐       │
│  │ Level 3: Summary (turns 30+)                 │       │
│  │  整段对话摘要: "讨论了认证模块,修复了bug #42..."  │       │
│  └──────────────────────────────────────────────┘       │
│                                                          │
│  ┌──────────────────────────────────────────────┐       │
│  │ FROZEN PREFIX: tools + project + memory       │       │
│  │ 永不变动 → cache 命中 → 几乎免费                 │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

## 实现

```python
class ProgressiveCompressor:
    """Multi-level context compression preserving critical info."""

    THRESHOLD_LEVEL1 = 0.50  # 50% full → compress level 1
    THRESHOLD_LEVEL2 = 0.65  # 65% → compress to level 2
    THRESHOLD_CHECKPOINT = 0.85  # 85% → checkpoint + resume
    
    def __init__(self, max_context_tokens: int = 120_000):
        self.max_tokens = max_context_tokens

    def should_compress(self, current_tokens: int) -> str:
        """Returns compression action: 'none', 'level1', 'level2', 'checkpoint'."""
        ratio = current_tokens / self.max_tokens
        if ratio < self.THRESHOLD_LEVEL1:
            return "none"
        elif ratio < self.THRESHOLD_LEVEL2:
            return "level1"
        elif ratio < self.THRESHOLD_CHECKPOINT:
            return "level2"
        else:
            return "checkpoint"

    def compress_level1(self, turn: Turn) -> Turn:
        """Compress tool results to ~500 chars, preserve facts."""
        compressed = turn.copy()
        for msg in compressed.messages:
            if msg.role == "tool":
                content = msg.content
                if len(content) > 500:
                    # Extract key facts: file names, error messages, line counts
                    facts = self._extract_facts(content)
                    msg.content = (
                        f"[压缩] 结果 {len(content)} chars → "
                        f"关键事实: {'; '.join(facts[:3])}"
                    )
        return compressed

    def compress_level2(self, turn: Turn) -> Turn:
        """Reduce to minimal fact: what was done + what was the result."""
        return Turn(
            role="system",
            content=f"[已压缩] 轮次 {turn.id}: "
                    f"工具调用 {turn.tool_name} → "
                    f"结果: {self._summarize_result(turn.result)}"
        )

    def checkout_and_resume(self, session: Session) -> Session:
        """Summarize entire session → start new session with summary."""
        summary = session.summarize(max_tokens=3000)
        new_session = Session(summary=summary)
        new_session.parent_id = session.id
        return new_session

    @staticmethod
    def _extract_facts(text: str) -> list[str]:
        """Extract actionable facts from tool output."""
        facts = []
        # File paths
        facts.extend(re.findall(r'[/\\][\w./\\-]+\.\w+', text))
        # Error messages
        facts.extend(re.findall(r'(Error|Exception|Traceback):.*', text))
        # Line counts
        facts.extend(re.findall(r'\d+ lines?', text))
        # Exit codes
        facts.extend(re.findall(r'exit.code.*?\d+', text))
        return list(dict.fromkeys(facts))  # dedup
```

## Level 1 的关键设计：事实提取 vs 简单截断

```
❌ 简单截断 (Reasonix/CodeWhale 的做法):
  "read_auth.py 返回了 487 行代码...\nclass AuthManager\nclass TokenHandler\
  \ndef login\n    validator = JWTValidator\n    def verify_token\n\
  ... [truncated after 500 chars]"

✅ 事实提取 (我们的做法):
  "[压缩] read_file(auth.py) 487 行 → 
   类: AuthManager, TokenHandler, JWTValidator
   函数: login(), verify_token(), refresh()
   错误: 无"
```

区别：简单截断可能丢失关键信息（截断了函数定义），事实提取保留结构化信息。

## 检查点机制

当上下文超过 85% → 不继续压缩（信息丢失太多），而是：
1. 用 deepseek-v4-flash（便宜）对当前会话做一个 3000 token 的摘要
2. Fork 一个新会话，摘要作为初始上下文
3. 用户感知上是连续的，但 token 从头开始

## 与 D (Cache 仪表盘) 的关系

压缩后的内容不再适用于 prefix cache（因为变了）。Cache 仪表盘会标记压缩事件：
```
  ┌────────────────────────────────────────────┐
  │ ℹ Level 1 压缩: 轮次 6-10                   │
  │   cache 需要重建 (~2000 tokens, ~$0.0003)    │
  └────────────────────────────────────────────┘
```

## 风险

- 过度压缩导致 LLM 丢失关键上下文 → 需要调优阈值
- 事实提取的正则不完美 → 需要持续改进
