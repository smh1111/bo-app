# ElevenLabs tool setup for "Bo (voice)"

Add these 5 tools in the agent: **Tools → Add tool → Webhook**.
Every tool uses the same settings except the name, URL ending and parameters.

Replace `<your-project>` with your Vercel address.

## Settings shared by all 5 tools

| Field | Value |
|---|---|
| Method | `POST` |
| URL | `https://<your-project>.vercel.app/api/tools/<tool name>` |
| Header | `X-Bo-Secret`, type **Secret**, value = your `BO_TOOL_SECRET` |
| Body parameter | `caller_phone`, type string, value type **Dynamic variable** → `system__caller_id` |

`caller_phone` must come from the caller ID, never from the AI. That's what stops someone from saying "I'm calling for another number."

## The 5 tools

### 1. get_appointments
- **Description:** List the caller's upcoming appointments. Use before talking about any appointment.
- **Extra parameters:** none.

### 2. get_available_slots
- **Description:** Get open times with the same doctor for one of the caller's appointments.
- **Extra parameters:**
  - `appointment_id`, number, LLM-filled: "The appointment_id from get_appointments."

### 3. reschedule_appointment
- **Description:** Move an appointment to an open time. Only use after the caller clearly said yes to that exact new time.
- **Extra parameters:**
  - `appointment_id`, number, LLM-filled: "The appointment_id from get_appointments."
  - `slot_id`, number, LLM-filled: "The slot_id from get_available_slots for the time the caller chose."

### 4. add_appointment
- **Description:** Save an appointment the caller tells you about. Only use after repeating the details and getting a yes.
- **Extra parameters:**
  - `title`, string, LLM-filled, required: "What the appointment is, like Eye exam."
  - `when`, string, LLM-filled, required: "Local date and time in ISO format, like 2026-10-20T15:00. Use today's date from the prompt to work it out."
  - `provider`, string, LLM-filled, optional: "Doctor or clinic name, if the caller said it."
  - `location`, string, LLM-filled, optional: "Where it is, if the caller said it."

### 5. record_consent
- **Description:** Save that the caller agreed to let Bo help with their appointments. Use only after they clearly say yes.
- **Extra parameters:** none.

## Also turn on
- **System tools → End call**, so Bo can hang up politely.

## Dynamic variables used in the prompt
`{{name}}`, `{{consented}}`, `{{upcoming}}`, `{{today}}`. They're filled in by `/api/voice/init` when someone calls. For browser tests, give them placeholder values in the agent's dynamic variables section, for example name = Shama, consented = yes, upcoming = Dental cleaning Friday at 2 PM, today = Tuesday, October 13.
