# -*- coding: utf-8 -*-
"""
气血内力系统 V5（百分比版）
=====================================
核心思想：所有角色（玩家+NPC）的 HP/MP 均为 0-100 的百分比整数。
境界高低不改变数值上限，而是体现在每次结算的变化量上：
- 低境界打高境界：HP 变化 -1 ~ -3（高人内力护体，伤势轻微）
- 高境界打低境界：HP 变化 -6 ~ -12（一掌重创）
- 吸内力：吸方 MP+4，被吸方 MP-4
- 化功大法：目标 MP-4

数据结构：
  npc_agents.json -> 每个NPC: "vitality": {"hp": 100, "mp": 100, "poisoned": false}
  player.json     -> "vitality": {"hp": 100, "mp": 100, "poisoned": false}

哨兵值：
  HP = -1 -> 已故（终态，唯一能解除的方式是控制台「恢复NPC」命令）
  HP = 0  -> 濒死（锁血，AI 必须写结局收尾）
  HP > 0  -> 正常区间

AI 协议（挂载在 update_game_state 工具上）：
  "vitality_change": [
      {"name": "张三", "hp_pct": -5, "mp_pct": 0},
      {"name": "玩家", "hp_pct": 0, "mp_pct": +4}
  ]
  name 可以是玩家名或NPC名。省略字段视为 0。

正则兜底（工具未提供时解析正文）：
  【体力结算】张三：气血-5，内力+0
  【体力结算】玩家：气血-2，内力-10
"""

import re
import os
import json
from file_utils import save_json, load_json

NPC_AGENT_FILE = "data/npc_agents.json"
PLAYER_FILE = "data/player.json"

# 单轮单角色变化量钳制（防止AI输出 ±100 直接秒杀/满血）
MAX_DELTA = 40

# HP -> body_status 映射（HP 是唯一真相源）
def hp_to_status(hp):
    if hp < 0:
        return "deceased"
    if hp == 0:
        return "dying"
    if hp <= 30:
        return "heavy_injured"
    if hp <= 70:
        return "light_injured"
    return "normal"


STATUS_CN = {
    "normal": "健康",
    "light_injured": "轻伤",
    "heavy_injured": "重伤",
    "dying": "濒死",
    "deceased": "已故",
}


# ---------- 工具 schema 片段（拼进 main.py 的 update_game_state） ----------
VITALITY_TOOL_SCHEMA = {
    "type": "array",
    "description": (
        "气血内力结算列表（0-100百分比刻度）。本轮交手/疗伤/运功后有变化的角色才报，"
        "无变化则省略整个字段。name可以填玩家姓名或NPC姓名。"
        "数值原则：境界悬殊时，强者一击可重创弱者，弱者反击难伤强者分毫；"
        "具体数值由你根据剧情自行把握，负数受伤/消耗，正数恢复/获得"
    ),
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "角色姓名（玩家名或NPC名）"},
            "hp_pct": {"type": "integer", "description": "生命百分比变化量，负数受伤正数恢复"},
            "mp_pct": {"type": "integer", "description": "内力百分比变化量，负数消耗正数恢复"},
        },
        "required": ["name"],
    },
}


# ---------- 状态上报schema（tool字段，两条管线共用；须在BATTLE_VITALITY_TOOL前定义） ----------
EFFECT_UPDATE_SCHEMA = {
    "type": "array",
    "description": (
        "状态变化上报列表（武侠状态：中毒/被封内力/点穴/醉酒等，状态库见【气血内力面板】）。"
        "本轮有角色获得或解除状态才报，无变化省略。"
        "effect_id只能从状态库列出的id中选，乱编会被系统忽略"
    ),
    "items": {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["add", "remove"],
                   "description": "add=获得状态 remove=解除状态"},
            "target": {"type": "string", "description": "角色姓名（玩家名或NPC名）"},
            "effect_id": {"type": "string", "description": "状态id（从状态库中选）"},
            "stacks": {"type": "integer", "description": "层数（默认1，上限按状态库）"},
            "rounds": {"type": "integer", "description": "持续回合数（默认按状态库）"},
            "source": {"type": "string", "description": "施加者（可选）"},
        },
        "required": ["op", "target", "effect_id"],
    },
}

# ---------- 对战专用极简工具（battle管线：tool优先，正则兜底） ----------
BATTLE_VITALITY_TOOL = {
    "type": "function",
    "function": {
        "name": "battle_settle_vitality",
        "description": (
            "对战回合气血内力结算工具。每回合交手后必须调用一次，"
            "上报双方（玩家与对手）本回合的变化量；双方都要报，无变化写0。"
            "若无法调用工具，才在正文末尾单独输出【体力结算】行兜底。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "vitality_change": VITALITY_TOOL_SCHEMA,
                "effect_update": EFFECT_UPDATE_SCHEMA,
            },
            "required": ["vitality_change"],
        },
    },
}


def parse_vitality_tool_calls(tool_calls):
    """从 tool_calls 中提取气血内力变化列表（兼容 battle_settle_vitality / update_game_state）。
    返回 [{name, hp_pct, mp_pct}]，无有效数据返回空列表。"""
    changes = []
    if not tool_calls:
        return changes
    for tc in tool_calls:
        try:
            fname = getattr(getattr(tc, "function", None), "name", "") or ""
            if fname not in ("battle_settle_vitality", "update_game_state"):
                continue
            raw_args = tc.function.arguments
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            _list = args.get("vitality_change", [])
            if isinstance(_list, list):
                changes.extend(_list)
        except Exception:
            continue
    return changes


# ---------- 正则兜底 ----------
# 【体力结算】张三：气血-5，内力+0（兼容数值后带括号注释/带百分号/多种分隔符/冒号缺失用空格替代）
_V_NUM = r"[+−-]?\d+(?:\s*%)?(?:[（(][^）)]*[）)])?"
# 分隔符族：气血↔内力之间的常见AI漂移符（8种标点）；也允许"纯空格/制表符/换行替代分隔符"
_V_SEP = r"[,，、;；/|｜]"
_V_SEP_OR_SPACE = r"(?:" + _V_SEP + r"|\s+)"
# 名字字符（原子级）：普通合法字，且禁止"气"后跟"血"、禁止"内"后跟"力"——解决【骆冰气血+1】被名字组
# 误吃成"骆冰气血"（后面没有冒号/空格就断不开的bug）
_NAME_CH = r"(?:[^：:，,\s（(气内]|[气内](?!血|力))"
# 人名↔气血之间：冒号(全/半角)/空格/或两者都有，**也允许直接贴着**（0个分隔字符）
#   这样【骆冰气血+1】就能正确切成 名字="骆冰" + 直接到"气血"
_NAME_SEP = r"[：:\s]*"
VITALITY_REGEX = re.compile(
    r"【体力结算】\s*(" + _NAME_CH + r"+)\s*" + _NAME_SEP + r"\s*气血\s*("
    + _V_NUM
    + r")\s*" + _V_SEP_OR_SPACE + r"\s*内力\s*("
    + _V_NUM
    + r")"
)
# 续行：前缀行后紧跟的不带前缀行（AI常把第二个人的结算直接换行写在后面）
#   行首行尾锁定 + 与主正则保持相同的人名分隔/气血内力分隔规则
VITALITY_LINE_REGEX = re.compile(
    r"^\s*(" + _NAME_CH + r"+)\s*" + _NAME_SEP + r"\s*气血\s*("
    + _V_NUM
    + r")\s*" + _V_SEP_OR_SPACE + r"\s*内力\s*("
    + _V_NUM
    + r")\s*$"
)


