"""The texting agent: Claude + Bo's tools, looping until Claude has a reply."""

import json
import os

from . import db, prompts, tools

MODEL = os.environ.get("BO_MODEL", "claude-haiku-4-5-20251001")
MAX_ROUNDS = 8


def _client():
    from anthropic import Anthropic

    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def run_turn(conn, person, user_text, channel, client=None):
    """Handle one incoming message and return Bo's reply. Saves both sides to the database."""
    client = client or _client()

    history = db.load_history(conn, person["id"])
    if history and history[-1]["role"] == "user":
        history[-1]["content"] += "\n" + user_text
    else:
        history.append({"role": "user", "content": user_text})
    messages = list(history)

    reply = "Sorry, I got a little mixed up. Could you say that again?"
    for _ in range(MAX_ROUNDS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=prompts.sms_system(person),
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
            if text:
                reply = text
            break

        results = []
        for tu in tool_uses:
            result = tools.run(conn, person, tu.name, tu.input)
            print(f"[tool] {tu.name} {json.dumps(tu.input)} -> {json.dumps(result, default=str)[:300]}")
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result, default=str)})
        messages.append({"role": "user", "content": results})

    db.save_message(conn, person["id"], "user", user_text, channel)
    db.save_message(conn, person["id"], "assistant", reply, channel)
    return reply
