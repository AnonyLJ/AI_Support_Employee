# Autonomous AI Task Worker

A prototype AI worker that takes a task in plain language and completes it on a computer. It reads files, operates a company web application in a real browser, asks a person when it must, checks its own work, and returns a summary with evidence.

```
python -m worker "Find the latest invoice from Kaveri Electricals, extract the amount and due date,
                  enter it into our invoice system, and tell me once it is done."
```

The worker is never told the steps. It works out that it should:
1. list the invoice folder;
2. read both Kaveri invoices and pick the newer one;
3. notice that the handbook requires finance approval above ₹1,00,000 and ask for it;
4. search the Invoice System to avoid a duplicate;
5. fill in and submit the form;
6. open the saved record to check it.

A separate reviewer agent then independently confirms the result before the user is told it is done.

The same code, unchanged, handles other tasks, such as "Process the customer request from Priya Sharma" or "Save a list of our premium customers as a CSV".

---

## Quick start

Requires Python 3.10+ and an OpenAI API key.

```powershell
python -m venv .venv
.venv\Scripts\activate                       # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium        # the browser the worker uses (~150 MB)

$env:OPENAI_API_KEY = "sk-..."               # macOS/Linux: export OPENAI_API_KEY=sk-...
```

Terminal 1: start the simulated company application:

```powershell
python -m company_portal --reset                       # http://127.0.0.1:5050
python -m company_portal --reset --failure-rate 0.3    # or: 30% of pages randomly fail (chaos mode)
```

Terminal 2: give the worker a task:

```powershell
python -m worker "Find the latest invoice from Kaveri Electricals, extract the amount and due date, enter it into our invoice system, and tell me once it is done."
python -m worker --headed --slow-mo 300 "..."   # watch the browser
python -m worker                                # it asks you for the task
```

Every run writes `runs/<timestamp>/report.md` containing the outcome, the plan, remembered facts, the human Q&A, the verifier's checks, and a timeline with a screenshot after every page change. `run.json` alongside it has the full model conversation.

| Option | Effect |
|---|---|
| `--model` | OpenAI model (default `gpt-5.4-mini`, or set `OPENAI_MODEL`) |
| `--headed`, `--slow-mo N` | Show the browser and slow it down, useful for demo videos |
| `--confirm-writes` | Ask the human before every form submission or file write |
| `--unattended` | No human available: the worker stops with `needs_human` instead of waiting |
| `--no-verify` | Skip the independent verification step |
| `--max-steps N` | Hard limit on model turns (default 40) |

Exit code: `0` = completed, `2` = needs a human, `1` = failed or not confirmed.

### Tasks to try (and for the demo video)

| Task | What it shows |
|---|---|
| *Find the latest invoice from Kaveri Electricals, extract the amount and due date, enter it into our invoice system, and tell me once it is done.* | Choosing between two invoices, a policy-required approval (amount > ₹1 lakh), duplicate check, form filling, self-check, independent verification |
| *Enter the BlueStar Logistics invoice into the invoice system.* | Due date is not printed (only "Net 30"), so the worker must calculate it |
| *Enter the CloudNine Hosting invoice.* | Reading a PDF; a USD invoice |
| *Process the customer request from Priya Sharma.* | Same system, different workflow: CRM update with an identity check |
| *Handle the customer request about a phone number for CUST-1004.* | The sender is not the account owner. The worker should refuse and escalate, not update. |
| *Deal with Vikram Singh's billing question.* | Not something it may do. It should escalate with a summary. |
| *Which customers are on the premium plan? Save their names and emails to a CSV for me.* | A task nobody designed for: reading the CRM and writing a file |
| Any invoice task with the portal in `--failure-rate 0.3` | Recovering from 503 errors, including saves that worked but reported failure |

---

## Architecture

