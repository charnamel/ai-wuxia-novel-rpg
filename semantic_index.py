# -*- coding: utf-8 -*-
"""
semantic_index.py — 语义向量检索模块
=====================================
【设计原则】懒加载、向量缓存、增量检测、安全降级
【功能】对世界书2179条目做语义向量编码，支持余弦相似度检索
【集成方式】worldbook.py 的 search() 中作为 L5 层叠加调用
【依赖】sentence-transformers + numpy（未安装时自动降级）
"""

import os
import json
import time
import hashlib

# ========== 0. HuggingFace环境固化 ==========
# 在import sentence_transformers之前设置，避免联网检查
# setdefault：已设置的环境变量不会被覆盖（systemd的优先级更高）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np

# ========== 1. 配置加载 ==========
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
_VECTOR_CACHE = os.path.join(_DATA_DIR, "semantic_vectors.npy")
_ID_CACHE = os.path.join(_DATA_DIR, "semantic_ids.json")

# 环境变量配置（默认关闭，明确启用才开启）
_ENABLE = os.getenv("ENABLE_SEMANTIC_SEARCH", "false").lower() == "true"
_MODEL_NAME = os.getenv("SEMANTIC_MODEL", "BAAI/bge-small-zh-v1.5")
_MIN_SIMILARITY = float(os.getenv("SEMANTIC_MIN_SIMILARITY", "0.45"))
_SCORE_WEIGHT = float(os.getenv("SEMANTIC_SCORE_WEIGHT", "2.0"))

# ========== 2. 全局状态 ==========
_model = None           # SentenceTransformer模型实例
_vectors = None         # np.ndarray [N, 512]，归一化后的向量矩阵
_id_list = None         # [entry_id, ...] 与向量行一一对应
_hash_list = None       # [content_hash, ...] 与向量行一一对应，用于检测内容变更
_id_to_idx = None       # {entry_id: row_index}（预留，目前用list.index）
_available = False      # 模型是否加载成功
_build_attempted = False  # 是否已尝试过构建（避免反复重试）


# ========== 3. 模型加载（懒加载） ==========
def _load_model():
    """懒加载embedding模型（首次调用时加载，约3秒）"""
    global _model, _available
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            t0 = time.time()
            _model = SentenceTransformer(_MODEL_NAME, device='cpu')
            _available = True
            print(f"[语义检索] ✅ 模型加载完成: {_MODEL_NAME} ({time.time()-t0:.1f}s)")
        except ImportError:
            _available = False
            # 不打印错误，避免未安装时刷屏
        except Exception as e:
            _available = False
            print(f"[语义检索] ❌ 模型加载失败（安全降级）: {e}")
    return _model


def is_available():
    """检查语义检索是否可用（供worldbook调用决定是否走L5）"""
    if not _ENABLE:
        return False
    if _available and _vectors is not None:
        return True
    # 首次检查：尝试加载模型
    if _model is None:
        _load_model()
    return _available and _vectors is not None


# ========== 4. 向量缓存（加载/保存） ==========
def load_cache():
    """加载缓存的向量（启动时调用，避免重新编码）"""
    global _vectors, _id_list, _hash_list, _id_to_idx
    try:
        if os.path.exists(_VECTOR_CACHE) and os.path.exists(_ID_CACHE):
            _vectors = np.load(_VECTOR_CACHE)
            with open(_ID_CACHE, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            # 兼容新旧格式
            # 旧格式: ["id1", "id2", ...]
            # 新格式: [["id1", "hash1"], ["id2", "hash2"], ...]
            if raw and isinstance(raw[0], list):
                _id_list = [item[0] for item in raw]
                _hash_list = [item[1] for item in raw]
            else:
                _id_list = raw
                _hash_list = [None] * len(_id_list)

            _id_to_idx = {eid: i for i, eid in enumerate(_id_list)}
            print(f"[语义检索] ✅ 加载缓存向量: {len(_id_list)}条, {_vectors.shape[1]}维")
            return True
    except Exception as e:
        print(f"[语义检索] 缓存加载失败: {e}")
    return False


def _save_cache():
    """保存向量到缓存文件"""
    global _vectors, _id_list, _hash_list
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
        np.save(_VECTOR_CACHE, _vectors)
        # 新格式: [["id", "hash"], ...]
        if _hash_list is None:
            _hash_list = [None] * len(_id_list)
        cache_data = [[eid, h] for eid, h in zip(_id_list, _hash_list)]
        with open(_ID_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False)
    except Exception as e:
        print(f"[语义检索] 缓存保存失败: {e}")


def _compute_hash(entry):
    """计算条目内容的哈希（用于检测内容变更）"""
    text = f"{entry.get('title', '')} {entry.get('content', '')}"[:200]
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:8]


