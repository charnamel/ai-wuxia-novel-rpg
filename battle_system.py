# ===================== 全新对战系统 V4.4 精准剧情NPC匹配修复版 =====================
# 核心修复：只加载【当前剧情真实出场NPC】｜非法序号直接退出对战｜零改核心打斗逻辑
# 对战系统模块，实现完整的武侠对战斗流程
import os
import re
import random

from config import DEEPSEEK_BASE_URL
from player_manager import get_player
from llm_utils import get_llm_content
import vitality_system
from dice_system import resolve_check_v4 as dice_resolve_check_v4, detect_martial_skill as dice_detect_martial_skill, detect_martial_skill_classified as dice_detect_martial_skill_classified, ai_judge_dc_only as dice_ai_judge_dc_only, build_active_npcs_brief as dice_build_active_npcs_brief, build_target_npc_line as dice_build_target_npc_line

# 颜色复用（和主程序完全对齐，补全缺失常量）
class Color:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    PURPLE = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    END = "\033[0m"

COLOR_SYSTEM = Color.CYAN
COLOR_BATTLE = Color.PURPLE
COLOR_WARN = Color.RED
COLOR_END = Color.END
COLOR_OPTION = Color.BLUE
COLOR_GREEN = Color.GREEN
COLOR_YELLOW = Color.YELLOW  # 全局变量补上

# 全局对战缓存（仅对战模块使用，独立存储空间）
BATTLE_CACHE = {
    "in_battle": False,
    "battle_target": "",
    "battle_summary": "",
    "battle_result": "",
    "player_hp_state": "状态完好，气血充盈",
    "npc_hp_state": "状态完好，气血充盈",
    "battle_round": 0
}


# 清空对战缓存（主程序调用，战后清零）
def clear_battle_cache():
    # 清空全局对战缓存，重置为初始状态
    global BATTLE_CACHE
    print("[DEBUG] clear_battle_cache 被调用")
    BATTLE_CACHE = {
        "in_battle": False,
        "battle_target": "",
        "battle_summary": "",
        "battle_result": "",
        "player_hp_state": "状态完好，气血充盈",
        "npc_hp_state": "状态完好，气血充盈",
        "battle_round": 0
    }

# 获取上轮对战上下文（供主剧情接续）
def get_last_battle_context():
    # 获取上一次对战的上下文信息
    # 返回: 包含对战状态、目标、摘要、结果的字典
    return {
        "has_last_battle": BATTLE_CACHE["battle_round"] > 0,
        "battle_target": BATTLE_CACHE["battle_target"],
        "battle_summary": BATTLE_CACHE["battle_summary"],
        "battle_result": BATTLE_CACHE["battle_result"]
    }

# AI 智能判定双方健康/伤势状态
def ai_check_battle_status(llm_func, player_data, npc_data, battle_process):
    # 调用AI智能判定对战双方的健康/伤势状态
    # llm_func: LLM调用函数
    # player_data: 玩家数据
    # npc_data: NPC数据
    # battle_process: 对战过程文本
    # 返回: AI生成的双方状态描述
    status_prompt = f"""
你是武侠对战状态判定师，根据当前对战过程、玩家、NPC实力，精准判断双方伤势、气血、战斗状态。
要求：
1. 输出两段文字：玩家状态、对手状态
2. 描述真实、贴合武侠打斗，包含：气血、伤势、体力、气息、伤口、乏力程度
3. 要根据打斗回合、招式交锋递进判定伤势
4. 无需结论，只客观描述当前健康战斗状态

玩家档案：{player_data}
对手档案：{npc_data}
当前对战过程：{battle_process}

严格输出格式：
【玩家战斗状态】xxx
【对手战斗状态】xxx
"""
    res =  get_llm_content(llm_func(status_prompt, "请精准判定双方当前战斗健康状态", temp=0.4))
    return res

