"""Nimbus Retail company portal: a simulated internal web application.

This is the "company system" the AI worker operates through a real browser,
just like an employee would:

  /                       dashboard + audit log of every change
  /invoices               Invoice System: list + search (?q=)
  /invoices/new           enter a supplier invoice
  /invoices/<number>      invoice details
  /crm                    CRM: customer list + search (?q=)
  /crm/<id>               customer details
  /crm/<id>/edit          edit a customer

A small read-only JSON API under /api/ exists only for tests and inspection;
the worker does not use it.

Chaos mode (--failure-rate) makes web pages randomly fail with HTTP 503 so the
worker's failure handling can be demonstrated. For form submissions, half of
the injected failures happen *after* the data was saved ("the save worked but
the page crashed") - the worker must check before re-submitting.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, url_for

from .db import connect, init_db, now_iso, write_audit
from .validation import CURRENCIES, PLANS, STATUSES, validate_customer_update, validate_invoice

DEFAULT_DB = Path(__file__).resolve().parent.parent / "company_portal.db"


def create_app(db_path: str | Path = DEFAULT_DB, failure_rate: float = 0.0,
               seed: int | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(DB_PATH=str(db_path), FAILURE_RATE=failure_rate, SECRET_KEY="local-demo-only")
    init_db(db_path)
    rng = random.Random(seed)

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def template_globals():
        return {"currencies": sorted(CURRENCIES), "plans": sorted(PLANS), "statuses": sorted(STATUSES)}

    # ------------------------------------------------------------------ chaos mode
    def service_unavailable():
        return render_template("error_503.html"), 503

    @app.before_request
    def inject_failure():
        if request.path.startswith(("/api/", "/static/")) or rng.random() >= app.config["FAILURE_RATE"]:
            return None
        if request.method == "POST" and rng.random() < 0.5:
            g.fail_after_commit = True  # let the save happen, then "crash"
            return None
        return service_unavailable()

    @app.after_request
    def crash_after_save(response):
        if g.pop("fail_after_commit", False):
            body, status = service_unavailable()
            return app.make_response((body, status))
        return response

    # ------------------------------------------------------------------ helpers
    def get_invoice(number: str):
        return db().execute("SELECT * FROM invoices WHERE invoice_number = ?", (number,)).fetchone()

    def get_customer(customer_id: str):
        return db().execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()

    def actor() -> str:
        return request.headers.get("X-Actor", "browser")  # the AI worker's browser sends X-Actor: ai-worker

    # ------------------------------------------------------------------ dashboard
    @app.get("/")
    def home():
        conn = db()
        return render_template(
            "home.html",
            invoice_count=conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0],
            customer_count=conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            audit=conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 25").fetchall(),
        )

    # ------------------------------------------------------------------ invoice system
    @app.get("/invoices")
    def invoices():
        q = request.args.get("q", "").strip()
        rows = db().execute(
            "SELECT * FROM invoices WHERE invoice_number LIKE ? OR vendor LIKE ? ORDER BY id DESC",
            (f"%{q}%", f"%{q}%")).fetchall()
        return render_template("invoices.html", invoices=rows, q=q)

    @app.get("/invoices/new")
    def new_invoice():
        return render_template("invoice_form.html", form={}, errors=[])

    @app.post("/invoices/new")
    def create_invoice():
        form = request.form.to_dict()
        clean, errors = validate_invoice(form)
        if errors:
            return render_template("invoice_form.html", form=form, errors=errors), 400
        if get_invoice(clean["invoice_number"]):
            return render_template("invoice_form.html", form=form, duplicate=clean["invoice_number"],
                                   errors=[f"Invoice {clean['invoice_number']} already exists. "
                                           f"Duplicates are not allowed."]), 409
        conn = db()
        conn.execute(
            "INSERT INTO invoices (invoice_number, vendor, amount, currency, due_date, source_file, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (clean["invoice_number"], clean["vendor"], clean["amount"], clean["currency"],
             clean["due_date"], clean["source_file"], now_iso()))
        write_audit(conn, "invoice", actor(), "create", clean["invoice_number"], clean)
        conn.commit()
        flash(f"Invoice {clean['invoice_number']} saved.", "ok")
        return redirect(url_for("invoice_detail", number=clean["invoice_number"]))

    @app.get("/invoices/<path:number>")
    def invoice_detail(number: str):
        row = get_invoice(number)
        if row is None:
            return render_template("not_found.html", what=f"Invoice {number}"), 404
        return render_template("invoice_detail.html", invoice=row)

    # ------------------------------------------------------------------ CRM
    @app.get("/crm")
    def customers():
        q = request.args.get("q", "").strip()
        like = f"%{q}%"
        rows = db().execute(
            "SELECT * FROM customers WHERE id LIKE ? OR name LIKE ? OR email LIKE ? ORDER BY id",
            (like, like, like)).fetchall()
        return render_template("customers.html", customers=rows, q=q)

    @app.get("/crm/<customer_id>")
    def customer_detail(customer_id: str):
        row = get_customer(customer_id)
        if row is None:
            return render_template("not_found.html", what=f"Customer {customer_id}"), 404
        return render_template("customer_detail.html", c=row)

    @app.get("/crm/<customer_id>/edit")
    def edit_customer(customer_id: str):
        row = get_customer(customer_id)
        if row is None:
            return render_template("not_found.html", what=f"Customer {customer_id}"), 404
        return render_template("customer_form.html", c=row, form=dict(row), errors=[])

    @app.post("/crm/<customer_id>/edit")
    def update_customer(customer_id: str):
        before = get_customer(customer_id)
        if before is None:
            return render_template("not_found.html", what=f"Customer {customer_id}"), 404
        form = request.form.to_dict()
        clean, errors = validate_customer_update(form)
        conn = db()
        if not errors and "email" in clean and conn.execute(
                "SELECT 1 FROM customers WHERE email = ? AND id != ?", (clean["email"], customer_id)).fetchone():
            errors.append("That email address already belongs to another customer.")
        if errors:
            return render_template("customer_form.html", c=before, form=form, errors=errors), 400
        changes = {f: v for f, v in clean.items() if before[f] != v}
        if changes:
            assignments = ", ".join(f"{f} = ?" for f in changes)
            conn.execute(f"UPDATE customers SET {assignments}, updated_at = ? WHERE id = ?",
                         [*changes.values(), now_iso(), customer_id])
            write_audit(conn, "crm", actor(), "update", customer_id,
                        {f: {"from": before[f], "to": v} for f, v in changes.items()})
            conn.commit()
            flash(f"Customer {customer_id} updated: {', '.join(changes)}.", "ok")
        else:
            flash("No changes to save.", "ok")
        return redirect(url_for("customer_detail", customer_id=customer_id))

    # ------------------------------------------------------------------ read-only JSON API (tests only)
    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.get("/api/invoices")
    def api_invoices():
        return jsonify([dict(r) for r in db().execute("SELECT * FROM invoices ORDER BY id").fetchall()])

    @app.get("/api/customers/<customer_id>")
    def api_customer(customer_id: str):
        row = get_customer(customer_id)
        return (jsonify(dict(row)), 200) if row else (jsonify(error="not_found"), 404)

    @app.get("/api/audit")
    def api_audit():
        return jsonify([dict(r) for r in db().execute("SELECT * FROM audit_log ORDER BY id").fetchall()])

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Nimbus Retail company portal (Invoice System + CRM).")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite file (default: %(default)s)")
    parser.add_argument("--failure-rate", type=float, default=0.0,
                        help="Chaos mode: fraction of page loads/submissions that fail with 503 (e.g. 0.2)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for chaos mode")
    parser.add_argument("--reset", action="store_true", help="Wipe the database and reload the seed data")
    args = parser.parse_args()

    if args.reset:
        init_db(args.db, reset=True)
        print(f"Database reset: {args.db}")
    app = create_app(args.db, args.failure_rate, args.seed)
    print(f"Company portal running at http://127.0.0.1:{args.port}  (failure rate {args.failure_rate:.0%})")
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
