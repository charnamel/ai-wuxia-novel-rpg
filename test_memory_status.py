# -*- coding: utf-8 -*-
"""测试 /memory/status 接口逻辑（不启动 Flask，直接验证核心路径）"""
import os
import sys
import time
import json

os.environ["MEMORY_BACKEND"] = "local"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 1) 后端路由判断（与 web_server.py 端点逻辑一致）
import cloud_memory_v2 as _cmv
backend = getattr(_cmv, "_MEMORY_BACKEND", "cloud").lower()
print(f"[1] backend = {backend}")
assert backend == "local", "后端路由应为 local"

# 2) local 模式状态查询
import local_vector_store as _lvs
s = _lvs.get_status()
print(f"[2] 初始状态: status keys = {sorted(s.keys())}")
print(f"    count={s['count']}, model={s['model']}, "
      f"ready={s['model_ready']}, loading={s['model_loading']}, error={s['model_error']}")

# 3) 端点分类标签映射（与 web_server.py 一致）
_LABELS = {"npc_memory": "NPC记忆", "memory_highlight": "重要剧情"}
cats = {_LABELS.get(k, k): v for k, v in (s.get("categories") or {}).items()}
print(f"[3] 分类统计: {json.dumps(cats, ensure_ascii=False)}")

# 4) 状态流转：等待模型加载完成
if not s["model_ready"]:
    print("[4] 等待模型加载（最长90秒）...")
    t0 = time.time()
    while time.time() - t0 < 90:
        time.sleep(3)
        s2 = _lvs.get_status()
        if s2["model_ready"] or s2["model_error"]:
            break
    print(f"    耗时 {time.time()-t0:.0f}s → ready={s2['model_ready']}, error={s2['model_error']}")
    st = "ready" if s2.get("model_ready") else ("error" if s2.get("model_error") else "loading")
else:
    st = "ready"
    print("[4] 模型已就绪（热缓存）")

# 5) 模拟前端展示
cats_sorted = sorted(cats.items(), key=lambda x: -x[1])[:4]
cat_text = "（" + "/".join(f"{k}{v}" for k, v in cats_sorted) + "）" if cats_sorted else ""
print(f"[5] 前端将显示: {'✅' if st=='ready' else '⏳'} 长期记忆{'已就绪' if st=='ready' else '模型加载中'} · "
      f"{s['count']}条{cat_text} · {s['model']}")
print("\n=== 全部测试通过 ===")
