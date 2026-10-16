"""Tester sign-up from trustbo.ai: each tester gets a pretend patient account at "Maple Health"
with three sample appointments and their own open slots."""

import os
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db

DEFAULT_TZ = "America/Los_Angeles"

# (title, provider, location, days from today, hour, minute)
SAMPLE_APPOINTMENTS = [
    ("Dental cleaning", "Dr. Priya Shah", "Bright Smile Dental", 3, 14, 0),
    ("Cardiology follow-up", "Dr. Lin", "Heart & Vascular Clinic", 8, 10, 30),
    ("Annual physical", "Dr. Okafor", "Maple Family Medicine", 15, 9, 0),
]
# (provider, days from today, hour, minute)
SAMPLE_SLOTS = [
    ("Dr. Priya Shah", 2, 10, 0),
    ("Dr. Priya Shah", 4, 11, 30),
    ("Dr. Priya Shah", 5, 15, 0),
    ("Dr. Priya Shah", 7, 9, 0),
    ("Dr. Lin", 9, 13, 0),
    ("Dr. Lin", 10, 9, 30),
    ("Dr. Lin", 12, 15, 15),
    ("Dr. Okafor", 14, 11, 0),
    ("Dr. Okafor", 16, 14, 0),
]


class SignupError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def tester_cap():
    try:
        return int(os.environ.get("TESTER_CAP", "25"))
    except ValueError:
        return 25


def clean_timezone(tz):
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        return DEFAULT_TZ


def us_phone(raw):
    """Returns +1XXXXXXXXXX for a 10-digit US number (optionally with a leading 1), else ''."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01":
        return ""
    return "+1" + digits


CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i look-alikes


def new_portal_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def pretty_phone(phone):
    d = phone[-10:]
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"


def seed_demo(conn, person):
    """Gives one person their 3 sample appointments and 9 open slots, relative to today."""
    tz = ZoneInfo(clean_timezone(person.get("timezone") or DEFAULT_TZ))
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    def at(days, hour, minute):
        # Build the wall-clock time in their zone, so DST changes don't shift appointments.
        d = (today + timedelta(days=days)).date()
        while d.weekday() >= 5:  # clinics are closed on weekends
            d += timedelta(days=1)
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)

    with conn.transaction():
        conn.execute("delete from appointments where person_id = %s", (person["id"],))
        conn.execute("delete from open_slots where person_id = %s", (person["id"],))
        for title, provider, location, days, h, m in SAMPLE_APPOINTMENTS:
            conn.execute(
                """insert into appointments (person_id, title, provider, location, starts_at)
                   values (%s, %s, %s, %s, %s)""",
                (person["id"], title, provider, location, at(days, h, m)),
            )
        for provider, days, h, m in SAMPLE_SLOTS:
            conn.execute(
                "insert into open_slots (person_id, provider, starts_at) values (%s, %s, %s)",
                (person["id"], provider, at(days, h, m)),
            )


def delete_expired_testers(conn):
    """Removes testers older than TESTER_TTL_HOURS (their appointments, slots, messages and calls go too)."""
    rows = conn.execute(
        "delete from people where is_tester and created_at < now() - make_interval(hours => %s) returning id",
        (db.TESTER_TTL_HOURS,),
    ).fetchall()
    if rows:
        print(f"[cleanup] deleted {len(rows)} expired tester(s)")
    return len(rows)


def sign_up(conn, name, raw_phone, timezone):
    """Creates (or finds) a tester and returns their person row."""
    delete_expired_testers(conn)
    name = re.sub(r"\s+", " ", (name or "")).strip()[:40]
    if not name:
        raise SignupError("name", "Add your first name.")
    phone = us_phone(raw_phone)
    if not phone:
        raise SignupError("phone", "Enter a 10-digit US mobile number.")
    tz = clean_timezone(timezone or DEFAULT_TZ)

    person = db.person_by_phone(conn, phone)
    if person:
        # Already here (signed up before, or one of your own numbers): just hand back their portal.
        updates = {"is_tester": person["is_tester"] or phone not in db.allowed_numbers()}
        if not person["portal_token"]:
            updates["portal_token"] = new_portal_code()
        if not person["consented_at"]:
            conn.execute("update people set consented_at = now() where id = %s", (person["id"],))
        person = conn.execute(
            """update people set is_tester = %s, portal_token = coalesce(portal_token, %s),
                                 name = coalesce(name, %s)
               where id = %s returning *""",
            (updates["is_tester"], updates.get("portal_token"), name, person["id"]),
        ).fetchone()
        has_appts = conn.execute(
            "select 1 from appointments where person_id = %s limit 1", (person["id"],)
        ).fetchone()
        if not has_appts:
            seed_demo(conn, person)
        return person

    count = conn.execute("select count(*) as n from people where is_tester").fetchone()["n"]
    if count >= tester_cap():
        raise SignupError("full", "The demo is full right now.", status=429)

    person = conn.execute(
        """insert into people (phone, name, timezone, consented_at, is_tester, portal_token)
           values (%s, %s, %s, now(), true, %s)
           on conflict (phone) do nothing
           returning *""",
        (phone, name, tz, new_portal_code()),
    ).fetchone()
    if not person:  # two sign-ups raced; use the row that won
        return sign_up(conn, name, raw_phone, timezone)
    seed_demo(conn, person)
    print(f"[signup] new tester {name} {phone[:-4]}XXXX tz={tz}")
    return person
