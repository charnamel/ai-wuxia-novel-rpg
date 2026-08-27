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


# ---------- 正则兜底 ----------
# 【体力结算】张三：气血-5，内力+0（兼容数值后带括号注释，如：气血-2（被掌风扫中））
_V_NUM = r"[+-]?\d+(?:[（(][^）)]*[）)])?"
VITALITY_REGEX = re.compile(
    r"【体力结算】\s*([^：:，,\s（(]+)\s*[：:]\s*气血\s*(" + _V_NUM + r")\s*[,，]\s*内力\s*(" + _V_NUM + r")"
)
# 续行：前缀行后紧跟的不带前缀行（AI常把第二个人的结算直接换行写在后面）
VITALITY_LINE_REGEX = re.compile(
    r"^\s*([^：:，,\s（(]+)\s*[：:]\s*气血\s*(" + _V_NUM + r")\s*[,，]\s*内力\s*(" + _V_NUM + r")\s*$"
)


def _to_int(raw):
    """'−2（注释）' → -2：截取数值部分转int，失败返回None"""
    m = re.match(r"^\s*([+-]?\d+)", raw or "")
    return int(m.group(1)) if m else None


def parse_vitality_regex(reply_text):
    """解析正文中的【体力结算】行，返回 [{name, hp_pct, mp_pct}]
    支持两种形态：
    1. 带【体力结算】前缀的行
    2. 紧跟在前缀行之后的续行（如 AI 常见的多人结算连写）
    """
    results = []
    if not reply_text:
        return results
    lines = reply_text.splitlines()
    prev_was_settle = False
    for line in lines:
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
    # 濒死锁血：不会再降到 0 以下，但也不允许一口气从濒死直接回复到高位
    if hp < 0:
        hp = 0
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

    if hp == 0 and old_hp > 0:
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
