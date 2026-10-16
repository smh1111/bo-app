# Bo app

Bo over WhatsApp (Twilio Sandbox) and phone calls (ElevenLabs), running on Vercel with a Neon Postgres database.

```
app.py                  Flask routes (Vercel finds this automatically)
bo/agent.py             texting brain: Claude + tools loop
bo/tools.py             the 5 appointment tools, shared by texting and calling
bo/db.py                database helpers, phone-number allowlist
bo/prompts.py           Bo's instructions (texting + voice)
sql/schema.sql          create the tables (run once)
sql/reset_demo.sql      fill in made-up appointments for you (run before each demo)
sql/migrate_testers.sql one-time upgrade for tester sign-up
sql/cleanup_testers.sql delete testers older than 24 hours (Bo also does this itself)
bo/demo.py              tester sign-up from trustbo.ai + their sample appointments
bo/portal.py            the pretend "My HealthChart" portal page each tester sees
elevenlabs/             the voice prompt and tool setup to paste into ElevenLabs
requirements.txt        Python packages
```

## Deploy

### 1. Put the code on GitHub (no git needed)
1. Go to github.com/new. Name it `bo-app`, choose **Private**, click **Create repository**.
2. On the next page click **uploading an existing file**.
3. Drag everything *inside* this folder (app.py, requirements.txt, README.md and the `bo`, `sql`, `elevenlabs` folders) into the page. Click **Commit changes**.

### 2. Create the Vercel project
1. Go to vercel.com and sign up with GitHub (Hobby plan).
2. **Add New → Project**, find `bo-app`, click **Import**. If it isn't listed, click "Adjust GitHub App permissions" and give Vercel access to `bo-app`.
3. Leave the settings as they are and click **Deploy**. Vercel should recognise it as Flask.
4. When it finishes, note your address, e.g. `bo-app-xyz.vercel.app`. Use the **production** address shown on the project page, not the long one with random letters for a single deployment.

The health page will say the database is missing. That's expected until step 3.

### 3. Add the Neon database
1. In the Vercel project, open **Storage → Create Database → Neon**. Pick the **Free** plan and the region closest to Vercel's default, Washington D.C. (`iad1`), then connect it to the project. Vercel adds `DATABASE_URL` for you.
2. Click **Open in Neon**, go to **SQL Editor**, paste all of `sql/schema.sql` and click **Run**.
3. Open `sql/reset_demo.sql`, change your phone number, name and time zone on the three lines marked `<-`, paste it into the SQL Editor and click **Run**.

### 4. Add the secrets
In Vercel go to **Settings → Environment Variables** and add:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your `sk-ant-...` key |
| `TWILIO_ACCOUNT_SID` | Twilio Console home page → Account Info |
| `TWILIO_AUTH_TOKEN` | same place, click Show |
| `ALLOWED_NUMBERS` | your mobile, e.g. `+15551234567` (comma-separate several) |
| `BO_TOOL_SECRET` | any long random string you make up (used by ElevenLabs) |

Then **Deployments → the latest one → ⋯ → Redeploy**. New variables only apply after a redeploy.

### 5. Check it's alive
Open `https://<your-project>.vercel.app/api/health`. You should see `{"database": true, "ok": true}`.

### 6. Connect WhatsApp
1. Twilio Console → **Messaging → Try it out → Send a WhatsApp message → Sandbox settings**.
2. **When a message comes in:** `https://<your-project>.vercel.app/api/sms`, method **POST**. Save.
3. On your phone, WhatsApp the sandbox number: `Hi`. Bo asks for consent. Reply `YES`, then try "What appointments do I have?" and "Can you move my dentist appointment?"

### 7. Connect calling (ElevenLabs)
Follow the voice build plan. You'll need:
- `elevenlabs/voice_prompt.txt`, to paste as the agent's system prompt.
- `elevenlabs/tools.md`, for the 5 webhook tools.
- Conversation initiation webhook: `https://<your-project>.vercel.app/api/voice/init` with header `X-Bo-Secret`.
- Post-call webhook: `https://<your-project>.vercel.app/api/voice/post-call`. Put its signing secret in Vercel as `ELEVENLABS_WEBHOOK_SECRET` and redeploy.

## Tester sign-up ("Try the live demo" on trustbo.ai)
Anyone can sign up on trustbo.ai with a US mobile number. Bo's app then:
- creates them as a tester (they're let in alongside `ALLOWED_NUMBERS`),
- gives them 3 sample appointments and their own open slots,
- returns a private portal link: `https://<your-project>.vercel.app/portal/<code>`.

Optional settings in Vercel → Environment Variables (redeploy after changing):

| Name | What it does |
|---|---|
| `TESTER_CAP` | Max testers at once. Default `25`. |
| `TESTER_TTL_HOURS` | How long a tester can use Bo before they're deleted. Default `24`. |
| `WHATSAPP_JOIN_CODE` | Your sandbox join code. Default `join away-new`. Set it if Twilio gives you a new one. |
| `BO_PHONE_NUMBER` | Number testers call. Default `+16506093471`. |
| `PORTAL_BASE_URL` | Set to `https://portal.trustbo.ai` once that address points at Vercel. Until then portal links use `/portal/<code>` on Bo's Vercel address. |
| `SIGNUP_ORIGINS` | Extra websites allowed to use the sign-up form, comma-separated. trustbo.ai is already allowed. |

See who signed up: `select name, phone, created_at from people where is_tester order by created_at desc;`
Testers are cut off after 24 hours and deleted on the next sign-up or the daily cleanup (`vercel.json`), whichever comes first. Portal links look like `/portal/4155550142`.

## When something breaks
- **No reply on WhatsApp:** Twilio Console → **Monitor → Logs → Errors**. Error 11200 means Bo's address failed or answered with an error.
- **Bo answered 403:** the Twilio signature check failed, usually because the sandbox URL doesn't exactly match your production address. To test, add `SKIP_TWILIO_SIGNATURE` = `1` in Vercel, redeploy, and remove it again afterwards.
- **Bo errored:** Vercel → your project → **Logs**. Tool calls are logged as `[tool]` and `[voice tool]`.
- **Start the demo over:** run `sql/reset_demo.sql` again.
- **Sandbox stopped answering after a few days:** WhatsApp `join <your-code>` to the sandbox number again.