# AI 智能战局走向判定（核心新增：替代手动输入胜负）
def ai_judge_battle_trend(llm_func, battle_process, player_status, npc_status):
    # 调用AI智能判定对战局势走向
    # llm_func: LLM调用函数
    # battle_process: 对战过程文本
    # player_status: 玩家状态
    # npc_status: NPC状态
    # 返回: AI生成的战局判定结果
    judge_prompt = f"""
你是武侠对战战局裁判，根据当前完整对战过程、双方伤势状态，**智能判定战局走向**。
可以让用户手动输入对战情况，并由AI分析剧情推演结果。

【完整对战过程】
{battle_process}
【玩家当前状态】
{player_status}
【对手当前状态】
{npc_status}

判定规则：
1. 仅输出三种走向：继续激战 / 玩家优势可收手 / 对手劣势可结束战斗
2. 附带简短剧情化分析，说明为何判定该走向（结合伤势、体力、攻防局势）
3. 可以让用户手动选择胜负、结果，不询问胜/负/平
4. 局势胶着一律判定【继续激战】，杜绝提前强行结束
5. 只有一方明显重伤、体力耗尽、彻底落败时，才判定可结束战斗

输出格式：
【AI战局判定】xxx（继续激战 / 玩家优势可收手 / 对手劣势可结束战斗）
【局势分析】xxx
"""
    res = get_llm_content(llm_func(judge_prompt, "AI智能分析对战战局走向", temp=0.5))
    return res

