# -*- coding: utf-8 -*-
"""主动检索模块修复验证（纯函数，不调API）"""
import threading
from active_cloud_retrieval import (
    _build_thinking_prompt,
    _repair_truncated_json,
    _parse_tool_call,
    _deduplicate,
    _search_one_group,
    _parse_npc_lines,
    _parse_l4_lines,
    merge_with_passive,
)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


class _MockFunc:
    def __init__(self, args):
        self.arguments = args


class _MockToolCall:
    def __init__(self, args):
        self.function = _MockFunc(args)


print("=" * 60)
print("③ 花括号注入修复：_build_thinking_prompt")
print("=" * 60)
try:
    p = _build_thinking_prompt(
        recent_context="剧情里出现了 {骰子} 标记和 {1d20}",
        player_input="我使用{独孤九剑}攻击「破剑式」}",
        active_npcs=["胡斐"],
    )
    check("含花括号输入不抛异常", True)
    check("占位符被替换", "{player_input}" not in p and "{recent_context}" not in p)
    check("花括号原文保留", "{独孤九剑}" in p)
except (KeyError, IndexError) as e:
    check("含花括号输入不抛异常", False, f"抛出 {type(e).__name__}: {e}")

print()
print("=" * 60)
print("④ JSON截断修复：_repair_truncated_json")
print("=" * 60)
# 场景1：截断在字符串中间（最常见）
r1 = _repair_truncated_json('{"queries": [{"query": "胡斐 切磋", "dimension": "人物记忆"}, {"query": "令狐冲')
check("截断在字符串中间：可解析且含第1组", isinstance(r1, dict) and any(
    isinstance(q, dict) and q.get("query") == "胡斐 切磋" for q in r1.get("queries", [])), f"got {r1}")
check("截断残留的空对象被_parse_tool_call过滤", _parse_tool_call(
    {"tool_calls": [_MockToolCall('{"queries": [{"query": "胡斐 切磋", "dimension": "人物记忆"}, {"query": "令狐冲')]}
) == [{"query": "胡斐 切磋", "dimension": "人物记忆"}])
# 场景2：截断在键中间
r2 = _repair_truncated_json('{"queries": [{"query": "胡斐 切磋", "dimens')
check("截断在键中间：挽救第1组", r2 == {"queries": [{"query": "胡斐 切磋"}]}, f"got {r2}")
# 场景3：截断在数组开头
r3 = _repair_truncated_json('{"queries": [')
check("截断在数组开头：空数组或None", r3 is None or r3 == {"queries": []}, f"got {r3}")
# 场景4：完整JSON不受影响
r4 = _repair_truncated_json('{"queries": [{"query": "a", "dimension": "b"}]}')
check("完整JSON正常解析", r4 == {"queries": [{"query": "a", "dimension": "b"}]}, f"got {r4}")
# 场景5：完全垃圾
check("垃圾输入返回None", _repair_truncated_json('') is None)

print()
print("=" * 60)
print("④ _parse_tool_call（配合修复后的解析）")
print("=" * 60)
resp = {"tool_calls": [_MockToolCall('{"queries": [{"query": "胡斐 切磋", "dimension": "人物记忆"}, {"query": "令狐冲')]}
q = _parse_tool_call(resp)
check("截断tool_call解析出1组", q is not None and len(q) == 1 and q[0]["query"] == "胡斐 切磋", f"got {q}")
resp2 = {"tool_calls": [_MockToolCall('not json at all')]}
check("非JSON返回None", _parse_tool_call(resp2) is None)
check("无tool_calls返回None", _parse_tool_call({"content": "x"}) is None)

print()
print("=" * 60)
print("⑤ _deduplicate（维度前缀剥离）")
print("=" * 60)
d = _deduplicate(["[人物记忆] 1. 胡斐在佛山救了钟阿四一家", "[剧情回忆] 1. 胡斐在佛山救了钟阿四一家"])
check("同内容不同维度去重为1条", d.count("胡斐在佛山") == 1, f"got: {d[:80]}")

print()
print("=" * 60)
print("⑤ 分流解析：_parse_npc_lines / _parse_l4_lines")
print("=" * 60)
raw_npc = [
    "1. [npc_memory] 【胡一刀的记忆】1753年冬，落马坡决战在即，客栈中与李三奇对饮",
    "2. [npc_memory] 【胡一刀的记忆】1753年冬，苗人凤夜至荒店，决战前夜把酒",
    "1. [npc_memory] 【苗人凤的记忆】1753年冬，腊月十五落马坡决战在即",
    "1. [chapter] 第3章：这不是NPC记忆应被跳过",
    "暂无相关记忆",
]
nl = _parse_npc_lines(raw_npc)
check("NPC行清洗为【XX的记忆】格式", all(l.startswith("【") and "的记忆】" in l for l in nl), f"got {nl}")
check("非NPC行被跳过", not any("第3章" in l or "暂无" in l for l in nl), f"got {nl}")
check("NPC行去重（前30字）", len(nl) == 3, f"got {len(nl)}: {nl}")

