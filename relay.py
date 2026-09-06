#!/usr/bin/env python3
"""Telegram <-> Notion relay. Runs on GitHub Actions every 5 minutes."""
import json, os, sys, urllib.request
from datetime import datetime, timezone, timedelta

TG = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT_ID"]
NOTION = os.environ["NOTION_TOKEN"]
IN_DB = "12c375bc-2f76-4905-91f4-3a97fafed628"
OUT_DB = "54af158a-9314-444a-b6be-8342a4753642"
MSK = timezone(timedelta(hours=3))

def req(url, data=None, headers=None, method=None):
    body = json.dumps(data).encode() if data is not None else None
    r = urllib.request.Request(url, data=body, method=method)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=45) as resp:
        return json.load(resp)

def tg(method, **params):
    return req("https://api.telegram.org/bot%s/%s" % (TG, method), data=params)

NH = {"Authorization": "Bearer " + NOTION, "Notion-Version": "2022-06-28"}

def notion(path, data=None, method="POST"):
    return req("https://api.notion.com/v1/" + path, data=data,
               headers=NH, method=method)


def pull():
    """Telegram -> Notion. Unconfirmed updates live on Telegram's side."""
    res = tg("getUpdates", timeout=0).get("result", [])
    if not res:
        return 0
    n = 0
    for u in res:
        m = u.get("message") or u.get("edited_message")
        if not m:
            continue
        text = (m.get("text") or m.get("caption") or "").strip()
        if not text:
            continue
        when = datetime.fromtimestamp(m["date"], MSK).isoformat()
        notion("pages", {
            "parent": {"database_id": IN_DB},
            "properties": {
                "Название": {"title": [{"text": {"content": text[:60]}}]},
                "Текст": {"rich_text": [{"text": {"content": text[:1900]}}]},
                "TG ID": {"number": m["message_id"]},
                "Дата": {"date": {"start": when}},
                "Статус": {"status": {"name": "Not started"}},
            }})
        n += 1
    tg("getUpdates", offset=res[-1]["update_id"] + 1, timeout=0)
    return n


def push():
    """Notion -> Telegram. Sends anything queued as 'К отправке'."""
    q = notion("databases/%s/query" % OUT_DB, {
        "filter": {"property": "Статус", "select": {"equals": "К отправке"}},
        "page_size": 20})
    n = 0
    for p in q.get("results", []):
        rt = p["properties"].get("Текст", {}).get("rich_text", [])
        text = "".join(x.get("plain_text", "") for x in rt).strip()
        if not text:
            continue
        try:
            tg("sendMessage", chat_id=CHAT, text=text,
               disable_web_page_preview=True)
            status = "Отправлено"
        except Exception as e:
            print("send failed:", type(e).__name__, file=sys.stderr)
            status = "Ошибка"
        notion("pages/" + p["id"],
               {"properties": {"Статус": {"select": {"name": status}}}},
               method="PATCH")
        n += 1
    return n

if __name__ == "__main__":
    got = pull()
    sent = push()
    print("pulled %d, sent %d" % (got, sent))
