"""MCP (Model Context Protocol) client — connects to external tool servers.

MCP servers communicate via stdio JSON-RPC. This module:
1. Launches an MCP server as a subprocess
2. Discovers available tools (tools/list)
3. Invokes tools on behalf of the agent (tools/call)

Protocol: JSON-RPC 2.0 over stdin/stdout
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from queue import Queue, Empty


@dataclass
class MCPTool:
    """An MCP tool discovered from a server."""
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    server_name: str = ""


class MCPClient:
    """JSON-RPC client for an MCP server subprocess."""

    def __init__(self, command: list[str], server_name: str = ""):
        self.command = command
        self.server_name = server_name or command[0]
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._responses: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> bool:
        """Launch the MCP server subprocess."""
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._running = True
            self._reader_thread = threading.Thread(
                target=self._read_responses, daemon=True
            )
            self._reader_thread.start()

            # Send initialize
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "next-agent", "version": "0.2.3"},
            })
            return result is not None

        except Exception:
            return False

    def stop(self) -> None:
        """Stop the MCP server subprocess."""
        self._running = False
        if self._process:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()

    def list_tools(self) -> list[MCPTool]:
        """Discover tools from the MCP server."""
        result = self._send_request("tools/list", {})
        if not result or "tools" not in result:
            return []

        tools = []
        for tool in result["tools"]:
            tools.append(MCPTool(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {}),
                server_name=self.server_name,
            ))
        return tools

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a tool on the MCP server.

        Returns {"ok": True, "output": "..."} or {"ok": False, "error": "..."}
        """
        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result is None:
            return {"ok": False, "error": f"MCP server '{self.server_name}' not responding"}

        # MCP results come in nested format
        content = result.get("content", [])
        if isinstance(content, list) and content:
            text_parts = [
                c.get("text", "") for c in content if c.get("type") == "text"
            ]
            return {"ok": True, "output": "\n".join(text_parts)}
        return {"ok": True, "output": json.dumps(result, ensure_ascii=False)}

    def _send_request(self, method: str, params: dict, timeout: float = 30) -> dict | None:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin:
            return None

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        try:
            self._process.stdin.write(json.dumps(request) + "\n")
            self._process.stdin.flush()
        except Exception:
            return None

        # Wait for response
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if req_id in self._responses:
                    resp = self._responses.pop(req_id)
                    if "error" in resp:
                        return None
                    return resp.get("result", {})
            time.sleep(0.05)

        return None  # timeout

    def _read_responses(self) -> None:
        """Background thread: read responses from server stdout."""
        try:
            for line in self._process.stdout:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if "id" in msg:
                        with self._lock:
                            self._responses[msg["id"]] = msg
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass


# ── MCP Manager ──────────────────────────────────────────────

class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, MCPTool] = {}  # tool_name → MCPTool

    def register_server(self, name: str, command: list[str]) -> bool:
        """Register and start an MCP server."""
        if name in self._clients:
            return True  # already running

        client = MCPClient(command, server_name=name)
        if not client.start():
            return False

        self._clients[name] = client

        # Discover tools
        tools = client.list_tools()
        for tool in tools:
            # Prefix tool name with server name to avoid conflicts
            full_name = f"mcp_{name}_{tool.name}"
            self._tools[full_name] = tool
            self._tools[full_name].name = full_name

        return True

    def get_tool_schemas(self) -> list[dict]:
        """Get OpenAI-compatible tool schemas for all MCP tools."""
        schemas = []
        for name, tool in self._tools.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"[MCP:{tool.server_name}] {tool.description}",
                    "parameters": tool.input_schema if tool.input_schema else {
                        "type": "object",
                        "properties": {},
                    },
                },
            })
        return schemas

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Call an MCP tool by its full name."""
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"Unknown MCP tool: {name}"}

        client_name = tool.server_name
        client = self._clients.get(client_name)
        if not client:
            return {"ok": False, "error": f"MCP server '{client_name}' not connected"}

        # Strip the mcp_<server>_ prefix to get the original tool name
        original_name = name[len(f"mcp_{client_name}_"):]
        return client.call_tool(original_name, arguments)

    def stop_all(self) -> None:
        """Stop all MCP servers."""
        for client in self._clients.values():
            client.stop()
        self._clients.clear()
        self._tools.clear()

    @property
    def server_count(self) -> int:
        return len(self._clients)

    @property
    def tool_count(self) -> int:
        return len(self._tools)


# Global manager
_mcp_manager = MCPManager()


def register_mcp_server(name: str, command: list[str] | str) -> dict:
    """Register and start an MCP server.

    Args:
        name: Human-readable server name
        command: Command as list (e.g., ["python", "server.py"]) or string

    Returns:
        {"ok": True, "tools": N} on success
    """
    if isinstance(command, str):
        command = command.split()

    ok = _mcp_manager.register_server(name, command)
    if ok:
        schemas = _mcp_manager.get_tool_schemas()
        return {
            "ok": True,
            "output": f"MCP server '{name}' registered with {_mcp_manager.tool_count} tools",
            "tools": len(schemas),
        }
    return {"ok": False, "error": f"Failed to start MCP server '{name}'"}


def get_mcp_manager() -> MCPManager:
    """Get the global MCP manager."""
    return _mcp_manager
