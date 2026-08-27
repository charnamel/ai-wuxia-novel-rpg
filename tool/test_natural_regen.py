# -*- coding: utf-8 -*-
"""测试：周期性自然恢复（每5轮 气血+10 内力+20）
验证：未到周期零开销 / 已故冻结 / 濒死HP不动 / 满血不写盘 / 伤势自动降级
"""
import sys, os, json, shutil, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 备份现场
BK = "tool/_regen_backup"
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
    for n in d["npc_list"][:3]:
        print(f"  {n['name']}: HP={n.get('vitality',{}).get('hp')} body={n.get('body_status')}")

try:
    # 构造测试状态：玩家 HP55/MP40
    vs.set_player_vitality({"hp": 55, "mp": 40, "poisoned": False})
    d = json.load(open("data/npc_agents.json", encoding="utf-8"))
    names = [n["name"] for n in d["npc_list"][:3]]
    # NPC1: 重伤可恢复; NPC2: 濒死(HP0)不恢复; NPC3: 已故冻结
    d["npc_list"][0]["vitality"] = {"hp": 35, "mp": 50, "poisoned": False}
    d["npc_list"][1]["vitality"] = {"hp": 0, "mp": 20, "poisoned": False}
    d["npc_list"][2]["vitality"] = {"hp": -1, "mp": 0, "poisoned": False}
    d["npc_list"][2]["body_status"] = "deceased"
    json.dump(d, open("data/npc_agents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("== 初始 ==")
    show("init")

    print("\n== 第3轮（未到周期，应无变化） ==")
    t0 = time.time()
    r = vs.natural_regen(3)
    print(f"返回: {r!r} | 耗时: {(time.time()-t0)*1000:.2f}ms")
    show("round3")

    print("\n== 第5轮（触发恢复） ==")
    t0 = time.time()
    r = vs.natural_regen(5)
    print(f"耗时: {(time.time()-t0)*1000:.2f}ms")
    print(r)
    show("round5")

    print("\n== 第10轮（再次触发，重伤35→45→55，濒死仍0，已故仍-1） ==")
    r = vs.natural_regen(10)
    print(r)
    show("round10")
finally:
    # 还原现场
    shutil.copy(BK + "/player.json", "data/player.json")
    shutil.copy(BK + "/npc_agents.json", "data/npc_agents.json")
    shutil.rmtree(BK)
    print("\n[现场已还原]")
