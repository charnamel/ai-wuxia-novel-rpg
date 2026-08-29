# dice_system.py - 骰子检定系统
# 参考 DiceFrame (D:\code\4\diceframe1) 设计，适配武侠AI互动小说场景
# 设计原则: 纯程序判定 + AI辅助DC + 硬约束文本注入AI上下文
#
# V4 核心流程（武功品阶+境界双值）:
#   1. detect_martial_skill() → 正则检测武功名（不用AI）
#   2. ai_judge_check_v4() → AI判定是否需要检定+使用武功
#   3. ai_judge_dc_only() → AI动态判定DC
#   4. check_d20() → 程序掷骰（随机数，非AI）
#   5. build_constraint_text_v4() → 生成【系统检定·必须遵循】硬约束文本
#   6. resolve_check_v4() → 对外主入口，串联全部步骤

from __future__ import annotations

import json
import random
import re
import logging

logger = logging.getLogger("dice_system")

# 最近一次DC判定的行动类型（"battle"/"daily"），ai_judge_dc_only 副作用写入，供对战回气等逻辑读取
_LAST_DC_ACTION_TYPE = "daily"

# 最近一次DC判定的对手境界（None=日常/未知），ai_judge_dc_only 副作用写入，
# 供 judge_grade_v4 境界差直通使用（preset_dc 路径也能读取）
_LAST_DC_OPPONENT_REALM = None


# ==================== 1. 基础骰子引擎 ====================

def roll(formula: str) -> dict:
    """基础骰子投掷引擎（纯程序，无AI依赖）
    
    支持格式: d20, d20+3, 2d6, 2d6+1, d100, 3d8-2
    
    Args:
        formula: 骰子公式字符串，如 "d20+3"
        
    Returns:
        {"formula": str, "rolls": [int], "modifier": int, "total": int, "natural": int}
        
    Raises:
        ValueError: 无效的骰子公式
    """
    formula = formula.strip().lower().replace(" ", "")
    match = re.match(r"(\d+)?d(\d+)([+-]\d+)?$", formula)
    if not match:
        raise ValueError(f"无效的掷骰公式: {formula}")

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    mod_str = match.group(3)
    modifier = int(mod_str) if mod_str else 0

    rolls = [random.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    natural = rolls[0] if count == 1 else total

    return {
        "formula": formula,
        "rolls": rolls,
        "modifier": modifier,
        "total": total,
        "natural": natural,
    }


def check_d20(modifier: int = 0, dc: int = 10,
              advantage: bool = False, disadvantage: bool = False) -> tuple[dict, str]:
    """d20 属性检定（D&D 5e风格，兼容DiceFrame）
    
    Args:
        modifier: 属性修正值，如 +2 或 -1
        dc: 难度等级 (Difficulty Class)
        advantage: 是否优势（掷两个d20取高）
        disadvantage: 是否劣势（掷两个d20取低）
        
    Returns:
        (result_dict, verdict_string)
        verdict: "大成功" | "成功" | "失败" | "大失败"
        
    判定规则:
        natural=20 → "大成功"（无论DC）
        natural=1  → "大失败"（无论DC）
        total >= dc → "成功"
        total < dc  → "失败"
    """
    # 优势和劣势同时存在则抵消
    if advantage and disadvantage:
        advantage = False
        disadvantage = False

    if advantage or disadvantage:
        rolls = [random.randint(1, 20), random.randint(1, 20)]
        natural = max(rolls) if advantage else min(rolls)
        mode = "kh1" if advantage else "kl1"
        formula = f"2d20{mode}{modifier:+d}" if modifier else f"2d20{mode}"
    else:
        rolls = [random.randint(1, 20)]
        natural = rolls[0]
        formula = f"d20{modifier:+d}" if modifier else "d20"

    total = natural + modifier

    result = {
        "formula": formula,
        "rolls": rolls,
        "natural": natural,
        "modifier": modifier,
        "total": total,
        "dc": dc,
    }

    # 大成功判定
    if natural == 20:
        result["is_critical"] = True
        result["is_fumble"] = False
        return result, "大成功"

    # 大失败判定
    if natural == 1:
        result["is_critical"] = False
        result["is_fumble"] = True
        return result, "大失败"

    # 普通判定
    result["is_critical"] = False
    result["is_fumble"] = False
    return result, "成功" if total >= dc else "失败"


# ==================== 2. 规则加载（JSON配置驱动，可热更新） ====================

import os as _os

_RULES_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "dice_rules.json")
_EFFECT_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "effect_config.json")

# ---- 内置兜底规则（JSON文件缺失/损坏时使用）----
_BUILTIN_CMD_KEYWORDS = [
    "等级", "功法", "物品", "传闻", "配图", "查看时空", "任务",
    "查询历史", "看看江湖传闻", "回归主线", "主线完成",
    "对战", "练功", "遗忘功法", "扔掉物品", "设置NPC", "治愈NPC",
    "存档", "exit", "地图", "一键回血", "整理物品",
    "修复NPC", "新增NPC", "忘记武功",
]

_BUILTIN_SKIP_PATTERNS = [
    "看看", "逛逛", "走走", "吃饭", "喝水", "睡觉", "坐下", "站起",
    "歇", "休息", "打个盹", "打个哈欠", "伸懒腰", "发呆",
]

# ---- 模块级可变状态（由 _load_rules / reload_rules 更新）----
SYSTEM_COMMAND_KEYWORDS: list = []
SKIP_PATTERNS: list = []
_loaded_from_file: bool = False


