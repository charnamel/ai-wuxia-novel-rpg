# 文件工具模块
# 提供通用的文件操作功能，包括JSON读写、目录管理、存档/读档等

import os
import json
import shutil
from config import CONTEXT_CACHE_FILE, MAX_CONTEXT_LOG

# 存档目录
SAVES_DIR = "saves"

# interact_log 独立追加文件（从 context_cache.json 剥离，避免每轮全量重写）
INTERACT_LOG_FILE = "data/interact_log.jsonl"


def ensure_dir(filepath):
    # 如果路径本身就是目录（没有后缀），直接创建该目录；否则创建其父目录
    if os.path.isdir(filepath) or "." not in os.path.basename(filepath):
        dirname = filepath
    else:
        dirname = os.path.dirname(filepath)
    if not os.path.exists(dirname):
        os.makedirs(dirname)


def save_json(path, data):
    # 保存数据到JSON文件
    # path: 保存路径
    # data: 要保存的数据（可序列化为JSON）
    ensure_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path):
    # 从JSON文件加载数据
    # path: 文件路径
    # 返回: 加载的数据，失败返回None
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ========== 整体存档/读档 ==========
def save_game(slot="auto"):
    # 快照备份整个data目录到存档槽
    # slot: 存档槽名称，默认"auto"
    # 返回: 成功返回True
    src = "data"
    dst = f"{SAVES_DIR}/{slot}"
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return True


def load_game(slot="auto"):
    # 从存档槽还原到data目录
    # slot: 存档槽名称，默认"auto"
    # 返回: 成功返回True，失败返回False
    src = f"{SAVES_DIR}/{slot}"
    if not os.path.exists(src):
        return False
    if os.path.exists("data"):
        shutil.rmtree("data")
    shutil.copytree(src, "data")
    return True


def list_saves():
    # 列出所有存档槽
    # 返回: 存档名称列表，按名称排序
    if not os.path.exists(SAVES_DIR):
        return []
    return sorted(os.listdir(SAVES_DIR))


# ========== interact_log jsonl 追加存储 ==========
# 将 context_cache 的 interact_log 从"整文件重写"改为独立 jsonl 追加文件，
# 每轮 O(1) 追加一行，避免每轮重写整个 context_cache.json。
# 内存中 cache["interact_log"] 的结构与行为保持不变，仅持久化方式改变。

def _read_all_interact_log():
    """读取整个 interact_log.jsonl，返回字符串列表（与原 cache["interact_log"] 结构一致）。
    单行损坏只跳过该行，不波及全文件。"""
    if not os.path.exists(INTERACT_LOG_FILE):
        return []
    logs = []
    try:
        with open(INTERACT_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    logs.append(obj.get("text", ""))
                except Exception:
                    continue
    except Exception:
        pass
    return logs


def append_interact_log(record):
    """O(1) 追加一条交互记录到 jsonl（与内存 append 同步调用）。"""
    ensure_dir(INTERACT_LOG_FILE)
    try:
        with open(INTERACT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"text": record}, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[interact_log] 追加失败: {e}")


def rewrite_interact_log(logs):
    """整文件重写 interact_log.jsonl（仅归档截断时调用，低频）。
    使用临时文件 + os.replace 原子替换，避免中途崩溃损坏数据。"""
    ensure_dir(INTERACT_LOG_FILE)
    tmp = INTERACT_LOG_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for text in logs:
                f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        os.replace(tmp, INTERACT_LOG_FILE)
    except Exception as e:
        print(f"[interact_log] 重写失败: {e}")


def load_context_cache():
    """加载 context_cache，并从 jsonl 附加 interact_log。
    替代所有 load_json(CONTEXT_CACHE_FILE) 调用点。
    - 自动迁移：旧格式 context_cache.json 含 interact_log 字段时，导出到 jsonl 并瘦身。
    - 内存 interact_log 截断到 MAX_CONTEXT_LOG，行为与原实现一致。"""
    cache = load_json(CONTEXT_CACHE_FILE) or {}
    if not isinstance(cache, dict):
        cache = {}
    # 一次性迁移：旧格式把 interact_log 内嵌在 context_cache.json
    if "interact_log" in cache:
        old_logs = cache.pop("interact_log")
        if isinstance(old_logs, list) and old_logs:
            rewrite_interact_log(old_logs)
        cache["interact_log_count"] = len(old_logs) if isinstance(old_logs, list) else 0
        save_json(CONTEXT_CACHE_FILE, cache)
    # 从 jsonl 读入内存
    logs = _read_all_interact_log()
    total_log_count = len(logs)  # 截断前的真实总行数，用于初始化 round
    if len(logs) > MAX_CONTEXT_LOG:
        logs = logs[-MAX_CONTEXT_LOG:]
    cache["interact_log"] = logs
    # 一次性迁移：旧存档无独立轮次计数器，用 jsonl 总行数或 interact_log_count 初始化
    # 解决封顶冻结bug——轮次号不再依赖 interact_log 长度
    # 取二者较大值，避免 interact_log_count 被窗口截断后偏小
    if "round" not in cache:
        cache["round"] = max(cache.get("interact_log_count", 0), total_log_count)
    if "last_appended_round" not in cache:
        cache["last_appended_round"] = cache["round"]
    return cache


def save_context_cache(cache):
    """保存 context_cache，剥离 interact_log（interact_log 由 append/rewrite 单独持久化）。
    替代所有 save_json(CONTEXT_CACHE_FILE, cache) 调用点。
    - interact_log 不写入 context_cache.json（避免大字段全量重写）。
    - 附加 interact_log_count 字段供 save_manager 显示轮次。"""
    if not isinstance(cache, dict):
        save_json(CONTEXT_CACHE_FILE, cache)
        return
    cache_to_save = {k: v for k, v in cache.items() if k != "interact_log"}
    cache_to_save["interact_log_count"] = len(cache.get("interact_log", []))
    save_json(CONTEXT_CACHE_FILE, cache_to_save)
