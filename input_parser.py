# -*- coding: utf-8 -*-
"""input_parser.py — 玩家输入结构化（独立模块）
============================================================
【职责】把玩家输入按"归属"结构化，供剧情路径使用（战斗路径不调用）。

【语法】
  @名字[：，,（(]内容   →  {名字}：{内容}     角色演出（台词/心理/动作，由AI按文义判断）
  #内容                →  旁白：{内容}        环境/镜头叙述
  无标记文字           →  玩家：{内容}        玩家本人言行
  行首（下一轮地点往XXX前进） → 【场景目标】…   程序注入的地图目标（独立行）

【名字判定】
  1) 名单匹配（roster / npc_agents.json，最长匹配）
  2) 未命中 → 自由名 = @ 后到第一个终止符（：:，,（( 空格换行）
  3) 无终止符且不在名单 → 整段当普通文本（兜底）
  别名：玩家/我/主角/自己 → 统一为「玩家」

【铁律】任何解析失败 → 原样保留，绝不丢字、绝不抛异常。

【升级点】本文件与主程序解耦：新增语法只改这里；主程序只调用
         `parse_player_input(raw, roster=None)`。
"""
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NPC_AGENT_FILE = os.path.join(BASE_DIR, "data", "npc_agents.json")

# 玩家别名（@玩家 / @我 / @主角 / @自己 都归为「玩家」）
PLAYER_ALIASES = {"玩家", "我", "主角", "自己", "本人"}

# 名字终止符：@ 后面取"自由名"时，遇到这些字符即止
_NAME_TERMINATORS = set("：:，,（( \u3000\t\n\r")

# 地图目标前缀（程序在 web_server 注入）：（下一轮地点往XXX前进）
_RE_MAP_PREFIX = re.compile(r'^[（(]\s*下一轮地点往(.+?)前进\s*[）)]\s*')

# 输出标签
LBL_PLAYER = "玩家"
LBL_ASIDE = "旁白"
LBL_SCENE = "【场景目标】"

# 自由名末尾的常见"言语/心思"动词后缀（仅用于"名单外自由名"的边界修正）
# 例：`@周大仁心想，…` → 名字=周大仁，动词"心想"回填到内容
# 注意：只用 ≥2 字后缀，避免误伤"韦一笑/李想"这类以单字结尾的名字
_VERB_SUFFIXES = [
    "冷笑道", "低声道", "沉吟道", "叹息道",
    "心道", "暗想", "心想", "想道", "说道", "问道", "答道", "笑道", "喝道",
    "叹道", "怒道", "叫道", "喊道", "自语", "嘀咕",
]


def _split_free_name_verb(name):
    """自由名末尾是常见动词后缀 → 拆成 (名字, 动词)。剩余不足2字则不拆。"""
    for suf in _VERB_SUFFIXES:
        if name.endswith(suf) and len(name) - len(suf) >= 2:
            return name[:-len(suf)], suf
    return name, ""