def _load_rules(filepath: str = None) -> bool:
    """从JSON加载规则配置，填充模块级变量。失败时回退内置规则。

    Returns:
        True: 成功从JSON加载
        False: 回退到内置规则
    """
    global SYSTEM_COMMAND_KEYWORDS, SKIP_PATTERNS, _loaded_from_file

    path = filepath or _RULES_FILE

    try:
        if not _os.path.exists(path):
            raise FileNotFoundError(f"规则文件不存在: {path}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # 加载命令关键词
        raw_cmds = data.get("system_command_keywords", [])
        SYSTEM_COMMAND_KEYWORDS[:] = [c for c in raw_cmds if not (isinstance(c, str) and c.startswith("_comment"))]

        # 加载跳过模式
        raw_skips = data.get("skip_patterns", [])
        SKIP_PATTERNS[:] = [s for s in raw_skips if not (isinstance(s, str) and s.startswith("_comment"))]

        _loaded_from_file = True
        logger.info("骰子规则已加载: %s", path)
        return True

    except Exception as e:
        logger.debug("骰子规则加载失败，回退内置规则: %s", e)
        # 回退内置规则
        SYSTEM_COMMAND_KEYWORDS = list(_BUILTIN_CMD_KEYWORDS)
        SKIP_PATTERNS = list(_BUILTIN_SKIP_PATTERNS)
        _loaded_from_file = False
        return False


def reload_rules(filepath: str = None) -> bool:
    """热重载规则配置（运行时调用，无需重启）"""
    ok = _load_rules(filepath)
    level = logging.INFO if ok else logging.WARNING
    logger.log(level, "骰子规则热重载: %s", "成功" if ok else "回退内置规则")
    return ok


def get_rules_info() -> dict:
    """返回当前规则集摘要信息"""
    return {
        "command_keywords_count": len(SYSTEM_COMMAND_KEYWORDS),
        "loaded_from_file": _loaded_from_file,
    }


# ---- 模块初始化时自动加载 ----
_load_rules()


# ==================== 3. 系统命令识别 ====================

def should_skip(action: str) -> bool:
    """判断是否为系统命令/特殊指令，不应触发检定
    
    Args:
        action: 玩家输入
        
    Returns:
        True: 应跳过检定（系统命令、空输入等）
    """
    action = str(action or "").strip()
    if not action:
        return True

    for cmd in SYSTEM_COMMAND_KEYWORDS:
        if cmd in action:
            return True

    return False


def parse_dc_json(text: str) -> tuple[int, str]:
    """从AI返回文本中提取DC值和原因
    
    Args:
        text: AI返回的文本
        
    Returns:
        (dc: int, reason: str)
        解析失败返回 (0, "")
    """
    if not text:
        return 0, ""

    # 尝试直接解析JSON
    text = text.strip()
    try:
        data = json.loads(text)
        dc = int(data.get("dc", 0))
        reason = str(data.get("reason", ""))
        return dc, reason
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # 尝试从文本中提取JSON块
    json_match = re.search(r'\{[^{}]*"dc"\s*:\s*\d+[^{}]*\}', text)
    if json_match:
        try:
            data = json.loads(json_match.group())
            dc = int(data.get("dc", 0))
            reason = str(data.get("reason", ""))
            return dc, reason
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # 正则兜底: 提取数字
    dc_match = re.search(r'"dc"\s*:\s*(\d+)', text)
    if dc_match:
        dc = int(dc_match.group(1))
        reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', text)
        reason = reason_match.group(1) if reason_match else ""
        return dc, reason

    return 0, ""


# ==================== V4 武功检定系统 ====================
# V4: 基于"基础修正(整体境界) + 武功加成(品阶+境界)"双值计算
#     AI判定 need_check + skill_name + dc
#     8档分级判定（差值驱动）

# ---- V4 模块级状态变量（Web→main 传递，避免重复检定）----
WEB_PROCESSED_CONSTRAINT_V4 = ""   # Web端已处理的约束文本
WEB_PROCESSED_RESULT_V4 = None     # Web端已处理的检定结果 dict
WEB_SKIPPED_V4 = False             # Web端用户跳过检定


def clear_web_state_v4():
    """清空 V4 Web 状态（每次新行动前调用）"""
    global WEB_PROCESSED_CONSTRAINT_V4, WEB_PROCESSED_RESULT_V4, WEB_SKIPPED_V4
    WEB_PROCESSED_CONSTRAINT_V4 = ""
    WEB_PROCESSED_RESULT_V4 = None
    WEB_SKIPPED_V4 = False


# ---- V4 8档分级判定表 ----
# (min_delta, grade, name, narrative_template)
# V4: 正态形区间——4/5档最宽(中心),3/6档次之,2/7档收窄,1/8档±18帽
# 中间档位在典型对局(s=-4~-9)中高频出现,极端档位留给nat特判与境界差直通
_DELTA_GRADE_TABLE = [
    (18,    1, "完美碾压", "超凡入化,如有神助——招式威力远超平常,对手门户大开毫无还手之力,正是施展压箱底绝学的时机(程序将直挂武学特效)"),
    (14,    2, "超常发挥", "行云流水,一气呵成,远超平时水准,目标顺利达成且占尽先手——正是趁势施展绝学的良机(程序将随机挂载武学特效)"),
    (8,     3, "正常发挥", "得心应手,招式熟练,符合自身预期水准,一切按部就班"),
    (0,     4, "差强人意", "成败只在毫厘之间,勉强撑住场面未落下风,但过程波折频频,有可能无功而返"),
    (-7,    5, "功亏一篑", "差距显现,功力稍欠火候,主要目标未能达成,但尚有余力自保,全身而退"),
    (-13,   6, "拙于应对", "应对失当,招式生涩,破绽频出,目标落空,且自身挂彩受伤"),
    (-17,   7, "力屈受挫", "力有不逮,遭对手全面压制,目标完全落空,身受明显创伤,元气受损——对手将趁势施展得意反手绝学"),
    (-9999, 8, "惨败而归", "差距悬殊,大败亏输,门户大开身受重创——对手将趁势施展得意反手绝学,恶果接连而至"),
]


# ==================== V4 增幅检定系统 ====================
# 辅助类武功（内功+轻功）作为攻击武功的增幅器
# 增幅率 = (辅助武功品阶加成 + 辅助武功境界加成) / 20

# 武功分类：辅助类（内功+轻功） vs 攻击类（其他）
SUPPORT_CATEGORIES = {"internal", "lightfoot"}
ATTACK_CATEGORIES = {"sword", "blade", "palm", "staff", "finger", "hidden", "fist", "special"}

# 增幅率分母（控制增幅范围：内功总值-1~+12 → 增幅率-4%~52%）
# V3: 从20调到25,降低增幅约20%
_AMPLIFY_DIVISOR = 25


def _fair_round(x):
    """公平四舍五入：0.5时向上取整（对玩家公平）"""
    if x >= 0:
        return int(x + 0.5)
    return int(x - 0.5 + 1)


def _compute_amplify_rate(support_skill_info: dict) -> float:
    """计算辅助武功的增幅率

    公式: (品阶加成 + 境界加成) / 20
    范围: -5% (1级+初学入门) ~ 60% (9级+破碎虚空)

    Args:
        support_skill_info: get_skill_info() 返回的 dict，含 bonus/realm_bonus

    Returns:
        增幅率（小数，如0.4表示40%）
    """
    if not support_skill_info:
        return 0.0
    bonus = int(support_skill_info.get("bonus", 0))
    realm_bonus = int(support_skill_info.get("realm_bonus", 0))
    rate = (bonus + realm_bonus) / _AMPLIFY_DIVISOR
    print(f"  [增幅DEBUG] {support_skill_info.get('skill_name','')}: bonus={bonus} + realm_bonus={realm_bonus} → 增幅率={rate:.1%}")
    return rate


def compute_amplify_bonus(attack_total: int,
                          inner_info: dict = None,
                          light_info: dict = None) -> tuple:
    """计算辅助武功对攻击的总增幅值

    Args:
        attack_total: 攻击总修正（基础+武功品阶+武功境界）
        inner_info: 内功的 skill_info（None表示无内功）
        light_info: 轻功的 skill_info（None表示无轻功）

    Returns:
        (total_amplify, detail_dict)
        total_amplify: 增幅总值（int）
        detail_dict: {
            "inner_rate": float, "inner_amplify": int,
            "light_rate": float, "light_amplify": int,
            "inner_name": str, "light_name": str,
        }
    """
    total_amplify = 0
    detail = {
        "inner_rate": 0.0, "inner_amplify": 0, "inner_name": "",
        "light_rate": 0.0, "light_amplify": 0, "light_name": "",
    }

    print(f"  [增幅DEBUG] 攻击总修正={attack_total}")

    if inner_info:
        rate = _compute_amplify_rate(inner_info)
        amp = _fair_round(attack_total * rate)
        # 保底1: 有内功催动但增幅值算出来为0时,至少+1
        if amp == 0 and attack_total > 0:
            amp = 1
            print(f"  [增幅DEBUG] 内功·保底+1（计算值为0,有内功催动保底）")
        total_amplify += amp
        detail["inner_rate"] = rate
        detail["inner_amplify"] = amp
        detail["inner_name"] = inner_info.get("skill_name", "")
        print(f"  [增幅DEBUG] 内功·{detail['inner_name']}: {attack_total} × {rate:.1%} = {attack_total*rate:.2f} → 增幅值={amp}")

    if light_info:
        rate = _compute_amplify_rate(light_info) / 2.0  # 轻功增幅为内功的一半
        amp = _fair_round(attack_total * rate)
        # 保底1: 有轻功催动但增幅值算出来为0时,至少+1
        if amp == 0 and attack_total > 0:
            amp = 1
            print(f"  [增幅DEBUG] 轻功·保底+1（计算值为0,有轻功催动保底）")
        total_amplify += amp
        detail["light_rate"] = rate
        detail["light_amplify"] = amp
        detail["light_name"] = light_info.get("skill_name", "")
        print(f"  [增幅DEBUG] 轻功·{detail['light_name']}: {attack_total} × {rate:.1%}(减半) = {attack_total*rate:.2f} → 增幅值={amp}")

    print(f"  [增幅DEBUG] 增幅总计: +{total_amplify}")

    return total_amplify, detail


# ==================== V5 武功特效锚点制（去概率化） ====================
# 设计: 程序零掷骰零概率。特效是否出现由DC档位锚点+AI剧情裁量决定：
#   1/2档（完美碾压/超常发挥）→ 玩家武功特效程序直挂（多特效源随机选1条，必兑现大成功）
#   3-6档                       → 程序不干预，AI通过effect_update工具自行决定挂不挂
#   7/8档（力屈受挫/惨败而归）→ 对手NPC配了effect_triggers则随机硬挂1条（反手招），
#                               未配置则指令约束AI必须给自己报一条不利状态

# ---- 特效元数据缓存（模块级）----
_effect_meta_cache: dict = None
_effect_meta_mtime = None


def _load_effect_meta() -> dict:
    """加载 effect_config.json 特效元数据,带缓存

    Returns:
        {"effects": {effect_id: {name, category, desc, ...}}}
        （effect_config.json 为平铺结构,这里包装成旧 martial_effects.json 结构,
          下游 name/category 读取代码零改动;
          不带category的条目为纯内部状态,不进武功编辑器下拉框）
        热联动:文件mtime变化自动重载（手改json保存后无需重启）
        文件缺失/损坏时返回空dict
    """
    global _effect_meta_cache, _effect_meta_mtime
    try:
        mtime = _os.path.getmtime(_EFFECT_FILE)
    except Exception:
        mtime = None
    if _effect_meta_cache is not None and _effect_meta_mtime == mtime:
        return _effect_meta_cache
    try:
        with open(_EFFECT_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        _effect_meta_cache = {
            "effects": {k: v for k, v in raw.items()
                        if not str(k).startswith("_") and isinstance(v, dict)},
        }
        _effect_meta_mtime = mtime
    except Exception as e:
        logger.warning("特效元数据加载失败: %s", e)
        _effect_meta_cache = {"effects": {}}
        _effect_meta_mtime = mtime
    return _effect_meta_cache


def reload_effect_meta() -> bool:
    """热重载特效元数据（武功书模块编辑后调用；mtime热重载下通常自动生效）"""
    global _effect_meta_cache, _effect_meta_mtime
    _effect_meta_cache = None
    _effect_meta_mtime = None
    meta = _load_effect_meta()
    ok = bool(meta.get("effects"))
    logger.info("特效元数据热重载: %s", "成功" if ok else "失败")
    return ok


def lookup_skill_effect(skill_name: str) -> dict | None:
    """从武功书查询某武功的特效配置

    Args:
        skill_name: 武功名

    Returns:
        {"type": str} 或 None（无特效配置）
    """
    if not skill_name:
        return None
    try:
        from player_manager import lookup_skill_in_book
        # lookup_skill_in_book 仅返回 grade/bonus/category/source,不返回 effect
        # 这里直接读武功书原始JSON,避免漏掉 effect 字段
        book = lookup_skill_in_book(skill_name)
        if not book:
            return None
    except Exception:
        return None
    # 直接从武功书文件读取 effect 字段
    try:
        book_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                   "data", "martial_arts_bonus.json")
        with open(book_path, encoding="utf-8-sig") as f:
            data = json.load(f)
        arts = data.get("martial_arts", {})
        # 精确匹配
        if skill_name in arts and arts[skill_name].get("effect"):
            return arts[skill_name]["effect"]
        # 模糊匹配（去括号）
        import re as _re
        base_name = _re.sub(r'[（(].*?[）)]', '', skill_name).strip()
        if base_name and base_name != skill_name and base_name in arts:
            if arts[base_name].get("effect"):
                return arts[base_name]["effect"]
    except Exception as e:
        logger.debug("查武功特效失败(%s): %s", skill_name, e)
    return None


def lookup_special_move(skill_name: str) -> dict | None:
    """从武功书查询某武功的特技名和描述

    Args:
        skill_name: 武功名

    Returns:
        {"special_move_name": str, "special_move_desc": str} 或 None（无特技配置）
    """
    if not skill_name:
        return None
    try:
        book_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                   "data", "martial_arts_bonus.json")
        with open(book_path, encoding="utf-8-sig") as f:
            data = json.load(f)
        arts = data.get("martial_arts", {})
        # 精确匹配
        if skill_name in arts:
            entry = arts[skill_name]
            name = entry.get("special_move_name", "").strip()
            if name:
                return {"special_move_name": name,
                        "special_move_desc": entry.get("special_move_desc", "").strip()}
        # 模糊匹配（去括号）
        import re as _re
        base_name = _re.sub(r'[（(].*?[）)]', '', skill_name).strip()
        if base_name and base_name != skill_name and base_name in arts:
            entry = arts[base_name]
            name = entry.get("special_move_name", "").strip()
            if name:
                return {"special_move_name": name,
                        "special_move_desc": entry.get("special_move_desc", "").strip()}
    except Exception as e:
        logger.debug("查武功特技失败(%s): %s", skill_name, e)
    return None


def compute_effect_trigger(
    skill_name: str,
    player_obj,
    classified_skills: dict | None = None,
    grade_result: int = 0,
    inner_info: dict = None,
    light_info: dict = None,
) -> dict | None:
    """武功特效锚点制（V5，零概率零掷骰）

    Args:
        skill_name: 武功名
        player_obj: Player对象（锚点制下仅用于存在性校验）
        classified_skills: 分类检测结果（保留签名兼容,未使用）
        grade_result: DC判定档位 1-8
        inner_info: 内功 skill_info（锚点制下不参与计算,未使用）
        light_info: 轻功 skill_info（未使用）

    Returns:
        None: 武功无特效配置
        dict: {
            "skill_name": str,
            "effect_type": str,        # 如 "shock"
            "effect_name": str,        # 如 "震慑"
            "effect_category": str,    # 如 "attack"
            "triggered": bool,         # 仅1/2档为True（程序直挂硬锚点）
            "anchor": str,             # "grade12"（程序直挂）| "ai"（交AI裁量）
            "narrative_hint": str,     # 1/2档时的⚡绝招叙述行
            "ref_hint": str,           # 3档以上给AI的优先提示行
        }
    """
    if not skill_name or not player_obj:
        return None

    effect_cfg = lookup_skill_effect(skill_name)
    if not effect_cfg:
        return None

    effect_type = str(effect_cfg.get("type", "")).strip()
    if not effect_type:
        return None

    meta = _load_effect_meta()
    effect_meta = meta.get("effects", {}).get(effect_type)
    if not effect_meta:
        effect_name = effect_type
        effect_category = "attack"
    else:
        effect_name = effect_meta.get("name", effect_type)
        effect_category = effect_meta.get("category", "attack")

    _grade = int(grade_result)
    triggered = _grade in (1, 2)
    anchor = "grade12" if triggered else "ai"

    narrative_hint = ""
    if triggered:
        special = lookup_special_move(skill_name)
        if special and special.get("special_move_name"):
            narrative_hint = f"⚡{skill_name}特技发动·{special['special_move_name']} — {special['special_move_desc']}"

    if _grade in (3, 4):
        ref_hint = f"参考：玩家武功【{skill_name}】自带特效【{effect_name}】（{effect_category}类），本轮发挥上佳，可顺手演绎出该特效雏形（可选，通过effect_update上报）"
    else:
        ref_hint = f"参考：玩家武功【{skill_name}】自带特效【{effect_name}】（{effect_category}类），若剧情合理可挂载（通过effect_update上报）"

    print(f"[特效锚点] {skill_name} → {effect_name}({effect_type}) 第{_grade}档 → "
          f"{'✓程序直挂' if triggered else '交AI裁量'}")

    return {
        "skill_name": skill_name,
        "effect_type": effect_type,
        "effect_name": effect_name,
        "effect_category": effect_category,
        "triggered": triggered,
        "anchor": anchor,
        "narrative_hint": narrative_hint,
        "ref_hint": ref_hint,
    }


# ---- NPC特效反手招（V5锚点制：7档力屈受挫/8档惨败时硬挂） ----


def compute_npc_effect_trigger(npc_data: dict, grade_result: int) -> list:
    """NPC反手招锚点制（零概率）

    仅当玩家DC档位∈{7,8}（力屈受挫/惨败而归）时生效：
      - NPC配了effect_triggers → 随机选1条硬挂（target语义见配置）
      - 未配置 → 返回[{"anchor": "directive"}]提示管线走指令兜底
    其余档位一律返回空列表（交AI剧情裁量）。

    Args:
        npc_data: NPC完整档案dict（须含 effect_triggers 字段才硬挂）
        grade_result: 本轮玩家DC检定档位（1-8）

    Returns:
        结果列表（0或1条）。
        硬挂条: {"effect_type", "effect_name", "triggered": True, "anchor": "grade78", "target"}
        指令兜底条: {"anchor": "directive", "npc_name": str}
    """
    try:
        _grade = int(grade_result)
        if _grade not in (7, 8):
            return []
        if not isinstance(npc_data, dict):
            return [{"anchor": "directive", "npc_name": ""}]
        triggers = npc_data.get("effect_triggers")
        if not isinstance(triggers, dict) or not triggers:
            return [{"anchor": "directive", "npc_name": str(npc_data.get("name", ""))}]

        meta = _load_effect_meta().get("effects", {})
        candidates = []
        for eid, conf in triggers.items():
            eid = str(eid).strip()
            if not eid:
                continue
            if not isinstance(conf, dict):
                conf = {}
            effect_meta = meta.get(eid)
            candidates.append({
                "effect_type": eid,
                "effect_name": (effect_meta or {}).get("name", eid),
                "triggered": True,
                "anchor": "grade78",
                "target": str(conf.get("target", "opponent")).strip() or "opponent",
            })
        if not candidates:
            return [{"anchor": "directive", "npc_name": str(npc_data.get("name", ""))}]
        pick = random.choice(candidates)
        print(f"[NPC反手招] {npc_data.get('name','?')} 第{_grade}档硬挂 "
              f"{pick['effect_name']}({pick['effect_type']}) target={pick['target']}")
        return [pick]
    except Exception as e:
        logger.debug("NPC反手招计算异常(已忽略): %s", e)
        return []


