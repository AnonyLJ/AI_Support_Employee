"""Browser tool against the real portal in a real (headless) Chromium."""
import pytest
import requests

from worker.tools import ToolError
from worker.tools.browser import Browser

from .conftest import ref


@pytest.fixture
def browser(portal_url, tmp_path):
    b = Browser([portal_url], screenshot_dir=tmp_path / "shots")
    yield b
    b.close()


def test_snapshot_lists_elements_with_refs(browser, portal_url):
    page = browser.open_url("/invoices/new").text
    assert page.startswith(f"PAGE {portal_url}/invoices/new  (HTTP 200)")
    assert 'textbox "Invoice number" value=""' in page
    assert 'dropdown "Currency" selected="INR" options=[EUR, GBP, INR, USD]' in page
    assert 'button "Save invoice" (submits form)' in page


def test_fill_and_submit_a_form(browser, portal_url):
    page = browser.open_url(f"{portal_url}/invoices/new").text
    filled = browser.fill_form([
        {"ref": ref(page, "Invoice number"), "value": "KE-1"},
        {"ref": ref(page, "Amount payable"), "value": "500"},
        {"ref": ref(page, "Currency"), "value": "USD"},
        {"ref": ref(page, "Due date"), "value": "2026-12-01"},
    ]).text
    assert "'KE-1'" in filled and "'USD'" in filled

    preview = browser.describe_submission(ref(page, "Save invoice"))
    assert preview.startswith("Submit form to /invoices/new") and 'invoice_number="KE-1"' in preview

    result = browser.click(ref(page, "Save invoice"))
    assert "Invoice KE-1 saved." in result.text and "USD 500.00" in result.text
    assert result.evidence and result.evidence[0].endswith(".png")
    saved = requests.get(f"{portal_url}/api/invoices").json()[0]
    assert (saved["invoice_number"], saved["currency"]) == ("KE-1", "USD")
    assert requests.get(f"{portal_url}/api/audit").json()[0]["actor"] == "ai-worker"


def test_links_are_not_submissions(browser):
    page = browser.open_url("/invoices").text
    assert browser.describe_submission(ref(page, "+ Enter a new invoice")) is None


def test_stale_ref_gives_a_helpful_error(browser):
    browser.open_url("/invoices")
    with pytest.raises(ToolError, match="Call read_page"):
        browser.click("e999")


def test_other_websites_are_blocked(browser):
    with pytest.raises(ToolError, match="Not allowed"):
        browser.open_url("https://example.com")


def test_bad_dropdown_value(browser):
    page = browser.open_url("/invoices/new").text
    with pytest.raises(ToolError, match="Could not set"):
        browser.fill_form([{"ref": ref(page, "Currency"), "value": "BITCOIN"}])


def test_error_pages_show_their_status(start_portal, tmp_path):
    url = start_portal(failure_rate=1.0, seed=1)
    browser = Browser([url])
    try:
        page = browser.open_url("/invoices").text
        assert "(HTTP 503)" in page and "Service Temporarily Unavailable" in page
    finally:
        browser.close()
