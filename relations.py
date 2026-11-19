# -*- coding: utf-8 -*-
"""关系表的只读查询层：给「小鲸鱼」用的，纯标准库。"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(
    os.environ.get("WHALE_RELATIONS_DB") or (Path(__file__).resolve().parent / "relations.db")
)

KIND_HUMAN = {
    "前后脚聊过": "在群里一前一后说过话",
    "被她在记忆里提到": "被她记住过",
    "同事": "同事",
    "同学": "同学",
    "室友": "室友",
    "朋友": "朋友",
}


def _connect(db: str | Path | None) -> sqlite3.Connection:
    path = Path(db or DEFAULT_DB)
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _person_line(row: sqlite3.Row) -> str:
    bits = [f"{row['name']}（QQ {row['qq']}）"]
    if row["note"]:
        bits.append(f"她自己的备注是「{row['note']}」")
    bits.append(f"在群里说过 {row['msg_count']} 条，{row['first_seen']} 到 {row['last_seen']}")
    if row["aliases"] and row["aliases"] != row["name"]:
        bits.append(f"用过的名字：{row['aliases']}")
    return "，".join(bits)


def find_people(query: str, db: str | Path | None = None, limit: int = 5) -> str:
    # 只取前 40 个字：拖长的查询会把 LIKE 拖慢，也说明这不是在找人
    q = (query or "").strip()[:40]
    if not q:
        return "你要查谁？给我名字或者 QQ 号都行。"
    con = _connect(db)
    try:
        rows = list(con.execute(
            "select * from people where qq=? or name like ? or aliases like ? "
            "order by msg_count desc limit ?",
            (q, f"%{q}%", f"%{q}%", limit),
        ))
        if not rows:
            return f"关系表里没有「{q}」这个人。"
        out = []
        for row in rows[:limit]:
            out.append(_person_line(row))
            qq = row["qq"]
            edges = list(con.execute(
                "select src,dst,kind,weight,evidence,confidence from edges "
                "where src=? or dst=? order by weight desc limit 6",
                (qq, qq),
            ))
            if edges:
                rel = []
                for e in edges:
                    other = e["dst"] if e["src"] == qq else e["src"]
                    who = con.execute("select name from people where qq=?", (other,)).fetchone()
                    label = who["name"] if who else other
                    kind = KIND_HUMAN.get(e["kind"], e["kind"])
                    if e["kind"] == "被她在记忆里提到":
                        rel.append(f"被她记住过 {e['weight']} 次")
                    elif e["kind"] == "前后脚聊过":
                        rel.append(f"和「{label}」一前一后说过 {e['weight']} 次话")
                    else:
                        rel.append(f"跟主人是{kind}" + (f"（原话：{e['evidence'][:40]}）" if e["evidence"] else ""))
                out.append("　" + "；".join(dict.fromkeys(rel)))
            else:
                out.append("　没有可靠的互动记录，只确认他在群里出现过。")
        return "\n".join(out)
    finally:
        con.close()


def group_roster(db: str | Path | None = None, limit: int = 12) -> str:
    con = _connect(db)
    try:
        rows = list(con.execute(
            "select * from people order by msg_count desc limit ?", (limit,)
        ))
        if not rows:
            return "关系表还是空的。"
        lines = []
        for row in rows:
            tag = f"（{row['note']}）" if row["note"] else ""
            lines.append(f"{row['name']}{tag} {row['qq']}：{row['msg_count']} 条，最后 {row['last_seen']}")
        return "群里出现过的人：\n" + "\n".join(lines)
    finally:
        con.close()


def stats(db: str | Path | None = None) -> dict:
    con = _connect(db)
    try:
        return {
            "people": con.execute("select count(*) from people").fetchone()[0],
            "edges": con.execute("select count(*) from edges").fetchone()[0],
        }
    finally:
        con.close()