def compute_npc_effect_hint(npc_data: dict) -> str:
    """NPC反手招2-6档优先提示（零概率，纯提示不挂载）

    把NPC配置的effect_triggers列成一行提示注入constraint_text，
    让NPC招牌特效在非7/8档也有剧情存在感（AI按剧情裁量是否体现）。

    Args:
        npc_data: NPC完整档案dict

    Returns:
        str: 提示行（无配置返回空串）
    """
    try:
        if not isinstance(npc_data, dict):
            return ""
        triggers = npc_data.get("effect_triggers")
        if not isinstance(triggers, dict) or not triggers:
            return ""
        meta = _load_effect_meta().get("effects", {})
        names = []
        for eid in triggers:
            eid = str(eid).strip()
            if eid:
                names.append((meta.get(eid) or {}).get("name", eid))
        if not names:
            return ""
        npc_name = str(npc_data.get("name", "")).strip() or "对手"
        eff_part = "、".join(f"【{n}】" for n in names)
        return (f"参考：对手【{npc_name}】惯用反手{eff_part}，"
                "若剧情合理可让NPC主动施展（通过effect_update上报）")
    except Exception as e:
        logger.debug("NPC反手招提示异常(已忽略): %s", e)
        return ""


def judge_grade_v4(delta: int, natural: int,
                  player_realm_idx: int = None,
                  opponent_realm_idx: int = None) -> tuple[int, str, str]:
    """V4 8档分级判定

    Args:
        delta: 判定差值 = (d20 + 总修正) - DC
        natural: d20自然值
        player_realm_idx: 玩家境界索引（REALM_ORDER中的序号，None=未知）
        opponent_realm_idx: 对手境界索引（None=日常行动/未知）

    Returns:
        (grade, grade_name, narrative_template)

    V4规则:
        1档(完美碾压) 保持条件: natural=20 或 玩家境界≥对手境界+6档（境界差直通）
        8档(惨败而归) 保持条件: natural=1 或 对手境界≥玩家境界+6档（境界差直通）
        natural 20: 升2档 / natural 1: 降2档
    """
    # 境界差直通：±6档及以上的绝对碾压，允许突破nat限制进入1/8档
    _player_dominates = (player_realm_idx is not None and opponent_realm_idx is not None
                         and player_realm_idx - opponent_realm_idx >= 6)
    _opponent_dominates = (player_realm_idx is not None and opponent_realm_idx is not None
                           and opponent_realm_idx - player_realm_idx >= 6)

    # 先按差值定基础档位
    base_grade = 8
    base_name = "惨败而归"
    base_narr = ""
    for min_delta, grade, name, narr in _DELTA_GRADE_TABLE:
        if delta >= min_delta:
            base_grade = grade
            base_name = name
            base_narr = narr
            break

    # natural 特判：20升2档，1降2档
    final_grade = base_grade
    if natural == 20:
        final_grade = max(1, base_grade - 2)  # 档位编号越小越好
    elif natural == 1:
        final_grade = min(8, base_grade + 2)

    # V4: 1档/8档保持条件（nat特判 或 境界差直通）
    # 1档: natural=20 或 玩家境界碾压对手6档以上时保持, 否则降为2档
    if final_grade == 1 and natural != 20 and not _player_dominates:
        final_grade = 2
    # 8档: natural=1 或 对手境界碾压玩家6档以上时保持, 否则升为7档
    if final_grade == 8 and natural != 1 and not _opponent_dominates:
        final_grade = 7

    # 如果档位变了，重新查名称
    if final_grade != base_grade:
        for min_delta, grade, name, narr in _DELTA_GRADE_TABLE:
            if grade == final_grade:
                base_name = name
                base_narr = narr
                break

    return final_grade, base_name, base_narr


# ---- V4 AI判定（一次调用完成 need_check + skill_name + dc）----

def detect_martial_skill(user_action: str, martial_skill_list: list, player_obj=None) -> list:
    """正则检测玩家输入是否包含武功名（不用AI）
    三级匹配:
    1. 精确匹配: 武功名完整出现在输入中
    2. 模糊匹配: 去括号后的基础名出现在输入中（"独孤九剑"→"独孤九剑（残）"）
    3. 类型匹配: 输入含"剑/刀/掌/拳/指/腿/脚/功/经"等关键字时，
       从同类型武功中选境界最高的（"一剑"→独孤九剑而非辟邪剑法）
       内功/轻功类型匹配时优先选用装备槽武功（已学会），无装备才退回exp最高

    Args:
        user_action: 玩家输入文本
        martial_skill_list: 玩家武功清单 [{skill_name, ...}, ...]

    Returns:
        命中的武功名列表，空列表表示未命中
    """
    action = str(user_action or "")
    if not action:
        return []

    # 境界档位排序表（用于类型匹配时选境界最高的）
    REALM_ORDER = ["初学入门", "初窥门径", "略有小成", "略有所成", "渐入佳境",
                   "融会贯通", "登堂入室", "炉火纯青", "出神入化", "登峰造极",
                   "超凡入圣", "返璞归真", "天人合一", "破碎虚空"]

    def _realm_idx(skill):
        """获取武功境界档位索引，越高越强"""
        level = skill.get("skill_level") or ""
        if not level:
            # 从exp推算（粗略）
            exp = int(skill.get("exp", 0))
            if exp >= 2700: level = "融会贯通"
            elif exp >= 1400: level = "渐入佳境"
            elif exp >= 700: level = "略有所成"
            elif exp >= 350: level = "略有小成"
            elif exp >= 150: level = "初窥门径"
            else: level = "初学入门"
        try:
            return REALM_ORDER.index(level)
        except ValueError:
            return 0

    # ===== 第1级: 精确匹配 =====
    matched = []
    for skill in martial_skill_list:
        skill_name = skill.get("skill_name", "")
        if not skill_name:
            continue
        if skill_name in action:
            matched.append(skill_name)
            print(f"  [武功检测] 精确匹配: '{skill_name}'")
            continue
        # 第2级: 模糊匹配（去括号）
        base_name = re.sub(r'[（(].*?[）)]', '', skill_name).strip()
        if base_name and base_name != skill_name and base_name in action:
            matched.append(skill_name)
            print(f"  [武功检测] 模糊匹配(去括号): '{skill_name}' → 基础名'{base_name}'")

    if matched:
        # 按exp降序（exp反映真实修炼程度，优先级高于境界字段）
        skill_map = {s.get("skill_name", ""): s for s in martial_skill_list}
        matched.sort(key=lambda n: (int(skill_map.get(n, {}).get("exp", 0)),
                                     _realm_idx(skill_map.get(n, {}))), reverse=True)
        print(f"  [武功检测] 精确/模糊命中: {matched} (已按exp优先降序)")

        # 检查是否只有辅助类（内功/轻功）命中，缺少攻击类
        # 如果是，则继续进入类型匹配补充攻击武功（不return）
        def _quick_cat(name):
            """快速判断类型（启发式，不用武功书避免循环导入）"""
            for kw in ("剑", "刀", "掌", "拳", "指", "腿", "脚"):
                if kw in name:
                    return "attack"
            for kw in ("功", "经", "气", "诀"):
                if kw in name:
                    return "internal"
            for kw in ("步", "轻功", "纵"):
                if kw in name:
                    return "lightfoot"
            return "unknown"

        has_attack = any(_quick_cat(n) == "attack" for n in matched)
        has_inner = any(_quick_cat(n) == "internal" for n in matched)
        has_light = any(_quick_cat(n) == "lightfoot" for n in matched)

        if has_attack:
            # 检查输入是否含有内功/轻功泛指词（需类型匹配补充辅助类）
            _action_no_lg = action.replace("轻功", "")  # 排除"轻功"中的"功"字干扰
            need_inner = (not has_inner) and any(kw in _action_no_lg for kw in ["内功", "内劲", "内力"])
            need_light = (not has_light) and any(kw in action for kw in ["轻功", "身法", "步法"])
            if not need_inner and not need_light:
                return matched
            # 继续类型匹配补充辅助类
            print(f"  [武功检测] 精确/模糊已命中攻击类,但输入含辅助类泛指词,继续类型匹配补充")
            existing = set(matched)
        else:
            print(f"  [武功检测] 精确/模糊仅命中辅助类，继续类型匹配补充攻击武功")
            # 保留辅助类已命中，类型匹配只补充攻击类（剑法/刀法等）
            existing = set(matched)
    else:
        has_attack = False
        has_inner = False
        has_light = False
        existing = set()
        print(f"  [武功检测] 精确/模糊未命中，进入类型匹配")

    # ===== 第3级: 类型匹配（输入含"剑/刀/掌/拳..."等关键字）=====
    # 输入匹配关键字（宽松，包含多种表达方式）
    TYPE_INPUT_KEYWORDS = [
        ("剑", ["剑"]),
        ("刀", ["刀"]),
        ("掌", ["掌"]),
        ("拳", ["拳"]),
        ("指腿", ["指", "爪", "腿", "脚", "一指", "一腿", "一脚", "一爪", "踢"]),  # 合并指+爪+腿脚
        ("棍枪", ["棍", "杖", "铲", "棒", "枪"]),           # 新增枪
        ("暗器", ["暗器", "镖", "针", "锒铛"]),
        ("特殊", ["鞭", "音", "琴", "箫", "声", "吼", "啸"]),  # 新增特殊类
        ("内功", ["功", "经", "气", "诀", "内劲", "内力", "真气"]),
        ("轻功", ["步", "轻功", "纵", "身法", "身形", "步法"]),
    ]
    # 武功名匹配关键字（精确，只用单字，避免多字词误匹配武功名）
    TYPE_SKILL_KEYWORDS = {
        "内功": ["功", "经", "气", "诀", "真气"],
        "轻功": ["步", "轻功", "纵"],
        "指腿": ["指", "爪", "腿", "脚"],            # 合并指+爪+腿脚
        "棍枪": ["棍", "杖", "铲", "棒", "枪"],      # 新增枪
        "暗器": ["镖", "针", "暗器", "锒铛"],
        "特殊": ["鞭", "音", "琴", "箫", "声", "吼", "啸"],  # 新增
    }

    # 收集每种类型各自最高的武功
    all_type_matches = list(existing)  # 包含精确/模糊已命中的武功（如果有）
    for type_name, input_kws in TYPE_INPUT_KEYWORDS:
        # 跳过已有精确匹配的类型（避免重复）
        if type_name == "内功" and has_inner:
            continue
        if type_name == "轻功" and has_light:
            continue
        # 攻击类：如果已有攻击类精确匹配，跳过攻击类型匹配
        if type_name not in ("内功", "轻功") and has_attack:
            continue
        # 第一层：检查玩家输入是否包含此类型的关键字
        # 内功类型特殊处理：排除"轻功"中的"功"字误匹配
        if type_name == "内功":
            action_for_check = action.replace("轻功", "")
            if not any(kw in action_for_check for kw in input_kws):
                continue
            print(f"  [武功检测] 类型匹配·{type_name}: 输入含内功关键字(已排除'轻功'干扰)")
        else:
            if not any(kw in action for kw in input_kws):
                continue
            print(f"  [武功检测] 类型匹配·{type_name}: 输入含关键字")
        # 第二层：从玩家武功清单中找同类型武功
        # 内功/轻功用精确关键字匹配武功名，其他类型用输入关键字
        skill_kws = TYPE_SKILL_KEYWORDS.get(type_name, input_kws)

        # ★ 装备槽优先：内功/轻功类型匹配时，装备槽有已学会的武功则优先选用
        if type_name in ("内功", "轻功") and player_obj is not None:
            _slot = "inner_martial" if type_name == "内功" else "light_martial"
            try:
                _eq_name = (player_obj.equipped or {}).get(_slot, "")
            except Exception:
                _eq_name = ""
            if _eq_name and any(s.get("skill_name") == _eq_name for s in martial_skill_list):
                if _eq_name not in all_type_matches:
                    all_type_matches.append(_eq_name)
                    print(f"  [武功检测] 类型匹配·{type_name}: 装备槽优先选中: '{_eq_name}'")
                continue  # 跳过本类型的exp最高选择

        type_skills = []
        for skill in martial_skill_list:
            skill_name = skill.get("skill_name", "")
            if not skill_name:
                continue
            if any(kw in skill_name for kw in skill_kws):
                type_skills.append(skill)
        if type_skills:
            # 按exp降序（exp反映真实修炼程度，优先级高于境界字段）
            type_skills.sort(key=lambda s: (int(s.get("exp", 0)), _realm_idx(s)), reverse=True)
            best = type_skills[0].get("skill_name", "")
            best_exp = int(type_skills[0].get("exp", 0))
            best_level = type_skills[0].get("skill_level", "")
            if best and best not in all_type_matches:
                all_type_matches.append(best)
                print(f"  [武功检测] 类型匹配·{type_name} 选中: '{best}' (境界={best_level}, exp={best_exp})")

    print(f"  [武功检测] 最终结果: {all_type_matches}")
    return all_type_matches


