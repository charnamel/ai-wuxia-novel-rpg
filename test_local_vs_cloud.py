# -*- coding: utf-8 -*-
"""
test_local_vs_cloud.py — 本地向量库 vs 百炼云向量库 检索质量对比
================================================================
【方法】5 组贴近实际调用的查询场景，同时调用云端与本地检索：
  - 云端：cloud_memory_v2.get_relevant_history（MEMORY_BACKEND 默认 cloud）
  - 本地：local_vector_store.get_relevant_history（迁移后的本地库）
【指标】召回条数 / 平均耗时 / 两端内容重合度（前30字匹配）/ 相关性人工抽查
"""

import os
import re
import time
import json

from dotenv import load_dotenv
load_dotenv()

# 显式保持 cloud 模式（确保拿到云端原版函数做对照）
assert os.getenv("MEMORY_BACKEND", "cloud").lower() != "local", "对比测试须在 cloud 模式下运行"

import cloud_memory_v2 as cloud
import local_vector_store as local

# 槽位与云端实际数据对齐（本地.env可能过时，从云端已上传ID推断，同迁移脚本）
def detect_slot():
    from collections import Counter
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cloud_memory_uploaded.json")
    if os.path.exists(p):
        ids = json.load(open(p, encoding="utf-8"))
        slots = Counter()
        for u in ids:
            parts = u.split("_")
            if len(parts) >= 3 and parts[0] == "default" and parts[1] == "player":
                slots[f"default_player_{parts[2]}"] += 1
        if slots:
            return slots.most_common(1)[0][0]
    return os.getenv("CLOUD_MEM_SLOT_ID", "default_player_XSFH6")


SLOT = detect_slot()
print(f"[对比] 检索槽位: {SLOT}")

SCENARIOS = [
    {
        "name": "场景1: 胡斐切磋武功",
        "query": "胡斐 切磋 刀法 武功",
        "cats": ["npc_memory", "单轮剧情"],
    },
    {
        "name": "场景2: 令狐冲与独孤九剑",
        "query": "令狐冲 独孤九剑 剑法 来历",
        "cats": None,  # 全类别
    },
    {
        "name": "场景3: 少林寺与葵花宝典",
        "query": "少林寺 葵花宝典 秘籍 下落",
        "cats": None,
    },
    {
        "name": "场景4: 苗人凤落马坡决战（当前剧情）",
        "query": "苗人凤 胡一刀 落马坡 决战",
        "cats": ["章节摘要", "npc_memory"],
    },
    {
        "name": "场景5: 程灵素雪参玉露丸（近期细节）",
        "query": "程灵素 雪参玉露丸 易容 警告",
        "cats": ["npc_memory"],
    },
]

REPORT = {"scenarios": [], "summary": {}}


def norm_key(line):
    """条目行 → 去重key（剥序号/分类标签/记忆主名/日期前缀后取30字，消除云端novel_node前缀差异）"""
    s = re.sub(r"^\d+\.\s*", "", line.strip())
    s = re.sub(r"^\[[^\]]+\]\s*", "", s)
    s = re.sub(r"^【[^】]{1,20}的记忆】\s*", "", s)
    s = re.sub(r"^1[6-9]\d{2}年[春夏秋冬]?[正一二三四五六七八九十腊冬\d]*月?[，,]?\s*", "", s)
    s = re.sub(r"^[正二三四五六七八九十腊冬\d]+月[初十廿一二三四五六七八九]*[日，,]?\s*", "", s)
    return s.strip()


def run_one(name, query, cats, backend_fn, tag):
    t0 = time.time()
    text = backend_fn(SLOT, query, top_k=5, min_score=0.40, category_filter=cats)
    dt = time.time() - t0
    lines = [l for l in (text or "").split("\n") if l.strip() and not l.startswith("【相关历史线索】")]
    keys = {norm_key(l) for l in lines}
    print(f"  [{tag}] {len(lines)}条 / {dt*1000:.0f}ms")
    for l in lines:
        print(f"      {l[:76]}")
    return {"count": len(lines), "ms": round(dt * 1000), "keys": keys, "lines": lines}


# 预热本地模型（排除首次加载耗时对均值的影响）
print("[预热] 本地模型加载中...")
local.get_relevant_history(SLOT, "预热查询", top_k=1, min_score=0.99)


def calc_overlap(cloud_keys, local_keys):
    """双向子串匹配：云端条目正文（前40字）在本地条目中出现（或反之）即视为同一条记忆"""
    n = 0
    for ck in cloud_keys:
        ck_body = ck[:40]
        if not ck_body:
            continue
        for lk in local_keys:
            lk_body = lk[:40]
            if ck_body in lk or lk_body in ck:
                n += 1
                break
    return n


for sc in SCENARIOS:
    print(f"\n{'='*70}\n{sc['name']}  query={sc['query']!r}  cats={sc['cats']}")
    print("-" * 70)
    c = run_one(sc["name"], sc["query"], sc["cats"], cloud.get_relevant_history, "云端")
    print("-" * 70)
    l = run_one(sc["name"], sc["query"], sc["cats"], local.get_relevant_history, "本地")
    overlap = calc_overlap(c["keys"], l["keys"])
    REPORT["scenarios"].append({
        "name": sc["name"], "query": sc["query"],
        "cloud": {k: c[k] for k in ("count", "ms")},
        "local": {k: l[k] for k in ("count", "ms")},
        "overlap": overlap,
        "cloud_lines": c["lines"], "local_lines": l["lines"],
    })
    print(f"  → 重合 {overlap} 条，云端{c['count']}条 / 本地{l['count']}条，"
          f"云端{c['ms']}ms / 本地{l['ms']}ms")

# ===== 汇总 =====
tc = sum(s["cloud"]["count"] for s in REPORT["scenarios"])
tl = sum(s["local"]["count"] for s in REPORT["scenarios"])
to = sum(s["overlap"] for s in REPORT["scenarios"])
mc = sum(s["cloud"]["ms"] for s in REPORT["scenarios"]) / len(REPORT["scenarios"])
ml = sum(s["local"]["ms"] for s in REPORT["scenarios"]) / len(REPORT["scenarios"])
REPORT["summary"] = {
    "cloud_total": tc, "local_total": tl, "overlap_total": to,
    "cloud_avg_ms": round(mc), "local_avg_ms": round(ml),
}
print(f"\n{'='*70}\n【汇总】云端总召回 {tc} 条 | 本地总召回 {tl} 条 | 内容重合 {to} 条")
print(f"【耗时】云端平均 {mc:.0f}ms/次 | 本地平均 {ml:.0f}ms/次（提速 {mc/ml:.1f}x）")

with open("docs/local_vs_cloud_report.json", "w", encoding="utf-8") as f:
    json.dump(REPORT, f, ensure_ascii=False, indent=2)
print("[报告] 已保存 docs/local_vs_cloud_report.json")
