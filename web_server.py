# -*- coding: utf-8 -*-
# web_server.py

import os
import sys
import json
import threading
import socket
import traceback  # <--- 加这一行
import time
from flask import Flask, request, jsonify
from flask_cors import CORS

from player_manager import get_player, set_player, Player,edit_player_raw, save_player_raw, set_player_field, clear_martial_arts_book_cache
# ===== 骰子检定系统导入 =====
import dice_system
from dice_system import should_skip as dice_should_skip
from dice_system import resolve_check_v4 as dice_resolve_check_v4, ai_judge_check_v4 as dice_ai_judge_check_v4, clear_web_state_v4 as dice_clear_web_state_v4
from dice_system import detect_martial_skill as dice_detect_martial_skill, detect_martial_skill_classified as dice_detect_martial_skill_classified, ai_judge_dc_only as dice_ai_judge_dc_only

# ======= 地图系统配置 =======
MAP_DATA_FILE = "data/map_data.json"
WEB_MAP_TARGET = None  # 当前选中的目标地点，结构: {level, id, region, city, location}

# ======= 记事本配置 =======
NOTEPAD_DATA_FILE = "data/notepad_data.txt"

# ======= 武功书管理配置 =======
MARTIAL_ARTS_FILE = "data/martial_arts_bonus.json"
MARTIAL_GRADE_BONUS = {9:7, 8:6, 7:5, 6:4, 5:3, 4:2, 3:1, 2:0, 1:-1}

# ======= 势力门派管理配置 =======
TIMELINE_FILE = "data/timeline_reference.json"