def detect_martial_skill_classified(user_action: str, martial_skill_list: list,
                                    player_obj=None) -> dict:
    """分类检测武功，区分辅助类（内功+轻功）和攻击类

    选择规则（每类独立选择）:
    - 精准匹配: 选文字中最后出现的那个
    - 模糊匹配: 选境界最高的那个
    - 类型匹配: 仅用于攻击类，选境界最高的

    Args:
        user_action: 玩家输入文本
        martial_skill_list: 玩家武功清单
        player_obj: Player对象（用于查武功category，可选）

    Returns:
        {
            "attack_skills": [str],   # 命中的攻击类武功名列表（已按规则排序）
            "support_skills": [str],  # 命中的辅助类武功名列表
            "all_matched": [str],     # 全部命中（向后兼容）
            "primary_attack": str,    # 选定的主攻击武功（""表示无）
            "primary_inner": str,     # 选定的内功（""表示无）
            "primary_light": str,     # 选定的轻功（""表示无）
            "match_type": str,        # "precise" | "fuzzy" | "type"
        }
    """
    # 先调用原函数获取全部命中
    all_matched = detect_martial_skill(user_action, martial_skill_list, player_obj)

    result = {
        "attack_skills": [],
        "support_skills": [],
        "all_matched": all_matched,
        "primary_attack": "",
        "primary_inner": "",
        "primary_light": "",
        "match_type": "fuzzy",
    }

    if not all_matched:
        print(f"  [分类DEBUG] 无武功命中")
        return result

    # 判断匹配类型：精准 vs 模糊
    # 精准匹配 = 武功名完整出现在输入中（非去括号匹配）
    action = str(user_action or "")
    has_precise = False
    for skill_name in all_matched:
        if skill_name in action:
            has_precise = True
            break
    result["match_type"] = "precise" if has_precise else "fuzzy"
    print(f"  [分类DEBUG] 匹配类型: {result['match_type']} (命中武功: {all_matched})")

    # 辅助函数：查武功category
    def _get_category(skill_name):
        if player_obj:
            info = player_obj.get_skill_info(skill_name)
            if info:
                # 查武功书获取category
                try:
                    from player_manager import lookup_skill_in_book
                    book_info = lookup_skill_in_book(skill_name)
                    cat = book_info.get("category", "")
                    print(f"  [分类DEBUG] _get_category('{skill_name}'): 武功书查到 → category='{cat}'")
                    return cat
                except Exception as e:
                    print(f"  [分类DEBUG] _get_category('{skill_name}'): 武功书未找到({e}) → 启发式判断")
            else:
                print(f"  [分类DEBUG] _get_category('{skill_name}'): 玩家未学此武功 → 启发式判断")
        # 启发式判断（攻击类优先，避免"七步追魂掌"含"步"被误判为轻功）
        # 先检查攻击类关键字（剑/刀/掌/拳/指/爪/腿/脚）
        for kw in ("剑", "刀", "掌", "拳", "指", "爪", "腿", "脚"):
            if kw in skill_name:
                print(f"  [分类DEBUG] _get_category('{skill_name}'): 启发式 → 含'{kw}' → 攻击类('')")
                return ""  # 攻击类
        # 再检查特殊类关键字（鞭/音/琴/箫/声/吼/啸）
        for kw in ("鞭", "音", "琴", "箫", "声", "吼", "啸"):
            if kw in skill_name:
                print(f"  [分类DEBUG] _get_category('{skill_name}'): 启发式 → 含'{kw}' → 特殊类('special')")
                return "special"
        # 再检查内功关键字
        for kw in ("功", "经", "气", "诀"):
            if kw in skill_name:
                print(f"  [分类DEBUG] _get_category('{skill_name}'): 启发式 → 含'{kw}' → 内功('internal')")
                return "internal"
        # 最后检查轻功关键字
        for kw in ("步", "轻功", "纵"):
            if kw in skill_name:
                print(f"  [分类DEBUG] _get_category('{skill_name}'): 启发式 → 含'{kw}' → 轻功('lightfoot')")
                return "lightfoot"
        print(f"  [分类DEBUG] _get_category('{skill_name}'): 启发式 → 未匹配任何关键字 → 默认攻击类('')")
        return ""

    # 分类
    attack_skills = []
    support_skills = []
    for skill_name in all_matched:
        cat = _get_category(skill_name)
        if cat in SUPPORT_CATEGORIES:
            support_skills.append(skill_name)
            print(f"  [分类DEBUG] '{skill_name}' → 辅助类({cat})")
        else:
            attack_skills.append(skill_name)
            print(f"  [分类DEBUG] '{skill_name}' → 攻击类")

    result["attack_skills"] = attack_skills
    result["support_skills"] = support_skills

    # 选定主攻击武功
    if attack_skills:
        if result["match_type"] == "precise":
            # 精准匹配: 选文字中最后出现的
            last_pos = -1
            last_name = attack_skills[0]
            for name in attack_skills:
                pos = action.rfind(name)
                print(f"  [分类DEBUG] 精准·攻击: '{name}' 出现位置={pos}")
                if pos >= last_pos:
                    last_pos = pos
                    last_name = name
            result["primary_attack"] = last_name
            print(f"  [分类DEBUG] 主攻击选定(精准·最后出现): '{last_name}' (位置={last_pos})")
        else:
            # 模糊匹配: 选境界最高的（列表第一个，原函数已按境界降序）
            result["primary_attack"] = attack_skills[0]
            print(f"  [分类DEBUG] 主攻击选定(模糊·境界最高): '{attack_skills[0]}'")

    # 选定主内功和主轻功
    if support_skills:
        if result["match_type"] == "precise":
            # 精准匹配: 选文字中最后出现的
            for name in support_skills:
                cat = _get_category(name)
                pos = action.rfind(name)
                print(f"  [分类DEBUG] 精准·辅助: '{name}'({cat}) 出现位置={pos}")
                if cat == "internal":
                    if not result["primary_inner"]:
                        result["primary_inner"] = name
                    else:
                        # 已有内功，比较位置取最后出现的
                        if action.rfind(name) > action.rfind(result["primary_inner"]):
                            result["primary_inner"] = name
                elif cat == "lightfoot":
                    if not result["primary_light"]:
                        result["primary_light"] = name
                    else:
                        if action.rfind(name) > action.rfind(result["primary_light"]):
                            result["primary_light"] = name
            print(f"  [分类DEBUG] 内功选定(精准·最后出现): '{result['primary_inner']}'")
            print(f"  [分类DEBUG] 轻功选定(精准·最后出现): '{result['primary_light']}'")
        else:
            # 模糊匹配: 选境界最高的（列表第一个）
            for name in support_skills:
                cat = _get_category(name)
                if cat == "internal" and not result["primary_inner"]:
                    result["primary_inner"] = name
                elif cat == "lightfoot" and not result["primary_light"]:
                    result["primary_light"] = name
            print(f"  [分类DEBUG] 内功选定(模糊·境界最高): '{result['primary_inner']}'")
            print(f"  [分类DEBUG] 轻功选定(模糊·境界最高): '{result['primary_light']}'")

    # ★ 装备槽兜底：精准匹配未命中内功/轻功时，从装备槽读取
    if player_obj and not result["primary_inner"]:
        try:
            equipped_inner = player_obj.equipped.get("inner_martial", "")
            if equipped_inner:
                result["primary_inner"] = equipped_inner
                print(f"  [分类DEBUG] 内功从装备槽读取: '{equipped_inner}'")
        except Exception:
            pass
    if player_obj and not result["primary_light"]:
        try:
            equipped_light = player_obj.equipped.get("light_martial", "")
            if equipped_light:
                result["primary_light"] = equipped_light
                print(f"  [分类DEBUG] 轻功从装备槽读取: '{equipped_light}'")
        except Exception:
            pass

    print(f"  [分类DEBUG] 最终结果: 攻击='{result['primary_attack']}' 内功='{result['primary_inner']}' 轻功='{result['primary_light']}'")

    return result


# 对战关键词（用于兜底DC判断）
_COMBAT_KEYWORDS = ("打", "战", "攻", "敌", "杀", "招", "剑", "刀", "掌",
                    "拳", "指", "腿", "脚", "击", "劈", "刺", "挡", "避", "斗", "对拼")


def _is_combat_action(user_action: str) -> bool:
    """粗判是否为对战类行动（用于兜底DC选择）"""
    action = str(user_action or "")
    return any(kw in action for kw in _COMBAT_KEYWORDS)


def _fallback_dc(user_action: str) -> int:
    """兜底DC：对战类行动14，日常行动12"""
    return 14 if _is_combat_action(user_action) else 12


def _clamp_dc(dc: int) -> int:
    """DC范围校验，限制到[5, 30]"""
    try:
        dc = int(dc)
    except (ValueError, TypeError):
        return 12
    return max(5, min(30, dc))


def _vit_text_for_npc(npc: dict, player_name: str = None) -> str:
    """生成NPC的HP/MP文本（供DC判定行内标注）。
    优先读档案vitality字段（落盘NPC），无则读临时缓存（临时NPC）。
    追加身上状态词条（effects），DC裁判可见中毒/受制等。
    返回如 "HP 45%/MP 0%（⚠内力枯竭）【化功散之毒×1·剩3轮】"，数据缺失返回空串。
    """
    try:
        import vitality_system as _vs
        name = str(npc.get("name", "")).strip()
        vit = npc.get("vitality")
        if not isinstance(vit, dict) or "hp" not in vit:
            vit = _vs.get_temp_vitality(name) if name else None
        if not vit:
            vit_text = ""
        else:
            hp, mp = vit.get("hp", 100), vit.get("mp", 100)
            if hp == -1:
                vit_text = "HP 已故"
            else:
                vit_text = f"HP {hp}%/MP {mp}%"
                if mp == 0:
                    vit_text += "（⚠内力枯竭：无法催动武功）"
                elif hp == 0:
                    vit_text += "（濒死锁血）"
        # 状态词条（跑不通最多不显示，不影响HP/MP部分）
        eff_text = ""
        try:
            eff_text = _vs.render_effects_line(name, player_name=player_name)
        except Exception:
            eff_text = ""
        if eff_text:
            vit_text = (vit_text + " " + eff_text).strip()
        return vit_text
    except Exception:
        return ""


def build_active_npcs_brief(npc_list_data, user_action: str,
                            recent_plot: str = "",
                            extra_npcs: list = None,
                            player_name: str = None) -> str:
    """构建活跃NPC精简摘要（供DC判定用）

    活跃判定: NPC名出现在 user_action 或 recent_plot 中
    返回精简字符串，如:
        任我行（日月神教教主）：吸星大法·绝顶 [健康]

    Args:
        npc_list_data: 从 npc_agents.json 加载的完整数据 dict
        user_action: 玩家本轮输入
        recent_plot: 最近剧情文本（可选）
        extra_npcs: 额外临时NPC列表（如AI实时生成的对手），格式同npc_list

    Returns:
        精简NPC摘要字符串，无活跃NPC时返回空串
    """
    if not npc_list_data and not extra_npcs:
        return ""

    # 合并数据库NPC + 临时NPC
    all_npcs = []
    if npc_list_data:
        npc_list = npc_list_data.get("npc_list", []) if isinstance(npc_list_data, dict) else []
        all_npcs.extend(npc_list)
    if extra_npcs:
        all_npcs.extend(extra_npcs)

    if not all_npcs:
        return ""

    combined = str(user_action or "") + " " + str(recent_plot or "")
    if not combined.strip():
        return ""

    _status_map = {
        "normal": "健康", "light_injured": "轻伤", "heavy_injured": "重伤",
        "dying": "濒死", "deceased": "已故", "poisoned": "中毒",
    }

    lines = []
    for npc in all_npcs:
        name = npc.get("name", "").strip()
        if not name or name not in combined:
            continue
        identity = npc.get("identity", "").strip()
        status = _status_map.get(npc.get("body_status", "normal"), "健康")
        # 武功信息（最多取3门）
        skills = npc.get("martial_skills", [])
        skill_parts = []
        for sk in skills[:3]:
            sk_name = sk.get("skill_name", "")
            sk_level = sk.get("skill_level", "")
            if sk_name:
                skill_parts.append(f"{sk_name}·{sk_level}" if sk_level else sk_name)
        skill_text = "、".join(skill_parts) if skill_parts else "武功不详"
        _vit = _vit_text_for_npc(npc, player_name=player_name)
        _vit_part = f" {_vit}" if _vit else ""
        lines.append(f"{name}（{identity}）：{skill_text} [{status}]{_vit_part}（注:此为完全体档案数据,需结合场景判断当前实际境界）")

    return "\n".join(lines)


