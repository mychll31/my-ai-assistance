# Telegram Calendar & Gmail Bot

A personal AI assistant Telegram bot that manages your Google Calendar and Gmail using natural language and voice messages.

**Features:**
- Create calendar events (including recurring) by describing them naturally
- Warns when a new event overlaps something already on your calendar
- Track to-dos in Google Tasks — add, list, and complete them from Telegram
- A daily digest of what's due today
- Check and read unread Gmail messages
- Reply to and compose emails
- Voice message support (transcribed via Whisper)
- Runs on Vercel (serverless) or locally

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create Your Telegram Bot](#2-create-your-telegram-bot)
3. [Set Up Google Cloud Project](#3-set-up-google-cloud-project)
4. [Set Up Zoom (Optional)](#4-set-up-zoom-optional)
5. [Local Installation](#5-local-installation)
6. [Deploy to Vercel](#6-deploy-to-vercel)
7. [Connect Google Account](#7-connect-google-account)
8. [Environment Variables Reference](#8-environment-variables-reference)
9. [Usage Guide](#9-usage-guide)
10. [How It's Wired](#10-how-its-wired)
11. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

Make sure you have the following installed before starting:

- **Python 3.13+** — [download](https://www.python.org/downloads/)
- **Git** — [download](https://git-scm.com/)
- **Vercel CLI** (for deployment) — install after Node.js:
  ```bash
  npm install -g vercel
  ```
- A **Telegram account**
- A **Google account** (the one whose Calendar and Gmail you want to manage)
- An **Anthropic API key** — [get one](https://console.anthropic.com/)
- A **Groq API key** (free, for voice transcription) — [get one](https://console.groq.com/)

---

## 2. Create Your Telegram Bot

### 2.1 Create the bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Enter a display name (e.g. `My Assistant`)
4. Enter a username ending in `bot` (e.g. `myassistant_bot`)
5. BotFather will reply with your **bot token** — looks like:
   ```
   8720726913:AAEqnXdOxvwmkot4rAZ5b9iW1uvnYTEcPL
   ```
   Save this — you'll need it as `TELEGRAM_BOT_TOKEN`.

### 2.2 Get your Telegram user ID

1. Search for **@userinfobot** on Telegram
2. Send `/start`
3. It will reply with your numeric **user ID** (e.g. `123456789`)

   Save this as `AUTHORIZED_USER_ID` — it restricts the bot to only respond to you.

---

## 3. Set Up Google Cloud Project

### 3.1 Create a project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top → **New Project**
3. Name it (e.g. `telegram-bot`) → **Create**
4. Make sure the new project is selected in the dropdown

### 3.2 Enable APIs

Three APIs must be enabled. Go to [APIs & Services → Library](https://console.cloud.google.com/apis/library),
search for each by name, and click **Enable**:

| API | Needed for |
|---|---|
| **Google Calendar API** | Creating events, conflict detection |
| **Gmail API** | Reading, replying to, and sending mail |
| **Google Tasks API** | To-dos, `/tasks`, `/done`, the daily digest |

> **Don't skip Google Tasks API.** A disabled API returns HTTP **403** — the same
> status as an unauthorized token — so it presents as a credentials problem when it
> isn't. If task commands report an authorization error, verify this first. The error
> text contains `has not been used in project <number>` when the API is the cause.

### 3.3 Configure the OAuth consent screen

1. Go to [APIs & Services → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
2. Select **External** → **Create**
3. Fill in the required fields:
   - **App name**: `Telegram Bot` (anything works)
   - **User support email**: your email
   - **Developer contact email**: your email
4. Click **Save and Continue**
5. On the **Scopes** step, click **Add or Remove Scopes** and add:
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/tasks`
6. Click **Update** → **Save and Continue**
7. On the **Test Users** step, click **Add Users** and add your Google account email
8. Click **Save and Continue** → **Back to Dashboard**

### 3.3b Publish the app

On the same consent screen — newer consoles label this **Google Auth Platform →
Audience** — set **Publishing status** to **In production**.

> **Do not leave the app in Testing.** Refresh tokens issued while an app is in
> Testing mode **expire after 7 days**. The bot will stop working weekly and you'll
> re-run the whole `/auth` dance every time. Publishing removes the expiry.
>
> You do **not** need Google verification for personal use. You'll see an
> "unverified app" warning at consent — click **Advanced → Go to [app name]** — and
> there's a 100-user cap you will never approach. `gmail.modify` is a *restricted*
> scope, so Google may prompt about verification; you can ignore that for a
> personal bot.
>
> If you leave it in Testing, the account you sign in with **must** be on the Test
> Users list, or consent fails with `Error 403: access_denied`.

### 3.4 Create OAuth credentials

1. Go to [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click **Create Credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Name: `Telegram Bot` (anything)
5. Under **Authorized redirect URIs**, add your callback URL:
   - **For Vercel deployment**: `https://your-app-name.vercel.app/api/callback`
   - **For local development**: `http://localhost:8080/oauth/callback`
   
   > You can add both — just separate entries.
6. Click **Create**
7. A dialog shows your credentials — copy and save:
   - **Client ID** → `GOOGLE_CLIENT_ID`
   - **Client Secret** → `GOOGLE_CLIENT_SECRET`

---

## 4. Set Up Zoom (Optional)

Skip this if you don't want Zoom links. Without it everything else works, and a
"zoom" request creates the calendar event with a note that Zoom isn't configured.

### 4.1 Create a Server-to-Server OAuth app

1. Go to [marketplace.zoom.us](https://marketplace.zoom.us) → **Develop** → **Build App**
2. Choose **Server-to-Server OAuth**

   > Not a *user* OAuth app. Server-to-Server needs no consent flow and no refresh
   > tokens — three static credentials is the whole story, which is the right shape
   > for a bot only you use.
3. Name it anything, then **Create**
4. On the **App Credentials** page copy all three values:

   | Zoom shows | Goes in |
   |---|---|
   | Account ID | `ZOOM_ACCOUNT_ID` |
   | Client ID | `ZOOM_CLIENT_ID` |
   | Client Secret | `ZOOM_CLIENT_SECRET` |

5. Fill in the **Information** tab (name, contact email) — Zoom won't let you activate
   until it's complete

### 4.2 Grant the meeting scope

On the **Scopes** tab → **Add Scopes** → search **meeting** → grant:

```
meeting:write:meeting:admin
```

The friendly UI labels this **"View and manage all user meetings"**.

> **Grant only this one.** A Server-to-Server token carries *every* scope the app
> holds, so a broad grant means a broadly-privileged secret. This bot creates
> meetings and nothing else — Account, Dashboard, and Data Request scopes are not
> needed and include things like sub-account deletion and ownership transfer.

### 4.3 Activate the app

**Activation** tab → **Activate your app**. Add scopes *before* activating.

### 4.4 Verify it works

Both setup steps fail differently, and the two errors look nothing alike:

| What you see | What it means |
|---|---|
| `invalid_client — The app has been disabled by the developer` on the token request | App not activated (4.3) |
| Token succeeds, then `code 4711 — Invalid access token, does not contain scopes: [meeting:write:meeting, meeting:write:meeting:admin]` | Meeting scope not granted (4.2) |
| In Telegram: *"Couldn't create the Zoom meeting — event added without a link."* | Either of the above — check the runtime logs for which |

To check both at once without going through the bot:

```bash
python3 - <<'EOF'
import base64, requests
ACCOUNT_ID, CLIENT_ID, CLIENT_SECRET = "...", "...", "..."
b = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
d = requests.post("https://zoom.us/oauth/token",
                  params={"grant_type": "account_credentials", "account_id": ACCOUNT_ID},
                  headers={"Authorization": f"Basic {b}"}, timeout=20).json()
print("token:", "OK" if "access_token" in d else d)
print("meeting scopes:", [s for s in d.get("scope", "").split() if s.startswith("meeting:")] or "NONE")
EOF
```

`token: OK` plus a non-empty meeting scope list means you're done.

### 4.5 Add the credentials

Locally, in `.env`; on Vercel, see [6.3](#63-add-environment-variables).

> Free Zoom accounts cap group meetings at 40 minutes. Deleting a calendar event
> does **not** delete the Zoom meeting it created.

---

## 5. Local Installation

### 5.1 Clone the repository

```bash
git clone https://github.com/your-username/telegram-calendar-bot.git
cd telegram-calendar-bot
```

### 5.2 Create a virtual environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows
```

### 5.3 Install dependencies

```bash
pip install -r requirements.txt
```

### 5.4 Create the `.env` file

Create a file named `.env` in the project root:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
AUTHORIZED_USER_ID=your_telegram_user_id
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
OAUTH_REDIRECT_URI=http://localhost:8080/oauth/callback
ANTHROPIC_API_KEY=your_anthropic_api_key
GROQ_API_KEY=your_groq_api_key
TIMEZONE=Asia/Manila
# GOOGLE_REFRESH_TOKEN=  # leave blank for now — added after first /auth

# Optional — Zoom links. See section 4. Omit and "zoom" requests still create the
# event, with a note that Zoom isn't configured.
ZOOM_ACCOUNT_ID=your_zoom_account_id
ZOOM_CLIENT_ID=your_zoom_client_id
ZOOM_CLIENT_SECRET=your_zoom_client_secret
```

Replace each value with your actual credentials.

### 5.5 Run the bot locally

```bash
python main.py
```

You should see:
```
Web server on :8080
Bot polling started
```

The bot now runs in **polling mode** — it continuously checks Telegram for new messages.

### 5.6 Connect Google (local)

Since the OAuth callback needs to be publicly reachable, you have two options:

**Option A — Use ngrok (recommended for local dev):**
1. Install ngrok: [ngrok.com](https://ngrok.com/)
2. Run: `ngrok http 8080`
3. Copy the `https://xxxx.ngrok.io` URL
4. Update `OAUTH_REDIRECT_URI` in `.env` to `https://xxxx.ngrok.io/oauth/callback`
5. Add the same URL to your Google OAuth credentials (step 3.4)
6. Send `/auth` in Telegram and complete the flow

**Option B — Deploy to Vercel first, then test locally against the Vercel callback:**
Skip ahead to Section 5, deploy, run `/auth` on Vercel, then come back to local dev.

---

## 6. Deploy to Vercel

### 6.1 Log in to Vercel

```bash
vercel login
```

Follow the browser prompt to authenticate.

### 6.2 Link the project

From inside the project directory:

```bash
vercel link
```

Answer the prompts:
- **Set up and deploy?** → Yes
- **Which scope?** → your account
- **Link to existing project?** → No (first time) / Yes (if already created)
- **Project name** → e.g. `telegram-bot`
- **Directory** → `./` (current directory)

This creates a `.vercel/project.json` file linking your local folder to the Vercel project.

### 6.3 Add environment variables

Add each variable to Vercel's production environment:

```bash
vercel env add TELEGRAM_BOT_TOKEN
vercel env add AUTHORIZED_USER_ID
vercel env add GOOGLE_CLIENT_ID
vercel env add GOOGLE_CLIENT_SECRET
vercel env add OAUTH_REDIRECT_URI
vercel env add ANTHROPIC_API_KEY
vercel env add GROQ_API_KEY
vercel env add TIMEZONE
vercel env add CRON_SECRET

# Optional — Zoom links, see section 4
vercel env add ZOOM_ACCOUNT_ID
vercel env add ZOOM_CLIENT_ID
vercel env add ZOOM_CLIENT_SECRET
```

For each command, paste the value when prompted and select **Production** (press Space to toggle, Enter to confirm).

`CRON_SECRET` is any random string — it authenticates the daily digest endpoint.
Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

> `GOOGLE_REFRESH_TOKEN` is added later — after the first `/auth` flow.

### 6.4 Deploy to production

```bash
vercel --prod
```

When the deploy completes, you'll see your production URL:
```
Production: https://your-app-name.vercel.app
```

### 6.5 Update the OAuth redirect URI

Now that you have your Vercel URL:

1. Go back to [Google Cloud → Credentials](https://console.cloud.google.com/apis/credentials)
2. Click your OAuth client ID
3. Under **Authorized redirect URIs**, make sure this is listed:
   ```
   https://your-app-name.vercel.app/api/callback
   ```
4. Click **Save**

Then update the env var in Vercel:

```bash
vercel env rm OAUTH_REDIRECT_URI production
vercel env add OAUTH_REDIRECT_URI
# paste: https://your-app-name.vercel.app/api/callback
```

Redeploy to apply:

```bash
vercel --prod
```

### 6.6 Register the Telegram webhook

Tell Telegram to send updates to your Vercel URL. Run this once:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-app-name.vercel.app/api/webhook"
```

Replace `<YOUR_BOT_TOKEN>` and `your-app-name` with your actual values.

Expected response:
```json
{"ok":true,"result":true,"description":"Webhook was set"}
```

Verify it's set correctly:
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

---

## 7. Connect Google Account

This step is done **once** after deployment. It authorizes the bot to access your Google Calendar and Gmail.

### 7.1 Start the auth flow

In Telegram, send your bot:
```
/auth
```

The bot replies with an authorization URL. Open it in your browser.

### 7.2 Authorize Google

1. Sign in with your Google account (the test user you added in step 3.3)
2. You may see a warning: **"Google hasn't verified this app"** — click **Continue**
3. Grant the requested permissions (Calendar and Gmail access)
4. You'll be redirected to a page saying **"Connected!"**

### 7.3 Save the refresh token

The bot will send you a Telegram message like:

```
Google Calendar connected!

Add this in Vercel → Settings → Environment Variables:

GOOGLE_REFRESH_TOKEN=1//0abc123...

Then redeploy. You only need to do this once.
```

Add this token to Vercel:

```bash
vercel env add GOOGLE_REFRESH_TOKEN
# paste the token value shown in Telegram
```

Then redeploy:

```bash
vercel --prod
```

### 7.4 Verify the connection

Send `/status` to your bot. It should reply:
```
Google Calendar & Gmail are connected.
```

---

## 8. Environment Variables Reference

| Variable | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | `8720726913:AAEq...` |
| `AUTHORIZED_USER_ID` | Your Telegram numeric user ID | `123456789` |
| `GOOGLE_CLIENT_ID` | OAuth client ID from Google Cloud | `386693...apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret from Google Cloud | `GOCSPX-...` |
| `OAUTH_REDIRECT_URI` | Must match what's in Google Cloud Console | `https://your-app.vercel.app/api/callback` |
| `GOOGLE_REFRESH_TOKEN` | Obtained after first `/auth` flow | `1//0abc...` |
| `ANTHROPIC_API_KEY` | For AI intent parsing (Claude) | `sk-ant-...` |
| `GROQ_API_KEY` | Voice transcription, and intent parsing if no other LLM key is set | `gsk_...` |
| `GROQ_MODEL` | Optional — override the Groq parsing model | `openai/gpt-oss-120b` |
| `CRON_SECRET` | Required for the daily task digest — any random string | `a7f3...` |
| `ZOOM_ACCOUNT_ID` | Optional — Zoom Server-to-Server OAuth app. See [section 4](#4-set-up-zoom-optional) | `YAeU...` |
| `ZOOM_CLIENT_ID` | Optional — same app | `jty2...` |
| `ZOOM_CLIENT_SECRET` | Optional — same app | `5wl4...` |
| `TIMEZONE` | Your local timezone | `Asia/Manila` |

> **You need at least one LLM key**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GROQ_API_KEY`. They're tried in that order.
> A `GROQ_API_KEY` on its own is enough to run the whole bot — it covers both transcription and parsing.
> Groq retires model IDs periodically; if parsing starts failing with a model error, set `GROQ_MODEL` rather than editing code.

> **Tasks also needs the Google Tasks API enabled** on your Google Cloud project —
> APIs & Services → Library → Google Tasks API → Enable. It is not on by default, and
> a disabled API fails with the same 403 as a missing scope.

> **Upgrading an existing install?** Tasks needs a Google scope your current token
> predates. Run `/auth` again, take the new token from the Telegram message, replace
> `GOOGLE_REFRESH_TOKEN` and redeploy. Until you do, task commands answer with a
> reminder to re-authorize. The digest schedule is UTC — `0 1 * * *` is 9am in
> UTC+8. On Vercel's Hobby plan crons fire within the hour, not on the minute.

---

## 9. Usage Guide

### Calendar

Just describe the event naturally:

| Message | What it does |
|---|---|
| `Meeting with Sarah tomorrow 2pm` | Creates a 1-hour event tomorrow at 2pm |
| `Dentist Friday 10am for 30 minutes` | Creates a 30-min event on Friday |
| `Team standup every weekday at 9am` | Creates a recurring weekday event |
| `Set meeting every Monday at 3pm with AI Labs` | Creates a weekly recurring Monday event |
| `Monthly review on the 1st at 2pm` | Creates a monthly recurring event |

**Conflict warnings.** The event is always created, but if it overlaps something
already on your primary calendar the confirmation says so:

```
Added!

Meeting with Belle
2026-08-28 15:00
https://calendar.google.com/...

⚠️ Conflicts with:
• Team offsite  (7:00 AM – 5:00 PM)
```

Events you've marked **Free** don't count, and back-to-back events (one ending at
3pm, the next starting at 3pm) aren't treated as overlapping. All-day events do
count. For a recurring event, only the first occurrence is checked.

### Tasks

Tasks live in Google Tasks, so they sync to your phone and the Calendar sidebar.

| Message | What it does |
|---|---|
| `Remind me to buy groceries Friday` | Adds a task due Friday |
| `Add a task to renew the domain` | Adds a task with no due date |
| `/tasks` | Lists your open tasks, numbered |
| `/done 2` | Marks task #2 finished |
| `Finished the groceries` | Marks the matching task finished by name |

**"Remind me to ..." is always a task**, even with a time on it. Meetings and
appointments go to the calendar. The reply tells you which it made — `Task added`
vs `Added!` with a timestamp — so a wrong guess is obvious immediately.

**Tasks have no time of day** — Google Tasks stores a due *date* only. If you say
"remind me to call the bank tomorrow at 3pm" it becomes a task due tomorrow with
`1pm` kept in the notes, and no alert fires at that time. Use a calendar event when
you need the alert.

Each morning a cron posts what's due today, including anything overdue. It stays
silent on a clear day.

### Zoom meetings

Say **"zoom"** and the bot books a real Zoom meeting and attaches the join link:

| Message | What it does |
|---|---|
| `Zoom with Belle tomorrow 3pm` | Creates the event *and* a Zoom meeting |
| `Team sync 2pm on zoom` | Same |
| `Meeting with Belle tomorrow 3pm` | Plain event, no Zoom |

The word **"zoom"** is the only trigger. "Call", "video", "online" and "remote" will
not book one — every booking is a real meeting on your Zoom account, so it is
deliberately opt-in. Deleting the calendar event does **not** delete the Zoom meeting.

If Zoom fails or isn't configured, the calendar event is still created and the reply
says why. A missing video link never costs you the entry.

### Email

| Command | What it does |
|---|---|
| `/inbox` | Shows your 5 most recent unread emails |
| `/read 2` | Reads the full body of email #2 |
| `/reply 2 Sure, I'll be there!` | Replies to email #2 |
| `Show my inbox` | Natural language — same as `/inbox` |
| `Reply to Sarah saying I'll be there` | AI figures out which email and sends the reply |

### Voice messages

Hold the microphone button in Telegram to send a voice message. The bot transcribes it and processes it the same as text.

### Commands

| Command | Description |
|---|---|
| `/start` | Show welcome message and feature overview |
| `/auth` | Get the Google authorization link |
| `/status` | Check if Google is connected |
| `/inbox` | Fetch unread emails |
| `/read <n>` | Read email number n |
| `/reply <n> <message>` | Reply to email number n |
| `/tasks` | List open tasks, numbered |
| `/done <n>` | Mark task number n finished |

---

## 10. How It's Wired

### Vercel runs `app.py`, not the `api/` folder

The Vercel project's framework preset is `python`, which serves **`app.py` as a single
Flask WSGI app**. Its endpoints — `/api/webhook`, `/api/callback`, `/api/cron`,
`/health` — are Flask **routes**, not files.

`api/webhook.py` and `api/callback.py` are `http.server` variants for other hosts.
**They never execute on Vercel.** Dropping a new `api/whatever.py` file in will 404
there no matter how correct the file is. To add an endpoint on Vercel, add an
`@app.route` to `app.py`.

| File | Runs on |
|---|---|
| `app.py` | Vercel (Flask), Fly.io |
| `api/webhook.py`, `api/callback.py` | Other `http.server` hosts |
| `main.py` | Local long-polling runner — **behind**: has calendar + conflicts, but no tasks or Zoom |
| `ai_parser.py`, `calendar_service.py`, `gmail_service.py`, `tasks_service.py`, `zoom_service.py` | Shared by all of the above |

Because the entry points are duplicated, a behavior change usually has to land in
more than one of them. The tests in `tests/test_tasks.py` are parametrized over both
`app` and `api.webhook` so the two cannot silently drift apart.

### Changing OAuth scopes

Refresh tokens are **scope-bound**. Adding a scope to `SCOPES` in
`calendar_service.py` does not extend a token you already hold. After any scope change:

1. Deploy the new scope list — `/auth` builds its consent URL from the *deployed* code
2. Run `/auth` in Telegram and re-consent
3. Replace `GOOGLE_REFRESH_TOKEN` in Vercel with the value the bot sends you
4. Redeploy so the new value is picked up

### The daily digest

`vercel.json` schedules `GET /api/cron` once a day.

- **Schedules are UTC.** `0 1 * * *` is 9:00 AM at UTC+8.
- On Vercel's **Hobby** plan, crons fire *within* the target hour rather than on the
  minute, and are capped at one run per day.
- The endpoint requires `Authorization: Bearer $CRON_SECRET`. Vercel sends this header
  automatically when the variable is set. With no `CRON_SECRET` it answers **503** and
  refuses to run, rather than leaving a public endpoint that anyone could trigger.
- **It sends nothing when nothing is due**, so silence is the normal state. To tell
  "quiet" from "broken", check the cron's run history in the Vercel dashboard.

### Zoom meetings, internally

`zoom_service.py` exchanges the three `ZOOM_*` credentials for a one-hour access token
(`grant_type=account_credentials`, HTTP Basic auth), cached in-process and renewed a
minute early so it can't expire mid-request. Meetings are created as `type: 2`
(scheduled) at the event's own start time and computed duration.

The join URL goes in the event's `location` — which Google Calendar renders as a
clickable link — and is appended to the description. Google's native `conferenceData`
is deliberately not used: third-party conferencing there requires a registered
Calendar add-on, so an arbitrary Zoom link cannot be injected into it.

Setup lives in [section 4](#4-set-up-zoom-optional).

### Running the tests

```bash
source .venv/bin/activate
python3 -m pytest tests/ -q
```

---

## Troubleshooting

### Google / OAuth

**`Error 403: access_denied` — "has not completed the Google verification process"**
Your OAuth app is in **Testing** and the account you're signing in with isn't on the
Test Users list. Either add it there, or better, publish the app — see [3.3b](#33b-publish-the-app).

**"Google hasn't verified this app" during OAuth**
Click **Advanced** → **Go to [app name] (unsafe)**. Expected for a personal bot.

**Google access stops working roughly every 7 days**
The app is still in **Testing** mode, where refresh tokens expire after 7 days.
Publish it — see [3.3b](#33b-publish-the-app).

**"Tasks isn't authorized on this token yet"**
Your token predates the `auth/tasks` scope. Re-run `/auth` and replace
`GOOGLE_REFRESH_TOKEN` — see [Changing OAuth scopes](#changing-oauth-scopes).

**"The Google Tasks API isn't enabled on your Google Cloud project"**
Different problem, same 403 from Google. Enable the API at
**APIs & Services → Library → Google Tasks API**, confirm the project selector shows
the right project, and wait a minute for it to propagate. Re-authorizing will **not**
fix this.

To tell the two apart, the API-disabled error contains
`has not been used in project <number>`.

**"Failed to fetch emails"**
Gmail API may not be enabled — visit the link in the error message. Or `/auth` again
for a fresh token.

**"Connect Google first: /auth"**
Complete the OAuth flow, and make sure `GOOGLE_REFRESH_TOKEN` is set in Vercel **and
you've redeployed** — env changes need a redeploy to take effect.

### LLM parsing

**`model_not_found` / "The model `...` does not exist or you do not have access to it"**
Groq retires and deprecates model IDs, and deprecation can apply to free and developer
tiers while enterprise accounts keep access. Set `GROQ_MODEL` to a current model rather
than editing code — see the [current model list](https://console.groq.com/docs/models).

Note the error body tells you which provider answered: Groq omits `param`, OpenAI
always includes `'param': None`.

### Behavior

**A "remind me to ..." became a calendar event (or vice versa)**
Classification is a live LLM judgment, so it is not perfectly predictable. "Remind me
to", "todo", and "don't forget" are instructed to always produce a task; meetings and
appointments always produce an event. The reply tells you which it made — `Task added`
vs `Added!` with a timestamp. If it guesses wrong, rephrase.

**A task's time of day disappeared**
Google Tasks stores a due *date* only. A time you mention is preserved in the task's
notes and shown in the confirmation, but **no alert fires at that time**. Use a
calendar event when you need to be pinged.

**No conflict warning on an event that overlaps**
Only your **primary** calendar is checked. Events marked **Free** are skipped, and
back-to-back events don't count as overlapping. The conflict lookup deliberately
swallows its own errors so it can never block event creation — which means a failing
lookup is indistinguishable from a clear calendar. Check the runtime logs.

**The daily digest never arrives**
Expected when nothing is due. Otherwise: confirm `CRON_SECRET` is set (without it the
endpoint returns 503), remember the schedule is UTC, and check the cron run history in
the Vercel dashboard.

**Recurring events not working**
Be explicit: "every Monday" or "every weekday" rather than just "weekly".

### Deployment

**Bot doesn't respond at all**
- Check `getWebhookInfo` for errors
- Verify `TELEGRAM_BOT_TOKEN` and `AUTHORIZED_USER_ID` in Vercel
- Redeploy: `vercel --prod`

**A new endpoint returns 404 on Vercel**
You probably added an `api/*.py` file. Vercel serves `app.py` — add an `@app.route`
instead. See [How It's Wired](#10-how-its-wired).

**An env var change didn't take effect**
Vercel env changes require a redeploy: `vercel --prod`.

**Removing an env var didn't revoke the credential**
It doesn't. Rotate or revoke at the provider — for Google, at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions).
