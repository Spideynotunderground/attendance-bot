# Attendance Bot — @lyceuma_bot

A Telegram bot that lets verified staff mark a group's attendance and export a
report image.

## Run it locally

```bash
./run.sh
```

First run creates `.venv`, installs dependencies and prints your unused access
codes. Ctrl-C stops the bot. It must stay running for the bot to respond.

The token is read from `BOT_TOKEN` — in `.env` locally, or the host's
environment settings on a server. `.env` is gitignored; `config.json` holds only
the roster and is safe to commit.

> **Only one copy of the bot may run at a time.** Telegram allows a single
> long-polling connection per token, so a second instance makes both fail with
> `Conflict: terminated by other getUpdates request`. Stop the local bot before
> the deployed one goes live.

To verify everything works without a network connection:

```bash
.venv/bin/python test_flow.py
```

## How it works

**1. Verification.** Nothing works until a user redeems a one-time access code.
Send `/start`, then send the code as a plain message. The moment a code verifies
an account it is burned — the same code can never verify a second person. The
user's Telegram ID is stored in `data.json` and they are never asked again.

Starting codes (in `config.json`):

```
ADMIN-4F7K2
ADMIN-9QX3M
ADMIN-B6R8T
ADMIN-6YG5U
```

All codes behave identically — the `ADMIN-` prefix is just a label for your own
bookkeeping, the bot has no separate permission levels.

Need to onboard someone else later? Any verified user sends `/newcode` and the
bot issues a fresh single-use code.

**2. Menu.** A verified user sees exactly one button:
`📋 Mark students' attendance`.

**3. Roster.** Tapping it lists every student as a button.

- Tap a name → `❌` appears next to it and the message reads
  **"{student} is absent"**.
- Tap the same name again → the `❌` disappears and the message reads
  **"{student} is present"**.
- `📄 Generate report` → the bot sends a PNG report: a green tick or red cross
  per student, present/absent/total counts, the date and who generated it.
- `⬅️ Go back` → returns to the menu.

**4. Sending a report to a group.** Every report arrives with a
`📤 Send to <group>` button for each Telegram group the bot belongs to. Tap one
and the same image is posted there, captioned with who sent it; the button then
reads `✅ Sent to <group>` so you can see what already went out.

Telegram gives bots no way to list the chats they are in, so the bot learns its
groups two ways: it is told immediately when someone **adds it to a group**, and
it registers any **group it already sits in** the first time it sees a message
there — so if you added it before starting the bot, just send `/start` in that
group once. Removing the bot from a group drops it from the list. `/groups`
shows what it currently knows.

## The day rolls over at midnight, Tashkent time

Every sheet belongs to one calendar day in **Asia/Tashkent (UTC+5)**, regardless
of your Mac's own clock or where the bot is hosted.

At `00:00` Tashkent:

- The new day starts with a clean sheet — nobody is absent.
- Every roster screen still open on someone's phone is rewritten in place, so
  the `❌` marks vanish without anyone having to reopen the menu.
- **The previous day is sealed.** Its marks are final and cannot be changed by
  anyone, through any button. If someone left the roster open overnight and taps
  a name, the edit is refused with a notice and the screen switches to today.
  `/reset` clears today only and never touches a sealed day.

Past days stay readable — `Generate report` on a sealed sheet still works and is
labelled `🔒 Closed — final.` The full history is kept in `data.json`.

## Commands

| Command | Who | What |
|---|---|---|
| `/start`, `/menu` | anyone | Verify, or open the menu |
| `/newcode` | verified | Issue a fresh one-time access code |
| `/reset` | verified | Clear today's marks (everyone present again) |
| `/groups` | verified | List the groups reports can be sent to |

## Configuration — `config.json`

| Key | Meaning |
|---|---|
| `group_name` | Shown in the report header |
| `students` | Your roster. Edit this list — button order follows it |
| `initial_access_codes` | Codes seeded on startup. New entries are added; already-used ones are never revived |

Environment variables (`.env` locally, host settings on a server):

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | **Required.** Bot token from @BotFather |
| `DATA_DIR` | Where `data.json` lives. Set to the mounted volume on a server |
| `PROXY_URL` | Only if your network blocks Telegram (see below) |
| `GROUP_NAME` | Overrides `group_name` from `config.json` |

