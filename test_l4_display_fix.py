# -*- coding: utf-8 -*-
"""测试 L4-2 显示层3项修复：多行压单行 / 标题行过滤 / emoji去重"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["MEMORY_BACKEND"] = "local"

ok = True

# ========== 测试1：_parse_l4_lines 过滤标题行 ==========
from active_cloud_retrieval import _parse_l4_lines, merge_with_passive, _PREFIX_RE

# 模拟修复后本地库检索输出（标题行待过滤 + 压平后的单行条目 + 占位符）
raw_lines = [
    "【相关历史线索】（语义匹配过往伏笔、传闻、任务记录）",   # 标题行（应被过滤）
    "1. [章节摘要] 雪夜托孤赴沧州局 雪夜之中，胡夫人将胡斐托付于你，赶赴沧州。",  # 与被动重复，应去重
    "2. [江湖见闻] 【近期剧情记录】胡苗决战首日战罢约明日再战，李三奇陪胡一刀归店",
    "3. [章节摘要] 鸳鸯刀定风波 平西川现身保定，群侠齐聚飞马镖局。",
    "4. [章节摘要] 萧府夜战退铁鹞，晋阳传功续前缘 平西川伏诛后萧府夜宴。",
    "暂无相关历史线索",                                        # 占位符（应被过滤）
]
out = _parse_l4_lines(raw_lines, [])
print(f"[1] 解析结果（{len(out)}条）:")
for l in out:
    print("    ", l[:50])
assert not any("【相关历史线索】" in l for l in out), "标题行未被过滤！"
assert not any("暂无" in l for l in out), "占位符未被过滤！"
print("[1] 通过：标题行和占位符均被过滤\n")

# ========== 测试2：merge_with_passive emoji去重 ==========
passive_text = (
    "1. [章节摘要] 雪夜托孤赴沧州局 雪夜之中，胡夫人将胡斐托付于你，赶赴沧州。\n"
    "📜 [剧情] [单轮剧情] 听说内个苗人凤和胡一刀最近在江湖上名声渐起\n"
    "📋 [任务] [任务记录] 【任务】沧州城外胡苗决战，江湖豪杰齐赴约\n"
    "📰 [剧情记录] [江湖见闻] 【近期剧情记录】胡苗决战首日战罢约明日再战，李三奇陪胡一刀归店"
)
active_result = {
    "npc_lines": ["【胡一刀的记忆】1753年冬，与苗人凤首日交手不分胜负"],
    "l4_lines": out,
}
merged = merge_with_passive(passive_text, active_result)
print("[2] 合并后的 L4-2:")
print(merged["l4"])
print("[2] 合并后的 L4-1 追加:", merged["npc"])
lines = merged["l4"].split("\n")
rumor_count = sum(1 for l in lines if "胡苗决战首日战罢" in l)
assert rumor_count == 1, f"见闻重复了{rumor_count}次！"
assert not any(l.strip().startswith(("2. [章节摘要] 雪夜", "3. [章节摘要] 雪夜")) for l in lines), "章节未去重！"
print("[2] 通过：见闻只出现1次，被动已有章节被去重\n")

# ========== 测试3：本地库 search() 多行压单行（真实数据） ==========
import local_vector_store as lvs
text, nodes = lvs._store.search(
    user_id="default_player_XSFH6", query="胡一刀 苗人凤 决战",
    top_k=2, min_score=0.40, category_filter=[lvs.MemoryCategory.CHAPTER])
print("[3] 本地库真实检索输出（章节摘要）:")
for line in text.split("\n"):
    print("    ", line[:80] + ("..." if len(line) > 80 else ""))
body_lines = [l for l in text.split("\n") if l and not l.startswith("【相关历史线索】")]
assert all(re.match(r'^\d+\.\s\[', l) for l in body_lines), "存在无序号续行（多行未压平）！"
ch_full = [l for l in body_lines if "[章节摘要]" in l]
assert all(len(l) > 50 for l in ch_full), "章节摘要只有标题没有正文！"
print(f"[3] 通过：{len(body_lines)}条全部单行，章节摘要含完整正文（最短{min(len(l) for l in ch_full)}字）")

print("\n=== 全部3项修复测试通过 ===")