raw_l4 = [
    "1. [chapter] 玩家在佛山救了钟阿四一家",
    "1. [rumor] 江湖传言苗人凤打遍天下无敌手",
    "2. [chapter] 玩家在佛山救了钟阿四一家",
    "1. [task] 调查闯王宝藏下落",
]
ll = _parse_l4_lines(raw_l4, ["1. [task] 调查闯王宝藏下落"])
check("L4行清洗保留[分类]标签", all(l.startswith("[") for l in ll), f"got {ll}")
check("L4行去重（含跨源）", len(ll) == 3, f"got {len(ll)}: {ll}")

print()
print("=" * 60)
print("⑤ merge_with_passive（分流合并：NPC→L4-1，其余→L4-2）")
print("=" * 60)
passive = "1. [chapter] 胡斐在佛山救了钟阿四一家\n2. [chapter] 玩家在客栈遇到令狐冲"
active_result = {
    "text": "【主动检索·剧情线索】\n...",
    "count": 3,
    "npc_lines": [
        "【胡一刀的记忆】1753年冬，落马坡决战在即，客栈中与李三奇对饮",
        "【苗人凤的记忆】1753年冬，腊月十五落马坡决战在即",
    ],
    "l4_lines": [
        "[chapter] 胡斐在佛山救了钟阿四一家",
        "[rumor] 江湖传言苗人凤打遍天下无敌手",
    ],
    "error": None,
}
passive_npc = "【苗人凤的记忆】1753年冬，腊月十五落马坡决战在即，李三奇随胡一刀至落马坡观战"
m = merge_with_passive(passive, active_result, passive_npc_block=passive_npc)

check("返回结构含l4/npc两个键", set(m.keys()) >= {"l4", "npc"}, f"got {m.keys()}")
check("NPC记忆分流入npc键", "【胡一刀的记忆】" in m["npc"], f"got {m['npc']}")
check("NPC记忆与被动L4-1去重（同NPC不同内容保留）", "【苗人凤的记忆】1753年冬，腊月十五" in m["npc"])
check("npc键格式与被动L4-1一致（无序号无标签）", all(not l[0].isdigit() and not l.startswith("[") for l in m["npc"].splitlines() if l.strip()))
check("L4-2重复条目被去重", m["l4"].count("胡斐在佛山") == 1, f"got {m['l4']}")
check("L4-2新条目保留", "[rumor] 江湖传言" in m["l4"])
check("L4-2续接被动编号（3.开头）", "\n3. [rumor] 江湖传言" in m["l4"], f"got {m['l4']}")
check("L4-2无主动检索标记头", "【主动检索" not in m["l4"])

# 被动为占位符时
m2 = merge_with_passive("无相关历史线索", active_result)
check("被动占位符被替换为主动条目", "无相关历史线索" not in m2["l4"] and m2["l4"].startswith("1. [chapter]"), f"got {m2['l4']}")
check("占位符场景编号从1连续", m2["l4"].startswith("1. ") and "\n2. " in m2["l4"], f"got {m2['l4']}")

# 主动失败时
m3 = merge_with_passive(passive, {"text": "", "count": 0, "error": "timeout"})
check("主动失败l4返回原被动文本", m3["l4"] == passive and m3["npc"] == "")

# 全部重复时
m4 = merge_with_passive(passive, {"npc_lines": [], "l4_lines": ["[chapter] 胡斐在佛山救了钟阿四一家"], "error": None})
check("全部重复l4返回原被动文本", m4["l4"] == passive and m4["npc"] == "")

# NPC全部与被动重复时
m5 = merge_with_passive(passive, {"npc_lines": [passive_npc], "l4_lines": [], "error": None}, passive_npc_block=passive_npc)
check("NPC全重复时npc为空且l4不变", m5["npc"] == "" and m5["l4"] == passive)

print()
print("=" * 60)
print("⑦⑧+取消机制：_search_one_group（不触发API）")
print("=" * 60)
ev = threading.Event()
ev.set()
r = _search_one_group("胡斐 切磋", "slot_test", ["胡斐", "令狐冲"], ev)
check("取消后返回空结果", r["l4"] == "" and r["npc"] == "" and r["quest"] == "")

import os
before = os.environ.get("CLOUD_MEM_SLOT_ID")
print()
print("=" * 60)
print("⑦ 环境变量污染检查（active_retrieve_cloud已移除os.environ写入）")
print("=" * 60)
import inspect
from active_cloud_retrieval import active_retrieve_cloud
src = inspect.getsource(active_retrieve_cloud)
check("入口函数不再写os.environ", 'os.environ[' not in src)

print()
print("=" * 60)
print(f"结果：{PASS} 通过，{FAIL} 失败")
print("=" * 60)
exit(0 if FAIL == 0 else 1)
