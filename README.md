# Attendance Bot — @lyceuma_bot

> The bot's entire interface — messages, buttons, alerts and the report
> images — is in **Russian**. This README stays in English for maintainers.

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

**Access codes never appear in this repository.** They live on the server only,
so cloning the repo gives nobody a way in. See
[Managing access codes](#managing-access-codes).

Need to onboard someone else later? Any verified user sends `/newcode` and the
bot issues a fresh single-use code.

**2. Menu.** A verified user sees two buttons: `📋 Отметить посещаемость`
and `👁 Посмотреть отмеченную посещаемость`.

**3. Roster.** Tapping it lists every student as a button.

- Tap a name → `❌` appears next to it and the message reads
  **"{student} is absent"**.
- Tap the same name again → the `❌` disappears and the message reads
  **"{student} is present"**.
- `📄 Сформировать отчёт` → the bot sends a PNG report: a green tick or red cross
  per student, present/absent/total counts, the date and who generated it.
- `⬅️ Назад` → returns to the menu.

**4. Viewing what's been marked.** `👁 Посмотреть отмеченную посещаемость` sends
the picture of today's register with two buttons under it: `✏️ Изменить` reopens
the roster with the current marks intact, and `👌 ОК` returns to the menu. Both
remove the picture so the chat stays tidy. If nobody has taken the register yet,
the caption says so rather than passing off the default as a real record.

**5. Sending a report to a group.** Every report arrives with a
`📤 Отправить в «<group>»` button for each Telegram group the bot belongs to. Tap one
and the same image is posted there, captioned with who sent it; the button then
reads `✅ Отправлено в «<group>»` so you can see what already went out.

Before the buttons are drawn the bot confirms it is still a member of each
group, so a group it was removed from never shows a button that would fail. If a
send fails anyway — removed between the check and the tap — the group is dropped
and the button disappears. A group upgraded to a supergroup is followed to its
new id rather than lost.

Telegram gives bots no way to list the chats they are in, so the bot learns its
groups two ways: it is told immediately when someone **adds it to a group**, and
it registers any **group it already sits in** the first time it sees a message
there — so if you added it before starting the bot, just send `/start` in that
group once. Removing the bot from a group drops it from the list. `/groups`
shows what it currently knows.

## Scheduled messages

All times are **Asia/Tashkent**. Nothing is sent on a day off.

| When | What | Where |
|---|---|---|
| Mondays 09:00 | Weekly statistics for the previous Mon–Sun | Every verified user **and** every group |
| Daily 09:40 and 11:10 | «Вы ещё не отметили посещаемость» — only if the register is untaken | Every verified user |
| Daily 00:00 | Day rollover (below) | — |

**Weekly statistics** rank the students with the most absences and list those
with perfect attendance, over the previous Monday–Sunday. Only days where the
register was actually taken are counted, so a week of holidays doesn't read as
perfect attendance for everyone. If no register was taken all week, nothing is
sent.

**The reminder** distinguishes "nobody marked anything" from "everyone turned
up" — an empty absent list means both, so the bot records separately whether
someone actually took the register. Toggling a student or generating a report
counts as taking it; merely viewing the list does not.

**Days off** are configured in `config.json`:

```json
"days_off": {
  "weekdays": ["sunday"],
  "dates": ["2026-09-23"]
}
```

`weekdays` repeats every week; `dates` are one-off holidays. On a day off there
is no reminder and no weekly stats.

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

Past days stay readable — `Сформировать отчёт` on a sealed sheet still works and
is labelled `🔒 День закрыт — данные окончательные.` The full history is kept in `data.json`.

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
| `days_off` | Weekly days off and one-off holidays |

Environment variables (`.env` locally, host settings on a server):

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | **Required.** Bot token from @BotFather |
| `DATA_DIR` | Where `data.json` lives. Set to the mounted volume on a server |
| `ACCESS_CODES` | One-time access codes, comma- or space-separated |
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

## Managing access codes

Codes are deliberately kept out of git. The bot reads them from two places on
the server, and registers anything new it finds:

1. **`ACCESS_CODES`** — an environment variable, comma- or space-separated.
2. **`access_codes.txt`** — a file on the persistent disk (`$DATA_DIR`), one
   code per line. `#` starts a comment.

A code that has already been redeemed is never revived by either source, so it
is safe to leave spent codes in the list.

### Adding codes on Render

Open your service → **Shell**, then:

```bash
echo "MYCODE-2026-A" >> /data/access_codes.txt
```

The bot re-reads that file **once a minute**, so the code goes live on its own —
no restart, no redeploy. Add several at once:

```bash
cat >> /data/access_codes.txt <<'EOF'
DIRECTOR-7K2M9
TEACHER-X4P1Q
EOF
```

To see what exists and what has been used:

```bash
cat /data/access_codes.txt
python -c "import json;d=json.load(open('/data/data.json'));[print(c, 'REVOKED' if v.get('revoked') else (v['used_by'] or 'unused')) for c,v in d['codes'].items()]"
```

The environment-variable route works too — service → **Environment** → set
`ACCESS_CODES` → save. That restarts the service, so the file is the smoother
option for day-to-day additions.

### Revoking a code

Append it to `revoked_codes.txt` on the disk:

```bash
echo "ADMIN-XXXXXXXX" >> /data/revoked_codes.txt
```

Within a minute — the same refresh as for adding — the bot blocks it:

- **Unused code:** it can no longer be redeemed; anyone who tries is told it was
  revoked.
- **Used code:** the person who got in with it **loses access** immediately.
  Their buttons stop working and they stop receiving reminders. Other users are
  unaffected.

A revoked code can never come back, even if it is still (or later) listed in
`access_codes.txt` — so you can also revoke a code *before* handing it out.
Revocations survive restarts and redeploys.

Don't revoke by editing `data.json` or deleting lines from `access_codes.txt`:
the running bot keeps its state in memory and would overwrite the edit, and a
code deleted from `data.json` but still in `access_codes.txt` would be re-added
as a fresh, usable code. `revoked_codes.txt` is the supported way.

To give someone access again after revoking, issue them a new code.

### The first code on a fresh deployment

If neither source is set and no codes exist yet, the bot mints three at startup
and prints them as a warning in the logs:

```
No ACCESS_CODES set. Generated bootstrap codes: CODE-4F7K2A, CODE-9QX3MB, CODE-B6R8TC
```

Read them out of the Render log, redeem one, then add your own with the file.
They exist nowhere else — not in the repo, not in the image.

## Deploying to a free VM

Free *managed* platforms no longer suit an always-on polling bot — but a free
VM does, and it costs nothing indefinitely:

- **Oracle Cloud Always Free** — no time limit, generous specs
- **Google Cloud free tier** — one `e2-micro` in `us-west1`, `us-central1` or
  `us-east1`

Create an **Ubuntu 22.04 or 24.04** VM (the smallest size is plenty — this bot
idles at a few MB), then SSH in and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Spideynotunderground/attendance-bot/main/deploy/setup.sh | bash
```

That installs Python and the fonts, creates an unprivileged `attbot` user,
clones the repo to `/opt/attendance-bot`, and installs a systemd service. Then
add your token and start it:

```bash
sudo nano /etc/attendance-bot.env     # paste it after BOT_TOKEN=
sudo systemctl start attendance-bot
sudo journalctl -u attendance-bot -f  # watch it come up
```

Grab a bootstrap code from that log and redeem it in Telegram.

No inbound ports are needed — the bot only makes outbound calls to Telegram, so
leave the firewall closed.

### Running it

| Task | Command |
|---|---|
| Status | `sudo systemctl status attendance-bot` |
| Logs (live) | `sudo journalctl -u attendance-bot -f` |
| Restart | `sudo systemctl restart attendance-bot` |
| Stop | `sudo systemctl stop attendance-bot` |
| Deploy new code | `bash /opt/attendance-bot/deploy/update.sh` |
| Add access codes | `sudo -u attbot tee -a /var/lib/attendance-bot/access_codes.txt` |

`Restart=always` brings the bot back after a crash, and the service is enabled,
so it also survives a reboot.

State lives in `/var/lib/attendance-bot/` — outside the git checkout, so
`update.sh` never touches your verified users or attendance history.

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
Unused access codes: <your codes>
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
| `deploy/` | systemd unit and setup/update scripts for a VM |
| `test_flow.py` | Offline end-to-end check of the whole flow |

> `config.json` holds your bot token and `data.json` holds who is verified.
> Both stay out of git via `.gitignore` — keep them off shared drives too.
