# -*- coding: utf-8 -*-
"""
embedding_registry.py — 共享向量模型注册表
==========================================
【定位】semantic_index.py（世界书 L5）与 local_vector_store.py（记忆库）共用的
       SentenceTransformer 实例工厂：按模型名缓存，同名共享一份、异名各自加载。
【铁律】检索路径只允许 get_model_nowait()——就绪返回模型、未就绪返回 None 并踢一脚
       后台加载，绝不阻塞；ensure_loaded() 仅限预热线程/写入/重建调用。
【失败策略】TTL 60s 冻结 + 连续失败退避（3 次后间隔翻倍，封顶 10 分钟），成功清零；
       clear_error() 供预热线程解冻重试 / 重建接口自愈。
【编码】不加全局锁：调用方拿到模型引用（快照）后各自分块编码，并发安全、仅 CPU 争用。
"""
import os
import sys
import time
import threading

# HuggingFace 环境固化（与 semantic_index.py 原行为一致；setdefault 不覆盖 systemd/用户设置）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

_LOCK = threading.Lock()   # 只保护 _SLOTS 的读改写（毫秒级）；slot["model"] 单次读取可无锁
_SLOTS = {}                # name -> slot
_ERROR_TTL = 60            # 失败冻结期（秒）
_BACKOFF_AFTER = 3         # 连续失败 N 次后进入退避
_BACKOFF_MAX = 600         # 退避封顶（秒）——防 1.9G 内存机器上"失败→重载"内存抖动


def _new_slot():
    return {"model": None, "loading": False, "error": None, "error_at": 0.0,
            "fail_count": 0, "load_lock": threading.Lock()}


def _get_slot(name):
    with _LOCK:
        return _SLOTS.setdefault(name, _new_slot())


def _retry_after(slot):
    """失败后的下一次允许重试间隔：前 3 次 = TTL，之后翻倍退避、封顶 _BACKOFF_MAX"""
    n = slot["fail_count"]
    if n <= _BACKOFF_AFTER:
        return _ERROR_TTL
    return min(_ERROR_TTL * (2 ** (n - _BACKOFF_AFTER)), _BACKOFF_MAX)


def _do_load(slot, name):
    """实际加载（调用方须持有 slot['load_lock']）。成功/失败均写回 slot。"""
    try:
        t0 = time.time()
        # colorama 护栏仅 Windows 本地开发启用；Linux 服务器不执行此分支
        if sys.platform == "win32":
            try:
                from win_console_guard import ensure_safe_console
                ensure_safe_console()
            except Exception:
                pass
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(name, device="cpu")
        with _LOCK:
            slot["model"] = model
            slot["error"] = None
            slot["error_at"] = 0.0
            slot["fail_count"] = 0
        print(f"[向量模型] ✅ 加载完成: {name} ({time.time() - t0:.1f}s)")
    except Exception as e:
        with _LOCK:
            slot["error"] = str(e)
            slot["error_at"] = time.time()
            slot["fail_count"] += 1
        print(f"[向量模型] ❌ 加载失败（连续第{slot['fail_count']}次）: {name} {str(e)[:120]}")


def _background_load(name):
    slot = _get_slot(name)
    try:
        with slot["load_lock"]:
            if slot["model"] is None:
                _do_load(slot, name)
    finally:
        with _LOCK:
            slot["loading"] = False


def get_model_nowait(name):
    """检索路径专用：就绪返回模型；加载中/冻结期/未启动返回 None（未启动时踢一脚后台加载）。
    【铁律】绝不阻塞——等待模型 30-60 秒会拖死 gunicorn worker。"""
    slot = _get_slot(name)
    with _LOCK:
        if slot["model"] is not None:
            return slot["model"]
        if slot["loading"]:
            return None
        if slot["error"] and (time.time() - slot["error_at"]) < _retry_after(slot):
            return None
        slot["loading"] = True
    threading.Thread(target=_background_load, args=(name,), daemon=True).start()
    return None


def ensure_loaded(name):
    """阻塞加载（仅预热线程/写入/重建调用）：双检锁 + 冻结/退避。成功返回模型，否则 None。"""
    slot = _get_slot(name)
    if slot["model"] is not None:
        return slot["model"]
    if slot["error"] and (time.time() - slot["error_at"]) < _retry_after(slot):
        return None  # 冻结期内直接返回（预热线程周期调用会在解冻后自然重试）
    with slot["load_lock"]:
        if slot["model"] is not None:
            return slot["model"]
        _do_load(slot, name)
        return slot["model"]


def clear_error(name, reset_count=False):
    """解除失败冻结（预热线程重试 / 重建接口自愈用）；reset_count=True 同时清零退避计数。"""
    slot = _get_slot(name)
    with _LOCK:
        slot["error"] = None
        slot["error_at"] = 0.0
        if reset_count:
            slot["fail_count"] = 0


def get_state(name):
    """状态查询（/memory/status、/worldbook/status 展示用）"""
    slot = _get_slot(name)
    with _LOCK:
        return {"ready": slot["model"] is not None,
                "loading": slot["loading"],
                "error": slot["error"],
                "fail_count": slot["fail_count"]}
