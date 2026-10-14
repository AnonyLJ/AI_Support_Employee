import json
import re
import threading

import pytest
from werkzeug.serving import make_server

from company_portal.app import create_app
from worker.llm import LLMReply, ToolCall


@pytest.fixture
def start_portal(tmp_path):
    """Start the company portal on a free port with a fresh database; returns its URL."""
    servers = []

    def start(failure_rate: float = 0.0, seed: int | None = None) -> str:
        app = create_app(tmp_path / f"portal{len(servers)}.db", failure_rate=failure_rate, seed=seed)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server in servers:
        server.shutdown()


@pytest.fixture
def portal_url(start_portal):
    return start_portal()


class ScriptedLLM:
    """Stands in for the real model in tests.

    Each script entry is a list of (tool_name, args) pairs, a plain string (a
    text reply without tool calls), or a function that receives the
    conversation so far and returns one of those - so a script can react to
    what it observed, e.g. find the ref of the "Save invoice" button.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if not self.script:
            raise AssertionError("ScriptedLLM ran out of script")
        entry = self.script.pop(0)
        out = entry(messages) if callable(entry) else entry
        if isinstance(out, str):
            return LLMReply(out, [], {"role": "assistant", "content": out}, {"input": 10, "output": 5})
        calls = [ToolCall(f"call_{self.calls}_{i}", name, json.dumps(args)) for i, (name, args) in enumerate(out)]
        message = {"role": "assistant", "content": None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls]}
        return LLMReply(None, calls, message, {"input": 10, "output": 5})


def last_result(messages) -> str:
    return next(m["content"] for m in reversed(messages) if m["role"] == "tool")


def ref(snapshot: str, label: str) -> str:
    """Find the [eN] ref of the element whose label starts with `label`."""
    match = re.search(rf'\[(e\d+)\] \w+ "{re.escape(label)}', snapshot)
    assert match, f"no element labelled {label!r} in:\n{snapshot}"
    return match.group(1)
