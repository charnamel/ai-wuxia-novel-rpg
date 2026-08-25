# -*- coding: utf-8 -*-
"""
local_vector_store.py — 本地向量记忆库（替代百炼云向量库）
============================================================
【定位】与 cloud_memory_v2.py 的公开 API 完全一致（函数名/参数/返回格式），
       由 cloud_memory_v2.py 末尾的路由开关（MEMORY_BACKEND=local）切换生效。
【模型】独立加载 BAAI/bge-small-zh-v1.5（与世界书 semantic_index.py 互不干扰，
       各自一个模型实例，故障隔离 + 主动检索线程可真并行）
【存储】data/local_memory_entries.jsonl（内容） + data/local_memory_vectors.npy（向量矩阵）
【检索】numpy 余弦相似度（向量归一化后内积即余弦），单次 ~20-50ms
【去重】unique_id 规则与云端完全一致（迁移时 ID 可对齐校验覆盖率）
"""

import os
import re
import json
import time
import hashlib
import threading

import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ========== 配置 ==========
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BASE_DIR, "data")
_ENTRIES_FILE = os.path.join(_DATA_DIR, "local_memory_entries.jsonl")
_VECTORS_FILE = os.path.join(_DATA_DIR, "local_memory_vectors.npy")
_META_FILE = os.path.join(_DATA_DIR, "local_memory_meta.json")

# 独立模型配置（默认与世界书同款 bge-small，可单独换模型不影响世界书）
_MODEL_NAME = (os.getenv("LOCAL_MEMORY_MODEL", "") or "").strip() or "BAAI/bge-small-zh-v1.5"
_ENCODE_BATCH = 64          # 批量重建向量时的批大小（避免内存尖峰）
_SAVE_EVERY = 8             # 攒N条落盘一次（迁移提速；进程退出前强制落盘）

# ========== L4 业务分类常量（值与 cloud_memory_v2.MemoryCategory 完全一致） ==========
class MemoryCategory:
    FORESHADOW = "未解决伏笔"
    RUMOR = "江湖见闻"
    TASK = "任务记录"
    PLOT_ROUND = "单轮剧情"
    LEGACY_MILESTONE = "大事记"
    CHAPTER = "章节摘要"
    BIOGRAPHY = "人物传记"
    HIGH_IMPORTANCE = "memory_highlight"
    NPC_MEMORY = "npc_memory"


