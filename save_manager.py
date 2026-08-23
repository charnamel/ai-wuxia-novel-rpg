# save_manager.py
import os
import shutil
import json
from datetime import datetime
from pathlib import Path

# 定义路径
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
SAVES_DIR = BASE_DIR / "saves"

def _ensure_dirs():
    """确保存档目录存在"""
    SAVES_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

def _get_metadata():
    """尝试读取当前存档的轮次和玩家名，用于显示"""
    meta = {"round": "未知", "player": "无名侠客"}
    try:
        # 读取上下文缓存获取轮次
        ctx_path = DATA_DIR / "context_cache.json"
        if ctx_path.exists():
            with open(ctx_path, 'r', encoding='utf-8') as f:
                ctx = json.load(f)
                meta["round"] = ctx.get("round", ctx.get("interact_log_count", len(ctx.get("interact_log", []))))
        # 读取玩家信息
        player_path = DATA_DIR / "player.json"
        if player_path.exists():
            with open(player_path, 'r', encoding='utf-8') as f:
                p = json.load(f)
                meta["player"] = p.get("name", "无名侠客")
    except Exception:
        pass
    return meta

def list_saves():
    """列出所有存档"""
    _ensure_dirs()
    slots = [d for d in SAVES_DIR.iterdir() if d.is_dir()]
    if not slots:
        print("\n📂 暂无存档记录。")
        return
    
    print("\n📂 ========== 存档列表 ==========")
    for i, slot_path in enumerate(sorted(slots), 1):
        meta_path = slot_path / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                time_str = meta.get("time", "未知时间")
                player = meta.get("player", "未知")
                rounds = meta.get("round", 0)
                print(f"{i}. 【{slot_path.name}】 玩家：{player} | 轮次：{rounds} | 存档于：{time_str}")
            except:
                print(f"{i}. 【{slot_path.name}】 (元数据损坏)")
        else:
            print(f"{i}. 【{slot_path.name}】 (旧版存档)")

def save_game(slot_name: str):
    """保存当前进度到指定槽位"""
    _ensure_dirs()
    if not slot_name:
        print("❌ 存档名不能为空")
        return
    
    # 清理非法字符（仅允许中文、英文、数字、下划线）
    clean_name = ''.join(c for c in slot_name if c.isalnum() or c in ('_', '，', '。'))
    if not clean_name:
        clean_name = "未命名存档"
    
    target_dir = SAVES_DIR / clean_name
    
    # 如果目标存在，先删除（实现覆盖）
    if target_dir.exists():
        shutil.rmtree(target_dir)
    
    try:
        # 复制整个 data 文件夹
        shutil.copytree(DATA_DIR, target_dir)
        
        # 生成元数据
        meta = _get_metadata()
        meta["time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(target_dir / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            
        print(f"✅ 游戏已存档至：{clean_name} (轮次: {meta['round']})")
    except Exception as e:
        print(f"❌ 存档失败：{e}")

def load_game(slot_name: str):
    """从指定槽位读取存档，覆盖当前进度"""
    _ensure_dirs()
    if not slot_name:
        print("❌ 存档名不能为空")
        return
    
    # 清理字符以匹配文件夹名
    clean_name = ''.join(c for c in slot_name if c.isalnum() or c in ('_', '，', '。'))
    source_dir = SAVES_DIR / clean_name
    
    if not source_dir.exists():
        print(f"❌ 未找到名为「{clean_name}」的存档")
        return
    
    try:
        # 危险操作：清空当前 data 并替换
        if DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
        shutil.copytree(source_dir, DATA_DIR)
        
        # 读取元数据显示
        meta_path = source_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            print(f"✅ 读档成功！当前回到：{meta.get('time', '未知时间')}，轮次：{meta.get('round', 0)}")
        else:
            print("✅ 读档成功！(旧版存档)")
    except Exception as e:
        print(f"❌ 读档失败：{e}")

def delete_save(slot_name: str):
    """删除指定存档"""
    clean_name = ''.join(c for c in slot_name if c.isalnum() or c in ('_', '，', '。'))
    target_dir = SAVES_DIR / clean_name
    if not target_dir.exists():
        print(f"❌ 未找到存档「{clean_name}」")
        return
    try:
        shutil.rmtree(target_dir)
        print(f"🗑️ 已删除存档：{clean_name}")
    except Exception as e:
        print(f"❌ 删除失败：{e}")