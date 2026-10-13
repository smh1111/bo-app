"""Bo — Flask app for Vercel.

Routes
  GET  /api/health             is the app up, can it reach the database?
  POST /api/sms                Twilio webhook for SMS and the WhatsApp Sandbox
  POST /api/voice/init         ElevenLabs: "who is calling?" (while the phone rings)
  POST /api/tools/<name>       ElevenLabs: run one of Bo's tools during a call
  POST /api/voice/post-call    ElevenLabs: save the transcript after the call
"""

import hashlib
import hmac
import json
import os
import time

from flask import Flask, Response, abort, jsonify, request

from bo import agent, db, prompts, tools

app = Flask(__name__)


# ── helpers ───────────────────────────────────────────────────────────────
def twiml(message=None):
    from twilio.twiml.messaging_response import MessagingResponse

    r = MessagingResponse()
    if message:
        r.message(message)
    return Response(str(r), mimetype="text/xml")


def twilio_request_is_valid():
    if os.environ.get("SKIP_TWILIO_SIGNATURE") == "1":
        return True
    from twilio.request_validator import RequestValidator

    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    host = request.headers.get("X-Forwarded-Host", request.host)
    url = f"https://{host}{request.full_path.rstrip('?')}"
    signature = request.headers.get("X-Twilio-Signature", "")
    return RequestValidator(token).validate(url, request.form.to_dict(), signature)


def send_reply(text, to, from_):
    """Send via Twilio's REST API so a slow turn isn't lost; fall back to a TwiML reply."""
    sid, token = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
    if sid and token:
        try:
            from twilio.rest import Client

            Client(sid, token).messages.create(to=to, from_=from_, body=text)
            return twiml()
        except Exception as e:
            print(f"[send] REST send failed, falling back to TwiML: {e}")
    return twiml(text)


def tool_secret_ok():
    expected = os.environ.get("BO_TOOL_SECRET", "")
    given = request.headers.get("X-Bo-Secret", "")
    return bool(expected) and hmac.compare_digest(expected, given)


def elevenlabs_signature_ok(raw_body, header):
    """Same check as the ElevenLabs SDK: header 't=<ts>,v0=<hmac_sha256(secret, ts.body)>'."""
    secret = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")
    if not secret or not header:
        return False
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts, sig = parts.get("t"), parts.get("v0")
    if not ts or not sig:
        return False
    try:
        if int(ts) < time.time() - 30 * 60:
            return False
    except ValueError:
        return False
    digest = hmac.new(secret.encode(), f"{ts}.{raw_body}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, sig)


def upcoming_summary(conn, person):
    appts = tools.get_appointments(conn, person, {})["appointments"][:3]
    if not appts:
        return "none on the calendar"
    return "; ".join(f"{a['title']} with {a['provider']}, {a['when']}" for a in appts)


# ── routes ────────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/api/health")
def health():
    try:
        with db.connect() as conn:
            conn.execute("select 1")
        return jsonify(ok=True, database=True)
    except Exception as e:
        return jsonify(ok=False, database=False, error=str(e)), 500


@app.post("/api/sms")
def sms():
    if not twilio_request_is_valid():
        abort(403)

    sender = request.form.get("From", "")        # e.g. whatsapp:+15555550123
    bo_number = request.form.get("To", "")       # the sandbox or Twilio number
    body = (request.form.get("Body") or "").strip()
    channel = "whatsapp" if sender.startswith("whatsapp:") else "sms"
    phone = db.normalize_phone(sender)

    if not db.is_allowed(phone):
        print(f"[sms] ignored message from {phone} (not in ALLOWED_NUMBERS)")
        return twiml()

    with db.connect() as conn:
        person = db.get_or_create_person(conn, phone)

        if not person["consented_at"]:
            if body.strip(" .!").upper() in {"YES", "Y", "YES PLEASE", "OK", "OKAY"}:
                db.set_consent(conn, person["id"])
                reply = prompts.WELCOME
            else:
                reply = prompts.CONSENT_PROMPT
            db.save_message(conn, person["id"], "user", body, channel)
            db.save_message(conn, person["id"], "assistant", reply, channel)
        else:
            reply = agent.run_turn(conn, person, body, channel)

    return send_reply(reply, to=sender, from_=bo_number)


@app.post("/api/voice/init")
def voice_init():
    if not tool_secret_ok():
        abort(401)
    data = request.get_json(force=True, silent=True) or {}
    phone = db.normalize_phone(data.get("caller_id", ""))

    with db.connect() as conn:
        if not db.is_allowed(phone):
            person, status = None, "blocked"
        else:
            person = db.get_or_create_person(conn, phone)
            status = "yes" if person["consented_at"] else "no"
            db.record_call(conn, data.get("conversation_id"), person["id"])

        name = (person or {}).get("name") or "there"
        if status == "yes":
            first = f"Hi {name}, it's Bo. How can I help today?"
            upcoming = upcoming_summary(conn, person)
            today = prompts.today_text(person)
        elif status == "no":
            first = (f"Hi {name}, this is Bo. I help people keep track of their doctor appointments. "
                     "Is it okay with you if I help look after yours?")
            upcoming, today = "not shared until they agree", prompts.today_text(person)
        else:
            first = "Hi, this is Bo. This line isn't open yet, so I can't help on this call. Goodbye!"
            upcoming, today = "none", ""

    return jsonify({
        "type": "conversation_initiation_client_data",
        "dynamic_variables": {"name": name, "consented": status, "upcoming": upcoming, "today": today},
        "conversation_config_override": {"agent": {"first_message": first}},
    })


@app.post("/api/tools/<name>")
def voice_tool(name):
    if not tool_secret_ok():
        abort(401)
    args = request.get_json(force=True, silent=True) or {}
    phone = db.normalize_phone(str(args.pop("caller_phone", "")))
    if not db.is_allowed(phone):
        return jsonify(error="This caller isn't allowed to use Bo."), 403

    with db.connect() as conn:
        person = db.person_by_phone(conn, phone)
        if not person:
            return jsonify(error="Unknown caller."), 403
        if name != "record_consent" and not person["consented_at"]:
            return jsonify(error="Ask the caller for permission first, then call record_consent.")
        result = tools.run(conn, person, name, args)
    print(f"[voice tool] {name} {json.dumps(args)} -> {json.dumps(result, default=str)[:300]}")
    return Response(json.dumps(result, default=str), mimetype="application/json")


@app.post("/api/voice/post-call")
def voice_post_call():
    raw = request.get_data(as_text=True)
    if not elevenlabs_signature_ok(raw, request.headers.get("ElevenLabs-Signature", "")):
        abort(401)
    event = json.loads(raw)
    if event.get("type") != "post_call_transcription":
        return jsonify(ok=True, ignored=event.get("type"))

    data = event.get("data") or {}
    with db.connect() as conn:
        person = db.person_for_call(conn, data.get("conversation_id"))
        if not person:
            dyn = ((data.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {})
            phone = db.normalize_phone(dyn.get("system__caller_id", ""))
            person = db.person_by_phone(conn, phone) if phone else None
        if not person:
            print(f"[post-call] no person for conversation {data.get('conversation_id')}")
            return jsonify(ok=True, saved=0)

        saved = 0
        for turn in data.get("transcript") or []:
            role = "user" if turn.get("role") == "user" else "assistant"
            text = turn.get("message")
            if text:
                db.save_message(conn, person["id"], role, text, "voice")
                saved += 1
    return jsonify(ok=True, saved=saved)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
