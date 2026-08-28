# -*- coding: utf-8 -*-
"""测试：对战回合回气 battle_regen_mp（MP+3%）
验证：玩家回气 / 落盘NPC回气 / 临时NPC回气 / 已故冻结 / 满血不写盘 / daily不触发（main侧逻辑）
"""
import sys, os, json, shutil, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BK = "tool/_regen_backup2"
if os.path.exists(BK):
    shutil.rmtree(BK)
os.makedirs(BK)
shutil.copy("data/player.json", BK)
shutil.copy("data/npc_agents.json", BK)

import vitality_system as vs

def show(tag):
    pv = vs.get_player_vitality()
    print(f"[{tag}] 玩家 HP={pv['hp']} MP={pv['mp']}")
    d = json.load(open("data/npc_agents.json", encoding="utf-8"))
    for n in d["npc_list"][:2]:
        print(f"  {n['name']}: HP={n.get('vitality',{}).get('hp')} MP={n.get('vitality',{}).get('mp')} body={n.get('body_status')}")
    t = vs.get_temp_vitality("路人甲")
    print(f"  路人甲(临时): HP={t['hp']} MP={t['mp']}")

try:
    # 构造：玩家 MP70；NPC1 MP40；NPC2 已故；临时NPC路人甲 MP30
    vs.set_player_vitality({"hp": 80, "mp": 70, "poisoned": False})
    d = json.load(open("data/npc_agents.json", encoding="utf-8"))
    d["npc_list"][0]["vitality"] = {"hp": 60, "mp": 40, "poisoned": False}
    d["npc_list"][1]["vitality"] = {"hp": -1, "mp": 0, "poisoned": False}
    d["npc_list"][1]["body_status"] = "deceased"
    json.dump(d, open("data/npc_agents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    vs.set_temp_vitality("路人甲", {"hp": 50, "mp": 30, "poisoned": False})

    names = [d["npc_list"][0]["name"], d["npc_list"][1]["name"], "路人甲"]
    print("== 初始 ==")
    show("init")

    print("\n== 回合1回气 ==")
    t0 = time.time()
    log = vs.battle_regen_mp("李沉舟", names)
    print(f"耗时: {(time.time()-t0)*1000:.1f}ms")
    print(log)
    show("r1")

    print("\n== 连续4次（模拟5回合战斗，满血后不再写） ==")
    for i in range(4):
        log = vs.battle_regen_mp("李沉舟", names)
    show("r5")
finally:
    shutil.copy(BK + "/player.json", "data/player.json")
    shutil.copy(BK + "/npc_agents.json", "data/npc_agents.json")
    shutil.rmtree(BK)
    print("\n[现场已还原]")
