"""The pretend clinic portal ("My HealthChart") each tester sees at /portal/<token>.

It reads the same appointments table Bo's tools change, so when Bo moves an appointment
the tester refreshes this page and sees it."""

from datetime import datetime

from flask import render_template_string

import re

from . import db
from .tools import _tz

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>My HealthChart · Patient portal</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap">
<style>
:root {
  --bg: #f3f5f8; --surface: #ffffff; --ink: #1b2533; --muted: #5d6b7c; --line: #dde3ea;
  --brand: #1f4f7b; --brand-ink: #ffffff; --brand-soft: #e6eef6;
  --notice: #fff6e0; --notice-ink: #6b4d00;
  --sans: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.5; margin: 0; }
.gutter { padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.inner { max-width: 880px; margin: 0 auto; }
header.bar { background: var(--brand); color: var(--brand-ink); }
header.bar .inner { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding-block: 14px; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 17px; }
.leaf { width: 28px; height: 28px; border-radius: 7px; background: var(--brand-ink); color: var(--brand); display: grid; place-items: center; font-weight: 700; }
.brand small { display: block; font-weight: 400; font-size: 12px; opacity: .8; }
.who { font-size: 13px; text-align: right; }
.who b { display: block; font-size: 14px; }
main { padding-block: 20px 64px; }
.notice { background: var(--notice); color: var(--notice-ink); border-radius: 8px; padding: 10px 14px; font-size: 13px; display: flex; gap: 8px; align-items: flex-start; }
h1 { font-size: 22px; font-weight: 600; margin: 24px 0 4px; }
.sub { color: var(--muted); margin: 0 0 16px; font-size: 14px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.refresh { font: inherit; font-size: 13px; font-weight: 600; color: var(--brand); background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 2px 10px; cursor: pointer; text-decoration: none; }
.refresh:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.appts { display: grid; gap: 10px; }
.appt { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
  display: grid; grid-template-columns: 64px 1fr auto; gap: 16px; align-items: center; padding: 14px 16px; }
.appt > * { min-width: 0; }
.date { text-align: center; border-radius: 8px; background: var(--brand-soft); color: var(--brand); padding: 6px 0; }
.date .m { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.date .d { font-size: 24px; font-weight: 700; line-height: 1.1; font-variant-numeric: tabular-nums; }
.date .w { font-size: 11px; }
.appt h2 { font-size: 16px; font-weight: 600; margin: 0; }
.meta { color: var(--muted); font-size: 13px; }
.time { font-weight: 600; font-variant-numeric: tabular-nums; }
.chip { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px; white-space: nowrap; background: var(--brand-soft); color: var(--brand); }
.appt-wrap { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.appt-wrap .appt { border: 0; border-radius: 0; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
details.slots > summary { list-style: none; cursor: pointer; font-size: 13px; font-weight: 600; color: var(--brand);
  padding: 10px 16px; border-top: 1px solid var(--line); }
details.slots > summary::-webkit-details-marker { display: none; }
details.slots > summary::after { content: " \\25BE"; }
details.slots[open] > summary::after { content: " \\25B4"; }
details.slots > summary:focus-visible { outline: 2px solid var(--brand); outline-offset: -2px; }
.slots-body { background: var(--bg); padding: 4px 16px 14px 96px; }
.slots-body h3 { font-size: 13px; font-weight: 600; margin: 8px 0; }
.slot-list { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; list-style: none; }
.slot-list li { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px; font-size: 13px; font-variant-numeric: tabular-nums; }
.slots-body p { margin: 8px 0 0; font-size: 12px; color: var(--muted); }
.empty { background: var(--surface); border: 1px dashed var(--line); border-radius: 10px; padding: 24px; color: var(--muted); text-align: center; }
footer.foot { color: var(--muted); font-size: 12px; margin-top: 24px; }
@media (max-width: 560px) {
  .appt { grid-template-columns: 56px 1fr; }
  .appt .chip { grid-column: 2; justify-self: start; }
  .slots-body { padding-left: 16px; }
  .who { text-align: left; }
}
</style>
</head>
<body>
<header class="bar gutter">
  <div class="inner">
    <div class="brand"><div class="leaf" aria-hidden="true">H</div><div>My HealthChart<small>Patient portal</small></div></div>
    <div class="who"><b>{{ name }}</b>Signed in with phone ending {{ last4 }}</div>
  </div>
</header>
<main class="gutter">
  <div class="inner">
    <div class="notice" role="note"><span aria-hidden="true">&#9432;</span><span><b>Demo sandbox.</b> My HealthChart is a pretend patient portal made for trying Bo. These are sample appointments, not real medical records.</span></div>
    <h1>Upcoming appointments</h1>
    <p class="sub"><span>Last updated {{ updated }}</span><a class="refresh" href="">Refresh</a></p>
    {% if appts %}
    <div class="appts">
      {% for a in appts %}
      <div class="appt-wrap">
        <article class="appt">
          <div class="date"><div class="m">{{ a.month }}</div><div class="d">{{ a.day }}</div><div class="w">{{ a.weekday }}</div></div>
          <div>
            <h2>{{ a.title }}</h2>
            <div class="meta"><span class="time">{{ a.time }}</span>{% for part in a.where %} · {{ part }}{% endfor %}</div>
          </div>
          <span class="chip">Confirmed</span>
        </article>
        {% if a.provider %}
        <details class="slots">
          <summary>Open times</summary>
          <div class="slots-body">
            {% if a.slots %}
            <h3>Other open times with {{ a.provider }}</h3>
            <ul class="slot-list">{% for t in a.slots %}<li>{{ t }}</li>{% endfor %}</ul>
            <p>To switch to one of these times, call the office.</p>
            {% else %}
            <p>No other open times right now.</p>
            {% endif %}
          </div>
        </details>
        {% endif %}
      </div>
      {% endfor %}
    </div>
    {% else %}
    <div class="empty">No upcoming appointments.</div>
    {% endif %}
    <footer class="foot">My HealthChart is fictional and exists only for the Bo demo. This page and its sample data are deleted after 24 hours.</footer>
  </div>
</main>
</body>
</html>"""

NOT_FOUND = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>My HealthChart · Patient portal</title></head>
<body style="font-family: system-ui, sans-serif; background:#f3f5f8; color:#1b2533; padding: 48px 16px; text-align:center">
<h1 style="font-size:20px">This demo portal isn't active.</h1>
<p style="color:#5d6b7c">Demo accounts last 24 hours. You can sign up again at <a href="https://trustbo.ai/#try">trustbo.ai</a>.</p>
</body></html>"""


def render(conn, token):
    """Returns (html, status)."""
    """`token` is the tester's 10-digit phone number (or an older random code)."""
    digits = re.sub(r"\D", "", token or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    person = None
    if len(digits) == 10:
        person = conn.execute(
            "select * from people where phone = %s and portal_token is not null", ("+1" + digits,)
        ).fetchone()
    elif token:
        person = conn.execute("select * from people where portal_token = %s", (token,)).fetchone()
    if not person or (person["is_tester"] and not db.is_allowed(conn, person["phone"])):
        return NOT_FOUND, 404

    tz = _tz(person)
    rows = conn.execute(
        """select * from appointments
           where person_id = %s and status = 'scheduled' and starts_at > now()
           order by starts_at""",
        (person["id"],),
    ).fetchall()

    slot_rows = conn.execute(
        """select provider, starts_at from open_slots
           where person_id = %s and not taken and starts_at > now()
           order by starts_at""",
        (person["id"],),
    ).fetchall()
    slots_by_provider = {}
    for sr in slot_rows:
        lst = slots_by_provider.setdefault(sr["provider"], [])
        if len(lst) < 6:
            st = sr["starts_at"].astimezone(tz)
            lst.append(st.strftime("%a %b %-d · %-I:%M %p"))

    appts = []
    for r in rows:
        t = r["starts_at"].astimezone(tz)
        appts.append({
            "title": r["title"],
            "month": t.strftime("%b"),
            "day": t.day,
            "weekday": t.strftime("%a"),
            "time": t.strftime("%-I:%M %p"),
            "where": [p for p in (r["provider"], r["location"]) if p],
            "provider": r["provider"],
            "slots": slots_by_provider.get(r["provider"], []),
        })

    html = render_template_string(
        PAGE,
        name=person["name"] or "Patient",
        last4=person["phone"][-4:],
        updated=datetime.now(tz).strftime("%-I:%M %p"),
        appts=appts,
    )
    return html, 200