# ========== 5. 向量构建（增量编码） ==========
def build_vectors(entries):
    """
    构建向量索引（worldbook._build()调用）
    【增量策略】只编码新增/变更的条目，保留已缓存的向量
    :param entries: {eid: entry_dict} 来自WorldbookIndex._entries
    """
    global _vectors, _id_list, _hash_list, _id_to_idx, _build_attempted

    if not _ENABLE:
        return

    # 尝试加载缓存
    if _vectors is None:
        load_cache()

    current_ids = set(entries.keys())

    # === 场景1：无缓存 → 全量构建 ===
    if _id_list is None or _vectors is None or len(_id_list) == 0:
        _build_full(entries)
        _build_attempted = True
        return

    cached_ids = set(_id_list)

    # 计算当前所有条目的内容哈希
    current_hash_map = {eid: _compute_hash(entries[eid]) for eid in entries}

    # 检测三种变更
    new_ids = current_ids - cached_ids                        # 新增
    removed_ids = cached_ids - current_ids                    # 删除
    modified_ids = set()                                      # 内容变更
    for eid in current_ids & cached_ids:
        idx = _id_to_idx.get(eid)
        if idx is not None and idx < len(_hash_list):
            if _hash_list[idx] != current_hash_map[eid]:
                modified_ids.add(eid)
        else:
            modified_ids.add(eid)  # 无哈希记录，视为变更

    # 无任何变更 → 跳过
    if not new_ids and not removed_ids and not modified_ids:
        if _model is None:
            import threading
            threading.Thread(target=_load_model, daemon=True).start()
        return

    # 如果变动量超过50% → 全量重建更划算
    total_change = len(new_ids) + len(removed_ids) + len(modified_ids)
    if total_change > len(entries) * 0.5:
        _build_full(entries)
        _build_attempted = True
        return

    # 增量更新需要加载模型
    model = _load_model()
    if model is None:
        _build_attempted = True
        return

    t0 = time.time()

    # --- Step1: 删除已移除 + 已变更的旧向量（变更的需重新编码）---
    ids_to_remove = removed_ids | modified_ids
    if ids_to_remove:
        keep_mask = [eid not in ids_to_remove for eid in _id_list]
        _vectors = _vectors[keep_mask]
        _id_list = [eid for eid in _id_list if eid not in ids_to_remove]
        _hash_list = [h for h, keep in zip(_hash_list, keep_mask) if keep]
        if removed_ids:
            print(f"[语义检索] 删除 {len(removed_ids)} 条")

    # --- Step2: 编码新增 + 变更条目 ---
    ids_to_encode = new_ids | modified_ids
    if ids_to_encode:
        new_texts = []
        new_id_list = []
        new_hash_list = []
        for eid in entries:
            if eid in ids_to_encode:
                entry = entries[eid]
                text = f"{entry.get('title', '')} {entry.get('content', '')}"
                new_texts.append(text[:200])
                new_id_list.append(eid)
                new_hash_list.append(current_hash_map[eid])

        print(f"[语义检索] 增量编码 {len(new_texts)} 条 (新增{len(new_ids)}/变更{len(modified_ids)})...")
        new_vecs = model.encode(
            new_texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=False
        )
        new_vecs = np.array(new_vecs, dtype=np.float32)

        # 拼接到现有向量
        if len(_id_list) > 0:
            _vectors = np.vstack([_vectors, new_vecs])
        else:
            _vectors = new_vecs
        _id_list = _id_list + new_id_list
        _hash_list = _hash_list + new_hash_list

    # --- Step3: 更新索引映射 ---
    _id_to_idx = {eid: i for i, eid in enumerate(_id_list)}

    # --- Step4: 保存缓存 ---
    _save_cache()

    duration = time.time() - t0
    mem_mb = _vectors.nbytes / 1024 / 1024
    print(f"[语义检索] ✅ 增量更新完成: {len(_id_list)}条 (+{len(new_ids)}/改{len(modified_ids)}/-{len(removed_ids)}), {duration:.1f}s, {mem_mb:.1f}MB")
    _build_attempted = True