def gen_single_battle_round(llm_func, player_data, npc_data, round_num, player_attack_text, last_process, battle_style_desc, dice_constraint="", scene_info="", player_name=None, target_npc_name=None, target_npc_persisted=True):
    # 生成单回合对战剧情
    # llm_func: LLM调用函数
    # player_data: 玩家数据
    # npc_data: NPC数据
    # round_num: 当前回合数
    # player_attack_text: 玩家出招文本
    # last_process: 上一回合的对战过程
    # battle_style_desc: 对战风格描述
    # 返回: 生成的单回合对战剧情
    import json
    from player_manager import Player

    p_info = json.loads(player_data)
    level = p_info.get("overall_martial_level", "未知修为")
    skills = p_info.get("martial_skill_list", [])

    # 构建技能文本，兼容新旧格式
    skill_lines = []
    for s in skills:
        name = s.get("skill_name", "")
        if not name:
            continue
        if "exp" in s:
            exp = s.get("exp", 0)
            realm = Player.get_realm(exp)
            skill_lines.append(f"{name}：{realm}")
        else:
            skill_lines.append(f"{name}：{s.get('skill_level', '未知')}")
    skill_text = "\n".join(skill_lines)

    # ===== V5：体力面板注入（战斗管线） =====
    _p_realm_i = calc_realm_index(p_info)
    _t_info = json.loads(npc_data) if npc_data else {}
    _t_realm_i = calc_realm_index(_t_info)
    _realm_diff = _p_realm_i - _t_realm_i
    _p_realm_s = REALM_ORDER[_p_realm_i]
    _t_realm_s = REALM_ORDER[_t_realm_i]
    _vit_block = ""
    _p_name = player_name or p_info.get("name")
    _t_name = target_npc_name
    if _p_name or _t_name:
        _names = []
        if _p_name:
            _names.append(_p_name)
        if _t_name:
            _names.append(_t_name)
        _vit_block = "\n【*气血内力面板*】（HP/MP均为0-100百分比刻度，全员上限都是100）\n" + \
            vitality_system.render_vitality_block(_p_name, _names if not target_npc_persisted else None) + "\n"
        # 对战目标若未落盘（临时NPC），用内存缓存单独渲染
        if _t_name and not target_npc_persisted:
            _tv = vitality_system.get_temp_vitality(_t_name)
            _hp_s = "0%（已故）" if _tv["hp"] < 0 else ("0%（濒死锁血）" if _tv["hp"] == 0 else f"{_tv['hp']}%")
            _t_mp_s = f"{_tv['mp']}%"
            if _tv["mp"] == 0:
                _t_mp_s += "（⚠内力枯竭：无法催动武功，招式威力大幅减弱）"
            _vit_block += f"・{_t_name}：HP {_hp_s} / MP {_t_mp_s}\n"
        _vit_block += (
            f"（双方境界：{_p_name or '玩家'}＝{_p_realm_s}，{_t_name or '对手'}＝{_t_realm_s}，相差{abs(_realm_diff)}档。）\n"
            "（结算规则：每回合末尾必须单独输出一行【体力结算】，格式严格为："
            "【体力结算】姓名：气血±N，内力±N（正数恢复/获得，负数受伤/消耗，双方都要报，无变化写0）。"
            "数值由你根据本回合交手激烈程度与双方境界差距自行把握，"
            "只需遵守方向：境界悬殊时，强者一击可重创弱者，弱者反击难伤强者分毫。"
            "内力为空者不能催动武功。）\n"
        )

    _scene_block = f"\n【当前场景环境】\n{scene_info}\n" if scene_info else ""
    battle_prompt = f"""
你正在续写武侠实时对战第{round_num}回合的交手细节，全程遵循金庸写实武侠风格，绝对不得自行终结战斗。

【对战基础设定】
打斗风格：{battle_style_desc}
玩家综合修为：{level}
玩家已修功法：
{skill_text}
玩家完整档案：{player_data}
对手NPC完整档案：{npc_data}
{_scene_block}{_vit_block}
【回合承接锚点（必须严格承接）】
上一回合收尾状态：{last_process if last_process else "双方刚摆开架势，初次照面，尚未正式交手"}
玩家本回合主动出招：{player_attack_text}
{dice_constraint}

【核心生成规则】
1.  强连续感：开篇必须承接上一回合的招式余势、站位或伤势，顺着战局往下写，不得凭空重启战局、跳脱过程。
2.  招式写实：围绕玩家本回合的出招展开拆解，补全身法、内力运转、兵器碰撞的细节；只润色不篡改玩家行动，不额外加剧情、不增减设定。
3.  渐进累积：每回合体现细微的局势变化——内力消耗、体力损耗、轻微伤势、站位进退，战斗节奏逐步推进，避免千篇一律的换招。
4.  贴合人设：NPC的招式路数、应对风格完全符合其性格、武功设定、武学水平，不出现不符合人设的打法。
5.  绝对禁止：绝杀、一招定胜负、直接结束战斗、写"数招过后"这类跨回合表述、自行结束战斗。

【武功推断规则】
- 如果已列出对手NPC的功法，请按照所列武功进行描写，招式风格必须与功法匹配。
- 如果未明确对手NPC的功法，请根据剧情中其身份、性格自行推断合理的武功水平和招式风格，确保符合武侠逻辑（如武林高手应有高深武功，普通村民可能只会粗浅拳脚）。

【输出要求】
- 仅输出本回合完整打斗过程 + 双方当前状态，结合当前双方伤势、气息变化自然融入叙事，同时单独列出双方此刻状态。
- 最后一行必须是【体力结算】行（双方各一行），这是系统结算气血内力的唯一依据。
- 结尾停在双方招式交替的间隙（可以是招式碰撞间隙，也可以是完整一招的间隙），留好下一回合的出招空间，不得收束战局。
- 全文控制在120~180字，凝练有画面感，无多余字段、无总结、无结局。（【体力结算】行不计入字数）

输出：
"""
    return get_llm_content(llm_func(battle_prompt, "生成单回合武侠对战剧情", temp=0.8))


# ===== V5：境界档位与体力结算数值校正 =====
REALM_ORDER = ["无武功", "初学入门", "初窥门径", "略有小成", "略有所成", "渐入佳境",
               "融会贯通", "登堂入室", "炉火纯青", "出神入化", "登峰造极",
               "超凡入圣", "返璞归真", "天人合一", "破碎虚空"]


def _realm_text_index(txt):
    for i, r in enumerate(REALM_ORDER):
        if r in (txt or ""):
            return i
    return None


