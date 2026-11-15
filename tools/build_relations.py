# -*- coding: utf-8 -*-
r"""从 AstrBot 的会话库生成「群关系表」（relations.db）。

思路：群会话历史会被插件裁剪，所以不按"当前历史"算，而是按"见过的消息"累积——
每条消息落一行到 seen 表（sha1 去重），人名和发言量都从 seen 聚合，重跑不会丢人。

只读两个库，只写自己的输出库：
  --chat-db   AstrBot 的 data_v4.db（读 conversations 表里的群会话）
  --mem-db    memory_companion.db（读 memories 表，看谁被她记住过）
  --out       输出的 relations.db 路径

刻意不猜关系：只有群聊里出现「我同事」「我室友」这类明确原话才记关系边，
其余只记「在群里说过多少话」「被她记住过」。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

HEAD = re.compile(r"^\[([^\]]+)\]\s*([^(:]+?)\s*\(ID:(\d+)\):\s*(.*)$", re.S)
REL_WORDS = ("同事", "同学", "室友", "朋友", "班长", "组长", "领导", "老板", "老师",
             "表哥", "表姐", "堂哥", "堂姐", "哥哥", "姐姐", "弟弟", "妹妹", "师父", "老乡")

SCHEMA = """
create table if not exists seen(
    key text primary key, qq text, name text, at text, body text, prev_qq text);
create table if not exists people(
    qq text primary key, name text, aliases text,
    msg_count integer, first_seen text, last_seen text, note text);
create table if not exists edges(
    src text, dst text, kind text, weight integer, evidence text,
    evidence_at text, confidence real, source text,
    primary key (src, dst, kind));
create table if not exists facts(
    id integer primary key autoincrement, subject text, text text, at text, source text);
