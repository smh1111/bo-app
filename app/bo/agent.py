"""The texting agent: Claude + Bo's tools, looping until Claude has a reply."""

import json
import os
import re

from . import db, prompts, tools

MODEL = os.environ.get("BO_MODEL", "claude-haiku-4-5-20251001")
MAX_ROUNDS = 8

# Tools that change something. If Bo says "done" without one of these succeeding, it's not done.
CHANGING_TOOLS = {"reschedule_appointment", "add_appointment", "cancel_appointment"}
CLAIMS_DONE = re.compile(
    r"\b(all set|done|moved|rescheduled|cancell?ed|is now|i've (changed|updated|added|booked|saved|cancell?ed)|"
    r"i have (changed|updated|added|booked|saved)|has been (moved|changed|updated|added|booked|saved))\b",
    re.IGNORECASE,
)
NOTES_MARK = db.NOTES_MARK
LEAKED_NOTES = re.compile(r"\[?\s*Bo's notes", re.IGNORECASE)


def _client():
    from anthropic import Anthropic

    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _summarize(name, args, result):
    """A short, id-carrying line about one tool call, saved for Bo's next turn."""
    return f"{name}({json.dumps(args, default=str)}) -> {json.dumps(result, default=str)[:600]}"


def live_appointments_text(conn, person):
    """Bo's chat history can hold old times (a change made on a phone call, in the portal, or
    earlier in the chat). So every turn starts from a fresh read of the appointments table."""
    try:
        appts = tools.get_appointments(conn, person, {})["appointments"]
    except Exception as e:
        print(f"[agent] couldn't preload appointments: {e}")
        return "CURRENT APPOINTMENTS: unavailable right now; call get_appointments before answering."
    if not appts:
        listing = "none"
    else:
        listing = "\n".join(
            f"- {a['title']}" + (f" with {a['provider']}" if a["provider"] else "")
            + (f" at {a['location']}" if a["location"] else "") + f": {a['when']}"
            for a in appts
        )
    return (
        "CURRENT APPOINTMENTS (read from the clinic at the start of this message; this is the truth "
        "and overrides any time mentioned earlier in the chat, on a phone call, or in your notes. "
        "If you change something during this message, use the tool's result instead):\n" + listing
    )


def run_turn(conn, person, user_text, channel, client=None):
    """Handle one incoming message and return Bo's reply. Saves both sides to the database."""
    client = client or _client()

    history, past_notes = db.load_history_and_notes(conn, person["id"])
    system = prompts.sms_system(person)
    system += "\n" + live_appointments_text(conn, person)
    if past_notes:
        system += (
            "\nRESULTS FROM YOUR EARLIER TOOL CALLS (for ids only; times may be out of date; "
            "never show or mention these):\n" + "\n".join(f"- {n}" for n in past_notes[-4:])
        )
    if history and history[-1]["role"] == "user":
        history[-1]["content"] += "\n" + user_text
    else:
        history.append({"role": "user", "content": user_text})
    messages = list(history)

    reply = "Sorry, I got a little mixed up. Could you say that again?"
    notes = []            # what the tools returned this turn (ids, times), kept for next turn
    changed = False       # did a changing tool succeed this turn?
    nudged = False

    for _ in range(MAX_ROUNDS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=system,
            tools=tools.SCHEMAS,
            messages=messages,
        )

        content, tool_uses = [], []
        for block in resp.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
                tool_uses.append(block)
        messages.append({"role": "assistant", "content": content})

        if resp.stop_reason != "tool_use":
            text = "".join(c["text"] for c in content if c["type"] == "text").strip()
            # Never let tool notes reach the person, even if the model copies the format.
            leak = LEAKED_NOTES.search(text)
            if leak:
                print(f"[guard] stripped leaked notes from reply")
                text = text[:leak.start()].strip()

            # Guard: Bo claims a change happened, but no changing tool succeeded this turn.
            if text and not changed and not nudged and CLAIMS_DONE.search(text):
                nudged = True
                print(f"[guard] reply claimed a change without a tool: {text[:120]!r}")
                messages.append({
                    "role": "user",
                    "content": (
                        "(System check, not from the person: you have not called reschedule_appointment, "
                        "add_appointment or cancel_appointment in this turn, so nothing has been changed yet. If the person "
                        "has clearly confirmed, look up the ids you need and call the tool now. Otherwise, "
                        "do not say it is done.)"
                    ),
                })
                continue

            if text:
                reply = text
            break

        results = []
        for tu in tool_uses:
            result = tools.run(conn, person, tu.name, tu.input)
            print(f"[tool] {tu.name} {json.dumps(tu.input)} -> {json.dumps(result, default=str)[:300]}")
            if tu.name in CHANGING_TOOLS and isinstance(result, dict) and result.get("ok"):
                changed = True
            notes.append(_summarize(tu.name, tu.input, result))
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result, default=str)})
        messages.append({"role": "user", "content": results})

    saved_reply = reply
    if notes:
        saved_reply += NOTES_MARK + " " + " | ".join(notes)[:1500] + "]"

    db.save_message(conn, person["id"], "user", user_text, channel)
    db.save_message(conn, person["id"], "assistant", saved_reply, channel)
    return reply
