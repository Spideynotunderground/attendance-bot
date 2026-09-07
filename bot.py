#!/usr/bin/env python3
"""Attendance bot.

  1. Every user must redeem a one-time access code before anything else works.
     Redeeming burns the code, so it can never verify a second account.
  2. Verified users get a single button: "Mark students' attendance".
  3. That opens the roster. Tapping a name toggles absent/present (❌ marks
     absent). "Generate report" renders a PNG summary, "Go back" returns
     to the menu.
  4. The sheet is per calendar day in Uzbekistan time. At 00:00 Tashkent the
     day rolls over: open roster screens are wiped clean and the previous day
     is sealed — its marks can no longer be changed by anyone.
  5. A finished report carries a "Send to <group>" button for every Telegram
     group the bot is currently a member of.
"""

import html
import io
import json
import logging
import os
import secrets
import string
from datetime import datetime
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import ChatMember, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import report
import storage

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

TZ = ZoneInfo("Asia/Tashkent")

logging.basicConfig(
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("attendance-bot")

CONFIG: dict = {}
STATE: dict = {}


# --------------------------------------------------------------------------
# time — everything is anchored to Uzbekistan time, not the host clock
# --------------------------------------------------------------------------

def now() -> datetime:
    return datetime.now(TZ)


def today_key() -> str:
    return now().date().isoformat()


def day_as_datetime(day: str) -> datetime:
    """Midday on `day`, so strftime never straddles a boundary."""
    d = datetime.strptime(day, "%Y-%m-%d")
    return d.replace(hour=12, tzinfo=TZ)


def pretty_day(day: str) -> str:
    return day_as_datetime(day).strftime("%A, %d %B %Y")


# --------------------------------------------------------------------------
# config / state helpers
# --------------------------------------------------------------------------

def load_dotenv() -> None:
    """Read KEY=value lines from .env into the environment (local runs).

    Real environment variables always win, so a hosting platform's settings
    override anything in the file.
    """
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_config() -> dict:
    """config.json holds the roster (safe to commit); secrets come from env."""
    cfg = {}
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open(encoding="utf-8") as fh:
            cfg = json.load(fh)

    cfg["token"] = os.environ.get("BOT_TOKEN") or cfg.get("token") or ""
    if not cfg["token"]:
        raise SystemExit(
            "No bot token. Set BOT_TOKEN in the environment (or in a local .env "
            "file next to bot.py)."
        )
    cfg["proxy"] = os.environ.get("PROXY_URL") or cfg.get("proxy") or ""
    if os.environ.get("GROUP_NAME"):
        cfg["group_name"] = os.environ["GROUP_NAME"]
    cfg.setdefault("group_name", "Group")
    cfg.setdefault("students", [])
    return cfg


def students() -> list:
    return CONFIG.get("students", [])


def absent_on(day: str) -> list:
    return STATE["attendance"].setdefault(day, [])


def absent_today() -> list:
    return absent_on(today_key())


def is_sealed(day: str) -> bool:
    """Any day other than the current Tashkent day is read-only, forever."""
    return day != today_key()


def make_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "CODE-" + "".join(secrets.choice(alphabet) for _ in range(6))


def seed_codes() -> None:
    """Add codes listed in config.json that we haven't seen before."""
    configured = CONFIG.get("initial_access_codes") or []
    if not configured and not STATE["codes"]:
        configured = [make_code() for _ in range(3)]
    added = []
    for code in configured:
        code = code.strip()
        if code and code not in STATE["codes"]:
            STATE["codes"][code] = {
                "created_at": storage.now_iso(),
                "used_by": None,
                "used_at": None,
            }
            added.append(code)
    if added:
        storage.save(STATE)
        log.info("Seeded %d access code(s).", len(added))

    unused = [c for c, v in STATE["codes"].items() if v["used_by"] is None]
    log.info("Unused access codes: %s", ", ".join(unused) if unused else "(none left)")


def is_verified(user_id: int) -> bool:
    return str(user_id) in STATE["verified_users"]


def redeem(code: str, user) -> bool:
    """Burn `code` for `user`. Returns False if unknown or already spent."""
    entry = STATE["codes"].get(code)
    if entry is None or entry["used_by"] is not None:
        return False
    entry["used_by"] = user.id
    entry["used_at"] = storage.now_iso()
    STATE["verified_users"][str(user.id)] = {
        "name": user.full_name,
        "username": user.username,
        "verified_at": storage.now_iso(),
        "code": code,
    }
    storage.save(STATE)
    log.info("Verified user %s (%s) with code %s", user.id, user.full_name, code)
    return True


def who(user) -> str:
    return f"@{user.username}" if user.username else user.full_name


# --------------------------------------------------------------------------
# open roster screens — tracked so midnight can wipe them clean
# --------------------------------------------------------------------------

def remember_screen(user_id: int, message, day: str) -> None:
    if message is None:
        return
    STATE["open_screens"][str(user_id)] = {
        "chat_id": message.chat_id,
        "message_id": message.message_id,
        "day": day,
    }
    storage.save(STATE)


def forget_screen(user_id: int) -> None:
    if STATE["open_screens"].pop(str(user_id), None) is not None:
        storage.save(STATE)


# --------------------------------------------------------------------------
# screens
# --------------------------------------------------------------------------

MENU_TEXT = "✅ <b>You're verified.</b>\n\nWhat would you like to do?"


def menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📋 Mark students' attendance", callback_data="mark")]]
    )