# ---------------------------- 名单 ----------------------------
def load_roster_names():
    """全量 NPC 名（按存档顺序）。失败返回 []。"""
    try:
        with open(NPC_AGENT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [str(n.get("name", "")).strip()
                for n in data.get("npc_list", [])
                if isinstance(n, dict) and n.get("name")]
    except Exception:
        return []


# ---------------------------- 内部工具 ----------------------------
def _match_list_name(text, pos, names):
    """在 text[pos:] 开头做"最长匹配"。返回 (name, end_pos) 或 (None, pos)。"""
    best = None
    for nm in (names or []):
        if nm and text.startswith(nm, pos):
            if best is None or len(nm) > len(best):
                best = nm
    if best:
        return best, pos + len(best)
    return None, pos


def _extract_free_name(text, pos):
    """自由名：从 pos 取到第一个终止符。返回 (name, end_pos)。"""
    i, n = pos, len(text)
    while i < n and text[i] not in _NAME_TERMINATORS:
        i += 1
    return text[pos:i].strip(), i


def _skip_separators(text, pos):
    """跳过名字与内容之间的分隔符（：:，, 空格）。"""
    n = len(text)
    while pos < n and text[pos] in "：:，, \t\u3000":
        pos += 1
    return pos


def _unescape(s):
    return s.replace("\\@", "@").replace("\\#", "#")


def _split_segments(text, names):
    """切段。返回 [(kind, name, content), ...]
    kind ∈ {'default','char','aside'}
    """
    segs = []
    i, n = 0, len(text)
    cur_kind, cur_name, cur_sep, cur_start = "default", None, "", 0

    def emit(end):
        nonlocal cur_start, cur_kind, cur_name, cur_sep
        if end > cur_start:
            segs.append((cur_kind, cur_name, cur_sep, text[cur_start:end]))
        cur_start = end
        cur_kind, cur_name, cur_sep = "default", None, ""

    while i < n:
        c = text[i]
        # 转义：\@ \# 当普通字符
        if c == "\\" and i + 1 < n and text[i + 1] in "@#":
            i += 2
            continue
        if c == "#":
            emit(i)
            cur_kind, cur_start = "aside", i + 1
            i += 1
            continue
        if c == "@":
            nm, end = _match_list_name(text, i + 1, names)
            if not nm:
                nm, end = _extract_free_name(text, i + 1)
            if nm:
                emit(i)
                cur_kind, cur_name = "char", nm
                _sep_start = end
                cur_start = _skip_separators(text, end)
                cur_sep = text[_sep_start:cur_start]
                i = cur_start
                continue
            # 无效 @（@ 后为空/无名字）→ 当普通文本
            i += 1
            continue
        i += 1

    emit(n)
    return segs


# ---------------------------- 对外主入口 ----------------------------
def parse_player_input(raw, roster=None, names=None):
    """把玩家输入结构化为多行文本。

    Args:
        raw: 原始输入（可能已含 web_server 注入的「（下一轮地点往…前进）」前缀）
        roster: 可选，有序名单（活跃>临时>全量）；不传则用 npc_agents.json 全量
        names: 兼容参数（同 roster）
    Returns:
        结构化多行字符串；解析失败或空输入则原样返回。
    """
    try:
        if raw is None:
            return ""
        text = str(raw)
        if not text.strip():
            return text
        nm_list = roster or names or load_roster_names()

        scene_lines = []

        # 1) 地图目标前缀（程序注入）→ 抽成独立"场景目标"行
        m = _RE_MAP_PREFIX.match(text)
        if m:
            target = m.group(1).strip()
            if target:
                scene_lines.append(f"{LBL_SCENE}下一轮地点往{target}前进")
            text = text[m.end():]

        # 2) 切段 + 归属
        body = []
        nm_set = set(nm_list or [])
        for kind, name, sep, content in _split_segments(text, nm_list):
            content = _unescape(content).strip()
            if kind == "char" and name:
                # 名单外的自由名：若末尾是"心想/说道"等动词 → 拆出并按原分隔符回填内容
                if name not in nm_set:
                    name, _verb = _split_free_name_verb(name)
                    if _verb:
                        content = f"{_verb}{sep}{content}" if content else _verb
                disp = LBL_PLAYER if name in PLAYER_ALIASES else name
                body.append(f"{disp}：{content}" if content else f"{disp}：")
            elif kind == "aside":
                body.append(f"{LBL_ASIDE}：{content}" if content else f"{LBL_ASIDE}：")
            else:
                if content:
                    body.append(f"{LBL_PLAYER}：{content}")

        out = scene_lines + body
        return "\n".join(out) if out else text
    except Exception as e:
        # 铁律：任何异常 → 原样返回
        try:
            print(f"[input_parser] 解析异常（已降级为原文）: {e}")
        except Exception:
            pass
        return raw if raw is not None else ""


def build_roster(limit=None):
    """构建下拉候选名单：活跃(如需可外部传入) → 这里返回全量名单。
    前端排序（活跃>临时>全量）由 /npc/roster 接口负责，本函数仅兜底。"""
    names = load_roster_names()
    return names[:limit] if (limit and limit > 0) else names
