"""Runs one task end to end: worker -> independent verification -> (one fix-up round) -> report."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .agent import Agent
from .llm import LLMError
from .prompts import RETRY_AFTER_FAILED_CHECK, VERIFIER_PROMPT, VERIFY_REQUEST, WORKER_PROMPT
from .run_log import RunLog
from .tools.browser import Browser, browser_tools
from .tools.files import Workspace, file_tools
from .tools.human import Human, NoHuman, human_tools
from .tools.state import TaskState, verdict_tool, worker_state_tools

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    model: str = "gpt-5.4-mini"
    reasoning_effort: str | None = None
    portal_url: str = "http://127.0.0.1:5050"
    workspace: Path = PROJECT_ROOT / "workspace"
    runs_dir: Path = PROJECT_ROOT / "runs"
    max_steps: int = 40
    verifier_max_steps: int = 15
    headless: bool = True
    slow_mo: int = 0
    confirm_writes: bool = False
    verify: bool = True


@dataclass
class RunOutcome:
    status: str          # verified | completed | unverified | needs_human | failed
    result: dict
    verification: dict | None
    report_path: Path
    facts: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        return {"verified": 0, "completed": 0, "needs_human": 2}.get(self.status, 1)


def _prompt(template: str, settings: Settings) -> str:
    handbook = (settings.workspace / "company_handbook.md").read_text(encoding="utf-8")
    handbook = handbook.replace("{portal_url}", settings.portal_url)
    return template.format(today=date.today().isoformat(), handbook=handbook)


def _bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items) or "(none)"


def verify(llm, task: str, result: dict, facts: dict, log: RunLog, browser: Browser, workspace: Workspace,
           settings: Settings) -> tuple[dict, list[dict]]:
    """A second agent with read-only tools checks the outcome independently."""
    state = TaskState()
    tools = file_tools(workspace, read_only=True) + browser_tools(browser, read_only=True) + [verdict_tool(state)]
    reviewer = Agent(llm, tools, _prompt(VERIFIER_PROMPT, settings), state, log, NoHuman(),
                     role="verifier", max_steps=settings.verifier_max_steps)
    human_log = [f"Q: {e['question']} / A: {e['answer']}" if e["kind"] == "human"
                 else f"Write approval {'granted' if e['approved'] else 'denied'}: {e['action']}"
                 for e in log.events if e["kind"] in ("human", "approval")]
    verdict = reviewer.run(VERIFY_REQUEST.format(
        task=task, status=result["status"], summary=result.get("summary", ""),
        evidence=_bullets(result.get("evidence", [])), facts=_bullets(f"{k}: {v}" for k, v in facts.items()),
        human=_bullets(human_log)))
    if "verified" not in verdict:  # the reviewer ran out of steps or stopped without a verdict
        verdict = {"verified": False, "reason": verdict.get("summary", "The reviewer gave no verdict."), "checks": []}
    log.note(f"Verification {'PASSED' if verdict['verified'] else 'FAILED'}: {verdict['reason']}")
    return verdict, reviewer.messages


def run_task(task: str, settings: Settings, llm, human: Human, echo: bool = True) -> RunOutcome:
    log = RunLog(settings.runs_dir, task, echo=echo)
    browser = Browser([settings.portal_url], headless=settings.headless, slow_mo=settings.slow_mo,
                      screenshot_dir=log.screens_dir)
    workspace = Workspace(settings.workspace)
    state = TaskState()
    transcripts: dict[str, list] = {}
    result: dict = {"status": "failed", "summary": "The run did not start.", "evidence": []}
    verification = None

    try:
        tools = (file_tools(workspace) + browser_tools(browser) + human_tools(human, log)
                 + worker_state_tools(state, log))
        worker = Agent(llm, tools, _prompt(WORKER_PROMPT, settings), state, log, human,
                       max_steps=settings.max_steps, confirm_writes=settings.confirm_writes)
        transcripts["worker"] = worker.messages
        log.note(f"Task: {task}")
        result = worker.run(task)

        if settings.verify and result["status"] == "completed":
            verification, transcripts["verifier"] = verify(llm, task, result, state.facts, log, browser,
                                                           workspace, settings)
            if not verification["verified"]:
                log.note("Sending the reviewer's findings back to the worker for one more attempt")
                result = worker.run(RETRY_AFTER_FAILED_CHECK.format(
                    reason=verification["reason"], checks=_bullets(verification.get("checks", []))))
                if result["status"] == "completed":
                    verification, transcripts["verifier_2"] = verify(llm, task, result, state.facts, log,
                                                                     browser, workspace, settings)
    except LLMError as exc:
        log.note(f"Model error: {exc}")
        result = {"status": "failed", "summary": f"Stopped because the AI model could not be used: {exc}",
                  "evidence": []}
    finally:
        browser.close()

    if result["status"] == "completed" and verification is not None:
        status = "verified" if verification["verified"] else "unverified"
    else:
        status = result["status"]
    labels = {"verified": "COMPLETED - independently verified",
              "completed": "COMPLETED (independent verification was switched off)",
              "unverified": "NOT CONFIRMED - the worker says done, but the independent check failed",
              "needs_human": "NEEDS HUMAN - the worker stopped and needs a person",
              "failed": "FAILED"}
    report = log.write_report(labels[status], result, verification, state.plan, state.facts, transcripts)
    return RunOutcome(status, result, verification, report, state.facts)