def roster_markup(day: str) -> InlineKeyboardMarkup:
    absent = set(absent_on(day))
    rows = [
        [InlineKeyboardButton(
            f"❌ {name}" if name in absent else name, callback_data=f"t:{day}:{i}"
        )]
        for i, name in enumerate(students())
    ]
    rows.append([InlineKeyboardButton("📄 Generate report", callback_data=f"rep:{day}")])
    rows.append([InlineKeyboardButton("⬅️ Go back", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def roster_text(day: str, status_line: str | None = None) -> str:
    absent = absent_on(day)
    total = len(students())
    head = (
        f"📋 <b>Attendance</b> — {html.escape(CONFIG['group_name'])}\n"
        f"{pretty_day(day)}\n\n"
        "Tap a name to toggle. ❌ means absent."
    )
    if is_sealed(day):
        head += "\n\n🔒 <b>This day is closed and can no longer be edited.</b>"
    tail = f"\n\nPresent: <b>{total - len(absent)}</b>   Absent: <b>{len(absent)}</b>"
    if status_line:
        return f"{head}\n\n{status_line}{tail}"
    return head + tail


def report_markup(day: str, sent_to=()) -> InlineKeyboardMarkup | None:
    """A "send to <group>" button per group the bot currently belongs to."""
    rows = []
    for chat_id, group in STATE["groups"].items():
        title = group.get("title") or "group"
        if chat_id in sent_to:
            rows.append([InlineKeyboardButton(f"✅ Sent to {title}", callback_data="noop")])
        else:
            rows.append([InlineKeyboardButton(
                f"📤 Send to {title}", callback_data=f"snd:{day}:{chat_id}"
            )])
    return InlineKeyboardMarkup(rows) if rows else None


async def show(query, text: str, markup: InlineKeyboardMarkup) -> None:
    """Edit the message in place, tolerating Telegram's 'not modified'."""
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


# --------------------------------------------------------------------------
# command handlers
# --------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "👋 I take attendance in a private chat. Message me directly to start."
        )
        return
    if is_verified(user.id):
        await update.message.reply_text(
            MENU_TEXT, reply_markup=menu_markup(), parse_mode=ParseMode.HTML
        )
        return
    await update.message.reply_text(
        "🔒 <b>This bot is private.</b>\n\n"
        "Send me your access code to get verified.\n"
        "<i>Each code works exactly once — it stops working the moment it "
        "verifies an account.</i>",
        parse_mode=ParseMode.HTML,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Private chat only: unverified users are typing a code."""
    user = update.effective_user
    if is_verified(user.id):
        await update.message.reply_text(
            MENU_TEXT, reply_markup=menu_markup(), parse_mode=ParseMode.HTML
        )
        return

    code = (update.message.text or "").strip()
    if redeem(code, user):
        await update.message.reply_text(
            "🎉 <b>Verification successful.</b>\n"
            "That code is now used up and cannot verify anyone else.",
            parse_mode=ParseMode.HTML,
        )
        await update.message.reply_text(
            MENU_TEXT, reply_markup=menu_markup(), parse_mode=ParseMode.HTML
        )
    else:
        known = code in STATE["codes"]
        reason = "already been used" if known else "not a valid code"
        await update.message.reply_text(
            f"❌ That code has {reason}. Ask an existing user for a fresh one."
        )


async def cmd_newcode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_verified(user.id):
        await update.message.reply_text("🔒 Send a valid access code first.")
        return
    code = make_code()
    STATE["codes"][code] = {
        "created_at": storage.now_iso(),
        "used_by": None,
        "used_at": None,
        "created_by": user.id,
    }
    storage.save(STATE)
    await update.message.reply_text(
        f"🆕 One-time access code:\n\n<code>{code}</code>\n\n"
        "Give it to <b>one</b> person. It dies as soon as they use it.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clears today only — sealed days are never touched."""
    user = update.effective_user
    if not is_verified(user.id):
        await update.message.reply_text("🔒 Send a valid access code first.")
        return
    STATE["attendance"][today_key()] = []
    storage.save(STATE)
    await update.message.reply_text(
        "♻️ Today's attendance was cleared — everyone is marked present again.",
        reply_markup=menu_markup(),
    )


async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows which groups the bot can send reports to."""
    if not is_verified(update.effective_user.id):
        await update.message.reply_text("🔒 Send a valid access code first.")
        return
    if not STATE["groups"]:
        await update.message.reply_text(
            "I'm not in any group yet.\n\n"
            "Add me to your group and I'll offer it as a destination under every "
            "report. (In a group with privacy mode on, I only need to be a member "
            "to post there.)"
        )
        return
    lines = [f"• {g.get('title')}  <code>{cid}</code>" for cid, g in STATE["groups"].items()]
    await update.message.reply_text(
        "📢 <b>I can send reports to:</b>\n" + "\n".join(lines), parse_mode=ParseMode.HTML
    )


# --------------------------------------------------------------------------
# group membership tracking
# --------------------------------------------------------------------------

JOINED = {ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER}


async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegram tells us whenever the bot is added to or removed from a chat."""
    change = update.my_chat_member
    chat = change.chat
    if chat.type not in ("group", "supergroup", "channel"):
        return

    status = change.new_chat_member.status
    if status in JOINED:
        STATE["groups"][str(chat.id)] = {
            "title": chat.title,
            "type": chat.type,
            "added_at": storage.now_iso(),
        }
        log.info("Added to %s %r (%s)", chat.type, chat.title, chat.id)
    else:
        STATE["groups"].pop(str(chat.id), None)
        log.info("Removed from %s %r (%s)", chat.type, chat.title, chat.id)
    storage.save(STATE)


async def on_group_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pick up groups we were already in, and follow renames.

    `my_chat_member` only fires when the bot is added while it is running, so a
    group it joined earlier would otherwise stay invisible. Any message the bot
    can see in that group registers it instead.
    """
    chat = update.effective_chat
    if chat is None or chat.type not in ("group", "supergroup"):
        return
    entry = STATE["groups"].get(str(chat.id))
    if entry is None:
        STATE["groups"][str(chat.id)] = {
            "title": chat.title,
            "type": chat.type,
            "added_at": storage.now_iso(),
        }
        log.info("Discovered existing group %r (%s)", chat.title, chat.id)
        storage.save(STATE)
    elif entry.get("title") != chat.title:
        entry["title"] = chat.title
        storage.save(STATE)


# --------------------------------------------------------------------------
# buttons
# --------------------------------------------------------------------------

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user

    if not is_verified(user.id):
        await query.answer(
            "🔒 You are not verified. Send /start and enter an access code.",
            show_alert=True,
        )
        return

    data = query.data or ""

    if data == "noop":
        await query.answer()
        return

    if data == "menu":
        await query.answer()
        forget_screen(user.id)
        await show(query, MENU_TEXT, menu_markup())
        return

    if data == "mark":
        await query.answer()
        day = today_key()
        await show(query, roster_text(day), roster_markup(day))
        remember_screen(user.id, query.message, day)
        return

    if data.startswith("rep:"):
        await query.answer("Generating…")
        await send_report(update, context, data.split(":", 1)[1])
        return

    if data.startswith("snd:"):
        _, day, chat_id = data.split(":", 2)
        await send_to_group(update, context, day, chat_id)
        return

    if data.startswith("t:"):
        _, day, raw_idx = data.split(":", 2)

        # A screen left open past midnight still carries yesterday's date.
        # Refuse the edit and swap the screen over to today.
        if is_sealed(day):
            await query.answer(
                f"🔒 Attendance for {pretty_day(day)} is closed and can no longer "
                "be edited. Showing today's sheet instead.",
                show_alert=True,
            )
            fresh = today_key()
            await show(query, roster_text(fresh), roster_markup(fresh))
            remember_screen(user.id, query.message, fresh)
            return

        try:
            name = students()[int(raw_idx)]
        except (ValueError, IndexError):
            await query.answer("That student is no longer on the roster.", show_alert=True)
            await show(query, roster_text(day), roster_markup(day))
            return

        absent = absent_on(day)
        if name in absent:
            absent.remove(name)
            status = f"✅ <b>{html.escape(name)}</b> is present"
            toast = f"{name} is present"
        else:
            absent.append(name)
            status = f"❌ <b>{html.escape(name)}</b> is absent"
            toast = f"{name} is absent"
        storage.save(STATE)

        await query.answer(toast)
        await show(query, roster_text(day, status), roster_markup(day))
        remember_screen(user.id, query.message, day)
        return

    await query.answer()


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------

def report_caption(day: str) -> str:
    absent = absent_on(day)
    total = len(students())
    caption = (
        f"📄 <b>Attendance report</b> — {html.escape(CONFIG['group_name'])}\n"
        f"{pretty_day(day)}\n"
        f"Present: <b>{total - len(absent)}</b>   Absent: <b>{len(absent)}</b>"
    )
    if is_sealed(day):
        caption += "\n🔒 Closed — final."
    return caption


async def send_report(update: Update, context: ContextTypes.DEFAULT_TYPE, day: str) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    absent = absent_on(day)
    roster = students()
    caption = report_caption(day)
    markup = report_markup(day)
    if markup is None:
        caption += "\n\n<i>Add me to a group to send reports there.</i>"

    try:
        image = report.build_report_image(
            CONFIG["group_name"], roster, absent,
            when=day_as_datetime(day), marked_by=who(user), generated_at=now(),
        )
        sent = await context.bot.send_photo(
            chat_id, photo=image, caption=caption,
            parse_mode=ParseMode.HTML, reply_markup=markup,
        )
        # Remember the rendered file so "send to group" re-uses it instead of
        # re-rendering (and so the group gets the exact same image).
        context.bot_data.setdefault("reports", {})[sent.message_id] = {
            "file_id": sent.photo[-1].file_id,
            "day": day,
            "sent_to": [],
        }
    except Exception:
        log.exception("Image report failed; falling back to a text file.")
        text = report.build_report_text(
            CONFIG["group_name"], roster, absent,
            when=day_as_datetime(day), generated_at=now(),
        )
        buf = io.BytesIO(text.encode("utf-8"))
        buf.name = f"attendance-{day}.txt"
        await context.bot.send_document(
            chat_id, document=buf, caption=caption,
            parse_mode=ParseMode.HTML, reply_markup=markup,
        )


async def send_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        day: str, chat_id: str) -> None:
    query = update.callback_query
    user = update.effective_user
    group = STATE["groups"].get(chat_id)
    if group is None:
        await query.answer("I'm no longer in that group.", show_alert=True)
        return

    title = group.get("title") or "the group"
    record = context.bot_data.get("reports", {}).get(query.message.message_id)
    caption = f"{report_caption(day)}\n\n<i>Sent by {html.escape(who(user))}</i>"

    try:
        if record and record.get("file_id"):
            await context.bot.send_photo(
                int(chat_id), photo=record["file_id"],
                caption=caption, parse_mode=ParseMode.HTML,
            )
        else:
            # Bot restarted since the report was posted — render it again.
            image = report.build_report_image(
                CONFIG["group_name"], students(), absent_on(day),
                when=day_as_datetime(day), marked_by=who(user), generated_at=now(),
            )
            await context.bot.send_photo(
                int(chat_id), photo=image, caption=caption, parse_mode=ParseMode.HTML
            )
    except Forbidden:
        await query.answer(
            f"I can't post in {title} — check I'm still a member and allowed "
            "to send messages there.",
            show_alert=True,
        )
        return
    except TelegramError as exc:
        log.warning("Sending report to %s failed: %s", chat_id, exc)
        await query.answer(f"Couldn't send to {title}: {exc}", show_alert=True)
        return

    await query.answer(f"Sent to {title} ✅")
    if record is not None and chat_id not in record["sent_to"]:
        record["sent_to"].append(chat_id)
    sent_to = record["sent_to"] if record else [chat_id]
    try:
        await query.edit_message_reply_markup(reply_markup=report_markup(day, sent_to))
    except BadRequest:
        pass


# --------------------------------------------------------------------------
# midnight rollover (00:00 Asia/Tashkent)
# --------------------------------------------------------------------------

async def midnight_rollover(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Seal yesterday and wipe the ❌ marks off every open roster screen."""
    day = today_key()
    absent_on(day)  # materialise today's empty sheet
    storage.save(STATE)
    log.info("Day rolled over to %s (Asia/Tashkent). Previous day is sealed.", day)

    for user_id, screen in list(STATE["open_screens"].items()):
        if screen.get("day") == day:
            continue
        try:
            await context.bot.edit_message_text(
                roster_text(day),
                chat_id=screen["chat_id"],
                message_id=screen["message_id"],
                reply_markup=roster_markup(day),
                parse_mode=ParseMode.HTML,
            )
            screen["day"] = day
            log.info("Reset open screen for user %s", user_id)
        except TelegramError as exc:
            # Message deleted, too old to edit, or the chat is gone.
            log.info("Dropping stale screen for user %s: %s", user_id, exc)
            STATE["open_screens"].pop(user_id, None)
    storage.save(STATE)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Handler error", exc_info=context.error)


# --------------------------------------------------------------------------

def main() -> None:
    global CONFIG, STATE
    load_dotenv()
    CONFIG = load_config()
    STATE = storage.load()
    seed_codes()

    builder = Application.builder().token(CONFIG["token"])
    # Some networks block api.telegram.org outright. Set "proxy" in config.json
    # (e.g. "socks5://127.0.0.1:1080" or "http://user:pass@host:port") to tunnel.
    proxy = (CONFIG.get("proxy") or "").strip()
    if proxy:
        builder = builder.proxy(proxy).get_updates_proxy(proxy)
        log.info("Using proxy %s", proxy)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_start))
    app.add_handler(CommandHandler("newcode", cmd_newcode))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("groups", cmd_groups))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(ChatMemberHandler(on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_text
    ))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, on_group_activity), group=1)
    app.add_error_handler(on_error)

    app.job_queue.run_daily(
        midnight_rollover, time=dtime(hour=0, minute=0, tzinfo=TZ), name="midnight-rollover"
    )

    log.info("Today in Tashkent is %s (now %s).", today_key(), now().strftime("%H:%M %Z"))
    log.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
