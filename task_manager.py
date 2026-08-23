# 任务管理模块
# 实现任务的创建、更新、完成、删除等功能
# 支持主线/支线任务分类，进度百分比，阶段描述等

import os
import time
import re
from file_utils import save_json, load_json, load_context_cache, save_context_cache
from cloud_memory_v2 import upload_task_node

# 配置
from config import CLOUD_MEM_SLOT_ID
TASK_FILE = "data/tasks.json"
CONTEXT_CACHE_FILE = "data/context_cache.json"


# ===== 初始化 =====
def init_task_file():
    # 确保任务文件存在
    if not os.path.exists(TASK_FILE):
        save_json(TASK_FILE, [])


def _load_tasks():
    # 加载任务列表（内部函数）
    # 返回: 任务列表
    init_task_file()
    return load_json(TASK_FILE) or []


def _save_tasks(tasks):
    # 保存任务列表（内部函数）
    # tasks: 任务列表
    save_json(TASK_FILE, tasks)


def _load_context_cache():
    # 加载上下文缓存（内部函数）
    return load_context_cache() or {}


def _save_context_cache(cache):
    # 保存上下文缓存（内部函数）
    save_context_cache(cache)


# ===== 任务管理核心功能 =====
def create_task(name, description, task_type="side"):
    # 创建新任务，自动分配编号
    # name: 任务名称
    # description: 任务描述
    # task_type: 任务类型，"main"（主线）或 "side"（支线），默认支线
    # 返回: (success: bool, msg: str)
    name = name.strip()
    description = description.strip()
    if not name or not description:
        return False, "❌ 任务名称和描述不能为空"
    
    tasks = _load_tasks()
    
    # 自动分配编号：从1开始，如果已存在则递增
    max_id = 0
    for t in tasks:
        try:
            tid = int(t["name"])
            if tid > max_id:
                max_id = tid
        except (ValueError, TypeError):
            pass
    
    new_id = max_id + 1
    task_name = str(new_id)  # 编号作为任务名称
    
    # 检查是否已被占用（理论上不会）
    for t in tasks:
        if t["name"] == task_name and t["status"] == "active":
            return False, f"❌ 任务编号 {task_name} 已被占用"
    
    task = {
        "id": int(time.time() * 1000),  # 唯一ID
        "name": task_name,              # 编号作为 name
        "description": description,      # 用户输入的描述
        "display_name": name,            # 用户友好的显示名称
        "status": "active",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "progress_percent": 0,
        "current_stage": "未开始",
        "suspended": False,
        "type": task_type                # 支持创建时直接指定类型
    }
    tasks.append(task)
    _save_tasks(tasks)
    
    # 关键节点同步到云记忆
    upload_task_node(
        CLOUD_MEM_SLOT_ID,
        f"【新任务】编号{task_name}：{name}，类型：{'主线' if task_type == 'main' else '支线'}"
    )
    return True, f"✅ 任务 {task_name}（{name}）已创建"


def list_tasks(filter_status=None):
    # 列出所有任务，显示编号和描述
    # filter_status: 状态筛选，"active"（进行中）或 "completed"（已完成），None表示全部
    # 返回: 格式化的任务列表字符串
    tasks = _load_tasks()
    if not tasks:
        return "📭 当前没有任何任务。"
    
    if filter_status:
        tasks = [t for t in tasks if t["status"] == filter_status]
    if not tasks:
        return "📭 没有符合条件的任务。"
    
    lines = []
    for t in sorted(tasks, key=lambda x: int(x["name"]) if x["name"].isdigit() else 0, reverse=True):
        # 状态图标
        if t["status"] == "completed":
            icon = "✅"
            status_text = "已完成"
        elif t.get("suspended", False):
            icon = "⏸️"
            status_text = "已搁置"
        else:
            icon = "⬜"
            status_text = "进行中"
        
        # 类型标记
        type_mark = "⭐" if t.get("type") == "main" else "○"
        type_text = "主线" if t.get("type") == "main" else "支线"
        
        # 显示编号和描述
        display_name = t.get("display_name", t["name"])
        lines.append(f"{icon} 【{status_text}】{type_mark} {type_text}：{t['name']}. {display_name}")
        lines.append(f"   📝 {t['description']}")
        if t.get("current_stage"):
            lines.append(f"   📍 阶段：{t['current_stage']}")
        if t.get("progress_percent", 0) > 0:
            lines.append(f"   📊 进度：{t['progress_percent']}%")
        lines.append(f"   🕐 {t['created_at']}")
        lines.append("")
    return "\n".join(lines)