def build_target_npc_line(npc: dict, player_name: str = None) -> str:
    """构建对战对手档案行（供DC判定的对手锚定块）。
    格式与 build_active_npcs_brief 一致，level 与主武功境界都列出。
    """
    if not isinstance(npc, dict):
        return ""
    name = str(npc.get("name", "")).strip()
    if not name:
        return ""
    identity = str(npc.get("identity", "")).strip()
    level = str(npc.get("level", "")).strip()
    _status_map = {
        "normal": "健康", "light_injured": "轻伤", "heavy_injured": "重伤",
        "dying": "濒死", "deceased": "已故", "poisoned": "中毒",
    }
    status = _status_map.get(str(npc.get("body_status", "normal")).strip(), "健康")
    skills = npc.get("martial_skills", []) or []
    skill_parts = []
    for sk in skills[:3]:
        if isinstance(sk, dict):
            sn = str(sk.get("skill_name", "")).strip()
            sl = str(sk.get("skill_level", "")).strip()
            if sn:
                skill_parts.append(f"{sn}·{sl}" if sl else sn)
    skill_text = "、".join(skill_parts) if skill_parts else (level or "武功不详")
    if level and level not in skill_text:
        skill_text = f"{skill_text}（当前境界：{level}）"
    _vit = _vit_text_for_npc(npc, player_name=player_name)
    _vit_part = f" {_vit}" if _vit else ""
    id_part = f"（{identity}）" if identity else ""
    return f"{name}{id_part}：{skill_text} [{status}]{_vit_part}（注:此为完全体档案数据,需结合场景判断当前实际境界）"


# ========== V5 分量制 DC：AI 分项给值，程序加总 ==========
# 境界 → 基础DC 对照表（与提示词中的参考一致，用于交叉校验 AI 是否自洽）
REALM_DC_TABLE = {
    "无武功": 5, "初学入门": 7, "初窥门径": 9, "略有小成": 11, "略有所成": 13,
    "渐入佳境": 15, "融会贯通": 17, "登堂入室": 19, "炉火纯青": 21,
    "出神入化": 23, "登峰造极": 25, "超凡入圣": 27, "返璞归真": 28,
    "天人合一": 29, "破碎虚空": 30,
}

_REALM_ENUM = list(REALM_DC_TABLE.keys())


def realm_idx(realm_name: str) -> int:
    """境界名 → REALM_DC_TABLE 顺序索引（0=无武功 ... 14=破碎虚空），未知返回 None"""
    try:
        return _REALM_ENUM.index(realm_name)
    except (ValueError, TypeError):
        return None

# 分量制 tool schema：AI 只分项填值，最终 DC 由程序 compute_final_dc() 加总
DC_COMPONENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_dc_judgement",
        "description": "分项提交DC判定分量（系统自动加总，禁止自行心算总分），必须如实分项填写",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string", "enum": ["battle", "daily"],
                    "description": "battle=对战行动(与NPC攻防互动) daily=日常行动(无对手)",
                },
                "opponent_realm": {
                    "type": "string", "enum": _REALM_ENUM,
                    "description": "对手当前实际境界（档案是巅峰数据，须按场景上下文修正：受伤/年迈/初学→降档，奇遇/发威→升档）。日常行动填'无武功'",
                },
                "base_dc": {
                    "type": "integer", "minimum": 5, "maximum": 30,
                    "description": "基础难度DC。对战=对手当前实际境界对应值(无武功5/初学入门7/初窥门径9/略有小成11/略有所成13/渐入佳境15/融会贯通17/登堂入室19/炉火纯青21/出神入化23/登峰造极25/超凡入圣27/返璞归真28/天人合一29/破碎虚空30)。日常=行动固有难度(喝水吃饭5/普通施展10/演练熟练12/演练生疏14/突破瓶颈16/疗重伤20)",
                },
                "base_reason": {
                    "type": "string",
                    "description": "30字内说明。对战必须写明对手当前境界名（如'对手登堂入室，独臂带伤'），便于人工校验；日常写明行动难度档（如'演练生疏武功'）",
                },
                "environment_mod": {
                    "type": "integer", "minimum": -8, "maximum": 8,
                    "description": "天时地利修正(对玩家有利为负)：黑暗+2/雨雪湿滑+1~+2/地形险峻+1~+2/天时不利+1~+2/开阔有利-1。无则0",
                },
                "environment_reason": {
                    "type": "string",
                    "description": "15字内环境修正说明，修正为0时填'无碍'或'无'",
                },
                "situation_mod": {
                    "type": "integer", "minimum": -3, "maximum": 3,
                    "description": "人和战况修正(对玩家有利为负)：偷袭得手-1~-3/对手负伤-1~-3/群战围杀-1~-3/以一敌多+1~+3/玩家带伤+1~+3/心神不宁+1~+2。无则0",
                },
                "situation_reason": {
                    "type": "string",
                    "description": "15字内战况修正说明，修正为0时填'势均力敌'或'无'",
                },
                "equipment_mod": {
                    "type": "integer", "minimum": -1, "maximum": 1,
                    "description": "装备利钝修正(对玩家有利为负)，参考玩家装备栏自行判断：神兵利刃且用对应武功/精良防具-1/对手持神兵或徒手对兵刃+1。装备与行动无关填0",
                },
                "equipment_reason": {
                    "type": "string",
                    "description": "15字内装备修正说明，修正为0时填'无装备影响'或'无'",
                },
                "mod_factors": {
                    "type": "array", "items": {"type": "string"},
                    "description": "触发的修正因素名列表，如['偷袭得手','玩家带伤']，无则空列表",
                },
            },
            "required": ["action_type", "base_dc", "base_reason",
                         "environment_mod", "situation_mod", "equipment_mod"],
        },
    },
}


def build_equipment_brief(player_obj=None) -> str:
    """构建玩家装备摘要（供DC判定）。player_obj 缺省时取全局玩家"""
    try:
        if player_obj is None:
            from player_manager import get_player
            player_obj = get_player()
        eq = player_obj.equipped or {}
        parts = []
        weapon = str(eq.get("weapon", "") or "").strip()
        armor = str(eq.get("armor", "") or "").strip()
        items = [str(i).strip() for i in (eq.get("items") or []) if str(i).strip()]
        if weapon:
            parts.append(f"武器：{weapon}")
        if armor:
            parts.append(f"防具：{armor}")
        if items:
            parts.append("随身物品：" + "、".join(items[:8]))
        return "\n".join(parts) if parts else "（无装备）"
    except Exception:
        return "（无装备）"


def build_v4_dc_judge_prompt(scene: str, user_action: str,
                             skill_name: str, skill_level: str, grade: int,
                             skill_list_summary: list,
                             overall_realm: str,
                             active_npcs_text: str = "",
                             battle_mode: bool = True,
                             target_npc_text: str = "") -> tuple:
    """构建AI DC判定的prompt，返回 (sys_prompt, user_prompt)
    AI分项判定DC分量（V5分量制）：AI只填 base_dc/environment_mod/situation_mod/equipment_mod，
    最终DC由程序 compute_final_dc() 加总，AI不心算总分。
    battle_mode=True(默认): battle模式，base_dc直接按对手当前实际境界判定
    battle_mode=False: 日常模式，AI先判行动类型（action_type）再选对应标准
    target_npc_text: 本次对战对手档案行（对战模块传入）。传入后base_dc只认此对手，
                     防止场景残留其他NPC名导致判定对象跑偏
    """
    skills_text = "\n".join(skill_list_summary) if skill_list_summary else "（暂无武功）"
    scene_short = (str(scene or ""))[-300:]
    if not scene_short:
        scene_short = "（场景信息暂无）"

    # 玩家装备摘要（供 equipment_mod 判断）
    equipment_text = build_equipment_brief()

    # 对手锚定块（对战模块专用，最高优先级）
    target_block = ""
    if target_npc_text and target_npc_text.strip():
        target_block = f"""
【★本次对战对手（base_dc 只能以此NPC判定，其余NPC一律不得作为判定对象）】
{target_npc_text}
"""

    # 活跃NPC区块（有则加入，无则省略；对战有锚定时降级为参考信息）
    npcs_block = ""
    if active_npcs_text and active_npcs_text.strip():
        if target_block:
            npcs_label = "【其他在场NPC（仅作战况参考，绝不可作为base_dc判定对象）】"
        else:
            npcs_label = "【活跃NPC（对手或协作者，据其【当前实际境界】判 base_dc）】"
        npcs_block = f"""
{npcs_label}
{active_npcs_text}
"""

    mode_line = ("当前为对战模式，玩家正与对手交手，action_type 填 battle，base_dc 按对手当前实际境界判定。"
                 if battle_mode else
                 "先判断行动类型：与NPC有攻防互动→action_type=battle（按对手当前实际境界判base_dc）；无对手→action_type=daily（按行动固有难度判base_dc）。")

    sys_prompt = f"""你是武侠世界的DC难度裁判。分项判定本次行动的DC分量，系统会自动加总，你只负责如实分项，禁止预想总分。

{mode_line}

【分量标准】
■ base_dc(5~30)基础难度：
  对战=对手【当前实际境界】对应DC。对手档案是完全体数据，须按场景上下文修正（受伤/年迈/初学→降，奇遇/发威→升）：
  无武功5·初学入门7·初窥门径9·略有小成11·略有所成13·渐入佳境15·融会贯通17·登堂入室19·炉火纯青21·出神入化23·登峰造极25·超凡入圣27·返璞归真28·天人合一29·破碎虚空30
  日常=行动固有难度：喝水吃饭5·日常行走8·普通施展10·演练熟练12·演练生疏14·突破瓶颈16·强行运功18·疗重伤20
■ environment_mod(-4~+4)天时地利与战术态势（对玩家有利为负，对玩家不利为正）：天时不利+1·开阔有利-1·偷袭得手-1~-2·玩家群战围杀NPC-1~-3·玩家以一敌多NPC+1~+3
■ situation_mod(-3~+3)人和战况（对玩家有利为负）：对手负伤-1~-3·对手受制-1~-3·玩家受制+1~+3·心神不宁+1~+2。双方当前HP/MP见档案行：对手HP≤70%按负伤降档·对手MP=0（内力枯竭）按受制降档·玩家HP≤70%或MP=0按带伤加档
■ equipment_mod(-1~+1)装备利钝（对玩家有利为负，参考【玩家装备】自行判断利钝）：神兵利刃且用对应武功或精良防具-1·对手持神兵或徒手对兵刃+1·装备与行动无关填0
■ 各reason字段：说明数值来历（面向玩家展示，句式自由）。base_reason 必须写明对手当前境界名，如"对手登堂入室，独臂带伤"；日常行动写明难度档，如"演练生疏武功"；其余reason说明来源即可，如"他中我一掌正在踉跄，所以-2"。修正为0时如实填"无碍/无"之类

【铁律】
1. DC各分量与玩家自身实力完全无关（实力已在修正值中），绝不因玩家境界高而降DC
2. 分量各自独立判断；同类因素取最高档，异类可叠加（叠加后不超过各分量上限：环境±4·战况±3·装备±1）
3. opponent_realm 必须如实填报（系统用于校验 base_dc 是否自洽）
4. 若给了【★本次对战对手】，base_dc 与 opponent_realm 只能针对该对手

只返回严格JSON，不要任何解释文字：
{{"action_type":"battle","opponent_realm":"登堂入室","base_dc":19,"base_reason":"对手武功境界登堂入室，所以是19","environment_mod":0,"environment_reason":"月色清朗，无碍","situation_mod":-2,"situation_reason":"他中我一掌正在踉跄，所以-2","equipment_mod":-1,"equipment_reason":"我持韩王青刀削铁如泥，所以-1","mod_factors":["对手负伤"]}}"""

    # 玩家当前HP/MP（带伤/内力枯竭可见，供situation_mod判断）
    player_vit_text = ""
    try:
        import vitality_system as _vs
        _pv = _vs.get_player_vitality()
        if _pv["hp"] == -1:
            player_vit_text = "已故"
        else:
            player_vit_text = f"HP {_pv['hp']}%/MP {_pv['mp']}%"
            if _pv["mp"] == 0:
                player_vit_text += "（⚠内力枯竭：无法催动武功，行动大打折扣）"
            elif _pv["hp"] == 0:
                player_vit_text += "（濒死锁血）"
    except Exception:
        player_vit_text = ""

    user_prompt = f"""【玩家整体境界】{overall_realm}

【玩家当前状态】{player_vit_text or "（未知，视为满状态）"}

【玩家装备】
{equipment_text}

【玩家武功清单】
{skills_text}

【本次使用武功】{skill_name}（{skill_level}·品阶{grade}级）
{target_block}{npcs_block}
【场景上下文】
{scene_short}

【玩家行动】
{user_action}

请分项判定DC分量。"""

    return sys_prompt, user_prompt


