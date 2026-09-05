import os
import time
import json
import hashlib
import threading
import re
from collections import OrderedDict
from typing import Optional
import requests

# ========== 1. 配置加载 ==========
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
PLOT_MEMORY_ID = os.getenv("BAILIAN_PLOT_MEMORY_ID", "")
ENABLE_CLOUD_MEMORY = os.getenv("ENABLE_CLOUD_MEMORY", "true").lower() == "true"

# 官方接口地址
API_BASE = "https://dashscope.aliyuncs.com/api/v2/apps/memory"
ADD_URL = f"{API_BASE}/add"
SEARCH_URL = f"{API_BASE}/memory_nodes/search"

# ========== 2. LRU缓存配置 ==========
class ThreadSafeLRUCache:
    """线程安全的LRU缓存，支持TTL过期"""
    
    def __init__(self, max_size: int = 100, ttl_seconds: int = 1800):
        self._cache = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
    
    def get(self, key: str):
        """获取缓存值，过期则返回None"""
        with self._lock:
            if key not in self._cache:
                return None
            timestamp, value = self._cache[key]
            # 检查TTL
            if time.time() - timestamp > self._ttl:
                del self._cache[key]
                return None
            # 更新访问顺序（LRU）
            self._cache.move_to_end(key)
            return value
    
    def put(self, key: str, value):
        """设置缓存值"""
        with self._lock:
            # 移除过期项（在添加新项前清理）
            self._clean_expired()
            
            # 如果已满，移除最久未访问的
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            
            self._cache[key] = (time.time(), value)
            self._cache.move_to_end(key)
    
    def _clean_expired(self):
        """清理过期项（最多扫描10个）"""
        expired_keys = []
        for key, (timestamp, _) in list(self._cache.items())[:10]:
            if time.time() - timestamp > self._ttl:
                expired_keys.append(key)
        for key in expired_keys:
            del self._cache[key]
    
    def size(self) -> int:
        """返回当前缓存条目数"""
        with self._lock:
            return len(self._cache)
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()

# 全局检索缓存（LRU，最大100条，30分钟TTL）
_search_cache = ThreadSafeLRUCache(max_size=100, ttl_seconds=1800)

_module_available = False

# 预检查
if ENABLE_CLOUD_MEMORY and DASHSCOPE_API_KEY and PLOT_MEMORY_ID:
    _module_available = True
    print("[云记忆] 初始化成功，已连接阿里云百炼长期记忆库")
else:
    _module_available = False
    print("[云记忆] 配置不完整，将使用本地记忆模式")

# ========== 3. 上传去重机制 ==========
class UploadDeduplicator:
    """上传去重管理器，记录已上传的唯一ID"""
    
    def __init__(self, cache_file: str = "data/cloud_memory_uploaded.json"):
        self._cache_file = cache_file
        self._uploaded_ids = set()
        self._lock = threading.RLock()
        self._load_cache()
    
    def _load_cache(self):
        """从文件加载已上传ID"""
        try:
            if os.path.exists(self._cache_file):
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self._uploaded_ids = set(data)
        except Exception as e:
            print(f"[云记忆] 加载上传缓存失败: {e}")
            self._uploaded_ids = set()
    
    def _save_cache(self):
        """保存已上传ID到文件"""
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(self._cache_file), exist_ok=True)
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(list(self._uploaded_ids), f, ensure_ascii=False)
        except Exception as e:
            print(f"[云记忆] 保存上传缓存失败: {e}")
    
    def is_uploaded(self, unique_id: str) -> bool:
        """检查ID是否已上传"""
        with self._lock:
            return unique_id in self._uploaded_ids
    
    def mark_uploaded(self, unique_id: str):
        """标记ID为已上传"""
        with self._lock:
            if unique_id not in self._uploaded_ids:
                self._uploaded_ids.add(unique_id)
                # 定期保存（每100条或超过5分钟）
                if len(self._uploaded_ids) % 100 == 0:
                    self._save_cache()
    
    def save(self):
        """手动触发保存"""
        self._save_cache()
    
    def clear(self):
        """清空去重缓存"""
        with self._lock:
            self._uploaded_ids.clear()
            self._save_cache()

# 全局去重管理器
_upload_deduplicator = UploadDeduplicator()

# ========== 4. L4 业务分类常量 ==========
class MemoryCategory:
    # 核心四类 L4 记忆
    FORESHADOW = "未解决伏笔"
    RUMOR = "江湖见闻"
    TASK = "任务记录"
    PLOT_ROUND = "单轮剧情"
    # 兼容旧分类
    LEGACY_MILESTONE = "大事记"
    CHAPTER = "章节摘要"
    BIOGRAPHY = "人物传记"
    HIGH_IMPORTANCE = "memory_highlight"  # LLM评分高分剧情
    NPC_MEMORY = "npc_memory"             # NPC个人记忆
    