"""


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(str(part.get("text") or part.get("content") or ""))
            else:
                out.append(str(part))
        return "\n".join(out)
    return str(content or "")


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def group_messages(chat_db: Path, group_session: str) -> list[dict]:
    con = connect(chat_db)
    try:
        row = con.execute("select content from conversations where user_id=?", (group_session,)).fetchone()
    finally:
        con.close()
    if not row:
        return []
    try:
        msgs = json.loads(row["content"])
    except json.JSONDecodeError:
        return []
    out = []
    for m in msgs:
        if m.get("role") != "user":
            continue
        hit = HEAD.match(text_of(m.get("content")).strip())
        if not hit:
            continue
        out.append({"at": hit.group(1), "name": hit.group(2).strip(), "qq": hit.group(3), "body": hit.group(4)})
    return out


def build(args) -> dict:
    mem_db = Path(args.mem_db)
    chat_db = Path(args.chat_db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)

    msgs = group_messages(chat_db, args.group_session)
    prev = None
    added = 0
    for m in msgs:
        key = hashlib.sha1(f"{m['qq']}|{m['at']}|{m['body'][:80]}".encode("utf-8")).hexdigest()
        cur = con.execute(
            "insert or ignore into seen(key,qq,name,at,body,prev_qq) values(?,?,?,?,?,?)",
            (key, m["qq"], m["name"], m["at"], m["body"], (prev or {}).get("qq")),
        )
        added += cur.rowcount
        prev = m
    con.commit()

    rows = list(con.execute("select * from seen"))
    people: dict[str, dict] = {}
    alias: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        qq = r["qq"]
        p = people.setdefault(qq, {"name": r["name"] or qq, "count": 0, "first": r["at"], "last": r["at"]})
        p["count"] += 1
        p["first"] = min(p["first"], r["at"])
        p["last"] = max(p["last"], r["at"])
        if r["name"]:
            p["name"] = r["name"]
            alias[qq].add(r["name"])

    pairs = Counter()
    for r in rows:
        if r["prev_qq"] and r["prev_qq"] != r["qq"]:
            pairs[tuple(sorted((r["prev_qq"], r["qq"])))] += 1

    rel_edges = []
    for r in rows:
        for word in REL_WORDS:
            if re.search(r"我(?:的)?" + word, r["body"] or ""):
                rel_edges.append((r["qq"], word, r["at"], (r["body"] or "")[:120]))

    mem_hits: Counter = Counter()
    mem_samples: dict[str, list[str]] = defaultdict(list)
    if mem_db.exists():
        mem_con = connect(mem_db)
        try:
            flat = {info["name"]: qq for qq, info in people.items()
                    if len((info.get("name") or "").strip()) >= 2}
            for row in mem_con.execute("select content, created_at from memories where validity_status='active'"):
                content = row["content"] or ""
                for name, qq in flat.items():
                    if name and name in content:
                        mem_hits[qq] += 1
                        if len(mem_samples[qq]) < 1:
                            mem_samples[qq].append(f"{row['created_at']}｜{content[:100]}")
        finally:
            mem_con.close()

    for qq, info in people.items():
        note = "主人" if qq == args.owner_qq else ""
        con.execute(
            "insert or replace into people(qq,name,aliases,msg_count,first_seen,last_seen,note) values(?,?,?,?,?,?,?)",
            (qq, info["name"], "、".join(sorted(alias[qq])), info["count"], info["first"], info["last"], note),
        )
    if args.bot_qq:
        exists = con.execute("select name from people where qq=?", (args.bot_qq,)).fetchone()
        if not exists:
            con.execute(
                "insert or replace into people(qq,name,aliases,msg_count,first_seen,last_seen,note) values(?,?,?,?,?,?,?)",
                (args.bot_qq, args.bot_name, args.bot_name, 0, "", "", "她自己"),
            )
        else:
            con.execute("update people set note='她自己' where qq=?", (args.bot_qq,))

    con.execute("delete from edges")
    for (a, b), n in pairs.most_common(40):
        if n < 2:
            continue
        con.execute(
            "insert or replace into edges(src,dst,kind,weight,evidence,evidence_at,confidence,source)"
            " values(?,?,?,?,?,?,?,?)",
            (a, b, "前后脚聊过", n, "", "", 0.3, "group_history"),
        )
    for src, kind, at, ev in rel_edges:
        con.execute(
            "insert or replace into edges(src,dst,kind,weight,evidence,evidence_at,confidence,source)"
            " values(?,?,?,?,?,?,?,?)",
            (src, args.owner_qq, kind, 1, ev, at, 0.7, "group_history"),
        )
    for qq, n in mem_hits.most_common():
        for sample in mem_samples[qq][:1]:
            con.execute(
                "insert or replace into edges(src,dst,kind,weight,evidence,evidence_at,confidence,source)"
                " values(?,?,?,?,?,?,?,?)",
                (qq, args.bot_qq or "bot", "被她在记忆里提到", n, sample, sample[:19], 0.5, "memory"),
            )
    con.commit()

    stats = {
        "messages_seen": len(rows),
        "new_this_run": added,
        "people": con.execute("select count(*) from people").fetchone()[0],
        "edges": con.execute("select count(*) from edges").fetchone()[0],
        "relation_edges": len(rel_edges),
        "top": [(r["name"], r["msg_count"]) for r in con.execute(
            "select name, msg_count from people order by msg_count desc limit 9")],
    }
    con.close()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="从 AstrBot 会话库生成群关系表")
    ap.add_argument("--chat-db", required=True, help="AstrBot 的 data_v4.db")
    ap.add_argument("--mem-db", required=True, help="memory_companion.db")
    ap.add_argument("--out", required=True, help="输出的 relations.db")
    ap.add_argument("--group-session", required=True,
                    help="群会话 id，形如 bot名字:GroupMessage:群号")
    ap.add_argument("--owner-qq", default="", help="主人的 QQ 号（用于关系边指向）")
    ap.add_argument("--bot-qq", default="", help="机器人自己的 QQ 号（可选）")
    ap.add_argument("--bot-name", default="小鲸鱼", help="机器人名字（可选）")
    args = ap.parse_args()
    print(json.dumps(build(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
