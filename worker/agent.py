"""The agent loop: Goal -> Plan -> Act -> Observe -> Adapt, until the model calls finish.

    while not finished and steps < max_steps:
        reply = model(conversation, tools)          # model decides the next action(s)
        for each tool call in reply:
            result = run the tool                   # act
            add result to the conversation          # observe; errors are shown, not hidden
        (the model reads the results next turn and adapts)

The loop is the same for every task. What changes per task is only the user's
request; what changes per company is only the handbook in the system prompt.
The harness adds the safety rails a model alone does not guarantee:
argument checking, error feedback, a write-approval gate, a repeated-action
guard, context trimming and a hard step limit.
"""
from __future__ import annotations

import json

from .llm import LLMReply
from .run_log import RunLog
from .tools import Tool, ToolError, ToolResult
from .tools.human import Human
from .tools.state import TaskState

KEEP_FULL_PAGES = 2  # older page snapshots are shortened to keep the context small
REPEAT_LIMIT = 3
NUDGE = ("You replied without using a tool. Continue the task with your tools, or call the "
         "finishing tool if you are done or cannot continue.")


class Agent:
    def __init__(self, llm, tools: list[Tool], system_prompt: str, state: TaskState, log: RunLog,
                 human: Human, *, role: str = "worker", max_steps: int = 40, confirm_writes: bool = False):
        self.llm = llm
        self.tools = {t.name: t for t in tools}
        self.schemas = [t.schema() for t in tools]
        self.state = state
        self.log = log
        self.human = human
        self.role = role
        self.max_steps = max_steps
        self.confirm_writes = confirm_writes
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self.steps = 0
        self._page_messages: list[int] = []
        self._recent_calls: list[str] = []

    # ------------------------------------------------------------------ main loop
    def run(self, user_message: str) -> dict:
        """Run until the model finishes. Can be called again to continue the same conversation."""
        self.messages.append({"role": "user", "content": user_message})
        self.state.final = None
        nudges = 0
        limit = self.steps + self.max_steps
        while self.steps < limit:
            self.steps += 1
            self._shorten_old_pages()
            reply: LLMReply = self.llm.complete(self.messages, self.schemas)
            self.log.usage(reply.usage)
            self.messages.append(reply.message)
            if reply.text:
                self.log.thought(self.role, self.steps, reply.text)

            if not reply.tool_calls:
                nudges += 1
                if nudges > 2:
                    return {"status": "failed", "summary": "The model stopped using tools without finishing.",
                            "evidence": []}
                self.messages.append({"role": "user", "content": NUDGE})
                continue
            nudges = 0

            for call in reply.tool_calls:
                if self.state.final is not None:  # every tool call needs an answer, even after finish
                    result = ToolResult("Skipped: the task was already closed.", ok=False)
                else:
                    result = self._execute(call.name, call.arguments)
                if result.is_page:
                    self._page_messages.append(len(self.messages))
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": result.text})

            if self.state.final is not None:
                return self.state.final

        return {"status": "failed", "evidence": [],
                "summary": f"Stopped after {self.max_steps} steps without finishing (step limit)."}

    # ------------------------------------------------------------------ one tool call
    def _execute(self, name: str, raw_arguments: str) -> ToolResult:
        tool = self.tools.get(name)
        args: dict = {}
        if tool is None:
            result = ToolResult(f"ERROR: there is no tool called '{name}'. Available: {', '.join(self.tools)}",
                                ok=False)
        else:
            try:
                args = json.loads(raw_arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except ValueError as exc:
                result = ToolResult(f"ERROR: the arguments were not valid JSON ({exc}). Try again.", ok=False)
            else:
                result = self._run_tool(tool, args)

        self.log.action(self.role, self.steps, name, args, result)
        return result

    def _run_tool(self, tool: Tool, args: dict) -> ToolResult:
        # Guard against loops: the same call again and again usually means the model is stuck.
        signature = tool.name + json.dumps(args, sort_keys=True)
        self._recent_calls = (self._recent_calls + [signature])[-REPEAT_LIMIT:]
        repeated = len(self._recent_calls) == REPEAT_LIMIT and len(set(self._recent_calls)) == 1

        # Optional approval gate for actions that change data (--confirm-writes).
        if self.confirm_writes and tool.describe_write:
            try:
                description = tool.describe_write(args)
            except Exception:
                description = None
            if description:
                approved = self.human.approve(description)
                self.log.approval(description, approved)
                if not approved:
                    return ToolResult("DENIED: the human did not approve this action, so it was not performed. "
                                      "Do not try it again. Ask the human what to do, or finish with status "
                                      "'needs_human'.", ok=False)

        try:
            outcome = tool.run(**args)
            result = outcome if isinstance(outcome, ToolResult) else ToolResult(str(outcome))
        except ToolError as exc:
            result = ToolResult(f"ERROR: {exc}", ok=False)
        except TypeError as exc:  # missing / unexpected arguments
            result = ToolResult(f"ERROR: wrong arguments for {tool.name}: {exc}", ok=False)
        except Exception as exc:  # a bug or an unexpected state: report it to the model, don't crash
            result = ToolResult(f"ERROR: {type(exc).__name__}: {str(exc)[:300]}", ok=False)

        if repeated:
            result.text = (f"WARNING: you have made exactly this call {REPEAT_LIMIT} times in a row. If it is not "
                           f"getting you closer to the goal, try a different approach or ask the human.\n"
                           + result.text)
        return result

    # ------------------------------------------------------------------ context management
    def _shorten_old_pages(self) -> None:
        """Keep only the latest page snapshots in full; old pages are stale anyway."""
        for index in self._page_messages[:-KEEP_FULL_PAGES]:
            message = self.messages[index]
            if not message["content"].startswith("[old page"):
                first_line = message["content"].splitlines()[0]
                message["content"] = f"[old page snapshot removed to save space] {first_line}"
        self._page_messages = self._page_messages[-KEEP_FULL_PAGES:]
