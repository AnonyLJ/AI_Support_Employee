"""Browser tools: the worker operates web applications through a real Chromium browser.

The model cannot see pixels, so every page is turned into a text "snapshot":
the visible text plus a numbered list of interactive elements, e.g.

    [e7] textbox "Invoice number" value=""
    [e12] button "Save invoice" (submits form)

The model then acts with click("e12") or fill_form([{"ref": "e7", "value": "KE-1"}]).
A screenshot is saved after every navigation as evidence for the run report.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

from . import Tool, ToolError, ToolResult, params

MAX_TEXT = 4_000
ACTION_TIMEOUT_MS = 5_000

# Tags every interactive element with data-ref="eN" and describes it in one line.
SNAPSHOT_JS = r"""
() => {
  document.querySelectorAll('[data-ref]').forEach(e => e.removeAttribute('data-ref'));
  const items = [];
  let n = 0;
  for (const el of document.querySelectorAll('a[href], button, input, select, textarea')) {
    if (el.type === 'hidden') continue;
    const box = el.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) continue;
    const ref = 'e' + (++n);
    el.setAttribute('data-ref', ref);
    const tag = el.tagName.toLowerCase();
    let label = (el.labels && el.labels[0] ? el.labels[0].innerText : '') || el.getAttribute('aria-label')
                || el.getAttribute('placeholder') || el.innerText || el.value || el.name || '';
    label = label.trim().replace(/\s+/g, ' ').slice(0, 80);
    let kind, extra = '';
    if (tag === 'a') { kind = 'link'; extra = ' -> ' + el.getAttribute('href'); }
    else if (tag === 'button' || (tag === 'input' && ['submit', 'button'].includes(el.type))) {
      kind = 'button';
      if (el.form && el.type === 'submit') extra = ' (submits form)';
    } else if (tag === 'select') {
      kind = 'dropdown';
      extra = ' selected="' + el.value + '" options=[' + Array.from(el.options).map(o => o.value).join(', ') + ']';
    } else { kind = tag === 'textarea' ? 'textarea' : 'textbox'; extra = ' value="' + el.value + '"'; }
    items.push('[' + ref + '] ' + kind + ' "' + label + '"' + extra);
  }
  return items;
}
"""

# For --confirm-writes: if the element submits a form, describe what would be sent.
SUBMISSION_JS = r"""
(el) => {
  const isSubmit = (el.tagName === 'BUTTON' || el.tagName === 'INPUT') && el.type === 'submit' && el.form;
  if (!isSubmit || (el.form.method || 'get').toLowerCase() !== 'post') return null;
  const fields = Array.from(new FormData(el.form).entries()).map(([k, v]) => k + '=' + JSON.stringify(v));
  return 'Submit form to ' + new URL(el.form.action).pathname + ' with ' + fields.join(', ');
}
"""


class Browser:
    def __init__(self, allowed_prefixes: list[str], headless: bool = True, slow_mo: int = 0,
                 screenshot_dir: Path | None = None):
        self.allowed_prefixes = [p.rstrip("/") for p in allowed_prefixes]
        self.headless = headless
        self.slow_mo = slow_mo
        self.screenshot_dir = screenshot_dir
        self.last_status: int | None = None
        self._playwright = self._browser = self._page = None
        self._shots = 0

    # ------------------------------------------------------------------ lifecycle
    @property
    def page(self):
        if self._page is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=self.headless, slow_mo=self.slow_mo)
            context = self._browser.new_context(extra_http_headers={"X-Actor": "ai-worker"},
                                                viewport={"width": 1280, "height": 900})
            self._page = context.new_page()
            self._page.on("response", self._track_status)
        return self._page

    def _track_status(self, response) -> None:
        if response.request.is_navigation_request() and response.frame == self._page.main_frame:
            self.last_status = response.status

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._playwright = self._browser = self._page = None

    # ------------------------------------------------------------------ helpers
    def _check_allowed(self, url: str) -> str:
        if not re.match(r"^https?://", url):
            url = urljoin(self.allowed_prefixes[0] + "/", url.lstrip("/"))  # allow "/invoices" style paths
        if not any(url == p or url.startswith(p + "/") or url.startswith(p + "?") for p in self.allowed_prefixes):
            raise ToolError(f"Not allowed to open {url}. You may only use: {', '.join(self.allowed_prefixes)}")
        return url

    def _locate(self, ref: str):
        locator = self.page.locator(f'[data-ref="{ref}"]')
        if locator.count() == 0:
            raise ToolError(f"Element {ref} is not on the current page (the page may have changed). "
                            f"Call read_page to get fresh element references.")
        return locator.first

    def _screenshot(self) -> list[str]:
        if not self.screenshot_dir:
            return []
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._shots += 1
        slug = re.sub(r"[^a-z0-9]+", "_", self.page.url.split("//", 1)[-1].lower()).strip("_")[:60]
        path = self.screenshot_dir / f"{self._shots:03d}_{slug}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return [str(path)]

    def snapshot(self) -> str:
        page = self.page
        elements = page.evaluate(SNAPSHOT_JS)
        text = page.inner_text("body").strip()
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n... [page text truncated]"
        return (f"PAGE {page.url}  (HTTP {self.last_status})\nTitle: {page.title()}\n"
                f"--- visible text ---\n{text}\n"
                f"--- interactive elements (use the [ref] with click / fill_form) ---\n" + "\n".join(elements))

    # ------------------------------------------------------------------ tool actions
    def open_url(self, url: str) -> ToolResult:
        url = self._check_allowed(url)
        try:
            self.page.goto(url, wait_until="load", timeout=15_000)
        except Exception as exc:  # timeouts, connection refused, ...
            raise ToolError(f"Could not open {url}: {str(exc).splitlines()[0]}") from exc
        return ToolResult(self.snapshot(), evidence=self._screenshot(), is_page=True)

    def read_page(self) -> ToolResult:
        if self._page is None:
            raise ToolError("No page is open yet. Use open_url first.")
        return ToolResult(self.snapshot(), is_page=True)

    def click(self, ref: str) -> ToolResult:
        element = self._locate(ref)
        href = element.get_attribute("href")
        if href:
            self._check_allowed(urljoin(self.page.url, href))
        try:
            element.click(timeout=ACTION_TIMEOUT_MS)
            self.page.wait_for_load_state("load", timeout=15_000)
        except Exception as exc:
            raise ToolError(f"Clicking {ref} failed: {str(exc).splitlines()[0]}") from exc
        return ToolResult(self.snapshot(), evidence=self._screenshot(), is_page=True)

    def fill_form(self, fields: list[dict]) -> ToolResult:
        done = []
        for item in fields:
            ref, value = item.get("ref", ""), str(item.get("value", ""))
            element = self._locate(ref)
            try:
                if element.evaluate("e => e.tagName") == "SELECT":
                    element.select_option(value, timeout=ACTION_TIMEOUT_MS)
                else:
                    element.fill(value, timeout=ACTION_TIMEOUT_MS)
            except Exception as exc:
                raise ToolError(f"Could not set {ref} to {value!r}: {str(exc).splitlines()[0]}. "
                                f"Fields set before this one: {done or 'none'}") from exc
            done.append(f"{ref}={element.input_value()!r}")  # read back what the field now contains
        return ToolResult("Fields now contain: " + ", ".join(done) + ". Nothing is saved until the form is submitted.")

    def describe_submission(self, ref: str) -> str | None:
        locator = self.page.locator(f'[data-ref="{ref}"]')
        return locator.first.evaluate(SUBMISSION_JS) if locator.count() else None


def browser_tools(browser: Browser, read_only: bool = False) -> list[Tool]:
    tools = [
        Tool("open_url", "Open a page of the company portal in the browser and return a snapshot of it. "
                         "Accepts a full URL or a path such as '/invoices?q=KE-2026'.",
             params({"url": {"type": "string"}}), browser.open_url),
        Tool("read_page", "Return a fresh snapshot of the current page (text + interactive elements with refs).",
             params({}), browser.read_page),
    ]
    if not read_only:
        tools += [
            Tool("click", "Click a link or button by its ref (e.g. 'e12') and return the resulting page.",
                 params({"ref": {"type": "string"}}), browser.click,
                 describe_write=lambda args: browser.describe_submission(args.get("ref", ""))),
            Tool("fill_form", "Type into text fields and choose dropdown options. Does not submit the form.",
                 params({"fields": {"type": "array", "items": params({"ref": {"type": "string"},
                                                                     "value": {"type": "string"}})}}),
                 browser.fill_form),
        ]
    return tools