def load_notepad():
    """加载记事本TXT，返回解析后的笔记列表"""
    if not os.path.exists(NOTEPAD_DATA_FILE):
        return []
    try:
        with open(NOTEPAD_DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        notes = []
        blocks = content.split('===== 笔记')
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.split('\n')
            note_id = ''
            title = ''
            created_at = ''
            content_lines = []
            i = 0
            # 第一行是 "1 =====" 这样的
            if i < len(lines) and lines[i].endswith('====='):
                note_id = lines[i].replace('=====', '').strip()
                i += 1
            # 读取标题
            if i < len(lines) and lines[i].startswith('标题：'):
                title = lines[i].replace('标题：', '').strip()
                i += 1
            # 读取时间
            if i < len(lines) and lines[i].startswith('时间：'):
                created_at = lines[i].replace('时间：', '').strip()
                i += 1
            # 跳过分隔线
            if i < len(lines) and lines[i].startswith('----'):
                i += 1
            # 读取内容
            while i < len(lines):
                content_lines.append(lines[i])
                i += 1
            note_content = '\n'.join(content_lines).strip()
            notes.append({
                'id': note_id or str(int(time.time()*1000)),
                'title': title or '无标题',
                'created_at': created_at or '未知时间',
                'content': note_content
            })
        return notes
    except Exception as e:
        print(f"[记事本] 加载失败: {e}")
        return []

def save_notepad(notes):
    """保存笔记列表为TXT格式"""
    try:
        parts = []
        for idx, note in enumerate(notes, 1):
            block = []
            block.append(f'===== 笔记{idx} =====')
            block.append(f'标题：{note.get("title", "无标题")}')
            block.append(f'时间：{note.get("created_at", "")}')
            block.append('--------------------')
            block.append(note.get('content', ''))
            parts.append('\n'.join(block))
        with open(NOTEPAD_DATA_FILE, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(parts))
        return True
    except Exception as e:
        print(f"[记事本] 保存失败: {e}")
        return False

def load_map_data():
    """加载地图数据"""
    if not os.path.exists(MAP_DATA_FILE):
        return {"version": 1, "regions": []}
    with open(MAP_DATA_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_map_data(data):
    """保存地图数据"""
    with open(MAP_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_martial_arts():
    """加载武功书数据"""
    if not os.path.exists(MARTIAL_ARTS_FILE):
        return {"_description":"", "_version":"", "_grade_system":{}, "_category_list":[], "martial_arts":{}}
    with open(MARTIAL_ARTS_FILE, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def save_martial_arts(data):
    """保存武功书数据"""
    with open(MARTIAL_ARTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _parse_effect_from_payload(payload):
    """从武功书编辑器payload解析effect配置

    payload字段:
        effect_type: 特效ID(如 "shock"),空串表示无特效
        base_rate: 基础率 1-20

    Returns:
        {"type": str, "base_rate": int} 或 None
    """
    effect_type = str(payload.get('effect_type', '') or '').strip()
    if not effect_type:
        return None
    try:
        base_rate = int(payload.get('base_rate', 5))
    except (ValueError, TypeError):
        base_rate = 5
    base_rate = max(1, min(20, base_rate))
    return {"type": effect_type, "base_rate": base_rate}

def _reload_effect_meta_safe():
    """安全重载特效元数据缓存（武功书增删改后调用）"""
    try:
        import dice_system as _ds
        _ds.reload_effect_meta()
    except Exception as _e:
        print(f"[WARN] 重载特效元数据失败: {_e}")

def _find_node_by_id(node_list, node_id):
    """递归查找节点（内部辅助函数）"""
    for node in node_list:
        if node.get("id") == node_id:
            return node
        if node.get("children"):
            found = _find_node_by_id(node["children"], node_id)
            if found:
                return found
    return None

def _gen_map_id(prefix):
    """生成唯一ID"""
    import time
    return f"{prefix}_{int(time.time()*1000)}"

# 导入任务管理模块
from task_manager import (
    create_task, list_tasks, complete_task, delete_task,
    update_task_progress, set_task_type, toggle_task_suspend,
    get_task_brief_for_ai, get_active_tasks,_load_tasks,get_task_info
)
from llm_utils import get_llm_content
# 将当前目录加入系统路径
sys.path.append(os.getcwd())

# ======= 导入核心模块 =======
from main import (
    process_one_round,
    llm_call_common, update_context_cache,
    parse_and_update_npc_state, update_progress, do_practice,
    parse_and_update_player_state,
    clear_battle_cache,
    query_player_level, query_player_skill, query_player_item, query_player_rumor,
    load_json, save_json, load_context_cache, build_novel_world, find_archive_for_round,load_archive_summary,handle_admin_commands,
    CONTEXT_CACHE_FILE,CLOUD_MEM_SLOT_ID,
    COLOR_SYSTEM, COLOR_END,    # <--- 这里加上了 COLOR_GREEN 和 COLOR_WARN
    PLAYER_FILE, NPC_AGENT_FILE, PLOT_PROGRESS_PER_ACTION,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, latest_plot1_text, # noqa: F401
    WORLD_FILE, client, DEEPSEEK_MODEL, load_location_time,  # noqa: F401
)
# 导入配图和战斗模块组件
from image_generator import draw_ascii
from battle_system import gen_single_battle_round, ai_judge_battle_trend, gen_battle_final_end, ai_check_battle_status

CURRENT_PLOT_TEXT = ""
# ======= 骰子待确认状态（Web端专用） =======
# None: 无待确认；dict: {"original_action": str, "intent_info": dict}
WEB_DICE_PENDING = None
# ======= 初始化 Flask 应用 =======
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})
game_lock = threading.Lock()

# ======= Web 专属战斗状态机 =======
WEB_BATTLE_STATE = {
    "active": False,
    "target_name": "",
    "target_npc": None,
    "player_data_raw": None,
    "total_process": "",
    "last_round": "",
    "round_num": 0,
    "battle_style": "",
    "phase": "idle",
    "dice_pending": None,
    "scene_info": "",
    "pre_battle_plot": "",
    "last_dc_summary": ""  # 上轮DC判定+掷骰战果摘要（DC续传锚定用）
}

def _llm_dc_low_temp(sys_p, user_p):
    """DC判定专用低温封装：判数值要一致（0.25），剧情生成仍走默认0.65"""
    return llm_call_common(sys_p, user_p, temp=0.25)

def reset_web_battle():
    """【修改点1】增加日志输出，便于追踪状态重置"""
    print("[DEBUG] reset_web_battle 被调用")
        # 打印调用栈，精确追踪是谁调用了它
    print("[DEBUG] 调用栈:\n" + "".join(traceback.format_stack()))
    WEB_BATTLE_STATE["active"] = False
    WEB_BATTLE_STATE["target_name"] = ""
    WEB_BATTLE_STATE["target_npc"] = None
    WEB_BATTLE_STATE["total_process"] = ""
    WEB_BATTLE_STATE["last_round"] = ""
    WEB_BATTLE_STATE["round_num"] = 0
    WEB_BATTLE_STATE["phase"] = "idle"
    WEB_BATTLE_STATE["dice_pending"] = None
    WEB_BATTLE_STATE["scene_info"] = ""
    WEB_BATTLE_STATE["pre_battle_plot"] = ""
    WEB_BATTLE_STATE["last_dc_summary"] = ""

def handle_battle_action(web_input: str, dice_confirm=None):
    import re

    
    """处理网页端的战斗流程（绝对稳定版，绝不会意外退出战斗）"""
    global WEB_BATTLE_STATE
    print(f"[DEBUG] handle_battle_action 收到: {web_input}")
    if not WEB_BATTLE_STATE["active"]:
        return {"type": "error", "msg": "当前无在进行中的战斗，请重新输入'对战'开启。"}

    web_input = web_input.strip()
    print(f"[DEBUG] 战斗操作输入: {web_input}")

    # ===== 模式选择阶段处理 =====
    if WEB_BATTLE_STATE["phase"] == "select_mode":
        _battle_modes = {
            "1": ("比武切磋", "常规比武过招，点到即止，双方仅切磋武学，不会下死手"),
            "2": ("死斗", "生死相搏，出手狠辣，招招致命，不留余地"),
            "3": ("暗中偷袭", "我方先手突袭，使用隐蔽、暗算类招式，对手猝不及防"),
            "4": ("擂台竞技", "有第三方裁判约束，禁止阴毒杀招，分出胜负即停"),
            "5": ("江湖群斗", "无固定招式套路，混战拉扯，场面杂乱激烈"),
        }
        if web_input in _battle_modes:
            _mode_name, _mode_desc = _battle_modes[web_input]
            WEB_BATTLE_STATE["battle_style"] = _mode_desc
            WEB_BATTLE_STATE["phase"] = "battling"
            return {"type": "info", "msg": f"⚔️ 选择【{_mode_name}】模式！对手：【{WEB_BATTLE_STATE['target_name']}】。\n\n1. 继续战斗（输入出招）\n2. 结束对战（AI结算结局）\n3. 判局（AI分析战局）"}
        else:
            reset_web_battle()
            clear_battle_cache()
            return {"type": "end", "msg": "已取消对战，返回江湖。"}

    # ===== 处理数字指令 =====
    if web_input == "1":
        return {"type": "info", "msg": "请直接输入你的出招动作（如：一剑刺向对方胸口），不要输入数字1。"}

    # 【修改点2】兼容全角数字“２”和“３”
    if web_input in ["2", "结束对战", "２"]:
        print(f"[DEBUG] 进入结束对战分支，输入: {web_input}")
        try:
            print("[DEBUG] 开始结束对战...")
            # Fix 5: 先获取双方伤势状态，传给结局生成
            _end_player_status = ""
            _end_npc_status = ""
            try:
                _end_status_text = ai_check_battle_status(
                    llm_call_common,
                    json.dumps(WEB_BATTLE_STATE["player_data_raw"], ensure_ascii=False),
                    json.dumps(WEB_BATTLE_STATE["target_npc"], ensure_ascii=False),
                    WEB_BATTLE_STATE["total_process"]
                )
                if _end_status_text:
                    _p_m = re.search(r"【玩家战斗状态】\s*(.*?)(?=\n【对手战斗状态】|\Z)", _end_status_text, re.S)
                    _n_m = re.search(r"【对手战斗状态】\s*(.*?)(?=\n|$)", _end_status_text, re.S)
                    _end_player_status = _p_m.group(1).strip() if _p_m else ""
                    _end_npc_status = _n_m.group(1).strip() if _n_m else ""
            except Exception as _es:
                print(f"[WARN] 结局前伤势判定失败: {_es}")

            final_end = gen_battle_final_end(
                llm_call_common,
                WEB_BATTLE_STATE["total_process"],
                WEB_BATTLE_STATE["battle_style"],
                player_status=_end_player_status,
                npc_status=_end_npc_status
            )
            print(f"[DEBUG] gen_battle_final_end 返回: {final_end}")
            if not final_end:
                final_end = "战斗结束，双方各自散去。"
                print("[DEBUG] final_end 为空，使用默认")

            # Fix 4: 压缩对战日志，只写入结局摘要，避免单条记录过大撑爆L2窗口
            compressed_battle_log = f"【对战剧情】与{WEB_BATTLE_STATE['target_name']}对战{WEB_BATTLE_STATE['round_num']}回合，对战风格：{WEB_BATTLE_STATE['battle_style']}。\n【对战结局】{final_end}"

            # 更新上下文、状态、进度
            update_context_cache(compressed_battle_log, user_action="结束战斗")
            parse_and_update_player_state(compressed_battle_log)
            parse_and_update_npc_state(compressed_battle_log)
            update_progress(PLOT_PROGRESS_PER_ACTION)

            # ===== ★★★ 新增：从全程对战文本中提取武功并加经验 ★★★ =====
            player_obj = get_player()
            if player_obj and player_obj.martial_skill_list:
                import random
                player_skill_names = [sk["skill_name"] for sk in player_obj.martial_skill_list]
                matched_skills = set()
                # 遍历整个对战过程，提取所有出现过的武功
                for skill_name in player_skill_names:
                    if skill_name in WEB_BATTLE_STATE["total_process"]:
                        matched_skills.add(skill_name)
                if matched_skills:
                    for skill_name in matched_skills:
                        exp_gain = random.randint(1, 3)
                        player_obj.add_exp(skill_name, exp_gain)
                        print(f"【战斗感悟】{skill_name} +{exp_gain} 点经验")
                else:
                    # 全程都没有提到任何武功 → 随机选一个武功 +1 点经验
                    random_skill = random.choice(player_obj.martial_skill_list)["skill_name"]
                    exp_gain = random.randint(1, 5)
                    player_obj.add_exp(random_skill, exp_gain)
                    print(f"【战斗感悟】{random_skill} +{exp_gain} 点经验（随机）")
                player_obj.sync_overall_level()
                player_obj.save()
                player_obj.update_bottleneck_status()  # 战斗后检测瓶颈突破

            # 只有这里才会重置战斗状态
            reset_web_battle()
            clear_battle_cache()
            print("[DEBUG] 对战结束，状态已清理")
            return {"type": "end", "msg": f"【对战结束】\n{final_end}\n\n（战斗已记入江湖轶事）"}
        except Exception as e:
            print(f"[ERROR] 结束战斗失败: {e}")
            # 绝对不能返回 end，必须保持在战斗中
            return {"type": "info", "msg": f"结束战斗时出现异常（{e}），请重试或继续战斗。"}

    if web_input in ["3", "判局", "３"]:
        try:
            print("[DEBUG] 开始AI战局分析...")
            # 状态获取（重试机制）
            status_text = ""
            for attempt in range(2):
                try:
                    status_text = ai_check_battle_status(
                        llm_call_common,
                        json.dumps(WEB_BATTLE_STATE["player_data_raw"], ensure_ascii=False),
                        json.dumps(WEB_BATTLE_STATE["target_npc"], ensure_ascii=False),
                        WEB_BATTLE_STATE["total_process"]
                    )
                    if status_text:
                        break
                except Exception as e:
                    print(f"[WARN] 第{attempt+1}次状态获取失败: {e}")
                    if attempt == 1:
                        status_text = "【玩家战斗状态】无法获取\n【对手战斗状态】无法获取"

            # 正则提取状态
            player_status = "未能获取玩家状态，但可参考战斗过程。"
            npc_status = "未能获取对手状态，但可参考战斗过程。"
            patterns = [
                r"【玩家战斗状态】\s*(.*?)(?=\n【对手战斗状态】|\Z)",
                r"玩家状态[:：]\s*(.*?)(?=\n对手状态|对手战斗状态|$)",
                r"玩家[：:]\s*(.*?)(?=\n对手|对手状态|$)"
            ]
            for pat in patterns:
                m = re.search(pat, status_text, re.S | re.I)
                if m:
                    player_status = m.group(1).strip()
                    break
            npc_patterns = [
                r"【对手战斗状态】\s*(.*?)(?=\n|$)",
                r"对手状态[:：]\s*(.*?)(?=\n|$)",
                r"对手[：:]\s*(.*?)(?=\n|$)"
            ]
            for pat in npc_patterns:
                m = re.search(pat, status_text, re.S | re.I)
                if m:
                    npc_status = m.group(1).strip()
                    break

            # 趋势分析（重试）
            trend_result = ""
            for attempt in range(2):
                try:
                    trend_result = ai_judge_battle_trend(
                        llm_call_common,
                        WEB_BATTLE_STATE["total_process"],
                        player_status,
                        npc_status
                    )
                    if trend_result:
                        break
                except Exception as e:
                    print(f"[WARN] 第{attempt+1}次趋势分析失败: {e}")
                    if attempt == 1:
                        trend_result = "【AI战局判定】当前战况不明，建议继续战斗或手动结束。"

            if not trend_result or trend_result.strip() == "":
                trend_result = "【AI战局判定】局势胶着，无明确优势方，建议继续观察。"

            full_analysis = f"{status_text}\n\n{trend_result}"
            print("[DEBUG] 战局分析完成")
            return {"type": "info", "msg": f"【AI战局分析】\n{full_analysis}"}
        except Exception as e:
            print(f"[ERROR] 战局分析异常: {e}")
            # 绝不影响战斗状态
            return {"type": "info", "msg": f"战局分析出现异常（{e}），请稍后再试。"}

    # ===== 非指令，作为出招文字 =====
    player_attack = web_input

    # ★ 战斗中括号调档：出招文字含（14档词）→ 程序直接更新对手境界（剧情演进：受伤变弱/卸下伪装）
    try:
        _REALM_SET = {"初学入门", "初窥门径", "略有小成", "略有所成", "渐入佳境", "融会贯通",
                      "登堂入室", "炉火纯青", "出神入化", "登峰造极", "超凡入圣", "返璞归真", "天人合一", "破碎虚空"}
        if WEB_BATTLE_STATE.get("target_npc"):
            for _adj_m in re.finditer(r'[（(]([^（）()]{2,6})[）)]', player_attack):
                _new_realm = _adj_m.group(1).strip()
                if _new_realm in _REALM_SET and WEB_BATTLE_STATE["target_npc"].get("level") != _new_realm:
                    WEB_BATTLE_STATE["target_npc"]["level"] = _new_realm
                    if isinstance(WEB_BATTLE_STATE["target_npc"].get("martial_skills"), list) and WEB_BATTLE_STATE["target_npc"]["martial_skills"]:
                        WEB_BATTLE_STATE["target_npc"]["martial_skills"][0]["skill_level"] = _new_realm
                    print(f"[临时NPC] 战斗中调档生效：对手境界 → {_new_realm}")
                    break
    except Exception:
        pass

    # ★ 骰子检定确认流程（与正常剧情一致：检测→确认面板→掷骰→显示结果）
    _dice_pending = WEB_BATTLE_STATE.get("dice_pending")
    _dice_constraint = ""
    _dice_result = None

    if _dice_pending and dice_confirm is True:
        # 步骤B: 玩家确认掷骰 → 执行检定
        WEB_BATTLE_STATE["dice_pending"] = None
        try:
            _pobj = get_player()
            _check_result = dice_resolve_check_v4(
                player_obj=_pobj,
                user_action=_dice_pending["original_action"],
                l1_scene=WEB_BATTLE_STATE["last_round"] or "",
                llm_func=llm_call_common,
                preset_skill_name=_dice_pending.get("skill_name"),
                preset_dc=_dice_pending.get("dc"),
                preset_dc_reason=_dice_pending.get("dc_reason"),
                classified_skills=_dice_pending.get("classified_skills"),
            )
            if _check_result and _check_result.get("constraint_text"):
                _dice_constraint = "\n" + _check_result["constraint_text"]
                # ★ DC续传锚定：记录本轮DC判定+掷骰战果，供下一轮DC判定参考
                try:
                    _vn = _check_result.get("verdict_narr") or _check_result.get("verdict") or ""
                    WEB_BATTLE_STATE["last_dc_summary"] = (
                        f"DC{_check_result.get('dc', '?')}({_check_result.get('dc_reason', '')})，"
                        f"掷骰结果：{_check_result.get('verdict', '?')}，{_vn[:60]}"
                    )
                    print(f"[BattleDC] 战果已记录: {WEB_BATTLE_STATE['last_dc_summary']}")
                except Exception:
                    pass
                _dice_result = {
                    "skill_name": _check_result["skill_name"],
                    "skill_level": _check_result["skill_level"],
                    "grade": _check_result["grade"],
                    "base_bonus": _check_result["base_bonus"],
                    "skill_bonus": _check_result["skill_bonus"],
                    "realm_bonus": _check_result["realm_bonus"],
                    "total_modifier": _check_result["total_modifier"],
                    "dc": _check_result["dc"],
                    "dc_reason": _check_result.get("dc_reason", ""),
                    "dice_natural": _check_result["dice_natural"],
                    "dice_total": _check_result["dice_total"],
                    "dice_rolls": _check_result["dice_rolls"],
                    "delta": _check_result["delta"],
                    "verdict_grade": _check_result["verdict_grade"],
                    "verdict": _check_result["verdict"],
                    "verdict_narr": _check_result["verdict_narr"],
                    "effect_result": _check_result.get("effect_result"),
                    "effect_results": _check_result.get("effect_results"),
                }
                print(f"[BattleDC] 确认掷骰: {_check_result['verdict']}（第{_check_result['verdict_grade']}档）")
        except Exception as _e:
            print(f"[WARN] 对战骰子检定异常: {_e}")

    elif _dice_pending and dice_confirm is False:
        # 步骤C: 玩家跳过检定
        WEB_BATTLE_STATE["dice_pending"] = None
        print("[BattleDC] 玩家跳过掷骰")

    elif not _dice_pending and dice_confirm is None:
        # 步骤A: 新出招 → 正则检测武功名
        try:
            _pobj = get_player()
            if _pobj:
                _classified = dice_detect_martial_skill_classified(player_attack, _pobj.martial_skill_list, _pobj)
                _matched = _classified.get("all_matched", [])
                if _matched:
                    _skill_name = _classified.get("primary_attack") or _matched[0]
                    _skill_info = _pobj.get_skill_info(_skill_name)
                    _skill_level = _skill_info["skill_level"] if _skill_info else _pobj.overall_realm
                    _grade = _skill_info["grade"] if _skill_info else 0
                    _skill_bonus = _skill_info["bonus"] if _skill_info else 0
                    _realm_bonus = _skill_info["realm_bonus"] if _skill_info else 0
                    _base_bonus = _pobj.base_bonus
                    _total_mod = _base_bonus + _skill_bonus + _realm_bonus

                    # 增幅检定预览（用于面板显示）
                    _inner_name = _classified.get("primary_inner", "")
                    _light_name = _classified.get("primary_light", "")
                    _inner_info = _pobj.get_skill_info(_inner_name) if _inner_name else None
                    _light_info = _pobj.get_skill_info(_light_name) if _light_name else None
                    _amp_total, _amp_detail = dice_system.compute_amplify_bonus(
                        attack_total=_total_mod,
                        inner_info=_inner_info,
                        light_info=_light_info,
                    )
                    if _amp_total:
                        _total_mod = _total_mod + _amp_total
                        print(f"[BattleDC] 增幅检定: 内功={_inner_name or '无'}, 轻功={_light_name or '无'}, 增幅=+{_amp_total}")

                    # ★ 构建DC判定场景上下文：首轮用战前剧情，后续轮用上轮输出，均追加场景信息
                    _dc_scene = WEB_BATTLE_STATE.get("last_round") or ""
                    if not _dc_scene:
                        # 首轮：last_round为空，使用战前最新剧情
                        _dc_scene = WEB_BATTLE_STATE.get("pre_battle_plot", "")
                    _scene_info = WEB_BATTLE_STATE.get("scene_info", "")
                    if _scene_info:
                        _dc_scene = f"{_dc_scene}\n【场景信息】\n{_scene_info}" if _dc_scene else f"【场景信息】\n{_scene_info}"
                    # ★ DC续传锚定：第2轮起拼入上轮DC判定+掷骰战果（放末尾，确保300字窗口优先保留）
                    _last_dc = WEB_BATTLE_STATE.get("last_dc_summary", "")
                    if _last_dc and WEB_BATTLE_STATE.get("round_num", 0) >= 1:
                        _dc_scene = f"{_dc_scene}\n【上一轮检定事实】\n{_last_dc}"

                    _battle_npcs_brief = dice_system.build_active_npcs_brief(
                        load_json(NPC_AGENT_FILE), player_attack,
                        _dc_scene,
                        extra_npcs=[WEB_BATTLE_STATE["target_npc"]] if WEB_BATTLE_STATE.get("target_npc") else []
                    )
                    _dc, _dc_reason = dice_ai_judge_dc_only(
                        llm_func=_llm_dc_low_temp,
                        scene=_dc_scene,
                        user_action=player_attack,
                        skill_name=_skill_name,
                        skill_level=_skill_level,
                        grade=_grade,
                        skill_list_summary=_pobj.get_skill_list_summary(),
                        overall_realm=_pobj.overall_realm,
                        active_npcs_text=_battle_npcs_brief,
                    )
                    print(f"[BattleDC] 命中「{_skill_name}」, DC={_dc}({_dc_reason})")

                    WEB_BATTLE_STATE["dice_pending"] = {
                        "original_action": player_attack,
                        "skill_name": _skill_name,
                        "dc": _dc,
                        "dc_reason": _dc_reason,
                        "classified_skills": _classified,
                    }
                    # 构建增幅显示文本
                    _amp_display_battle = ""
                    if _amp_total:
                        _amp_parts = []
                        if _inner_name:
                            _amp_parts.append(f"内功{_inner_name}")
                        if _light_name:
                            _amp_parts.append(f"轻功{_light_name}")
                        _amp_display_battle = f"\n增幅检定: {'+'.join(_amp_parts)} → +{_amp_total}"

                    return {
                        "type": "dice_pending",
                        "dice_check": {
                            "skill_name": _skill_name,
                            "skill_level": _skill_level,
                            "grade": _grade,
                            "base_bonus": _base_bonus,
                            "skill_bonus": _skill_bonus,
                            "realm_bonus": _realm_bonus,
                            "total_modifier": _total_mod,
                            "amplify_total": _amp_total,
                            "inner_name": _inner_name,
                            "light_name": _light_name,
                            "dc": _dc,
                            "dc_reason": _dc_reason,
                        },
                        "msg": f"🎲 武功检定触发\n武功: {_skill_name}（{_skill_level}·品阶{_grade}级）\n基础修正: +{_base_bonus} | 武功加成: +{_skill_bonus + _realm_bonus}{_amp_display_battle}\n总修正: +{_total_mod} vs DC{_dc}\n({_dc_reason})\n请确认是否掷骰？",
                    }
        except Exception as _e:
            print(f"[WARN] 对战骰子检测异常: {_e}")

    # 超过20轮自动强制结束，防止战斗日志无限膨胀塞爆LLM上下文
    WEB_BATTLE_STATE["round_num"] += 1
    if WEB_BATTLE_STATE["round_num"] > 20:
        print("[DEBUG] 战斗超过20轮，自动触发结束")
        result = handle_battle_action("2")
        if result["type"] != "end":
            # 结束失败，强制重置防止无限循环
            print("[DEBUG] 自动结束失败，强制重置战斗状态")
            reset_web_battle()
            clear_battle_cache()
            return {"type": "end", "msg": "战斗超过20回合，已强制结束。"}
        return result

    # Fix 2+3: 每回合刷新玩家数据并精简（只保留对战相关字段）
    _fresh_player = get_player()
    if _fresh_player:
        _full = _fresh_player.to_dict()
        _slim_player = {
            "name": _full.get("name", ""),
            "self_state": _full.get("self_state", ""),
            "overall_realm": _full.get("overall_realm", ""),
            "overall_martial_level": _full.get("overall_martial_level", ""),
            "reputation": _full.get("reputation", 0),
            "item_list": _full.get("item_list", []),
            "martial_skill_list": _full.get("martial_skill_list", []),
        }
    else:
        _slim_player = WEB_BATTLE_STATE["player_data_raw"] or {}

    try:
        round_plot = gen_single_battle_round(
            llm_func=llm_call_common,
            player_data=json.dumps(_slim_player, ensure_ascii=False),
            npc_data=json.dumps(WEB_BATTLE_STATE["target_npc"], ensure_ascii=False),
            round_num=WEB_BATTLE_STATE["round_num"],
            player_attack_text=player_attack,
            last_process=WEB_BATTLE_STATE["last_round"],
            battle_style_desc=WEB_BATTLE_STATE["battle_style"],
            dice_constraint=_dice_constraint,
            scene_info=WEB_BATTLE_STATE.get("scene_info", "")
        )
        if round_plot:
            WEB_BATTLE_STATE["total_process"] += f"\n【第{WEB_BATTLE_STATE['round_num']}回合】{round_plot}"
            WEB_BATTLE_STATE["last_round"] = round_plot
            _ret = {"type": "round", "msg": f"【第{WEB_BATTLE_STATE['round_num']}回合 对战剧情】\n{round_plot}"}
            if _dice_result:
                _ret["dice_result"] = _dice_result
            return _ret
        else:
            return {"type": "info", "msg": "本回合对战生成失败，请重试。"}
    except Exception as e:
        print(f"[ERROR] 生成单回合战斗失败: {e}")
        return {"type": "info", "msg": f"战斗回合生成异常（{e}），请重新输入招式。"}


def generate_task_panel_html():
    """生成任务管理面板的 HTML（移动端优化版）"""
    from task_manager import _load_tasks
    tasks = _load_tasks()
    
    # 基础样式
    base_style = """
    <style>
        .task-panel { 
            background: #1a1a2e; 
            border: 1px solid #4ff; 
            border-radius: 8px; 
            padding: 10px; 
            margin: 8px 0; 
            font-size: 13px;
            max-width: 100%;
            overflow-x: hidden;
        }
        .task-panel h3 { 
            color: #4ff; 
            margin: 0 0 8px 0; 
            font-size: 16px;
        }
        .task-panel .input-row {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 8px;
        }
        .task-panel .input-row input {
            flex: 1;
            min-width: 80px;
            background: #111;
            border: 1px solid #444;
            color: #0f0;
            padding: 6px 8px;
            border-radius: 4px;
            font-size: 12px;
        }
        .task-panel .input-row input:focus {
            outline: 1px solid #4ff;
        }
        .task-panel .btn {
            padding: 4px 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 11px;
            font-weight: bold;
            white-space: nowrap;
        }
        .task-panel .btn-green { background: #4f4; color: #000; }
        .task-panel .btn-blue { background: #44f; color: #fff; }
        .task-panel .btn-yellow { background: #ff4; color: #000; }
        .task-panel .btn-cyan { background: #4ff; color: #000; }
        .task-panel .btn-red { background: #f44; color: #fff; }
        .task-panel .btn-gray { background: #555; color: #ddd; }
        
        .task-card {
            background: #111;
            border: 1px solid #333;
            border-radius: 6px;
            padding: 8px 10px;
            margin-bottom: 6px;
        }
        .task-card .task-header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 4px 8px;
        }
        .task-card .task-name {
            color: #fff;
            font-weight: bold;
            font-size: 13px;
        }
        .task-card .task-display {
            color: #4f4;
            font-size: 12px;
        }
        .task-card .task-tag {
            color: #888;
            font-size: 10px;
        }
        .task-card .task-status {
            color: #888;
            font-size: 10px;
        }
        .task-card .task-desc {
            color: #aaa;
            font-size: 12px;
            margin: 4px 0;
        }
        .task-card .task-progress {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 4px 10px;
            margin-top: 4px;
            font-size: 12px;
        }
        .task-card .task-progress .pct { color: #4ff; }
        .task-card .task-progress .stage { color: #ff4; }
        .task-card .task-update-row {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 4px;
        }
        .task-card .task-update-row input {
            flex: 1;
            min-width: 60px;
            background: #111;
            border: 1px solid #444;
            color: #0f0;
            padding: 4px 6px;
            border-radius: 4px;
            font-size: 11px;
        }
        .task-card .task-update-row input:focus {
            outline: 1px solid #4ff;
        }
        .task-card .task-btns {
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            margin-top: 4px;
        }
        .task-list-scroll {
            max-height: 350px;
            overflow-y: auto;
            padding-right: 4px;
        }
        .task-list-scroll::-webkit-scrollbar {
            width: 4px;
        }
        .task-list-scroll::-webkit-scrollbar-thumb {
            background: #4ff;
            border-radius: 2px;
        }
        @media (max-width: 480px) {
            .task-panel { padding: 6px; font-size: 12px; }
            .task-panel h3 { font-size: 14px; }
            .task-panel .input-row input { font-size: 11px; padding: 5px 6px; min-width: 60px; }
            .task-panel .btn { font-size: 10px; padding: 3px 8px; }
            .task-card { padding: 6px 8px; }
            .task-card .task-name { font-size: 12px; }
            .task-card .task-display { font-size: 11px; }
            .task-card .task-desc { font-size: 11px; }
            .task-card .task-progress { font-size: 11px; }
            .task-card .task-update-row input { font-size: 10px; padding: 3px 5px; min-width: 50px; }
        }
    </style>
    """
    
    if not tasks:
        return base_style + """
        <div class="task-panel">
            <h3>📋 任务管理</h3>
            <p style="color:#888; font-size:13px;">当前没有任何任务。</p>
            <div class="input-row">
                <input type="text" id="new_task_name" placeholder="任务名称">
                <input type="text" id="new_task_desc" placeholder="任务描述">
                <button class="btn btn-green" onclick="createTask()">➕ 新建</button>
            </div>
        </div>
        """
    
    html = base_style + """
    <div class="task-panel">
        <h3>📋 任务管理</h3>
        <div class="input-row">
            <input type="text" id="new_task_name" placeholder="任务名称">
            <input type="text" id="new_task_desc" placeholder="任务描述">
            <button class="btn btn-green" onclick="createTask()">➕ 新建</button>
        </div>
        <div class="task-list-scroll">
    """
    
    for t in sorted(tasks, key=lambda x: int(x["name"]) if x["name"].isdigit() else 0, reverse=True):
        status_icon = "✅" if t["status"] == "completed" else ("⏸️" if t.get("suspended", False) else "⬜")
        status_text = "已完成" if t["status"] == "completed" else ("已搁置" if t.get("suspended", False) else "进行中")
        type_mark = "⭐" if t.get("type") == "main" else "○"
        type_text = "主线" if t.get("type") == "main" else "支线"
        display_name = t.get("display_name", t["name"])
        progress = t.get("progress_percent", 0)
        stage = t.get("current_stage", "未开始")
        is_active = t["status"] == "active" and not t.get("suspended", False)
        
        html += f"""
        <div class="task-card">
            <div class="task-header">
                <span class="task-name">{status_icon} #{t['name']}</span>
                <span class="task-display">{display_name}</span>
                <span class="task-tag">[{type_mark} {type_text}]</span>
                <span class="task-status">{status_text}</span>
            </div>
            <div class="task-desc">📝 {t['description']}</div>
            <div class="task-progress">
                <span class="pct">📊 {progress}%</span>
                <span class="stage">📍 {stage}</span>
            </div>
        """
        
        if is_active:
            html += f"""
            <div class="task-update-row">
                <input type="text" id="stage_input_{t['name']}" placeholder="阶段">
                <input type="number" id="percent_input_{t['name']}" placeholder="进度" min="0" max="100">
                <button class="btn btn-cyan" onclick="updateTaskProgress('{t['name']}')">📤</button>
            </div>
            <div class="task-btns">
                <button class="btn btn-green" onclick="taskAction('complete','{t['name']}')">完成</button>
                <button class="btn btn-blue" onclick="taskAction('toggle_type','{t['name']}')">切换</button>
                <button class="btn btn-yellow" onclick="taskAction('toggle_suspend','{t['name']}')">搁置</button>
                <button class="btn btn-red" onclick="taskAction('delete','{t['name']}')">删除</button>
            </div>
            """
        else:
            html += f"""
            <div class="task-btns">
                <button class="btn btn-cyan" onclick="taskAction('toggle_suspend','{t['name']}')">激活</button>
                <button class="btn btn-red" onclick="taskAction('delete','{t['name']}')">删除</button>
            </div>
            """
        
        html += "</div>"
    
    html += """
        </div>
    </div>
    """
    
    return html

def get_task_list_data():
    """返回任务列表的纯文本和结构化数据（供前端渲染按钮）"""
    from task_manager import _load_tasks
    tasks = _load_tasks()
    if not tasks:
        return {
            "text": "📭 当前没有任何任务。",
            "tasks": []
        }
    
    lines = []
    lines.append("========== 📋 任务列表 ==========")
    task_data = []
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
        display_name = t.get("display_name", t["name"])
        progress = t.get("progress_percent", 0)
        stage = t.get("current_stage", "未开始")
        
        lines.append(f"{icon} {type_mark} #{t['name']} {display_name} [{type_text}] {status_text}")
        lines.append(f"   📝 {t['description']}")
        lines.append(f"   📊 进度: {progress}%  |  阶段: {stage}")
        lines.append("")
        
        task_data.append({
            "id": t["name"],
            "display_name": display_name,
            "status": t["status"],
            "suspended": t.get("suspended", False),
            "type": t.get("type", "side"),
            "progress": progress,
            "stage": stage
        })
    
    return {
        "text": "\n".join(lines),
        "tasks": task_data
    }


# ======= 网页 API 路由 =======
@app.route('/')
def index():
    """渲染主页面 - HTML/CSS/JS已分离到templates和static目录"""
    import os
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'index.html')
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()


# ======= 创建角色接口 =======
@app.route('/create_player', methods=['POST'])
def create_player():
    data = request.get_json()
    name = data.get('name', '少侠').strip()
    origin = data.get('origin', '江湖游侠').strip()
    ability = data.get('ability', '基础内功').strip()
    
    if not name or not origin or not ability:
        return jsonify({"status": "error", "message": "所有字段都不能为空"})
    
    try:
        from main import create_player_profile
        create_player_profile(name=name, origin=origin, ability=ability)
        return jsonify({"status": "success", "message": "角色创建成功！"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"角色创建失败：{str(e)}"})

# ======= 角色属性编辑器 API =======
@app.route('/player/get', methods=['GET'])
def api_get_player():
    success, data, msg = edit_player_raw()
    if success:
        return jsonify({"status": "success", "data": data})
    return jsonify({"status": "error", "message": msg})

@app.route('/player/set_field', methods=['POST'])
def api_set_field():
    data = request.get_json()
    field = data.get('field', '').strip()
    value = data.get('value', '')
    if not field:
        return jsonify({"status": "error", "message": "字段名不能为空"})
    success, msg = set_player_field(field, value)
    return jsonify({"status": "success" if success else "error", "message": msg})

@app.route('/player/save_raw', methods=['POST'])
def api_save_raw():
    data = request.get_json()
    player_data = data.get('player_data')
    if not player_data or not isinstance(player_data, dict):
        return jsonify({"status": "error", "message": "数据格式错误"})
    
    # 新增：打印接收日志，确认前端数据正常传到后端
    print(f"[DEBUG] 收到玩家完整JSON保存请求，字段数：{len(player_data)}")
    
    success, msg = save_player_raw(player_data)
    return jsonify({"status": "success" if success else "error", "message": msg})

@app.route('/chat', methods=['POST'])
def chat():
    global CURRENT_PLOT_TEXT
    import re
    
    # ========== DEBUG1 开始：全链路计时初始化 ==========
    req_start = time.time()
    # ========== DEBUG1 结束 ==========
    
    data = request.get_json()
    user_action = data.get('action', '').strip()
    # ===== 骰子确认标志（True=确认掷骰, False=跳过, None=无待确认） =====
    dice_confirm = data.get('dice_confirm', None)
    # ========== DEBUG 开始 ==========
    print(f"\n{'='*60}")
    print(f"【DEBUG-请求】收到指令: {user_action[:40]}")
    # ========== DEBUG 结束 ==========
    if not user_action:
        return jsonify({"status": "error", "message": "输入不能为空"})
    
    try:
        # ========== 新增：管理指令优先处理 ==========
        handled, admin_msg = handle_admin_commands(user_action)
        if handled:
            return jsonify({
                "status": "success",
                "type": "system",
                "plot": admin_msg,
                "message": admin_msg
            })
        # 【修改点3】优先处理“对战”指令，防止状态残留
        if user_action.startswith("对战"):
            # 如果当前战斗状态仍活跃，强制重置（因为用户想开新战斗）
            if WEB_BATTLE_STATE["active"]:
                print("[DEBUG] 用户发起新对战，但战斗状态仍活跃，强制重置")
                reset_web_battle()
            
            parts = user_action.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return jsonify({"status": "error", "message": "请输入对手姓名，格式：对战 胡斐"})
            target_name_raw = parts[1].strip()
            # ★ 括号控档：拆解"黑衣人（略有小成）" → 干净名 + 境界/线索提示
            _paren_m = re.match(r'^(.+?)[（(]([^）)]+)[）)]\s*$', target_name_raw)
            if _paren_m:
                target_name = _paren_m.group(1).strip() or target_name_raw
                _level_hint = _paren_m.group(2).strip()
            else:
                target_name = target_name_raw
                _level_hint = ""
            current_npc_all = load_json(NPC_AGENT_FILE)
            target_npc = None
            for npc in current_npc_all.get("npc_list", []):
                if npc.get("name") == target_name_raw or npc.get("name") == target_name:
                    target_npc = npc
                    break
            
            if not target_npc:
                print(f"\n【Web提示】{target_name} 不在存档NPC列表，AI正在生成人物档案...")
                
                # 取最近2轮全量剧情作为背景（总长截断800字防token膨胀）
                ctx_cache = load_context_cache() or {}
                recent_logs = ctx_cache.get("interact_log", [])[-2:]
                recent_context = "\n".join(recent_logs) if recent_logs else "江湖日常场景"
                if len(recent_context) > 800:
                    recent_context = recent_context[-800:]

                # ★ 14档枚举（与DC判定表严格对齐）+ 括号境界锁定
                _REALM_14 = "初学入门、初窥门径、略有小成、略有所成、渐入佳境、融会贯通、登堂入室、炉火纯青、出神入化、登峰造极、超凡入圣、返璞归真、天人合一、破碎虚空"
                if _level_hint and _level_hint in _REALM_14:
                    _realm_lock_block = f"""
【境界锁定（最高优先级，玩家显式指定）】
该对手境界必须为「{_level_hint}」，level 与主武功 skill_level 必须严格采用此档位，不得擅改；
此指定优先于下方世界观天花板。"""
                elif _level_hint:
                    _realm_lock_block = f"""
【人物线索】玩家补充信息「{_level_hint}」，作为身份/门派/武功风格参考；境界由你按剧情与世界观天花板自行判定。"""
                else:
                    _realm_lock_block = ""
                
                gen_prompt = f"""
仅输出纯净JSON，无任何注释、markdown、多余文字。
【当前剧情背景】
{recent_context}
{_realm_lock_block}
【生成规则】
1. 结合上面的剧情背景，生成贴合当前场景的武侠NPC对手
2. level 与 skill_level 必须从以下14档中选用：{_REALM_14}
3. 世界观天花板：清朝为低武世界，最高仅出神入化/登峰造极（宗师级全江湖仅4人）；明朝中武世界最高超凡入圣
4. initial_favor 范围 -100~100，对手默认15
根据名称「{target_name}」生成完整档案，结构严格如下：
{{
    "name": "{target_name}",
    "identity": "江湖身份，简短一句话",
    "level": "武侠修为等级（14档之一）",
    "personality": "三十字内性格描述",
    "life_experience": "简短身世经历",
    "secret": "人物隐秘心事",
    "initial_favor": 15,
    "memory_list": [],
    "martial_skills": [
        {{
            "skill_name": "专属武学名称",
            "skill_level": "对应修为档次（14档之一）"
        }}
    ],
    "body_status": "normal"
}}
"""
                # 安全提取AI返回文本，兼容字典/字符串两种返回，彻底避免 strip 报错
                llm_result = llm_call_common(gen_prompt, f"生成临时对手 {target_name} 档案", temp=0.6, max_tokens=1200, timeout=60)
                raw_text = get_llm_content(llm_result)
                if not raw_text or not isinstance(raw_text, str):
                    raw_text = "{}"
                
                # 标准化JSON清洗
                clean_str = raw_text.strip()
                pat = r"```(?:json)?\s*([\s\S]*?)\s*```"
                res_match = re.search(pat, clean_str)
                if res_match:
                    clean_str = res_match.group(1).strip()
                first = clean_str.find("{")
                last = clean_str.rfind("}")
                if first != -1 and last > first:
                    clean_str = clean_str[first:last+1]
                
                try:
                    target_npc = json.loads(clean_str)
                    # 强制采用干净名（不带括号），防止AI生成错名或带括号脏名
                    target_npc["name"] = target_name
                    if "body_status" not in target_npc:
                        target_npc["body_status"] = "normal"
                    if _level_hint and _level_hint in _REALM_14:
                        # 双保险：程序层直接锁定境界档，不依赖AI遵守
                        target_npc["level"] = _level_hint
                        if isinstance(target_npc.get("martial_skills"), list) and target_npc["martial_skills"]:
                            target_npc["martial_skills"][0]["skill_level"] = _level_hint
                        print(f"[临时NPC] 括号控档生效：{target_name} → {_level_hint}")
                except Exception:
                    # 生成失败兜底模板
                    target_npc = {
                        "name": target_name,
                        "identity": "江湖路人",
                        "level": "初学入门",
                        "personality": "性情普通，无特殊特点",
                        "life_experience": "行走江湖，来历不明",
                        "secret": "无",
                        "initial_favor": 15,
                        "memory_list": [],
                        "martial_skills": [{"skill_name": "基础入门拳", "skill_level": "初学入门"}],
                        "relation_to_player": ""
                    }

            player_obj = get_player()
            if not player_obj:
                return jsonify({"status": "error", "message": "无法获取玩家数据，请先创建角色。"})
            player_data_raw = player_obj.to_dict()

            # Fix 7: 从最近5轮日志中提取当前场景信息（地点/时辰/日期）
            _battle_ctx = load_context_cache() or {}
            _battle_logs = _battle_ctx.get("interact_log", [])[-5:] if _battle_ctx else []
            _battle_loc = "未记录"
            _battle_time = "未记录"
            for _b_log in reversed(_battle_logs):
                if _battle_loc == "未记录":
                    _b_m = re.search(r"【地点变更】\s*([^【\n]+)", _b_log)
                    if _b_m:
                        _battle_loc = _b_m.group(1).strip()
                if _battle_time == "未记录":
                    _b_m = re.search(r"【时间变更】\s*([^【\n]+)", _b_log)
                    if _b_m:
                        _battle_time = _b_m.group(1).strip()
                if _battle_loc != "未记录" and _battle_time != "未记录":
                    break
            _battle_scene_info = f"时辰：{_battle_time}\n地点：{_battle_loc}\n日期：{player_obj.novel_node}"

            WEB_BATTLE_STATE["active"] = True
            WEB_BATTLE_STATE["target_name"] = target_name
            WEB_BATTLE_STATE["target_npc"] = target_npc
            WEB_BATTLE_STATE["player_data_raw"] = player_data_raw
            WEB_BATTLE_STATE["total_process"] = ""
            WEB_BATTLE_STATE["last_round"] = ""
            WEB_BATTLE_STATE["round_num"] = 0
            WEB_BATTLE_STATE["battle_style"] = ""
            WEB_BATTLE_STATE["phase"] = "select_mode"
            WEB_BATTLE_STATE["scene_info"] = _battle_scene_info
            # ★ 保存战前最新剧情，供首轮DC判定使用（last_round在首轮为空）
            _pre_plot = CURRENT_PLOT_TEXT or ""
            if not _pre_plot:
                try:
                    with open("data/latest_plot.txt", "r", encoding="utf-8") as _f:
                        _pre_plot = _f.read().strip()
                except Exception:
                    pass
            WEB_BATTLE_STATE["pre_battle_plot"] = _pre_plot[-500:] if _pre_plot else ""
            return jsonify({
                "status": "success",
                "plot": f"⚔️ 即将与【{target_name}】对决，请选择战斗模式：\n\n1. 比武切磋（点到即止，切磋武学）\n2. 死斗（生死相搏，招招致命）\n3. 暗中偷袭（先手突袭，阴招暗算）\n4. 擂台竞技（有裁判，规则约束）\n5. 江湖群斗（混战无规则）\n6. 退出对战",
                "battle_action": "require_input"
            })

        # 【修改点4】战斗拦截（仅在 active=True 且不是“对战”指令时触发）
        if WEB_BATTLE_STATE["active"]:
            print(f"[DEBUG] 战斗状态 active=True，用户输入: {user_action}")
            try:
                result = handle_battle_action(user_action, dice_confirm=dice_confirm)
                print(f"[DEBUG] handle_battle_action 返回类型: {result['type']}")
                
                if result["type"] == "dice_pending":
                    return jsonify({
                        "status": "dice_pending",
                        "dice_check": result["dice_check"],
                        "plot": result["msg"],
                        "battle_action": "require_input"
                    })
                elif result["type"] == "round":
                    _resp = {"status": "success", "plot": result["msg"], "battle_action": "require_input"}
                    if result.get("dice_result"):
                        _resp["dice_result"] = result["dice_result"]
                    return jsonify(_resp)
                elif result["type"] == "info":
                    return jsonify({"status": "success", "plot": result["msg"]})
                elif result["type"] == "end":
                    print("[DEBUG] 战斗正常结束，重置状态")
                    reset_web_battle()
                    return jsonify({"status": "success", "plot": result["msg"]})
                else:
                    print(f"[WARN] 战斗返回未知类型: {result['type']}")
                    return jsonify({"status": "success", "plot": f"【系统】{result['msg']}", "battle_action": "require_input"})
            except Exception as e:
                print(f"[ERROR] 战斗处理异常: {e}")
                # 【修改点5】异常发生时强制重置，避免死锁
                print("[DEBUG] 异常发生，强制重置战斗状态")
                reset_web_battle()
                return jsonify({
                    "status": "success", 
                    "plot": f"【系统】战斗处理遇到异常（{e}），已自动退出战斗。",
                })


    # ===== 查询历史指令 =====
        if user_action.startswith("查询历史"):
            parts = user_action.split()
            if len(parts) < 2:
                return jsonify({
                    "status": "error",
                    "message": "用法：查询历史 <轮次>，例如：查询历史 500"
                })
            try:
                round_num = int(parts[1])
                if round_num < 1:
                    return jsonify({"status": "error", "message": "轮次必须大于0"})
            
                archive_path = find_archive_for_round(round_num)
                if not archive_path:
                    return jsonify({
                        "status": "success",
                        "plot": f"【提示】未找到第 {round_num} 轮的历史归档（需要达到100轮后才会生成归档文件）。"
                    })
            
                data = load_archive_summary(archive_path)
                if not data:
                    return jsonify({"status": "error", "message": "读取归档失败"})
            
                # 构建HTML格式的显示内容
                html_content = f"""
                <div style="border-left: 3px solid #4ff; padding-left: 15px;">
                    <h3>📜 历史档案：{data.get('round_range', '')}</h3>
                """
            
                # 章节摘要
                chapter = data.get("chapter_summary", {})
                if chapter:
                    html_content += f"""
                    <div style="margin: 10px 0;">
                        <b style="color: #4ff;">【章节摘要】</b><br>
                        <span style="color: #fff;">{chapter.get('summary', '无摘要')[:300]}...</span>
                    </div>
                    """
            
                # 大事记
                milestones = data.get("milestones", [])
                if milestones:
                    html_content += f"""
                    <div style="margin: 10px 0;">
                        <b style="color: #ff4;">【大事记】</b><br>
                        <ul style="margin: 5px 0; color: #ff4;">
                            {''.join([f'<li>{m}</li>' for m in milestones[:10]])}
                        </ul>
                    </div>
                    """
            
                # 人物状态
                bio = data.get("biography", {})
                protagonist = bio.get("protagonist", {})
                if protagonist:
                    html_content += f"""
                    <div style="margin: 10px 0;">
                        <b style="color: #4f4;">【人物状态】</b><br>
                        <span style="color: #4f4;">姓名：{protagonist.get('name', '未知')}</span><br>
                        <span style="color: #4f4;">身份：{protagonist.get('identity', '未知')}</span>
                    """
                    allies = protagonist.get("allies", [])
                    if allies:
                        html_content += f'<span style="color: #4f4;">盟友：{", ".join(allies)}</span><br>'
                    enemies = protagonist.get("enemies", [])
                    if enemies:
                        html_content += f'<span style="color: #f44;">敌人：{", ".join(enemies)}</span><br>'
                    html_content += "</div>"
            
                html_content += "</div>"
            
                return jsonify({"status": "success", "plot": html_content})
            
            except ValueError:
                return jsonify({"status": "error", "message": "请输入有效的轮次数字"})

        # ===== 任务系统指令（Web 版） =====
        if user_action == "任务":
            data = get_task_list_data()
            return jsonify({
                "status": "success",
                "plot": data["text"],
                "is_task_panel": True,
                "tasks": data["tasks"]
            })
        
        elif user_action.startswith("task_action"):
            parts = user_action.split("|")
            if len(parts) < 3:
                return jsonify({"status": "error", "message": "任务操作格式错误"})
            
            action = parts[1]
            task_name = parts[2]
            
            success = False
            result_msg = "未知操作"
            
            try:
                if action == "complete":
                    success, result_msg, stage_hist = complete_task(task_name)
                    if success:
                        # AI 任务总结 + 写入上下文 + 上传云向量（公共函数）
                        task_summary = generate_task_summary(task_name, stage_hist)
                        if task_summary:
                            result_msg += f"\n\n【任务总结】\n{task_summary}"
                elif action == "delete":
                    success, result_msg = delete_task(task_name)
                elif action == "toggle_type":
                    tasks = _load_tasks()
                    found = False
                    for t in tasks:
                        if t["name"] == task_name and t["status"] == "active":
                            current = t.get("type", "side")
                            new_type = "main" if current != "main" else "side"
                            success, result_msg = set_task_type(task_name, new_type)
                            found = True
                            break
                    if not found:
                        result_msg = f"未找到活跃任务「{task_name}」"
                elif action == "toggle_suspend":
                    success, result_msg = toggle_task_suspend(task_name)
                elif action == "update_progress":
                    import re
                    
                    # 清理所有参数（去除空格、换行、不可见字符）
                    clean_parts = []
                    for p in parts:
                        p = p.strip().replace('\r', '').replace('\n', '').replace('\x00', '')
                        # 全角数字转半角
                        fw_map = str.maketrans('０１２３４５６７８９', '0123456789')
                        p = p.translate(fw_map)
                        clean_parts.append(p)
                    
                    stage = ""
                    percent = None
                    
                    def is_digit_str(s):
                        return bool(re.match(r'^\d+$', s))
                    
                    if len(clean_parts) == 4:
                        param = clean_parts[3]
                        if is_digit_str(param):
                            num = int(param)
                            if 0 <= num <= 100:
                                percent = num
                            else:
                                result_msg = "❌ 进度必须在 0-100 之间"
                                data = get_task_list_data()
                                return jsonify({
                                    "status": "success",
                                    "plot": f"{'✅' if success else '❌'} {result_msg}\n\n" + data["text"],
                                    "is_task_panel": True,
                                    "tasks": data["tasks"]
                                })
                        else:
                            stage = param
                    elif len(clean_parts) >= 5:
                        stage = clean_parts[3]
                        if len(clean_parts) > 4 and is_digit_str(clean_parts[4]):
                            num = int(clean_parts[4])
                            if 0 <= num <= 100:
                                percent = num
                            else:
                                result_msg = "❌ 进度必须在 0-100 之间"
                                data = get_task_list_data()
                                return jsonify({
                                    "status": "success",
                                    "plot": f"{'✅' if success else '❌'} {result_msg}\n\n" + data["text"],
                                    "is_task_panel": True,
                                    "tasks": data["tasks"]
                                })
                    else:
                        result_msg = "❌ 参数不足"
                        data = get_task_list_data()
                        return jsonify({
                            "status": "success",
                            "plot": f"{'✅' if success else '❌'} {result_msg}\n\n" + data["text"],
                            "is_task_panel": True,
                            "tasks": data["tasks"]
                            })
                    
                    success = update_task_progress(task_name, stage, percent, replace=True)
                    result_msg = f"✅ 任务「{task_name}」已更新" if success else f"❌ 更新失败"
                else:
                    result_msg = f"未知操作：{action}"
            except Exception as e:
                success = False
                result_msg = f"操作异常：{str(e)}"
            
            data = get_task_list_data()
            return jsonify({
                "status": "success",
                "plot": f"{'✅' if success else '❌'} {result_msg}\n\n" + data["text"],
                "is_task_panel": True,
                "tasks": data["tasks"]
            })
        
        elif user_action.startswith("add_npc"):
            from main import add_npc_manual
            parts = user_action.split("|")
            name = parts[1].strip() if len(parts) > 1 else ""
            if not name:
                return jsonify({"status": "success", "plot": "❌ NPC姓名不能为空"})
            identity = parts[2].strip() if len(parts) > 2 else "江湖人士"
            fav = int(parts[3]) if len(parts) > 3 and parts[3].lstrip("-").isdigit() else 15
            success, msg = add_npc_manual(name, identity, "", fav)
            return jsonify({"status": "success", "plot": msg})
        elif user_action == "选择主线":
            from mainline_dynamic import list_upcoming_mainlines
            return jsonify({"status": "success", "plot": list_upcoming_mainlines()})
        elif user_action == "主线完成":
            from mainline_dynamic import mark_last_event_completed
            success = mark_last_event_completed()
            if success:
                return jsonify({"status": "success", "plot": "✅ 主线事件已标记为完成，主线剧情将继续推进。"})
            else:
                return jsonify({"status": "success", "plot": "❌ 暂无进行中的主线事件需要完成。"})
        elif user_action.startswith("跳转主线"):
            parts = user_action.split()
            if len(parts) >= 2 and parts[1].isdigit():
                from mainline_dynamic import set_mainline_skip
                success, msg = set_mainline_skip(int(parts[1]))
                return jsonify({"status": "success", "plot": msg})
            return jsonify({"status": "success", "plot": "❌ 用法：跳转主线 编号"})
        elif user_action.startswith("new_task"):
            parts = user_action.split("|")
            if len(parts) < 3:
                return jsonify({"status": "success", "plot": "❌ 格式错误\n\n" + generate_task_panel_html(), "is_task_panel": True})
            name = parts[1].strip()
            desc = parts[2].strip() if len(parts) > 2 else ""
            if not name:
                return jsonify({"status": "success", "plot": "❌ 任务名称不能为空\n\n" + generate_task_panel_html(), "is_task_panel": True})
            try:
                success, result_msg = create_task(name, desc)
            except Exception as e:
                success = False
                result_msg = f"创建任务异常：{str(e)}"
            data = get_task_list_data()
            return jsonify({
                "status": "success",
                "plot": f"{'✅' if success else '❌'} {result_msg}\n\n" + data["text"],
                "is_task_panel": True,
                "tasks": data["tasks"]
            })
        # ===== 快捷指令（特殊处理） =====
        if user_action == "等级":
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                query_player_level()
            raw_text = f.getvalue()
            formatted_text = raw_text.replace("\033[91m", '<span style="color:#f44">').replace("\033[92m", '<span style="color:#4f4">').replace("\033[93m", '<span style="color:#ff4">').replace("\033[94m", '<span style="color:#44f">').replace("\033[95m", '<span style="color:#f4f">').replace("\033[96m", '<span style="color:#4ff">').replace("\033[97m", '<span style="color:#fff">').replace("\033[0m", '</span>')
            return jsonify({"status": "success", "plot": formatted_text})
        elif user_action == "当前主线":
            from mainline_dynamic import get_pending_mainline
            return jsonify({"status": "success", "plot": get_pending_mainline()})
        elif user_action == "功法":
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                query_player_skill()
            raw_text = f.getvalue()
            formatted_text = raw_text.replace("\033[91m", '<span style="color:#f44">').replace("\033[92m", '<span style="color:#4f4">').replace("\033[93m", '<span style="color:#ff4">').replace("\033[94m", '<span style="color:#44f">').replace("\033[95m", '<span style="color:#f4f">').replace("\033[96m", '<span style="color:#4ff">').replace("\033[97m", '<span style="color:#fff">').replace("\033[0m", '</span>')
            # 追加境界和瓶颈信息
            player = get_player()
            extra_info = ""
            if player:
                realm = player.overall_realm
                level = player.bottleneck_level
                progress = player.bottleneck_progress
                threshold = player.get_bottleneck_threshold()
                if level > 0:
                    bottleneck_info = f"第 {level} 重，进度 {progress}/{threshold}"
                else:
                    bottleneck_info = "无瓶颈"
                extra_info = f'<br><span style="color:#ff4">【当前总境界】{realm}</span><br><span style="color:#ff4">【瓶颈状态】{bottleneck_info}</span>'
            formatted_text += extra_info
            
            return jsonify({"status": "success", "plot": formatted_text})
            
        elif user_action == "物品":
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                query_player_item()
            raw_text = f.getvalue()
            formatted_text = raw_text.replace("\033[91m", '<span style="color:#f44">').replace("\033[92m", '<span style="color:#4f4">').replace("\033[93m", '<span style="color:#ff4">').replace("\033[94m", '<span style="color:#44f">').replace("\033[95m", '<span style="color:#f4f">').replace("\033[96m", '<span style="color:#4ff">').replace("\033[97m", '<span style="color:#fff">').replace("\033[0m", '</span>')
            return jsonify({"status": "success", "plot": formatted_text})
            
        elif user_action == "传闻":
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                query_player_rumor()
            raw_text = f.getvalue()
            formatted_text = raw_text.replace("\033[91m", '<span style="color:#f44">').replace("\033[92m", '<span style="color:#4f4">').replace("\033[93m", '<span style="color:#ff4">').replace("\033[94m", '<span style="color:#44f">').replace("\033[95m", '<span style="color:#f4f">').replace("\033[96m", '<span style="color:#4ff">').replace("\033[97m", '<span style="color:#fff">').replace("\033[0m", '</span>')
            return jsonify({"status": "success", "plot": formatted_text})
        
        elif user_action == "练功":
            success, msg = do_practice(is_first_init=False)
            # 获取玩家当前境界和瓶颈信息
            player = get_player()
            if player:
                # 同步武功书的 bonus/grade（练功时检查，确保新武功数据准确）
                try:
                    _synced, _fallback, _fixed = player.sync_skill_bonus_from_book()
                    if _synced > 0:
                        player.save()
                        if _fixed > 0 or _fallback > 0:
                            print(f"[武功书] 练功同步{_synced}门，修正{_fixed}门境界，{_fallback}门兜底")
                except Exception as _e:
                    print(f"[武功书] 练功同步异常: {_e}")
                realm = player.overall_realm
                level = player.bottleneck_level
                progress = player.bottleneck_progress
                threshold = player.get_bottleneck_threshold()
                if level > 0:
                    bottleneck_info = f"【瓶颈】第 {level} 重，进度 {progress}/{threshold}"
                else:
                    bottleneck_info = "【瓶颈】无"
                info = f"\n【当前总境界】{realm}\n{bottleneck_info}"
            else:
                info = ""
            return jsonify({"status": "success", "plot": f"【练功结果】{msg}{info}"})
 # ==# ===== 存档管理命令（Web 版，使用 split） =====
        if user_action == "存档列表":
            from save_manager import list_saves
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                list_saves()
            raw = f.getvalue()
            html = raw.replace('\n', '<br>')
            return jsonify({"status": "success", "plot": html})

        elif user_action.startswith("存档 "):
            from save_manager import save_game
            parts = user_action.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return jsonify({"status": "error", "message": "存档名不能为空"})
            slot = parts[1].strip()
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                save_game(slot)
            raw = f.getvalue()
            html = raw.replace('\n', '<br>')
            return jsonify({"status": "success", "plot": html})

        elif user_action.startswith("读档 "):
            from save_manager import load_game
            parts = user_action.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return jsonify({"status": "error", "message": "存档名不能为空"})
            slot = parts[1].strip()
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                load_game(slot)
            raw = f.getvalue()
            html = raw.replace('\n', '<br>')
            return jsonify({
                "status": "success",
                "plot": html,
                "reload": True
            })

        elif user_action.startswith("删档 "):
            from save_manager import delete_save
            parts = user_action.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                return jsonify({"status": "error", "message": "存档名不能为空"})
            slot = parts[1].strip()
            import io
            from contextlib import redirect_stdout
            f = io.StringIO()
            with redirect_stdout(f):
                delete_save(slot)
            raw = f.getvalue()
            html = raw.replace('\n', '<br>')
            return jsonify({"status": "success", "plot": html})
        
        elif user_action == "配图":
            # ★★★ 兜底：CURRENT_PLOT_TEXT 为空时，依次从持久化文件、主模块内存变量读取 ★★★
            if not CURRENT_PLOT_TEXT:
                try:
                    with open("data/latest_plot.txt", "r", encoding="utf-8") as _f:
                        CURRENT_PLOT_TEXT = _f.read().strip()
                except Exception:
                    pass
            if not CURRENT_PLOT_TEXT:
                from main import latest_plot1_text
                CURRENT_PLOT_TEXT = latest_plot1_text
            # 优先用 Agnes 生成剧情配图（基于最近一轮剧情文字），失败回退 ASCII
            from image_generator import generate_plot_image
            img_path = generate_plot_image(CURRENT_PLOT_TEXT)
            if img_path:
                formatted_text = f'<div style="text-align:center;margin:8px 0;"><img src="{img_path}" class="plot-scene-img" alt="plot scene"></div>'
            else:
                import io
                from contextlib import redirect_stdout
                f = io.StringIO()
                with redirect_stdout(f):
                    draw_ascii(latest_plot=CURRENT_PLOT_TEXT)
                raw_art = f.getvalue()
                formatted_text = raw_art.replace("\033[91m", '<span style="color:#f44">').replace("\033[92m", '<span style="color:#4f4">').replace("\033[93m", '<span style="color:#ff4">').replace("\033[94m", '<span style="color:#44f">').replace("\033[95m", '<span style="color:#f4f">').replace("\033[96m", '<span style="color:#4ff">').replace("\033[97m", '<span style="color:#fff">').replace("\033[0m", '</span>')
            return jsonify({"status": "success", "plot": formatted_text})
        
        elif user_action.startswith("遗忘功法"):
            parts = user_action.split(maxsplit=1)
            idx = 1
            if len(parts) > 1 and parts[1].strip().isdigit():
                idx = int(parts[1].strip())
    
            player = get_player()
            if not player:
                return jsonify({"status": "error", "message": "未读取到玩家存档"})
            skill_list = player.martial_skill_list
            if not skill_list:
                return jsonify({"status": "success", "plot": "【提示】暂无习得任何功法，无需遗忘。"})
            if idx < 1 or idx > len(skill_list):
                return jsonify({"status": "error", "message": f"无效序号：{idx}，有效范围 1-{len(skill_list)}"})
            target_skill = skill_list.pop(idx-1)
            player.martial_skill_list = skill_list
            # 联动清空装备槽
            try:
                from equipment_manager import EquipmentManager
                cleared = EquipmentManager.clear_if_equipped(player, skill_name=target_skill['skill_name'])
                if cleared:
                    player.save()
            except Exception:
                pass
            if not skill_list:
                player.overall_martial_level = "初窥门径"
            else:
                player.sync_overall_level()  # 重新计算整体修为
            player.save()
            extra_msg = "所有功法已遗忘，整体修为重置为：初窥门径。" if not skill_list else ""
            return jsonify({"status": "success", "plot": f"【系统提示】成功遗忘功法：{target_skill['skill_name']}。{extra_msg}"})
        
        elif user_action.startswith("扔掉物品"):
            parts = user_action.split(maxsplit=1)
            idx = 1
            if len(parts) > 1 and parts[1].strip().isdigit():
                idx = int(parts[1].strip())
            player = get_player()
            if not player:
                return jsonify({"status": "error", "message": "未读取到玩家存档"})
            raw_items = player.item_list
            valid_items = [it for it in raw_items if it.strip() != "" and it.strip() != "无"]
            if not valid_items:
                return jsonify({"status": "success", "plot": "【提示】背包为空，无需扔掉物品。"})
            if idx < 1 or idx > len(valid_items):
                return jsonify({"status": "error", "message": f"无效序号：{idx}，有效范围 1-{len(valid_items)}"})
            target_item = valid_items[idx-1]
            player.item_list.remove(target_item)  # 直接从列表移除
            # 联动清空装备槽
            try:
                from equipment_manager import EquipmentManager
                cleared = EquipmentManager.clear_if_equipped(player, item_name=target_item)
                if cleared:
                    player.save()
            except Exception:
                pass
            player.save()
            return jsonify({"status": "success", "plot": f"【系统提示】成功扔掉物品：{target_item}。"})
            
        elif user_action == "存档":
            return jsonify({"status": "success", "plot": "【系统】当前进度已自动安全保存至本地文件（data/ 目录）。"})

        
        elif user_action == "exit":
            return jsonify({"status": "success", "plot": "【系统】已安全断开连接，所有进度已自动保存完毕。"})

        else:
            # ===== 普通剧情交互：调用 process_one_round =====
            # ========== 骰子确认状态机 V4（Web端专用，武功品阶+境界双值） ==========
            global WEB_DICE_PENDING

            # P1: 有骰子待确认 + 用户确认掷骰
            if WEB_DICE_PENDING and dice_confirm is True:
                pending = WEB_DICE_PENDING
                WEB_DICE_PENDING = None
                # 执行 V4 检定（传入预设武功名和DC，跳过重复AI判定）
                _pobj = get_player()
                _l1_scene = CURRENT_PLOT_TEXT[-300:] if CURRENT_PLOT_TEXT else ""
                try:
                    _check_result = dice_resolve_check_v4(
                        player_obj=_pobj,
                        user_action=pending["original_action"],
                        l1_scene=_l1_scene,
                        llm_func=llm_call_common,
                        preset_skill_name=pending.get("skill_name"),
                        preset_dc=pending.get("dc"),
                        preset_dc_reason=pending.get("dc_reason"),
                        classified_skills=pending.get("classified_skills"),
                    )
                except Exception as _e:
                    print(f"[骰子V4] 检定异常: {_e}")
                    _check_result = None

                if _check_result:
                    # 将约束文本和结果存入 dice_system 模块变量，供 main.py 读取
                    dice_system.WEB_PROCESSED_CONSTRAINT_V4 = _check_result["constraint_text"]
                    dice_system.WEB_PROCESSED_RESULT_V4 = {
                        "skill_name": _check_result["skill_name"],
                        "skill_level": _check_result["skill_level"],
                        "grade": _check_result["grade"],
                        "base_bonus": _check_result["base_bonus"],
                        "skill_bonus": _check_result["skill_bonus"],
                        "realm_bonus": _check_result["realm_bonus"],
                        "total_modifier": _check_result["total_modifier"],
                        "dc": _check_result["dc"],
                        "dc_reason": _check_result.get("dc_reason", ""),
                        "dice_natural": _check_result["dice_natural"],
                        "dice_total": _check_result["dice_total"],
                        "dice_rolls": _check_result["dice_rolls"],
                        "delta": _check_result["delta"],
                        "verdict_grade": _check_result["verdict_grade"],
                        "verdict": _check_result["verdict"],
                        "verdict_narr": _check_result["verdict_narr"],
                        "effect_result": _check_result.get("effect_result"),
                        "effect_results": _check_result.get("effect_results"),
                    }
                    print(f"[骰子V4] 玩家确认掷骰，检定结果: {_check_result['verdict']}（第{_check_result['verdict_grade']}档）")
                else:
                    dice_system.WEB_PROCESSED_CONSTRAINT_V4 = ''
                    dice_system.WEB_PROCESSED_RESULT_V4 = None
                # 清除跳过标记（防止残留）
                dice_system.WEB_SKIPPED_V4 = False

            # P2: 有骰子待确认 + 用户跳过
            elif WEB_DICE_PENDING and dice_confirm is False:
                WEB_DICE_PENDING = None
                # 设置跳过标记，main.py 读取后跳过骰子检定
                dice_system.WEB_SKIPPED_V4 = True
                dice_system.WEB_PROCESSED_CONSTRAINT_V4 = ''
                dice_system.WEB_PROCESSED_RESULT_V4 = None
                print("[骰子V4] 玩家跳过掷骰")

            # P3: 无待确认 + 新行动 → 正则匹配武功名 + AI给DC
            else:
                WEB_DICE_PENDING = None
                dice_clear_web_state_v4()

                # V4: 正则检测武功名（不用AI），命中后再让AI给DC
                if not dice_should_skip(user_action):
                    _pobj = get_player()
                    _classified_skills = dice_detect_martial_skill_classified(
                        user_action, _pobj.martial_skill_list if _pobj else [], _pobj
                    )
                    _matched_skills = _classified_skills.get("all_matched", [])

                    if _matched_skills:
                        # 取主攻击武功（分类选择后）
                        _skill_name = _classified_skills.get("primary_attack") or _matched_skills[0]
                        _skill_info = _pobj.get_skill_info(_skill_name)
                        if _skill_info:
                            _skill_level = _skill_info["skill_level"]
                            _grade = _skill_info["grade"]
                            _skill_bonus = _skill_info["bonus"]
                            _realm_bonus = _skill_info["realm_bonus"]
                        else:
                            _skill_level = _pobj.overall_realm if _pobj else "初学入门"
                            _grade = 0
                            _skill_bonus = 0
                            _realm_bonus = 0
                        _base_bonus = _pobj.base_bonus if _pobj else 0
                        _total_mod = _base_bonus + _skill_bonus + _realm_bonus

                        # 增幅检定预览（用于面板显示）
                        _inner_name = _classified_skills.get("primary_inner", "")
                        _light_name = _classified_skills.get("primary_light", "")
                        _inner_info = _pobj.get_skill_info(_inner_name) if _inner_name else None
                        _light_info = _pobj.get_skill_info(_light_name) if _light_name else None
                        _amp_total, _amp_detail = dice_system.compute_amplify_bonus(
                            attack_total=_total_mod,
                            inner_info=_inner_info,
                            light_info=_light_info,
                        )
                        _amp_display = ""
                        if _amp_total:
                            _total_mod = _total_mod + _amp_total
                            _amp_parts = []
                            if _inner_name:
                                _amp_parts.append(f"内功{_inner_name}")
                            if _light_name:
                                _amp_parts.append(f"轻功{_light_name}")
                            _amp_display = f"\n增幅检定: {'+'.join(_amp_parts)} → +{_amp_total}"
                            print(f"[骰子V4] 增幅检定: 内功={_inner_name or '无'}, 轻功={_light_name or '无'}, 增幅=+{_amp_total}")

                        # AI只给DC
                        _l1_scene = CURRENT_PLOT_TEXT[-300:] if CURRENT_PLOT_TEXT else ""
                        _active_npcs_brief = dice_system.build_active_npcs_brief(
                            load_json(NPC_AGENT_FILE), user_action, _l1_scene
                        )
                        try:
                            _dc, _dc_reason = dice_ai_judge_dc_only(
                                llm_func=_llm_dc_low_temp,
                                scene=_l1_scene,
                                user_action=user_action,
                                skill_name=_skill_name,
                                skill_level=_skill_level,
                                grade=_grade,
                                skill_list_summary=_pobj.get_skill_list_summary() if _pobj else [],
                                overall_realm=_pobj.overall_realm if _pobj else "初学入门",
                                active_npcs_text=_active_npcs_brief,
                            )
                        except Exception as _e:
                            print(f"[骰子V4] AI DC判定异常: {_e}")
                            _dc, _dc_reason = dice_system._fallback_dc(user_action), ""
                        print(f"[骰子V4] 正则命中武功「{_skill_name}」, AI判定DC={_dc}({_dc_reason})")

                        WEB_DICE_PENDING = {
                            "original_action": user_action,
                            "skill_name": _skill_name,
                            "dc": _dc,
                            "dc_reason": _dc_reason,
                            "classified_skills": _classified_skills,
                        }
                        return jsonify({
                            "status": "dice_pending",
                            "dice_check": {
                                "skill_name": _skill_name,
                                "skill_level": _skill_level,
                                "grade": _grade,
                                "base_bonus": _base_bonus,
                                "skill_bonus": _skill_bonus,
                                "realm_bonus": _realm_bonus,
                                "total_modifier": _total_mod,
                                "amplify_total": _amp_total,
                                "inner_name": _inner_name,
                                "light_name": _light_name,
                                "dc": _dc,
                                "dc_reason": _dc_reason,
                            },
                            "plot": f"🎲 武功检定触发\n武功: {_skill_name}（{_skill_level}·品阶{_grade}级）\n基础修正: +{_base_bonus} | 武功加成: +{_skill_bonus + _realm_bonus}{_amp_display}\n总修正: +{_total_mod} vs DC{_dc}\n({_dc_reason})\n请确认是否掷骰？",
                        })
                    else:
                        # ★ 未命中武功名：标记跳过，阻止 main.py CLI兜底自动掷骰（确保无确认面板则不检定）
                        dice_system.WEB_SKIPPED_V4 = True
                else:
                    # ★ 系统命令（回归主线/等级/功法等）：标记跳过，阻止 main.py 对系统命令做骰子检定
                    dice_system.WEB_SKIPPED_V4 = True

            # ========== 地图目标地点提示注入（完整三级路径） ==========
            actual_user_action = user_action
            if WEB_MAP_TARGET and isinstance(WEB_MAP_TARGET, dict) and WEB_MAP_TARGET.get("full_path"):
                full_path = WEB_MAP_TARGET["full_path"]
                actual_user_action = f"（下一轮地点往{full_path}前进）{user_action}"
                print(f"【地图系统】已注入地点目标: {full_path}")
            # ========== DEBUG2 开始：锁等待计时 ==========
            lock_wait_start = time.time()
            print(f"【DEBUG-锁】等待获取 game_lock...")
            # ========== DEBUG2 结束 ==========

            with game_lock:
                # ========== DEBUG3 开始 ==========
                lock_wait_cost = time.time() - lock_wait_start
                print(f"【DEBUG-锁】已获取锁，排队等待耗时: {lock_wait_cost:.2f}s")
                process_start = time.time()
                # ========== DEBUG3 结束 ==========
                result = process_one_round(actual_user_action, is_web=True)
                # ========== DEBUG4 开始 ==========
                process_cost = time.time() - process_start
                print(f"【DEBUG-核心】剧情生成+处理耗时: {process_cost:.2f}s")
                # ========== DEBUG4 结束 ==========
            # ★★★ 更新最新剧情文本，供配图使用 ★★★
            CURRENT_PLOT_TEXT = result.get("plot", "")
            # ★★★ 持久化到文件：服务/worker 重启后配图仍可读取最近一轮剧情 ★★★
            if CURRENT_PLOT_TEXT:
                try:
                    os.makedirs("data", exist_ok=True)
                    with open("data/latest_plot.txt", "w", encoding="utf-8") as _f:
                        _f.write(CURRENT_PLOT_TEXT)
                except Exception:
                    pass
            # ========== DEBUG5 开始：总耗时统计 ==========
            total_cost = time.time() - req_start
            print(f"【DEBUG-总耗时】请求完成，接口总耗时: {total_cost:.2f}s")
            print(f"{'='*60}\n")
            # ========== DEBUG5 结束 ==========

            # 返回结果给前端
            return jsonify({"status": "success", **result})
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"操作异常：{str(e)}"})

