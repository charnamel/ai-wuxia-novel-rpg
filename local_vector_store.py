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
【非阻塞铁律】模型加载（30-60秒）只持有模型锁；检索路径模型未就绪立即返回空，
       绝不等待——否则请求线程阻塞超时，gunicorn 杀 worker → 新worker重载模型
       → 再阻塞 → 死循环（表现为"游戏卡住必须刷新"）。
【自愈】预热线程失败自动重试（默认10次×15秒），服务器重启瞬间的内存竞争等
       一过性故障无需人工干预。
【跨平台】服务器（Linux/gunicorn）零额外依赖：colorama 护栏仅 Windows 本地
       开发启用；下载进度条已全局禁用，从源头消除 tqdm/colorama 光标码崩溃。
"""

import os
import re
import json
import sys
import time
import hashlib
import threading

import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 下载进度条在 gunicorn/journald 等无终端环境下无意义，且是 tqdm/colorama
# 光标码崩溃的唯一触发源——加载模型前直接禁用（平台无关的根治方案）
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

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
        self._lock = threading.RLock()       # 数据锁：只保护内存结构（毫秒级操作，绝不在持锁期间加载模型/编码）
        self._model_lock = threading.Lock()  # 模型锁：只保护模型加载（30-60秒，期间读写照常进行）
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
        """加载模型（阻塞，服务器上约30-60秒）。只持有模型锁——加载期间检索/写入完全不受影响。
        调用方：后台预热线程 / 写入线程 / 重建接口。检索路径绝不调用本方法（防请求超时拖死worker）。
        失败缓存于 _model_error：由预热线程清除后自动重试（一过性故障自愈）。"""
        if self._model is not None or self._model_error:
            return self._model
        with self._model_lock:
            if self._model is not None or self._model_error:
                return self._model
            try:
                t0 = time.time()
                # colorama 护栏仅用于 Windows 本地开发环境；Linux 服务器不执行此分支，
                # 也不需要部署 win_console_guard.py（进度条已由环境变量全局禁用）
                if sys.platform == "win32":
                    try:
                        from win_console_guard import ensure_safe_console
                        ensure_safe_console()
                    except Exception:
                        pass
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(_MODEL_NAME, device="cpu")
                self._model_error = None
                print(f"[本地记忆] 模型加载完成: {_MODEL_NAME} ({time.time()-t0:.1f}s)")
            except Exception as e:
                self._model_error = str(e)
                print(f"[本地记忆] 模型加载失败: {str(e)[:120]}")
            return self._model

    def _encode(self, texts):
        """单条或批量编码，返回归一化向量 (N, D)。不触发模型加载——未就绪直接返回 None"""
        model = self._model
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
        """写入一条记忆（去重+向量+落盘）。调用方为后台线程，可阻塞等待模型加载。
        返回 True=新增 / False=重复或模型不可用"""
        if not content or not str(content).strip():
            return False
        if unique_id is None:
            hash_input = f"{user_id}_{category}_{content[:500]}"
            unique_id = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:16]
        with self._lock:
            if unique_id in self._ids:
                return False
        # 写入线程可等模型（模型锁与数据锁分离，等模型不挡检索）
        self._load_model()
        vec = self._encode(content)  # 锁外编码（数十毫秒）
        if vec is None:
            return False
        with self._lock:
            if unique_id in self._ids:  # 锁内二次查重（等待期间可能被并发写入抢先）
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
        if self._load_model() is None:
            return 0
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
        """语义检索，返回 (文本, 节点列表)——文本格式与云端 get_relevant_history 一致。
        【铁律】模型未就绪立即返回空：绝不等待、绝不触发模型加载。
        否则请求线程会阻塞30-60秒 → gunicorn WORKER TIMEOUT → worker被杀 → 死循环。"""
        if not query or not str(query).strip():
            return "", []
        if self._model is None or self._vectors is None:
            return "", []  # 模型还在加载/失败：本轮跳过记忆召回，游戏照常进行
        with self._lock:
            cand = [(e, i) for i, e in enumerate(self._entries)
                    if (not user_id or e["user_id"] == user_id)
                    and (not category_filter or e["category"] in category_filter)]
            if not cand:
                return "", []
            sub_matrix = self._vectors[[i for _, i in cand]]  # (n, D) 快照
            entries_snapshot = [e for e, _ in cand]  # 条目一并快照（防重建期间被整体替换）

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
            e = entries_snapshot[idx]
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

_WARMUP_MAX_RETRY = 10      # 自动重试上限（覆盖服务器重启后约5-10分钟的自愈窗口）
_WARMUP_RETRY_INTERVAL = 15  # 重试间隔（秒）


def _warmup_model():
    """后台预热：加载模型；失败自动重试（服务器重启瞬间的内存竞争等一过性故障可自愈，
    无需手动重启/点重建）。重试期间清除错误标记——状态栏显示"加载中"而非"不可用"。"""
    # 延迟启动：避开进程启动即退出的短命脚本（daemon线程中途加载torch会在解释器关闭时崩溃）
    time.sleep(1)
    retries = 0
    while _store._model is None:
        try:
            if _store._load_model() is not None:
                return
        except Exception:
            pass
        retries += 1
        if retries >= _WARMUP_MAX_RETRY:
            print(f"[本地记忆] 模型预热失败（已重试{retries}次），读写暂不可用，"
                  f"可点击状态栏'重建'按钮恢复。最后原因: {str(_store._model_error)[:100]}")
            return
        _store._model_error = None  # 一过性失败：清除标记稍后重试，期间对外显示"加载中"
        time.sleep(_WARMUP_RETRY_INTERVAL)


threading.Thread(target=_warmup_model, daemon=True).start()


# ========== 对外写入接口（签名/内容加工/unique_id 规则与 cloud_memory_v2 完全一致） ==========
def _bg_add(user_id, content, category, meta, unique_id):
    threading.Thread(target=_store.add_memory,
                     args=(user_id, content, category, meta, unique_id), daemon=True).start()


# ---------- novel_node 时间前缀规范化 ----------
_SEASON_ALIAS = {
    "春": "春", "春季": "春", "春天": "春", "早春": "春", "初春": "春",
    "仲春": "春", "暮春": "春", "晚春": "春", "深春": "春", "孟春": "春",
    "夏": "夏", "夏季": "夏", "夏天": "夏", "初夏": "夏", "仲夏": "夏",
    "盛夏": "夏", "暮夏": "夏", "晚夏": "夏", "孟夏": "夏",
    "秋": "秋", "秋季": "秋", "秋天": "秋", "早秋": "秋", "初秋": "秋",
    "仲秋": "秋", "暮秋": "秋", "晚秋": "秋", "深秋": "秋", "孟秋": "秋",
    "冬": "冬", "冬季": "冬", "冬天": "冬", "初冬": "冬", "仲冬": "冬",
    "暮冬": "冬", "晚冬": "冬", "深冬": "冬", "孟冬": "冬",
}

def normalize_time_prefix(novel_node: str) -> str:
    """从 novel_node 中仅提取 'YYYY年X'(X=春/夏/秋/冬) 时间前缀，丢弃后续剧情文字。

    兼容 1755年春/春季/春天/深春/早春 等各种季节修饰写法；无法识别返回空串。
    """
    if not novel_node:
        return ""
    m = re.search(r"(\d{1,4})\s*年\s*([\u4e00-\u9fa5]{0,4}?[春夏秋冬])", novel_node)
    if not m:
        return ""
    year = m.group(1)
    season = _SEASON_ALIAS.get(m.group(2), "")
    return f"{year}年{season}" if season else ""

def upload_plot_memory(user_id, round_num, plot_content, user_action, novel_node=""):
    clean_action = re.sub(r'【[^】]+】', '', user_action).strip()
    short_plot = re.sub(r'【[^】]+】', '', plot_content[:200]).strip()
    time_prefix = normalize_time_prefix(novel_node)
    content = f"{time_prefix}，{clean_action}。{short_plot}" if time_prefix else f"{clean_action}。{short_plot}"
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
    time_prefix = normalize_time_prefix(novel_node)
    content = f"【{npc_name}的记忆】{time_prefix}，{memory_text[:200]}" if time_prefix else f"【{npc_name}的记忆】{memory_text[:200]}"
    hash_str = hashlib.md5(memory_text.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, content, MemoryCategory.NPC_MEMORY, None,
            f"{user_id}_NPC_MEMORY_{npc_name}_{hash_str}")


def upload_task_memory(user_id, task_name, stage_hist, summary, novel_node=""):
    time_prefix = normalize_time_prefix(novel_node)
    content = f"【任务】{task_name}：{time_prefix}，{summary[:300]}" if time_prefix else f"【任务】{task_name}：{summary[:300]}"
    hash_input = f"{task_name}_{summary[:100]}"
    hash_str = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:8]
    _bg_add(user_id, content, MemoryCategory.TASK, None,
            f"{user_id}_TASK_MEMORY_{hash_str}")


def upload_rumor_item(user_id, rumor_text, novel_node=""):
    if not rumor_text or rumor_text.strip() in ("无", "（无）", "(无)"):
        return
    rumor_text = rumor_text.strip()
    time_prefix = normalize_time_prefix(novel_node)
    content = f"【近期剧情记录】{time_prefix}，{rumor_text[:200]}" if time_prefix else f"【近期剧情记录】{rumor_text[:200]}"
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


def rebuild_vectors():
    """全量重编码向量（后台调用，线程安全）。
    修复三类问题：①非优雅重启导致的向量数<条目数（磁盘上的孤儿条目一并救回）
                 ②更换模型后旧向量不兼容
                 ③启动时模型加载瞬时失败（如重启瞬间内存竞争）——_load_model 见错误即返回
                   会让失败永久固化，这里清除后强制重试一次
    编码在锁外进行（约60-120秒，不阻塞游戏写入），完成后锁内原子替换并落盘。
    返回重建后的条目总数。
    """
    # 自愈：清除历史加载失败记录并重试（仍失败则带出真实原因，而非笼统的"模型不可用"）
    if _store._model is None:
        _store._model_error = None
        if _store._load_model() is None:
            raise RuntimeError(f"模型重试加载仍失败: {(_store._model_error or '未知原因')[:150]}")
    # 1. 锁外读磁盘全量条目（含孤儿行；同 unique_id 后写的覆盖先写的）
    disk_entries = {}
    if os.path.exists(_ENTRIES_FILE):
        with open(_ENTRIES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    disk_entries[e["unique_id"]] = e
                except (json.JSONDecodeError, KeyError):
                    continue
    if not disk_entries:
        return 0
    entries = list(disk_entries.values())
    disk_ids = set(disk_entries.keys())
    # 2. 锁外全量重编码
    vecs = _store._encode([e["content"] for e in entries])
    if vecs is None:
        raise RuntimeError("模型不可用，无法重编码")
    # 3. 锁内合并：编码期间新增的条目（在内存但不在磁盘快照）追加编码后原子替换
    with _store._lock:
        extra = [e for e in _store._entries if e["unique_id"] not in disk_ids]
        if extra:
            extra_vecs = _store._encode([e["content"] for e in extra])
            if extra_vecs is not None:
                vecs = np.vstack([vecs, extra_vecs])
                entries = entries + extra
        _store._entries = entries
        _store._ids = {e["unique_id"] for e in entries}
        _store._vectors = vecs
        _store._dirty_count = 0
        # 重写条目文件（清掉历史重复行/孤儿行，保证磁盘条目数=向量数，重启不再告警）
        with open(_ENTRIES_FILE, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        _store._flush_locked()
    return len(entries)


# 优雅退出时强制落盘（systemctl restart 发 SIGTERM 可触发；防重启丢尾部向量）
import atexit as _atexit
_atexit.register(_store.flush)