def _to_int(raw):
    """'−2%'/'-2（注释）' → -2：统一全角减号、截取数值部分转int，失败返回None"""
    if raw is None:
        return None
    m = re.match(r"^\s*([+−-]?\d+)", str(raw).replace("−", "-"))
    return int(m.group(1)) if m else None


def parse_vitality_regex(reply_text):
    """解析正文中的【体力结算】行，返回 [{name, hp_pct, mp_pct}]
    支持两种形态：
    1. 带【体力结算】前缀的行
    2. 紧跟在前缀行之后的续行（如 AI 常见的多人结算连写）
    3. AI拆行：同一条结算被拆成两行（如"【体力结算】骆冰：气血+1\n内力+2"）
       处理：逐行扫描，若上一行含"气血XX"但缺内力段，当前行含纯"内力XX"则合并回上一行
    """
    results = []
    if not reply_text:
        return results
    lines = reply_text.splitlines()
    # 预处理：合并 AI 拆行的气血/内力分离
    merged = []
    for line in lines:
        # 合并条件：上一行含"气血"+数字（无分隔符+内力段），当前行以"内力"+数字开头
        if (merged
                and re.search(r"气血\s*[+−-]?\d+", merged[-1])
                and not re.search(_V_SEP + r"\s*内力", merged[-1])
                and re.match(r"^\s*内力\s*[+−-]?\d+", line)):
            merged[-1] = f"{merged[-1]}，{line.strip()}"   # 拼接逗号，与主正则兼容
        else:
            merged.append(line)

    prev_was_settle = False
    for line in merged:
        m = VITALITY_REGEX.search(line)
        if m:
            prev_was_settle = True
        else:
            m = VITALITY_LINE_REGEX.match(line) if prev_was_settle else None
            if not m:
                prev_was_settle = False
                continue
            # 续行不能是剧情正文中的普通人名描述（要求名字后紧跟气血/内力格式才命中）
        name = m.group(1).strip()
        hp = _to_int(m.group(2))
        mp = _to_int(m.group(3))
        if hp is None or mp is None:
            prev_was_settle = VITALITY_REGEX.search(line) is not None
            continue
        if name:
            results.append({"name": name, "hp_pct": hp, "mp_pct": mp})
    return results


# ---------- 变化量校验 ----------
def _clamp_delta(v):
    if v is None:
        return 0
    try:
        v = int(v)
    except (TypeError, ValueError):
        return 0
    if v > MAX_DELTA:
        return MAX_DELTA
    if v < -MAX_DELTA:
        return -MAX_DELTA
    return v


def _normalize_vitality(v):
    """规范化 vitality dict：补全字段 + 类型修正"""
    if not isinstance(v, dict):
        v = {}
    hp = v.get("hp", 100)
    mp = v.get("mp", 100)
    poisoned = v.get("poisoned", False)
    try:
        hp = int(hp)
    except (TypeError, ValueError):
        hp = 100
    try:
        mp = int(mp)
    except (TypeError, ValueError):
        mp = 100
    # hp 保持 -1~100（-1是哨兵）
    if hp > 100:
        hp = 100
    if hp < -1:
        hp = -1
    if mp > 100:
        mp = 100
    if mp < 0:
        mp = 0
    return {"hp": hp, "mp": mp, "poisoned": bool(poisoned)}


# ---------- 应用变化量 ----------
def apply_delta(hp, mp, hp_d, mp_d):
    """应用变化量并返回 (new_hp, new_mp, event)"""
    hp_d = _clamp_delta(hp_d)
    mp_d = _clamp_delta(mp_d)
    event = ""

    # 已故(-1)不可恢复不可再掉（气血内力全部冻结）
    if hp == -1:
        return hp, mp, "已故角色，变化被忽略"

    old_hp = hp
    hp = hp + hp_d
    # HP>0受伤：最低降到0（濒死）；HP=0再受伤：直接亡故（-1）
    if hp < 0:
        hp = -1 if old_hp == 0 else 0
    if hp > 100:
        hp = 100

    # 濒死(0)不允许通过常规恢复直接跳回健康：单轮最多回到 15
    if old_hp == 0 and hp_d > 0:
        hp = min(hp, 15)

    mp = mp + mp_d
    if mp > 100:
        mp = 100
    if mp < 0:
        mp = 0

    if hp == -1 and old_hp == 0:
        event = "角色伤重不治身亡！AI 应当撰写死亡收场剧情"
    elif hp == 0 and old_hp > 0:
        event = "角色濒死！AI 应当撰写结局或重创收场剧情"
    return hp, mp, event


# ---------- 临时NPC（内存缓存） ----------
# 临时NPC（场景中新出现的、未落盘的角色）：模拟 100/100，不写文件
_TEMP_VITALITY = {}


def get_temp_vitality(name):
    return dict(_TEMP_VITALITY.get(name, {"hp": 100, "mp": 100, "poisoned": False}))


def set_temp_vitality(name, vit):
    _TEMP_VITALITY[name] = _normalize_vitality(vit)


def clear_temp_vitality(name=None):
    if name is None:
        _TEMP_VITALITY.clear()
    else:
        _TEMP_VITALITY.pop(name, None)


# ---------- 玩家存取 ----------
def get_player_vitality():
    data = load_json(PLAYER_FILE)
    if not data:
        return {"hp": 100, "mp": 100, "poisoned": False}
    return _normalize_vitality(data.get("vitality"))


def set_player_vitality(vit):
    data = load_json(PLAYER_FILE)
    if not data:
        return False
    data["vitality"] = _normalize_vitality(vit)
    save_json(PLAYER_FILE, data)
    return True


