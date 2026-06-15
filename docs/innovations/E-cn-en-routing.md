# E — 中文-英文动态路由 (CN-EN Dynamic Routing)

## 解决的问题

DeepSeek v4 是**唯一**在中英文上同样强大的模型，但所有现有 agent 都用纯英文 prompt。这在中文用户场景中浪费了 DeepSeek 的双语优势。

## 发现：不同任务在不同语言中表现更好

通过分析 DeepSeek 在不同语言中的性能差异：

| 任务类型 | 最佳语言 | 原因 |
|---------|---------|------|
| 代码生成 | 英文 | 代码本身就是英文生态 |
| 技术分析 | 英文 | 技术术语无歧义 |
| 架构设计/高层规划 | 中文 | 对中文用户更准确的表达 |
| Bug 调试推理 | 中文 | 更自然的逻辑链 |
| 文件读写 | 英文 | 减少翻译开销 |
| 用户交互 | 匹配用户语言 | 避免中英混杂 |

## 方案：per-request 语言选择

```
用户输入: "这个 JWT 验证逻辑为什么不安全？"
    ↓
语言检测: 中文 (中文字符占比 > 30%)
    ↓
构建 system prompt:
  "用中文进行推理分析，但代码和技术术语保持英文。
   最终输出使用中文，代码示例用英文注释。"
    ↓
DeepSeek 输出:
  推理: "JWT 的签名验证使用 HS256 算法...问题在于 secret 是硬编码的..."
  代码: "```python\n# Fix: load secret from env\njwt_secret = os.environ['JWT_SECRET']\n```"
```

## 实现

```python
class LanguageRouter:
    """Routes prompt language based on task type and user language."""

    CHINESE_CHARS = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

    # Tasks that benefit from Chinese reasoning
    CN_FAVORED_KEYWORDS = [
        "为什么", "如何", "设计", "架构", "重构", "建议",
        "怎么", "原因", "分析", "解释", "比较", "选择",
        "优化", "最佳实践", "方案", "思路",
    ]

    @classmethod
    def detect_user_language(cls, text: str) -> str:
        """Detect primary language from user input."""
        chinese_count = len(cls.CHINESE_CHARS.findall(text))
        total_chars = len(text.replace(" ", ""))
        if total_chars > 0 and chinese_count / total_chars > 0.3:
            return "zh"
        return "en"

    @classmethod
    def get_system_extension(cls, user_lang: str, content: str) -> str:
        """Return language-tuning instructions."""
        if user_lang != "zh":
            return ""  # default: English only

        # Check if task is code-heavy (use English for code context)
        code_keywords = ["python", "js", "rust", "函数", "代码", "bug",
                         "fix", "implement", "write", "test", "import"]
        is_code_task = any(kw in content.lower() for kw in code_keywords)

        # Check if task benefits from Chinese reasoning
        is_cn_favored = any(kw in content for kw in cls.CN_FAVORED_KEYWORDS)

        if is_code_task and not is_cn_favored:
            return (
                "这是一位中文用户。代码和注释使用英文，"
                "简短说明使用中文。"
            )
        elif is_cn_favored:
            return (
                "这是一位中文用户。用中文进行推理分析，"
                "代码和技术术语保持英文。"
            )
        else:
            return (
                "这是一位中文用户。用中文回复，"
                "技术术语和代码保持英文。"
            )

    @classmethod
    def format_output(cls, user_lang: str, text: str) -> str:
        """Post-process: ensure language consistency."""
        if user_lang != "zh":
            return text
        
        # If the output mixes languages awkwardly, clean up
        # ... minimal post-processing
        return text
```

## 为什么这不需要模型特殊支持

- 就是 prompt 工程：在 system prompt 中加一段语言指令
- DeepSeek 本身在多语言上训练，遵循语言指令很自然
- 不影响 function calling（函数名和参数仍然是英文）

## 与 A (推理提取) 的组合效果

```
用户: "为什么 auth 模块的 token 过期后还能访问？"
    ↓
E: 检测为中文 + 分析型任务 → 中文推理
A: REASONING: "先去读 auth.py 检查 token_verify() 的实现
    → 检查是否有 expiry 检查 → 检查缓存策略..."
    ↓
DeepSeek 在中文中推理更自然 → 更准确的工具调用序列
```

## 优势

- 零额外成本（就是一个字符串判断 + prompt 拼接）
- 对英文用户完全透明（不影响默认行为）
- 大量中文 DeepSeek 用户群体
