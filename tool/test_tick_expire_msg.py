# -*- coding: utf-8 -*-
"""测试：tick_effects 到期消退讯息（含纯debuff无dot场景）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vitality_system as vs

P = "测试玩家甲"
N1 = "测试临时NPC乙"   # dot类（外伤，默认2轮）
N2 = "测试临时NPC丙"   # 1轮纯debuff（震慑，无dot）

def show(tag, log):
    print(f"[{tag}] {'(空)' if not log else log}")
    return log

# 挂载：外伤2轮 + 震慑1轮（临时NPC走内存缓存）
print("挂载:", vs.apply_effect(N1, "external_wound", source="system", player_name=P, system=True))
print("挂载:", vs.apply_effect(N2, "shock", source="system", player_name=P, system=True))

print("\n===== 第1轮 tick =====")
l1 = show(N1, vs.tick_effects(N1, player_name=P, scene_npc_names=[N1]))
l2 = show(N2, vs.tick_effects(N2, player_name=P, scene_npc_names=[N2]))

# 断言
assert "剩1轮" in l1, "外伤第1轮应显示剩1轮"
assert "效果结束" in l2, "震慑1轮状态第1轮就应结束并给出讯息"

print("\n===== 第2轮 tick（外伤到期）=====")
l1b = show(N1, vs.tick_effects(N1, player_name=P, scene_npc_names=[N1]))
assert "效果结束" in l1b, "外伤到期应给出结束讯息"

print("\n===== 第3轮 tick（无状态应返回空）=====")
l1c = show(N1, vs.tick_effects(N1, player_name=P, scene_npc_names=[N1]))
assert l1c == "", "无状态应返回空串"

# 清场
vs.clear_temp_effects()
print("\n✅ 全部断言通过：dot到期/纯debuff到期均有结束讯息，无状态返回空")