def calc_realm_index(entity_info):
    """从玩家/NPC档案推算最高境界档位索引
    兼容字段：martial_skill_list[].skill_level > martial_skill_list[].exp推算 >
    martial_skills[].skill_level（临时NPC） > overall_martial_level / level / overall_realm
    """
    from player_manager import Player
    best = 0
    info = entity_info or {}
    for s in info.get("martial_skill_list", []):
        idx = _realm_text_index(s.get("skill_level", ""))
        if idx is None and "exp" in s:
            idx = _realm_text_index(Player.get_realm(s.get("exp", 0)))
        if idx is not None:
            best = max(best, idx)
    for s in info.get("martial_skills", []):
        idx = _realm_text_index(s.get("skill_level", ""))
        if idx is not None:
            best = max(best, idx)
    for field in ("overall_martial_level", "level", "overall_realm"):
        idx = _realm_text_index(info.get(field, ""))
        if idx is not None:
            best = max(best, idx)
    return best


def settle_battle_round_vitality(round_plot, player_name, target_name, target_persisted=True):
    """从单回合对战剧情中解析【体力结算】行并结算（AI报什么数值就用什么数值，不做强制校正）。
    返回结算日志字符串（空串表示无变化）。
    战斗中的临时对手若未落盘，走内存缓存结算。
    """
    changes = vitality_system.parse_vitality_regex(round_plot or "")
    if not changes:
        return ""
    scene_names = [target_name] if (target_name and not target_persisted) else None
    results = vitality_system.settle_vitality(
        changes,
        player_name=player_name,
        scene_npc_names=scene_names,
        user_action="对战回合",
    )
    return vitality_system.format_settle_log(results)

# 最终对战收尾结局生成（纯AI剧情结算，无手动输入）
def gen_battle_final_end(llm_func, all_process, battle_style_desc, player_status="", npc_status=""):
    # 生成对战最终结局
    # llm_func: LLM调用函数
    # all_process: 完整的对战过程
    # battle_style_desc: 对战风格描述
    # 返回: 生成的对战最终结局
    _status_block = f"\n【双方最终伤势状态】\n玩家状态：{player_status}\n对手状态：{npc_status}\n" if (player_status or npc_status) else ""
    end_prompt = f"""
当前多回合武侠对战结束，AI根据本次战斗风格设定：{battle_style_desc}，结合对战剧情、双方伤势状态，自动生成最终对战结局。
全部对战过程：{all_process}
{_status_block}
要求：
1. 完全根据实战剧情判定胜负（胜/负/平/险胜/惜败），无人工干预。
2. **字数严格控制在120字以内**，精炼有力！拒绝长篇大论的招式拆解和华丽辞藻堆砌，只写核心胜负结果、双方最终状态和氛围。
3. 结局贴合全程打斗节奏，不突兀、不强行反转。
4. **结尾必须实现向日常状态的自然过渡**（例如：胜负既定，你调整呼吸，重新审视当前情况。）
5. 禁止出现"总结"、"总而言之"等现代套话，保持武侠古风。

输出精简的对战结局剧情。
"""
    return get_llm_content(llm_func(end_prompt, "AI自动生成对战最终结局", temp=0.7))

