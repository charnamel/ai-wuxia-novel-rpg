# -*- coding: utf-8 -*-
"""测试：DC裁判HP/MP可见性（①修正）
验证：
1. _vit_text_for_npc：档案vitality / 临时缓存 / 已故 / 内力枯竭 / 数据缺失
2. build_active_npcs_brief 行内带HP/MP
3. build_target_npc_line 行内带HP/MP
4. build_v4_dc_judge_prompt 含【玩家当前状态】HP/MP
"""
import sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BK = "tool/_dcvit_backup"
if os.path.exists(BK):
    shutil.rmtree(BK)
os.makedirs(BK)
shutil.copy("data/player.json", BK)
shutil.copy("data/npc_agents.json", BK)

import vitality_system as vs
import dice_system as ds


def check(tag, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} | {tag} {detail}")
    return bool(cond)


try:
    ok = True

    # ===== 1. _vit_text_for_npc =====
    ok &= check("档案vitality：HP 45%/MP 20%",
                ds._vit_text_for_npc({"name": "胡一刀", "vitality": {"hp": 45, "mp": 20}}) == "HP 45%/MP 20%")
    ok &= check("MP=0 标注内力枯竭",
                "内力枯竭" in ds._vit_text_for_npc({"name": "胡一刀", "vitality": {"hp": 50, "mp": 0}}))
    ok &= check("HP=0 标注濒死锁血",
                "濒死锁血" in ds._vit_text_for_npc({"name": "胡一刀", "vitality": {"hp": 0, "mp": 30}}))
    ok &= check("HP=-1 显示已故",
                ds._vit_text_for_npc({"name": "胡一刀", "vitality": {"hp": -1, "mp": 0}}) == "HP 已故")

    # 临时NPC（无vitality字段，走内存缓存）
    vs.set_temp_vitality("路人乙", {"hp": 60, "mp": 10, "poisoned": False})
    ok &= check("临时NPC走缓存：HP 60%/MP 10%",
                ds._vit_text_for_npc({"name": "路人乙"}) == "HP 60%/MP 10%")
    # 完全未知NPC（缓存默认满值）→ 也应有HP/MP（100/100）
    _t = ds._vit_text_for_npc({"name": "无名客"})
    ok &= check("无档案NPC默认满值", _t == "HP 100%/MP 100%", _t)

    # ===== 2. build_active_npcs_brief =====
    data = {"npc_list": [
        {"name": "胡一刀", "identity": "镖头", "body_status": "heavy_injured",
         "martial_skills": [{"skill_name": "八卦刀", "skill_level": "登堂入室"}],
         "vitality": {"hp": 25, "mp": 0, "poisoned": False}},
    ]}
    brief = ds.build_active_npcs_brief(data, "攻击胡一刀", "胡一刀挥刀迎战")
    ok &= check("brief含HP 25%", "HP 25%" in brief, brief)
    ok &= check("brief含内力枯竭标注", "内力枯竭" in brief)

    # ===== 3. build_target_npc_line =====
    line = ds.build_target_npc_line({"name": "苗人凤", "identity": "打遍天下无敌手",
                                     "level": "登峰造极",
                                     "martial_skills": [{"skill_name": "苗家剑", "skill_level": "登峰造极"}],
                                     "vitality": {"hp": 80, "mp": 40, "poisoned": False}})
    ok &= check("对手锚定行含HP 80%/MP 40%", "HP 80%/MP 40%" in line, line)

    # ===== 4. DC prompt 含玩家当前状态 =====
    vs.set_player_vitality({"hp": 30, "mp": 0, "poisoned": False})
    sys_p, user_p = ds.build_v4_dc_judge_prompt(
        "荒庙中", "运起内力出掌", "混元掌", "略有小成", 2,
        ["混元掌：略有小成"], "略有小成", "胡一刀（镖头）：八卦刀·登堂入室 [重伤] HP 25%/MP 0%",
        battle_mode=True, target_npc_text=line)
    ok &= check("user_prompt含【玩家当前状态】", "【玩家当前状态】" in user_p)
    ok &= check("玩家HP 30%可见", "HP 30%" in user_p)
    ok &= check("玩家MP=0标注", "内力枯竭" in user_p)
    ok &= check("sys_prompt含HP/MP规则", "双方当前HP/MP见档案行" in sys_p)

    # 满血状态不误标
    vs.set_player_vitality({"hp": 100, "mp": 100, "poisoned": False})
    _, user_p2 = ds.build_v4_dc_judge_prompt(
        "客栈", "喝酒", "overall", "略有小成", 0, [], "略有小成")
    ok &= check("满血无警示标注", "内力枯竭" not in user_p2 and "濒死" not in user_p2)

    print("\n" + ("✅ 全部通过" if ok else "❌ 存在失败项"))
finally:
    shutil.copy(BK + "/player.json", "data/player.json")
    shutil.copy(BK + "/npc_agents.json", "data/npc_agents.json")
    shutil.rmtree(BK)
    print("[现场已还原]")
    sys.exit(0 if ok else 1)
