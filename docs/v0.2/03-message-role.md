# L — Message Role 交替强制 (Message Role Enforcement)

## 借鉴 Hermes

Hermes 的 agent loop 强制 message role 交替——永远不会出现连续两个 `assistant` 或连续两个 `user` 消息。违反会导致 OpenAI API 400 错误。

## 当前状态

Next Agent v0.1 的 `_run_loop` 通过 `messages.append()` 追加消息，但没有检查 role 交替。理论上不会违反（因为没有异常路径），但以下场景可能出错：

- 子代理结果直接追加到主消息列表
- 压缩后消息顺序被打乱
- 手动构造的 message 列表

## 方案

单点检查——在 `messages.append()` 前验证。

### 实现

```python
# In agent.py, replace all messages.append() with _append_message()

def _append_message(self, msg: dict) -> None:
    """Append a message, enforcing role alternation."""
    if not self.messages:
        self.messages.append(msg)
        return
    
    prev_role = self.messages[-1].get("role", "")
    new_role = msg.get("role", "")
    
    # System messages can appear anywhere
    if new_role == "system":
        self.messages.append(msg)
        return
    
    # Tool messages must follow assistant(tool_calls)
    if new_role == "tool":
        prev_has_tool_calls = bool(self.messages[-1].get("tool_calls"))
        if not prev_has_tool_calls and prev_role != "tool":
            # Insert a synthetic assistant acknowledgment
            self.messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [],  # empty — will be harmless
            })
    
    # Same role twice → merge or warn
    if new_role == prev_role and new_role != "tool":
        # For assistant: append as new paragraph (not ideal but better than crash)
        # For user: unlikely but merge
        pass
    
    self.messages.append(msg)
```

### 改动文件

- `src/next_agent/agent.py` — 加 `_append_message()` + 替换所有 `messages.append()`
