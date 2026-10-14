"""The agent loop's behaviour, with fake tools and a scripted model."""
import pytest

from worker.agent import Agent
from worker.run_log import RunLog
from worker.tools import Tool, ToolError, ToolResult, params
from worker.tools.human import ScriptedHuman
from worker.tools.state import TaskState, worker_state_tools

from .conftest import ScriptedLLM, last_result

FINISH = ("finish", {"status": "completed", "summary": "done", "evidence": ["saw it"]})


def make_agent(script, tmp_path, extra_tools=(), human=None, **kwargs):
    log = RunLog(tmp_path, "test task", echo=False)
    state = TaskState()
    tools = list(extra_tools) + worker_state_tools(state, log)
    agent = Agent(ScriptedLLM(script), tools, "system prompt", state, log, human or ScriptedHuman(), **kwargs)
    return agent, state, log


def failing_tool():
    def run(x):
        raise ToolError("the portal said no")
    return Tool("flaky", "", params({"x": {"type": "string"}}), run)


def test_finish_ends_the_run(tmp_path):
    agent, state, _ = make_agent([[("update_plan", {"steps": [{"step": "do it", "status": "doing"}]})], [FINISH]],
                                 tmp_path)
    assert agent.run("task")["status"] == "completed"
    assert state.plan == [{"step": "do it", "status": "doing"}]


def test_tool_errors_are_shown_to_the_model(tmp_path):
    seen = []
    script = [[("flaky", {"x": "1"})], lambda m: seen.append(last_result(m)) or [FINISH]]
    agent, _, log = make_agent(script, tmp_path, [failing_tool()])
    agent.run("task")
    assert seen == ["ERROR: the portal said no"]
    assert [e["ok"] for e in log.events if e["kind"] == "action"] == [False, True]


@pytest.mark.parametrize("call, message", [
    (("no_such_tool", {}), "there is no tool called 'no_such_tool'"),
    (("flaky", {"wrong": 1}), "wrong arguments for flaky"),
])
def test_bad_calls_are_reported(tmp_path, call, message):
    seen = []
    agent, _, _ = make_agent([[call], lambda m: seen.append(last_result(m)) or [FINISH]], tmp_path, [failing_tool()])
    agent.run("task")
    assert message in seen[0]


def test_invalid_json_arguments(tmp_path):
    seen = []
    agent, _, _ = make_agent([[("flaky", {})], lambda m: seen.append(last_result(m)) or [FINISH]], tmp_path,
                             [failing_tool()])
    agent.llm.complete = _corrupt_arguments(agent.llm.complete)
    agent.run("task")
    assert "not valid JSON" in seen[0]


def _corrupt_arguments(complete):
    state = {"first": True}

    def wrapper(messages, tools):
        reply = complete(messages, tools)
        if state.pop("first", False):
            reply.tool_calls[0].arguments = "{not json"
        return reply
    return wrapper


def test_unexpected_exceptions_do_not_crash_the_loop(tmp_path):
    boom = Tool("boom", "", params({}), lambda: 1 / 0)
    seen = []
    agent, _, _ = make_agent([[("boom", {})], lambda m: seen.append(last_result(m)) or [FINISH]], tmp_path, [boom])
    assert agent.run("task")["status"] == "completed"
    assert seen[0].startswith("ERROR: ZeroDivisionError")


def test_text_replies_are_nudged_then_given_up(tmp_path):
    agent, _, _ = make_agent(["I think it's done", "Really done", "Done!"], tmp_path)
    result = agent.run("task")
    assert result["status"] == "failed" and "stopped using tools" in result["summary"]


def test_nudge_gets_the_model_back_on_track(tmp_path):
    agent, _, _ = make_agent(["Let me think...", [FINISH]], tmp_path)
    assert agent.run("task")["status"] == "completed"
    assert any(m["role"] == "user" and "without using a tool" in m["content"] for m in agent.messages)


def test_step_limit(tmp_path):
    agent, _, _ = make_agent([[("flaky", {"x": str(i)})] for i in range(5)], tmp_path, [failing_tool()], max_steps=3)
    result = agent.run("task")
    assert result["status"] == "failed" and "step limit" in result["summary"]


def test_repeating_the_same_call_triggers_a_warning(tmp_path):
    seen = []
    script = [[("flaky", {"x": "same"})]] * 3 + [lambda m: seen.append(last_result(m)) or [FINISH]]
    agent, _, _ = make_agent(script, tmp_path, [failing_tool()])
    agent.run("task")
    assert seen[0].startswith("WARNING: you have made exactly this call 3 times")


def test_calls_after_finish_are_skipped(tmp_path):
    ran = []
    noisy = Tool("noisy", "", params({}), lambda: ran.append(1) or "ran")
    agent, _, _ = make_agent([[FINISH, ("noisy", {})]], tmp_path, [noisy])
    agent.run("task")
    assert ran == []
    assert agent.messages[-1]["content"].startswith("Skipped")


def write_tool(calls):
    return Tool("save", "", params({"value": {"type": "string"}}),
                lambda value: calls.append(value) or "saved",
                describe_write=lambda args: f"Save {args['value']}")


def test_confirm_writes_denied(tmp_path):
    calls, seen = [], []
    human = ScriptedHuman(approve_all=False)
    agent, _, log = make_agent([[("save", {"value": "x"})], lambda m: seen.append(last_result(m)) or [FINISH]],
                               tmp_path, [write_tool(calls)], human=human, confirm_writes=True)
    agent.run("task")
    assert calls == [] and seen[0].startswith("DENIED")
    assert human.questions == ["Save x"]
    assert any(e["kind"] == "approval" and not e["approved"] for e in log.events)


def test_confirm_writes_approved(tmp_path):
    calls = []
    agent, _, _ = make_agent([[("save", {"value": "x"})], [FINISH]], tmp_path, [write_tool(calls)],
                             human=ScriptedHuman(approve_all=True), confirm_writes=True)
    agent.run("task")
    assert calls == ["x"]


def test_old_page_snapshots_are_shortened(tmp_path):
    page = Tool("page", "", params({"n": {"type": "string"}}),
                lambda n: ToolResult(f"PAGE /p{n}\n" + "lots of text\n" * 50, is_page=True))
    agent, _, _ = make_agent([[("page", {"n": str(i)})] for i in range(4)] + [[FINISH]], tmp_path, [page])
    agent.run("task")
    pages = [m["content"] for m in agent.messages if m["role"] == "tool" and "/p" in m["content"]]
    assert pages[0] == "[old page snapshot removed to save space] PAGE /p0"
    assert pages[1] == "[old page snapshot removed to save space] PAGE /p1"
    assert pages[3].startswith("PAGE /p3") and "lots of text" in pages[3]


def test_conversation_can_continue(tmp_path):
    agent, _, _ = make_agent([[FINISH], [("finish", {"status": "needs_human", "summary": "stuck", "evidence": []})]],
                             tmp_path)
    assert agent.run("first")["status"] == "completed"
    assert agent.run("reviewer feedback")["status"] == "needs_human"
    assert [m["content"] for m in agent.messages if m["role"] == "user"] == ["first", "reviewer feedback"]
