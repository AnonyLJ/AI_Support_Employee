"""Full runs through run_task(): worker -> real browser -> portal -> independent verifier -> report.

The model is scripted (no API key needed), so these tests check the system's
plumbing and safety behaviour, not the real model's judgement.
"""
import requests

from worker.llm import LLMError
from worker.runner import Settings, run_task
from worker.tools.human import NoHuman, ScriptedHuman

from .conftest import ScriptedLLM, last_result, ref

INVOICE_TASK = ("Find the latest invoice from Kaveri Electricals, extract the amount and due date, "
                "enter it into our invoice system, and tell me once it is done.")


def last_page(messages) -> str:
    return next(m["content"] for m in reversed(messages) if m["role"] == "tool" and m["content"].startswith("PAGE"))


def settings_for(url, tmp_path, **kwargs) -> Settings:
    return Settings(portal_url=url, runs_dir=tmp_path / "runs", **kwargs)


def finish(status="completed", summary="Done.", evidence=("checked",)):
    return [("finish", {"status": status, "summary": summary, "evidence": list(evidence)})]


def verdict(ok, reason="ok"):
    return [("submit_verdict", {"verified": ok, "reason": reason, "checks": ["looked at the record"]})]


def test_invoice_task_end_to_end(portal_url, tmp_path):
    def expect(text, then):
        def step(messages):
            assert text in last_result(messages), last_result(messages)
            return then(messages) if callable(then) else then
        return step

    script = [
        # --- worker ---
        [("update_plan", {"steps": [{"step": "Find the latest Kaveri invoice", "status": "doing"},
                                    {"step": "Get approval (amount > 1 lakh)", "status": "todo"},
                                    {"step": "Enter and check it", "status": "todo"}]})],
        [("list_files", {"path": "inbox/invoices"})],
        [("read_file", {"path": "inbox/invoices/kaveri_electricals_aug.txt"}),   # two calls in one turn
         ("read_file", {"path": "inbox/invoices/kaveri_electricals_oct.txt"})],
        [("remember", {"key": "invoice_number", "value": "KE-2026-1045"}),
         ("remember", {"key": "amount", "value": "INR 102070.00, due 2026-11-07"})],
        [("ask_human", {"question": "Approve entering KE-2026-1045 from Kaveri Electricals, INR 1,02,070.00, "
                                    "due 2026-11-07?"})],
        expect("Human answered: Yes", [("open_url", {"url": "/invoices?q=KE-2026-1045"})]),
        expect("No invoices found", [("open_url", {"url": "/invoices/new"})]),
        lambda m: [("fill_form", {"fields": [
            {"ref": ref(last_page(m), "Invoice number"), "value": "KE-2026-1045"},
            {"ref": ref(last_page(m), "Vendor"), "value": "Kaveri Electricals"},
            {"ref": ref(last_page(m), "Amount payable"), "value": "102070.00"},
            {"ref": ref(last_page(m), "Currency"), "value": "INR"},
            {"ref": ref(last_page(m), "Due date"), "value": "2026-11-07"}]})],
        lambda m: [("click", {"ref": ref(last_page(m), "Save invoice")})],
        expect("Invoice KE-2026-1045 saved.", finish(summary="Entered KE-2026-1045 (INR 1,02,070.00, due 2026-11-07).",
                                                     evidence=["/invoices/KE-2026-1045 shows INR 102070.00"])),
        # --- independent verifier ---
        [("open_url", {"url": "/invoices/KE-2026-1045"})],
        expect("INR 102070.00", verdict(True, "Invoice saved once with the right amount and due date")),
    ]
    human = ScriptedHuman(["Yes, approved."])
    outcome = run_task(INVOICE_TASK, settings_for(portal_url, tmp_path), ScriptedLLM(script), human, echo=False)

    assert outcome.status == "verified" and outcome.exit_code == 0
    assert "KE-2026-1045" in human.questions[0]
    [saved] = requests.get(f"{portal_url}/api/invoices").json()
    assert (saved["amount"], saved["due_date"], saved["vendor"]) == ("102070.00", "2026-11-07", "Kaveri Electricals")
    assert requests.get(f"{portal_url}/api/audit").json()[0]["actor"] == "ai-worker"

    report = outcome.report_path.read_text(encoding="utf-8")
    assert "COMPLETED - independently verified" in report
    assert "Approve entering KE-2026-1045" in report and "invoice_number:** KE-2026-1045" in report
    shots = list((outcome.report_path.parent / "screens").glob("*.png"))
    assert len(shots) >= 4 and "](screens/" in report
    assert (outcome.report_path.parent / "run.json").exists()