def _extract_components_from_tool_calls(tool_calls) -> dict | None:
    """从 tool_calls 中提取 DC 分量（层1）。兼容 OpenAI 对象和 dict 两种形态"""
    if not tool_calls:
        return None
    for tc in tool_calls:
        try:
            fn = getattr(tc, "function", None)
            if fn is None and isinstance(tc, dict):
                fn = tc.get("function", {})
            if fn is None:
                continue
            name = getattr(fn, "name", None)
            if name is None and isinstance(fn, dict):
                name = fn.get("name", "")
            if name and name != "submit_dc_judgement":
                continue
            args_raw = getattr(fn, "arguments", None)
            if args_raw is None and isinstance(fn, dict):
                args_raw = fn.get("arguments", "")
            if not args_raw:
                continue
            data = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            if isinstance(data, dict) and "base_dc" in data:
                return data
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            continue
    return None


def _parse_dc_components(raw) -> dict | None:
    """解析 AI 返回的 DC 分量（三级解析链）
    层1: tool_calls arguments（真 tool call 模式）
    层2: content 完整JSON / ```json围栏 / 首个含base_dc的{}块
    层3: 正则逐字段提取（部分损坏也能用）
    返回分量 dict 或 None
    """
    tool_calls = None
    content = ""
    if isinstance(raw, dict):
        tool_calls = raw.get("tool_calls")
        content = str(raw.get("content", "") or "")
    elif raw is not None:
        content = str(raw)

    # 层1：tool_calls
    comp = _extract_components_from_tool_calls(tool_calls)
    if comp:
        return comp

    # 层2：content JSON
    text = content.strip()
    candidates = [text]
    fence = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1))
    brace = re.search(r'\{[^{}]*"base_dc"[^{}]*\}', text, re.DOTALL)
    if brace:
        candidates.append(brace.group())
    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict) and "base_dc" in data:
                return data
        except (json.JSONDecodeError, ValueError):
            continue

    # 层3：正则逐字段提取
    m = re.search(r'"base_dc"\s*:\s*(\d+)', text)
    if m:
        fields = {"base_dc": int(m.group(1))}
        for key, pat in (
            ("environment_mod", r'"environment_mod"\s*:\s*(-?\d+)'),
            ("situation_mod", r'"situation_mod"\s*:\s*(-?\d+)'),
            ("equipment_mod", r'"equipment_mod"\s*:\s*(-?\d+)'),
            ("action_type", r'"action_type"\s*:\s*"(battle|daily)"'),
            ("base_reason", r'"base_reason"\s*:\s*"([^"]{1,30})"'),
            ("environment_reason", r'"environment_reason"\s*:\s*"([^"]{1,24})"'),
            ("situation_reason", r'"situation_reason"\s*:\s*"([^"]{1,24})"'),
            ("equipment_reason", r'"equipment_reason"\s*:\s*"([^"]{1,24})"'),
            ("flavor_text", r'"flavor_text"\s*:\s*"([^"]{1,80})"'),
        ):
            mm = re.search(pat, text)
            if mm:
                val = mm.group(1)
                fields[key] = int(val) if key.endswith("_mod") else val
        return fields
    return None


def _sanitize_components(comp: dict, user_action: str = "") -> dict:
    """分量清洗：类型转换+范围夹紧+缺省补全。部分字段损坏不影响其余字段"""
    def _int(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(v)))
        except (TypeError, ValueError):
            return default

    action_type = "battle" if str(comp.get("action_type", "battle")) == "battle" else "daily"
    realm = str(comp.get("opponent_realm", "") or "")[:10]
    if realm not in REALM_DC_TABLE:
        realm = ""
    def _reason(key, limit=36):
        return str(comp.get(key, "") or "").strip()[:limit]
    return {
        "action_type": action_type,
        "opponent_realm": realm,
        "base_dc": _int(comp.get("base_dc"), 5, 30, _fallback_dc(user_action)),
        "base_reason": _reason("base_reason"),
        "environment_mod": _int(comp.get("environment_mod"), -8, 8, 0),
        "environment_reason": _reason("environment_reason", 24),
        "situation_mod": _int(comp.get("situation_mod"), -3, 3, 0),
        "situation_reason": _reason("situation_reason", 24),
        "equipment_mod": _int(comp.get("equipment_mod"), -1, 1, 0),
        "equipment_reason": _reason("equipment_reason", 24),
        "mod_factors": [str(x)[:12] for x in (comp.get("mod_factors") or [])][:6],
        "flavor_text": _reason("flavor_text", 80),
    }


def compute_final_dc(comp: dict, user_action: str = "") -> dict:
    """分量加总（唯一公式入口）。
    扩展点：以后非AI分量（NPC伤势数据/地形/时辰等）在此追加，
    AI 分量只负责定性判断，数据权威分量由程序注入。
    """
    c = _sanitize_components(comp, user_action)
    # ★ 公式：总DC = 基础 + 环境 + 战况 + 装备（各分量已独立夹紧，总分再夹紧）
    total = max(5, min(30, c["base_dc"] + c["environment_mod"] + c["situation_mod"] + c["equipment_mod"]))
    # realm 交叉校验：报"初学入门"却给 base=25 之类的分项不自洽预警
    if c["opponent_realm"] and c["action_type"] == "battle":
        expect = REALM_DC_TABLE[c["opponent_realm"]]
        if abs(c["base_dc"] - expect) > 3:
            logger.warning("[DC校验] realm=%s 期望base≈%d 实际=%d（AI分项不自洽）",
                           c["opponent_realm"], expect, c["base_dc"])
    # 分项明细：每个分量自带文字解释（数值(标签：解释)），修正值自带正负号
    # base_reason 程序侧保底补境界名（AI漏写时），确保玩家在骰子面板可见对手境界便于人工校验
    base_txt = c["base_reason"]
    if c["action_type"] == "battle" and c["opponent_realm"] and c["opponent_realm"] not in base_txt:
        base_txt = f"{base_txt}，对手境界{c['opponent_realm']}" if base_txt else f"对手境界{c['opponent_realm']}"
    def _part(val, label, reason):
        return f"{val}({label}：{reason})" if reason else f"{val}({label})"
    parts = [_part(c["base_dc"], "基础", base_txt)]
    for val, label, reason in (
        (c["environment_mod"], "环境", c["environment_reason"]),
        (c["situation_mod"], "战况", c["situation_reason"]),
        (c["equipment_mod"], "装备", c["equipment_reason"]),
    ):
        parts.append(_part(f"{val:+d}", label, reason))
    bd = "".join(parts) + f"→DC{total}"
    return {"dc": total, "breakdown": bd, "reason": c["flavor_text"], "components": c}


def ai_judge_dc_only(llm_func, scene: str, user_action: str,
                     skill_name: str, skill_level: str, grade: int,
                     skill_list_summary: list, overall_realm: str,
                     active_npcs_text: str = "",
                     battle_mode: bool = True,
                     target_npc_text: str = "") -> tuple:
    """AI分项判定DC分量，程序加总（V5分量制）

    Args:
        llm_func: AI调用函数（llm_call_common 或支持 tools 透传的封装）
        active_npcs_text: 活跃NPC精简摘要（可选，增强DC判定）
        battle_mode: True=battle模式; False=日常模式（AI自判行动类型）
        target_npc_text: 本次对战对手档案行（对战模块传入，防止判定对象跑偏）
        其余: 场景、行动、武功信息

    Returns:
        (dc: int, reason: str) reason=分项解释明细（每个分量自带文字说明）
        四级兜底：①tool call分量 ②文本JSON分量 ③正则提取 ④兜底分量
        副作用：把本次判定的 action_type 存入 _LAST_DC_ACTION_TYPE（供回气等逻辑读取），
        对手境界存入 _LAST_DC_OPPONENT_REALM（供 judge_grade_v4 境界差直通读取）
    """
    global _LAST_DC_ACTION_TYPE, _LAST_DC_OPPONENT_REALM
    _LAST_DC_ACTION_TYPE = "daily"
    _LAST_DC_OPPONENT_REALM = None
    if not llm_func:
        return _fallback_dc(user_action), ""

    try:
        sys_prompt, user_prompt = build_v4_dc_judge_prompt(
            scene, user_action, skill_name, skill_level, grade,
            skill_list_summary, overall_realm, active_npcs_text,
            battle_mode, target_npc_text
        )
        # 适配签名：优先尝试 tool call（llm_call_common 及其封装支持 tools 透传）
        import inspect as _inspect
        try:
            _sig = _inspect.signature(llm_func)
            _params = list(_sig.parameters.keys())
            _nparams = len(_params)
        except (ValueError, TypeError):
            _params, _nparams = [], 1
        raw = None
        try:
            if _nparams >= 2 and ("tools" in _params or "**kwargs" in str(_sig)):
                raw = llm_func(sys_prompt, user_prompt,
                               tools=[DC_COMPONENT_TOOL], tool_choice="auto")
            elif _nparams >= 2:
                raw = llm_func(sys_prompt, user_prompt)
            else:
                raw = llm_func(sys_prompt + "\n\n" + user_prompt)
        except TypeError:
            # llm_func 不接受 tools 参数（未知封装），降级为纯文本模式
            try:
                raw = llm_func(sys_prompt, user_prompt)
            except TypeError:
                raw = llm_func(sys_prompt + "\n\n" + user_prompt)

        # 分量解析（四级兜底链）
        comp = _parse_dc_components(raw)
        if comp is None:
            _fb = _fallback_dc(user_action)
            logger.warning("V5 DC分量解析全部失败，使用兜底DC=%d", _fb)
            return _fb, ""
        result = compute_final_dc(comp, user_action)
        _comp = result.get("components") or {}
        _LAST_DC_ACTION_TYPE = _comp.get("action_type", "daily")
        _LAST_DC_OPPONENT_REALM = _comp.get("opponent_realm") or None
        print(f"[DC分量] {result['breakdown']}")
        return result["dc"], result["breakdown"]
    except Exception as e:
        _fb = _fallback_dc(user_action)
        logger.warning("V5 DC分量判定异常: %s", e)
        return _fb, ""