# ---------- NPC 存取（落盘的正式NPC） ----------
def get_npc_vitality(name):
    data = load_json(NPC_AGENT_FILE)
    if not data or "npc_list" not in data:
        return None
    for npc in data["npc_list"]:
        if npc.get("name") == name:
            return read_npc_vitality(npc)
    return None


def read_npc_vitality(npc):
    """统一读取NPC的vitality（含迁移+亡故刷新）：
    - 无 vitality 字段 → 按 body_status 推导（T0 自愈）
    - body_status == deceased → HP 强制刷新为 -1（亡故哨兵，双写一致）
    """
    if "vitality" not in npc:
        vit = _migrate_npc_vitality(npc)
    else:
        vit = _normalize_vitality(npc["vitality"])
    if npc.get("body_status") == "deceased" and vit["hp"] != -1:
        vit = {"hp": -1, "mp": vit["mp"], "poisoned": vit["poisoned"]}
        npc["vitality"] = vit
    return vit


def set_npc_vitality(name, vit):
    data = load_json(NPC_AGENT_FILE)
    if not data or "npc_list" not in data:
        return False
    for npc in data["npc_list"]:
        if npc.get("name") == name:
            npc["vitality"] = _normalize_vitality(vit)
            _sync_body_status(npc)
            save_json(NPC_AGENT_FILE, data)
            return True
    return False


def _migrate_npc_vitality(npc):
    """旧存档迁移：无 vitality 字段时，按 body_status 推导初始 HP（T0 自愈）"""
    status = npc.get("body_status", "normal")
    status_hp = {
        "normal": 100,
        "light_injured": 80,
        "heavy_injured": 40,
        "dying": 0,
        "deceased": -1,
    }
    hp = status_hp.get(status, 100)
    poisoned = status == "poisoned"
    vit = {"hp": hp, "mp": 100, "poisoned": poisoned}
    npc["vitality"] = vit
    return vit


def migrate_all_npcs(force=False):
    """全量迁移 npc_agents.json（启动时调用一次）
    - 补全缺失的 vitality 字段
    - body_status=deceased 的NPC强制刷新 HP=-1（亡故哨兵）
    force=True 时无论是否已有字段都重新校验一遍
    """
    data = load_json(NPC_AGENT_FILE)
    if not data or "npc_list" not in data:
        return 0
    count = 0
    for npc in data["npc_list"]:
        had_vit = "vitality" in npc
        old_vit = dict(npc.get("vitality") or {})
        read_npc_vitality(npc)
        if not had_vit or npc.get("vitality") != old_vit:
            count += 1
    if count > 0:
        save_json(NPC_AGENT_FILE, data)
    return count


def _sync_body_status(npc):
    """HP -> body_status 单向同步（HP 是唯一真相源）"""
    vit = _normalize_vitality(npc.get("vitality"))
    hp = vit["hp"]
    status = hp_to_status(hp)
    if status == "poisoned" and not vit["poisoned"]:
        # 保留 poisoned 正交状态
        pass
    if vit["poisoned"] and status == "normal":
        status = "poisoned"
    npc["body_status"] = status
    npc["vitality"] = vit


# ---------- 姓名匹配 ----------
def find_npc_name(raw_name, npc_names):
    """模糊匹配NPC名：精确 > 去后缀 > 包含"""
    raw = (raw_name or "").strip()
    if not raw:
        return None
    if raw in npc_names:
        return raw
    for n in npc_names:
        if n in raw or raw in n:
            return n
    return None


# ---------- 核心结算入口 ----------
def settle_vitality(changes, player_name=None, scene_npc_names=None, user_action=""):
    """
    结算一批变化量。
    :param changes: [{name, hp_pct, mp_pct}]
    :param player_name: 玩家姓名（命中则改 player.json）
    :param scene_npc_names: 本轮场景中的NPC名单（临时NPC也在这里，未落盘的走内存缓存）
    :return: dict {name: {"hp": .., "mp": .., "old_hp": .., "old_mp": .., "event": str, "temp": bool}}
    """
    results = {}
    if not changes:
        return results
    scene_npc_names = scene_npc_names or []

    # 分三类：玩家 / 落盘NPC / 临时NPC
    npc_data = load_json(NPC_AGENT_FILE)
    npc_list = npc_data.get("npc_list", []) if npc_data else []
    persisted_names = {n.get("name", "") for n in npc_list}

    player_changed = False
    player_vit = get_player_vitality()
    npc_dirty = False

    for ch in changes:
        if not isinstance(ch, dict):
            continue
        raw_name = (ch.get("name") or "").strip()
        if not raw_name:
            continue
        hp_d = ch.get("hp_pct", 0)
        mp_d = ch.get("mp_pct", 0)
        if hp_d == 0 and mp_d == 0:
            continue

        # 1) 玩家
        if player_name and raw_name == player_name:
            old_hp, old_mp = player_vit["hp"], player_vit["mp"]
            new_hp, new_mp, event = apply_delta(old_hp, old_mp, hp_d, mp_d)
            player_vit = {"hp": new_hp, "mp": new_mp, "poisoned": player_vit["poisoned"]}
            player_changed = True
            results[raw_name] = {
                "hp": new_hp, "mp": new_mp, "old_hp": old_hp, "old_mp": old_mp,
                "event": event, "temp": False,
            }
            continue

        # 2) 落盘NPC
        matched = find_npc_name(raw_name, list(persisted_names)) if raw_name not in persisted_names else raw_name
        if matched:
            for npc in npc_list:
                if npc.get("name") == matched:
                    if "vitality" not in npc:
                        _migrate_npc_vitality(npc)
                    vit = _normalize_vitality(npc.get("vitality"))
                    old_hp, old_mp = vit["hp"], vit["mp"]
                    new_hp, new_mp, event = apply_delta(old_hp, old_mp, hp_d, mp_d)
                    vit = {"hp": new_hp, "mp": new_mp, "poisoned": vit["poisoned"]}
                    npc["vitality"] = vit
                    _sync_body_status(npc)
                    npc_dirty = True
                    results[matched] = {
                        "hp": new_hp, "mp": new_mp, "old_hp": old_hp, "old_mp": old_mp,
                        "event": event, "temp": False,
                    }
                    break
            continue

        # 3) 临时NPC（场景内提到但未落盘）
        matched_temp = find_npc_name(raw_name, scene_npc_names)
        if matched_temp:
            vit = get_temp_vitality(matched_temp)
            old_hp, old_mp = vit["hp"], vit["mp"]
            new_hp, new_mp, event = apply_delta(old_hp, old_mp, hp_d, mp_d)
            vit = {"hp": new_hp, "mp": new_mp, "poisoned": vit["poisoned"]}
            set_temp_vitality(matched_temp, vit)
            results[matched_temp] = {
                "hp": new_hp, "mp": new_mp, "old_hp": old_hp, "old_mp": old_mp,
                "event": event, "temp": True,
            }

    # 统一落盘
    if player_changed:
        set_player_vitality(player_vit)
    if npc_dirty:
        save_json(NPC_AGENT_FILE, npc_data)

    return results


