from telethon import TelegramClient, events
from telethon.tl.types import ReplyKeyboardForceReply
import asyncio
import json
import sqlite3
import datetime
from recurrent.event_parser import RecurringEvent
import dateutil.rrule
from dateutil.relativedelta import relativedelta
from peewee import SqliteDatabase, Model, IntegerField, TextField, DateTimeField, BooleanField
import html
import re
import logging

logger = logging.getLogger('peewee')
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)

with open("config.json", "r") as f:
    config = json.load(f)

db = SqliteDatabase(config["db"])

class InvalidRecurrenceTextError(Exception):
    pass

class Reminder(Model):
    user_id = IntegerField(index=True)
    text = TextField()
    rrule = TextField(null=True)
    recurrence_text = TextField()
    dtstart = DateTimeField()
    next_remind_date = DateTimeField(index=True)
    finished = BooleanField(default=False)
    days_in_advance = IntegerField(default=14)

    class Meta:
        database = db

    def parse_recurrence_text(self):
        text = self.recurrence_text
        if "since " in text:
            since = text.split("since ")[-1]
            prev = text[:-len(since)+6]
            r = RecurringEvent(now_date=self.dtstart)
            date = r.parse(since)
            if isinstance(date, datetime.datetime):
                self.dtstart = date
                text = prev
            
        r = RecurringEvent()
        result = r.parse(self.recurrence_text)
        if result is None:
            raise InvalidRecurrenceTextError("Invalid recurrence text")
        if r.is_recurring:
            self.rrule = r.get_RFC_rrule()
            self.reset_next_remind_date()
        else:
            self.rrule = None
            self.next_remind_date = result

    @staticmethod
    def create_reminder(user_id, text, recurrence_text):
        rm = Reminder()
        rm.user_id = user_id
        rm.text = text
        rm.recurrence_text = recurrence_text
        rm.dtstart = datetime.datetime.now()
        rm.parse_recurrence_text()
        rm.save()
        return rm

    def get_next_remind_date_advance(self):
        return self.next_remind_date - datetime.timedelta(days=self.days_in_advance)

    def reset_next_remind_date(self):
        if self.rrule is not None:
            rr = dateutil.rrule.rrulestr(self.rrule, dtstart=self.dtstart)
            self.next_remind_date = rr.after(datetime.datetime.now())

    def done(self):
        if self.rrule is not None:
            rr = dateutil.rrule.rrulestr(self.rrule, dtstart=self.dtstart)
            self.next_remind_date = rr.after(self.next_remind_date)
        else:
            self.finished = True

    def delay_day(self):
        self.next_remind_date += datetime.timedelta(days=1)

    def delay_week(self):
        self.next_remind_date += datetime.timedelta(days=7)

    def delay_month(self):
        self.next_remind_date += relativedelta(months=1)

    def format(self):
        return f"{self.next_remind_date.isoformat()} ({self.id})<{self.days_in_advance}> {self.text}"

db.connect()
db.create_tables([Reminder])