# ========== 7. 内部工具：缓存 + 请求头 ==========
def _get_headers():
    return {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }

def _get_cache(key: str):
    """获取缓存值，使用 ThreadSafeLRUCache 的 get 方法（自动处理过期）"""
    return _search_cache.get(key)

def _set_cache(key: str, content: str):
    """设置缓存值，使用 ThreadSafeLRUCache 的 put 方法（自动处理容量限制）"""
    _search_cache.put(key, content)

# ========== 5. 核心：通用记忆写入（带去重） ==========
def _sync_add_memory(user_id: str, content: str, category: str = "通用", meta: dict = None, unique_id: Optional[str] = None):
    """
    同步写入函数，后台线程调用；使用custom_content直存，不经过AI提取
    :param unique_id: 唯一标识，用于去重，不传则基于内容生成
    """
    if not _module_available:
        return
    
    # 生成唯一ID用于去重
    if unique_id is None:
        # 基于 user_id + category + content 生成哈希
        hash_input = f"{user_id}_{category}_{content[:500]}"
        unique_id = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:16]
    
    # 去重检查
    if _upload_deduplicator.is_uploaded(unique_id):
        print(f"[云记忆] 跳过重复上传[{category}]：{unique_id[:8]}...")
        return
    
    try:
        meta_data = {"category": category}
        if meta:
            meta_data.update(meta)
        
        payload = {
            "user_id": user_id,
            "custom_content": content,
            "meta_data": meta_data
        }
        
        resp = requests.post(
            ADD_URL,
            headers=_get_headers(),
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()
        
        # 标记为已上传
        _upload_deduplicator.mark_uploaded(unique_id)
        
        # 打印日志方便调试
        # print(f"[云记忆] 写入成功，新增{len(result.get('memory_nodes', []))}个节点 [{unique_id[:8]}]")
        
    except Exception as e:
        print(f"[云记忆] 写入失败[{category}]：{str(e)[:80]}")

# ========== 6. 对外写入接口（带唯一ID去重） ==========
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

def upload_plot_memory(user_id: str, round_num: int, plot_content: str, user_action: str, novel_node: str = ""):
    """单轮剧情上传——纯原文，去所有标签"""
    if not _module_available:
        return
    clean_action = re.sub(r'【[^】]+】', '', user_action).strip()
    short_plot = re.sub(r'【[^】]+】', '', plot_content[:200]).strip()
    time_prefix = normalize_time_prefix(novel_node)
    if time_prefix:
        content = f"{time_prefix}，{clean_action}。{short_plot}"
    else:
        content = f"{clean_action}。{short_plot}"
    # 生成唯一ID: {user_id}_PLOT_ROUND_{round_num}
    unique_id = f"{user_id}_PLOT_ROUND_{round_num}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.PLOT_ROUND, {"round": round_num}, unique_id),
        daemon=True
    ).start()

def upload_foreshadowing(user_id: str, arc_text: str):
    """上传未解决伏笔节点（L4 专用）"""
    if not _module_available:
        return
    content = f"【未解决伏笔】{arc_text}"
    # 生成唯一ID: {user_id}_FORESHADOW_{hash(arc_text)}
    hash_str = hashlib.md5(arc_text.encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_FORESHADOW_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.FORESHADOW, None, unique_id),
        daemon=True
    ).start()

def upload_rumor_snapshot(user_id: str, rumor_content: str, round_num: int = 0):
    """上传江湖见闻/环境快照节点（L4 专用）"""
    if not _module_available:
        return
    meta = {"round": round_num} if round_num > 0 else None
    # 生成唯一ID: {user_id}_RUMOR_{round_num}_{hash(content)}
    hash_str = hashlib.md5(rumor_content.encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_RUMOR_{round_num}_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, rumor_content, MemoryCategory.RUMOR, meta, unique_id),
        daemon=True
    ).start()

def upload_task_node(user_id: str, task_content: str):
    """上传任务记录节点（L4 专用）"""
    if not _module_available:
        return
    # 生成唯一ID: {user_id}_TASK_{hash(content)}
    hash_str = hashlib.md5(task_content.encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_TASK_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, task_content, MemoryCategory.TASK, None, unique_id),
        daemon=True
    ).start()

