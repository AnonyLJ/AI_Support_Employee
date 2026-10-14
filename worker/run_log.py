"""Run log: prints what the worker does as it happens and writes the final report.

Every run gets a folder runs/<timestamp>/ with
  report.md        - human-readable summary, timeline and evidence
  run.json         - everything, including the full model conversation
  screens/*.png    - browser screenshots taken after each navigation
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class RunLog:
    def __init__(self, runs_dir: str | Path, task: str, echo: bool = True):
        self.started = datetime.now()
        self.dir = Path(runs_dir) / self.started.strftime("%Y%m%d-%H%M%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.screens_dir = self.dir / "screens"
        self.task = task
        self.echo = echo
        self.events: list[dict] = []
        self.tokens = {"input": 0, "output": 0, "calls": 0}
        self._t0 = time.perf_counter()

    def _add(self, kind: str, line: str, **data) -> None:
        self.events.append({"t": round(time.perf_counter() - self._t0, 1), "kind": kind, **data})
        if self.echo:
            print(line, flush=True)

    # ------------------------------------------------------------------ events
    def thought(self, role: str, step: int, text: str) -> None:
        self._add("thought", f"[{role} {step}] thinking: {_short(text, 300)}", role=role, step=step, text=text)

    def action(self, role: str, step: int, tool: str, args: dict, result) -> None:
        shown = ", ".join(f"{k}={_short(json.dumps(v, ensure_ascii=False), 70)}" for k, v in args.items())
        status = "ok" if result.ok else "ERROR"
        self._add("action", f"[{role} {step}] {tool}({shown})\n      -> {status}: {_short(result.text)}",
                  role=role, step=step, tool=tool, args=args, ok=result.ok,
                  result=result.text[:2000], evidence=result.evidence)

    def plan(self, steps: list[dict]) -> None:
        lines = "\n".join(f"      [{s['status']:>7}] {s['step']}" for s in steps)
        self._add("plan", f"      plan:\n{lines}", steps=steps)

    def fact(self, key: str, value: str) -> None:
        self._add("fact", f"      remembered {key} = {_short(value, 100)}", key=key, value=value)

    def human(self, question: str, answer: str) -> None:
        self._add("human", f"      human answered: {_short(answer, 200)}", question=question, answer=answer)

    def approval(self, action: str, approved: bool) -> None:
        self._add("approval", f"      write approval {'GRANTED' if approved else 'DENIED'}: {_short(action)}",
                  action=action, approved=approved)

    def note(self, text: str) -> None:
        self._add("note", f"*** {text}", text=text)

    def usage(self, usage: dict) -> None:
        self.tokens["calls"] += 1
        self.tokens["input"] += usage.get("input", 0)
        self.tokens["output"] += usage.get("output", 0)

    # ------------------------------------------------------------------ report
    def write_report(self, outcome: str, result: dict, verification: dict | None, plan: list[dict],
                     facts: dict, transcripts: dict) -> Path:
        duration = round(time.perf_counter() - self._t0)
        report = {
            "task": self.task, "outcome": outcome, "result": result, "verification": verification,
            "plan": plan, "facts": facts, "tokens": self.tokens, "duration_seconds": duration,
            "events": self.events, "transcripts": transcripts,
        }
        (self.dir / "run.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                                           encoding="utf-8")

        md = [f"# AI worker run - {self.started:%Y-%m-%d %H:%M:%S}", "",
              f"**Task:** {self.task}", "",
              f"**Outcome:** {outcome}", "",
              f"**Summary:** {result.get('summary', '')}", ""]
        if result.get("evidence"):
            md += ["**Evidence reported by the worker:**", ""] + [f"- {e}" for e in result["evidence"]] + [""]
        if verification:
            md += [f"## Independent verification: {'PASSED' if verification.get('verified') else 'FAILED'}", "",
                   verification.get("reason", ""), ""] + [f"- {c}" for c in verification.get("checks", [])] + [""]
        if plan:
            md += ["## Final plan", ""] + [f"- [{s['status']}] {s['step']}" for s in plan] + [""]
        if facts:
            md += ["## Facts remembered", ""] + [f"- **{k}:** {v}" for k, v in facts.items()] + [""]
        questions = [e for e in self.events if e["kind"] in ("human", "approval")]
        if questions:
            md += ["## Human interaction", ""]
            for e in questions:
                if e["kind"] == "human":
                    md += [f"- **Q:** {e['question']}  ", f"  **A:** {e['answer']}"]
                else:
                    md += [f"- Write approval {'granted' if e['approved'] else 'denied'}: {e['action']}"]
            md.append("")
        md += ["## Timeline", "", "| Time (s) | Who | Step | Action | Result |", "|---|---|---|---|---|"]
        for e in self.events:
            if e["kind"] != "action":
                continue
            args = ", ".join(f"{k}={_short(json.dumps(v, ensure_ascii=False), 60)}" for k, v in e["args"].items())
            shots = " ".join(f"[screenshot]({Path(p).relative_to(self.dir).as_posix()})" for p in e["evidence"])
            result_text = _short(e["result"], 140).replace("|", "\\|")
            md.append(f"| {e['t']} | {e['role']} | {e['step']} | `{e['tool']}({args.replace('|', '/')})` | "
                      f"{'' if e['ok'] else '**ERROR** '}{result_text} {shots} |")
        md += ["", f"Model calls: {self.tokens['calls']}, tokens in/out: {self.tokens['input']:,} / "
                   f"{self.tokens['output']:,}, duration: {duration} s", ""]
        path = self.dir / "report.md"
        path.write_text("\n".join(md), encoding="utf-8")
        return path