# ---------- 状态块渲染（注入上下文） ----------
def render_vitality_block(player_name, scene_npc_names=None, max_npcs=8):
    """
    渲染当前气血内力状态块，注入 dynamic_info。
    显示规则：HP/MP 一律带 % 号，已故显示 HP:0%（已故），濒死显示 HP:0%（濒死）
    """
    lines = []
    vit = get_player_vitality()
    if vit["hp"] < 0:
        p_hp = "0%（已故）"
    elif vit["hp"] == 0:
        p_hp = "0%（濒死锁血）"
    else:
        p_hp = f"{vit['hp']}%"
    p_mp = f"{vit['mp']}%"
    if vit["mp"] == 0:
        p_mp += "（⚠内力枯竭：无法催动武功，招式威力大幅减弱）"
    lines.append(f"・{player_name or '主角'}：HP {p_hp} / MP {p_mp}")

    scene_npc_names = scene_npc_names or []
    if scene_npc_names:
        npc_data = load_json(NPC_AGENT_FILE)
        npc_list = npc_data.get("npc_list", []) if npc_data else []
        persisted = {n.get("name", ""): n for n in npc_list}
        shown = 0
        for name in scene_npc_names:
            if shown >= max_npcs:
                break
            if player_name and name == player_name:
                continue
            if name in persisted:
                npc = persisted[name]
                v = read_npc_vitality(npc)
                temp = False
            else:
                v = get_temp_vitality(name)
                temp = True
            if v["hp"] < 0:
                hp_s = "0%（已故）"
            elif v["hp"] == 0:
                hp_s = "0%（濒死锁血）"
            else:
                hp_s = f"{v['hp']}%"
            mp_s = f"{v['mp']}%"
            if v["mp"] == 0:
                mp_s += "（⚠内力枯竭：无法催动武功，招式威力大幅减弱）"
            tag = "（临时角色）" if temp else ""
            lines.append(f"・{name}{tag}：HP {hp_s} / MP {mp_s}")
            shown += 1

    if len(lines) <= 1:
        lines.append("・（本场景暂无其他角色）")
    # ===== 状态词条简报（effects：给剧情AI看的中毒/受制等词条，无状态不占行） =====
    try:
        _eff_brief = render_effects_brief(player_name, scene_npc_names=scene_npc_names, max_npcs=max_npcs)
        if _eff_brief:
            lines.append("・――― 状态词条 ―――")
            lines.append(_eff_brief)
    except Exception:
        pass
    return "\n".join(lines)


# ---------- 控制台恢复命令 ----------
def restore_npc_full(name):
    """恢复NPC：HP/MP 全部重置为 100，无论当前是 -1（已故）还是 0（濒死）"""
    data = load_json(NPC_AGENT_FILE)
    if not data or "npc_list" not in data:
        return False, "未找到NPC数据文件"
    for npc in data["npc_list"]:
        if npc.get("name") == name:
            npc["vitality"] = {"hp": 100, "mp": 100, "poisoned": False}
            npc["body_status"] = "normal"
            npc["body_status_desc"] = "伤势痊愈，气血内力尽复"
            save_json(NPC_AGENT_FILE, data)
            return True, f"NPC「{name}」HP/MP 已全部恢复至 100%"
    # 临时NPC也允许恢复
    if name in _TEMP_VITALITY:
        _TEMP_VITALITY[name] = {"hp": 100, "mp": 100, "poisoned": False}
        return True, f"临时角色「{name}」HP/MP 已全部恢复至 100%"
    return False, f"未找到 NPC「{name}」"


def restore_player_full():
    """恢复玩家：HP/MP 重置为 100"""
    ok = set_player_vitality({"hp": 100, "mp": 100, "poisoned": False})
    return ok, "主角 HP/MP 已全部恢复至 100%" if ok else "玩家存档不存在"


# ---------- 周期性自然恢复 ----------
NATURAL_REGEN_ROUNDS = 5   # 每N轮触发一次
NATURAL_REGEN_HP = 10      # 气血+10%
NATURAL_REGEN_MP = 20      # 内力+20%

def natural_regen(round_num):
    """周期性自然恢复：每N轮，玩家+所有落盘NPC 气血+10/内力+20。
    规则：已故(-1)冻结、濒死(0=HP)不自动恢复（须剧情疗伤），上限100不溢出。
    未到周期零开销直接返回空串；满血全员不写盘。"""
    if round_num <= 0 or round_num % NATURAL_REGEN_ROUNDS != 0:
        return ""
    changed = []
    # 玩家
    pv = get_player_vitality()
    if pv["hp"] > 0 or pv["mp"] < 100:  # 濒死(0)/已故(-1)的HP不动，MP仍恢复
        old = (pv["hp"], pv["mp"])
        if pv["hp"] > 0:
            pv["hp"] = min(100, pv["hp"] + NATURAL_REGEN_HP)
        pv["mp"] = min(100, pv["mp"] + NATURAL_REGEN_MP)
        if (pv["hp"], pv["mp"]) != old:
            set_player_vitality(pv)
            changed.append(f"主角：HP {old[0]}→{pv['hp']}%，MP {old[1]}→{pv['mp']}%")
    # NPC
    data = load_json(NPC_AGENT_FILE)
    if data and "npc_list" in data:
        dirty = False
        for npc in data["npc_list"]:
            if npc.get("body_status") == "deceased":
                continue  # 亡故冻结
            vit = _normalize_vitality(npc.get("vitality") or {"hp": 100, "mp": 100})
            old = (vit["hp"], vit["mp"])
            if vit["hp"] > 0:  # 濒死(0)不自动恢复
                vit["hp"] = min(100, vit["hp"] + NATURAL_REGEN_HP)
            vit["mp"] = min(100, vit["mp"] + NATURAL_REGEN_MP)
            if (vit["hp"], vit["mp"]) != old:
                npc["vitality"] = vit
                _sync_body_status(npc)  # HP回升自动降级伤势（重伤→轻伤）
                dirty = True
                changed.append(f"{npc['name']}：HP {old[0]}→{vit['hp']}%，MP {old[1]}→{vit['mp']}%")
        if dirty:
            save_json(NPC_AGENT_FILE, data)
    return "\n".join(changed)


