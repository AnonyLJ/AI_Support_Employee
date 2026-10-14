import pytest

from company_portal.app import create_app

INVOICE = {"invoice_number": "T-100", "vendor": "Test Vendor", "amount": "1,250.50", "currency": "INR",
           "due_date": "2026-12-01"}
PRIYA = {"email": "priya.sharma@example.com", "phone": "+919820022002",
         "address": "45 Park Street, Kolkata 700016", "plan": "standard", "status": "active"}


@pytest.fixture
def client(tmp_path):
    return create_app(tmp_path / "test.db").test_client()


def test_enter_invoice_through_the_form(client):
    response = client.post("/invoices/new", data=INVOICE, follow_redirects=True)
    assert b"Invoice T-100 saved." in response.data
    assert b"INR 1250.50" in response.data
    assert client.get("/api/invoices").json[0]["due_date"] == "2026-12-01"
    assert client.get("/api/audit").json[0]["actor"] == "browser"


def test_invoice_form_explains_errors(client):
    response = client.post("/invoices/new", data={**INVOICE, "amount": "Rs 500", "due_date": "30/11/2026"})
    assert response.status_code == 400
    assert b"Amount must be a plain number" in response.data
    assert b"Due date must be in YYYY-MM-DD format" in response.data
    assert client.get("/api/invoices").json == []


def test_duplicate_invoice_is_refused(client):
    client.post("/invoices/new", data=INVOICE)
    response = client.post("/invoices/new", data=INVOICE)
    assert response.status_code == 409
    assert b"already exists" in response.data
    assert len(client.get("/api/invoices").json) == 1


def test_invoice_search_and_detail(client):
    client.post("/invoices/new", data={**INVOICE, "invoice_number": "AOS/2026/0912"})
    assert b"AOS/2026/0912" in client.get("/invoices?q=AOS").data
    assert b"No invoices found" in client.get("/invoices?q=nothing").data
    assert client.get("/invoices/AOS/2026/0912").status_code == 200
    assert client.get("/invoices/NOPE-1").status_code == 404


def test_edit_customer(client):
    response = client.post("/crm/CUST-1002/edit", data={**PRIYA, "phone": "+91 98765 43210"},
                           follow_redirects=True)
    assert b"Customer CUST-1002 updated: phone." in response.data
    assert client.get("/api/customers/CUST-1002").json["phone"] == "+919876543210"
    audit = client.get("/api/audit").json[0]
    assert audit["record_id"] == "CUST-1002" and "phone" in audit["details"]


def test_edit_customer_validation(client):
    assert client.post("/crm/CUST-1002/edit", data={**PRIYA, "phone": "12345"}).status_code == 400
    taken = client.post("/crm/CUST-1002/edit", data={**PRIYA, "email": "rohan.gupta@example.com"})
    assert taken.status_code == 400 and b"belongs to another customer" in taken.data
    assert client.get("/api/customers/CUST-1002").json["email"] == "priya.sharma@example.com"


def test_crm_search_and_unknown_customer(client):
    page = client.get("/crm?q=rahul").data
    assert b"CUST-1007" in page and b"CUST-1008" in page and b"CUST-1002" not in page
    assert client.get("/crm/CUST-9999").status_code == 404


def test_chaos_mode_breaks_pages_but_not_the_test_api(tmp_path):
    client = create_app(tmp_path / "chaos.db", failure_rate=1.0, seed=1).test_client()
    assert client.get("/invoices").status_code == 503
    assert b"503 Service Temporarily Unavailable" in client.get("/crm").data
    assert client.get("/api/health").status_code == 200


def test_chaos_can_fail_after_saving(tmp_path):
    client = create_app(tmp_path / "chaos.db", failure_rate=1.0, seed=3).test_client()
    statuses = [client.post("/invoices/new", data={**INVOICE, "invoice_number": f"T-{i}00"}).status_code
                for i in range(1, 9)]
    assert set(statuses) == {503}
    saved = client.get("/api/invoices").json
    assert 0 < len(saved) < 8  # some "failed" submissions were actually saved
