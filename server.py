#!/usr/bin/env python3
"""
IMSB Dhoke Mai Nawab - School Website Backend
----------------------------------------------
Zero-dependency Python backend (uses only the standard library).

Features:
  - Serves the public website + admin dashboard
  - Secure admin login (password -> session cookie)
  - SQLite database (data.db) shared by all visitors / devices
  - REST API for homework, exam schedule, notices and photos

Run:
  python server.py
  Then open http://localhost:8000          (public website)
  Admin:     http://localhost:8000/admin.html

Admin password:
  Set environment variable ADMIN_PASSWORD before starting.
  Default (demo only): admin123   <-- change this before going live!

Deploy (e.g. Render):
  Start command:  python server.py
  Environment:    ADMIN_PASSWORD=<your strong password>
                  PORT is provided automatically by the host.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "data.db"))
PORT = int(os.environ.get("PORT", "8000"))
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
SESSION_COOKIE = "imsb_session"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours
MAX_BODY_BYTES = 3 * 1024 * 1024  # 3 MB (photos are sent as base64)

COLLECTIONS = {
    "homework": ["className", "subject", "dueDate", "details"],
    "exams": ["examName", "className", "subject", "examDate", "details"],
    "notices": ["title", "date", "details"],
}
REQUIRED = {
    "homework": ["className", "subject", "details"],
    "exams": ["examName", "className", "subject", "examDate"],
    "notices": ["title", "details"],
}
PHOTO_SLOTS = {"heroImage", "principalImage", "staffImage", "studentsImage", "buildingImage"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/admin": ("admin.html", "text/html; charset=utf-8"),
    "/admin.html": ("admin.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/admin.js": ("admin.js", "application/javascript; charset=utf-8"),
    "/assistant": ("assistant.html", "text/html; charset=utf-8"),
    "/assistant.html": ("assistant.html", "text/html; charset=utf-8"),
}


# ---------------------------------------------------------------- database
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS items (
                   id TEXT PRIMARY KEY,
                   kind TEXT NOT NULL,
                   payload TEXT NOT NULL,
                   created_at INTEGER NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS photos (
                   slot TEXT PRIMARY KEY,
                   data_url TEXT NOT NULL,
                   updated_at INTEGER NOT NULL
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                   token TEXT PRIMARY KEY,
                   expires INTEGER NOT NULL
               )"""
        )


# ------------------------------------------------------- school assistant
# The same agent logic as the standalone LangGraph project, built into
# the website so parents can ask questions from any phone browser:
#   POST /api/ask  {"question": "Class 3 ka homework kya hai?"}
# Intent is detected with keywords (no paid AI key needed).
HOMEWORK_WORDS = ["homework", "home work", "ہوم ورک", "سبق"]
EXAM_WORDS = ["exam", "test", "paper", "امتحان", "پرچہ", "پیپر"]
NOTICE_WORDS = ["notice", "announcement", "news", "نوٹس", "اطلاع", "اعلان"]