def complete_task(name):
    # 手动完成一个任务
    # name: 任务编号
    # 返回: (success: bool, msg: str, stage_hist: str)
    name = name.strip()
    if not name:
        return False, "❌ 请指定任务名称", ""
    
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name and t["status"] == "active":
            # 先触发进度更新->上传100%完成节点到向量库
            update_task_progress(name, stage="已完成", percent=100)
            # 再刷新状态（重新加载，因为 update_task_progress 已落盘）
            tasks = _load_tasks()
            for t2 in tasks:
                if t2["name"] == name:
                    t2["status"] = "completed"
                    _save_tasks(tasks)
                    stage_hist = t2.get("current_stage", "")
                    return True, f"✅ 任务「{name}」已完成！", stage_hist
    return False, f"❌ 未找到进行中的任务「{name}」", ""


def get_task_info(name):
    # 获取任务完整信息（供任务总结Prompt使用，不影响complete_task签名）
    # name: 任务编号
    # 返回: dict 或 None
    name = name.strip()
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name:
            return {
                "description": t.get("description", ""),
                "display_name": t.get("display_name", t["name"]),
                "current_stage": t.get("current_stage", ""),
                "type": t.get("type", "side")
            }
    return None


def delete_task(name):
    # 删除任务（无论状态）
    # name: 任务编号
    # 返回: (success: bool, msg: str)
    name = name.strip()
    tasks = _load_tasks()
    original_len = len(tasks)
    tasks = [t for t in tasks if t["name"] != name]
    if len(tasks) < original_len:
        _save_tasks(tasks)
        return True, f"🗑️ 任务「{name}」已删除"
    return False, f"❌ 未找到任务「{name}」"


def update_task_progress(name, stage=None, percent=None, replace=False):
    # 更新任务进度（允许任意调整，不受增减限制）
    # name: 任务编号
    # stage: 阶段描述，如果为 None 或空字符串则不更新
    # percent: 进度百分比（0-100），如果为 None 则不更新
    # replace: True=直接覆盖（web手动编辑），False=累计追加（AI工具调用）
    # 返回: 成功返回True
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name and t["status"] == "active":
            # 更新阶段（如果提供了有效值）
            if stage is not None and stage.strip():
                pct = percent if percent is not None else t.get("progress_percent", 0)
                if replace:
                    t["current_stage"] = f"{pct}% {str(stage).strip()}"
                else:
                    # 累计拼接，去重
                    old = t.get("current_stage", "")
                    entry = f"{pct}% {str(stage).strip()}"
                    if old:
                        last_part = old.split(" → ")[-1]
                        if entry == last_part:
                            pass  # 和上一条相同
                        elif percent is not None and percent <= t.get("progress_percent", 0):
                            pass  # 进度未前进，跳过
                        else:
                            t["current_stage"] = f"{old} → {entry}"
                    else:
                        t["current_stage"] = entry
            # 更新进度（如果提供了有效值）
            old_percent = t.get("progress_percent", 0)
            if percent is not None:
                # 限制到 0-100
                t["progress_percent"] = max(0, min(100, int(percent)))
            _save_tasks(tasks)
            # 关键进度节点同步到云记忆
            new_percent = t.get("progress_percent", 0)
            key_nodes = {20, 50, 80, 100}
            # 跨过关键节点时触发上传
            crossed_node = False
            for node in key_nodes:
                if old_percent < node <= new_percent:
                    crossed_node = True
                    break
            if crossed_node:
                # upload_task_node 已停用，L4回归纯剧情检索
                pass
            return True
    return False


