# -*- coding: utf-8 -*-
"""测试状态API自愈修复（/memory/status + /worldbook/status）
覆盖：自愈触发、旧版local_vector_store兼容、时间戳格式化、语义自愈
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["MEMORY_BACKEND"] = "local"  # 必须在 import web_server 前设置

print("=" * 60)
print("[导入] web_server（含main，耗时较长）...")
t0 = time.time()
import web_server  # noqa: E402
print(f"[导入] 完成 ({time.time()-t0:.1f}s)")

client = web_server.app.test_client()

# ========== T1: /memory/status 初始状态 + 自愈触发 ==========
d = client.get('/memory/status').get_json()
print(f"\n[T1] memory初始: backend={d['backend']}, status={d['status']}, "
      f"entries={d['total_entries']}, model={d['model']}")
assert d["backend"] == "local", "后端应为local"
assert d["total_entries"] == 1581, "条数应为1581"
print("[T1] 通过：接口正常返回")

# ========== T2: 自愈轮询（模型加载→ready，最长150s） ==========
print("[T2] 等待记忆模型自愈加载...")
deadline = time.time() + 150
while time.time() < deadline:
    d = client.get('/memory/status').get_json()
    if d["status"] == "ready":
        break
    time.sleep(4)
assert d["status"] == "ready", f"自愈失败：status={d['status']}, error={d.get('model_error')}"
cats = d.get("categories") or {}
print(f"[T2] 通过：{time.time()-deadline+150:.0f}s内转ready，分类={ {k: v for k, v in list(cats.items())[:4]} }")
assert cats.get("NPC记忆") == 1038, "NPC记忆分类应为1038"

# ========== T3: 旧版 local_vector_store 兼容（探测+现算分类） ==========
import local_vector_store as lvs
_orig = lvs.get_status
lvs.get_status = lambda: {"available": True, "model": "BAAI/bge-small-zh-v1.5",
                          "model_error": None, "count": 1581}  # 旧版无 model_ready/categories
try:
    d = client.get('/memory/status').get_json()
finally:
    lvs.get_status = _orig
print(f"\n[T3] 旧版兼容: status={d['status']}, categories含NPC记忆={d['categories'].get('NPC记忆')}")
assert d["status"] == "ready", "旧版应通过探测_store._model判ready"
assert d["categories"].get("NPC记忆") == 1038, "旧版应从entries现算分类"
print("[T3] 通过：旧版部署也能正确显示")

# ========== T4: /worldbook/status 时间戳格式化 + semantic字段 ==========
d2 = client.get('/worldbook/status').get_json()
print(f"\n[T4] worldbook: status={d2['status']}, last_build_time={d2.get('last_build_time')!r}")
assert "semantic" in d2, "semantic字段应存在（_index未初始化时API会补init）"
if d2.get("last_build_time"):
    assert "-" in d2["last_build_time"] and ":" in d2["last_build_time"], "时间戳未格式化！"
    print("[T4] 通过：时间戳已格式化")
else:
    print("[T4] 通过：last_build为空（未构建），格式化逻辑无原始数字暴露")

# ========== T5: 语义自愈轮询（模型+向量缓存→available，最长150s） ==========
print("[T5] 等待语义模型自愈加载...")
deadline = time.time() + 150
sem = {}
while time.time() < deadline:
    d2 = client.get('/worldbook/status').get_json()
    sem = d2.get("semantic") or {}
    if sem.get("available"):
        break
    time.sleep(4)
print(f"[T5] semantic: available={sem.get('available')}, model_ready={sem.get('model_ready')}, "
      f"vector_count={sem.get('vector_count')}, cache_exists={sem.get('cache_exists')}")
assert sem.get("available"), f"语义自愈失败: {sem}"
print(f"[T5] 通过：语义✅ {sem['vector_count']}条向量")
print("\n=== 全部5项测试通过 ===")
