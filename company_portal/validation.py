"""Form validation for the Invoice System and the CRM.

Each function returns (clean_data, errors). Error messages are written for the
person (or AI worker) filling in the form, so they say how to fix the problem.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

CURRENCIES = {"INR", "USD", "EUR", "GBP"}
PLANS = {"basic", "standard", "premium"}
STATUSES = {"active", "inactive"}
CUSTOMER_FIELDS = {"email", "phone", "address", "plan", "status"}

INVOICE_NUMBER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/]{2,39}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?\d{10,15}$")


def validate_invoice(payload: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    clean: dict = {}

    number = str(payload.get("invoice_number") or "").strip()
    if not INVOICE_NUMBER_RE.match(number):
        errors.append("Invoice number is required (3-40 characters: letters, digits, '-' or '/').")
    clean["invoice_number"] = number

    raw_amount = str(payload.get("amount", "")).replace(",", "").strip()
    try:
        amount = Decimal(raw_amount)
        if amount <= 0 or amount >= Decimal("1e10"):
            errors.append("Amount must be greater than 0.")
        elif amount.as_tuple().exponent < -2:
            errors.append("Amount can have at most 2 decimal places.")
        clean["amount"] = f"{amount:.2f}"
    except InvalidOperation:
        errors.append(f"Amount must be a plain number such as 102070.00 (got '{raw_amount}').")

    currency = str(payload.get("currency") or "INR").strip().upper()
    if currency not in CURRENCIES:
        errors.append(f"Currency must be one of {', '.join(sorted(CURRENCIES))}.")
    clean["currency"] = currency

    raw_due = str(payload.get("due_date", "")).strip()
    try:
        clean["due_date"] = date.fromisoformat(raw_due).isoformat()
    except ValueError:
        errors.append(f"Due date must be in YYYY-MM-DD format, e.g. 2026-11-07 (got '{raw_due}').")

    clean["vendor"] = str(payload.get("vendor") or "").strip() or None
    clean["source_file"] = str(payload.get("source_file") or "").strip() or None
    if clean["vendor"] and len(clean["vendor"]) > 200:
        errors.append("Vendor must be at most 200 characters.")

    return clean, errors


def validate_customer_update(payload: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    clean: dict = {}

    unknown = set(payload) - CUSTOMER_FIELDS
    if unknown:
        errors.append(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    if not set(payload) & CUSTOMER_FIELDS:
        errors.append(f"Nothing to update; editable fields are {', '.join(sorted(CUSTOMER_FIELDS))}.")

    if "email" in payload:
        email = str(payload["email"]).strip().lower()
        if not EMAIL_RE.match(email):
            errors.append(f"Email address '{email}' is not valid.")
        clean["email"] = email
    if "phone" in payload:
        phone = re.sub(r"[\s\-()]", "", str(payload["phone"]))
        if not PHONE_RE.match(phone):
            errors.append("Phone must have 10-15 digits, optionally starting with + and country code, "
                          "e.g. +919876543210.")
        clean["phone"] = phone
    if "address" in payload:
        address = " ".join(str(payload["address"]).split())
        if not 5 <= len(address) <= 300:
            errors.append("Address must be 5-300 characters.")
        clean["address"] = address
    if "plan" in payload:
        plan = str(payload["plan"]).strip().lower()
        if plan not in PLANS:
            errors.append(f"Plan must be one of {', '.join(sorted(PLANS))}.")
        clean["plan"] = plan
    if "status" in payload:
        status = str(payload["status"]).strip().lower()
        if status not in STATUSES:
            errors.append(f"Status must be one of {', '.join(sorted(STATUSES))}.")
        clean["status"] = status

    return clean, errors