# ---------- 对战回合回气 ----------
BATTLE_REGEN_MP = 3   # 对战每回合双方回气

def battle_regen_mp(player_name, npc_names):
    """对战回合回气：双方 MP+3%（上限100）。
    只回MP不动HP（战斗中活血不现实）；已故(-1)冻结；
    落盘NPC批量改一次落盘，临时NPC（未落盘）走内存缓存。
    返回恢复日志（空串=无变化）。"""
    npc_names = [n for n in (npc_names or []) if n]
    if not player_name and not npc_names:
        return ""
    changed = []
    # 玩家
    if player_name:
        pv = get_player_vitality()
        if pv["hp"] != -1 and pv["mp"] < 100:
            old_mp = pv["mp"]
            pv["mp"] = min(100, pv["mp"] + BATTLE_REGEN_MP)
            set_player_vitality(pv)
            changed.append(f"主角：MP {old_mp}→{pv['mp']}%（回气）")
    # NPC：落盘与临时分开处理
    data = load_json(NPC_AGENT_FILE)
    npc_list = data.get("npc_list", []) if data else []
    persisted_names = {n.get("name", "") for n in npc_list}
    dirty = False
    for raw in npc_names:
        matched = raw if raw in persisted_names else find_npc_name(raw, list(persisted_names))
        if matched:
            for npc in npc_list:
                if npc.get("name") == matched:
                    if npc.get("body_status") == "deceased":
                        break  # 亡故冻结
                    vit = _normalize_vitality(npc.get("vitality") or {"hp": 100, "mp": 100})
                    if vit["mp"] < 100:
                        old_mp = vit["mp"]
                        vit["mp"] = min(100, vit["mp"] + BATTLE_REGEN_MP)
                        npc["vitality"] = vit
                        dirty = True
                        changed.append(f"{matched}：MP {old_mp}→{vit['mp']}%（回气）")
                    break
            continue
        # 临时NPC（内存缓存）
        vit = get_temp_vitality(raw)
        if vit["mp"] < 100:
            old_mp = vit["mp"]
            vit["mp"] = min(100, vit["mp"] + BATTLE_REGEN_MP)
            set_temp_vitality(raw, vit)
            changed.append(f"{raw}：MP {old_mp}→{vit['mp']}%（回气·临时）")
    if dirty:
        save_json(NPC_AGENT_FILE, data)
    return "\n".join(changed)


# ---------- 事件日志（供前端/控制台显示） ----------
def format_settle_log(results, user_action=""):
    """把结算结果格式化成人类可读的日志"""
    if not results:
        return ""
    parts = []
    for name, r in results.items():
        hp_d = r["hp"] - r["old_hp"]
        mp_d = r["mp"] - r["old_mp"]
        segs = []
        if hp_d != 0:
            segs.append(f"气血{hp_d:+d}%")
        if mp_d != 0:
            segs.append(f"内力{mp_d:+d}%")
        if not segs:
            continue
        temp_tag = "（临时）" if r.get("temp") else ""
        line = f"❤️‍🩹 {name}{temp_tag}：" + "，".join(segs) + f"（现 HP {r['hp']}%/MP {r['mp']}%）"
        if r.get("event"):
            line += f" ⚠️{r['event']}"
        parts.append(line)
    return "\n".join(parts)


# ==========================================================
# ---------- 独立状态系统（effects）：挂词条给DC和剧情AI ----------
# 设计：条目只存运行时数据（id/层数/剩余回合/来源），
#       名称/描述/dot/回合数/上限全部查 data/effect_config.json。
# 存储：与vitality同轨 —— 玩家player.json / 落盘NPC npc_agents.json /
#       临时NPC内存缓存（战斗结束即消失）。
# 原则：跑不通最多不挂词条，绝不影响主流程。
# ==========================================================
EFFECT_CONFIG_FILE = "data/effect_config.json"

# 临时NPC的effects内存缓存（与_TEMP_VITALITY同生命周期）
_TEMP_EFFECTS = {}


def _load_effect_config():
    """加载状态库配置（带缓存，文件不存在/损坏返回空dict）。
    下划线开头的键（_version/_default_base_rate等元信息）已过滤，
    避免混入状态库id清单注入AI上下文。
    热联动：文件mtime变化自动重载（手改json保存后无需重启）。"""
    global _EFFECT_CONFIG_CACHE, _EFFECT_CONFIG_MTIME
    try:
        mtime = os.path.getmtime(EFFECT_CONFIG_FILE)
    except Exception:
        mtime = None
    try:
        if _EFFECT_CONFIG_CACHE is not None and _EFFECT_CONFIG_MTIME == mtime:
            return _EFFECT_CONFIG_CACHE
    except NameError:
        pass
    raw = load_json(EFFECT_CONFIG_FILE) or {}
    _EFFECT_CONFIG_CACHE = {k: v for k, v in raw.items()
                            if not str(k).startswith("_") and isinstance(v, dict)}
    _EFFECT_CONFIG_MTIME = mtime
    return _EFFECT_CONFIG_CACHE


def reload_effect_config():
    """强制重载状态库配置（mtime热重载下通常无需手动调用，保留兼容）"""
    global _EFFECT_CONFIG_MTIME
    _EFFECT_CONFIG_MTIME = None
    return _load_effect_config()


def _effect_exists(effect_id):
    return effect_id in _load_effect_config()


# ---------- effects 读写（三轨分发，内部函数） ----------

def _get_effects_raw(name, player_name):
    """读取角色effects列表（返回列表引用或None表示不存在该角色）。
    玩家/落盘NPC返回读到的json列表副本+轨道标记；临时NPC返回内存列表。
    返回 (effects_list, track) track: "player"/"npc"/"temp"/None
    """
    if player_name and name == player_name:
        data = load_json(PLAYER_FILE)
        if data:
            return list(data.get("effects") or []), "player"
        return None, None
    # 落盘NPC
    data = load_json(NPC_AGENT_FILE)
    if data and "npc_list" in data:
        for npc in data["npc_list"]:
            if npc.get("name") == name:
                return list(npc.get("effects") or []), "npc"
    # 其余一律视为临时NPC（内存缓存，战斗结束即消失）
    return list(_TEMP_EFFECTS.get(name) or []), "temp"


