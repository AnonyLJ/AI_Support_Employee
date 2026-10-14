import pytest

from worker.runner import PROJECT_ROOT
from worker.tools import ToolError
from worker.tools.files import Workspace


@pytest.fixture
def ws():
    return Workspace(PROJECT_ROOT / "workspace")


def test_list_and_read(ws):
    listing = ws.list_files("inbox")
    assert "inbox/invoices/kaveri_electricals_oct.txt" in listing
    assert "inbox/customer_requests/req_03_phone_update.txt" in listing
    assert "Total Amount Payable" in ws.read_file("inbox/invoices/kaveri_electricals_oct.txt")


def test_read_pdf(ws):
    assert "CN-INV-7781" in ws.read_file("inbox/invoices/cloudnine_hosting_sep.pdf")


def test_cannot_escape_the_shared_drive(ws):
    for path in ("../README.md", "/etc/passwd", "inbox/../../worker/agent.py"):
        with pytest.raises(ToolError, match="outside the shared drive"):
            ws.read_file(path)


def test_missing_file(ws):
    with pytest.raises(ToolError, match="does not exist"):
        ws.read_file("inbox/nope.txt")


def test_writes_only_go_to_outbox(tmp_path):
    (tmp_path / "inbox").mkdir()
    ws = Workspace(tmp_path)
    assert "Saved" in ws.write_file("outbox/premium.csv", "name,email\n")
    assert (tmp_path / "outbox" / "premium.csv").exists()
    with pytest.raises(ToolError, match="only write inside 'outbox/'"):
        ws.write_file("inbox/evil.txt", "x")
