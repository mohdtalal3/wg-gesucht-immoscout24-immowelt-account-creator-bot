"""
app.py — Flask web interface for Account Creator.
Run: python app.py
"""

import csv
import io
import json
import os
from functools import wraps

from flask import (Flask, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from dotenv import load_dotenv
from supabase import create_client

import worker

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
_sb = create_client(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_KEY", ""))


# ── Auth ──────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password", "") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        error = "Incorrect password. Try again."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    accounts_res = _sb.table("created_accounts").select("*").order("created_at", desc=True).execute()
    accounts     = accounts_res.data or []
    stats = {
        "total":     len(accounts),
        "pending":   sum(1 for a in accounts if a["status"] == "pending"),
        "running":   sum(1 for a in accounts if a["status"] == "running"),
        "completed": sum(1 for a in accounts if a["status"] == "completed"),
        "failed":    sum(1 for a in accounts if a["status"] == "failed"),
    }
    runs_res       = _sb.table("bot_runs").select("*").order("started_at", desc=True).limit(5).execute()
    recent_runs    = runs_res.data or []
    passwords_json = json.dumps({a["id"]: a["password"] for a in accounts})
    return render_template("dashboard.html", stats=stats, recent_runs=recent_runs,
                           accounts=accounts, passwords_json=passwords_json,
                           bot_running=worker.is_bot_running())


@app.route("/accounts")
@login_required
def accounts_page():
    return redirect(url_for("dashboard"))


@app.route("/upload", methods=["POST"])
@login_required
def upload_csv():
    f = request.files.get("csv_file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("dashboard"))

    content  = f.read().decode("utf-8-sig")
    reader   = csv.DictReader(io.StringIO(content))
    inserted = skipped = 0

    for row in reader:
        email = (row.get("User ID / Email Address") or "").strip().lstrip("'")
        pwd   = (row.get("Password") or "").strip()
        if not email or not pwd:
            continue
        try:
            _sb.table("created_accounts").insert({"email": email, "password": pwd}).execute()
            inserted += 1
        except Exception:
            skipped += 1

    flash(f"Imported {inserted} accounts. {skipped} skipped (already exist).", "success")
    return redirect(url_for("dashboard"))


@app.route("/account/delete/<account_id>", methods=["POST"])
@login_required
def delete_account(account_id):
    _sb.table("created_accounts").delete().eq("id", account_id).execute()
    flash("Account deleted.", "success")
    return redirect(url_for("dashboard"))



@app.route("/account/retry/<account_id>", methods=["POST"])
@login_required
def retry_account(account_id):
    _sb.table("created_accounts").update({
        "status": "pending", "error_msg": "",
    }).eq("id", account_id).execute()
    flash("Account queued for retry (existing platforms preserved).", "success")
    return redirect(url_for("dashboard"))


# ── Run Bot ───────────────────────────────────────────────────────────────────

@app.route("/run", methods=["GET", "POST"])
@login_required
def run_page():
    if request.method == "POST":
        if worker.is_bot_running():
            flash("Bot is already running.", "error")
        else:
            n      = max(1, int(request.form.get("n_accounts", 1)))
            run_id = worker.start_bot(n)
            if run_id:
                flash(f"Bot started — processing {n} accounts in the background.", "success")
            else:
                flash("Bot is already running.", "error")
        return redirect(url_for("run_page"))

    res           = _sb.table("created_accounts").select("id", count="exact").eq("status", "pending").execute()
    pending_count = res.count or 0
    state         = worker.get_state()
    runs_res      = _sb.table("bot_runs").select("*").order("started_at", desc=True).limit(10).execute()
    run_history   = runs_res.data or []
    return render_template("run.html", pending_count=pending_count,
                           bot_running=worker.is_bot_running(),
                           state=state, run_history=run_history)


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/bot-status")
@login_required
def api_bot_status():
    state = worker.get_state()
    return jsonify({
        "active":        state["active"],
        "total":         state["total"],
        "completed":     state["completed"],
        "failed":        state["failed"],
        "current_email": state["current_email"],
        "log":           state["log"][-100:],
    })


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5003, use_reloader=False)