def _save_effects(name, player_name, effects, track):
    """把effects列表写回对应轨道"""
    if track == "player":
        data = load_json(PLAYER_FILE)
        if data:
            data["effects"] = effects
            save_json(PLAYER_FILE, data)
            return True
    elif track == "npc":
        data = load_json(NPC_AGENT_FILE)
        if data and "npc_list" in data:
            for npc in data["npc_list"]:
                if npc.get("name") == name:
                    npc["effects"] = effects
                    save_json(NPC_AGENT_FILE, data)
                    return True
    elif track == "temp":
        _TEMP_EFFECTS[name] = effects
        return True
    return False


# ---------- 对外四API ----------

def apply_effect(name, effect_id, stacks=1, rounds=None, source="", player_name=None, system=False):
    """上状态：查库校验 → 已有则叠层（不超上限）并刷新回合 → 没有则新建。
    库里无此effect_id则忽略（AI乱编的id静默丢弃）。
    rounds钳制1-5轮；debuff类同角色最多3条（新debuff挤掉最旧一条）。
    system=True：武功特效程序触发（优先级高于AI上报——AI对system条目的重复add直接忽略）。
    返回日志字符串（空串=未挂上）。"""
    cfg = _load_effect_config().get(effect_id)
    if not cfg:
        return ""
    effects, track = _get_effects_raw(name, player_name)
    if track is None:
        return ""
    max_stacks = int(cfg.get("max_stacks", 1) or 1)
    stacks = max(1, min(int(stacks or 1), max_stacks))
    remain = int(rounds) if rounds is not None else int(cfg.get("default_rounds", 3) or 3)
    remain = max(1, min(remain, 5))  # 钳制1-5轮
    entry = None
    for e in effects:
        if e.get("id") == effect_id:
            entry = e
            break
    evicted_log = ""
    if entry:
        # 优先级规则：程序特效挂的词条，AI的重复add不刷新不叠层（主动触发 > AI调tool）
        if not system and entry.get("source") == "system":
            return ""
        # 叠层：层数封顶，回合刷新为本次remain（同名单刷不叠时长）
        old_s = entry.get("stacks", 1)
        entry["stacks"] = max(old_s, stacks)
        entry["remain_rounds"] = remain
        if system:
            entry["source"] = "system"
        else:
            entry.setdefault("source", source)
    else:
        # debuff叠层上限：同角色最多3条debuff，超出挤掉最旧一条
        if str(cfg.get("type", "")) == "debuff":
            cfg_all = _load_effect_config()
            debuff_idx = [i for i, e in enumerate(effects)
                          if str((cfg_all.get(e.get("id")) or {}).get("type", "")) == "debuff"]
            if len(debuff_idx) >= 3:
                _old_i = debuff_idx[0]
                _old = effects.pop(_old_i)
                _old_name = (cfg_all.get(_old.get("id")) or {}).get("name", _old.get("id"))
                evicted_log = f"；旧状态「{_old_name}」被挤下"
        entry = {"id": effect_id, "stacks": stacks, "remain_rounds": remain,
                 "source": "system" if system else source}
        effects.append(entry)
    _save_effects(name, player_name, effects, track)
    n = cfg.get("name", effect_id)
    log = f"【状态触发】{name} 获得「{n}」×{entry['stacks']}（{remain}轮）"
    desc = str(cfg.get("desc", "")).strip()
    if desc:
        log += f"·{desc}"
    return log + evicted_log


def remove_effects_by_prefix(name, prefix, player_name=None):
    """按id前缀批量移除状态（解毒特效用：清掉 poison/cold_poison 等毒类条目）。
    返回日志字符串（空串=本来就没有）。"""
    if not prefix:
        return ""
    effects, track = _get_effects_raw(name, player_name)
    if track is None:
        return ""
    removed = [e for e in effects if str(e.get("id", "")).startswith(prefix)]
    if not removed:
        return ""
    kept = [e for e in effects if not str(e.get("id", "")).startswith(prefix)]
    _save_effects(name, player_name, kept, track)
    cfg_all = _load_effect_config()
    names = "、".join(cfg_all.get(e.get("id"), {}).get("name", e.get("id")) for e in removed)
    return f"【状态】{name} 的「{names}」已被驱散"


def mount_martial_effect_triggers(effect_results, player_name, opponent_name):
    """武功特效程序触发挂状态（优先级最高的入口，先于AI生成剧情）。
    effect_results: dice_system.compute_effect_trigger 的结果列表（含未触发的）。
    只处理状态库中带 martial_trigger 字段的条目，其余忽略。
    返回日志字符串（挂载结果，供注入constraint_text让AI知道状态已挂）。"""
    logs = []
    try:
        cfg_all = _load_effect_config()
        for r in effect_results or []:
            if not isinstance(r, dict) or not r.get("triggered"):
                continue
            etype = str(r.get("effect_type", "")).strip()
            trig = (cfg_all.get(etype) or {}).get("martial_trigger")
            if not trig:
                continue
            op = str(trig.get("op", "add")).strip()
            who = str(trig.get("target", "opponent")).strip()
            target = player_name if who == "self" else opponent_name
            if not target:
                continue
            if op == "add":
                log = apply_effect(target, etype, source="system",
                                   player_name=player_name, system=True)
                # 附加效果（仅支持also带effect_id=同时挂词条；数值直转结算已废弃，
                # 扣多少由AI经vitality_change体现）
                also = trig.get("also") or {}
                also_id = str(also.get("effect_id", "")).strip()
                t2 = player_name if str(also.get("target", "opponent")) == "self" else opponent_name
                if also_id and t2:
                    log2 = apply_effect(t2, also_id, source="system",
                                         player_name=player_name, system=True)
                    if log2:
                        logs.append(log2)
            elif op == "remove_prefix":
                log = remove_effects_by_prefix(target, str(trig.get("prefix", "")),
                                                player_name=player_name)
            else:
                continue
            if log:
                logs.append(log)
    except Exception:
        pass
    return "\n".join(logs)