# ========== 存储核心 ==========
class _LocalStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._ids = set()          # 已写入 unique_id 集合（去重）
        self._entries = []         # [{"unique_id","user_id","content","category","meta"}]
        self._vectors = None       # np.ndarray (N, D) float32 已归一化
        self._model = None
        self._model_error = None
        self._dirty_count = 0      # 未落盘条数计数
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        os.makedirs(_DATA_DIR, exist_ok=True)
        if os.path.exists(_ENTRIES_FILE):
            with open(_ENTRIES_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        self._entries.append(e)
                        self._ids.add(e["unique_id"])
                    except (json.JSONDecodeError, KeyError):
                        continue
        if os.path.exists(_VECTORS_FILE):
            try:
                self._vectors = np.load(_VECTORS_FILE)
            except Exception:
                self._vectors = None
        # 向量数与条目数对齐（异常截断保护）
        if self._vectors is not None and len(self._vectors) != len(self._entries):
            n = min(len(self._vectors), len(self._entries))
            print(f"[本地记忆] 警告：向量数({len(self._vectors)})与条目数({len(self._entries)})不一致，截断对齐到{n}")
            self._vectors = self._vectors[:n]
            self._entries = self._entries[:n]
            self._ids = {e["unique_id"] for e in self._entries}
        # 模型哈希校验（防换模型后旧向量静默不兼容）
        meta = {}
        if os.path.exists(_META_FILE):
            try:
                meta = json.load(open(_META_FILE, encoding="utf-8"))
            except Exception:
                meta = {}
        if meta.get("model") and meta["model"] != _MODEL_NAME and self._entries:
            print(f"[本地记忆] 警告：向量由 {meta['model']} 生成，当前配置 {_MODEL_NAME}，"
                  f"建议运行迁移脚本重建，否则检索质量会劣化")
        print(f"[本地记忆] 已加载 {len(self._entries)} 条记忆，模型={_MODEL_NAME}")

    def _save_meta(self):
        with open(_META_FILE, "w", encoding="utf-8") as f:
            json.dump({"model": _MODEL_NAME, "count": len(self._entries), "updated": time.time()}, f)

    def _flush_locked(self):
        """落盘（调用方须持有锁）"""
        with open(_VECTORS_FILE, "wb") as f:
            np.save(f, self._vectors)
        self._save_meta()
        self._dirty_count = 0

    # ---------- 模型 ----------
    def _load_model(self):
        if self._model is not None or self._model_error:
            return self._model
        # RLock可重入：add_memory持锁调用_encode→本方法时同线程直接进入
        with self._lock:
            if self._model is not None or self._model_error:
                return self._model
            try:
                t0 = time.time()
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(_MODEL_NAME, device="cpu")
                print(f"[本地记忆] 模型加载完成: {_MODEL_NAME} ({time.time()-t0:.1f}s)")
            except Exception as e:
                self._model_error = str(e)
                print(f"[本地记忆] 模型加载失败，读写将不可用: {str(e)[:120]}")
            return self._model

    def _encode(self, texts):
        """单条或批量编码，返回归一化向量 (N, D)"""
        model = self._load_model()
        if model is None:
            return None
        if isinstance(texts, str):
            texts = [texts]
        vecs = []
        for i in range(0, len(texts), _ENCODE_BATCH):
            batch = texts[i:i + _ENCODE_BATCH]
            v = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
            vecs.append(np.asarray(v, dtype=np.float32))
        return np.vstack(vecs)

    # ---------- 写入 ----------
    def add_memory(self, user_id, content, category, meta=None, unique_id=None):
        """同步写入一条记忆（去重+向量+落盘）。返回 True=新增 / False=重复或失败"""
        if not content or not str(content).strip():
            return False
        if unique_id is None:
            hash_input = f"{user_id}_{category}_{content[:500]}"
            unique_id = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:16]
        with self._lock:
            if unique_id in self._ids:
                return False
            vec = self._encode(content)
            if vec is None:
                return False
            entry = {"unique_id": unique_id, "user_id": user_id,
                     "content": str(content).strip(), "category": category,
                     "meta": meta or {}}
            self._entries.append(entry)
            self._ids.add(unique_id)
            if self._vectors is None:
                self._vectors = vec
            else:
                self._vectors = np.vstack([self._vectors, vec])
            # jsonl 追加
            with open(_ENTRIES_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._dirty_count += 1
            if self._dirty_count >= _SAVE_EVERY:
                self._flush_locked()
            return True

    def add_many(self, items):
        """批量写入（迁移用）：[{user_id, content, category, meta, unique_id}]，分批encode，返回新增数"""
        with self._lock:
            new_items = [it for it in items
                         if it.get("unique_id") and it["unique_id"] not in self._ids
                         and it.get("content") and str(it["content"]).strip()]
        if not new_items:
            return 0
        texts = [str(it["content"]).strip() for it in new_items]
        vecs = self._encode(texts)
        if vecs is None:
            return 0
        with self._lock:
            # 锁内二次去重（可能被并发写入抢先）
            pending = [(it, v) for it, v in zip(new_items, vecs)
                       if it["unique_id"] not in self._ids]
            if not pending:
                return 0
            with open(_ENTRIES_FILE, "a", encoding="utf-8") as f:
                for it, v in pending:
                    entry = {"unique_id": it["unique_id"], "user_id": it["user_id"],
                             "content": str(it["content"]).strip(), "category": it["category"],
                             "meta": it.get("meta") or {}}
                    self._entries.append(entry)
                    self._ids.add(it["unique_id"])
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            mat = np.vstack([v.reshape(1, -1) for _, v in pending])
            self._vectors = mat if self._vectors is None else np.vstack([self._vectors, mat])
            self._flush_locked()
            return len(pending)

    def flush(self):
        with self._lock:
            if self._dirty_count > 0:
                self._flush_locked()

    # ---------- 检索 ----------
    def search(self, user_id, query, top_k=4, min_score=0.45, category_filter=None):
        """语义检索，返回 (文本, 节点列表)——文本格式与云端 get_relevant_history 一致"""
        if not query or not str(query).strip():
            return "", []
        with self._lock:
            candidates = []
            for i, e in enumerate(self._entries):
                if user_id and e["user_id"] != user_id:
                    continue
                if category_filter and e["category"] not in category_filter:
                    continue
                candidates.append(i)
            if not candidates or self._vectors is None:
                return "", []
            sub_matrix = self._vectors[candidates]  # (n, D) 复制（锁内快照）

        qv = self._encode(str(query)[:100])
        if qv is None:
            return "", []
        sims = sub_matrix @ qv.T  # (n, 1)
        sims = sims[:, 0]
        order = np.argsort(-sims)

        nodes = []
        for idx in order[:top_k]:
            score = float(sims[idx])
            if score < min_score:
                break
            e = self._entries[candidates[idx]]
            nodes.append({"content": e["content"], "category": e["category"],
                          "meta_data": {"category": e["category"], **(e.get("meta") or {})},
                          "score": score})
        if not nodes:
            return "", []

        lines = ["【相关历史线索】（语义匹配过往伏笔、传闻、任务记录）"]
        for i, node in enumerate(nodes, 1):
            _sc = node["score"]
            _sc_str = f"score={_sc:.3f} " if isinstance(_sc, (int, float)) else ""
            # 多行内容（章节摘要=标题+正文）压成单行，避免下游按行解析时标题/正文被拆成两条
            _flat = re.sub(r'\s+', ' ', node['content'].strip())
            print(f"[本地记忆] {_sc_str}[{node['category']}] {_flat[:40]}")
            lines.append(f"{i}. [{node['category']}] {_flat}")
        return "\n".join(lines), nodes

    def status(self):
        cats = {}
        for e in self._entries:
            cats[e["category"]] = cats.get(e["category"], 0) + 1
        return {
            "available": self._model is not None or self._model_error is None,
            "model_ready": self._model is not None,
            "model_loading": self._model is None and self._model_error is None,
            "model": _MODEL_NAME,
            "model_error": self._model_error,
            "count": len(self._entries),
            "categories": cats,
        }


_store = _LocalStore()


def _warmup_model():
    # 延迟启动：避开进程启动即退出的短命脚本（daemon线程中途加载torch会在解释器关闭时崩溃）
    time.sleep(1)
    try:
        _store._load_model()
    except Exception:
        pass


threading.Thread(target=_warmup_model, daemon=True).start()


# ========== 对外写入接口（签名/内容加工/unique_id 规则与 cloud_memory_v2 完全一致） ==========
def _bg_add(user_id, content, category, meta, unique_id):
    threading.Thread(target=_store.add_memory,
                     args=(user_id, content, category, meta, unique_id), daemon=True).start()


def upload_plot_memory(user_id, round_num, plot_content, user_action, novel_node=""):
    import re
    clean_action = re.sub(r'【[^】]+】', '', user_action).strip()
    short_plot = re.sub(r'【[^】]+】', '', plot_content[:200]).strip()
    content = f"{novel_node}，{clean_action}。{short_plot}" if novel_node else f"{clean_action}。{short_plot}"
    _bg_add(user_id, content, MemoryCategory.PLOT_ROUND, {"round": round_num},
            f"{user_id}_PLOT_ROUND_{round_num}")


def upload_foreshadowing(user_id, arc_text):
    content = f"【未解决伏笔】{arc_text}"
    hash_str = hashlib.md5(arc_text.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, content, MemoryCategory.FORESHADOW, None,
            f"{user_id}_FORESHADOW_{hash_str}")


def upload_rumor_snapshot(user_id, rumor_content, round_num=0):
    meta = {"round": round_num} if round_num else None
    hash_str = hashlib.md5(rumor_content.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, rumor_content, MemoryCategory.RUMOR, meta,
            f"{user_id}_RUMOR_SNAPSHOT_{hash_str}")


def upload_task_node(user_id, task_content):
    hash_str = hashlib.md5(task_content.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, task_content, MemoryCategory.TASK, None,
            f"{user_id}_TASK_NODE_{hash_str}")


def upload_milestone(user_id, milestone_text, category=MemoryCategory.LEGACY_MILESTONE):
    hash_str = hashlib.md5(milestone_text.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, milestone_text, category, None,
            f"{user_id}_MILESTONE_{hash_str}")


def upload_chapter_summary(user_id, chapter_id, round_range, summary):
    _bg_add(user_id, summary, MemoryCategory.CHAPTER, {"chapter_id": chapter_id},
            f"{user_id}_CHAPTER_{chapter_id}")


def upload_biography_update(user_id, bio_content):
    content = f"人物状态更新：{bio_content[:300]}"
    _bg_add(user_id, content, MemoryCategory.BIOGRAPHY, None,
            f"{user_id}_BIOGRAPHY_{int(time.time())}")


def upload_important_memory(user_id, round_num, content, score):
    full_content = f"【重要剧情 score={score}】第{round_num}轮：{content[:200]}"
    _bg_add(user_id, full_content, MemoryCategory.HIGH_IMPORTANCE, None,
            f"{user_id}_HIGH_IMPORTANCE_{round_num}")


def upload_npc_memory(user_id, npc_name, memory_text, novel_node=""):
    if novel_node:
        content = f"【{npc_name}的记忆】{novel_node}，{memory_text[:200]}"
    else:
        content = f"【{npc_name}的记忆】{memory_text[:200]}"
    hash_str = hashlib.md5(memory_text.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, content, MemoryCategory.NPC_MEMORY, None,
            f"{user_id}_NPC_MEMORY_{npc_name}_{hash_str}")


def upload_task_memory(user_id, task_name, stage_hist, summary, novel_node=""):
    if novel_node:
        content = f"【任务】{task_name}：{novel_node}，{summary[:300]}"
    else:
        content = f"【任务】{task_name}：{summary[:300]}"
    hash_input = f"{task_name}_{summary[:100]}"
    hash_str = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, content, MemoryCategory.TASK, None,
            f"{user_id}_TASK_MEMORY_{hash_str}")


def upload_rumor_item(user_id, rumor_text, novel_node=""):
    if not rumor_text or rumor_text.strip() in ("无", "（无）", "(无)"):
        return
    rumor_text = rumor_text.strip()
    if novel_node:
        content = f"【近期剧情记录】{novel_node}，{rumor_text[:200]}"
    else:
        content = f"【近期剧情记录】{rumor_text[:200]}"
    hash_str = hashlib.md5(f"{novel_node}_{rumor_text}".encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, content, MemoryCategory.RUMOR, None,
            f"{user_id}_RUMOR_ITEM_{hash_str}")


# ========== 检索接口（签名/返回格式与 cloud_memory_v2.get_relevant_history 一致） ==========
def get_relevant_history(user_id, query, top_k=4, min_score=0.55, category_filter=None):
    """语义召回历史记忆（本地版）。返回格式化文本，失败/无结果返回空字符串"""
    try:
        text, _nodes = _store.search(user_id, query, top_k, min_score, category_filter)
        return text
    except Exception as e:
        print(f"[本地记忆] 检索失败: {str(e)[:80]}")
        return ""


def get_status():
    return _store.status()


def flush():
    _store.flush()
