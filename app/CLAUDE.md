# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Bo is a prototype assistant that helps an older adult manage doctor appointments over WhatsApp/SMS (Twilio) and phone calls (ElevenLabs Conversational AI). It is a small Flask app deployed on Vercel with a Neon Postgres database. The `appointments` and `open_slots` tables stand in for a clinic portal and are filled with made-up data by `sql/reset_demo.sql`.

The README is a click-by-click deploy guide written for someone who doesn't use git: code reaches GitHub by drag-and-drop upload, and Vercel deploys from there. This folder is not a git repo.

## Commands

There are no tests, linter or build step.

```sh
pip install -r requirements.txt
DATABASE_URL=postgres://... ANTHROPIC_API_KEY=... python app.py   # Flask dev server on :5000
```

- Health check: `GET /api/health` returns `{"ok": true, "database": true}`.
- Database setup: run `sql/schema.sql` once (idempotent). Run `sql/reset_demo.sql` before each demo. It wipes that person's messages/calls/appointments and all `open_slots`, then reseeds relative to today. Edit the three `<-` lines first.
- Env vars: `DATABASE_URL` (or `POSTGRES_URL`), `ANTHROPIC_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `ALLOWED_NUMBERS` (comma-separated), `BO_TOOL_SECRET`, `ELEVENLABS_WEBHOOK_SECRET`. Optional: `BO_MODEL` (defaults to Haiku 4.5 in `bo/agent.py`), `TESTER_CAP`, `WHATSAPP_JOIN_CODE`, `BO_PHONE_NUMBER`, `SIGNUP_ORIGINS`, and `SKIP_TWILIO_SIGNATURE=1` for debugging only.
- Tester upkeep: `sql/migrate_testers.sql` (one-time upgrade), `sql/cleanup_testers.sql` (delete testers older than 14 days).
- On Vercel, new env vars only take effect after a redeploy.

## Architecture

There are two channels, and both share one tool layer and one message history.

- **Texting** (`POST /api/sms`): Twilio webhook → signature check → allowlist → consent gate (handled in `app.py` with fixed strings from `prompts.py`, no LLM) → `agent.run_turn`. Here the Claude tool loop runs on our server. The reply goes out through the Twilio REST API, falling back to TwiML so a slow turn isn't lost.
- **Voice**: ElevenLabs runs the LLM itself. Our server only provides webhooks:
  - `/api/voice/init` fills the dynamic variables `name`, `consented`, `upcoming` and `today`, plus the first message.
  - `/api/tools/<name>` runs one tool. It is authenticated by the `X-Bo-Secret` header.
  - `/api/voice/post-call` saves the transcript into `messages`. It is HMAC-verified, and it finds the person through the `calls` table.

### Things that span several files

- **Adding or changing a tool** touches up to four places:
  - the function and the `TOOLS` dict in `bo/tools.py`
  - `SCHEMAS` in `bo/tools.py` (texting)
  - `elevenlabs/tools.md` (voice; configured by hand in the ElevenLabs UI, nothing in code)
  - `CHANGING_TOOLS` in `bo/agent.py`, if the tool modifies data

  `record_consent` is voice-only on purpose. It isn't in `SCHEMAS` because texting handles consent in `app.py`.
- **The voice prompt exists twice:** `VOICE_PROMPT` in `bo/prompts.py` and `elevenlabs/voice_prompt.txt` (the copy that gets pasted into ElevenLabs). Keep them identical. Its `{{vars}}` must match what `/api/voice/init` returns.
- **Security model:** every tool is scoped to one `person`, resolved from the phone number and never from LLM input. On voice calls, `caller_phone` is injected from ElevenLabs' `system__caller_id` and popped from the args before the tool runs. Each entry point also checks `db.is_allowed(conn, phone)` (`ALLOWED_NUMBERS` or a signed-up tester) and consent. Keep these invariants when editing routes or tools.
- **Tester sign-up:** `POST /api/signup` (CORS-limited to trustbo.ai, see `SIGNUP_ORIGINS` in `app.py`) calls `bo/demo.py`: creates a person with `is_tester`, `consented_at` and a random `portal_token`, then seeds 3 appointments and 9 open slots for them (weekdays only). Capped by `TESTER_CAP`. Testers expire after `TESTER_TTL_HOURS` (default 24): `db.is_allowed` and the portal stop accepting them, and they're deleted on the next sign-up or by the daily Vercel Cron (`vercel.json` → `/api/cron/cleanup`, optional `CRON_SECRET`). `GET /portal/<10-digit phone>` (or `portal.trustbo.ai/<phone>`, routed in `portal_subdomain`; older random codes still work) (`bo/portal.py`) renders, with view-only open times per appointment, the read-only "Maple Health" portal from the same `appointments` table the tools change. `open_slots.person_id` scopes slots to one person, so testers never share slots.
- **Memory across turns (`bo/agent.py`):** history comes from the `messages` table (last 30 rows, consecutive same-role rows merged, voice rows prefixed `(On a phone call)`). Tool results are not stored as tool blocks. Instead, a summary that includes ids is appended to the saved assistant message after `NOTES_MARK`, so the next turn can reuse ids. `db.load_history_and_notes` strips those notes out of the history and the agent passes the last few to the model in the system prompt instead (if the model saw them inside its own past replies, it copied the format). As a backstop, `agent.py` cuts anything from "Bo's notes" onward out of a reply before sending.
- **Hallucinated-action guard:** if the final text matches `CLAIMS_DONE` but no tool in `CHANGING_TOOLS` returned `ok: true` this turn, the loop adds a one-time "system check" user message and retries.
- **Tool conventions:** tools return JSON-able dicts. Changing tools return `{"ok": bool, ...}`, and errors come back as `{"error": ...}` instead of raising (`tools.run` catches exceptions). Times are stored as `timestamptz` and shown through `say_time` in the person's time zone. A naive ISO time passed to `add_appointment` is read in the person's time zone. `reschedule_appointment` locks the slot, marks it taken and puts the old time back into `open_slots`, all in one transaction.
- **Connections:** one short-lived autocommit psycopg connection per request (`db.connect()`), because the app is serverless.
- **Logging:** tool calls print `[tool]` (texting) or `[voice tool]`. These logs show up in Vercel's Logs.
