# -*- coding: utf-8 -*-
"""
migrate_cloud_to_local.py — 云向量记忆本地化迁移脚本
=====================================================
【来源】本地 data/ 数据源重放（云端 1500 条记忆的原始出处都在本地）：
  1. npc_agents.json  → NPC_MEMORY（1038条，unique_id 与云端规则完全一致）
  2. interact_log.jsonl → PLOT_ROUND（按动作词/长度规则筛选，ID=轮次号，与云端对齐）
  3. context_cache.json → CHAPTER（47章全量）
  4. tasks.json       → TASK（任务描述近似重建，ID 不对齐但内容近似）
  5. world_state.json → RUMOR（江湖见闻）
【输出】data/local_memory_entries.jsonl + local_memory_vectors.npy
【校验】与 data/cloud_memory_uploaded.json 的 1500 个云端 ID 求交集，报告覆盖率
【安全】幂等可重复运行（unique_id 去重）；不动任何云端数据
"""

import os
import re
import sys
import json
import hashlib
import time

from dotenv import load_dotenv
load_dotenv()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

import local_vector_store as lvs

DATA = os.path.join(_PROJECT_ROOT, "data")


def detect_slot():
    """从云端已上传ID推断实际槽位（本地.env可能过时，以云端数据为准）"""
    p = os.path.join(DATA, "cloud_memory_uploaded.json")
    if os.path.exists(p):
        from collections import Counter
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


def load_json(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        print(f"[迁移] 跳过（文件不存在）: {name}")
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ========== 1. NPC_MEMORY ==========
def build_npc_items():
    npc_data = load_json("npc_agents.json")
    if not npc_data:
        return []
    items = []
    for npc in npc_data.get("npc_list", []):
        name = npc.get("name", "").strip()
        if not name:
            continue
        for mem in npc.get("memory_list", []):
            mem = str(mem).strip()
            if not mem:
                continue
            content = f"【{name}的记忆】{mem[:200]}"
            hash_str = hashlib.md5(mem.encode("utf-8")).hexdigest()[:8]
            items.append({
                "user_id": SLOT, "content": content,
                "category": lvs.MemoryCategory.NPC_MEMORY,
                "meta": None, "unique_id": f"{SLOT}_NPC_MEMORY_{name}_{hash_str}",
            })
    return items


# ========== 2. PLOT_ROUND ==========
_ACTION_WORDS = ["去", "到", "找", "杀", "救", "拿", "取", "放", "走", "跑", "追", "逃",
                 "战", "比", "见", "说", "问", "买", "卖", "学", "练", "闯", "探", "寻",
                 "决", "离", "回", "赴", "谈", "交", "夺", "护", "劫", "救", "启"]


def build_plot_items():
    p = os.path.join(DATA, "interact_log.jsonl")
    if not os.path.exists(p):
        print("[迁移] 跳过 interact_log.jsonl")
        return []
    items = []
    total = 0
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                text = json.loads(line).get("text", "")
            except json.JSONDecodeError:
                continue
            total += 1
            m = re.match(r"【第\s*(\d+)\s*轮交互】", text)
            if not m:
                continue
            round_num = int(m.group(1))
            # 提取玩家行动（【玩家行动】到【本轮剧情】之间）
            ma = re.search(r"【玩家行动】(.*?)(?:【本轮剧情】|$)", text, re.DOTALL)
            user_action = ma.group(1).strip() if ma else ""
            # 提取本轮剧情
            mp = re.search(r"【本轮剧情】(.*?)$", text, re.DOTALL)
            plot = mp.group(1).strip() if mp else ""
            if not plot:
                continue
            # 近似复现云端上传判定：行动含动作词 或 行动超20字
            should = any(w in user_action for w in _ACTION_WORDS) or len(user_action) > 20
            if not should:
                continue
            clean_action = re.sub(r"【[^】]+】", "", user_action).strip()
            short_plot = re.sub(r"【[^】]+】", "", plot[:200]).strip()
            content = f"{clean_action}。{short_plot}"
            items.append({
                "user_id": SLOT, "content": content,
                "category": lvs.MemoryCategory.PLOT_ROUND,
                "meta": {"round": round_num},
                "unique_id": f"{SLOT}_PLOT_ROUND_{round_num}",
            })
    print(f"[迁移] interact_log 共 {total} 轮，按上传规则筛选出 {len(items)} 轮")
    return items


# ========== 3. CHAPTER ==========
def build_chapter_items():
    cache = load_json("context_cache.json")
    if not cache:
        return []
    items = []
    for ch in cache.get("chapter_summaries", []):
        summary = str(ch.get("summary", "")).strip()
        if not summary:
            continue
        cid = ch.get("chapter_id")
        items.append({
            "user_id": SLOT, "content": summary,
            "category": lvs.MemoryCategory.CHAPTER,
            "meta": {"chapter_id": cid},
            "unique_id": f"{SLOT}_CHAPTER_{cid}",
        })
    return items


# ========== 4. TASK ==========
def build_task_items():
    tasks = load_json("tasks.json")
    if not tasks:
        return []
    items = []
    for t in tasks:
        name = (t.get("display_name") or t.get("name") or "").strip()
        desc = str(t.get("description", "")).strip()
        stage = str(t.get("current_stage", "")).strip()
        if not name:
            continue
        content = f"【任务】{name}：{desc[:300]}"
        hash_input = f"{name}_{desc[:100]}"
        hash_str = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:8]
        items.append({
            "user_id": SLOT, "content": content,
            "category": lvs.MemoryCategory.TASK,
            "meta": {"stage": stage[:150]},
            "unique_id": f"{SLOT}_TASK_MEMORY_{hash_str}",
        })
    return items