```
                 user task (plain language)
                            │
                            ▼
┌───────────────────────── worker/runner.py ─────────────────────────┐
│                                                                    │
│  WORKER agent (agent.py)      system prompt = how to work +        │
│                               company handbook (workspace/)        │
│    ┌──────────────────────────────────────────────────────┐        │
│    │ model decides next action(s) ──► harness runs tools   │        │
│    │        ▲                                │             │        │
│    │        └──── observation / error ◄──────┘             │        │
│    └──────────────────────────────────────────────────────┘        │
│        │ finish(completed)                                         │
│        ▼                                                           │
│  VERIFIER agent: same loop, read-only tools, fresh context         │
│        │ verdict = false ──► findings go back to the worker (once) │
│        ▼                                                           │
│  run report + screenshots (run_log.py)                             │
└────────────────────────────────────────────────────────────────────┘
        │ tools (worker/tools/)
        ├── files    list_files, read_file (txt/PDF), write_file (outbox/ only)
        ├── browser  open_url, read_page, click, fill_form   (Playwright + Chromium)
        ├── human    ask_human
        └── state    update_plan, remember, finish
                            │
                            ▼
  company_portal/ - simulated internal web app (Flask + SQLite):
  Invoice System, CRM, audit log, chaos mode
  workspace/      - simulated shared drive: invoices, customer emails, company handbook
```

| Path | What it is |
|---|---|
| `worker/agent.py` | The task-independent agent loop and its safety rails |
| `worker/runner.py` | Runs one task: worker → verifier → one fix-up round → report |
| `worker/prompts.py` | Worker and verifier system prompts (no task-specific content) |
| `worker/llm.py` | OpenAI adapter, the only file that knows about OpenAI |
| `worker/tools/` | The tools: files, browser, human, plan/memory/finish |
| `worker/run_log.py` | Live console output and the run report |
| `company_portal/` | The simulated company application the worker operates |
| `workspace/` | The shared drive: `inbox/` documents, `outbox/` for results, `company_handbook.md` |
| `tests/` | 43 tests, including full runs through the real browser |

### How each requirement is met

| The brief asks for… | How |
|---|---|
| Understanding the end goal | The worker gets only the user's sentence plus the company handbook. Nothing about the task is hard-coded. |
| Breaking the request into actions | The worker writes an explicit plan with `update_plan` before acting and revises it. The plan is shown live and saved in the report. |
| Using tools (browser, files, apps) | Generic tools: a real Chromium browser via Playwright, a sandboxed file drive, a human channel |
| Observing each result | Every tool returns an observation: a page snapshot with HTTP status, file contents, or an error message |
| Deciding the next step from what happened | The model chooses each next action after seeing the previous result (no fixed sequence) |
| Remembering what it discovered | `remember` keeps key facts; they go into the report and are handed to the verifier. Old page snapshots are trimmed so long tasks fit in context. |
| Detecting failures | HTTP status on every page, form validation messages, tool errors returned as `ERROR: ...`, a repeated-action guard |
| Retrying / alternatives | The model gets the error and adapts. The prompt requires checking whether a failed save actually happened before resubmitting (chaos mode tests exactly this). |
| Verifying the outcome | Twice: the worker re-opens the saved record, then an independent read-only reviewer agent checks the systems itself. A failed check goes back to the worker for one more attempt. |
| Asking for clarification / approval | `ask_human`, driven by the handbook's policies (finance approval, account closure, identity mismatch). Optional `--confirm-writes` gate enforced by the harness on every submission. |
| Summary and evidence | `finish` requires a summary and observed evidence. The report adds screenshots, a timeline, Q&A and the verifier's checks. |

---

## Design decisions

- **One generic loop instead of scripted workflows.** The loop, tools and prompts contain nothing about invoices or customers. Company-specific knowledge lives in `workspace/company_handbook.md` as plain text that a business person could edit. This is what makes it generalize: a new task needs no code; a new company needs a new handbook; a new web app works with the same browser tools.
- **A real browser, not the app's API.** Internal tools often have no API, and the brief is about using a computer. The worker sees each page as text plus numbered elements (`[e7] textbox "Invoice number"`), which is cheaper and more reliable than screenshots for a text model. Screenshots are still saved, as evidence for humans.
- **Independent verification by a second agent.** The worker grading its own work is weak evidence. The verifier starts with a fresh context and read-only tools (it cannot "fix" things to make them look right), and only sees the worker's claims as claims.
- **Policies are enforced by the model, with a harness backstop.** Approvals that depend on meaning (e.g. "above ₹1 lakh") come from the handbook, and the model asks via `ask_human`. Rules that must never depend on the model are enforced in code:
  - file writes only in `outbox/`;
  - the browser can only open the company portal;
  - optional approval of every form submission (`--confirm-writes`);
  - a step limit.