def build_v4_judge_prompt(scene: str, user_action: str,
                          skill_list_summary: list,
                          overall_realm: str) -> tuple:
    """构建V4 AI判定的 prompt，返回 (sys_prompt, user_prompt)
    拆分为系统提示和用户输入两部分，适配 llm_call_common(sys_prompt, user_prompt) 签名
    """
    skills_text = "\n".join(skill_list_summary) if skill_list_summary else "（暂无武功）"
    scene_short = (str(scene or ""))[-300:]
    if not scene_short:
        scene_short = "（场景信息暂无）"

    sys_prompt = """你是武侠世界的武功检定裁判。根据场景和玩家行动,判断是否需要武功检定。

⚠️【DC核心原则】DC值只取决于【对手强度】和【环境因素】,与玩家自身实力【完全无关】。
玩家的实力已经体现在修正值中,绝对不要因为玩家境界高或武功强就降低DC。
⚠️【场景判定优先】判定DC前,必须先识别行动类型:
  ■ 日常行动(无对手):演练武功、施展轻功、运功疗伤、破解机关等。查【日常行动DC参考】,不得参考身边NPC境界。
  ■ 对战行动(有对手):与NPC交手、比武、暗杀、围攻等。查【对战DC参考】,从场景或活跃NPC中识别对手境界。
  ■ 判定标准:玩家行动是否针对某NPC产生攻防互动?是→对战;否→日常。
⚠️【NPC档案修正】活跃NPC摘要是【完全体档案数据】,表示该NPC巅峰状态。当前剧情中NPC可能处于不同阶段(幼年/初学/受伤/老年等),你必须根据【场景上下文】判断NPC的【当前实际境界】而非直接使用档案数据。场景上下文优先级 > 档案数据。

请判断:
1. 此行动是否涉及武功运用?
   涉及(运功/出招/对敌/逼毒/护体/轻功/内力/剑法/掌法等)→need_check=true
   纯对话/走路/看东西/休息→need_check=false
2. 玩家会用哪门武功?
   从清单中选最相关的;通用行动(运功/护体)选内功类武功;
   无特定武功可用时填"overall"
3. 合理的DC是多少?(减值因素如受伤/中毒/天气请直接算进DC)

【日常行动DC参考】(无对手时使用,不得参考身边NPC境界)
5=极简单(喝水吃饭) 8=很简单(日常行走) 10=简单(普通施展武功)
12=中等(演练熟练武功) 14=较难(演练生疏武功) 16=困难(尝试突破瓶颈)
18=很困难(强行运功) 20=极难(运功疗重伤) 25+=近乎不可能(逆天改命)

【对战DC参考】(有对手时使用,基础DC+环境修正。按金庸十四部小说整体标准,"掌门"是门内地位非江湖地位)
对手无武功→DC5(普通百姓、不会武功的NPC)
对手初学入门→DC7(刚入门弟子、江湖新丁,修炼0-1年)
对手初窥门径→DC9(外门弟子、庄客,修炼1-3年)
对手略有小成→DC11(内门弟子、杂役,修炼3-5年)
对手略有所成→DC13(镖师、小头目、权臣非武人,修炼5-8年)
对手渐入佳境→DC15(地方小派掌门/镖局香主/精英弟子/一方好手,修炼8-15年)
对手融会贯通→DC17(中等门派掌门/总镖头/帮派香主/一方之雄,修炼15-20年)
对手登堂入室→DC19(名门长老/邪派堂主/小派宗师,修炼20-30年)
对手炉火纯青→DC21(名门掌门/武林宿望/一方霸主,修炼30-40年,中低武世界天花板)
对手出神入化→DC23(神功大成/天赋异禀,修炼40-50年或得奇遇)
对手登峰造极→DC25(邪教教主/大内供奉/绝顶高手,修炼50-70年或天赋+奇遇)
对手超凡入圣→DC27(武林绝顶/隐世高人,百年难遇,需天赋+奇遇+机缘)
对手返璞归真→DC28(隐世宗师/武林神话,超凡脱俗)
对手天人合一→DC29(传说级,与天地共鸣,非凡人可敌)
对手破碎虚空→DC30(神话级,千古难遇)
※ 中低武世界天花板为8档(DC21),神功大成者可破例达9档。高武世界(射雕/神雕/倚天/笑傲)天花板为10-11档。超高武世界(天龙/侠客行)天花板为12-13档。

【DC判定的环境因素·江湖险象】
判定DC时,需在对手境界对应基础DC之上,叠加以下环境修正,贴合江湖实战变数。
【减值因素·玩家有利】(降低DC,可放手一搏)
■ 偷袭得手(-1~-3):趁敌不备,出其不意。夜半突袭、暗中出手,对手仓促应战。
■ 对手负伤(-1~-4):敌亦带伤,出招迟滞,破绽处处,正是进攻良机。
■ 群战围杀(-1~-4):玩家一方多人围杀单一对手。2人围杀-1,3人-2,4人及以上-4。人多势众,轮番抢攻,对手首尾难顾。
■ 玩家持神兵(-1~-3):玩家持名剑宝刀,削铁如泥,对手兵刃触之即断。
■ 对手受制(-1~-3):对手中毒、被封穴、内息紊乱,出手大打折扣。
【加值因素·玩家不利】(抬高DC,须谨慎出招)
■ 玩家带伤(+1~+4):旧创未愈,气血不畅,对战受伤,招式运转大打折扣。
■ 以一敌多(+2~+6):群敌环伺,腹背受敌。围攻人数愈多,DC攀升愈高。
■ 黑暗环境(+1~+2):月黑风高,密林昏暗,全凭听声辨位。
■ 对手持神兵(+1~+3):对手持名剑宝刀,锋芒凌厉,只能避其锋、寻其隙。
■ 玩家受制(+1~+3):玩家中毒、被封穴、内息走岔,运劲滞涩。
■ 心神不宁(+1~+2):暴怒失智、惊惧分心、牵挂生乱,招式破绽百出。
■ 天时不利(+1~+2):雨雪湿滑影响轻功,大风影响暗器,酷暑严寒消耗体力。
【判定要点】异类修正可叠加(如"玩家带伤+以一敌多"),同类只取最高档(如"对手负伤"与"对手受制"取其一)。双方持神兵相互抵消,不叠加。总修正封顶±8,防止极端DC。

只返回严格JSON,不要任何解释文字:
{"need_check": true, "skill_name": "紫霞神功", "dc": 16, "reason": "对手登堂入室级"}
或
{"need_check": false}"""

    user_prompt = f"""【玩家整体境界】{overall_realm}

【玩家武功清单】
{skills_text}

【场景上下文】
{scene_short}

【玩家行动】
{user_action}"""

    return sys_prompt, user_prompt


