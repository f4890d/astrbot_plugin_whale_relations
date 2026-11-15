# 小鲸鱼的关系表（astrbot_plugin_whale_relations）

给 AstrBot 里的陪伴型机器人一张**只读**的小本子：群里这个人是谁、说过多少话、跟主人是什么关系。

不联网、不调模型、不写别人的库——插件只查一张本地 SQLite 表。

## 为什么写这个

陪伴机器人记得住「跟主人聊过什么」，但常常记不住「群里那个 ID 是谁」。被问「刚才说话那人是谁」时，只能含糊过去。

这个插件的做法很土但可靠：把群聊里真实出现过的发言攒起来（按 `[时间] 昵称(ID:QQ): 正文` 的格式解析），聚合出人名、QQ、发言量、时间段；再从记忆库里找出「谁被她记住过」。**没有明确原话就不猜关系**——只有群里真的出现过「我同事」「我室友」这种句子，才记一条关系边，并附上原话当证据。

## 装法

1. 把整个目录放到 `AstrBot/data/plugins/astrbot_plugin_whale_relations/`
2. 生成数据（见下节），产物默认放在插件目录里的 `relations.db`
3. AstrBot 后台「插件」页启用，或 `POST /plugins/reload`
4. 看到两个工具：`lookup_relation`（查人）、`group_roster`（看名单）

## 生成关系表

`tools/build_relations.py` 只读两个库、只写输出文件，纯标准库：

```bash
python tools/build_relations.py \
  --chat-db   /path/to/AstrBot/data/data_v4.db \
  --mem-db    /path/to/AstrBot/data/plugin_data/astrbot_plugin_memory_companion/memory_companion.db \
  --out       /path/to/AstrBot/data/plugins/astrbot_plugin_whale_relations/relations.db \
  --group-session "机器人名:GroupMessage:群号" \
  --owner-qq  "主人的QQ号" \
  --bot-qq    "机器人的QQ号"
```

- `--mem-db` 不存在也能跑，只是没有「被她在记忆里提到」这类边。
- 可以反复跑：按消息 sha1 累积，群历史被插件裁剪也不会丢人。
- 建议挂个计划任务每半小时跑一次（会话历史会被裁剪，跑得勤才攒得全）。

## 表结构

```sql
people(qq, name, aliases, msg_count, first_seen, last_seen, note)
edges(src, dst, kind, weight, evidence, evidence_at, confidence, source)
seen(key, qq, name, at, body, prev_qq)   -- 累积的消息指纹
facts(id, subject, text, at, source)     -- 预留
```

边只有三种：`前后脚聊过`（相邻发言 ≥2 次，置信 0.3）、`<关系词>`（原话命中「我同事」这类，0.7）、`被她在记忆里提到`（0.5）。每条边都带证据字段。

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `db_path` | 空 | 留空用插件目录下的 `relations.db`；也可设环境变量 `WHALE_RELATIONS_DB` |
| `max_chars` | 900 | 每次查询最多回多少字（上限 4000） |

## 已知限制

- 只解析 `[时间] 昵称(ID:QQ): 正文` 这种带昵称的群消息格式；别的格式会解析出 0 条。
- 关系词只覆盖常见称谓（同事/同学/室友/朋友/家人/师徒/老乡），不做推断。
- 一个群一份表；多群要么分库，要么自己改 `--group-session` 分别跑。
- 数据是本地文件，备份和删除都靠你自己。

## 隐私

- 插件只读自己那份 `relations.db`，不联网。
- 生成器只读 AstrBot 的两个库，且用 `mode=ro` 打开。
- 工具描述里写明了「只在私聊里讲、群里不提」，但最终还是靠人格/skill 约束模型。

## License

MIT