- **Errors are information, not crashes.** Every tool failure (unknown element, validation error, timeout, even a bug) is returned to the model as text so it can adapt, and is logged. The run always ends with a report.
- **Explicit plan and memory tools.** They make the agent's reasoning visible to the user and the reviewer, and they survive context trimming.
- **Small, dependency-light stack.** No agent framework. The loop is about 150 lines, so every decision in it can be explained and debugged.

## Reliability and safety measures

- OpenAI SDK retries for network errors, 429 and 5xx; clear messages for bad keys or unknown models.
- Chaos mode in the portal: random 503 pages, and saves that succeed but report a failure (the hardest case for duplicates).
- Duplicate protection: the handbook requires searching first, the portal rejects duplicate invoice numbers, and the verifier checks for duplicates.
- Repeated-action guard (warns the model after 3 identical calls), a nudge when the model talks without acting, and a hard step limit.
- Sandboxes: files restricted to `workspace/`, writes to `outbox/`, browser restricted to the portal URL.
- `--unattended` mode: the worker cannot proceed past a needed approval and stops with `needs_human`.
- Audit trail: the portal logs every change with `actor = ai-worker`, and each run has its own report.

## Tests

```powershell
pytest          # 43 tests, ~30 s; needs Chromium but no API key
```

Without an API key, tests use a **scripted model** that plays the model's part. Everything else is real: the agent loop, a real headless Chromium, the real portal over HTTP, the verifier and the report. The tests cover:
- the full invoice task, including approval and verification;
- a CRM update;
- the verifier catching a false "done" and the worker getting a second chance;
- unattended stops and model errors;
- every safety rail in the loop: errors, bad arguments, repeats, step limit, write approval, context trimming;
- the browser tool (refs, forms, dropdowns, blocked sites, 503 pages);
- the file sandbox;
- the portal itself, including chaos mode.

The scripted tests prove the system works mechanically. How well the *real* model plans is measured by running the example tasks above with a key.

## Models, APIs and libraries

| Component | Used for |
|---|---|
| OpenAI API, Chat Completions with function calling; default model `gpt-5.4-mini` (any tool-calling model works via `--model`) | All reasoning: planning, choosing tools, reading documents, verification |
| Playwright for Python + Chromium | Browser automation |
| Flask + SQLite | The simulated company portal |
| pypdf | Reading PDF invoices |
| pytest | Tests |

No agent framework and no external services other than the OpenAI API. The sample company, people, invoices and emails are fictional.

## Assumptions

- The company's systems are web apps the worker can reach, simulated here by `company_portal`. Documents arrive on a shared drive, simulated by `workspace/inbox/`.
- "Latest invoice" means the newest invoice date printed on the document, not the file's timestamp.
- The person running the worker is the approver for anything the handbook says needs approval.
- Text-based PDFs only; dates use the Indian day-first convention when written as `dd/mm/yyyy`.

## Known limitations

- The model sees pages as text, not pixels. Canvas-heavy apps, CAPTCHAs and visual-only cues would need screenshot-based computer use.
- No login or sessions in the portal, no desktop (non-browser) applications, no OCR for scanned PDFs.
- Approvals are interactive in the terminal only. Unattended runs stop rather than queue an approval request.
- No memory across runs: each task starts fresh apart from the handbook.
- Uses Chat Completions. With reasoning models the hidden reasoning is not carried between turns. The Responses API would keep it. GPT-6 models support function calling only through the Responses API, so use GPT-5.x models with `--model` for now.
- Quality depends on the model. Small models can mis-read long pages. The step limit, verifier and `--confirm-writes` bound the damage, but do not make mistakes impossible.

## What I would build next

1. **Approval queue**: unattended runs park the task with a pending approval (web page or Slack), then resume when someone approves.
2. **Learning from runs**: save successful procedures ("to enter an invoice: …") and corrections from reviewers, and retrieve them for similar tasks.
3. **Vision fallback**: send a screenshot when the text snapshot is not enough (charts, unlabeled icons).
4. **More tools**: an email inbox, spreadsheets, desktop apps via OS automation, and authenticated sessions with secrets kept out of the model's view.
5. **Evaluation harness**: a set of tasks with automatic checks against the portal database, run against each model or prompt change to track success rate, cost and steps.
6. **Responses API** with server-side reasoning state, and streaming output in a small web UI.
