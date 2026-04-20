# Telegram Calendar & Gmail Bot

A personal AI assistant Telegram bot that manages your Google Calendar and Gmail using natural language and voice messages.

**Features:**
- Create calendar events (including recurring) by describing them naturally
- Check and read unread Gmail messages
- Reply to and compose emails
- Voice message support (transcribed via Whisper)
- Runs on Vercel (serverless) or locally

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create Your Telegram Bot](#2-create-your-telegram-bot)
3. [Set Up Google Cloud Project](#3-set-up-google-cloud-project)
4. [Local Installation](#4-local-installation)
5. [Deploy to Vercel](#5-deploy-to-vercel)
6. [Connect Google Account](#6-connect-google-account)
7. [Environment Variables Reference](#7-environment-variables-reference)
8. [Usage Guide](#8-usage-guide)

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
   8720726913:AAEqnXdOxvwmkot4rAZ5b9iW1uvjSRUCrPc
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

You need to enable two APIs:

**Enable Google Calendar API:**
1. Go to [APIs & Services → Library](https://console.cloud.google.com/apis/library)
2. Search for **Google Calendar API**
3. Click it → **Enable**

**Enable Gmail API:**
1. In the same Library page, search for **Gmail API**
2. Click it → **Enable**

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
6. Click **Update** → **Save and Continue**
7. On the **Test Users** step, click **Add Users** and add your Google account email
8. Click **Save and Continue** → **Back to Dashboard**

> **Why "External" + test user?** This avoids a full Google verification process. Since only you use the bot, test mode is fine.

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

## 4. Local Installation

### 4.1 Clone the repository

```bash
git clone https://github.com/your-username/telegram-calendar-bot.git
cd telegram-calendar-bot
```

### 4.2 Create a virtual environment

```bash
python3.13 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows
```

### 4.3 Install dependencies

```bash
pip install -r requirements.txt
```

### 4.4 Create the `.env` file

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
```

Replace each value with your actual credentials.

### 4.5 Run the bot locally

```bash
python main.py
```

You should see:
```
Web server on :8080
Bot polling started
```

The bot now runs in **polling mode** — it continuously checks Telegram for new messages.

### 4.6 Connect Google (local)

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

## 5. Deploy to Vercel

### 5.1 Log in to Vercel

```bash
vercel login
```

Follow the browser prompt to authenticate.

### 5.2 Link the project

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

### 5.3 Add environment variables

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
```

For each command, paste the value when prompted and select **Production** (press Space to toggle, Enter to confirm).

> `GOOGLE_REFRESH_TOKEN` is added later — after the first `/auth` flow.

### 5.4 Deploy to production

```bash
vercel --prod
```

When the deploy completes, you'll see your production URL:
```
Production: https://your-app-name.vercel.app
```

### 5.5 Update the OAuth redirect URI

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

### 5.6 Register the Telegram webhook

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

## 6. Connect Google Account

This step is done **once** after deployment. It authorizes the bot to access your Google Calendar and Gmail.

### 6.1 Start the auth flow

In Telegram, send your bot:
```
/auth
```

The bot replies with an authorization URL. Open it in your browser.

### 6.2 Authorize Google

1. Sign in with your Google account (the test user you added in step 3.3)
2. You may see a warning: **"Google hasn't verified this app"** — click **Continue**
3. Grant the requested permissions (Calendar and Gmail access)
4. You'll be redirected to a page saying **"Connected!"**

### 6.3 Save the refresh token

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

### 6.4 Verify the connection

Send `/status` to your bot. It should reply:
```
Google Calendar & Gmail are connected.
```

---

## 7. Environment Variables Reference

| Variable | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | `8720726913:AAEq...` |
| `AUTHORIZED_USER_ID` | Your Telegram numeric user ID | `123456789` |
| `GOOGLE_CLIENT_ID` | OAuth client ID from Google Cloud | `386693...apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret from Google Cloud | `GOCSPX-...` |
| `OAUTH_REDIRECT_URI` | Must match what's in Google Cloud Console | `https://your-app.vercel.app/api/callback` |
| `GOOGLE_REFRESH_TOKEN` | Obtained after first `/auth` flow | `1//0abc...` |
| `ANTHROPIC_API_KEY` | For AI intent parsing (Claude) | `sk-ant-...` |
| `GROQ_API_KEY` | For voice transcription (Whisper) | `gsk_...` |
| `TIMEZONE` | Your local timezone | `Asia/Manila` |

> `OPENAI_API_KEY` can be used instead of `GROQ_API_KEY` for voice transcription if preferred.

---

## 8. Usage Guide

### Calendar

Just describe the event naturally:

| Message | What it does |
|---|---|
| `Meeting with Sarah tomorrow 2pm` | Creates a 1-hour event tomorrow at 2pm |
| `Dentist Friday 10am for 30 minutes` | Creates a 30-min event on Friday |
| `Team standup every weekday at 9am` | Creates a recurring weekday event |
| `Set meeting every Monday at 3pm with AI Labs` | Creates a weekly recurring Monday event |
| `Monthly review on the 1st at 2pm` | Creates a monthly recurring event |

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

---

## Troubleshooting

**Bot doesn't respond:**
- Check `getWebhookInfo` for errors
- Verify `TELEGRAM_BOT_TOKEN` and `AUTHORIZED_USER_ID` are correct in Vercel
- Redeploy: `vercel --prod`

**"Connect Google first: /auth":**
- Run `/auth` and complete the OAuth flow
- Make sure `GOOGLE_REFRESH_TOKEN` is set in Vercel and you've redeployed

**"Failed to fetch emails":**
- Gmail API may not be enabled — visit the link in the error message to enable it
- Or run `/auth` again to get a fresh token

**"Google hasn't verified this app" during OAuth:**
- Click **Advanced** → **Go to [app name] (unsafe)** — this is expected for personal bots

**Recurring events not working:**
- Be explicit: say "every Monday" or "every weekday" rather than just "weekly"
