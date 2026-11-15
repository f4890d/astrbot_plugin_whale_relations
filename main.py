# -*- coding: utf-8 -*-
"""小鲸鱼的关系表：用群聊里真实出现过的发言，回答「这人是谁、跟主人什么关系」。"""
from __future__ import annotations

import os
import sys

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

try:  # 包内导入
    from .relations import DEFAULT_DB, find_people, group_roster, stats
except ImportError:  # 插件被以脚本方式加载时兜底
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from relations import DEFAULT_DB, find_people, group_roster, stats


class WhaleRelations(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.conf = config or {}
        self.db = str(self.conf.get("db_path") or DEFAULT_DB)
        try:
            self.max_chars = max(200, min(4000, int(self.conf.get("max_chars") or 900)))
        except (TypeError, ValueError):
            self.max_chars = 900

    def _clip(self, text: str) -> str:
        text = (text or "").strip()
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars - 1].rstrip() + "…"

    @filter.llm_tool(name="lookup_relation")
    async def lookup_relation(self, event: AstrMessageEvent, query: str) -> str:
        """查群里某个人是谁、跟主人什么关系。

        Args:
            query(string): 名字、群名片或者 QQ 号
        """
        try:
            return self._clip(find_people(query, db=self.db))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale_relations] 查询失败 query={query!r}: {exc}")
            return "关系表打不开，跟主人说一声。"

    @filter.llm_tool(name="group_roster")
    async def group_roster(self, event: AstrMessageEvent) -> str:
        """看看群里都有谁、各自说过多少话。"""
        try:
            return self._clip(group_roster(db=self.db))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[whale_relations] 名单读取失败: {exc}")
            return "关系表打不开，跟主人说一声。"