# ======= 地图系统 API 路由 =======
@app.route('/map/get', methods=['GET'])
def api_map_get():
    """获取完整地图数据 + 玩家当前位置"""
    try:
        data = load_map_data()
        # 获取玩家当前位置
        try:
            loc_data = load_location_time()
            current_location = loc_data.get("location", "") if loc_data else ""
        except:
            current_location = ""
        return jsonify({
            "status": "success", 
            "data": data, 
            "target": WEB_MAP_TARGET,
            "current_location": current_location
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/map/add', methods=['POST'])
def api_map_add():
    """添加节点
    参数: parent_id (空=添加一级区域), name, level (1/2/3)
    """
    data = request.get_json()
    parent_id = data.get('parent_id', '').strip()
    name = data.get('name', '').strip()
    level = int(data.get('level', 1))
    
    if not name:
        return jsonify({"status": "error", "message": "名称不能为空"})
    
    try:
        map_data = load_map_data()
        
        if level == 1:
            # 添加一级区域
            new_node = {"id": _gen_map_id("r"), "name": name, "children": []}
            map_data["regions"].append(new_node)
        elif level == 2:
            # 添加二级城市
            parent = _find_node_by_id(map_data.get("regions", []), parent_id)
            if not parent:
                return jsonify({"status": "error", "message": "未找到父级区域"})
            if "children" not in parent:
                parent["children"] = []
            new_node = {"id": _gen_map_id("c"), "name": name, "children": []}
            parent["children"].append(new_node)
        elif level == 3:
            # 添加三级地点
            parent = _find_node_by_id(map_data.get("regions", []), parent_id)
            if not parent:
                return jsonify({"status": "error", "message": "未找到父级城市"})
            if "children" not in parent:
                parent["children"] = []
            new_node = {"id": _gen_map_id("l"), "name": name}
            parent["children"].append(new_node)
        else:
            return jsonify({"status": "error", "message": "无效级别"})
        
        save_map_data(map_data)
        return jsonify({"status": "success", "message": "添加成功", "data": map_data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/map/delete', methods=['POST'])
def api_map_delete():
    """删除节点"""
    data = request.get_json()
    node_id = data.get('node_id', '').strip()
    
    if not node_id:
        return jsonify({"status": "error", "message": "节点ID不能为空"})
    
    try:
        map_data = load_map_data()
        regions = map_data.get("regions", [])
        
        # 先尝试从一级列表删除
        for i, r in enumerate(regions):
            if r["id"] == node_id:
                del regions[i]
                save_map_data(map_data)
                # 如果删除的是当前目标，清空目标
                global WEB_MAP_TARGET
                if WEB_MAP_TARGET and WEB_MAP_TARGET.get("id") == node_id:
                    WEB_MAP_TARGET = None
                return jsonify({"status": "success", "message": "删除成功", "data": map_data})
        
        # 递归查找并删除
        def delete_from_list(node_list, target_id):
            for i, node in enumerate(node_list):
                if node["id"] == target_id:
                    del node_list[i]
                    return True
                if node.get("children"):
                    if delete_from_list(node["children"], target_id):
                        return True
            return False
        
        if delete_from_list(regions, node_id):
            save_map_data(map_data)
            if WEB_MAP_TARGET and WEB_MAP_TARGET.get("id") == node_id:
                WEB_MAP_TARGET = None
            return jsonify({"status": "success", "message": "删除成功", "data": map_data})
        
        return jsonify({"status": "error", "message": "未找到节点"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/map/rename', methods=['POST'])
def api_map_rename():
    """重命名地图节点"""
    global WEB_MAP_TARGET
    try:
        data = request.get_json()
        node_id = data.get('node_id', '').strip()
        new_name = data.get('new_name', '').strip()
        
        if not node_id or not new_name:
            return jsonify({"status": "error", "message": "参数不完整"})
        
        map_data = load_map_data()
        regions = map_data.get("regions", [])
        
        # 递归查找并更新节点名称
        def rename_node_in_list(node_list, target_id):
            for node in node_list:
                if node.get("id") == target_id:
                    old_name = node.get("name", "")
                    node["name"] = new_name
                    return True, old_name
                if node.get("children"):
                    found, old = rename_node_in_list(node["children"], target_id)
                    if found:
                        return True, old
            return False, None
        
        found, old_name = rename_node_in_list(regions, node_id)
        
        if found:
            save_map_data(map_data)
            # 如果重命名的是目标节点，更新full_path
            if WEB_MAP_TARGET and WEB_MAP_TARGET.get("id") == node_id:
                # 重新构建路径
                def find_and_build_path(node_list, target_id, path_parts):
                    for node in node_list:
                        current_path = path_parts + [node["name"]]
                        if node.get("id") == target_id:
                            return current_path
                        if node.get("children"):
                            result = find_and_build_path(node["children"], target_id, current_path)
                            if result:
                                return result
                    return None
                
                new_path_parts = find_and_build_path(regions, node_id, [])
                if new_path_parts:
                    WEB_MAP_TARGET["full_path"] = "·".join(new_path_parts)
                    # 更新对应层级的字段
                    if len(new_path_parts) >= 1: WEB_MAP_TARGET["region"] = new_path_parts[0]
                    if len(new_path_parts) >= 2: WEB_MAP_TARGET["city"] = new_path_parts[1]
                    if len(new_path_parts) >= 3: WEB_MAP_TARGET["location"] = new_path_parts[2]
            
            return jsonify({"status": "success", "message": f"已重命名：{old_name} → {new_name}", "data": map_data})
        
        return jsonify({"status": "error", "message": "未找到节点"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/map/set_target', methods=['POST'])
def api_map_set_target():
    """设置目标地点（支持完整三级路径）
    参数: level(1/2/3), id, region, city, location
    """
    global WEB_MAP_TARGET
    data = request.get_json()
    level = int(data.get('level', 3))
    node_id = data.get('id', '').strip()
    region = data.get('region', '').strip()
    city = data.get('city', '').strip()
    location = data.get('location', '').strip()
    
    if not node_id:
        WEB_MAP_TARGET = None
        return jsonify({"status": "success", "message": "已取消目标地点", "target": None})
    
    # 构建完整路径名称
    path_parts = []
    if region:
        path_parts.append(region)
    if city and level >= 2:
        path_parts.append(city)
    if location and level >= 3:
        path_parts.append(location)
    full_path = "·".join(path_parts) if path_parts else location or city or region
    
    WEB_MAP_TARGET = {
        "level": level,
        "id": node_id,
        "region": region,
        "city": city,
        "location": location,
        "full_path": full_path
    }
    return jsonify({"status": "success", "message": f"已设为目标：{full_path}", "target": WEB_MAP_TARGET})

@app.route('/map/get_target', methods=['GET'])
def api_map_get_target():
    """获取当前目标地点"""
    return jsonify({"status": "success", "target": WEB_MAP_TARGET})

# ======= 世界书 API =======
@app.route('/worldbook/status', methods=['GET'])
def api_worldbook_status():
    """获取世界书检索状态（供前端显示）
    worldbook.get_status() 返回的 key：ready/entries_count/keywords_count/last_build/groups
    前端期望的 key：status/total_entries/total_keywords/last_build_time
    此处做 key 映射，保持零侵入。
    """
    try:
        import worldbook
        s = worldbook.get_status()
        return jsonify({
            "status": "ready" if s.get("ready") else "not_ready",
            "total_entries": s.get("entries_count", 0),
            "total_keywords": s.get("keywords_count", 0),
            "last_build_time": s.get("last_build", ""),
            "groups": s.get("groups", {}),
            "semantic": s.get("semantic", {}),
        })
    except Exception:
        return jsonify({"status": "not_available", "total_entries": 0,
                        "total_keywords": 0, "last_build_time": ""})

@app.route('/worldbook/rebuild', methods=['POST'])
def api_worldbook_rebuild():
    """强制重建世界书索引"""
    try:
        import worldbook
        worldbook.rebuild()
        s = worldbook.get_status()
        return jsonify({"success": True,
                        "total_entries": s.get("entries_count", 0),
                        "total_keywords": s.get("keywords_count", 0),
                        "semantic": s.get("semantic", {}),
                        "message": "索引重建成功"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

# ======= 记事本 API =======
@app.route('/notepad/raw', methods=['GET'])
def api_notepad_raw():
    """获取记事本原始TXT内容"""
    try:
        if not os.path.exists(NOTEPAD_DATA_FILE):
            return jsonify({"status": "success", "content": ""})
        with open(NOTEPAD_DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"status": "success", "content": content})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/notepad/raw_save', methods=['POST'])
def api_notepad_raw_save():
    """保存记事本原始TXT内容"""
    data = request.get_json()
    content = data.get('content', '')
    try:
        with open(NOTEPAD_DATA_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"status": "success", "message": "保存成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ======= MD 文件 API（最小侵入，仅限项目根目录及 data/ 子目录）=======
_PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
_ALLOWED_SUBDIRS = ['', 'data']

def _is_safe_md_path(p):
    if not p or not p.endswith('.md'):
        return False
    if '..' in p.replace('\\', '/').split('/'):
        return False
    if os.path.isabs(p):
        return False
    if len(p) >= 2 and p[1] == ':':
        return False
    try:
        full = os.path.normpath(os.path.join(_PROJECT_ROOT, p))
        if not full.startswith(_PROJECT_ROOT):
            return False
        rel = os.path.relpath(full, _PROJECT_ROOT)
        rel_dir = os.path.dirname(rel)
        return rel_dir in _ALLOWED_SUBDIRS
    except Exception:
        return False

@app.route('/md/list', methods=['GET'])
def api_md_list():
    try:
        files = []
        for sub in _ALLOWED_SUBDIRS:
            base = os.path.join(_PROJECT_ROOT, sub) if sub else _PROJECT_ROOT
            if os.path.isdir(base):
                for f in sorted(os.listdir(base)):
                    if f.endswith('.md') and os.path.isfile(os.path.join(base, f)):
                        files.append(os.path.join(sub, f) if sub else f)
        return jsonify({"status": "success", "files": sorted(files)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/md/read', methods=['GET'])
def api_md_read():
    p = request.args.get('path', '')
    if not _is_safe_md_path(p):
        return jsonify({"status": "error", "message": "路径非法，仅允许项目根目录和 data/ 下的 .md 文件"})
    try:
        full = os.path.join(_PROJECT_ROOT, p)
        if not os.path.exists(full) or not os.path.isfile(full):
            return jsonify({"status": "error", "message": "文件不存在"})
        with open(full, 'r', encoding='utf-8') as f:
            return jsonify({"status": "success", "content": f.read()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/md/save', methods=['POST'])
def api_md_save():
    data = request.get_json() or {}
    p = data.get('path', '')
    content = data.get('content', '')
    if not _is_safe_md_path(p):
        return jsonify({"status": "error", "message": "路径非法"})
    try:
        full = os.path.join(_PROJECT_ROOT, p)
        with open(full, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"status": "success", "message": f"保存成功：{p}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ======= NPC 管理器 API =======
@app.route('/npc/list', methods=['GET'])
def api_npc_list():
    """获取NPC列表"""
    try:
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        npc_list = npc_data.get("npc_list", [])
        # 返回精简列表（只包含 name 和 identity）
        simplified = [{"name": n.get("name", ""), "identity": n.get("identity", "")} for n in npc_list]
        return jsonify({"status": "success", "npc_list": simplified})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/npc/get', methods=['GET'])
def api_npc_get():
    """获取单个NPC详情"""
    name = request.args.get('name', '')
    if not name:
        return jsonify({"status": "error", "message": "缺少NPC姓名参数"})
    try:
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        for npc in npc_data.get("npc_list", []):
            if npc.get("name") == name:
                return jsonify({"status": "success", "npc": npc})
        return jsonify({"status": "error", "message": f"NPC「{name}」不存在"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/npc/update', methods=['POST'])
def api_npc_update():
    """更新NPC数据"""
    data = request.get_json()
    name = data.get('name', '')
    npc_new = data.get('npc', {})
    if not name or not npc_new:
        return jsonify({"status": "error", "message": "参数不完整"})
    try:
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        found = False
        for i, npc in enumerate(npc_data.get("npc_list", [])):
            if npc.get("name") == name:
                npc_data["npc_list"][i] = npc_new
                found = True
                break
        if not found:
            return jsonify({"status": "error", "message": f"NPC「{name}」不存在"})
        save_json(NPC_AGENT_FILE, npc_data)
        return jsonify({"status": "success", "message": "保存成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/npc/delete', methods=['POST'])
def api_npc_delete():
    """删除NPC"""
    data = request.get_json()
    name = data.get('name', '')
    if not name:
        return jsonify({"status": "error", "message": "缺少NPC姓名参数"})
    try:
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        original_len = len(npc_data.get("npc_list", []))
        npc_data["npc_list"] = [n for n in npc_data.get("npc_list", []) if n.get("name") != name]
        if len(npc_data["npc_list"]) == original_len:
            return jsonify({"status": "error", "message": f"NPC「{name}」不存在"})
        save_json(NPC_AGENT_FILE, npc_data)
        return jsonify({"status": "success", "message": "删除成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/npc/add', methods=['POST'])
def api_npc_add():
    """新增NPC"""
    data = request.get_json()
    name = data.get('name', '').strip()
    identity = data.get('identity', '江湖人士').strip()
    initial_favor = int(data.get('initial_favor', 15))
    if not name:
        return jsonify({"status": "error", "message": "NPC姓名不能为空"})
    try:
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        # 检查是否已存在
        for npc in npc_data.get("npc_list", []):
            if npc.get("name") == name:
                return jsonify({"status": "error", "message": f"NPC「{name}」已存在"})
        # 添加新NPC
        npc_data["npc_list"].append({
            "name": name,
            "identity": identity,
            "personality": "",
            "life_experience": "",
            "secret": "",
            "initial_favor": max(-100, min(100, initial_favor)),
            "memory_list": [],
            "martial_skills": [],
            "body_status": "normal",
            "body_status_desc": "",
            "relation_to_player": ""
        })
        save_json(NPC_AGENT_FILE, npc_data)
        return jsonify({"status": "success", "message": "创建成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/npc/ai_generate', methods=['POST'])
def api_npc_ai_generate():
    """AI 辅助生成 NPC JSON（不写盘，返回前端编辑器供人工审核修改）"""
    import re as _re
    try:
        payload = request.get_json(force=True, silent=True) or {}
        desc = (payload.get('desc') or '').strip()
        if not desc:
            return jsonify({"status": "error", "message": "请输入人物描述"})

        sys_prompt = """你是武侠角色设定专家，擅长塑造符合金庸武侠世界观的江湖人物。
请根据用户描述，生成一个完整的 NPC 人物档案 JSON，严格遵循以下结构：

{
  "name": "人物姓名",
  "identity": "身份简介（30字内，如：红花会三当家，千手如来）",
  "personality": "性格描述（30字内，关键词式概括）",
  "life_experience": "简短身世经历（关键事件）",
  "secret": "人物隐秘心事/秘密",
  "initial_favor": 15,
  "memory_list": [],
  "martial_skills": [
    {"skill_name": "主武功名", "skill_level": "对应境界"}
  ],
  "body_status": "normal",
  "body_status_desc": "",
  "relation_to_player": "",
  "year": 出生年份整数
}

要求：
1. initial_favor 范围 -100 ~ 100，默认 15，敌对/仇家/恩人可适当调整
2. martial_skills 1-5 门，按重要性排序，主武功排第一
3. skill_level 必须从以下14档中选：初学入门、初窥门径、略有小成、略有所成、渐入佳境、融会贯通、登堂入室、炉火纯青、出神入化、登峰造极、超凡入圣、返璞归真、天人合一、破碎虚空
4. 清朝为低武世界，最高仅出神入化/登峰造极（宗师级4人）；明朝为中武世界，最高可达超凡入圣/返璞归真
5. year 为出生年份整数，按人物所属故事时代合理推算（书剑时代约1730-1750出生，飞狐外传约1745-1765，笑傲约1585-1605，侠客行约1595-1615，碧血约1615-1635）
6. 只输出纯 JSON，不要任何解释文字、不要 markdown 代码块标记"""

        user_prompt = f"请根据以下描述生成 NPC 人物档案：\n{desc}"

        # 加载最近10轮剧情，供AI参考当前场景
        try:
            _cache = load_context_cache() or {}
            _logs = _cache.get("interact_log", [])
            _recent = _logs[-10:] if len(_logs) >= 10 else _logs
            _plot_lines = []
            for _log in _recent:
                _m = _re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", _log, _re.S)
                if _m:
                    _plot_lines.append(_m.group(1).strip()[:100])
            if _plot_lines:
                recent_plot = "\n".join(_plot_lines)
                user_prompt += f"\n\n【最近剧情参考（请结合当前剧情场景设计NPC，使人物自然融入）】\n{recent_plot}"
        except Exception:
            pass

        llm_result = llm_call_common(sys_prompt, user_prompt, temp=0.6, max_tokens=1200, timeout=60)
        raw_text = get_llm_content(llm_result)
        if not raw_text or not isinstance(raw_text, str):
            return jsonify({"status": "error", "message": "AI 未返回有效内容"})

        # JSON 清洗
        clean_str = raw_text.strip()
        m = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
        if m:
            clean_str = m.group(1).strip()
        first = clean_str.find("{")
        last = clean_str.rfind("}")
        if first != -1 and last > first:
            clean_str = clean_str[first:last + 1]

        try:
            npc_data = json.loads(clean_str)
        except Exception:
            return jsonify({"status": "error", "message": "AI 返回的 JSON 解析失败，请重试或手动编辑"})

        # 补全/修正关键字段
        if not npc_data.get("name"):
            return jsonify({"status": "error", "message": "AI 生成的人物缺少 name 字段"})
        if "initial_favor" not in npc_data:
            npc_data["initial_favor"] = 15
        else:
            npc_data["initial_favor"] = max(-100, min(100, int(npc_data["initial_favor"])))
        if "memory_list" not in npc_data:
            npc_data["memory_list"] = []
        if not isinstance(npc_data.get("memory_list"), list):
            npc_data["memory_list"] = []
        if "body_status" not in npc_data:
            npc_data["body_status"] = "normal"
        if "body_status_desc" not in npc_data:
            npc_data["body_status_desc"] = ""
        if "relation_to_player" not in npc_data:
            npc_data["relation_to_player"] = ""
        if not isinstance(npc_data.get("martial_skills"), list):
            npc_data["martial_skills"] = []

        return jsonify({"status": "success", "npc": npc_data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"AI 生成失败：{str(e)}"})


@app.route('/npc/generate_avatar', methods=['POST'])
def api_npc_generate_avatar():
    """调用硅基流动 Kolors API 为 NPC 生成头像（180x180，白底转透明），覆盖已有头像"""
    import requests as _req
    import io as _io
    from PIL import Image as _Image
    from config import (KOLORS_IMG_API_URL, KOLORS_IMG_API_KEY, KOLORS_IMG_MODEL,
                        KOLORS_IMG_SIZE, KOLORS_AVATAR_SIZE)

    data = request.get_json()
    name = data.get('name', '').strip() if data else ''
    if not name:
        return jsonify({"status": "error", "message": "缺少NPC姓名参数"})

    try:
        # 1. 读取NPC数据，拼装提示词
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        target = None
        for npc in npc_data.get("npc_list", []):
            if npc.get("name") == name:
                target = npc
                break
        if not target:
            return jsonify({"status": "error", "message": f"NPC「{name}」不存在"})

        # 从 NPC JSON 所有字段构建英文提示词
        identity = target.get("identity", "")
        personality = target.get("personality", "")
        skills = target.get("martial_skills", [])
        skill_names = "/".join(s.get("skill_name", "") for s in skills[:3]) if skills else ""
        year = target.get("year", "")

        # 从 player.json 读取 novel_node 作为当前剧情时间线
        novel_node = ""
        try:
            player_data = load_json(PLAYER_FILE)
            if player_data:
                novel_node = player_data.get("novel_node", "")
        except Exception:
            pass

        prompt_parts = [f"Chinese traditional colorful ink wash painting portrait of {name}"]
        if identity:
            prompt_parts.append(f"identity: {identity}")
        if personality:
            prompt_parts.append(f"personality: {personality}")
        if skill_names:
            prompt_parts.append(f"martial arts: {skill_names}")
        if year:
            prompt_parts.append(f"born in {year}")
        if novel_node:
            prompt_parts.append(f"current storyline: {novel_node}")
        prompt_parts.append("wuxia style, detailed facial features, traditional Chinese clothing, no text, no watermark")
        prompt = ", ".join(prompt_parts)

        # 2. 调用 Kolors API
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KOLORS_IMG_API_KEY}",
        }
        payload = {
            "model": KOLORS_IMG_MODEL,
            "prompt": prompt,
            "image_size": KOLORS_IMG_SIZE,
            "batch_size": 1,
            "num_inference_steps": 20,
            "guidance_scale": 7.5,
        }
        print(f"[NPC头像] 正在为 {name} 生成头像...")
        resp = _req.post(KOLORS_IMG_API_URL, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        result = resp.json()
        images = result.get("images", [])
        if not images or not images[0].get("url"):
            return jsonify({"status": "error", "message": f"API返回异常: {str(result)[:200]}"})

        # 3. 下载图片
        img_url = images[0]["url"]
        img_resp = _req.get(img_url, timeout=120)
        img_resp.raise_for_status()
        image_data = img_resp.content

        # 4. 缩放至 180x180 + 白底转透明
        img = _Image.open(_io.BytesIO(image_data))
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        img = img.resize((KOLORS_AVATAR_SIZE, KOLORS_AVATAR_SIZE), _Image.LANCZOS)
        pixel_data = list(img.getdata())
        new_data = []
        for r, g, b, a in pixel_data:
            if r > 230 and g > 230 and b > 230:
                new_data.append((r, g, b, 0))
            else:
                new_data.append((r, g, b, a))
        img.putdata(new_data)

        # 5. 保存（覆盖已有）
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images", "npcs")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{name}.png")
        img.save(output_path, "PNG")
        web_path = f"/static/images/npcs/{name}.png"
        print(f"[NPC头像] 已生成: {web_path}")
        return jsonify({"status": "success", "path": web_path})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})


# ======= API 预设管理接口 =======
_PRESET_GROUPS = {
    "main_loop": {"prefix": "MAIN_LOOP", "options": ["A", "B", "C"]},
    "auxiliary": {"prefix": "AUX", "options": ["A", "B"]},
    "img_gen": {"prefix": "IMG_GEN", "options": ["A", "B"]},
}

@app.route('/api/presets', methods=['GET'])
def api_get_presets():
    """返回所有 API 预设组及其当前选择（不返回密钥）"""
    import os as _os
    result = {}
    for group, info in _PRESET_GROUPS.items():
        active = _os.getenv(f"{info['prefix']}_ACTIVE", "A")
        options = []
        for opt in info["options"]:
            label = _os.getenv(f"{info['prefix']}_{opt}_LABEL", f"选项{opt}")
            model = _os.getenv(f"{info['prefix']}_{opt}_MODEL", "")
            options.append({"key": opt, "label": label, "model": model})
        result[group] = {"active": active, "options": options}

    # Kolors（仅1个，展示状态）
    result["kolors"] = {
        "active": "A",
        "options": [{"key": "A", "label": "硅基流动 Kolors",
                      "model": _os.getenv("KOLORS_IMG_MODEL", "Kwai-Kolors/Kolors")}]
    }
    return jsonify({"status": "success", "presets": result})


@app.route('/api/presets/switch', methods=['POST'])
def api_switch_preset():
    """切换 API 预设（原子写入 .env，需重启服务生效）"""
    import os as _os
    import tempfile as _tempfile

    data = request.get_json()
    group = data.get('group', '')
    option = data.get('option', '')

    if group not in _PRESET_GROUPS:
        return jsonify({"status": "error", "message": f"未知预设组: {group}"})
    info = _PRESET_GROUPS[group]
    if option not in info["options"]:
        return jsonify({"status": "error", "message": f"未知选项: {option}"})

    env_prefix = info["prefix"]
    env_key = f"{env_prefix}_ACTIVE"

    try:
        env_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".env")
        if not _os.path.exists(env_path):
            return jsonify({"status": "error", "message": ".env 文件不存在"})

        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{env_key}=") and not stripped.startswith("#"):
                lines[i] = f"{env_key}={option}\n"
                found = True
                break

        if not found:
            lines.append(f"\n{env_key}={option}\n")

        # 原子写入：先写临时文件，再 rename
        fd, tmp_path = _tempfile.mkstemp(dir=_os.path.dirname(env_path), suffix=".tmp")
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(lines)
        _os.replace(tmp_path, env_path)
        # 同步更新内存环境变量，让 GET 接口立即反映新选择
        _os.environ[env_key] = option

        print(f"[API预设] {group} 切换到 {option}，需重启服务生效")
        return jsonify({"status": "success",
                         "message": f"已切换到选项{option}，需重启服务生效"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})


# ======= .env 全量编辑接口 =======

def _build_editable_schema():
    """构建可编辑环境变量的 schema（分组 + 字段元数据）"""
    schema = [
        {
            "group": "bailian",
            "label": "☁️ 阿里云百炼配置",
            "fields": [
                {"key": "DASHSCOPE_API_KEY", "label": "DashScope API Key", "type": "password"},
                {"key": "BAILIAN_PLOT_MEMORY_ID", "label": "剧情记忆库 ID", "type": "text"},
                {"key": "BAILIAN_WORLD_KNOWLEDGE_ID", "label": "世界知识库 ID", "type": "text"},
                {"key": "ENABLE_CLOUD_MEMORY", "label": "启用云记忆 (true/false)", "type": "text"},
                {"key": "CLOUD_MEM_SLOT_ID", "label": "云记忆槽位 ID", "type": "text"},
            ]
        },
    ]
    for gkey, glabel, prefix, options in [
        ("main_loop", "🔄 主循环（3选1）", "MAIN_LOOP", ["A", "B", "C"]),
        ("auxiliary", "🔧 辅助（2选1）", "AUX", ["A", "B"]),
        ("img_gen", "🖼️ 配图LLM（2选1）", "IMG_GEN", ["A", "B"]),
    ]:
        fields = [{"key": f"{prefix}_ACTIVE", "label": "当前选项", "type": "select", "options": options}]
        for opt in options:
            for suffix, slabel, stype in [
                ("LABEL", "标签", "text"),
                ("API_KEY", "API Key", "password"),
                ("BASE_URL", "Base URL", "text"),
                ("MODEL", "模型名", "text"),
                ("TIMEOUT", "超时(秒)", "text"),
            ]:
                fields.append({"key": f"{prefix}_{opt}_{suffix}", "label": f"{opt} · {slabel}", "type": stype})
        schema.append({"group": gkey, "label": glabel, "fields": fields})

    schema.append({
        "group": "kolors",
        "label": "🎨 Kolors 图片生成",
        "fields": [
            {"key": "KOLORS_IMG_API_URL", "label": "API URL", "type": "text"},
            {"key": "KOLORS_IMG_API_KEY", "label": "API Key", "type": "password"},
            {"key": "KOLORS_IMG_MODEL", "label": "模型名", "type": "text"},
            {"key": "KOLORS_IMG_SIZE", "label": "图片尺寸", "type": "text"},
        ]
    })
    return schema


def _update_env_keys(updates: dict):
    """原子写入多个 env key 到 .env 文件，同步更新 os.environ"""
    import tempfile as _tempfile
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        raise FileNotFoundError(".env 文件不存在")

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated_keys = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for key, value in updates.items():
            if stripped.startswith(f"{key}=") and key not in updated_keys:
                lines[i] = f"{key}={value}\n"
                updated_keys.add(key)
                break

    for key, value in updates.items():
        if key not in updated_keys:
            lines.append(f"{key}={value}\n")

    fd, tmp_path = _tempfile.mkstemp(dir=os.path.dirname(env_path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp_path, env_path)

    for key, value in updates.items():
        os.environ[key] = value


@app.route('/api/presets/env', methods=['GET'])
def api_get_env_config():
    """返回所有可编辑环境变量的 schema + 当前值（密码脱敏）"""
    schema = _build_editable_schema()
    for group in schema:
        for field in group["fields"]:
            val = os.getenv(field["key"], "")
            if field["type"] == "password" and val:
                field["value"] = "*" * max(len(val) - 4, 0) + val[-4:]
                field["masked"] = True
            else:
                field["value"] = val
                field["masked"] = False
    return jsonify({"status": "success", "schema": schema})


@app.route('/api/presets/env', methods=['POST'])
def api_update_env_config():
    """批量更新环境变量（原子写入 .env，跳过未修改的脱敏密码）"""
    data = request.get_json()
    updates = data.get('updates', {})
    if not updates:
        return jsonify({"status": "error", "message": "无更新内容"})

    schema = _build_editable_schema()
    valid_keys = set()
    password_keys = set()
    for group in schema:
        for field in group["fields"]:
            valid_keys.add(field["key"])
            if field["type"] == "password":
                password_keys.add(field["key"])

    filtered = {}
    skipped = []
    for key, value in updates.items():
        if key not in valid_keys:
            skipped.append(key)
            continue
        if key in password_keys and value.startswith("*"):
            skipped.append(key)
            continue
        filtered[key] = value

    if not filtered:
        return jsonify({"status": "success", "message": "无有效更改（密码未修改则跳过）", "skipped": skipped})

    try:
        _update_env_keys(filtered)
        changed = list(filtered.keys())
        print(f"[API预设] 批量更新 .env: {changed}（跳过: {skipped}），需重启服务生效")
        return jsonify({
            "status": "success",
            "message": f"已更新 {len(changed)} 项配置，需重启服务生效",
            "changed": changed,
            "skipped": skipped,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})


# ======= 初始化接口：加载最近一次历史剧情 =======
@app.route('/init', methods=['GET'])
def init_history():
    try:
        # ===== 1. 确保世界设定文件存在 =====
        world_data = build_novel_world()  # 若文件不存在则生成，若存在则加载
        # 若生成过程只返回内存数据而未写入文件（兜底情况），则强制保存
        if not os.path.exists(WORLD_FILE):
            save_json(WORLD_FILE, world_data)

        # ===== 2. 检查玩家档案是否已存在 =====
        if not Player.load():
            # 如果不存在，告诉前端需要创建角色
            return jsonify({
                "status": "success",
                "need_init": True,
                "history": "欢迎来到武侠世界！请先创建你的角色。"
            })

        # ===== 3. 如果存在，正常读取历史剧情 =====
        # 同步武功书的 bonus/grade 到 player.json（确保检定数据准确）
        try:
            _p = get_player()
            if _p:
                _synced, _fallback, _fixed = _p.sync_skill_bonus_from_book()
                if _synced > 0:
                    _p.save()
                    _msg_parts = [f"同步{_synced}门武功"]
                    if _fixed > 0:
                        _msg_parts.append(f"修正{_fixed}门境界")
                    if _fallback > 0:
                        _msg_parts.append(f"{_fallback}门不在书中(兜底)")
                    print(f"[武功书] {'，'.join(_msg_parts)}")
        except Exception as _e:
            print(f"[武功书] 同步异常（已忽略）: {_e}")
        cache = load_context_cache()
        if cache and "interact_log" in cache and len(cache["interact_log"]) > 0:
            last_records = cache["interact_log"][-2:]
            history_text = "\n\n".join(last_records)
            return jsonify({"status": "success", "history": history_text})

        return jsonify({
            "status": "success",
            "history": "你穿越到了《笑傲江湖》的世界，成为青城派的一名青年弟子。随着穿越，你脑海里还带着《北冥神功》的心法，现在离小说剧情正式开始开始还有1年……"
        })
    except Exception as e:
        print(f"[ERROR] 初始化异常: {e}")
        return jsonify({"status": "error", "history": "读取历史缓存失败，请刷新重试。"})
# ======= 武功书管理接口 =======
@app.route('/martial/guide', methods=['GET'])
def api_martial_guide():
    """返回武功品阶评判标准文档内容"""
    try:
        guide_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '武功品阶评判标准.md')
        with open(guide_path, 'r', encoding='utf-8') as f:
            return jsonify({'status': 'success', 'content': f.read()})
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)})

# ==================== 📜 任务管理 REST API（弹窗用，薄封装 task_manager） ====================

@app.route('/task/list', methods=['GET'])
def api_task_list():
    """任务列表（全量）"""
    try:
        tasks = _load_tasks()
        return jsonify({"status": "success", "tasks": tasks, "total": len(tasks)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/task/create', methods=['POST'])
def api_task_create():
    """创建任务"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        display_name = str(data.get("display_name", "")).strip()
        description = str(data.get("description", "")).strip()
        task_type = str(data.get("type", "side")).strip() or "side"
        if not display_name or not description:
            return jsonify({"status": "error", "message": "任务名称和描述不能为空"})
        ok, msg = create_task(display_name, description, task_type)
        return jsonify({"status": "success" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/task/progress', methods=['POST'])
def api_task_progress():
    """更新任务进度（阶段/百分比，字段可选）"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        name = str(data.get("name", "")).strip()
        if not name:
            return jsonify({"status": "error", "message": "缺少任务编号name"})
        percent = data.get("percent")
        if percent is not None:
            try:
                percent = int(percent)
            except (ValueError, TypeError):
                percent = None
        stage = data.get("stage")
        if stage is not None:
            stage = str(stage).strip() or None
        # 手动编辑：replace=True 直接覆盖阶段文本（默认False是AI累计追加模式）
        result = update_task_progress(name, stage=stage, percent=percent, replace=True)
        ok = result is True
        msg = "✅ 进度已更新" if ok else f"❌ 未找到进行中的任务「{name}」"
        return jsonify({"status": "success" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


def generate_task_summary(task_name, stage_hist):
    """AI生成任务总结 + 写入上下文缓存（作为正常交互轮数） + 上传云向量库
    返回: 总结文本（失败返回空字符串）"""
    try:
        print(f"[DEBUG 任务总结] 开始生成总结 for 任务「{task_name}」")
        print(f"[DEBUG 任务总结] 过程记录: {stage_hist}")
        cache = load_context_cache() or {}
        recent_logs = cache.get("interact_log", [])[-5:]
        recent_text = "\n\n".join(recent_logs) if recent_logs else "暂无"
        loc = load_location_time()
        location_name = loc.get("location", "江湖某处") if loc else "江湖某处"
        player = get_player()
        player_name = player.name if player else "李三奇"
        # 补查任务完整信息（description/display_name/type）
        task_info = get_task_info(task_name) or {}
        task_desc = task_info.get("description", "")
        display_name = task_info.get("display_name", task_name)
        task_type = task_info.get("type", "side")
        # 统计阶段数
        stage_hist_str = stage_hist if stage_hist else "暂无"
        stage_count = stage_hist_str.count("→") + 1 if stage_hist_str and stage_hist_str != "暂无" else 0
        summary_prompt = f"""请为玩家「{player_name}」完成的任务撰写一段180~200字的任务剧情总结。

【任务信息】
任务编号：{task_name}
任务名称：{display_name}
任务描述：{task_desc}
任务类型：{task_type}
任务地点：{location_name}

【过程记录】（共{stage_count}个阶段，请从中挑出3-8个关键转折点串联成文，不要全量罗列）
{stage_hist_str}

【近几轮剧情】（用于补充结局细节）
{recent_text[-500:]}

【写作要求】
1. 结构：起因(1句) → 关键转折(3-8句，只挑最重要的) → 结局(1句)。
2. 聚焦任务核心目标「{task_desc[:20]}」，与任务目标无关的支线事件（如途中遭遇战、旁支对话）一律略去。
3. 开篇首句必须点明「主角名 + 任务名称({display_name}) + 任务地点」，实体前置，不用「一桩差事」「此番际遇」这类模糊代称。
4. 第三人称叙事，金庸武侠文风，关键NPC、核心道具/奖励、任务结局必须用全称。
5. 结局必须明确（成功/失败/达成约定），禁止使用「暂歇」「将起」「未了」「待续」等未完成态词汇。
6. 严格控制在180~200字之间，超过210字视为失败。只输出正文，不要标题、序号。

输出："""
        print(f"[DEBUG 任务总结] Prompt长度: {len(summary_prompt)} 字")
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是武侠小说总结者。根据任务过程记录，写一段180~200字的任务剧情总结。"},
                {"role": "user", "content": summary_prompt}
            ],
            max_tokens=400, temperature=0.4, timeout=60,
            extra_body={"thinking": {"type": "disabled"}}
        )
        # 安全检查：message.content 可能为 None
        content = getattr(resp.choices[0].message, 'content', '') or ''
        task_summary = content.strip()
        if not task_summary:
            print("[DEBUG 任务总结] ⚠️ AI返回空内容")
            return ""
        # 写入上下文缓存（作为一条正常交互轮数的文本）
        update_context_cache(task_summary, user_action="任务完成")
        # 上传云向量库（含 novel_node）
        from cloud_memory_v2 import upload_task_memory
        _nn = ""
        try:
            _p = get_player()
            if _p and _p.novel_node:
                _nn = _p.novel_node
        except Exception:
            pass
        upload_task_memory(CLOUD_MEM_SLOT_ID, task_name, stage_hist, task_summary, novel_node=_nn)
        print(f"[DEBUG 任务总结] 完成，输出{len(task_summary)}字")
        return task_summary
    except Exception as e:
        print(f"[DEBUG 任务总结] ❌ 生成异常: {e}")
        return ""


@app.route('/task/complete', methods=['POST'])
def api_task_complete():
    try:
        data = request.get_json(force=True, silent=True) or {}
        result = complete_task(str(data.get("name", "")).strip())  # 三元组 (ok, msg, stage_hist)
        ok, msg = result[0], result[1]
        summary = ""
        if ok:
            summary = generate_task_summary(str(data.get("name", "")).strip(), result[2] if len(result) > 2 else "")
        return jsonify({"status": "success" if ok else "error", "message": msg, "summary": summary})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/task/delete', methods=['POST'])
def api_task_delete():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = delete_task(str(data.get("name", "")).strip())
        return jsonify({"status": "success" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/task/type', methods=['POST'])
def api_task_type():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = set_task_type(str(data.get("name", "")).strip(),
                                str(data.get("type", "side")).strip() or "side")
        return jsonify({"status": "success" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/task/suspend', methods=['POST'])
def api_task_suspend():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ok, msg = toggle_task_suspend(str(data.get("name", "")).strip())
        return jsonify({"status": "success" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/task/ai_generate', methods=['POST'])
def api_task_ai_generate():
    """AI生成任务（辅助LLM，生成→前端预填→人工确认后走 /task/create 落库）"""
    try:
        data = request.get_json(force=True, silent=True) or {}
        intent = str(data.get("intent", "")).strip()[:200]
        if not intent:
            return jsonify({"status": "error", "message": "请输入任务意图描述"})

        # 1) 近5轮剧情
        ctx_cache = load_context_cache() or {}
        recent_logs = ctx_cache.get("interact_log", [])[-5:]
        recent_text = "\n\n".join(recent_logs) if recent_logs else "（暂无近期剧情）"
        if len(recent_text) > 1500:
            recent_text = recent_text[-1500:]

        # 2) 当前地点/时辰/日期
        loc_data = load_location_time() or {}
        _loc = loc_data.get("location", "") or "未记录"
        _time = loc_data.get("time", "") or "未记录"
        _date = ""
        try:
            _pd = load_json(PLAYER_FILE) or {}
            _date = str(_pd.get("novel_node", ""))[:60] and str(_pd.get("novel_node", "")).split("，")[0]
        except Exception:
            pass
        scene_text = f"地点：{_loc}　时辰：{_time}　日期：{_date or '未记录'}"

        # 3) 主角信息（novel_node 剧情时间线 + 境界）
        protagonist = ""
        try:
            _pd = load_json(PLAYER_FILE) or {}
            _p_name = _pd.get("name", "主角")
            _p_level = _pd.get("level", "") or _pd.get("realm", "")
            _nn = str(_pd.get("novel_node", ""))[:250]
            protagonist = f"{_p_name}（{_p_level}）\n{_nn}" if _nn else f"{_p_name}（{_p_level}）"
        except Exception:
            protagonist = "（主角信息读取失败）"

        prompt = f"""你是武侠小说任务设计师。玩家提出了一个任务意图，你需要围绕该意图设计任务。

【玩家意图】（任务核心，最高优先级）
{intent}

【背景参考】（近5轮剧情，仅用于取材：人物、地点、伏笔的衔接，不是任务主题来源）
{recent_text}

【当前场景】
{scene_text}

【主角状态】
{protagonist}

【生成要求】
1. 任务必须直接围绕【玩家意图】展开：意图中的目标就是任务目标，意图中的对象就是任务对象；禁止抛开意图、从背景剧情里另起炉灶
2. 背景参考只用来让任务衔接自然（人物称呼、地点、时间线），不得反客为主
3. display_name：任务名，不超过12字，武侠风格，体现意图核心
4. description：任务描述，50~100字，写明目标、背景、涉及人物；可引入新的江湖人物或势力丰富线索
5. type：main（主线关键节点）或 side（支线），不确定时用 side
6. current_stage：初始阶段描述，不超过15字
7. progress_percent：初始进度，默认0

只输出标准JSON，格式：
{{"display_name": "", "description": "", "type": "", "current_stage": "", "progress_percent": 0}}"""

        raw_resp = llm_call_common(prompt, "AI生成任务", temp=0.6, max_tokens=600, timeout=60)
        raw_text = get_llm_content(raw_resp)
        if not raw_text or not isinstance(raw_text, str):
            return jsonify({"status": "error", "message": "AI未返回有效内容，请重试"})

        # JSON 清洗（剥代码块 + 首尾大括号，与NPC生成路由同款）
        import re as _re
        clean_str = raw_text.strip()
        m = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
        if m:
            clean_str = m.group(1).strip()
        first = clean_str.find("{")
        last = clean_str.rfind("}")
        if first != -1 and last > first:
            clean_str = clean_str[first:last + 1]
        try:
            task_data = json.loads(clean_str)
        except Exception:
            return jsonify({"status": "error", "message": "AI输出JSON解析失败，请重试"})
        if not isinstance(task_data, dict) or not task_data.get("display_name"):
            return jsonify({"status": "error", "message": "AI输出缺少任务名，请重试"})

        # 字段规整
        task_data["type"] = task_data.get("type") if task_data.get("type") in ("main", "side") else "side"
        task_data["display_name"] = str(task_data["display_name"]).strip()[:20]
        task_data["description"] = str(task_data.get("description", "")).strip()[:200]
        task_data["current_stage"] = str(task_data.get("current_stage", "")).strip()[:30]
        try:
            task_data["progress_percent"] = max(0, min(100, int(task_data.get("progress_percent", 0))))
        except (ValueError, TypeError):
            task_data["progress_percent"] = 0
        return jsonify({"status": "success", "task": task_data})
    except Exception as e:
        return jsonify({"status": "error", "message": f"生成失败：{e}"})


@app.route('/martial/list', methods=['GET'])
def api_martial_list():
    """获取武功列表（支持关键字/等级/类别筛选）"""
    try:
        keyword = request.args.get('keyword', '').strip().lower()
        grade = request.args.get('grade', '').strip()
        category = request.args.get('category', '').strip()
        data = load_martial_arts()
        arts = data.get("martial_arts", {})
        result = []
        for name, info in arts.items():
            if keyword and keyword not in name.lower() and keyword not in info.get("source","").lower():
                continue
            if grade and str(info.get("grade","")) != grade:
                continue
            if category and info.get("category","") != category:
                continue
            result.append({
                "name": name,
                "grade": info.get("grade", 0),
                "bonus": info.get("bonus", 0),
                "category": info.get("category", ""),
                "source": info.get("source", ""),
                "brief_desc": info.get("brief_desc", "")
            })
        # 按等级降序、名称升序
        result.sort(key=lambda x: (-x["grade"], x["name"]))
        return jsonify({"status": "success", "arts": result, "total": len(result)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/get', methods=['GET'])
def api_martial_get():
    """获取单个武功详情"""
    try:
        name = request.args.get('name', '').strip()
        if not name:
            return jsonify({"status": "error", "message": "缺少name参数"})
        data = load_martial_arts()
        arts = data.get("martial_arts", {})
        if name not in arts:
            return jsonify({"status": "error", "message": "武功不存在"})
        info = arts[name]
        return jsonify({
            "status": "success",
            "art": {
                "name": name,
                "grade": info.get("grade", 0),
                "bonus": info.get("bonus", 0),
                "category": info.get("category", ""),
                "source": info.get("source", ""),
                "note": info.get("_note", ""),
                "brief_desc": info.get("brief_desc", ""),
                "effect": info.get("effect", None),
                "special_move_name": info.get("special_move_name", ""),
                "special_move_desc": info.get("special_move_desc", "")
            },
            "grade_system": data.get("_grade_system", {}),
            "category_list": data.get("_category_list", [])
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/add', methods=['POST'])
def api_martial_add():
    """新增武功"""
    try:
        payload = request.get_json()
        name = payload.get('name', '').strip()
        if not name:
            return jsonify({"status": "error", "message": "武功名不能为空"})
        grade = int(payload.get('grade', 4))
        if grade not in MARTIAL_GRADE_BONUS:
            return jsonify({"status": "error", "message": "等级必须为1-9"})
        category = payload.get('category', 'fist').strip()
        source = payload.get('source', '').strip()
        note = payload.get('note', '').strip()
        brief_desc = payload.get('brief_desc', '').strip()
        effect = _parse_effect_from_payload(payload)
        data = load_martial_arts()
        arts = data.get("martial_arts", {})
        if name in arts:
            return jsonify({"status": "error", "message": "武功已存在"})
        entry = {
            "grade": grade,
            "bonus": MARTIAL_GRADE_BONUS[grade],
            "category": category,
            "source": source,
            "brief_desc": brief_desc
        }
        if note:
            entry["_note"] = note
        if effect:
            entry["effect"] = effect
        special_name = payload.get('special_move_name', '').strip()
        if special_name:
            entry["special_move_name"] = special_name
        special_desc = payload.get('special_move_desc', '').strip()
        if special_desc:
            entry["special_move_desc"] = special_desc
        arts[name] = entry
        data["martial_arts"] = arts
        save_martial_arts(data)
        clear_martial_arts_book_cache()
        _reload_effect_meta_safe()
        return jsonify({"status": "success", "message": "新增成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/update', methods=['POST'])
def api_martial_update():
    """更新武功（支持重命名）"""
    try:
        payload = request.get_json()
        old_name = payload.get('old_name', '').strip()
        new_name = payload.get('name', '').strip()
        if not old_name or not new_name:
            return jsonify({"status": "error", "message": "参数不完整"})
        grade = int(payload.get('grade', 4))
        if grade not in MARTIAL_GRADE_BONUS:
            return jsonify({"status": "error", "message": "等级必须为1-9"})
        category = payload.get('category', 'fist').strip()
        source = payload.get('source', '').strip()
        note = payload.get('note', '').strip()
        brief_desc = payload.get('brief_desc', '').strip()
        effect = _parse_effect_from_payload(payload)
        data = load_martial_arts()
        arts = data.get("martial_arts", {})
        if old_name not in arts:
            return jsonify({"status": "error", "message": "原武功不存在"})
        # 重命名冲突检查
        if new_name != old_name and new_name in arts:
            return jsonify({"status": "error", "message": "新名称已存在"})
        # 删除旧名（若改名）
        if new_name != old_name:
            del arts[old_name]
        entry = {
            "grade": grade,
            "bonus": MARTIAL_GRADE_BONUS[grade],
            "category": category,
            "source": source,
            "brief_desc": brief_desc
        }
        if note:
            entry["_note"] = note
        if effect:
            entry["effect"] = effect
        special_name = payload.get('special_move_name', '').strip()
        if special_name:
            entry["special_move_name"] = special_name
        special_desc = payload.get('special_move_desc', '').strip()
        if special_desc:
            entry["special_move_desc"] = special_desc
        arts[new_name] = entry
        data["martial_arts"] = arts
        save_martial_arts(data)
        clear_martial_arts_book_cache()
        _reload_effect_meta_safe()
        return jsonify({"status": "success", "message": "保存成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/delete', methods=['POST'])
def api_martial_delete():
    """删除武功"""
    try:
        payload = request.get_json()
        name = payload.get('name', '').strip()
        if not name:
            return jsonify({"status": "error", "message": "缺少name参数"})
        data = load_martial_arts()
        arts = data.get("martial_arts", {})
        if name not in arts:
            return jsonify({"status": "error", "message": "武功不存在"})
        del arts[name]
        data["martial_arts"] = arts
        save_martial_arts(data)
        clear_martial_arts_book_cache()
        _reload_effect_meta_safe()
        return jsonify({"status": "success", "message": "已删除"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/meta', methods=['GET'])
def api_martial_meta():
    """获取等级系统与类别列表元数据"""
    try:
        data = load_martial_arts()
        return jsonify({
            "status": "success",
            "grade_system": data.get("_grade_system", {}),
            "category_list": data.get("_category_list", [])
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/list_effect', methods=['GET'])
def api_martial_list_effect():
    """返回所有特效类型列表（供武功书编辑器下拉框使用）

    返回结构:
        {
            "status": "success",
            "effects": [
                {"id": "internal_injury", "name": "内伤", "category": "attack", "desc": "..."},
                ...
            ],
            "default_base_rate": {"attack": 5, "internal": 8, "lightfoot": 6, "special": 4}
        }
    """
    try:
        import dice_system as _ds
        meta = _ds._load_effect_meta()
        effects_dict = meta.get("effects", {})
        effects_list = []
        # 按 attack/internal/lightfoot/special 顺序输出
        cat_order = ["attack", "internal", "lightfoot", "special"]
        for cat in cat_order:
            for eid, einfo in effects_dict.items():
                if einfo.get("category") == cat:
                    effects_list.append({
                        "id": eid,
                        "name": einfo.get("name", eid),
                        "category": cat,
                        "desc": einfo.get("desc", ""),
                    })
        # 加一个"无特效"占位项放最前
        effects_list.insert(0, {"id": "", "name": "无特效", "category": "", "desc": "该武功不触发任何特效"})
        return jsonify({
            "status": "success",
            "effects": effects_list,
            "default_base_rate": meta.get("_default_base_rate", {
                "attack": 5, "internal": 8, "lightfoot": 6, "special": 4
            }),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/martial/ai_generate', methods=['POST'])
def api_martial_ai_generate():
    """AI 辅助生成武功 JSON（不写盘，返回前端编辑器供人工审核修改）"""
    import re as _re
    try:
        payload = request.get_json(force=True, silent=True) or {}
        desc = (payload.get('desc') or '').strip()
        if not desc:
            return jsonify({"status": "error", "message": "请输入武功描述"})

        sys_prompt = """你是武侠世界武功设计专家，擅长设计符合金庸武侠世界观的武功设定。
请根据用户描述，生成一门武功的完整设定，严格输出以下JSON结构（只输出JSON，不要markdown代码块）：

{
  "name": "武功名称",
  "grade": 7,
  "category": "sword",
  "source": "来源门派/人物",
  "brief_desc": "一句话简述",
  "effect": {"type": "shock", "base_rate": 10},
  "special_move_name": "绝招名称",
  "special_move_desc": "绝招描述"
}

字段约束：
1. grade：1-9整数。9=神话级, 8=绝世级, 7=顶级, 6=上乘级, 5=中上级, 4=中等级, 3=中下级, 2=入门级, 1=粗浅级
2. category：必须是以下10种之一：
   internal(内功), sword(剑法), blade(刀法), palm(掌法), staff(杖法/枪法), lightfoot(轻功), finger(指法/擒拿), hidden(暗器), fist(拳法), special(特殊/阵法/奇门)
3. effect.type：必须是以下22种特效之一（或留空字符串表示无特效）：
   攻击类：internal_injury(内伤), external_wound(外伤), weakness(虚弱), poison(剧毒), cold_poison(寒毒), fire_poison(火毒), acupoint_seal(点穴), shock(震慑), disarm(缴械), sound_attack(音攻)
   内功类：heal(治疗), purify(解毒), absorb(吸纳), dissolve(化功), shield(护体), reverse(反弹)
   轻功类：dodge(闪避), pursuit(追击), surprise(奇袭)
   特殊类：illusion(幻象), control(摄心), counter(反击)
4. effect.base_rate：1-20整数，表示特效基础触发率%
5. special_move_name/special_move_desc：该武功的招牌绝招名称和描述，建议填写
6. 只输出纯JSON，不要任何解释文字"""

        user_prompt = f"请根据以下描述生成武功设定：\n{desc}"

        # 加载最近10轮剧情，供AI参考当前场景
        try:
            _cache = load_context_cache() or {}
            _logs = _cache.get("interact_log", [])
            _recent = _logs[-10:] if len(_logs) >= 10 else _logs
            _plot_lines = []
            for _log in _recent:
                _m = _re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", _log, _re.S)
                if _m:
                    _plot_lines.append(_m.group(1).strip()[:100])
            if _plot_lines:
                recent_plot = "\n".join(_plot_lines)
                user_prompt += f"\n\n【最近剧情参考（请结合当前剧情场景设计武功，使其自然融入）】\n{recent_plot}"
        except Exception:
            pass

        llm_result = llm_call_common(sys_prompt, user_prompt, temp=0.6, max_tokens=800, timeout=60)
        raw_text = get_llm_content(llm_result)
        if not raw_text or not isinstance(raw_text, str):
            return jsonify({"status": "error", "message": "AI 未返回有效内容"})

        # JSON 清洗
        clean_str = raw_text.strip()
        m = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
        if m:
            clean_str = m.group(1).strip()
        first = clean_str.find("{")
        last = clean_str.rfind("}")
        if first != -1 and last > first:
            clean_str = clean_str[first:last + 1]

        try:
            art_data = json.loads(clean_str)
        except Exception:
            return jsonify({"status": "error", "message": "AI 返回的 JSON 解析失败，请重试或手动编辑"})

        # 补全/校验关键字段
        if not art_data.get("name"):
            return jsonify({"status": "error", "message": "AI 生成的武功缺少 name 字段"})

        # grade 钳制 1-9
        try:
            grade = int(art_data.get("grade", 4))
        except Exception:
            grade = 4
        grade = max(1, min(9, grade))
        art_data["grade"] = grade
        # bonus 由 grade 自动映射
        art_data["bonus"] = MARTIAL_GRADE_BONUS.get(grade, 0)

        # category 校验
        valid_categories = ["internal", "sword", "blade", "palm", "staff", "lightfoot", "finger", "hidden", "fist", "special"]
        if art_data.get("category") not in valid_categories:
            art_data["category"] = "fist"

        # source/brief_desc 默认空字符串
        if not art_data.get("source"):
            art_data["source"] = ""
        if not art_data.get("brief_desc"):
            art_data["brief_desc"] = ""

        # effect 校验
        valid_effects = ["internal_injury", "external_wound", "weakness", "poison", "cold_poison",
                         "fire_poison", "acupoint_seal", "shock", "disarm", "sound_attack",
                         "heal", "purify", "absorb", "dissolve", "shield", "reverse",
                         "dodge", "pursuit", "surprise", "illusion", "control", "counter"]
        effect = art_data.get("effect")
        if isinstance(effect, dict) and effect.get("type") in valid_effects:
            try:
                base_rate = int(effect.get("base_rate", 5))
            except Exception:
                base_rate = 5
            base_rate = max(1, min(20, base_rate))
            art_data["effect"] = {"type": effect["type"], "base_rate": base_rate}
        else:
            art_data["effect"] = None

        # special_move 默认空字符串
        if not art_data.get("special_move_name"):
            art_data["special_move_name"] = ""
        if not art_data.get("special_move_desc"):
            art_data["special_move_desc"] = ""

        return jsonify({"status": "success", "art": art_data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"AI 生成失败：{str(e)}"})

# ================================================================
#  🎒 物品书管理 API（镜像武功书结构，文件：data/items_catalog.json）
# ================================================================
ITEMS_CATALOG_FILE = "data/items_catalog.json"

def _load_items_catalog():
    """加载物品目录（含容错），若文件不存在返回最小可行结构"""
    data = load_json(ITEMS_CATALOG_FILE) or {}
    if not isinstance(data, dict):
        data = {}
    # 保证最小字段完整（防止空文件/custom_items.json老版本）
    data.setdefault("items_version", "1.0")
    data.setdefault("items", {})
    data.setdefault("subcategory_list", ["秘籍", "武器", "防具", "暗器", "丹药", "坐骑"])
    data.setdefault("rarity_tier", {
        "S": "传世至宝", "A": "绝顶之宝", "B": "罕见好物",
        "C": "江湖常见", "D": "普通物品"
    })
    data.setdefault("rarity_weight", {
        "S": 3.0, "A": 2.0, "B": 1.2, "C": 0.8, "D": 0.4
    })
    if not isinstance(data["items"], dict):
        data["items"] = {}
    return data

def _generate_item_keywords(it):
    """从物品字段自动生成关键词（供自动补全使用）"""
    kws = set()
    for field in ["name", "subcategory", "linked_martial", "source", "owner_hint"]:
        v = it.get(field, "") or ""
        if v:
            # 出典可能带 "/" 分拆
            for part in v.replace("/", " ").replace("，", " ").replace("、", " ").split():
                if len(part) >= 2:
                    kws.add(part)
    desc = it.get("description", "") or ""
    # 描述中的派/门/宫/庄关键词抽一段
    import re as _re_local
    for m in _re_local.finditer(r"[\u4e00-\u9fff]{2,6}(?:派|门|宫|庄|谷|堂|寨|堡|寺|帮|会|教|府|镖局)", desc):
        kws.add(m.group())
    return sorted(kws, key=len, reverse=True)

def _next_csv_id(items_dict):
    """为新增物品生成csv_id（取最大值+1），保持和 CSV源兼容"""
    used = [it.get("csv_id", 0) for it in items_dict.values() if isinstance(it, dict)]
    used.append(10000)
    return max(used) + 1

def _rarity_weight_table():
    return {"S": 3.0, "A": 2.0, "B": 1.2, "C": 0.8, "D": 0.4}

@app.route('/items/meta', methods=['GET'])
def api_items_meta():
    """获取物品元数据：种类列表/稀有度/总数/按种类+稀有度统计"""
    try:
        data = _load_items_catalog()
        items = data["items"]
        subcategory_counts = {}
        rarity_counts = {}
        for it in items.values():
            if not isinstance(it, dict):
                continue
            sc = it.get("subcategory", "")
            if sc:
                subcategory_counts[sc] = subcategory_counts.get(sc, 0) + 1
            r = it.get("rarity", "")
            if r:
                rarity_counts[r] = rarity_counts.get(r, 0) + 1
        return jsonify({
            "status": "success",
            "subcategory_list": data["subcategory_list"],
            "rarity_tier": data["rarity_tier"],
            "rarity_weight": data.get("rarity_weight", _rarity_weight_table()),
            "total_count": len(items),
            "subcategory_counts": subcategory_counts,
            "rarity_counts": rarity_counts,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/items/list', methods=['GET'])
def api_items_list():
    """获取物品列表（关键字/种类/稀有度筛选，按稀有度权重排序）"""
    try:
        keyword = request.args.get('search', '').strip().lower()
        subcategory = request.args.get('category', '').strip() or request.args.get('subcategory', '').strip()
        rarity = request.args.get('rarity', '').strip()
        data = _load_items_catalog()
        items = data["items"]
        rw = data.get("rarity_weight", _rarity_weight_table())

        result = []
        for iid, it in items.items():
            if not isinstance(it, dict):
                continue
            name = it.get("name", "")
            if not name:
                continue
            # 搜索：名称+描述+归属+出典+对应武学
            if keyword:
                haystack = " ".join([
                    name,
                    it.get("description", "") or "",
                    it.get("owner_hint", "") or "",
                    it.get("source", "") or "",
                    it.get("linked_martial", "") or "",
                    it.get("note", "") or "",
                    " ".join(it.get("keywords", []) or []),
                ]).lower()
                if keyword not in haystack:
                    continue
            if subcategory and it.get("subcategory", "") != subcategory:
                continue
            if rarity and it.get("rarity", "") != rarity:
                continue
            r = it.get("rarity", "C")
            result.append({
                "id": iid,
                "csv_id": it.get("csv_id", ""),
                "name": name,
                "subcategory": it.get("subcategory", ""),
                "rarity": r,
                "rarity_name": data["rarity_tier"].get(r, ""),
                "weight": rw.get(r, 0.8),
                "source": it.get("source", ""),
                "owner_hint": it.get("owner_hint", ""),
                "linked_martial": it.get("linked_martial", ""),
                "description": (it.get("description", "") or "")[:60],
            })

        # 排序：稀有度权重降序 → 名称
        result.sort(key=lambda x: (-x["weight"], x["name"]))
        print(f"[物品模块] list: search='{keyword}' cat='{subcategory}' rarity='{rarity}' → 返回 {len(result)} 条")
        return jsonify({"status": "success", "items": result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/items/get', methods=['GET'])
def api_items_get():
    """按物品名获取完整记录"""
    try:
        name = request.args.get('name', '').strip()
        if not name:
            return jsonify({"status": "error", "msg": "参数name缺失"})
        data = _load_items_catalog()
        items = data["items"]
        # 按 name 匹配（优先精确，再按id）
        for iid, it in items.items():
            if isinstance(it, dict) and it.get("name") == name:
                return jsonify({
                    "status": "success",
                    "item": {
                        "csv_id": it.get("csv_id"),
                        "name": it.get("name"),
                        "subcategory": it.get("subcategory", ""),
                        "rarity": it.get("rarity", "C"),
                        "description": it.get("description", ""),
                        "linked_martial": it.get("linked_martial", ""),
                        "source": it.get("source", ""),
                        "owner_hint": it.get("owner_hint", ""),
                        "note": it.get("note", ""),
                        "keywords": it.get("keywords", []),
                        "custom_fields": it.get("custom_fields", {}),
                    }
                })
        return jsonify({"status": "error", "msg": f"物品 '{name}' 不存在"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/items/add', methods=['POST'])
def api_items_add():
    """新增物品（name必须唯一）"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"status": "error", "msg": "物品名称不能为空"})
        subcategory = (payload.get("subcategory") or "").strip()
        rarity = (payload.get("rarity") or "C").strip().upper()
        data = _load_items_catalog()
        items = data["items"]

        # 唯一性：检查是否重名
        for it in items.values():
            if isinstance(it, dict) and it.get("name") == name:
                return jsonify({"status": "error", "msg": f"物品 '{name}' 已存在，不能重复新增"})

        if subcategory and subcategory not in data["subcategory_list"]:
            return jsonify({"status": "error", "msg": f"未知种类 '{subcategory}'"})
        if rarity not in data["rarity_tier"]:
            return jsonify({"status": "error", "msg": f"未知稀有度 '{rarity}'"})

        # 构造新物品
        new_iid = f"item_{name}"
        tmp = {
            "name": name,
            "subcategory": subcategory or "秘籍",
            "rarity": rarity,
            "description": (payload.get("description") or "").strip(),
            "linked_martial": (payload.get("linked_martial") or "").strip(),
            "source": (payload.get("source") or "").strip(),
            "owner_hint": (payload.get("owner_hint") or "").strip(),
            "note": (payload.get("note") or "").strip(),
        }
        # 关键词：手动优先，否则自动生成
        manual_kw = payload.get("keywords")
        if isinstance(manual_kw, list) and manual_kw:
            kw = [str(k).strip() for k in manual_kw if str(k).strip()]
        else:
            kw = _generate_item_keywords(tmp)
        if name not in kw:
            kw.insert(0, name)

        new_item = {
            "id": new_iid,
            "csv_id": payload.get("csv_id") or _next_csv_id(items),
            "name": tmp["name"],
            "subcategory": tmp["subcategory"],
            "description": tmp["description"],
            "linked_martial": tmp["linked_martial"],
            "source": tmp["source"],
            "owner_hint": tmp["owner_hint"],
            "rarity": tmp["rarity"],
            "keywords": kw,
            "note": tmp["note"],
            "custom_fields": payload.get("custom_fields") if isinstance(payload.get("custom_fields"), dict) else {},
        }
        items[new_iid] = new_item

        # 更新统计
        data["total_count"] = len(items)
        if "subcategory_counts" in data:
            del data["subcategory_counts"]
        if "rarity_counts" in data:
            del data["rarity_counts"]
        data["last_generated"] = time.strftime("%Y-%m-%d")

        save_json(ITEMS_CATALOG_FILE, data)
        print(f"[物品模块] add: '{name}' 成功，csv_id={new_item['csv_id']}，id={new_iid}")
        return jsonify({"status": "success", "msg": f"物品 '{name}' 新增成功", "item_id": new_iid})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/items/update', methods=['POST'])
def api_items_update():
    """更新物品（支持改名，original_name=旧名）"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        original_name = (payload.get("original_name") or "").strip()
        new_name = (payload.get("name") or "").strip()
        if not original_name:
            return jsonify({"status": "error", "msg": "original_name 缺失"})
        if not new_name:
            return jsonify({"status": "error", "msg": "新物品名称不能为空"})
        subcategory = (payload.get("subcategory") or "").strip()
        rarity = (payload.get("rarity") or "C").strip().upper()
        data = _load_items_catalog()
        items = data["items"]

        # 找原条目
        old_iid = None
        old_item = None
        for iid, it in items.items():
            if isinstance(it, dict) and it.get("name") == original_name:
                old_iid, old_item = iid, it
                break
        if not old_item:
            return jsonify({"status": "error", "msg": f"原物品 '{original_name}' 不存在"})

        if subcategory and subcategory not in data["subcategory_list"]:
            return jsonify({"status": "error", "msg": f"未知种类 '{subcategory}'"})
        if rarity not in data["rarity_tier"]:
            return jsonify({"status": "error", "msg": f"未知稀有度 '{rarity}'"})

        # 若改名：需要检查重名 + 更换 id
        if new_name != original_name:
            for iid, it in items.items():
                if isinstance(it, dict) and it.get("name") == new_name and iid != old_iid:
                    return jsonify({"status": "error", "msg": f"新名称 '{new_name}' 已存在，无法改名"})
            # 删旧 id，用新 id
            del items[old_iid]
            new_iid = f"item_{new_name}"
            old_item["id"] = new_iid
            old_item["name"] = new_name
        else:
            new_iid = old_iid

        old_item["subcategory"] = subcategory or old_item.get("subcategory", "秘籍")
        old_item["rarity"] = rarity
        old_item["description"] = (payload.get("description") or "").strip()
        old_item["linked_martial"] = (payload.get("linked_martial") or "").strip()
        old_item["source"] = (payload.get("source") or "").strip()
        old_item["owner_hint"] = (payload.get("owner_hint") or "").strip()
        old_item["note"] = (payload.get("note") or "").strip()
        # 关键词：用户提供则覆盖，否则自动重新生成
        manual_kw = payload.get("keywords")
        if isinstance(manual_kw, list) and manual_kw:
            kw = [str(k).strip() for k in manual_kw if str(k).strip()]
        else:
            kw = _generate_item_keywords(old_item)
        if old_item["name"] not in kw:
            kw.insert(0, old_item["name"])
        old_item["keywords"] = kw
        if isinstance(payload.get("custom_fields"), dict):
            old_item["custom_fields"] = payload["custom_fields"]

        items[new_iid] = old_item
        data["total_count"] = len(items)
        data["last_generated"] = time.strftime("%Y-%m-%d")
        save_json(ITEMS_CATALOG_FILE, data)
        print(f"[物品模块] update: '{original_name}' -> '{new_name}' 成功")
        return jsonify({"status": "success", "msg": f"物品 '{new_name}' 更新成功", "item_id": new_iid})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/items/delete', methods=['POST'])
def api_items_delete():
    """按物品名删除"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"status": "error", "msg": "name 缺失"})
        data = _load_items_catalog()
        items = data["items"]
        hit_iid = None
        for iid, it in items.items():
            if isinstance(it, dict) and it.get("name") == name:
                hit_iid = iid
                break
        if not hit_iid:
            return jsonify({"status": "error", "msg": f"物品 '{name}' 不存在，无需删除"})
        del items[hit_iid]
        data["total_count"] = len(items)
        data["last_generated"] = time.strftime("%Y-%m-%d")
        save_json(ITEMS_CATALOG_FILE, data)
        print(f"[物品模块] delete: '{name}' 成功，已从items字典移除")
        return jsonify({"status": "success", "msg": f"物品 '{name}' 删除成功"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "msg": str(e)})

@app.route('/items/ai_generate', methods=['POST'])
def api_items_ai_generate():
    """AI 辅助生成物品 JSON（不写盘，返回前端编辑器供人工审核修改）"""
    import re as _re
    try:
        payload = request.get_json(force=True, silent=True) or {}
        desc = (payload.get('desc') or '').strip()
        if not desc:
            return jsonify({"status": "error", "message": "请输入物品描述"})

        data = _load_items_catalog()
        subcat_list = data.get("subcategory_list", ["秘籍", "武器", "防具", "暗器", "丹药", "坐骑"])

        sys_prompt = f"""你是武侠世界物品设计专家，擅长设计符合金庸武侠世界观的物品设定。
请根据用户描述，生成一件物品的完整设定，严格输出以下JSON结构（只输出JSON，不要markdown代码块）：

{{
  "name": "物品名称",
  "subcategory": "武器",
  "rarity": "B",
  "description": "物品详细描述（外观、特性、功效等，50-150字）",
  "linked_martial": "关联武功名（无则空字符串）",
  "source": "出典小说（如：射雕英雄传）",
  "owner_hint": "归属人物/门派（如：黄蓉/桃花岛）",
  "note": "备注（可选，如：剧情中可掉落）"
}}

字段约束：
1. name：物品名称，简洁有武侠风格
2. subcategory：必须是以下之一：{", ".join(subcat_list)}
3. rarity：必须是以下之一：
   S=传世至宝（如屠龙刀、倚天剑、软猬宝甲）
   A=绝顶之宝（如玄铁重剑、九阴真经下卷）
   B=罕见好物（如精钢剑、银丝软甲、大还丹）
   C=江湖常见（如普通铁剑、小还丹）
   D=普通物品（如普通坐骑、地摊货）
4. description：详细描述物品的外观、特性、功效等
5. linked_martial：如该物品与某武功相关则填写武功名，否则空字符串
6. source：出典小说名，原创则填"原创"
7. owner_hint：该物品的归属者或门派
8. 只输出纯JSON，不要任何解释文字"""

        user_prompt = f"请根据以下描述生成物品设定：\n{desc}"

        # 加载最近10轮剧情，供AI参考当前场景
        try:
            _cache = load_context_cache() or {}
            _logs = _cache.get("interact_log", [])
            _recent = _logs[-10:] if len(_logs) >= 10 else _logs
            _plot_lines = []
            for _log in _recent:
                _m = _re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", _log, _re.S)
                if _m:
                    _plot_lines.append(_m.group(1).strip()[:100])
            if _plot_lines:
                recent_plot = "\n".join(_plot_lines)
                user_prompt += f"\n\n【最近剧情参考（请结合当前剧情场景设计物品，使其自然融入）】\n{recent_plot}"
        except Exception:
            pass

        llm_result = llm_call_common(sys_prompt, user_prompt, temp=0.6, max_tokens=800, timeout=60)
        raw_text = get_llm_content(llm_result)
        if not raw_text or not isinstance(raw_text, str):
            return jsonify({"status": "error", "message": "AI 未返回有效内容"})

        # JSON 清洗
        clean_str = raw_text.strip()
        m = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
        if m:
            clean_str = m.group(1).strip()
        first = clean_str.find("{")
        last = clean_str.rfind("}")
        if first != -1 and last > first:
            clean_str = clean_str[first:last + 1]

        try:
            item_data = json.loads(clean_str)
        except Exception:
            return jsonify({"status": "error", "message": "AI 返回的 JSON 解析失败，请重试或手动编辑"})

        # 补全/校验关键字段
        if not item_data.get("name"):
            return jsonify({"status": "error", "message": "AI 生成的物品缺少 name 字段"})

        # subcategory 校验
        if item_data.get("subcategory") not in subcat_list:
            item_data["subcategory"] = subcat_list[0] if subcat_list else "武器"

        # rarity 校验
        valid_rarities = ["S", "A", "B", "C", "D"]
        if item_data.get("rarity") not in valid_rarities:
            item_data["rarity"] = "C"

        # 默认空字符串
        for k in ("description", "linked_martial", "source", "owner_hint", "note"):
            if not item_data.get(k):
                item_data[k] = ""

        # 关键词：AI不生成，交给前端保存时后端自动生成
        item_data["keywords"] = []

        return jsonify({"status": "success", "item": item_data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"AI 生成失败：{str(e)}"})

# ================================================================
#  🎽 玩家装备管理 API（装备槽：内功/轻功/武器/防具/随身物品）
# ================================================================
from equipment_manager import EquipmentManager, EquipmentSlots

@app.route('/player/equipped', methods=['GET'])
def api_player_equipped():
    """获取玩家当前装备状态 + 可装备列表"""
    try:
        player = get_player()
        if not player:
            return jsonify({"status": "error", "message": "未读取到玩家存档"})
        equipped = EquipmentManager.get_equipped(player)
        # 可装备的内功/轻功列表
        inner_list = []
        light_list = []
        for sk in player.martial_skill_list:
            name = sk.get("skill_name", "")
            if not name:
                continue
            cat = EquipmentManager._get_skill_category(player, name)
            if cat == "internal":
                inner_list.append({"name": name, "exp": sk.get("exp", 0)})
            elif cat == "lightfoot":
                light_list.append({"name": name, "exp": sk.get("exp", 0)})
        # 可装备的武器/防具/随身物品列表
        weapon_list = []
        armor_list = []
        items_list = []
        from equipment_manager import _get_item_subcategory
        for it in player.item_list:
            if not it or it.strip() in ("无", ""):
                continue
            subcat = _get_item_subcategory(it)
            if subcat == "武器":
                weapon_list.append(it)
            elif subcat == "防具":
                armor_list.append(it)
            else:
                # 非武器非防具的物品 → 随身物品候选
                items_list.append(it)
        return jsonify({
            "status": "success",
            "equipped": equipped,
            "available": {
                "inner_martial": inner_list,
                "light_martial": light_list,
                "weapon": weapon_list,
                "armor": armor_list,
                "items": items_list,
            },
            "slots": EquipmentSlots.LABELS
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})


@app.route('/player/equip', methods=['POST'])
def api_player_equip():
    """装备：{slot: "inner_martial", name: "紫霞神功"}"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        slot = (payload.get("slot") or "").strip()
        name = (payload.get("name") or "").strip()
        if not slot or not name:
            return jsonify({"status": "error", "message": "slot 和 name 不能为空"})
        player = get_player()
        if not player:
            return jsonify({"status": "error", "message": "未读取到玩家存档"})
        result = EquipmentManager.equip(player, slot, name)
        if not result["ok"]:
            return jsonify({"status": "error", "message": result["reason"]})
        player.save()
        label = EquipmentSlots.LABELS.get(slot, slot)
        return jsonify({"status": "success", "plot": f"【装备】{label}已装备：{name}"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})


@app.route('/player/unequip', methods=['POST'])
def api_player_unequip():
    """卸下：{slot: "inner_martial"} 或 {slot: "items", name: "某物品"}"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        slot = (payload.get("slot") or "").strip()
        name = (payload.get("name") or "").strip()
        if not slot:
            return jsonify({"status": "error", "message": "slot 不能为空"})
        player = get_player()
        if not player:
            return jsonify({"status": "error", "message": "未读取到玩家存档"})
        old = EquipmentManager.get_equipped(player, slot)
        EquipmentManager.unequip(player, slot, name=name if name else None)
        player.save()
        label = EquipmentSlots.LABELS.get(slot, slot)
        if isinstance(old, list):
            old_str = name or "、".join(old) or "无"
        else:
            old_str = old or "无"
        return jsonify({"status": "success", "plot": f"【卸下】{label}已卸下：{old_str}"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})


# ================================================================
#  🏯 势力门派管理 API（文件：data/timeline_reference.json 的 factions[]）
# ================================================================
def _load_timeline_factions():
    """加载 timeline_reference.json，返回 (data, factions_list)。
    若文件缺失或无 factions 键，返回 ({}, [])。"""
    data = load_json(TIMELINE_FILE) or {}
    if not isinstance(data, dict):
        data = {}
    factions = data.get("factions", [])
    if not isinstance(factions, list):
        factions = []
    return data, factions


@app.route('/faction/list', methods=['GET'])
def api_faction_list():
    """获取门派/势力精简列表，支持关键字搜索。
    返回: {"status":"success","factions":[{"name","novel","category","location","stance"}], "total":N}"""
    try:
        keyword = (request.args.get('keyword', '') or '').strip().lower()
        _, factions = _load_timeline_factions()
        simplified = []
        for f in factions:
            name = f.get("name", "")
            novel = f.get("novel", "")
            category = f.get("category", "")
            location = f.get("location", "")
            stance = f.get("stance", "")
            # 关键字过滤（匹配 name/novel/category/location/stance）
            if keyword:
                haystack = " ".join([name, novel, category, location, stance]).lower()
                if keyword not in haystack:
                    continue
            simplified.append({
                "name": name,
                "novel": novel,
                "category": category,
                "location": location,
                "stance": stance,
            })
        return jsonify({"status": "success", "factions": simplified, "total": len(simplified)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/faction/get', methods=['GET'])
def api_faction_get():
    """获取单个门派详情（按 name 查询）"""
    try:
        name = (request.args.get('name', '') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "缺少 name 参数"})
        _, factions = _load_timeline_factions()
        for f in factions:
            if f.get("name") == name:
                return jsonify({"status": "success", "faction": f})
        return jsonify({"status": "error", "message": f"门派「{name}」不存在"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/faction/update', methods=['POST'])
def api_faction_update():
    """更新门派数据（按原 name 定位，整体替换为 faction 字段内容）"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get('name') or '').strip()
        faction_new = payload.get('faction')
        if not name or not isinstance(faction_new, dict):
            return jsonify({"status": "error", "message": "参数不完整（需 name + faction）"})
        data, factions = _load_timeline_factions()
        found = False
        for i, f in enumerate(factions):
            if f.get("name") == name:
                # 确保 name 字段一致（防止前端误改 key）
                faction_new["name"] = name
                factions[i] = faction_new
                found = True
                break
        if not found:
            return jsonify({"status": "error", "message": f"门派「{name}」不存在"})
        data["factions"] = factions
        save_json(TIMELINE_FILE, data)
        return jsonify({"status": "success", "message": "保存成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/faction/delete', methods=['POST'])
def api_faction_delete():
    """删除门派（按 name）"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get('name') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "缺少 name 参数"})
        data, factions = _load_timeline_factions()
        original_len = len(factions)
        data["factions"] = [f for f in factions if f.get("name") != name]
        if len(data["factions"]) == original_len:
            return jsonify({"status": "error", "message": f"门派「{name}」不存在"})
        save_json(TIMELINE_FILE, data)
        return jsonify({"status": "success", "message": "删除成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/faction/add', methods=['POST'])
def api_faction_add():
    """新增门派（最小字段：name；其余字段由前端补全）"""
    try:
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get('name') or '').strip()
        if not name:
            return jsonify({"status": "error", "message": "门派名不能为空"})
        data, factions = _load_timeline_factions()
        # 重名检查
        for f in factions:
            if f.get("name") == name:
                return jsonify({"status": "error", "message": f"门派「{name}」已存在"})
        new_faction = {
            "id": f"faction_{name}",
            "name": name,
            "novel": (payload.get('novel') or "跨时代通用").strip(),
            "category": (payload.get('category') or "门派·正道").strip(),
            "founding": "",
            "location": "",
            "stance": "",
            "core_members": [],
            "martial_arts": [],
            "allies": [],
            "enemies": [],
            "stages": [],
            "flags": [],
            "keywords": [name],
        }
        factions.append(new_faction)
        data["factions"] = factions
        save_json(TIMELINE_FILE, data)
        return jsonify({"status": "success", "message": "创建成功"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/faction/ai_generate', methods=['POST'])
def api_faction_ai_generate():
    """AI 辅助生成门派 JSON（不写盘，返回给前端编辑器供人工审核修改）"""
    import re as _re  # 局部导入，零侵入
    try:
        payload = request.get_json(force=True, silent=True) or {}
        desc = (payload.get('desc') or '').strip()
        if not desc:
            return jsonify({"status": "error", "message": "请输入门派描述"})

        sys_prompt = """你是武侠世界设定专家，擅长创作符合金庸武侠世界观的门派/势力设定。
请根据用户描述，生成一个完整的门派/势力 JSON 数据，严格遵循以下结构：

{
  "id": "faction_门派名",
  "name": "门派名称",
  "novel": "出典小说（跨时代通用/书剑恩仇录/飞狐外传/雪山飞狐/连城诀/鸳鸯刀/笑傲江湖/侠客行/碧血剑）",
  "category": "类别（如：门派·正道/帮会·反清/镖局·中立/部落·反清/门派·邪道）",
  "founding": "创派背景简述（一句话）",
  "location": "地理位置（如：湖北武当山）",
  "stance": "立场简述（如：反清复明/中立/效忠清廷）",
  "core_members": ["掌门", "长老/护法", "核心弟子（3-8人）"],
  "martial_arts": ["主武功", "次要武功（2-5门，按重要性排序）"],
  "allies": ["盟友门派/势力"],
  "enemies": ["敌对势力"],
  "stages": [
    {"period": "阶段名", "year_range": "年份区间", "power": 5, "desc": "阶段描述"}
  ],
  "flags": ["特殊标记（可空）"],
  "keywords": ["检索关键词（含门派名、核心人物、主武功）"]
}

要求：
1. power 值范围 1-10，10为武林至尊，1为末流
2. stages 包含2-4个发展阶段，体现门派兴衰
3. 武功与门派定位匹配，符合金庸武侠体系
4. core_members 3-8人，名字符合武侠风格
5. 只输出纯 JSON，不要任何解释文字、不要 markdown 代码块标记"""

        user_prompt = f"请根据以下描述生成门派设定：\n{desc}"

        # 加载最近10轮剧情，供AI参考当前场景
        try:
            _cache = load_context_cache() or {}
            _logs = _cache.get("interact_log", [])
            _recent = _logs[-10:] if len(_logs) >= 10 else _logs
            _plot_lines = []
            for _log in _recent:
                _m = _re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", _log, _re.S)
                if _m:
                    _plot_lines.append(_m.group(1).strip()[:100])
            if _plot_lines:
                recent_plot = "\n".join(_plot_lines)
                user_prompt += f"\n\n【最近剧情参考（请结合当前剧情场景设计门派，使其与当前江湖局势自然关联）】\n{recent_plot}"
        except Exception:
            pass

        llm_result = llm_call_common(sys_prompt, user_prompt, temp=0.6, max_tokens=1500, timeout=60)
        raw_text = get_llm_content(llm_result)
        if not raw_text or not isinstance(raw_text, str):
            return jsonify({"status": "error", "message": "AI 未返回有效内容"})

        # JSON 清洗（参照项目现有逻辑）
        clean_str = raw_text.strip()
        # 去 markdown 代码块
        m = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_str)
        if m:
            clean_str = m.group(1).strip()
        # 提取 {...}
        first = clean_str.find("{")
        last = clean_str.rfind("}")
        if first != -1 and last > first:
            clean_str = clean_str[first:last + 1]

        try:
            faction_data = json.loads(clean_str)
        except Exception:
            return jsonify({"status": "error", "message": "AI 返回的 JSON 解析失败，请重试或手动编辑"})

        # 补全 id 字段（AI 可能遗漏）
        fname = faction_data.get("name", "")
        if fname and not faction_data.get("id"):
            faction_data["id"] = f"faction_{fname}"

        return jsonify({"status": "success", "faction": faction_data})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"AI 生成失败：{str(e)}"})


# ======= 启动局域网服务器 =======
if __name__ == '__main__':
    # ===== 世界书索引预初始化（零侵入：web端启动时即构建，不等首次search） =====
    try:
        import worldbook as _wb_bootstrap
        _wb_bootstrap.init()
        # 立即触发一次构建，使 /worldbook/status 在首页加载时就显示正确数据
        _wb_bootstrap.search("__bootstrap_warmup__", max_chars=100)
        print(f"{COLOR_SYSTEM}[世界书] Web端预初始化完成{COLOR_END}")
    except Exception as _wb_e:
        print(f"[世界书] Web端预初始化失败（不影响主功能，首次检索时自动重试）: {_wb_e}")

    print(f"\n{COLOR_SYSTEM}【局域网 Web 服务启动中...】{COLOR_END}")
    print("请在同一局域网下的手机或电脑上打开：")
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    print(f"👉 http://{local_ip}:5000")
    print(f"{COLOR_SYSTEM}【按 Ctrl+C 停止服务】{COLOR_END}\n")
    app.run(host="0.0.0.0", port=5001, debug=False)