def upload_milestone(user_id: str, milestone_text: str, category: str = MemoryCategory.LEGACY_MILESTONE):
    """通用里程碑上传（兼容旧调用，可指定分类）"""
    if not _module_available:
        return
    # 生成唯一ID: {user_id}_MILESTONE_{hash(text)}
    hash_str = hashlib.md5(milestone_text.encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_MILESTONE_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, milestone_text, category, None, unique_id),
        daemon=True
    ).start()

# 保留原有章节、传记上传函数，分类不变
def upload_chapter_summary(user_id: str, chapter_id: int, round_range: str, summary: str):
    if not _module_available:
        return
    content = summary  # 全文上传
    # 生成唯一ID: {user_id}_CHAPTER_{chapter_id}
    unique_id = f"{user_id}_CHAPTER_{chapter_id}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.CHAPTER, {"chapter_id": chapter_id}, unique_id),
        daemon=True
    ).start()

def upload_biography_update(user_id: str, bio_content: str):
    if not _module_available:
        return
    content = f"人物状态更新：{bio_content[:300]}"
    # 生成唯一ID: {user_id}_BIOGRAPHY_{timestamp}
    unique_id = f"{user_id}_BIOGRAPHY_{int(time.time())}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.BIOGRAPHY, None, unique_id),
        daemon=True
    ).start()

def upload_important_memory(user_id: str, round_num: int, content: str, score: int):
    """上传LLM评分的高分剧情到向量库"""
    if not _module_available:
        return
    full_content = f"【重要剧情 score={score}】第{round_num}轮：{content[:200]}"
    # 生成唯一ID: {user_id}_HIGH_IMPORTANCE_{round_num}
    unique_id = f"{user_id}_HIGH_IMPORTANCE_{round_num}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, full_content, MemoryCategory.HIGH_IMPORTANCE, None, unique_id),
        daemon=True
    ).start()

def upload_npc_memory(user_id: str, npc_name: str, memory_text: str, novel_node: str = ""):
    """上传NPC个人记忆到向量库"""
    if not _module_available:
        return
    time_prefix = normalize_time_prefix(novel_node)
    if time_prefix:
        content = f"【{npc_name}的记忆】{time_prefix}，{memory_text[:200]}"
    else:
        content = f"【{npc_name}的记忆】{memory_text[:200]}"
    # 生成唯一ID: {user_id}_NPC_MEMORY_{npc_name}_{hash(text)}
    hash_str = hashlib.md5(memory_text.encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_NPC_MEMORY_{npc_name}_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.NPC_MEMORY, None, unique_id),
        daemon=True
    ).start()

def upload_task_memory(user_id: str, task_name: str, stage_hist: str, summary: str, novel_node: str = ""):
    """上传任务完成总结到向量库"""
    if not _module_available:
        return
    time_prefix = normalize_time_prefix(novel_node)
    if time_prefix:
        content = f"【任务】{task_name}：{time_prefix}，{summary[:300]}"
    else:
        content = f"【任务】{task_name}：{summary[:300]}"
    # 生成唯一ID: {user_id}_TASK_MEMORY_{hash(task_name+summary)}
    hash_input = f"{task_name}_{summary[:100]}"
    hash_str = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_TASK_MEMORY_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.TASK, None, unique_id),
        daemon=True
    ).start()

def upload_rumor_item(user_id: str, rumor_text: str, novel_node: str = ""):
    """上传单条玩家剧情记录到向量库，带 novel_node 时间戳"""
    if not _module_available:
        return
    if not rumor_text or rumor_text.strip() in ("无", "（无）", "(无)"):
        return
    rumor_text = rumor_text.strip()
    time_prefix = normalize_time_prefix(novel_node)
    if time_prefix:
        content = f"【近期剧情记录】{time_prefix}，{rumor_text[:200]}"
    else:
        content = f"【近期剧情记录】{rumor_text[:200]}"
    hash_str = hashlib.md5(f"{novel_node}_{rumor_text}".encode('utf-8')).hexdigest()[:8]
    unique_id = f"{user_id}_RUMOR_ITEM_{hash_str}"
    threading.Thread(
        target=_sync_add_memory,
        args=(user_id, content, MemoryCategory.RUMOR, None, unique_id),
        daemon=True
    ).start()

