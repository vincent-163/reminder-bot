# reminder-bot

一个用于提醒事项的 telegram bot. <https://t.me/xaatopnwivbot>

## 配置

需要在同目录的 `config.json` 里这样写：
```json
{
    "api_id": 12345,
    "api_hash": "",
    "token": "<token>",
    "db": "reminders.db"
}
```
其中 `api_id` 和 `api_hash` 需要从 <http://my.telegram.org/> 获得，`token` 为 Bot 使用的 `token`. `db` 指向存储提醒事项数据的数据库文件，填 `reminders.db` 即可。

## 数据库格式

表 reminders
`CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, text TEXT, rrule TEXT, recurrence_text TEXT, dtstart DATETIME, next_remind_date DATETIME, user_id INTEGER NOT NULL)`
其中：
* id: 自增列，用于标识每条 reminder，用户用 id 操作指定的 reminder
* text: reminder 的内容
* rrule: rfc5545 格式的 rrule。为空时表示事件不重复，否则按照此 rrule 计算事件的下一次发生时间。
* dtstart: 事件的初始时间，配合 rrule 用来决定周期的相位。例如 recurrence 是 “every week”，具体是星期几就由 dtstart 决定。
* recurrence_text: 描述事件周期的字符串。仅用来存储和展示，实际的周期还是得看 rrule.
* next_remind_date: 事件下次触发的时间。对于重复事件来说，事件入库时和 reset 时都要更新。
* user_id: 用户 id.
