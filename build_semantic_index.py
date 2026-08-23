# -*- coding: utf-8 -*-
"""
build_semantic_index.py — 本地语义向量索引预构建工具
=====================================================
【用途】
  提前对世界书全部条目（约2200条）做向量编码，生成缓存文件：
    data/semantic_vectors.npy   向量矩阵（约4.5MB）
    data/semantic_ids.json      条目ID + 内容哈希
  游戏运行时直接加载缓存，检索零等待。

【为什么需要预构建】
  若不预构建，首次进入游戏触发检索时会临时全量编码
  （CPU约30秒~2分钟，期间游戏卡住），预构建后启动即秒级就绪。

【使用方法】
  python build_semantic_index.py             # 构建（已存在缓存则增量更新）
  python build_semantic_index.py --rebuild   # 删除缓存后全量重建

【前置条件】
  1. 安装依赖：
     pip install sentence-transformers numpy
  2. 首次构建需联网下载 embedding 模型
     （BAAI/bge-small-zh-v1.5，约95MB，已配置国内镜像 hf-mirror.com）
  3. 之后再次运行无需联网（自动使用本地模型缓存）

【说明】
  本脚本只生成缓存文件，不修改 .env 与任何游戏数据；
  游戏内是否启用语义检索由 .env 中 ENABLE_SEMANTIC_SEARCH 控制。
  数据文件更新后（npc_agents.json 等）重新运行本脚本即可增量更新向量。
"""
import os
import sys
import time

# ====== 环境变量：必须在 import worldbook 之前设置 ======
# 本次构建会话内强制开启语义检索（不改动 .env）
os.environ["ENABLE_SEMANTIC_SEARCH"] = "true"
# 首次构建需要联网下载模型 → 显式覆盖 semantic_index.py 的默认离线模式
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"
# 国内镜像加速（海外网络可删除此行）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(_PROJECT_ROOT)

import worldbook


def main():
    rebuild = "--rebuild" in sys.argv

    print("=" * 60)
    print("  本地语义向量索引预构建工具")
    print("=" * 60)

    # 依赖检查
    try:
        import sentence_transformers  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        print("\n[错误] 缺少依赖，请先安装：")
        print("    pip install sentence-transformers numpy")
        sys.exit(1)

    # 强制重建：删除旧缓存
    if rebuild:
        for fname in ("semantic_vectors.npy", "semantic_ids.json"):
            fpath = os.path.join("data", fname)
            if os.path.exists(fpath):
                os.remove(fpath)
                print(f"[重建] 已删除旧缓存: data/{fname}")

    print("\n[1/3] 构建世界书索引并编码向量（首次约1-3分钟）...")
    print("      首次运行需下载模型，请保持网络畅通")
    t0 = time.time()
    worldbook.init()

    # worldbook 为懒加载设计：search() 首次调用时才真正构建索引 + 向量
    worldbook.search("__warmup__")
    duration = time.time() - t0

    print(f"\n[2/3] 构建完成，耗时 {duration:.1f}s")

    print("\n[3/3] 构建结果:")
    status = worldbook.get_status()
    sem = status.get("semantic", {})
    ok = sem.get("available", False)
    print(f"  语义检索可用: {'是' if ok else '否'}")
    print(f"  向量条目数:   {sem.get('vector_count', 0)}")
    print(f"  向量维度:     {sem.get('vector_dim', 0)}")
    print(f"  缓存文件:     data/semantic_vectors.npy")
    print(f"  相似度门槛:   {sem.get('min_similarity', 0)}")
    print(f"  打分系数:     {sem.get('score_weight', 0)}")

    print("\n" + "=" * 60)
    if ok:
        print("预构建成功！游戏启动后将直接加载缓存，检索零等待。")
        print("提醒：请确保 .env 中 ENABLE_SEMANTIC_SEARCH=true，")
        print("      否则游戏运行时不会启用语义检索层。")
    else:
        print("构建失败，可能原因：")
        print("  1. 模型下载失败（检查网络后重试，或配置代理）")
        print("  2. 内存不足（模型加载约需500MB内存）")
        print("  3. numpy 版本过旧（尝试 pip install -U numpy）")
    print("=" * 60)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