def mount_npc_effect_triggers(effect_results, player_name, npc_name):
    """NPC特效程序触发挂状态（目标=玩家，与玩家侧mount_martial_effect_triggers对称）。
    effect_results: dice_system.compute_npc_effect_trigger 的结果列表（仅含已触发条目）。
    状态库martial_trigger的self/opponent语义从NPC视角：self=NPC自己，opponent=玩家。
    增量设计：无结果/无玩家名/库里无配置 → 静默返回空串，零影响。"""
    logs = []
    try:
        if not player_name or not npc_name:
            return ""
        cfg_all = _load_effect_config()
        for r in effect_results or []:
            if not isinstance(r, dict) or not r.get("triggered"):
                continue
            etype = str(r.get("effect_type", "")).strip()
            cfg = cfg_all.get(etype) or {}
            trig = cfg.get("martial_trigger")
            if not trig:
                continue
            op = str(trig.get("op", "add")).strip()
            # NPC配置的target(反手招语义)优先，状态库默认值兜底
            who = str(r.get("target", "")).strip() or \
                str(trig.get("target", "opponent")).strip()
            # NPC视角: self=NPC自己, opponent=玩家
            target = npc_name if who == "self" else player_name
            if not target:
                continue
            if op == "add":
                log = apply_effect(target, etype, source="system",
                                   player_name=player_name, system=True)
                # 附加效果（NPC视角: self=NPC, opponent=玩家；数值直转结算已废弃）
                also = trig.get("also") or {}
                also_id = str(also.get("effect_id", "")).strip()
                t2 = npc_name if str(also.get("target", "opponent")) == "self" else player_name
                if also_id and t2:
                    log2 = apply_effect(t2, also_id, source="system",
                                         player_name=player_name, system=True)
                    if log2:
                        logs.append(log2)
            elif op == "remove_prefix":
                log = remove_effects_by_prefix(target, str(trig.get("prefix", "")),
                                                player_name=player_name)
            else:
                continue
            if log:
                logs.append(log)
    except Exception:
        pass
    return "\n".join(logs)


def remove_effect(name, effect_id, player_name=None):
    """下状态（解毒/驱散/清场统一出口）。返回日志字符串（空串=本来就没有）。"""
    effects, track = _get_effects_raw(name, player_name)
    if track is None:
        return ""
    before = len(effects)
    effects = [e for e in effects if e.get("id") != effect_id]
    if len(effects) == before:
        return ""
    _save_effects(name, player_name, effects, track)
    n = _load_effect_config().get(effect_id, {}).get("name", effect_id)
    return f"【状态】{name} 的「{n}」已解除"


def _clear_legacy_poisoned_flag(name, track, player_name):
    """effects列表中已无中毒类条目时，将旧vitality.poisoned联动置False。
    返回True表示实际做了写入（供上层决定是否追加播报日志）。"""
    def _do_clear(vit_getter, vit_setter, *args):
        vit = vit_getter(*args) if args else vit_getter()
        if not vit or not vit.get("poisoned"):
            return False
        new_vit = dict(vit)
        new_vit["poisoned"] = False
        if args:
            ok = vit_setter(*args, new_vit)
        else:
            ok = vit_setter(new_vit)
        return bool(ok) if ok is not None else True
    if track == "player":
        return _do_clear(get_player_vitality, set_player_vitality)
    elif track == "npc":
        return _do_clear(get_npc_vitality, set_npc_vitality, name)
    elif track == "temp":
        return _do_clear(get_temp_vitality, set_temp_vitality, name)
    return False


def tick_effects(name, player_name=None, scene_npc_names=None):
    """每轮结算（V5纯播报制）：到点播报状态警讯 → 剩余回合-1 → 到期移除。
    程序不再做任何数值结算——损血扣蓝的具体数值由AI经vitality_change单写者通道
    在下一轮剧情中体现。已故角色冻结跳过。返回日志字符串（空串=无效果在身/无变化）。
    兼容层：effects列表无中毒类条目时，联动清理旧vitality.poisoned僵尸标记。"""
    effects, track = _get_effects_raw(name, player_name)
    if track is None:
        return ""

    # ---- 出口1：effects本来就为空 → 直接尝试清旧poisoned残留，然后返回 ----
    if not effects:
        cleared = _clear_legacy_poisoned_flag(name, track, player_name)
        if cleared:
            return f"☠️ {name} 状态结算：余毒未清标记已清除（毒素自然代谢消散）"
        return ""

    cfg_all = _load_effect_config()
    # 亡故冻结
    if track == "player":
        vit = get_player_vitality()
    elif track == "npc":
        vit = get_npc_vitality(name)
    else:
        vit = get_temp_vitality(name)
    if vit and vit.get("hp") == -1:
        return ""

    changed = False
    kept = []
    active_parts = []
    expired_parts = []
    for e in effects:
        cfg = cfg_all.get(e.get("id"))
        if not cfg:
            changed = True  # 库里已删的孤儿条目直接清除
            continue
        stacks = int(e.get("stacks", 1) or 1)
        # 持续性状态到点警讯（仅播报，无数值——扣多少由AI剧情决定）
        if str(cfg.get("type", "")) == "debuff":
            active_parts.append(f"{cfg.get('name', e.get('id'))}×{stacks}发作")
        remain = int(e.get("remain_rounds", 1) or 1) - 1
        if remain > 0:
            e["remain_rounds"] = remain
            kept.append(e)
            changed = True  # 回合递减也需落盘
        else:
            changed = True
            expired_parts.append(f"{cfg.get('name', e.get('id'))}×{stacks}效果结束")
    _save_effects(name, player_name, kept, track)
    parts = []
    for e in kept:
        cfg = cfg_all.get(e.get("id"), {})
        parts.append(f"{cfg.get('name', e.get('id'))}×{e.get('stacks', 1)}·剩{e.get('remain_rounds')}轮")

    # ---- 出口2：正常结算后，若kept中已无任何中毒类id → 联动清旧poisoned残留 ----
    has_any_poison_effect = any(str(e.get("id", "")).startswith("poison") for e in kept)
    cleared_log = ""
    if not has_any_poison_effect:
        if _clear_legacy_poisoned_flag(name, track, player_name):
            cleared_log = "余毒未清标记已清除"

    if not parts and not expired_parts and not active_parts and not cleared_log:
        return ""
    tag = "（临时）" if track == "temp" else ""
    segments = []
    if parts:
        segments.append("，".join(parts))
    if active_parts:
        segments.append("，".join(active_parts))
    if expired_parts:
        segments.append("，".join(expired_parts))
    if cleared_log:
        segments.append(cleared_log)
    return f"☠️ {name}{tag} 状态结算：" + "；".join(segments)


