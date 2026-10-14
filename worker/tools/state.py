"""State tools: the worker's plan, its working memory, and how it ends a task.

These are tools (not hidden code) so planning and memory are explicit,
visible in the console and saved in the run report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import Tool, ToolError, ToolResult, params

FINISH_STATUSES = ("completed", "needs_human", "failed")


@dataclass
class TaskState:
    plan: list[dict] = field(default_factory=list)   # [{"step": "...", "status": "todo|doing|done|skipped"}]
    facts: dict[str, str] = field(default_factory=dict)
    final: dict | None = None                        # set by finish / submit_verdict


def worker_state_tools(state: TaskState, log) -> list[Tool]:
    def update_plan(steps: list[dict]) -> ToolResult:
        state.plan = [{"step": str(s.get("step", "")), "status": str(s.get("status", "todo"))} for s in steps]
        log.plan(state.plan)
        return ToolResult("Plan saved.")

    def remember(key: str, value: str) -> ToolResult:
        state.facts[key] = value
        log.fact(key, value)
        return ToolResult(f"Remembered {key}.")

    def finish(status: str, summary: str, evidence: list[str] | None = None) -> ToolResult:
        if status not in FINISH_STATUSES:
            raise ToolError(f"status must be one of {FINISH_STATUSES}")
        state.final = {"status": status, "summary": summary, "evidence": evidence or []}
        return ToolResult("Task closed.")

    return [
        Tool("update_plan", "Write or revise your step-by-step plan. Call it before you start and whenever "
                            "the plan changes or a step is done.",
             params({"steps": {"type": "array", "items": params({
                 "step": {"type": "string"},
                 "status": {"type": "string", "enum": ["todo", "doing", "done", "skipped"]}})}}),
             update_plan),
        Tool("remember", "Save an important fact you discovered (e.g. invoice_number, customer_id, amount) "
                         "so it is not lost. Saved facts are shown to the reviewer at the end.",
             params({"key": {"type": "string"}, "value": {"type": "string"}}), remember),
        Tool("finish", "End the task. status: 'completed' (done and checked), 'needs_human' (you stopped "
                       "because a person must decide or answer), or 'failed'. Give a short summary for the "
                       "user and the evidence you observed.",
             params({"status": {"type": "string", "enum": list(FINISH_STATUSES)},
                     "summary": {"type": "string"},
                     "evidence": {"type": "array", "items": {"type": "string"},
                                  "description": "What you saw that proves the outcome, e.g. 'Invoice page "
                                                 "/invoices/KE-1 shows INR 500.00 due 2026-11-07'"}}),
             finish),
    ]


def verdict_tool(state: TaskState) -> Tool:
    def submit_verdict(verified: bool, reason: str, checks: list[str] | None = None) -> ToolResult:
        state.final = {"verified": bool(verified), "reason": reason, "checks": checks or []}
        return ToolResult("Verdict recorded.")

    return Tool("submit_verdict", "Give your verdict: was the task really completed as the user asked?",
                params({"verified": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "checks": {"type": "array", "items": {"type": "string"},
                                   "description": "Each thing you checked and what you saw"}}),
                submit_verdict)