# ========== 8. 记忆检索（支持分类过滤，对齐 L4 展示格式） ==========
def get_relevant_history(
    user_id: str,
    query: str,
    top_k: int = 4,
    min_score: float = 0.55,
    category_filter: list = None
) -> str:
    """
    语义召回历史记忆
    :param category_filter: 可选，指定召回的分类列表，如 [MemoryCategory.FORESHADOW, MemoryCategory.RUMOR]
    不传则默认召回所有分类
    返回格式化文本，可直接拼入 Prompt；失败返回空字符串自动降级
    """
    if not _module_available:
        return ""
    
    cache_key = f"{user_id}:{query}:{top_k}:{min_score}:{str(category_filter)}"
    cached = _get_cache(cache_key)
    if cached:
        return cached
    
    try:
        payload = {
            "user_id": user_id,
            "messages": [{"role": "user", "content": query}],
            "top_k": top_k * 2,  # 多召回一倍，用于本地分类过滤
            "min_score": min_score
        }
        
        resp = requests.post(
            SEARCH_URL,
            headers=_get_headers(),
            json=payload,
            timeout=10
        )
        resp.raise_for_status()
        result = resp.json()
        memory_nodes = result.get("memory_nodes", [])
        
        # 本地分类过滤
        if category_filter and memory_nodes:
            filtered = []
            for node in memory_nodes:
                meta = node.get("meta_data", {})
                cat = meta.get("category", "")
                if cat in category_filter:
                    filtered.append(node)
            memory_nodes = filtered
        else:
            memory_nodes = list(memory_nodes)

        # 按 score 降序排序，取最高 top_k 条（云端不返回score时保持云端相似度原序）
        _has_score = bool(memory_nodes) and "score" in memory_nodes[0]
        if memory_nodes and not _has_score and not globals().get("_score_warned"):
            globals()["_score_warned"] = True
            print("[云记忆] 提示：百炼返回节点无score字段，按云端相似度原序截断（此提示仅显示一次）")
        if _has_score:
            memory_nodes.sort(key=lambda n: n.get("score", 0), reverse=True)
        memory_nodes = memory_nodes[:top_k]

        # score 召回日志（阈值校准用）
        for node in memory_nodes:
            _sc = node.get("score")
            _ct = node.get("content", "").strip()[:40]
            _cat = node.get("meta_data", {}).get("category", "")
            _sc_str = f"score={_sc:.3f} " if isinstance(_sc, (int, float)) else ""
            print(f"[云记忆] {_sc_str}[{_cat}] {_ct}")
        
        if not memory_nodes:
            result_text = ""
        else:
            # 返回格式对齐新 L4：保留每条的分类属性，AI 更容易识别
            lines = ["【相关历史线索】（语义匹配过往伏笔、传闻、任务记录）"]
            for idx, node in enumerate(memory_nodes, 1):
                content = node.get("content", "").strip()
                cat = node.get("meta_data", {}).get("category", "历史记录")
                lines.append(f"{idx}. [{cat}] {content}")
            result_text = "\n".join(lines)
        
        _set_cache(cache_key, result_text)
        return result_text
    
    except Exception as e:
        print(f"[云记忆] 检索失败，将仅使用本地上下文：{str(e)[:60]}")
        return ""

# ========== 9. 轻量化上下文构建（不变） ==========
def build_compact_context(
    user_id: str,
    user_query: str,
    recent_context: str,
    player_state: str,
    world_basic: str
) -> str:
    base_context = f"""
【主角当前状态】{player_state}
【近期详细剧情】（最近10轮）
{recent_context}
"""
    
    history_mem = get_relevant_history(user_id, user_query)
    if history_mem:
        base_context += f"\n{history_mem}\n"
    
    base_context += f"\n【世界观基础】{world_basic}\n"
    return base_context.strip()


# ========== 10. 本地向量库路由（MEMORY_BACKEND=local 时生效，默认 cloud 走原百炼） ==========
# 说明：在模块加载时用 local_vector_store 的同名实现替换本模块的公开接口。
# main.py / active_cloud_retrieval.py 等调用方 "from cloud_memory_v2 import xxx"
# 拿到的即是本地版（from-import 绑定发生在本补丁之后），无需改动任何调用方代码。
_MEMORY_BACKEND = os.getenv("MEMORY_BACKEND", "cloud").lower().strip()
if _MEMORY_BACKEND == "local":
    try:
        import local_vector_store as _lvs
        for _fn in (
            "upload_plot_memory", "upload_foreshadowing", "upload_rumor_snapshot",
            "upload_task_node", "upload_milestone", "upload_chapter_summary",
            "upload_biography_update", "upload_important_memory", "upload_npc_memory",
            "upload_task_memory", "upload_rumor_item", "get_relevant_history",
        ):
            if hasattr(_lvs, _fn):
                globals()[_fn] = getattr(_lvs, _fn)
        print("[云记忆] 路由切换：MEMORY_BACKEND=local，读写走本地向量库（百炼不再计费）")
    except Exception as _e:
        print(f"[云记忆] 本地向量库加载失败，保持云端模式: {_e}")