def render_effects_line(name, player_name=None):
    """渲染角色身上的状态文本行（给DC裁判和剧情AI注入用）。
    兼容旧poisoned布尔：读时视作通用中毒条目（不改存档）。
    返回如 "【化功散之毒×1·剩3轮·内力絮乱】"，无状态返回空串。"""
    effects, track = _get_effects_raw(name, player_name)
    if track is None:
        return ""
    cfg_all = _load_effect_config()
    parts = []
    for e in effects:
        cfg = cfg_all.get(e.get("id"))
        if not cfg or not cfg.get("visible_to_ai", True):
            continue
        seg = cfg.get("name", e.get("id"))
        stacks = int(e.get("stacks", 1) or 1)
        if stacks > 1:
            seg += f"×{stacks}"
        remain = e.get("remain_rounds")
        if remain is not None:
            seg += f"·剩{remain}轮"
        desc = cfg.get("desc", "")
        if desc:
            seg += f"·{desc}"
        hint = cfg.get("dc_hint", "")
        if hint:
            seg += f"（{hint}）"
        parts.append(seg)
    # 旧poisoned布尔读兼容（渲染层面视作中毒条目，不写回存档）
    if not any(e.get("id", "").startswith("poison") for e in effects):
        if track == "player":
            vit = get_player_vitality()
        elif track == "npc":
            vit = get_npc_vitality(name)
        else:
            vit = get_temp_vitality(name)
        if vit and vit.get("poisoned"):
            parts.append("中毒·余毒未清")
    if not parts:
        return ""
    return "【" + "】【".join(parts) + "】"


def clear_temp_effects(name=None):
    """清除临时NPC的状态（战斗结束清场用，与clear_temp_vitality对齐）"""
    if name is None:
        _TEMP_EFFECTS.clear()
    else:
        _TEMP_EFFECTS.pop(name, None)


# ---------- 状态上报解析（tool字段，两条管线共用） ----------


def parse_effect_tool_calls(tool_calls):
    """从tool_calls中提取effect_update列表（兼容battle_settle_vitality/update_game_state）。
    返回 [effect_update条目]，无有效数据返回空列表。"""
    updates = []
    if not tool_calls:
        return updates
    for tc in tool_calls:
        try:
            fname = getattr(getattr(tc, "function", None), "name", "") or ""
            if fname not in ("battle_settle_vitality", "update_game_state"):
                continue
            raw_args = tc.function.arguments
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            _list = args.get("effect_update", [])
            if isinstance(_list, list):
                updates.extend([u for u in _list if isinstance(u, dict)])
        except Exception:
            continue
    return updates


def apply_effect_updates(updates, player_name=None, self_name=None, opponent_name=None):
    """执行一批effect_update上报（add/remove分发）。
    target支持相对标记"self"/"opponent"（正则兜底产出的格式）：
      有self_name/opponent_name时翻译成真实角色名（self=叙述主角视角，
      battle管线下传入者视角=玩家）；无映射时该条静默跳过。
    返回日志字符串（空串=无变化）。任何条目异常单独跳过，不阻塞其他。"""
    if not updates:
        return ""
    logs = []
    for u in updates:
        try:
            op = str(u.get("op", "")).strip()
            target = str(u.get("target", "")).strip()
            effect_id = str(u.get("effect_id", "")).strip()
            if not target or not effect_id:
                continue
            _t_low = target.lower()
            if target in ("自己", "自身") or _t_low in ("self", "player"):
                if not self_name:
                    continue
                target = self_name
            elif target in ("对手", "敌方") or _t_low in ("opponent", "npc"):
                if not opponent_name:
                    continue
                target = opponent_name
            if op == "add":
                log = apply_effect(
                    target, effect_id,
                    stacks=u.get("stacks", 1),
                    rounds=u.get("rounds"),
                    source=str(u.get("source", "") or ""),
                    player_name=player_name,
                )
            elif op == "remove":
                log = remove_effect(target, effect_id, player_name=player_name)
            else:
                continue
            if log:
                logs.append(log)
        except Exception:
            continue
    return "\n".join(logs)


# ---------- 状态上报解析（正则兜底：AI工具调用失败时从正文【状态】标记行解析） ----------

_EFFECT_LINE_RE = None


def parse_effect_regex(plot_text, known_names=None):
    """从AI正文中的状态标记行解析effect_update兜底列表。

    识别行格式（每行一条，op与target可省略，默认add/opponent）：
        【状态·add·对手·poison·2轮】或【状态·挂·对手·poison】
        【状态·remove·自己·pursuit】/【状态·下·pursuit】
    字段顺序不敏感：add/remove/挂/下→op；自己/对手/self/opponent→target；
    其余token→effect_id（须在状态库白名单内，乱编的静默丢弃）；
    纯数字+"轮"→rounds。

    Args:
        plot_text: AI生成的剧情正文
        known_names: 额外的角色名→（player/npc/temp）判定提示，暂未使用

    Returns:
        [effect_update条目dict]，无有效条目返回空列表。
    """
    global _EFFECT_LINE_RE
    import re as _re
    if _EFFECT_LINE_RE is None:
        _EFFECT_LINE_RE = _re.compile(r"【\s*状态((?:·[^】\n]{1,24})+)】")
    if not plot_text:
        return []
    cfg_all = _load_effect_config()
    updates = []
    for m in _EFFECT_LINE_RE.finditer(str(plot_text)):
        tokens = [t.strip() for t in m.group(1).split("·") if t.strip()]
        if not tokens:
            continue
        op, target, effect_id, rounds = "add", "opponent", None, None
        for t in tokens:
            low = t.lower()
            if low in ("add", "挂", "上", "挂载"):
                op = "add"
            elif low in ("remove", "下", "解除", "移除"):
                op = "remove"
            elif t in ("自己", "自身") or low in ("self", "player"):
                target = "self"
            elif t in ("对手", "敌方") or low in ("opponent", "npc"):
                target = "opponent"
            elif t.endswith("轮") and t[:-1].isdigit():
                rounds = int(t[:-1])
            elif t in cfg_all:
                effect_id = t
            else:
                # 中文名→id反查（白名单）
                for eid, cfg in cfg_all.items():
                    if cfg.get("name") == t:
                        effect_id = eid
                        break
        if not effect_id:
            continue
        updates.append({"op": op, "target": target, "effect_id": effect_id})
        if op == "add" and rounds:
            updates[-1]["rounds"] = rounds
    return updates


def render_effects_brief(player_name, scene_npc_names=None, max_npcs=8):
    """渲染多角色状态简报（拼进气血面板/DC上下文用）。
    返回各角色状态行的拼接文本，无任何状态返回空串。"""
    scene_npc_names = scene_npc_names or []
    parts = []
    if player_name:
        line = render_effects_line(player_name, player_name)
        if line:
            parts.append(f"・{player_name} {line}")
    # NPC去重（保持顺序）
    seen = []
    for n in scene_npc_names:
        if n and n != player_name and n not in seen:
            seen.append(n)
    for n in seen[:max_npcs]:
        line = render_effects_line(n, player_name)
        if line:
            parts.append(f"・{n} {line}")
    return "\n".join(parts)
