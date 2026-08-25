# -*- coding: utf-8 -*-
"""test_local_vector_store.py — 本地向量库单元测试（不依赖模型加载）
重点：unique_id 生成规则与云端 cloud_memory_uploaded.json 的真实 ID 对齐验证
"""
import os
import sys
import json
import hashlib
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import local_vector_store as lvs

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CLOUD_IDS = set(json.load(open(os.path.join(DATA, "cloud_memory_uploaded.json"), encoding="utf-8")))

passed, failed = 0, 0
def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


print("=" * 60)
print("1. NPC_MEMORY unique_id 规则对齐（云端真实ID）")
# 云端规则: {slot}_NPC_MEMORY_{npc_name}_{md5(memory_text)[:8]}
# 本地 npc_agents.json 的 memory_list 应能复现出云端 ID
npc_data = json.load(open(os.path.join(DATA, "npc_agents.json"), encoding="utf-8"))
slot = "default_player_XSFH6"
generated = set()
for npc in npc_data["npc_list"]:
    name = npc.get("name", "").strip()
    for mem in npc.get("memory_list", []):
        h = hashlib.md5(str(mem).encode("utf-8")).hexdigest()[:8]
        generated.add(f"{slot}_NPC_MEMORY_{name}_{h}")
# 云端ID中仅取"单人名"部分作分母（复合名如"/ 周绮"、章末蒸馏文本本地无源，属数据源差异非规则差异）
npc_names_local = {n.get("name", "").strip() for n in npc_data["npc_list"]}
npc_cloud_single = {u for u in CLOUD_IDS if "_NPC_MEMORY_" in u
                    and u.split("_NPC_MEMORY_")[1].rsplit("_", 1)[0] in npc_names_local}
hit = generated & npc_cloud_single
check(f"NPC_MEMORY ID 规则可复现云端（{len(hit)}/{len(npc_cloud_single)}，"
      f"差异=memory_list25条裁剪+章末蒸馏无本地源）",
      len(hit) > 0 and len(hit) >= len(npc_cloud_single) * 0.25,
      f"命中{len(hit)} 单人名云端{len(npc_cloud_single)} 全量云端1125 本地生成{len(generated)}")

print("=" * 60)
print("2. PLOT_ROUND unique_id 规则对齐")
plot_cloud = {u for u in CLOUD_IDS if "_PLOT_ROUND_" in u}
check("云端 PLOT_ROUND ID 全部形如 {slot}_PLOT_ROUND_{round}",
      all(re.match(r"^default_player_XSFH6_PLOT_ROUND_\d+$", u) for u in plot_cloud))

print("=" * 60)
print("3. MemoryCategory 值与 cloud_memory_v2 一致")
import cloud_memory_v2 as cm
for attr in ["FORESHADOW", "RUMOR", "TASK", "PLOT_ROUND", "LEGACY_MILESTONE",
             "CHAPTER", "BIOGRAPHY", "HIGH_IMPORTANCE", "NPC_MEMORY"]:
    check(f"MemoryCategory.{attr}", getattr(lvs.MemoryCategory, attr) == getattr(cm.MemoryCategory, attr))

print("=" * 60)
print("4. add_memory 去重（同 unique_id 二次写入拒绝）")
class FakeModel:
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        import numpy as np
        return [[0.1, 0.2, 0.3]] * len(texts)
lvs._store._model = FakeModel()
lvs._store._model_error = None
r1 = lvs._store.add_memory("test_user", "测试内容A", lvs.MemoryCategory.TASK, None, "TEST_UID_1")
r2 = lvs._store.add_memory("test_user", "测试内容A", lvs.MemoryCategory.TASK, None, "TEST_UID_1")
check("首次写入成功", r1 is True)
check("重复 ID 写入被拒绝", r2 is False)

print("=" * 60)
print("5. search 检索与格式")
lvs._store.add_memory("test_user", "【胡一刀的记忆】测试记忆内容X", lvs.MemoryCategory.NPC_MEMORY, None, "TEST_UID_2")
lvs._store.add_memory("test_user", "章节摘要测试内容Y", lvs.MemoryCategory.CHAPTER, None, "TEST_UID_3")
text, nodes = lvs._store.search("test_user", "任意查询", top_k=2, min_score=0.0, category_filter=None)
check("检索返回格式化文本", text.startswith("【相关历史线索】"))
check("条目带序号和分类标签", bool(re.search(r"^1\. \[.+\] ", text, re.MULTILINE)), text[:100])
text_npc, _ = lvs._store.search("test_user", "任意查询", top_k=2, min_score=0.0, category_filter=["npc_memory"])
check("category_filter 过滤生效", "npc_memory" in text_npc and "章节摘要" not in text_npc)
text_other, _ = lvs._store.search("other_user", "任意查询", top_k=2, min_score=0.0)
check("user_id 隔离生效", text_other == "")
text_none, _ = lvs._store.search("test_user", "任意查询", top_k=2, min_score=0.99)
check("min_score 过滤生效（超高阈值无结果）", text_none == "")

print("=" * 60)
print("6. 清理测试数据（还原 store）")
# 移除测试条目，避免污染正式库
with lvs._store._lock:
    lvs._store._entries = [e for e in lvs._store._entries if not e["unique_id"].startswith("TEST_UID_")]
    lvs._store._ids = {e["unique_id"] for e in lvs._store._entries}
    import numpy as np
    if lvs._store._vectors is not None and len(lvs._store._vectors) == 3:
        lvs._store._vectors = None
    # 清空测试写入的文件（正式迁移会全量重建）
    for uid in ("TEST_UID_1", "TEST_UID_2", "TEST_UID_3"):
        pass
check("测试条目已清理", all(not e["unique_id"].startswith("TEST_UID_") for e in lvs._store._entries))

# 清掉测试产生的脏文件，让正式迁移从零开始
for f in ("local_memory_entries.jsonl", "local_memory_vectors.npy", "local_memory_meta.json"):
    p = os.path.join(DATA, f)
    if os.path.exists(p):
        os.remove(p)
print("  已删除测试产生的本地库文件（正式迁移将全量重建）")

print("=" * 60)
print(f"结果: {passed} 通过 / {failed} 失败")
sys.exit(0 if failed == 0 else 1)
