#!/usr/bin/env python3
"""Offline end-to-end check: drives the real handlers with fake Telegram
updates, so the whole flow can be verified without touching the network.

Run:  .venv/bin/python test_flow.py
"""

import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "0:OFFLINE-TEST")
from datetime import timedelta
from pathlib import Path

import storage

# Point the store at a scratch file so the real data.json is untouched.
storage.DATA_FILE = Path(tempfile.mkdtemp()) / "data.json"

import bot  # noqa: E402


class User:
    def __init__(self, uid, name, username=None):
        self.id, self.full_name, self.username = uid, name, username


class Message:
    def __init__(self, text=None, chat_id=999, message_id=1):
        self.text, self.chat_id, self.message_id = text, chat_id, message_id
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return Message()


class Photo:
    def __init__(self, file_id):
        self.file_id = file_id


class Sent:
    def __init__(self, message_id, file_id):
        self.message_id, self.photo = message_id, [Photo(file_id)]


class Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or Message()
        self.toasts, self.alerts, self.screens, self.markups = [], [], [], []
        self.markup_edits = []

    async def answer(self, text=None, show_alert=False):
        self.toasts.append(text)
        if show_alert:
            self.alerts.append(text)

    async def edit_message_text(self, text, reply_markup=None, **kw):
        self.screens.append(text)
        self.markups.append(reply_markup)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markup_edits.append(reply_markup)


class Chat:
    def __init__(self, cid=999, ctype="private", title=None):
        self.id, self.type, self.title = cid, ctype, title


class Update:
    def __init__(self, user, message=None, query=None, chat=None, my_chat_member=None):
        self.effective_user = user
        self.message = message
        self.callback_query = query
        self.effective_chat = chat or Chat()
        self.my_chat_member = my_chat_member


class MemberChange:
    def __init__(self, chat, status):
        self.chat = chat
        self.new_chat_member = type("M", (), {"status": status})()


class Bot_:
    def __init__(self):
        self.photos, self.docs, self.edits = [], [], []
        self._n = 100

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
        self._n += 1
        is_file_id = isinstance(photo, str)
        self.photos.append({
            "chat_id": chat_id,
            "name": photo if is_file_id else photo.name,
            "size": None if is_file_id else len(photo.getvalue()),
            "caption": caption,
            "markup": reply_markup,
        })
        return Sent(self._n, f"FILEID{self._n}")

    async def send_document(self, chat_id, document, **kw):
        self.docs.append(document.name)

    async def edit_message_text(self, text, chat_id=None, message_id=None,
                                reply_markup=None, **kw):
        self.edits.append({"chat_id": chat_id, "message_id": message_id,
                           "text": text, "markup": reply_markup})


class Ctx:
    def __init__(self):
        self.bot = Bot_()
        self.bot_data = {}


def labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


PASS, FAIL = "  ok  ", "  FAIL"
failures = []
total = [0]


def check(label, cond):
    total[0] += 1
    print((PASS if cond else FAIL) + " | " + label)
    if not cond:
        failures.append(label)


def section(title):
    print(f"\n--- {title} ---")