Attendance is stored per calendar day and shared by all verified users — it is
one group's register, not a per-user scratchpad.

## If the bot won't connect

On this machine `api.telegram.org` is currently **unreachable** — the rest of
the internet works, but TCP to Telegram's servers (149.154.166.110 and
149.154.167.220 on port 443) times out. That is a network-level block on the
current connection, not a bug in the bot. Symptom in `bot.log`:

```
telegram.error.TimedOut: Timed out
```

Fixes, in order of ease:

1. Switch network (different Wi-Fi / mobile carrier) and run `./run.sh` again.
2. Turn on a VPN, then run `./run.sh`.
3. Point the bot at a proxy — set `"proxy"` in `config.json`, for example
   `"socks5://127.0.0.1:1080"` or `"http://user:pass@host:port"`, then run.

Check connectivity at any time with:

```bash
curl -s -m 10 "https://api.telegram.org/bot<TOKEN>/getMe"
```

A JSON response means you are good to go.

## Deploying to Render

Render runs it as a **Background Worker** — a polling bot serves no HTTP, so a
web service would sleep when idle and quietly stop taking attendance. Workers
are a paid service type; the free tier will not work for this. Check Render's
current pricing before you commit to it.

**1. Push to GitHub**

Create an empty **private** repo on github.com (no README, no .gitignore), then:

```bash
git remote add origin https://github.com/<you>/attendance-bot.git
git push -u origin main
```

Or with the GitHub CLI, if you install it (`brew install gh`, then `gh auth login`):

```bash
gh repo create attendance-bot --private --source=. --push
```

**2. Create the service**

In Render: **New → Blueprint**, point it at the repo. It reads `render.yaml` and
creates a Docker worker with a 1 GB disk mounted at `/data`.

**3. Set the token**

Render will prompt for `BOT_TOKEN` (it is marked `sync: false`, so it is never
stored in git). Paste the token from BotFather. Deploy.

**4. Stop the local bot**, or the two instances will fight over the same token.

Check the Render logs — a healthy start looks like:

```
Unused access codes: ADMIN-4F7K2, ADMIN-9QX3M, ...
Today in Tashkent is 2026-09-07 (now 14:12 +05).
Bot is running.
Application started
```

### The disk is not optional

`render.yaml` mounts a persistent disk at `/data` and points `DATA_DIR` there.
Without it, Render's container filesystem resets on **every redeploy and
restart** — every verified user would be logged out, every access code would
come back to life, and the attendance history would be gone. Do not remove it.

### Day-to-day

- **Change the roster:** edit `students` in `config.json`, commit, push. Render
  redeploys automatically; `/data` is untouched, so attendance survives.
- **Add access codes:** add them to `initial_access_codes` and push. Codes
  already redeemed are never revived.
- **Fresh start:** the deployed bot begins with nobody verified and every code
  unused. Your local `data.json` does not travel — it is gitignored.
- **Logs:** Render's dashboard, or `render logs` with their CLI.

### Other hosts

`Dockerfile` is plain and portable — the same image runs on Fly.io, Railway, or
any VPS with Docker. Whatever you choose, it needs two things: an always-on
process (not a sleeping web service) and a persistent volume at `DATA_DIR`.

## Files

| File | Purpose |
|---|---|
| `bot.py` | Handlers, auth, menus, toggling |
| `report.py` | PNG (and plain-text fallback) report rendering |
| `storage.py` | Atomic JSON persistence |
| `config.json` | Roster, group name, starting codes. No secrets — safe to commit |
| `.env` | `BOT_TOKEN`. Gitignored, never commit |
| `data.json` | Runtime state — codes, verified users, groups, attendance history |
| `fonts/` | DejaVu Sans, shipped so Cyrillic renders identically everywhere |
| `Dockerfile` | Container image (fonts + tzdata included) |
| `render.yaml` | Render Blueprint: worker + persistent disk |
| `test_flow.py` | Offline end-to-end check of the whole flow |

> `config.json` holds your bot token and `data.json` holds who is verified.
> Both stay out of git via `.gitignore` — keep them off shared drives too.