async def main():
    global config

    api_id = config["api_id"]
    api_hash = config["api_hash"]
    token = config["token"]
    client = TelegramClient("session", api_id, api_hash)
    client.parse_mode = "html"
    await client.start(lambda: token)
    print("Client started")

    help_msg = """A reminder bot.

/start, /help: Display this message
/today, /list: List reminders today
/listall: List all reminders
/get <id>: Get detailed information about a reminder
/del <id>: Delete a reminder
/done <id>: Move reminder to next date
/delayd <id>: Delay reminder by one day
/delayw <id>: Delay reminder by one week
/delaym <id>: Delay reminder by one month
/reset <id>: Reset reminder
/edit <id>: Edit reminder
/setadv <id> <days>: Set days to remind in advance
/on <recurrence>: Create a new reminder"""

    # Run function on 06:00AM every day
    async def daily_reminder():
        return # This functionality is disabled
        while True:
            now = datetime.datetime.now()
            next = now.replace(hour=6, minute=0, second=0, microsecond=0)
            if next < now:
                next += datetime.timedelta(days=1)
            await asyncio.sleep((next - now).total_seconds())
            
            lines = []
            before = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
            for rem in Reminder.select().where(Reminder.finished == False).order_by(Reminder.next_remind_date):
                if rem.get_next_remind_date_advance() <= before:
                    lines.append(rem.format())

            for chat in config["chats"]:
                await client.send_message(await client.get_input_entity(chat), "Here are your today's reminders:\n" + "\n".join(lines))
            break
            
    # asyncio.ensure_future(daily_reminder())
    @client.on(events.NewMessage(incoming=True))
    async def on_msg(ev):
        print(ev.sender_id)

    @client.on(events.NewMessage(incoming=True, pattern="^/(start|help)$"))
    async def on_help(ev):
        await ev.reply(help_msg)

    @client.on(events.NewMessage(incoming=True, pattern="^/(today|list)$"))
    async def on_today(ev):
        cur = db.cursor()
        lines = []
        before = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        for rem in Reminder.select().where((Reminder.user_id == ev.sender_id) & (Reminder.finished == False)).order_by(Reminder.next_remind_date):
            if rem.get_next_remind_date_advance() <= before:
                lines.append(rem.format())

        msg = "Here are your reminders:\n" + "\n".join(lines)
        await ev.reply(msg[:4096])

    @client.on(events.NewMessage(incoming=True, pattern="^/listall$"))
    async def on_listall(ev):
        cur = db.cursor()
        lines = []
        for rem in Reminder.select().where((Reminder.user_id == ev.sender_id) & (Reminder.finished == False)).order_by(Reminder.next_remind_date):
            lines.append(rem.format())

        msg = "Here are your reminders:\n" + "\n".join(lines)
        await ev.reply(msg[:4096])

    @client.on(events.NewMessage(incoming=True, pattern="^/on (.*)\n(.+)$"))
    async def on_create(ev):
        recurrence_text, text = ev.pattern_match.group(1, 2)
        try:
            rm = Reminder.create_reminder(ev.sender_id, text, recurrence_text)
            await ev.reply(f"Created reminder {rm.id}, will trigger at {rm.next_remind_date}")
        except InvalidRecurrenceTextError:
            await ev.reply("Invalid recurrence text")

    @client.on(events.NewMessage(incoming=True, pattern="^/done (\\d+?)$"))
    async def on_done(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.done()
            rm.save()
            await ev.reply("Reminder done")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/delayd (\\d+?)$"))
    async def on_delayd(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.delay_day()
            rm.save()
            await ev.reply("Reminder delayed by 1 day")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/reset (\\d+?)$"))
    async def on_reset(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.reset_next_remind_date()
            rm.save()
            await ev.reply("Reminder reset")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/delayw (\\d+?)$"))
    async def on_delayw(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.delay_week()
            rm.save()
            await ev.reply("Reminder delayed by 1 week")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/delaym (\\d+?)$"))
    async def on_delayw(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.delay_month()
            rm.save()
            await ev.reply("Reminder delayed by 1 month")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/setadv (\\d+?) (\\d+?)$"))
    async def on_setadv(ev):
        id, adv = int(ev.pattern_match.group(1)), int(ev.pattern_match.group(2))
        if not adv >= 1 and adv <= 30:
            await ev.reply("Days must be between 1 and 30")
            return
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.days_in_advance = adv
            rm.save()
            await ev.reply("Reminder done")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/edit (\\d+?)$"))
    async def on_edit(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            cmd = f"/edit {id} {rm.recurrence_text}\n{rm.text}"
            await ev.reply(f"Copy the following command:\n<pre>{html.escape(cmd)}</pre>")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/edit (\\d+?) (.+)\n(.+)$"))
    async def on_edit(ev):
        id = int(ev.pattern_match.group(1))
        recurrence_text, text = ev.pattern_match.group(2, 3)

        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.text = text
            rm.recurrence_text = recurrence_text
            rm.parse_recurrence_text()
            rm.reset_next_remind_date()
            rm.save()
            await ev.reply(f"Reminder {id} saved")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/del (\\d+?)$"))
    async def on_del(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.get((Reminder.user_id == ev.sender_id) & (Reminder.id == id))
            rm.delete_instance()
            await ev.reply(f"Reminder {id} deleted")
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    @client.on(events.NewMessage(incoming=True, pattern="^/get (\\d+?)$"))
    async def on_get(ev):
        id = int(ev.pattern_match.group(1))
        try:
            rm = Reminder.select().where((Reminder.user_id == ev.sender_id) & (Reminder.id == id)).dicts().get()
            await ev.reply(repr(rm))
        except Reminder.DoesNotExist:
            await ev.reply(f"Reminder {id} not found")

    await client.run_until_disconnected()

asyncio.run(main())
