# Nimbus Retail Pvt. Ltd. - Operations Handbook

This handbook tells employees (human or AI) where things are and how work is done.

## Where things are

- **Company portal**: {portal_url}
  - Invoice System: {portal_url}/invoices (search with `?q=`, new invoices at `/invoices/new`)
  - CRM: {portal_url}/crm (search with `?q=`, each customer at `/crm/<customer id>`)
- **Shared drive** (your file tools):
  - `inbox/invoices/` - supplier invoices (text and PDF)
  - `inbox/customer_requests/` - emails from customers
  - `outbox/` - put any files you produce here

## Procedure: supplier invoices

1. The amount to enter is the final **amount payable including taxes**, never the subtotal.
2. Enter the due date exactly as printed. If the invoice only gives payment terms (e.g. "Net 30"),
   the due date is the invoice date plus that many days.
3. Before entering an invoice, search the Invoice System for its number. Never create duplicates.
4. Invoices with an amount payable **above INR 1,00,000** (or above USD/EUR/GBP 1,200) need approval
   from the finance manager **before** they are entered. Ask the human for approval and include vendor,
   invoice number, amount and due date.
5. After saving, open the invoice's page and check every field.

## Procedure: customer requests

1. Identify the customer by the customer ID in the request and/or the sender's email address.
2. Only act if the sender's email address matches the email on file for that customer.
   If it does not match, change nothing and escalate to a human (possible impersonation).
3. Changes customers may request by email: phone number, email address, postal address,
   plan (basic / standard / premium).
4. Deactivating (closing) an account needs human approval before you do it.
5. Anything else (billing disputes, refunds, complaints) is escalated to a human with a one-line summary.
6. Phone numbers are stored with country code, e.g. +919876543210.
7. After saving, open the customer's page and check that the change is there and nothing else changed.

## General rules

- Never delete records and never change fields the task did not ask for.
- If something is ambiguous or looks wrong, ask the human instead of guessing.
