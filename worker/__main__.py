"""Command line:

    python -m worker "Find the latest invoice from Kaveri Electricals, extract the amount and due date,
                      enter it into our invoice system, and tell me once it is done."
    python -m worker                      # asks you for the task
    python -m worker --headed --slow-mo 400 "..."   # watch the browser (good for demo videos)

Exit code: 0 = completed, 2 = needs a human, 1 = failed / not confirmed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

from .llm import LLMError, OpenAIChat
from .runner import Settings, run_task
from .tools.human import ConsoleHuman, NoHuman


def build_parser() -> argparse.ArgumentParser:
    defaults = Settings()
    p = argparse.ArgumentParser(prog="python -m worker", description="Autonomous AI task worker")
    p.add_argument("task", nargs="*", help="What you want done, in plain language")
    p.add_argument("--model", default=os.environ.get("OPENAI_MODEL", defaults.model),
                   help="OpenAI model (default: %(default)s, or set OPENAI_MODEL)")
    p.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=None,
                   help="Reasoning effort for reasoning models (default: the model's own default)")
    p.add_argument("--portal-url", default=os.environ.get("PORTAL_URL", defaults.portal_url))
    p.add_argument("--workspace", type=Path, default=defaults.workspace, help="The shared drive folder")
    p.add_argument("--max-steps", type=int, default=defaults.max_steps)
    p.add_argument("--headed", action="store_true", help="Show the browser window")
    p.add_argument("--slow-mo", type=int, default=0, help="Slow each browser action down by N ms")
    p.add_argument("--confirm-writes", action="store_true",
                   help="Ask you before every form submission or file write")
    p.add_argument("--unattended", action="store_true",
                   help="No human available: questions go unanswered, the worker stops if it needs a person")
    p.add_argument("--no-verify", action="store_true", help="Skip the independent verification step")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on a non-ASCII character in a Windows console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    task = " ".join(args.task).strip() or input("What should the worker do?\n> ").strip()
    if not task:
        print("No task given.")
        return 1

    try:
        requests.get(f"{args.portal_url}/api/health", timeout=3).raise_for_status()
    except requests.RequestException:
        print(f"The company portal is not reachable at {args.portal_url}.\n"
              f"Start it first in another terminal:  python -m company_portal --reset")
        return 1
    try:
        llm = OpenAIChat(args.model, args.reasoning_effort)
    except LLMError as exc:
        print(f"Cannot use the OpenAI API: {exc}\nSet your key first, e.g. (PowerShell): "
              f"$env:OPENAI_API_KEY = \"sk-...\"")
        return 1

    settings = Settings(model=args.model, reasoning_effort=args.reasoning_effort, portal_url=args.portal_url,
                        workspace=args.workspace.resolve(), max_steps=args.max_steps, headless=not args.headed,
                        slow_mo=args.slow_mo, confirm_writes=args.confirm_writes, verify=not args.no_verify)
    human = NoHuman() if args.unattended else ConsoleHuman()
    print(f"Model: {args.model} | portal: {args.portal_url} | workspace: {settings.workspace}\n")

    outcome = run_task(task, settings, llm, human)

    print("\n" + "=" * 72)
    print(f"RESULT: {outcome.status.upper()}")
    print(outcome.result.get("summary", ""))
    if outcome.verification:
        print(f"\nIndependent check: {'PASSED' if outcome.verification['verified'] else 'FAILED'} - "
              f"{outcome.verification['reason']}")
    print(f"\nFull report with screenshots: {outcome.report_path}")
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