def test_customer_request_end_to_end(portal_url, tmp_path):
    """A different task through the same, unchanged system: update a phone number in the CRM."""
    script = [
        [("read_file", {"path": "inbox/customer_requests/req_03_phone_update.txt"})],
        [("open_url", {"url": "/crm/CUST-1002"})],
        lambda m: (assert_in("priya.sharma@example.com", last_result(m)), [("open_url", {"url": "/crm/CUST-1002/edit"})])[1],
        lambda m: [("fill_form", {"fields": [{"ref": ref(last_page(m), "Phone"), "value": "+919876543210"}]})],
        lambda m: [("click", {"ref": ref(last_page(m), "Save changes")})],
        lambda m: (assert_in("updated: phone", last_result(m)), finish(summary="Updated Priya's phone."))[1],
        [("open_url", {"url": "/crm/CUST-1002"})],
        verdict(True),
    ]
    outcome = run_task("Process the customer request from Priya Sharma.", settings_for(portal_url, tmp_path),
                       ScriptedLLM(script), ScriptedHuman(), echo=False)
    assert outcome.status == "verified"
    customer = requests.get(f"{portal_url}/api/customers/CUST-1002").json()
    assert customer["phone"] == "+919876543210" and customer["email"] == "priya.sharma@example.com"


def assert_in(text, content):
    assert text in content, content


def test_reviewer_catches_a_false_claim_and_worker_gets_a_second_chance(portal_url, tmp_path):
    feedback = []
    script = [
        finish(),                                                           # worker claims success
        verdict(False, "Invoice KE-2026-1045 is not in the system"),        # reviewer disagrees
        lambda m: feedback.append(m[-1]["content"]) or finish("needs_human", "I could not enter it."),
    ]
    outcome = run_task(INVOICE_TASK, settings_for(portal_url, tmp_path), ScriptedLLM(script), ScriptedHuman(),
                       echo=False)
    assert "could NOT confirm" in feedback[0] and "not in the system" in feedback[0]
    assert outcome.status == "needs_human" and outcome.exit_code == 2


def test_still_unconfirmed_after_second_attempt(portal_url, tmp_path):
    script = [finish(), verdict(False, "nope"), finish(), verdict(False, "still nope")]
    outcome = run_task(INVOICE_TASK, settings_for(portal_url, tmp_path), ScriptedLLM(script), ScriptedHuman(),
                       echo=False)
    assert outcome.status == "unverified" and outcome.exit_code == 1
    assert "NOT CONFIRMED" in outcome.report_path.read_text(encoding="utf-8")


def test_unattended_run_stops_when_it_needs_a_person(portal_url, tmp_path):
    answers = []
    script = [
        [("ask_human", {"question": "Approve this INR 1,02,070 invoice?"})],
        lambda m: answers.append(last_result(m)) or finish("needs_human", "Waiting for finance approval."),
    ]
    outcome = run_task(INVOICE_TASK, settings_for(portal_url, tmp_path), ScriptedLLM(script), NoHuman(), echo=False)
    assert "NO HUMAN AVAILABLE" in answers[0]
    assert outcome.status == "needs_human" and outcome.verification is None


def test_verification_can_be_switched_off(portal_url, tmp_path):
    outcome = run_task(INVOICE_TASK, settings_for(portal_url, tmp_path, verify=False), ScriptedLLM([finish()]),
                       ScriptedHuman(), echo=False)
    assert outcome.status == "completed" and outcome.verification is None


def test_model_errors_end_the_run_with_a_report(portal_url, tmp_path):
    class BrokenLLM:
        def complete(self, messages, tools):
            raise LLMError("OpenAI rejected the API key.")

    outcome = run_task(INVOICE_TASK, settings_for(portal_url, tmp_path), BrokenLLM(), ScriptedHuman(), echo=False)
    assert outcome.status == "failed"
    assert "rejected the API key" in outcome.report_path.read_text(encoding="utf-8")
