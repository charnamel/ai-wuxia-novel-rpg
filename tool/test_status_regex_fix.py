# -*- coding: utf-8 -*-
"""正则兜底防误伤验证（方案A+B）：泛化词删除 + 方向过滤 + V6钳制
运行：python tool/test_status_regex_fix.py
注意：仅验证 parse_and_update_npc_state 的状态判定段，不真正跑主循环。
"""
import os, sys, re, io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")

# ---------- 模拟 parse_and_update_npc_state 的核心判定段（与 main.py 保持同步的逻辑副本） ----------
severity = {"normal": 0, "light_injured": 1, "poisoned": 2, "heavy_injured": 3, "dying": 4, "deceased": 5}
status_rules = [
    ("normal", ["伤势痊愈", "恢复如初", "已然痊愈", "毒已解", "伤势大好", "身体恢复", "伤愈"]),
    ("deceased", ["身亡", "毙命", "当场死去", "气绝身亡", "不治身亡", "已死", "死去", "丧命", "亡故", "咽气", "断了气", "没了气息", "气绝", "力竭而亡", "战死", "香消玉殒", "当场毙命", "再无声息"]),
    ("dying", ["性命垂危", "奄奄一息", "濒死", "只剩一口气", "危在旦夕"]),
    ("heavy_injured", ["身受重伤", "重伤", "伤势不轻", "遍体鳞伤"]),
    ("light_injured", ["受了轻伤", "轻伤", "擦破", "划伤", "皮肉伤"]),
    ("poisoned", ["身中剧毒", "中毒", "毒发", "中了毒"])
]
deny_words = ["听说", "听闻", "传言", "据说", "仿佛", "好似", "以为", "传闻", "回忆", "梦中", "如果", "倘若"]

def simulate(npc_list, reply_text, tool_updated=frozenset()):
    """返回 {name: (status, kw)}"""
    npc_final_status = {}
    for status, keywords in status_rules:
        for kw in keywords:
            for npc in npc_list:
                name = npc["name"]
                if name in tool_updated:
                    continue
                if name not in reply_text:
                    continue
                pattern = f"{name}[^。！？]*?{kw}"
                match = re.search(pattern, reply_text)
                if not match:
                    continue
                sentence = match.group(0)
                if any(w in sentence for w in deny_words):
                    continue
                gap_text = sentence[len(name):sentence.find(kw, len(name))] if kw in sentence[len(name):] else ""
                if any(other["name"] in gap_text for other in npc_list if other["name"] != name):
                    continue
                current_sev = severity.get(status, 0)
                if name not in npc_final_status or current_sev > severity.get(npc_final_status[name][0], 0):
                    npc_final_status[name] = (status, kw)
    return npc_final_status

def mk(*names):
    return [{"name": n, "vitality": {"hp": 100, "mp": 100, "poisoned": False},
             "body_status": "normal", "body_status_desc": ""} for n in names]

# ---------- 测试 ----------
print("=" * 60)
print("测试1：方向过滤（本次主修）")
print("=" * 60)
npcs = mk("骆冰", "赫连铁")
# 已知限制：铁鹞堂帮众不是注册NPC名 → gap里没有已知NPC名 → 方向过滤挡不住。
# 此场景靠V6钳制兜底（最坏压到30，不会更糟），且下一轮结算/自然恢复自动修正
r = simulate(npcs, "骆冰望着重伤的铁鹞堂帮众，冷笑一声。")
check("骆冰望着(未注册NPC)重伤 → 已知限制：仍会标（靠V6钳制兜底）", r.get("骆冰", ("",))[0] == "heavy_injured", f"got={r.get('骆冰')}")
r = simulate(npcs, "骆冰望着赫连铁身受重伤，冷笑一声。")
check("骆冰望着赫连铁重伤 → 骆冰不标（gap夹了赫连铁）", "骆冰" not in r, f"got={r.get('骆冰')}")
check("赫连铁重伤 → 赫连铁标重伤", r.get("赫连铁", ("",))[0] == "heavy_injured", f"got={r.get('赫连铁')}")

print("\n" + "=" * 60)
print("测试2：泛化词删除（方案A）")
print("=" * 60)
npcs = mk("李四")
r = simulate(npcs, "李四心碎了，茶碗也碎了，气得他直想呕血。")
check("心碎/茶碗碎/呕血 不再触发重伤", "李四" not in r, f"got={r.get('李四')}")
r = simulate(npcs, "李四身受重伤，退了两步。")
check("真正的身受重伤 仍正常命中", r.get("李四", ("",))[0] == "heavy_injured", f"got={r.get('李四')}")

print("\n" + "=" * 60)
print("测试3：正常命中不受影响（回归）")
print("=" * 60)
npcs = mk("张召重")
r = simulate(npcs, "张召重重伤倒地，口吐鲜血不止。")
check("张召重重伤 → heavy_injured", r.get("张召重", ("",))[0] == "heavy_injured", f"got={r.get('张召重')}")
r = simulate(npcs, "张召重已然毙命，气绝身亡。")
check("毙命 → deceased", r.get("张召重", ("",))[0] == "deceased", f"got={r.get('张召重')}")
r = simulate(npcs, "张召重伤势痊愈。")
check("伤势痊愈 → normal", r.get("张召重", ("",))[0] == "normal", f"got={r.get('张召重')}")
r = simulate(npcs, "张召重中了毒，脸色发黑。")
check("中了毒 → poisoned", r.get("张召重", ("",))[0] == "poisoned", f"got={r.get('张召重')}")

print("\n" + "=" * 60)
print("测试4：deny_words 回归")
print("=" * 60)
r = simulate(mk("王五"), "王五听闻李四重伤，传闻而已。")
check("听说/传闻 → 不标", "王五" not in r, f"got={r.get('王五')}")

print("\n" + "=" * 60)
print("测试5：工具已更新的NPC跳过（回归）")
print("=" * 60)
r = simulate(mk("赵六"), "赵六身受重伤。", tool_updated=frozenset({"赵六"}))
check("工具更新过的NPC → 正则不碰", "赵六" not in r, f"got={r.get('赵六')}")

print("\n" + "=" * 60)
print("测试6：V6单向钳制逻辑（独立验证分支条件）")
print("=" * 60)
def clamp(status, hp):
    """与 main.py V6 相同的分支逻辑"""
    if status == "deceased": return -1
    if status == "dying": return 0
    if status == "heavy_injured": return min(hp, 30)
    if status == "light_injured": return min(hp, 70)
    return hp  # normal/poisoned 不动HP
check("重伤+HP100 → 30", clamp("heavy_injured", 100) == 30)
check("重伤+HP20 → 20（不抬）", clamp("heavy_injured", 20) == 20)
check("轻伤+HP95 → 70", clamp("light_injured", 95) == 70)
check("轻伤+HP50 → 50（不抬）", clamp("light_injured", 50) == 50)
check("痊愈+HP30 → 30（不送血）", clamp("normal", 30) == 30)
check("濒死+HP80 → 0", clamp("dying", 80) == 0)
check("已故+HP50 → -1", clamp("deceased", 50) == -1)

print("\n" + "=" * 60)
print(f"总结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