async def main():
    bot.CONFIG = bot.load_config()
    bot.CONFIG["students"] = ["Alice Brown", "Bob Carter", "Chen Wei"]
    bot.STATE = storage.load()
    bot.seed_codes()
    ctx = Ctx()

    teacher = User(1001, "Ms. Ivanova", "ivanova")
    intruder = User(2002, "Random Person")
    code = bot.CONFIG["initial_access_codes"][0]
    today = bot.today_key()

    section("verification")
    m = Message("/start")
    await bot.cmd_start(Update(teacher, message=m), ctx)
    check("unverified /start asks for a code", "access code" in m.sent[0])

    q = Query("mark")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("unverified button press blocked", "not verified" in (q.toasts[0] or ""))
    check("unverified press renders no screen", q.screens == [])

    m = Message("hunter2")
    await bot.on_text(Update(teacher, message=m), ctx)
    check("wrong code rejected", "not a valid code" in m.sent[0])

    m = Message(code)
    await bot.on_text(Update(teacher, message=m), ctx)
    check("valid code verifies the user", bot.is_verified(teacher.id))
    check("burn is announced", "used up" in m.sent[0])

    m = Message(code)
    await bot.on_text(Update(intruder, message=m), ctx)
    check("reused code rejected", "already been used" in m.sent[0])
    check("second account stays unverified", not bot.is_verified(intruder.id))

    section("menu and roster")
    m = Message("hi")
    await bot.on_text(Update(teacher, message=m), ctx)
    check("verified user gets the menu", "verified" in m.sent[0].lower())
    check("menu has one button", labels(bot.menu_markup()) == ["📋 Mark students' attendance"])

    q = Query("mark")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("roster lists every student + report + back",
          labels(q.markups[0]) ==
          ["Alice Brown", "Bob Carter", "Chen Wei", "📄 Generate report", "⬅️ Go back"])

    section("toggling")
    q = Query(f"t:{today}:1")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("toast says absent", q.toasts[0] == "Bob Carter is absent")
    check("message says absent", "<b>Bob Carter</b> is absent" in q.screens[0])
    check("X icon appears on that name", "❌ Bob Carter" in labels(q.markups[0]))
    check("state records the absence", bot.absent_today() == ["Bob Carter"])

    q = Query(f"t:{today}:1")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("toast says present", q.toasts[0] == "Bob Carter is present")
    check("message says present", "<b>Bob Carter</b> is present" in q.screens[0])
    check("X icon disappears", "❌ Bob Carter" not in labels(q.markups[0]))
    check("state cleared", bot.absent_today() == [])

    await bot.on_button(Update(teacher, query=Query(f"t:{today}:0")), ctx)
    await bot.on_button(Update(teacher, query=Query(f"t:{today}:2")), ctx)
    q = Query("menu")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("go back returns to the menu",
          labels(q.markups[0]) == ["📋 Mark students' attendance"])

    q = Query("mark", Message(chat_id=999, message_id=55))
    await bot.on_button(Update(teacher, query=q), ctx)
    check("marks persist across screens",
          labels(q.markups[0])[:3] == ["❌ Alice Brown", "Bob Carter", "❌ Chen Wei"])

    section("Uzbekistan time")
    check("timezone is Asia/Tashkent", str(bot.TZ) == "Asia/Tashkent")
    check("today follows Tashkent, not the host clock",
          bot.today_key() == bot.now().date().isoformat())
    check("offset is UTC+5", bot.now().utcoffset() == timedelta(hours=5))

    section("previous day is sealed")
    yesterday = (bot.now().date() - timedelta(days=1)).isoformat()
    bot.STATE["attendance"][yesterday] = ["Bob Carter"]
    storage.save(bot.STATE)
    check("yesterday counts as sealed", bot.is_sealed(yesterday))
    check("today is not sealed", not bot.is_sealed(today))

    q = Query(f"t:{yesterday}:0")          # a screen left open overnight
    await bot.on_button(Update(teacher, query=q), ctx)
    check("editing a sealed day is refused", any("closed" in (a or "") for a in q.alerts))
    check("sealed data is untouched", bot.STATE["attendance"][yesterday] == ["Bob Carter"])
    check("stale screen swaps to today", bot.pretty_day(today) in q.screens[0])
    check("today's marks are intact after the refusal",
          set(bot.absent_today()) == {"Alice Brown", "Chen Wei"})
    check("sealed sheet is labelled as closed", "no longer be edited" in bot.roster_text(yesterday))

    section("midnight rollover")
    # A screen still showing yesterday's sheet, which carries one ❌.
    bot.STATE["open_screens"]["1001"] = {"chat_id": 999, "message_id": 55, "day": yesterday}
    bot.STATE["attendance"][today] = []          # the new day starts empty
    storage.save(bot.STATE)
    check("the open screen shows an X before midnight",
          any(l.startswith("❌") for l in labels(bot.roster_markup(yesterday))))
    before = len(ctx.bot.edits)
    await bot.midnight_rollover(ctx)
    check("rollover edited the open screen", len(ctx.bot.edits) == before + 1)
    edit = ctx.bot.edits[-1]
    check("it edited the right message", (edit["chat_id"], edit["message_id"]) == (999, 55))
    check("every X sign is gone from the screen",
          not any(l.startswith("❌") for l in labels(edit["markup"])))
    check("screen now points at today", bot.STATE["open_screens"]["1001"]["day"] == today)
    check("yesterday's record survives untouched",
          bot.STATE["attendance"][yesterday] == ["Bob Carter"])

    # Re-mark today so the report below has content.
    await bot.on_button(Update(teacher, query=Query(f"t:{today}:0")), ctx)
    await bot.on_button(Update(teacher, query=Query(f"t:{today}:2")), ctx)

    section("group discovery")
    grp = Chat(-1001234567890, "supergroup", "10-A Parents")
    await bot.on_my_chat_member(
        Update(teacher, my_chat_member=MemberChange(grp, "member"), chat=grp), ctx)
    check("bot records the group it was added to",
          bot.STATE["groups"]["-1001234567890"]["title"] == "10-A Parents")

    grp2 = Chat(-1009876543210, "group", "Staff Room")
    await bot.on_my_chat_member(
        Update(teacher, my_chat_member=MemberChange(grp2, "administrator"), chat=grp2), ctx)
    check("a second group is recorded too", len(bot.STATE["groups"]) == 2)

    await bot.on_group_activity(Update(teacher, chat=Chat(-1001234567890, "supergroup",
                                                          "10-A Parents 2026")), ctx)
    check("a renamed group updates its title",
          bot.STATE["groups"]["-1001234567890"]["title"] == "10-A Parents 2026")

    # A group the bot joined before it was running emits no my_chat_member.
    await bot.on_group_activity(
        Update(teacher, chat=Chat(-1005555555555, "group", "Old Group")), ctx)
    check("a pre-existing group is discovered from activity",
          bot.STATE["groups"]["-1005555555555"]["title"] == "Old Group")
    bot.STATE["groups"].pop("-1005555555555")   # keep later button assertions tidy
    await bot.on_group_activity(Update(teacher, chat=Chat(555, "private")), ctx)
    check("private chats are never treated as groups", "555" not in bot.STATE["groups"])

    section("report")
    rq = Query(f"rep:{today}", Message(chat_id=999, message_id=55))
    await bot.on_button(Update(teacher, query=rq), ctx)
    photo = ctx.bot.photos[-1]
    check("a PNG report is sent", photo["name"].endswith(".png") and photo["size"] > 5000)
    check("caption counts 1 present / 2 absent",
          "Present: <b>1</b>" in photo["caption"] and "Absent: <b>2</b>" in photo["caption"])
    check("report offers a send button per group",
          labels(photo["markup"]) ==
          ["📤 Send to 10-A Parents 2026", "📤 Send to Staff Room"])

    section("sending a report to a group")
    report_msg_id = max(ctx.bot_data["reports"])
    sq = Query(f"snd:{today}:-1001234567890", Message(chat_id=999, message_id=report_msg_id))
    await bot.on_button(Update(teacher, query=sq), ctx)
    delivered = ctx.bot.photos[-1]
    check("the report reached the group", delivered["chat_id"] == -1001234567890)
    check("it reused the rendered image, not a re-render",
          delivered["name"].startswith("FILEID"))
    check("group caption names the sender", "@ivanova" in delivered["caption"])
    check("toast confirms delivery", "Sent to 10-A Parents 2026" in (sq.toasts[-1] or ""))
    check("that button flips to sent",
          labels(sq.markup_edits[-1])[0] == "✅ Sent to 10-A Parents 2026")
    check("the other group is still offered",
          labels(sq.markup_edits[-1])[1] == "📤 Send to Staff Room")

    await bot.on_my_chat_member(
        Update(teacher, my_chat_member=MemberChange(grp2, "left"), chat=grp2), ctx)
    check("leaving a group drops it", "-1009876543210" not in bot.STATE["groups"])
    gone = Query(f"snd:{today}:-1009876543210", Message(message_id=report_msg_id))
    await bot.on_button(Update(teacher, query=gone), ctx)
    check("sending to a group we left is refused",
          any("no longer in that group" in (a or "") for a in gone.alerts))

    section("persistence and codes")
    bot.STATE = storage.load()
    check("absences reloaded from disk",
          set(bot.absent_today()) == {"Alice Brown", "Chen Wei"})
    check("verified users reloaded", bot.is_verified(teacher.id))
    check("groups reloaded", "-1001234567890" in bot.STATE["groups"])

    m = Message("/newcode")
    await bot.cmd_newcode(Update(teacher, message=m), ctx)
    fresh = m.sent[0].split("<code>")[1].split("</code>")[0]
    m2 = Message(fresh)
    await bot.on_text(Update(intruder, message=m2), ctx)
    check("a fresh code verifies a second person", bot.is_verified(intruder.id))
    m3 = Message(fresh)
    await bot.on_text(Update(User(3003, "Third"), message=m3), ctx)
    check("that code is now dead too", "already been used" in m3.sent[0])

    await bot.cmd_reset(Update(teacher, message=Message("/reset")), ctx)
    check("/reset clears today", bot.absent_today() == [])
    check("/reset does not touch sealed days",
          bot.STATE["attendance"][yesterday] == ["Bob Carter"])

    print()
    if failures:
        print(f"{len(failures)} of {total[0]} check(s) FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print(f"All {total[0]} checks passed.")


asyncio.run(main())
