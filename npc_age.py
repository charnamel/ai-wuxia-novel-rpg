# -*- coding: utf-8 -*-
"""npc_age.py — NPC 年龄阶段（age_stage）
============================================================
【年龄】= 当前剧情年份(player.novel_node) − 出生年(npc["year"])
【阶段】未出生(<0) / 幼年(0-7) / 少年(8-16) / 青壮年(17-60) / 老年(61-75) / 暮年(76+)
【用途】注入主剧情活跃NPC信息 + web 显示；未来用于动态 NPC 基础DC
        （境界修正：幼年-2 · 少年-1 · 青壮年0 · 老年-1 · 暮年-2，到最低档就停最低档）
【设计】使用驱动（lazy）：用到某NPC时才现算；有变化才原子写盘；已故不更新；>120不写。
"""
import os
import re
import json

from file_utils import ensure_dir

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NPC_AGENT_FILE = os.path.join(BASE_DIR, "data", "npc_agents.json")

AGE_MAX = 120

# 阶段上界（闭）+ 名称 + 未来境界修正
AGE_STAGE_TABLE = [
    (7,  "幼年",  -2),
    (16, "少年",  -1),
    (60, "青壮年", 0),
    (75, "老年",  -1),
]
STAGE_MATURE = "暮年"          # >75
STAGE_UNBORN = "未出生"
# 未来 DC 联动的境界修正（到最低档就停最低档，钳制由 DC 侧处理）
STAGE_REALM_DELTA = {
    STAGE_UNBORN: None,
    "幼年": -2, "少年": -1, "青壮年": 0, "老年": -1, "暮年": -2,
}


def get_current_year(novel_node):
    """从 novel_node 提取当前剧情年份（1500-2049）。
    优先取「N年+季节」，避免误取剧情里的其它年份。无返回 0。"""
    if not novel_node:
        return 0
    s = str(novel_node)
    m = re.search(r"(\d{1,4})\s*年[之]?\s*[春夏秋冬]", s)
    if m:
        y = int(m.group(1))
        if 1500 <= y <= 2049:
            return y
    for m in re.finditer(r"(\d{1,4})年", s):
        y = int(m.group(1))
        if 1500 <= y <= 2049:
            return y
    return 0


def calc_age_stage(age):
    """年龄 → 阶段名；age<0 → 未出生；>120 / 非法 → None。"""
    try:
        age = int(age)
    except (TypeError, ValueError):
        return None
    if age < 0:
        return STAGE_UNBORN
    if age > AGE_MAX:
        return None
    for up, name, _ in AGE_STAGE_TABLE:
        if age <= up:
            return name
    return STAGE_MATURE


def calc_npc_age(npc, cur_year):
    """返回 (age, stage)。已故 / 无出生年 / 无当前年 → (None, None)。"""
    if not isinstance(npc, dict):
        return None, None
    if npc.get("body_status") == "deceased":
        return None, None
    try:
        cur_year = int(cur_year or 0)
    except (TypeError, ValueError):
        cur_year = 0
    if not cur_year:
        return None, None
    birth = npc.get("year", 0)
    if not birth:
        return None, None
    try:
        birth = int(birth)
    except (TypeError, ValueError):
        return None, None
    age = cur_year - birth
    return age, calc_age_stage(age)


def age_stage_suffix(npc, cur_year):
    """注入/显示片段：'年龄:45岁(青壮年)' / '年龄:未出生' / '年龄:120岁(长生不老，返老还童)'；无则 ''。
    锁定（age_stage_locked）时用 npc['age_stage'] 的文字，不再自动推断。"""
    if not isinstance(npc, dict):
        return ""
    locked = bool(npc.get("age_stage_locked"))
    stage = npc.get("age_stage")
    if not locked and not stage and cur_year:
        _, stage = calc_npc_age(npc, cur_year)
    if not stage:
        return ""
    if not locked and stage == STAGE_UNBORN:
        return "年龄:未出生"
    # 年龄数字：按当前年份现算（锁定不影响年龄数字）
    if cur_year and npc.get("year"):
        try:
            age = int(cur_year) - int(npc["year"])
            if 0 <= age <= AGE_MAX:
                return f"年龄:{age}岁({stage})"
        except (TypeError, ValueError):
            pass
    return f"年龄:({stage})"


def _atomic_save(path, data):
    """临时文件 + os.replace 原子写，避免半途损坏。"""
    ensure_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ===== DC 软联动：年龄阶段 → base_dc 建议区间（并入 base_dc，不新增分量）=====
# 值含义：在「境界对应 base_dc」基础上调低的幅度（强建议，AI 可结合剧情微调）
STAGE_DC_HINT = {
    "幼年": "调低 3~6",
    "少年": "调低 1~3",
    "老年": "调低 1~3",
    "暮年": "调低 3~6",
}


def age_stage_dc_hint(npc):
    """DC 软建议串：'年龄阶段:暮年（base_dc 在境界对应值基础上调低 3~6）'。
    青壮年/锁定 → '（base_dc 不调整）'；未出生/无 → ''（DC 路径忽略）。"""
    if not isinstance(npc, dict):
        return ""
    stage = str(npc.get("age_stage") or "").strip()
    if not stage or stage == STAGE_UNBORN:
        return ""
    if npc.get("age_stage_locked") or stage == "青壮年":
        return f"年龄阶段:{stage}（base_dc 不调整）"
    hint = STAGE_DC_HINT.get(stage)
    if not hint:
        return ""
    return f"年龄阶段:{stage}（base_dc 在境界对应值基础上{hint}）"


def refresh_npc_age_stages(npc_data, cur_year, write=True, path=None):
    """重算全部可算NPC的 age_stage；有变化则（默认）原子写回。返回改动数。
    已故 / 无出生年 / >120 的NPC 不动；已锁定（age_stage_locked）的NPC 跳过。"""
    if not isinstance(npc_data, dict):
        return 0
    changed = 0
    for npc in npc_data.get("npc_list", []):
        if not isinstance(npc, dict):
            continue
        if npc.get("age_stage_locked"):
            continue  # 锁死年龄阶段：自动推算失效
        _, stage = calc_npc_age(npc, cur_year)
        if stage is None:
            continue
        if npc.get("age_stage") != stage:
            npc["age_stage"] = stage
            changed += 1
    if changed and write:
        try:
            _atomic_save(path or NPC_AGENT_FILE, npc_data)
        except Exception as e:
            print(f"[npc_age] age_stage 写盘失败: {e}")
    return changed
