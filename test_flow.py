#!/usr/bin/env python3
"""Offline end-to-end check: drives the real handlers with fake Telegram
updates, so the whole flow can be verified without touching the network.

Run:  .venv/bin/python test_flow.py
"""

import asyncio
import datetime as dt
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "0:OFFLINE-TEST")
os.environ["ACCESS_CODES"] = "TEST-AAA, TEST-BBB"
from datetime import timedelta
from pathlib import Path

from telegram.error import ChatMigrated, Forbidden, TelegramError

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
        self.deleted = False

    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return Message()

    async def delete(self):
        self.deleted = True


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
    id = 42

    def __init__(self):
        self.photos, self.docs, self.edits, self.messages = [], [], [], []
        self._n = 100
        self.membership = {}       # chat_id -> status Telegram would report
        self.member_errors = {}    # chat_id -> error raised by get_chat_member
        self.send_fail = {}        # chat_id -> error raised by send_photo
        self.migrate = {}          # chat_id -> new id, raised once as ChatMigrated

    async def get_chat_member(self, chat_id, user_id):
        if chat_id in self.member_errors:
            raise self.member_errors[chat_id]
        return type("M", (), {"status": self.membership.get(chat_id, "member")})()

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
        if chat_id in self.send_fail:
            raise self.send_fail[chat_id]
        if chat_id in self.migrate:
            raise ChatMigrated(self.migrate.pop(chat_id))
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

    async def send_message(self, chat_id, text, reply_markup=None, **kw):
        self._n += 1
        self.messages.append({"chat_id": chat_id, "text": text, "markup": reply_markup})
        return Message(text, chat_id=chat_id, message_id=self._n)

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
    code = "TEST-AAA"
    today = bot.today_key()

    section("access codes come from the server, not the repo")
    check("codes are not stored in config.json",
          "initial_access_codes" not in bot.CONFIG)
    check("ACCESS_CODES env var is registered", "TEST-AAA" in bot.STATE["codes"])
    check("every env code is registered", "TEST-BBB" in bot.STATE["codes"])

    # A code appended to access_codes.txt on the persistent disk goes live
    # without a restart — this is what the 60s refresh job calls.
    bot.codes_file().write_text("DISK-CODE-1\n# a comment line\nDISK-CODE-2\n",
                                encoding="utf-8")
    added = bot.seed_codes(quiet=True)
    check("codes dropped on the disk are picked up", set(added) == {"DISK-CODE-1", "DISK-CODE-2"})
    check("comments in the file are ignored",
          not any(c.startswith("#") for c in bot.STATE["codes"]))
    check("re-reading the file adds nothing twice", bot.seed_codes(quiet=True) == [])

    section("verification")
    m = Message("/start")
    await bot.cmd_start(Update(teacher, message=m), ctx)
    check("unverified /start asks for a code", "код доступа" in m.sent[0])

    q = Query("mark")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("unverified button press blocked", "не верифицированы" in (q.toasts[0] or ""))
    check("unverified press renders no screen", q.screens == [])

    m = Message("hunter2")
    await bot.on_text(Update(teacher, message=m), ctx)
    check("wrong code rejected", "Неверный код" in m.sent[0])

    m = Message(code)
    await bot.on_text(Update(teacher, message=m), ctx)
    check("valid code verifies the user", bot.is_verified(teacher.id))
    check("burn is announced", "использован" in m.sent[0])

    m = Message(code)
    await bot.on_text(Update(intruder, message=m), ctx)
    check("reused code rejected", "уже использован" in m.sent[0])
    check("second account stays unverified", not bot.is_verified(intruder.id))

    section("menu and roster")
    m = Message("hi")
    await bot.on_text(Update(teacher, message=m), ctx)
    check("verified user gets the menu", "верифицированы" in m.sent[0].lower())
    check("menu has both buttons", labels(bot.menu_markup()) ==
          ["📋 Отметить посещаемость", "👁 Посмотреть отмеченную посещаемость"])

    q = Query("mark")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("roster lists every student + report + back",
          labels(q.markups[0]) ==
          ["Alice Brown", "Bob Carter", "Chen Wei", "📄 Сформировать отчёт", "⬅️ Назад"])

    section("toggling")
    q = Query(f"t:{today}:1")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("toast says absent", q.toasts[0] == "Bob Carter отсутствует")
    check("message says absent", "<b>Bob Carter</b> отсутствует" in q.screens[0])
    check("X icon appears on that name", "❌ Bob Carter" in labels(q.markups[0]))
    check("state records the absence", bot.absent_today() == ["Bob Carter"])

    q = Query(f"t:{today}:1")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("toast says present", q.toasts[0] == "Bob Carter присутствует")
    check("message says present", "<b>Bob Carter</b> присутствует" in q.screens[0])
    check("X icon disappears", "❌ Bob Carter" not in labels(q.markups[0]))
    check("state cleared", bot.absent_today() == [])

    await bot.on_button(Update(teacher, query=Query(f"t:{today}:0")), ctx)
    await bot.on_button(Update(teacher, query=Query(f"t:{today}:2")), ctx)
    q = Query("menu")
    await bot.on_button(Update(teacher, query=q), ctx)
    check("go back returns to the menu",
          labels(q.markups[0])[0] == "📋 Отметить посещаемость")

    q = Query("mark", Message(chat_id=999, message_id=55))
    await bot.on_button(Update(teacher, query=q), ctx)
    check("marks persist across screens",
          labels(q.markups[0])[:3] == ["❌ Alice Brown", "Bob Carter", "❌ Chen Wei"])

    section("view marked attendance list (Task 1)")
    before = len(ctx.bot.photos)
    vq = Query("view", Message(chat_id=999, message_id=70))
    await bot.on_button(Update(teacher, query=vq), ctx)
    check("view sends a picture", len(ctx.bot.photos) == before + 1)
    pic = ctx.bot.photos[-1]
    check("the picture is a real PNG", pic["name"].endswith(".png") and pic["size"] > 5000)
    check("exactly two buttons under it", labels(pic["markup"]) == ["✏️ Изменить", "👌 ОК"])
    check("caption reports the marked figures",
          "Присутствуют: <b>1</b>" in pic["caption"] and "Отсутствуют: <b>2</b>" in pic["caption"])

    cq = Query("chg", Message(chat_id=999, message_id=71))
    await bot.on_button(Update(teacher, query=cq), ctx)
    check("Change removes the picture", cq.message.deleted)
    roster_msg = ctx.bot.messages[-1]
    check("Change opens the roster", "Нажмите на имя" in roster_msg["text"])
    check("Change keeps the existing marks",
          labels(roster_msg["markup"])[:3] == ["❌ Alice Brown", "Bob Carter", "❌ Chen Wei"])

    okq = Query("ok", Message(chat_id=999, message_id=72))
    await bot.on_button(Update(teacher, query=okq), ctx)
    check("OK removes the picture", okq.message.deleted)
    check("OK returns to the main menu",
          labels(ctx.bot.messages[-1]["markup"]) ==
          ["📋 Отметить посещаемость", "👁 Посмотреть отмеченную посещаемость"])

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
    check("editing a sealed day is refused", any("закрыта" in (a or "") for a in q.alerts))
    check("sealed data is untouched", bot.STATE["attendance"][yesterday] == ["Bob Carter"])
    check("stale screen swaps to today", bot.pretty_day(today) in q.screens[0])
    check("today's marks are intact after the refusal",
          set(bot.absent_today()) == {"Alice Brown", "Chen Wei"})
    check("sealed sheet is labelled as closed", "изменить его больше нельзя" in bot.roster_text(yesterday))

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
          "Присутствуют: <b>1</b>" in photo["caption"] and "Отсутствуют: <b>2</b>" in photo["caption"])
    check("report offers a send button per group",
          labels(photo["markup"]) ==
          ["📤 Отправить в «10-A Parents 2026»", "📤 Отправить в «Staff Room»"])

    section("sending a report to a group")
    report_msg_id = max(ctx.bot_data["reports"])
    sq = Query(f"snd:{today}:-1001234567890", Message(chat_id=999, message_id=report_msg_id))
    await bot.on_button(Update(teacher, query=sq), ctx)
    delivered = ctx.bot.photos[-1]
    check("the report reached the group", delivered["chat_id"] == -1001234567890)
    check("it reused the rendered image, not a re-render",
          delivered["name"].startswith("FILEID"))
    check("group caption names the sender", "@ivanova" in delivered["caption"])
    check("toast confirms delivery", "Отправлено в «10-A Parents 2026»" in (sq.toasts[-1] or ""))
    check("that button flips to sent",
          labels(sq.markup_edits[-1])[0] == "✅ Отправлено в «10-A Parents 2026»")
    check("the other group is still offered",
          labels(sq.markup_edits[-1])[1] == "📤 Отправить в «Staff Room»")

    await bot.on_my_chat_member(
        Update(teacher, my_chat_member=MemberChange(grp2, "left"), chat=grp2), ctx)
    check("leaving a group drops it", "-1009876543210" not in bot.STATE["groups"])
    gone = Query(f"snd:{today}:-1009876543210", Message(message_id=report_msg_id))
    await bot.on_button(Update(teacher, query=gone), ctx)
    check("sending to a group we left is refused",
          any("Меня больше нет в этой группе" in (a or "") for a in gone.alerts))

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
    check("that code is now dead too", "уже использован" in m3.sent[0])

    m = Message("DISK-CODE-1")
    await bot.on_text(Update(User(4004, "Fourth"), message=m), ctx)
    check("a disk code verifies someone", bot.is_verified(4004))
    bot.seed_codes(quiet=True)
    check("re-seeding does not revive a spent disk code",
          bot.STATE["codes"]["DISK-CODE-1"]["used_by"] == 4004)

    await bot.cmd_reset(Update(teacher, message=Message("/reset")), ctx)
    check("/reset clears today", bot.absent_today() == [])
    check("/reset does not touch sealed days",
          bot.STATE["attendance"][yesterday] == ["Bob Carter"])

    section("stale group buttons")
    bot.STATE["groups"] = {
        "-1001111111111": {"title": "Still In", "type": "group"},
        "-1002222222222": {"title": "Kicked Out", "type": "group"},
    }
    storage.save(bot.STATE)
    ctx.bot.membership = {-1001111111111: "member", -1002222222222: "left"}

    await bot.on_button(Update(teacher, query=Query(f"rep:{today}", Message(message_id=90))), ctx)
    check("a group the bot has left gets no button",
          labels(ctx.bot.photos[-1]["markup"]) == ["📤 Отправить в «Still In»"])
    check("and it is dropped from state", "-1002222222222" not in bot.STATE["groups"])

    bot.STATE["groups"]["-1003333333333"] = {"title": "Flaky", "type": "group"}
    ctx.bot.member_errors = {-1003333333333: TelegramError("temporary failure")}
    live = await bot.live_groups(ctx)
    check("a transient check failure keeps the group", "-1003333333333" in live)
    check("and does not drop it from state", "-1003333333333" in bot.STATE["groups"])
    ctx.bot.member_errors = {}
    bot.STATE["groups"].pop("-1003333333333")

    bot.STATE["groups"]["-1004444444444"] = {"title": "Gone", "type": "group"}
    ctx.bot.membership[-1004444444444] = "member"
    await bot.on_button(Update(teacher, query=Query(f"rep:{today}", Message(message_id=91))), ctx)
    rid = max(ctx.bot_data["reports"])
    ctx.bot.send_fail = {-1004444444444: Forbidden("Forbidden: bot was kicked from the group chat")}
    sq2 = Query(f"snd:{today}:-1004444444444", Message(message_id=rid))
    await bot.on_button(Update(teacher, query=sq2), ctx)
    check("a failed send drops the group", "-1004444444444" not in bot.STATE["groups"])
    check("the user is told why", any("Меня больше нет в группе «Gone»" in (a or "") for a in sq2.alerts))
    check("the dead button disappears", "📤 Отправить в «Gone»" not in labels(sq2.markup_edits[-1]))
    ctx.bot.send_fail = {}

    bot.STATE["groups"]["-1005555555555"] = {"title": "Upgraded", "type": "group"}
    ctx.bot.membership[-1005555555555] = "member"
    await bot.on_button(Update(teacher, query=Query(f"rep:{today}", Message(message_id=92))), ctx)
    rid = max(ctx.bot_data["reports"])
    ctx.bot.migrate = {-1005555555555: -1009999999999}
    sq3 = Query(f"snd:{today}:-1005555555555", Message(message_id=rid))
    await bot.on_button(Update(teacher, query=sq3), ctx)
    check("a migrated group moves to its new id",
          "-1009999999999" in bot.STATE["groups"] and "-1005555555555" not in bot.STATE["groups"])
    check("and the report still arrives", ctx.bot.photos[-1]["chat_id"] == -1009999999999)

    bot.STATE["groups"] = {"-1001234567890": {"title": "10-A Parents 2026", "type": "supergroup"}}
    ctx.bot.membership = {}
    storage.save(bot.STATE)

    section("days off")
    bot.CONFIG["days_off"] = {"weekdays": ["sunday"], "dates": ["2026-09-23"]}
    check("Sunday is a day off", bot.is_day_off(dt.date(2026, 9, 20)))
    check("Monday is not", not bot.is_day_off(dt.date(2026, 9, 21)))
    check("a one-off holiday is a day off", bot.is_day_off(dt.date(2026, 9, 23)))
    bot.CONFIG["days_off"] = {"weekdays": ["Воскресенье"], "dates": []}
    check("Russian weekday names work too", bot.is_day_off(dt.date(2026, 9, 20)))
    check("and don't over-match", not bot.is_day_off(dt.date(2026, 9, 21)))
    bot.CONFIG["days_off"] = {"weekdays": ["sunday"], "dates": ["2026-09-23"]}

    section("scheduled jobs")
    real_now = bot.now

    def freeze(y, mo, d, h, mi=0):
        bot.now = lambda: dt.datetime(y, mo, d, h, mi, tzinfo=bot.TZ)

    # -- Task 3: the unmarked-attendance nudge
    freeze(2026, 9, 15, 9, 40)                    # a Tuesday
    bot.STATE["marked"].pop("2026-09-15", None)
    before = len(ctx.bot.messages)
    await bot.job_unmarked_reminder(ctx)
    check("reminder reaches every verified user",
          len(ctx.bot.messages) == before + len(bot.private_chats()))
    check("reminder says what it should",
          "Вы ещё не отметили посещаемость" in ctx.bot.messages[-1]["text"])
    check("reminder goes to private chats, not groups",
          all(m["chat_id"] > 0 for m in ctx.bot.messages[before:]))

    bot.mark_touched("2026-09-15", teacher.id)
    before = len(ctx.bot.messages)
    await bot.job_unmarked_reminder(ctx)
    check("silent once the register has been taken", len(ctx.bot.messages) == before)

    freeze(2026, 9, 20, 9, 40)                    # Sunday
    bot.STATE["marked"].pop("2026-09-20", None)
    before = len(ctx.bot.messages)
    await bot.job_unmarked_reminder(ctx)
    check("silent on a day off", len(ctx.bot.messages) == before)

    # -- Task 2: Monday morning weekly statistics
    # Start from an empty week: the real "today" may fall inside it and was
    # marked by the toggles earlier in this run.
    stray = [k for k in bot.STATE["marked"] if "2026-09-07" <= k <= "2026-09-13"]
    for k in stray:
        bot.STATE["marked"].pop(k)
    for d, absents in {"2026-09-07": ["Alice Brown", "Bob Carter"],
                       "2026-09-08": ["Alice Brown"],
                       "2026-09-09": []}.items():
        bot.STATE["attendance"][d] = absents
        bot.mark_touched(d, teacher.id)
    bot.STATE["attendance"]["2026-09-10"] = ["Chen Wei"]     # never marked
    bot.STATE["marked"].pop("2026-09-10", None)

    counts, days = bot.week_absences(dt.date(2026, 9, 7), dt.date(2026, 9, 13))
    check("only days with a register are counted", days == 3)
    check("absences tally correctly", counts == {"Alice Brown": 2, "Bob Carter": 1})
    check("a day nobody marked is excluded", "Chen Wei" not in counts)

    freeze(2026, 9, 14, 9)                        # Monday 09:00
    before = len(ctx.bot.photos)
    await bot.job_weekly_stats(ctx)
    expected = len(bot.private_chats()) + len(bot.group_chats())
    check("stats reach every user and every group",
          len(ctx.bot.photos) == before + expected)
    check("stats caption names the week",
          "Посещаемость за неделю" in ctx.bot.photos[-1]["caption"])
    check("stats cover last Mon-Sun, not this week",
          "7 сен" in ctx.bot.photos[-1]["caption"] and "13 сен 2026" in ctx.bot.photos[-1]["caption"])
    check("the image is uploaded once then reused by file_id",
          ctx.bot.photos[before]["name"].endswith(".png")
          and ctx.bot.photos[before + 1]["name"].startswith("FILEID"))

    freeze(2026, 9, 15, 9)                        # Tuesday
    before = len(ctx.bot.photos)
    await bot.job_weekly_stats(ctx)
    check("no stats on a non-Monday", len(ctx.bot.photos) == before)

    freeze(2026, 9, 21, 9)                        # Monday, but no register last week
    for d in list(bot.STATE["marked"]):
        if "2026-09-1" in d:
            bot.STATE["marked"].pop(d)
    before = len(ctx.bot.photos)
    await bot.job_weekly_stats(ctx)
    check("no stats when the register was never taken",
          len(ctx.bot.photos) == before)

    bot.now = real_now

    print()
    if failures:
        print(f"{len(failures)} of {total[0]} check(s) FAILED:")
        for f in failures:
            print("  -", f)
        raise SystemExit(1)
    print(f"All {total[0]} checks passed.")


asyncio.run(main())