def get_items(kind):
    with db() as conn:
        rows = conn.execute(
            "SELECT payload FROM items WHERE kind = ? ORDER BY created_at DESC", (kind,)
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def assistant_answer(question):
    q = (question or "").lower()

    class_name = None
    m = re.search(r"class[\s-]*([1-5])", q)
    if m:
        class_name = f"Class {m.group(1)}"
    elif "prep" in q:
        class_name = "Prep"

    if any(w in q for w in HOMEWORK_WORDS):
        items = get_items("homework")
        if class_name:
            items = [x for x in items if (x.get("className") or "").lower() == class_name.lower()]
        if not items:
            where = f" for {class_name}" if class_name else ""
            return f"No homework has been published{where} yet."
        lines = [f"Homework{f' for {class_name}' if class_name else ''}:"]
        for x in items:
            lines.append(
                f"- {x.get('className')}: {x.get('subject')} "
                f"(due: {x.get('dueDate') or 'no due date set'}) — {x.get('details')}"
            )
        return "\n".join(lines)

    if any(w in q for w in EXAM_WORDS):
        items = get_items("exams")
        if not items:
            return "No examination schedule has been published yet."
        lines = ["Examination schedule:"]
        for x in sorted(items, key=lambda i: i.get("examDate") or ""):
            lines.append(
                f"- {x.get('examDate') or 'date not set'}: {x.get('examName')} — "
                f"{x.get('subject')} ({x.get('className')})"
            )
        return "\n".join(lines)

    if any(w in q for w in NOTICE_WORDS):
        items = get_items("notices")
        if not items:
            return "There are no school notices at the moment."
        lines = ["Latest school notices:"]
        for x in items:
            lines.append(f"- {x.get('title')} ({x.get('date') or 'no date'}): {x.get('details')}")
        return "\n".join(lines)

    return (
        "Assalam-o-Alaikum! I am the IMSB school assistant. You can ask me things like:\n"
        '- "What is the homework for Class 3?"\n'
        '- "When is the next exam?"\n'
        '- "Any new school notices?"'
    )


# ---------------------------------------------------------------- helpers
def clean_payload(kind, raw):
    """Keep only known fields, coerce to trimmed strings, enforce limits."""
    payload = {}
    for field in COLLECTIONS[kind]:
        value = raw.get(field, "")
        if not isinstance(value, str):
            value = str(value)
        payload[field] = value.strip()[:5000]
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "IMSB/1.0"

    # ---------- low-level helpers
    def log_message(self, fmt, *args):  # quieter logs
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, status, obj, extra_headers=None):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            return None, "Request too large"
        if length == 0:
            return {}, None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except Exception:
            return None, "Invalid JSON"

    def session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def is_logged_in(self):
        token = self.session_token()
        if not token:
            return False
        with db() as conn:
            row = conn.execute(
                "SELECT expires FROM sessions WHERE token = ?", (token,)
            ).fetchone()
        return bool(row and row["expires"] > int(time.time()))

    def require_login(self):
        if self.is_logged_in():
            return True
        self.send_json(401, {"error": "Login required"})
        return False

    # ---------- routing
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json(200, {"ok": True})
        if path == "/api/me":
            return self.send_json(200, {"loggedIn": self.is_logged_in()})
        if path == "/api/photos":
            with db() as conn:
                rows = conn.execute("SELECT slot, data_url FROM photos").fetchall()
            return self.send_json(200, {r["slot"]: r["data_url"] for r in rows})
        if path.startswith("/api/") and path[5:] in COLLECTIONS:
            kind = path[5:]
            with db() as conn:
                rows = conn.execute(
                    "SELECT payload FROM items WHERE kind = ? ORDER BY created_at DESC",
                    (kind,),
                ).fetchall()
            return self.send_json(200, [json.loads(r["payload"]) for r in rows])
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            file_path = BASE_DIR / filename
            if file_path.is_file():
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
        return self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/ask":
            data, err = self.read_json()
            if err:
                return self.send_json(400, {"error": err})
            question = str(data.get("question", "")).strip()
            if not question:
                return self.send_json(400, {"error": "Please write a question"})
            return self.send_json(200, {"answer": assistant_answer(question)})

        if path == "/api/login":
            data, err = self.read_json()
            if err:
                return self.send_json(400, {"error": err})
            password = data.get("password", "")
            if not hmac.compare_digest(password, ADMIN_PASSWORD):
                return self.send_json(401, {"error": "Wrong password"})
            token = secrets.token_urlsafe(32)
            expires = int(time.time()) + SESSION_TTL_SECONDS
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE expires <= ?", (int(time.time()),))
                conn.execute(
                    "INSERT INTO sessions (token, expires) VALUES (?, ?)", (token, expires)
                )
            cookie = (
                f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; "
                f"Max-Age={SESSION_TTL_SECONDS}; SameSite=Lax"
            )
            return self.send_json(200, {"loggedIn": True}, {"Set-Cookie": cookie})

        if path == "/api/logout":
            token = self.session_token()
            if token:
                with db() as conn:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            cookie = f"{SESSION_COOKIE}=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax"
            return self.send_json(200, {"loggedIn": False}, {"Set-Cookie": cookie})

        if path == "/api/reset":
            if not self.require_login():
                return
            with db() as conn:
                conn.execute("DELETE FROM items")
                conn.execute("DELETE FROM photos")
            return self.send_json(200, {"ok": True})

        if path == "/api/photos":
            if not self.require_login():
                return
            data, err = self.read_json()
            if err:
                return self.send_json(400, {"error": err})
            slot = data.get("slot", "")
            data_url = data.get("dataUrl", "")
            if slot not in PHOTO_SLOTS:
                return self.send_json(400, {"error": "Unknown photo section"})
            if not data_url.startswith("data:image/") or len(data_url) > int(MAX_BODY_BYTES * 0.95):
                return self.send_json(400, {"error": "Invalid or too large image"})
            with db() as conn:
                conn.execute(
                    """INSERT INTO photos (slot, data_url, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(slot) DO UPDATE SET data_url = excluded.data_url,
                       updated_at = excluded.updated_at""",
                    (slot, data_url, int(time.time())),
                )
            return self.send_json(200, {"ok": True})

        if path.startswith("/api/") and path[5:] in COLLECTIONS:
            if not self.require_login():
                return
            kind = path[5:]
            data, err = self.read_json()
            if err:
                return self.send_json(400, {"error": err})
            payload = clean_payload(kind, data)
            missing = [f for f in REQUIRED[kind] if not payload.get(f)]
            if missing:
                return self.send_json(400, {"error": f"Missing fields: {', '.join(missing)}"})
            item_id = f"{int(time.time() * 1000)}_{secrets.token_hex(3)}"
            payload["id"] = item_id
            payload["createdAt"] = int(time.time() * 1000)
            with db() as conn:
                conn.execute(
                    "INSERT INTO items (id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                    (item_id, kind, json.dumps(payload), payload["createdAt"]),
                )
            return self.send_json(201, payload)

        return self.send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        parts = [unquote(p) for p in path.split("/") if p]  # ['api', kind, id]
        if len(parts) == 3 and parts[0] == "api" and parts[1] in COLLECTIONS:
            if not self.require_login():
                return
            with db() as conn:
                cur = conn.execute(
                    "DELETE FROM items WHERE kind = ? AND id = ?", (parts[1], parts[2])
                )
            if cur.rowcount:
                return self.send_json(200, {"ok": True})
            return self.send_json(404, {"error": "Item not found"})
        return self.send_json(404, {"error": "Not found"})


def main():
    init_db()
    if ADMIN_PASSWORD == "admin123":
        print("WARNING: Using default admin password 'admin123'.")
        print("Set ADMIN_PASSWORD environment variable before going live!")
    print(f"IMSB website running at http://localhost:{PORT}")
    print(f"Admin dashboard:       http://localhost:{PORT}/admin.html")
    print(f"Database file:         {DB_PATH}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
