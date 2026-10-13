"""Bo's tools. Shared by the texting loop (agent.py) and the ElevenLabs voice agent (/api/tools/<name>).

Every tool is scoped to one person: it can only see and change that person's appointments.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from . import db


def _tz(person):
    try:
        return ZoneInfo(person.get("timezone") or "America/New_York")
    except Exception:
        return ZoneInfo("America/New_York")


def say_time(dt, person):
    """2026-10-15 18:00Z -> 'Thu Oct 15 at 2:00 PM' in the person's time zone."""
    local = dt.astimezone(_tz(person))
    return local.strftime("%a %b %-d at %-I:%M %p")


def _appt(row, person):
    return {
        "appointment_id": row["id"],
        "title": row["title"],
        "provider": row["provider"],
        "location": row["location"],
        "when": say_time(row["starts_at"], person),
    }


# ── tools ─────────────────────────────────────────────────────────────────
def get_appointments(conn, person, args):
    rows = conn.execute(
        """select * from appointments
           where person_id = %s and status = 'scheduled' and starts_at > now()
           order by starts_at""",
        (person["id"],),
    ).fetchall()
    return {"appointments": [_appt(r, person) for r in rows]}


def get_available_slots(conn, person, args):
    appt = _own_appointment(conn, person, args.get("appointment_id"))
    if not appt:
        return {"error": "No upcoming appointment with that id for this person."}
    rows = conn.execute(
        """select * from open_slots
           where provider = %s and not taken and starts_at > now()
           order by starts_at limit 5""",
        (appt["provider"],),
    ).fetchall()
    return {
        "appointment_id": appt["id"],
        "provider": appt["provider"],
        "current_time": say_time(appt["starts_at"], person),
        "open_slots": [{"slot_id": r["id"], "when": say_time(r["starts_at"], person)} for r in rows],
    }


def reschedule_appointment(conn, person, args):
    appt = _own_appointment(conn, person, args.get("appointment_id"))
    if not appt:
        return {"ok": False, "error": "No upcoming appointment with that id for this person."}
    try:
        slot_id = int(args.get("slot_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "slot_id must be a number from get_available_slots."}

    with conn.transaction():
        slot = conn.execute(
            "select * from open_slots where id = %s for update", (slot_id,)
        ).fetchone()
        if not slot or slot["taken"] or slot["provider"] != appt["provider"]:
            return {"ok": False, "error": "That time is no longer available. Check open slots again."}
        conn.execute("update open_slots set taken = true where id = %s", (slot_id,))
        # The old time goes back on the clinic's calendar.
        conn.execute(
            "insert into open_slots (provider, starts_at) values (%s, %s)",
            (appt["provider"], appt["starts_at"]),
        )
        conn.execute(
            "update appointments set starts_at = %s where id = %s", (slot["starts_at"], appt["id"])
        )

    return {
        "ok": True,
        "title": appt["title"],
        "provider": appt["provider"],
        "old_time": say_time(appt["starts_at"], person),
        "new_time": say_time(slot["starts_at"], person),
    }


def add_appointment(conn, person, args):
    title = (args.get("title") or "").strip()
    when_raw = (args.get("when") or "").strip()
    if not title or not when_raw:
        return {"ok": False, "error": "Need a title and a time."}
    try:
        when = datetime.fromisoformat(when_raw)
    except ValueError:
        return {"ok": False, "error": "Time must look like 2026-10-20T15:00."}
    if when.tzinfo is None:
        when = when.replace(tzinfo=_tz(person))

    row = conn.execute(
        """insert into appointments (person_id, title, provider, location, starts_at)
           values (%s, %s, %s, %s, %s) returning *""",
        (person["id"], title, args.get("provider") or None, args.get("location") or None, when),
    ).fetchone()
    return {"ok": True, "appointment": _appt(row, person)}


def record_consent(conn, person, args):
    db.set_consent(conn, person["id"])
    return {"ok": True, "message": "Consent saved. You can help with appointments now."}


def _own_appointment(conn, person, appointment_id):
    try:
        appointment_id = int(appointment_id)
    except (TypeError, ValueError):
        return None
    return conn.execute(
        """select * from appointments
           where id = %s and person_id = %s and status = 'scheduled' and starts_at > now()""",
        (appointment_id, person["id"]),
    ).fetchone()


TOOLS = {
    "get_appointments": get_appointments,
    "get_available_slots": get_available_slots,
    "reschedule_appointment": reschedule_appointment,
    "add_appointment": add_appointment,
    "record_consent": record_consent,
}


def run(conn, person, name, args):
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"Unknown tool {name}"}
    try:
        return fn(conn, person, args or {})
    except Exception as e:  # tell the model something went wrong instead of crashing the turn
        return {"error": f"{type(e).__name__}: {e}"}


# ── Tool descriptions for Claude (texting). The voice agent gets the same
#    tools configured in ElevenLabs; see elevenlabs/tools.md. ──────────────
SCHEMAS = [
    {
        "name": "get_appointments",
        "description": "List this person's upcoming appointments. Use before talking about any appointment.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_available_slots",
        "description": "Get open times with the same provider for one of the person's appointments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "From get_appointments"}
            },
            "required": ["appointment_id"],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": (
            "Move an appointment to an open slot. Only call after the person clearly "
            "said yes to that specific new time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "appointment_id": {"type": "integer", "description": "From get_appointments"},
                "slot_id": {"type": "integer", "description": "From get_available_slots"},
            },
            "required": ["appointment_id", "slot_id"],
        },
    },
    {
        "name": "add_appointment",
        "description": (
            "Save an appointment the person tells you about. Only call after repeating the "
            "details back and getting a yes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "e.g. 'Eye exam'"},
                "provider": {"type": "string", "description": "Doctor or clinic, if known"},
                "location": {"type": "string", "description": "Place, if known"},
                "when": {
                    "type": "string",
                    "description": "Local date and time, ISO format like 2026-10-20T15:00",
                },
            },
            "required": ["title", "when"],
        },
    },
]
