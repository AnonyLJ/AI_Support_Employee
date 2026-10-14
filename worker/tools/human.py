"""Human-in-the-loop: clarification questions and approvals.

The worker talks to a Human object, so the same code works in a terminal
(ConsoleHuman), unattended (NoHuman) and in tests (ScriptedHuman).
"""
from __future__ import annotations

from typing import Protocol

from . import Tool, ToolResult, params

NO_HUMAN_ANSWER = ("NO HUMAN AVAILABLE: nobody can answer right now. Do not do anything that depends on this "
                   "answer. Finish with status 'needs_human' and explain exactly what you need.")


class Human(Protocol):
    def ask(self, question: str) -> str: ...
    def approve(self, action: str) -> bool: ...


class ConsoleHuman:
    def ask(self, question: str) -> str:
        print(f"\n>>> The worker asks: {question}")
        return input(">>> Your answer: ").strip() or "(no answer)"

    def approve(self, action: str) -> bool:
        print(f"\n>>> Approval needed before the worker continues:\n    {action}")
        return input(">>> Approve? [y/N]: ").strip().lower() in ("y", "yes")


class NoHuman:
    """For unattended runs: questions are never answered and approvals are always refused."""

    def ask(self, question: str) -> str:
        return NO_HUMAN_ANSWER

    def approve(self, action: str) -> bool:
        return False


class ScriptedHuman:
    """For tests: replies with prepared answers, in order."""

    def __init__(self, answers: list[str] | None = None, approve_all: bool = True):
        self.answers = list(answers or [])
        self.approve_all = approve_all
        self.questions: list[str] = []

    def ask(self, question: str) -> str:
        self.questions.append(question)
        return self.answers.pop(0) if self.answers else NO_HUMAN_ANSWER

    def approve(self, action: str) -> bool:
        self.questions.append(action)
        return self.approve_all


def human_tools(human: Human, log) -> list[Tool]:
    def ask_human(question: str) -> ToolResult:
        answer = human.ask(question)
        log.human(question, answer)
        return ToolResult(f"Human answered: {answer}")

    return [Tool(
        "ask_human",
        "Ask the user a question and wait for the answer. Use it for approvals that company policy requires, "
        "for missing or ambiguous information, and whenever it is not safe to continue on your own.",
        params({"question": {"type": "string", "description": "A clear, self-contained question"}}),
        ask_human,
    )]