def get_active_tasks():
    # 获取所有活跃任务（供其他模块调用）
    # 返回: 活跃任务列表
    tasks = _load_tasks()
    return [t for t in tasks if t["status"] == "active"]


def get_task_brief_for_ai():
    # 获取给AI用的任务简报
    # 返回: 任务简报字符串，无活跃任务返回None
    tasks = _load_tasks()
    active = [t for t in tasks if t["status"] == "active" and not t.get("suspended", False)]
    if not active:
        return None
    
    main_tasks = [t for t in active if t.get("type") == "main"]
    side_tasks = [t for t in active if t.get("type") != "main"]
    
    lines = ["【*当前任务目标*】"]
    
    if main_tasks:
        lines.append("📌 主线任务（仅在有实质进展时更新，日常闲聊无进展可不更新）：")
        for t in main_tasks:
            display_name = t.get("display_name", t["name"])
            lines.append(f"   【任务名】{t['name']}")
            lines.append(f"      目标：{display_name}")
            lines.append(f"      描述：{t['description']}")
            if t.get("current_stage") and t["current_stage"] != "未开始":
                lines.append(f"      阶段：{t['current_stage']}")
            if t.get("progress_percent", 0) > 0:
                lines.append(f"      进度：{t['progress_percent']}%")
            # lines.append("      ⚠️ 汇报时 name 必须填写【任务名】中的数字")
    else:
        lines.append("（暂无主线任务，你可自由推进任意支线）")
    
    if side_tasks:
        lines.append("")
        lines.append("📎 支线任务（遇到时才汇报）：")
        for t in side_tasks[:3]:
            display_name = t.get("display_name", t["name"])
            lines.append(f"   【任务名】{t['name']}：{display_name}")
        if len(side_tasks) > 3:
            lines.append(f"   ... 还有 {len(side_tasks) - 3} 个支线任务未显示")
    
    return "\n".join(lines)


def set_task_type(name, task_type):
    # 调整任务类型（main 或 side）
    # name: 任务编号
    # task_type: 任务类型，"main" 或 "side"
    # 返回: (success: bool, msg: str)
    name = name.strip()
    if task_type not in ["main", "side"]:
        return False, "❌ 类型必须是 main（主线）或 side（支线）"
    
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name and t["status"] == "active":
            t["type"] = task_type
            _save_tasks(tasks)
            return True, f"✅ 任务「{name}」已调整为{'主线' if task_type == 'main' else '支线'}"
    return False, f"❌ 未找到进行中的任务「{name}」"


def toggle_task_suspend(name):
    # 切换任务的搁置状态（激活 ↔ 搁置）
    # 搁置的任务不会出现在 AI 简报中，但保留在任务列表里
    # name: 任务编号
    # 返回: (success: bool, msg: str)
    name = name.strip()
    tasks = _load_tasks()
    for t in tasks:
        if t["name"] == name and t["status"] == "active":
            current = t.get("suspended", False)
            t["suspended"] = not current
            _save_tasks(tasks)
            if t["suspended"]:
                return True, f"⏸️ 任务「{name}」已搁置（不在简报中显示）"
            else:
                return True, f"▶️ 任务「{name}」已激活（重新出现在简报中）"
    return False, f"❌ 未找到任务「{name}」"


# ===== 高级：从 AI 的 JSON 更新任务进展 =====
def parse_ai_task_updates(updates):
    # 解析 AI 输出的 task_updates 字段
    # updates: 列表，每个元素包含 name, stage, percent
    # 返回: 更新了多少个任务
    if not updates:
        return 0
    count = 0
    for item in updates:
        name = item.get("name")
        if not name:
            continue
        stage = item.get("stage")
        percent = item.get("percent")
        if update_task_progress(name, stage, percent):
            count += 1
    return count