# ========== 5. RUMOR（江湖见闻） ==========
def build_rumor_items():
    ws = load_json("world_state.json")
    if not ws:
        return []
    items = []
    rumors = ws.get("recent_rumor") or ws.get("江湖见闻") or ws.get("rumors") or []
    if isinstance(rumors, str):
        rumors = [rumors]
    for r in rumors:
        r = str(r).strip()
        if not r or r in ("无", "（无）", "(无)"):
            continue
        content = f"【近期剧情记录】{r[:200]}"
        hash_str = hashlib.md5(f"_{r}".encode("utf-8")).hexdigest()[:8]
        items.append({
            "user_id": SLOT, "content": content,
            "category": lvs.MemoryCategory.RUMOR,
            "meta": None, "unique_id": f"{SLOT}_RUMOR_ITEM_{hash_str}",
        })
    return items


# ========== 主流程 ==========
def main():
    t0 = time.time()
    print(f"[迁移] 槽位: {SLOT}")
    builders = [
        ("NPC_MEMORY", build_npc_items),
        ("PLOT_ROUND", build_plot_items),
        ("CHAPTER", build_chapter_items),
        ("TASK", build_task_items),
        ("RUMOR", build_rumor_items),
    ]
    total_added = 0
    for label, builder in builders:
        items = builder()
        if not items:
            print(f"[迁移] {label}: 0 条（跳过）")
            continue
        t1 = time.time()
        added = lvs._store.add_many(items)
        total_added += added
        print(f"[迁移] {label}: 新增 {added}/{len(items)} 条（{time.time()-t1:.1f}s）")
    lvs._store.flush()

    # ===== 覆盖率校验（与云端已上传 ID 对照） =====
    cloud_ids = set()
    p = os.path.join(DATA, "cloud_memory_uploaded.json")
    if os.path.exists(p):
        cloud_ids = set(json.load(open(p, encoding="utf-8")))
    local_ids = {e["unique_id"] for e in lvs._store._entries}
    inter = cloud_ids & local_ids
    print("\n" + "=" * 56)
    print(f"[迁移] 完成：本地库共 {len(lvs._store._entries)} 条，总耗时 {time.time()-t0:.1f}s")
    if cloud_ids:
        print(f"[迁移] 云端 ID 1500条中，本地精确对齐 {len(inter)} 条"
              f"（{len(inter)/len(cloud_ids)*100:.0f}%，ID含AI文本hash的类别无法精确对齐）")
    # 分类统计
    from collections import Counter
    cats = Counter(e["category"] for e in lvs._store._entries)
    for cat, n in cats.most_common():
        print(f"    {cat}: {n}")


if __name__ == "__main__":
    main()