# ===================== 主对战入口函数（对接main.py） =====================
def run_battle_system(
    llm_common_func,
    update_ctx_func,
    update_plot_func,
    modify_favor_func,
    append_memory_func,
    update_npc_skill_func,
    update_player_func,
    update_npc_func,
    ctx_cache,
    his_text,
    branch_text,
    npc_all_data=None,
    current_plot_npc_names=None,
    battle_style_desc="",  # 新增：对战风格描述
    api_key=""
):
    # 运行对战系统的主入口函数
    # llm_common_func: LLM通用调用函数
    # update_ctx_func: 更新上下文函数
    # update_plot_func: 更新剧情函数
    # modify_favor_func: 修改好感度函数
    # append_memory_func: 追加记忆函数
    # update_npc_skill_func: 更新NPC技能函数
    # update_player_func: 更新玩家函数
    # update_npc_func: 更新NPC函数
    # ctx_cache: 上下文缓存
    # his_text: 历史文本
    # branch_text: 分支文本
    # npc_all_data: NPC所有数据
    # current_plot_npc_names: 当前剧情出场的NPC名字列表
    # battle_style_desc: 对战风格描述
    # api_key: API密钥
    # 局部按需导入，彻底修复冗余导入报错
    import json
    
    def load_json(path):
        # 内部函数：加载JSON文件
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    player_obj = get_player()
    if player_obj:
        player_data_raw = player_obj.to_dict()
    else:
        player_data_raw = {}  # 或报错
    npc_data_raw = load_json("data/npc_agents.json")
    npc_list = npc_data_raw.get("npc_list", []) if npc_data_raw else []

    # ========== 改为手动输入单个对决角色逻辑 ==========
    scene_active_npc = []
    target_name_input = ""
    if isinstance(current_plot_npc_names, list) and len(current_plot_npc_names) > 0:
        target_name_input = current_plot_npc_names[0].strip()

    if not target_name_input:
        print(f"{COLOR_WARN}未输入对决对象，退出对战{COLOR_END}")
        return

    # 构建数据库NPC名字映射
    db_npc_name_map = {npc["name"].strip(): npc for npc in npc_list}

    # 1. 数据库存在该NPC，直接取用档案
    if target_name_input in db_npc_name_map:
        scene_active_npc.append(db_npc_name_map[target_name_input])
    else:
     # 2. 数据库无此人，调用AI实时生成完整临时NPC档案
        if target_name_input in db_npc_name_map:
            scene_active_npc.append(db_npc_name_map[target_name_input])
        else:
            print(f"{COLOR_YELLOW}【提示】{target_name_input} 不在存档NPC列表，AI正在生成人物档案...{COLOR_END}")
            
            # 确保是字符串，超长则裁剪（正常近3轮不会触发）
        his_text_str = str(his_text) if not isinstance(his_text, str) else his_text
        his_text_short = his_text_str[-500:] if len(his_text_str) > 500 else his_text_str
        gen_prompt = f"""
仅输出纯净JSON，无任何注释、markdown、多余文字。
【当前剧情上下文】
{his_text_short}
【生成规则】结合上面的近期江湖剧情，贴合故事背景、势力、武学设定生成NPC；
根据名称「{target_name_input}」生成武侠NPC完整档案，结构严格如下：
{{
    "name": "{target_name_input}",
    "identity": "江湖身份，简短一句话",
    "level": "武侠修为等级",
    "personality": "三十字内性格描述",
    "life_experience": "简短身世经历",
    "secret": "人物隐秘心事",
    "initial_favor": 50,
    "memory_list": [],
    "martial_skills": [
        {{
            "skill_name": "专属武学名称",
            "skill_level": "对应修为档次"
        }}
    ]
}}
"""
        raw_resp = llm_common_func(gen_prompt, f"生成临时对手 {target_name_input} 档案", temp=0.6)
        raw_text = get_llm_content(raw_resp)  # 提取纯文本，修复字典类型报错
        
        # 清洗JSON（直接用全局re模块，不再内部import）
        def clean_json_local(raw_str):
            # 内部函数：清洗JSON文本
            raw_str = raw_str.strip()
            pat = r"```(?:json)?\s*([\s\S]*?)\s*```"
            match_res = re.search(pat, raw_str)
            if match_res:
                return match_res.group(1).strip()
            s1 = raw_str.find("{")
            s2 = raw_str.rfind("}")
            if s1 != -1 and s2 > s1:
                return raw_str[s1:s2+1]
            return ""
        
        clean_str = clean_json_local(raw_text)
        try:
            temp_npc = json.loads(clean_str)
            # 强制校验name字段，防止AI生成错名字
            if "name" not in temp_npc or not temp_npc["name"]:
                temp_npc["name"] = target_name_input
        except Exception:
            # AI生成失败兜底模板
            temp_npc = {
                "name": target_name_input,
                "identity": "江湖路人",
                "level": "初学入门",
                "personality": "性情普通，无特殊特点",
                "life_experience": "行走江湖，来历不明",
                "secret": "无",
                "initial_favor": 50,
                "memory_list": [],
                "martial_skills": [{"skill_name": "基础入门拳", "skill_level": "初学入门"}]
            }
        scene_active_npc.append(temp_npc)

    # 调试打印（简易无报错版本）
    print(f"\n{COLOR_SYSTEM}===== 对决对象信息 ====={COLOR_END}")
    print(f"{COLOR_GREEN}本次对决目标：{scene_active_npc[0]['name']}{COLOR_END}")
    print(f"{COLOR_SYSTEM}========================\n{COLOR_END}")

    # 下方原有单NPC自动选中逻辑无需改动
    if len(scene_active_npc) > 1:
        # 现在只会有1个，这段永远不会执行，保留兼容
        print(f"\n{COLOR_SYSTEM}📋 当前可对战NPC：{COLOR_END}")
        for idx, npc in enumerate(scene_active_npc, 1):
            print(f"  {idx}. {npc['name']}｜修为：{npc.get('level','未知')}｜身份：{npc.get('identity','江湖人士')}")
        while True:
            sel_opt = input(f"\n{COLOR_GREEN}请输入序号选择对战NPC（输入非法序号退出对战）：{COLOR_END}").strip()
            if not sel_opt.isdigit():
                print(f"{COLOR_WARN}【输入非法】退出对战系统{COLOR_END}")
                return
            sel_num = int(sel_opt)
            if 1 <= sel_num <= len(scene_active_npc):
                target_npc = scene_active_npc[sel_num-1]
                break
            else:
                print(f"{COLOR_WARN}【所选NPC不在列表】退出对战系统{COLOR_END}")
                return
    else:
        # 固定只有一个对手，直接选中
        target_npc = scene_active_npc[0]
        print(f"\n{COLOR_SYSTEM}📋 本次对决对手：{target_npc['name']}{COLOR_END}")

    # 初始化对战缓存
    global BATTLE_CACHE
    BATTLE_CACHE["in_battle"] = True
    BATTLE_CACHE["battle_target"] = target_name_input
    BATTLE_CACHE["battle_round"] = 0

    print(f"\n{COLOR_BATTLE}⚔️  武侠对决开启！对战目标：{target_name_input}{COLOR_END}")
    print(f"{COLOR_SYSTEM}📌 对战模式：AI智能判局｜无限手动回合｜无自动结束{COLOR_END}\n")

    # 对战过程累计容器
    total_battle_process = ""
    last_round_process = ""
    player_status_cache = ""
    npc_status_cache = ""

    # ========== 无限对战主循环（核心逻辑完全保留未改动） ==========
    while True:
        BATTLE_CACHE["battle_round"] += 1
        current_round = BATTLE_CACHE["battle_round"]

        # 打印对战菜单
        print(f"\n{COLOR_BATTLE}—————— 第{current_round}回合 对战操作面板 ——————{COLOR_END}")
        print(f"{COLOR_OPTION}① 继续战斗（输入自定义招式文字出招）{COLOR_END}")
        print(f"{COLOR_OPTION}② 结束本次对战（AI自动结算结局）{COLOR_END}")
        print(f"{COLOR_OPTION}③ AI分析战局+双方健康伤势状态{COLOR_END}")
        print(f"{COLOR_OPTION}④ 生成本场对战ASCII配图{COLOR_END}")  # 新增配图选项
        
        opt = input(f"\n{COLOR_GREEN}请输入序号选择操作：{COLOR_END}").strip()

        # ③ AI分析状态+智能判局（核心功能：替代手动胜负输入）
        if opt == "3":
            print(f"\n{COLOR_SYSTEM}🔍 AI正在全方位分析对战局势与伤势状态...{COLOR_END}")
            # 刷新双方伤势状态
            player_status_cache = ai_check_battle_status(llm_common_func, json.dumps(player_data_raw,ensure_ascii=False), json.dumps(target_npc,ensure_ascii=False), total_battle_process)
            # AI智能判定战局走向
            trend_result = ai_judge_battle_trend(llm_common_func, total_battle_process, player_status_cache, npc_status_cache)
            print(f"{COLOR_BATTLE}{player_status_cache}\n{trend_result}{COLOR_END}\n")
            continue

        # ===== 在 run_battle_system 中找到 opt == "2" 分支 =====
        if opt == "2":
            print(f"\n{COLOR_SYSTEM}📝 AI正在根据全程对战剧情自动结算结局...{COLOR_END}")
            final_end = gen_battle_final_end(llm_common_func, total_battle_process, battle_style_desc)
            print(f"\n{COLOR_BATTLE}【整场对战最终结局】{COLOR_END}")
            print(f"{final_end}")

            # ---- 从【全程对战文本】中提取武功，涨经验 ----
            player_obj = get_player()
            if player_obj and player_obj.martial_skill_list:

                player_skill_names = [sk["skill_name"] for sk in player_obj.martial_skill_list]
                matched_skills = set()

                # 遍历整个对战过程，提取所有出现过的武功
                for skill_name in player_skill_names:
                    if skill_name in total_battle_process:
                        matched_skills.add(skill_name)

                if matched_skills:
                    for skill_name in matched_skills:
                        exp_gain = random.randint(1, 3)
                        player_obj.add_exp(skill_name, exp_gain)  # 瓶颈进度由 add_exp 自动转化
                        print(f"【战斗感悟】{skill_name} +{exp_gain} 点经验")
                else:
                    # 全程都没有提到任何武功 → 随机选一个武功 +1 点经验
                    random_skill = random.choice(player_obj.martial_skill_list)["skill_name"]
                    exp_gain = random.randint(1, 5)
                    player_obj.add_exp(random_skill, exp_gain)
                    print(f"【战斗感悟】{random_skill} +{exp_gain} 点经验（随机）")

                player_obj.sync_overall_level()
                player_obj.save()

            BATTLE_CACHE["battle_summary"] = total_battle_process[:600]
            BATTLE_CACHE["battle_result"] = final_end
            BATTLE_CACHE["in_battle"] = False

            new_branch = branch_text + "\n【对战剧情】" + total_battle_process + "\n【对战结局】" + final_end
            update_plot_func(his_text, new_branch)
            print(f"\n{COLOR_SYSTEM}✅ 对战结束，剧情已自动存档，返回主游戏{COLOR_END}")
            break


        # ① 继续战斗，玩家自定义出招，AI承接打斗
        if opt == "1":
            player_attack = input(f"{COLOR_GREEN}请输入本回合出招/打斗动作：{COLOR_END}").strip()
            if not player_attack:
                print(f"{COLOR_WARN}【输入为空，请重新选择】{COLOR_END}")
                BATTLE_CACHE["battle_round"] -= 1
                continue

            # ★ 骰子检定：正则检测武功名→AI判DC→程序掷骰（与web端正常剧情一致路径）
            _dice_constraint = ""
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
                        # AI只判DC（传入target_npc作为extra_npcs，支持临时生成的对手）
                        _extra_npcs = [target_npc] if target_npc else []
                        _active_npcs_brief = dice_build_active_npcs_brief(
                            npc_data_raw, player_attack, last_round_process or "",
                            extra_npcs=_extra_npcs
                        )
                        # 对手锚定：防止场景残留其他NPC名导致DC判定对象跑偏
                        _target_line = dice_build_target_npc_line(target_npc) if target_npc else ""
                        _dc, _dc_reason = dice_ai_judge_dc_only(
                            llm_func=llm_common_func,
                            scene=last_round_process or "",
                            user_action=player_attack,
                            skill_name=_skill_name,
                            skill_level=_skill_level,
                            grade=_grade,
                            skill_list_summary=_pobj.get_skill_list_summary(),
                            overall_realm=_pobj.overall_realm,
                            active_npcs_text=_active_npcs_brief,
                            target_npc_text=_target_line,
                        )
                        # 传入preset跳过AI need_check判定，直接掷骰
                        _check_result = dice_resolve_check_v4(
                            player_obj=_pobj,
                            user_action=player_attack,
                            l1_scene=last_round_process or "",
                            llm_func=llm_common_func,
                            preset_skill_name=_skill_name,
                            preset_dc=_dc,
                            preset_dc_reason=_dc_reason,
                            classified_skills=_classified,
                        )
                        if _check_result and _check_result.get("constraint_text"):
                            _dice_constraint = "\n" + _check_result["constraint_text"]
                            _verdict = _check_result.get("verdict", "?")
                            _dice_natural = _check_result.get("dice_natural", 0)
                            _dice_total = _check_result.get("dice_total", 0)
                            print(f"{COLOR_WARN}🎲 本回合骰子检定: {_skill_name} d20={_dice_natural} → 总计={_dice_total} vs DC{_dc} → {_verdict}{COLOR_END}")
            except Exception as _e:
                print(f"{COLOR_WARN}[骰子] 对战检定异常: {_e}{COLOR_END}")

            # 生成本回合打斗
            round_plot = gen_single_battle_round(
                llm_func=llm_common_func,
                player_data=json.dumps(player_data_raw, ensure_ascii=False),
                npc_data=json.dumps(target_npc, ensure_ascii=False),
                round_num=current_round,
                player_attack_text=player_attack,
                last_process=last_round_process,
                battle_style_desc=battle_style_desc,  # 新增传参
                dice_constraint=_dice_constraint
            )

            if not round_plot:
                print(f"{COLOR_WARN}【本回合对战生成失败，跳过】{COLOR_END}")
                BATTLE_CACHE["battle_round"] -= 1
                continue

            # 累加对战记录
            total_battle_process += f"\n【第{current_round}回合】{round_plot}"
            last_round_process = round_plot

            # ===== V5：CLI对战每回合体力结算（与web端一致） =====
            try:
                _vit_log = settle_battle_round_vitality(
                    round_plot,
                    player_name=player_obj.name if player_obj else None,
                    target_name=target_npc.get("name"),
                    target_persisted=target_npc.get("name") in db_npc_name_map,
                )
                if _vit_log:
                    print(_vit_log)
                # ===== 对战回合回气：双方 MP+5%（先结算掉蓝再回气） =====
                _regen_log = vitality_system.battle_regen_mp(
                    player_obj.name if player_obj else None,
                    [target_npc.get("name")] if target_npc.get("name") else [],
                )
                if _regen_log:
                    print(_regen_log)
            except Exception as _ve:
                print(f"{COLOR_WARN}[WARN] 对战体力结算异常: {_ve}{COLOR_END}")

            # 打印本回合对战剧情
            print(f"\n{COLOR_BATTLE}【第{current_round}回合 对战剧情】{COLOR_END}")
            print(f"{round_plot}")
            continue
            
        if opt == "4":
            from image_generator import draw_ascii
            # 拼接本场全部对战剧情传给绘图接口
            battle_full_text = f"武侠对战场景，对手：{BATTLE_CACHE['battle_target']}，全程打斗内容：{total_battle_process}"
            print(f"\n{COLOR_SYSTEM}正在生成本场对战古风ASCII画面...{COLOR_END}")
            draw_ascii(latest_plot=battle_full_text) 
            continue


        # 无效输入
        else:
            print(f"{COLOR_WARN}【无效指令，请输入 1 / 2 / 3】{COLOR_END}")
            BATTLE_CACHE["battle_round"] -= 1
            continue
