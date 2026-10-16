"""Small Postgres helpers. One short-lived connection per request (serverless-friendly)."""

import os
import re

import psycopg
from psycopg.rows import dict_row


def connect():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Add the Neon database in Vercel → Storage.")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def normalize_phone(raw):
    """'whatsapp:+1 (555) 555-0123' -> '+15555550123'."""
    if not raw:
        return ""
    raw = raw.replace("whatsapp:", "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if len(digits) == 10:          # US/Canada number without country code
        digits = "1" + digits
    return "+" + digits


def allowed_numbers():
    raw = os.environ.get("ALLOWED_NUMBERS", "")
    return {normalize_phone(p) for p in raw.split(",") if p.strip()}


# Testers who signed up on trustbo.ai can use Bo for this long, then they're deleted.
TESTER_TTL_HOURS = int(os.environ.get("TESTER_TTL_HOURS", "24") or 24)


def is_allowed(conn, phone):
    """Your own numbers (ALLOWED_NUMBERS) plus anyone who signed up as a tester on trustbo.ai."""
    if not phone:
        return False
    if phone in allowed_numbers():
        return True
    row = conn.execute(
        "select 1 from people where phone = %s and is_tester "
        "and created_at > now() - make_interval(hours => %s)",
        (phone, TESTER_TTL_HOURS),
    ).fetchone()
    return row is not None


# ── people ────────────────────────────────────────────────────────────────
def person_by_phone(conn, phone):
    return conn.execute("select * from people where phone = %s", (phone,)).fetchone()


def get_or_create_person(conn, phone):
    person = person_by_phone(conn, phone)
    if person:
        return person
    return conn.execute(
        "insert into people (phone) values (%s) on conflict (phone) do update set phone = excluded.phone returning *",
        (phone,),
    ).fetchone()


def set_consent(conn, person_id):
    return conn.execute(
        "update people set consented_at = now() where id = %s returning *", (person_id,)
    ).fetchone()


# ── messages ──────────────────────────────────────────────────────────────
def save_message(conn, person_id, role, content, channel):
    if not content or not content.strip():
        return
    conn.execute(
        "insert into messages (person_id, role, content, channel) values (%s, %s, %s, %s)",
        (person_id, role, content.strip(), channel),
    )


NOTES_MARK = "\n\n[Bo's notes, not shown to the person:"


def load_history(conn, person_id, limit=30):
    return load_history_and_notes(conn, person_id, limit)[0]


def load_history_and_notes(conn, person_id, limit=30):
    """Recent turns as Anthropic messages (alternating user/assistant, starting with user),
    plus Bo's saved tool notes, kept separate so the model never sees them inside its own
    replies (it would start copying them into new replies)."""
    rows = conn.execute(
        "select role, content, channel from messages where person_id = %s order by id desc limit %s",
        (person_id, limit),
    ).fetchall()
    rows.reverse()

    history, notes = [], []
    for r in rows:
        text = r["content"]
        if r["role"] == "assistant" and NOTES_MARK in text:
            text, note = text.split(NOTES_MARK, 1)
            notes.append(note.strip().rstrip("]").strip())
            if not text.strip():
                continue
        if r["channel"] == "voice":
            text = "(On a phone call) " + text
        if history and history[-1]["role"] == r["role"]:
            history[-1]["content"] += "\n" + text
        else:
            history.append({"role": r["role"], "content": text})

    while history and history[0]["role"] != "user":
        history.pop(0)
    return history, notes


# ── calls ─────────────────────────────────────────────────────────────────
def record_call(conn, conversation_id, person_id):
    if not conversation_id:
        return
    conn.execute(
        "insert into calls (conversation_id, person_id) values (%s, %s) on conflict do nothing",
        (conversation_id, person_id),
    )


def person_for_call(conn, conversation_id):
    return conn.execute(
        "select p.* from calls c join people p on p.id = c.person_id where c.conversation_id = %s",
        (conversation_id,),
    ).fetchone()