def parse_v4_judge_json(text: str) -> dict:
    """解析V4 AI判定的JSON返回"""
    if not text:
        return {"need_check": False}

    text = text.strip()
    # 尝试直接解析
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    # 尝试从文本中提取JSON块
    json_match = re.search(r'\{[^{}]*"need_check"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    return {"need_check": False}


def ai_judge_check_v4(llm_func, scene: str, user_action: str,
                      skill_list_summary: list, overall_realm: str) -> dict:
    """V4 AI判定主入口

    Args:
        llm_func: AI调用函数。支持两种签名:
                  (sys_prompt, user_prompt) -> str  (如 llm_call_common)
                  (prompt) -> str                   (其他单参数函数)
        scene: 场景上下文
        user_action: 玩家行动
        skill_list_summary: 玩家武功清单摘要
        overall_realm: 玩家整体境界

    Returns:
        {"need_check": bool, "skill_name": str, "dc": int, "reason": str}
        失败时返回 {"need_check": False}
    """
    if not llm_func:
        # 无AI可用,无法判定检定
        return {"need_check": False}

    try:
        sys_prompt, user_prompt = build_v4_judge_prompt(scene, user_action, skill_list_summary, overall_realm)
        # 适配双参数签名 (llm_call_common) 和单参数签名
        import inspect as _inspect
        try:
            _sig = _inspect.signature(llm_func)
            _nparams = len(_sig.parameters)
        except (ValueError, TypeError):
            _nparams = 1
        if _nparams >= 2:
            raw = llm_func(sys_prompt, user_prompt)
        else:
            raw = llm_func(sys_prompt + "\n\n" + user_prompt)
        # llm_call_common 返回 {"content": str, ...}，需提取 content
        if isinstance(raw, dict):
            raw = raw.get("content", "") or ""
        raw = str(raw or "").strip()
        result = parse_v4_judge_json(raw)
        # 规范化
        if result.get("need_check"):
            result["need_check"] = True
            result.setdefault("skill_name", "overall")
            result.setdefault("dc", 12)
            try:
                result["dc"] = int(result["dc"])
            except (ValueError, TypeError):
                result["dc"] = 12
            result.setdefault("reason", "")
        else:
            result = {"need_check": False}
        return result
    except Exception as e:
        logger.warning("V4 AI判定异常: %s", e)
        return {"need_check": False}


# ---- V4 约束文本生成 ----

def build_constraint_text_v4(skill_name: str, skill_level: str, grade: int,
                             base_bonus: int, skill_bonus: int, realm_bonus: int,
                             total_modifier: int, dc: int, dc_reason: str,
                             dice_result: dict, delta: int,
                             verdict_grade: int, verdict_name: str,
                             verdict_narr: str, overall_realm: str,
                             amplify_detail: dict = None) -> str:
    """生成V4约束文本

    Args:
        amplify_detail: 增幅详情（None表示无增幅）
            {
                "inner_name": str, "inner_rate": float, "inner_amplify": int,
                "light_name": str, "light_rate": float, "light_amplify": int,
                "total_amplify": int,
            }
    """
    natural = dice_result["natural"]
    total = dice_result["total"]

    # natural 特判说明
    natural_note = ""
    if natural == 20:
        natural_note = "（天助:自然20,档位提升2级）"
    elif natural == 1:
        natural_note = "（背运:自然1,档位降低2级）"

    # 增幅检定文本（明确标注为玩家主角的增幅）
    amplify_block = ""
    if amplify_detail and (amplify_detail.get("inner_name") or amplify_detail.get("light_name")):
        amp_lines = ["【玩家·内功轻功增幅检定】"]
        if amplify_detail.get("inner_name"):
            amp_lines.append(f"玩家内功催动: {amplify_detail['inner_name']}（增幅率{amplify_detail['inner_rate']*100:.0f}% → +{amplify_detail['inner_amplify']}）")
        if amplify_detail.get("light_name"):
            amp_lines.append(f"玩家轻功辅助: {amplify_detail['light_name']}（增幅率{amplify_detail['light_rate']*100:.0f}% → +{amplify_detail['light_amplify']}）")
        amp_lines.append(f"玩家增幅总值: +{amplify_detail.get('total_amplify', 0)}")
        amplify_block = "\n".join(amp_lines) + "\n"

    text = f"""【!系统检定·必须遵循!】
检定类型: 玩家武功运用{('（玩家内功催动攻击·增幅检定）') if amplify_block else ''}
使用武功: 玩家·{skill_name}（{skill_level}·品阶{grade}级）
基础修正: +{base_bonus}（玩家整体境界：{overall_realm}）
武功加成: +{skill_bonus}（玩家武功品阶）+ {realm_bonus}（玩家武功境界）= +{skill_bonus + realm_bonus}
{amplify_block}玩家总修正: +{total_modifier}
DC难度: {dc}（{dc_reason}）
掷骰过程: d20自然值={natural} → {natural}{total_modifier:+d} = {total}
判定差值: {total} - {dc} = {delta:+d}
最终档位: 第{verdict_grade}档·{verdict_name}{natural_note}

【叙事要求】
{verdict_name}: {verdict_narr}
请结合当前场景和玩家行动,生成符合此检定程度的剧情。

【关键规则】
1. 掷骰结果为程序生成,不得改判
2. 绝对禁止出现"骰子""DC""检定""档位""差值""d20"等游戏术语
3. 叙事必须自然融入场景,用动作/环境/人物反应体现检定程度
4. 差值越大,玩家武功运用过程越要描写得挥洒自如或狼狈不堪{('' if not amplify_block else '5. 上述内功/轻功增幅均为玩家主角所有,叙事中应体现玩家"内力催动""身法配合"等增幅效果,不可挪作NPC能力')}"""

    return text


# ---- V4 对外主接口 ----

def resolve_check_v4(player_obj, user_action: str, l1_scene: str = "",
                     llm_func=None, preset_skill_name: str = None,
                     preset_dc: int = None, preset_dc_reason: str = None,
                     active_npcs_text: str = "",
                     classified_skills: dict = None,
                     effect_opponent_name: str = None,
                     effect_opponent_data: dict = None) -> dict | None:
    """V4 完整检定流程 - 对外主入口

    流程:
    1. need_check判定: 预设武功名→直接检定；否则AI判定
    2. DC判定: 预设DC→直接用；否则AI判定
    3. 程序查表: 基础修正(整体境界) + 武功加成(品阶+境界)
    4. 增幅检定(可选): 内功轻功催动攻击，基于攻击总修正×增幅率
    5. check_d20() → 掷骰
    6. judge_grade_v4() → 8档分级判定
    7. build_constraint_text_v4() → 生成约束文本

    Args:
        player_obj: Player对象 (player_manager.Player 实例)
        user_action: 玩家输入文本
        l1_scene: L1即时场景锚点
        llm_func: AI调用函数
        preset_skill_name: 预设武功名（Web端正则已命中时传入，跳过AI判定）
        preset_dc: 预设DC值（Web端AI已判定时传入，跳过AI DC判定）
        preset_dc_reason: 预设DC理由
        classified_skills: 分类检测结果（detect_martial_skill_classified 返回）
            None表示不做增幅检定（走原逻辑）
            有值时，若包含辅助类武功，触发增幅检定

    Returns:
        None 或 {完整检定结果dict}
    """
    if not player_obj:
        return None

    overall_realm = player_obj.overall_realm
    skill_list_summary = player_obj.get_skill_list_summary()

    # Step 1: need_check + skill_name 判定
    if preset_skill_name:
        # Web端正则已命中武功名，直接检定
        skill_name = preset_skill_name
    else:
        # CLI模式或未预设，用AI判定
        judge = ai_judge_check_v4(llm_func, l1_scene, user_action,
                                  skill_list_summary, overall_realm)
        if not judge.get("need_check"):
            return None
        skill_name = judge.get("skill_name", "overall")

    # Step 2: DC判定
    if preset_dc is not None:
        dc = int(preset_dc)
        dc_reason = preset_dc_reason or ""
    else:
        # AI判定DC
        skill_info_tmp = player_obj.get_skill_info(skill_name) if skill_name != "overall" else None
        _slevel = skill_info_tmp["skill_level"] if skill_info_tmp else overall_realm
        _sgrade = skill_info_tmp["grade"] if skill_info_tmp else 0
        dc, dc_reason = ai_judge_dc_only(
            llm_func, l1_scene, user_action, skill_name, _slevel, _sgrade,
            skill_list_summary, overall_realm, active_npcs_text
        )

    # Step 3: 程序查表计算总修正
    base_bonus = player_obj.base_bonus  # 基础修正(整体境界)

    if skill_name == "overall":
        # 通用行动:仅用基础修正
        skill_info = None
        skill_level = overall_realm
        grade = 0
        skill_bonus = 0
        realm_bonus = 0
    else:
        skill_info = player_obj.get_skill_info(skill_name)
        if skill_info:
            skill_level = skill_info["skill_level"]
            grade = skill_info["grade"]
            skill_bonus = skill_info["bonus"]
            realm_bonus = skill_info["realm_bonus"]
        else:
            # 玩家未学此武功,用基础修正兜底
            skill_level = "未修炼"
            grade = 0
            skill_bonus = 0
            realm_bonus = 0

    # 攻击总修正（基础+武功品阶+武功境界）
    attack_total = base_bonus + skill_bonus + realm_bonus

    # ===== Step 3.5: 增幅检定（新增分支，最小侵入）=====
    amplify_detail = None
    total_amplify = 0
    if (classified_skills and
        classified_skills.get("primary_attack") and
        (classified_skills.get("primary_inner") or classified_skills.get("primary_light"))):

        # 只有当主攻击武功确实存在时才做增幅
        inner_name = classified_skills.get("primary_inner", "")
        light_name = classified_skills.get("primary_light", "")

        inner_info = player_obj.get_skill_info(inner_name) if inner_name else None
        light_info = player_obj.get_skill_info(light_name) if light_name else None

        if inner_info or light_info:
            total_amplify, amp_detail = compute_amplify_bonus(
                attack_total=attack_total,
                inner_info=inner_info,
                light_info=light_info,
            )
            amp_detail["total_amplify"] = total_amplify
            amplify_detail = amp_detail

            # ===== DEBUG 输出 =====
            print(f"\n{'='*60}")
            print(f"[增幅检定DEBUG] 内功轻功催动攻击")
            print(f"{'='*60}")
            print(f"  玩家输入: {user_action[:80]}")
            print(f"  匹配类型: {classified_skills.get('match_type', '?')}")
            print(f"  主攻击武功: {skill_name}（{skill_level}·品阶{grade}级）")
            print(f"  攻击总修正: {base_bonus}(基础) + {skill_bonus}(品阶) + {realm_bonus}(境界) = {attack_total}")
            if inner_info:
                inner_b = inner_info.get("bonus", 0)
                inner_rb = inner_info.get("realm_bonus", 0)
                inner_rate = _compute_amplify_rate(inner_info)
                print(f"  内功: {inner_name}（品阶{inner_info.get('grade',0)}级, bonus={inner_b}, realm_bonus={inner_rb}）")
                print(f"       增幅率 = ({inner_b}+{inner_rb})/20 = {inner_rate*100:.1f}%")
                print(f"       增幅值 = fair_round({attack_total} × {inner_rate:.3f}) = {amp_detail['inner_amplify']}")
            if light_info:
                light_b = light_info.get("bonus", 0)
                light_rb = light_info.get("realm_bonus", 0)
                light_rate = _compute_amplify_rate(light_info)
                print(f"  轻功: {light_name}（品阶{light_info.get('grade',0)}级, bonus={light_b}, realm_bonus={light_rb}）")
                print(f"       增幅率 = ({light_b}+{light_rb})/20 = {light_rate*100:.1f}%")
                print(f"       增幅值 = fair_round({attack_total} × {light_rate:.3f}) = {amp_detail['light_amplify']}")
            print(f"  增幅总值: +{total_amplify}")
            print(f"  最终修正: {attack_total} + {total_amplify} = {attack_total + total_amplify}")
            print(f"{'='*60}\n")

    # 最终总修正 = 攻击总修正 + 增幅值（无增幅时增幅为0，等价原逻辑）
    total_modifier = attack_total + total_amplify

    # Step 4: 掷骰
    dice_result, _ = check_d20(modifier=total_modifier, dc=dc)

    # Step 5: 8档分级判定（含境界差直通：±6档境界差可突破nat限制）
    delta = dice_result["total"] - dc
    _p_idx = realm_idx(overall_realm)
    _o_idx = realm_idx(_LAST_DC_OPPONENT_REALM) if _LAST_DC_OPPONENT_REALM else None
    verdict_grade, verdict_name, verdict_narr = judge_grade_v4(
        delta, dice_result["natural"],
        player_realm_idx=_p_idx, opponent_realm_idx=_o_idx
    )

    # Step 6: 生成约束文本
    constraint_text = build_constraint_text_v4(
        skill_name=skill_name,
        skill_level=skill_level,
        grade=grade,
        base_bonus=base_bonus,
        skill_bonus=skill_bonus,
        realm_bonus=realm_bonus,
        total_modifier=total_modifier,
        dc=dc,
        dc_reason=dc_reason,
        dice_result=dice_result,
        delta=delta,
        verdict_grade=verdict_grade,
        verdict_name=verdict_name,
        verdict_narr=verdict_narr,
        overall_realm=overall_realm,
        amplify_detail=amplify_detail,
    )

    # ===== Step 6.5: 武功特效触发（最小侵入,完全离线计算）=====
    # 主武功(攻击类) + 增幅源(内功/轻功) 自身的特效均同步计算
    # 设计: 增幅源特效的增幅系数=1.0(避免自我增幅),DC档位与主检定一致
    effect_result = None
    effect_results = []  # 所有特效结果列表(主武功+内功+轻功,含未触发)
    try:
        if skill_name and skill_name != "overall":
            _inner_name = ""
            _light_name = ""
            _inner_for_effect = None
            _light_for_effect = None
            if amplify_detail:
                _inner_name = amplify_detail.get("inner_name", "")
                _light_name = amplify_detail.get("light_name", "")
                if _inner_name:
                    _inner_for_effect = player_obj.get_skill_info(_inner_name)
                if _light_name:
                    _light_for_effect = player_obj.get_skill_info(_light_name)

            # 1) 主武功特效（用内功+轻功计算增幅系数）
            effect_result = compute_effect_trigger(
                skill_name=skill_name,
                player_obj=player_obj,
                classified_skills=classified_skills,
                grade_result=verdict_grade,
                inner_info=_inner_for_effect,
                light_info=_light_for_effect,
            )
            if effect_result:
                effect_results.append(effect_result)

            # 2) 增幅源·内功特效
            if _inner_name and _inner_name != skill_name:
                _inner_effect = compute_effect_trigger(
                    skill_name=_inner_name,
                    player_obj=player_obj,
                    classified_skills=None,
                    grade_result=verdict_grade,
                    inner_info=None,   # 内功不自我增幅
                    light_info=None,
                )
                if _inner_effect:
                    effect_results.append(_inner_effect)

            # 3) 增幅源·轻功特效
            if _light_name and _light_name != skill_name:
                _light_effect = compute_effect_trigger(
                    skill_name=_light_name,
                    player_obj=player_obj,
                    classified_skills=None,
                    grade_result=verdict_grade,
                    inner_info=None,
                    light_info=None,
                )
                if _light_effect:
                    effect_results.append(_light_effect)

            # 4) 锚点分流：1/2档随机直挂1条 / 3-7档提示注入
            if effect_results and verdict_grade in (1, 2, 3, 4, 5, 6, 7):
                if verdict_grade in (1, 2):
                    _picked = random.choice(effect_results)
                    for _r in effect_results:
                        _r["triggered"] = (_r is _picked)
                    if _picked.get("narrative_hint"):
                        constraint_text = constraint_text + "\n" + _picked["narrative_hint"]
                else:
                    _ref_lines = "\n".join(
                        _r["ref_hint"] for _r in effect_results if _r.get("ref_hint"))
                    if _ref_lines:
                        constraint_text = constraint_text + "\n" + _ref_lines + \
                            "\n（以上仅为优先参考，是否挂载由你按剧情合理性决定，通过effect_update上报）"

            # ===== Step 6.6: 1/2档特效直挂→挂状态词条 =====
            # 仅triggered=True（1/2档选中那条）的条目挂载；挂载日志注入constraint_text
            effect_mount_log = None
            try:
                import vitality_system as _vs_eff
                _mount_log = _vs_eff.mount_martial_effect_triggers(
                    effect_results,
                    player_name=getattr(player_obj, "name", None),
                    opponent_name=effect_opponent_name,
                )
                if _mount_log:
                    effect_mount_log = _mount_log
                    constraint_text = constraint_text + "\n" + _mount_log + \
                        "（系统已挂载状态词条，本回合剧情必须体现该状态的效果）"
            except Exception as _me:
                logger.debug("特效挂状态异常(已忽略): %s", _me)
    except Exception as _e:
        logger.warning("特效触发计算异常(已忽略): %s", _e)
        effect_result = None
        effect_results = []

    # ===== Step 6.7: NPC反手招锚点（7档力屈受挫/8档惨败时生效） =====
    # NPC配了effect_triggers → 随机选1条硬挂（target=self给NPC上buff /
    #   target=opponent给玩家上debuff）；未配置 → 指令兜底约束AI必报一条不利状态
    # 2-6档：仅注入招牌特效优先提示（AI按剧情裁量），7/8档硬挂逻辑不变
    # 失效保障：没传/异常 → 静默跳过，零影响
    npc_effect_results = []
    try:
        if effect_opponent_data and verdict_grade:
            if verdict_grade not in (7, 8):
                _npc_hint = compute_npc_effect_hint(effect_opponent_data)
                if _npc_hint:
                    constraint_text = constraint_text + "\n" + _npc_hint
            else:
                npc_effect_results = compute_npc_effect_trigger(
                    effect_opponent_data, verdict_grade)
                if npc_effect_results:
                    _npc_pick = npc_effect_results[0]
                    if _npc_pick.get("anchor") == "grade78":
                        import vitality_system as _vs_npc
                        _npc_mount_log = _vs_npc.mount_npc_effect_triggers(
                            npc_effect_results,
                            player_name=getattr(player_obj, "name", None),
                            npc_name=effect_opponent_data.get("name"),
                        )
                        if _npc_mount_log:
                            effect_mount_log = (effect_mount_log + "\n" + _npc_mount_log
                                                if effect_mount_log else _npc_mount_log)
                            constraint_text = constraint_text + "\n" + _npc_mount_log + \
                                "（系统已挂载状态词条，本回合剧情必须体现该状态的效果）"
                    elif _npc_pick.get("anchor") == "directive":
                        _npc_name = _npc_pick.get("npc_name") or "对手"
                        _grade_label = "惨败而归（第8档）" if verdict_grade == 8 \
                            else "力屈受挫（第7档）"
                        constraint_text = constraint_text + (
                            f"\n指令：本轮玩家{_grade_label}，{_npc_name}的反击必须给玩家"
                            "造成一条不利状态（如【受伤】【中毒】【震慑】等，从状态库选），"
                            "必须通过effect_update上报；若对手明显弱于玩家，可酌情豁免。")
    except Exception as _ne:
        logger.debug("NPC反手招挂状态异常(已忽略): %s", _ne)

    return {
        "required": True,
        "action_type": _LAST_DC_ACTION_TYPE,
        "skill_name": skill_name,
        "skill_level": skill_level,
        "grade": grade,
        "base_bonus": base_bonus,
        "skill_bonus": skill_bonus,
        "realm_bonus": realm_bonus,
        "total_modifier": total_modifier,
        "amplify_total": total_amplify,
        "amplify_detail": amplify_detail,
        "dc": dc,
        "dc_reason": dc_reason,
        "dice_natural": dice_result["natural"],
        "dice_total": dice_result["total"],
        "dice_rolls": dice_result["rolls"],
        "delta": delta,
        "verdict_grade": verdict_grade,
        "verdict": verdict_name,
        "verdict_narr": verdict_narr,
        "constraint_text": constraint_text,
        "effect_result": effect_result,
        "effect_results": effect_results,
        "npc_effect_results": npc_effect_results,
        "effect_mount_log": effect_mount_log,
    }