def _build_full(entries):
    """全量构建向量索引（首次或大批量变更时调用）"""
    global _vectors, _id_list, _hash_list, _id_to_idx

    model = _load_model()
    if model is None:
        return

    t0 = time.time()
    _id_list = list(entries.keys())
    texts = []
    _hash_list = []
    for eid in _id_list:
        entry = entries[eid]
        text = f"{entry.get('title', '')} {entry.get('content', '')}"
        texts.append(text[:200])
        _hash_list.append(_compute_hash(entry))

    print(f"[语义检索] 全量编码 {len(texts)} 条目...")
    _vectors = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False
    )
    _vectors = np.array(_vectors, dtype=np.float32)
    _id_to_idx = {eid: i for i, eid in enumerate(_id_list)}

    _save_cache()

    duration = time.time() - t0
    mem_mb = _vectors.nbytes / 1024 / 1024
    print(f"[语义检索] ✅ 全量构建: {len(_id_list)}条, {duration:.1f}s, {mem_mb:.1f}MB")


# ========== 6. 语义检索 ==========
def search_semantic(query_text, top_k=30):
    """
    语义检索（worldbook.search()调用）
    :param query_text: 查询文本
    :param top_k: 返回前N条
    :return: [(eid, similarity_score), ...] 按相似度降序，已过滤低相似度
    """
    if not _ENABLE or _vectors is None or _id_list is None or not query_text:
        return []

    try:
        model = _load_model()
        if model is None:
            return []

        # 编码query
        query_vec = model.encode(
            [query_text],
            normalize_embeddings=True
        )
        query_vec = np.array(query_vec[0], dtype=np.float32)

        # 矩阵乘法 = cosine相似度（向量已归一化，内积=余弦）
        similarities = _vectors @ query_vec  # [N]

        # TopK排序
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # 门槛过滤
        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score < _MIN_SIMILARITY:
                break
            eid = _id_list[idx]
            results.append((eid, score))

        return results
    except Exception as e:
        print(f"[语义检索] 检索异常（安全降级）: {e}")
        return []


# ========== 7. 状态查询（供Web端） ==========
def get_status():
    """供web端状态查询"""
    return {
        "enabled": _ENABLE,
        "available": _available and _vectors is not None,
        "model": _MODEL_NAME if _ENABLE else "未启用",
        "vector_count": len(_id_list) if _id_list else 0,
        "vector_dim": int(_vectors.shape[1]) if _vectors is not None else 0,
        "min_similarity": _MIN_SIMILARITY,
        "score_weight": _SCORE_WEIGHT,
        "cache_exists": os.path.exists(_VECTOR_CACHE),
    }


def get_score_weight():
    """获取L5打分系数（供worldbook.search调用）"""
    return _SCORE_WEIGHT


# ========== 8. 模块初始化日志 ==========
if _ENABLE:
    print(f"[语义检索] 配置: 模型={_MODEL_NAME}, 门槛={_MIN_SIMILARITY}, 系数={_SCORE_WEIGHT}")
else:
    print("[语义检索] 未启用（ENABLE_SEMANTIC_SEARCH != true）")
