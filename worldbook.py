# -*- coding: utf-8 -*-
"""
worldbook.py — 世界书检索引擎 v2
==================================
【设计原则】零侵入、懒加载、自动更新、安全降级
【功能】从6个数据源构建内存倒排索引，每轮按需检索注入AI上下文
【数据源 → 6输出类】一一对应
  ① mainline_catalog.json     → 任务（任务剧情）
  ② npc_agents.json           → NPC（人物档案，仅此源）
  ③ martial_arts_bonus.json   → 武功（仅grade≥3）
  ④ timeline_reference.json   → 门派（仅 factions[]）
  ⑤ map_data.json             → 地点（三级嵌套）
  ⑥ items_catalog.json        → 物品（CSV全量转换，新增）
【输出格式】6大类独立标题 + 按比例字数配额分配
"""

import os
import json
import time

# ====== 数据目录配置 ======
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

# ====== 数据源文件列表（mtime变更时自动重建索引）======
_SOURCE_FILES = [
    "npc_agents.json",            # NPC（②）
    "martial_arts_bonus.json",    # 武功（③）
    "mainline_catalog.json",      # 任务（①）
    "timeline_reference.json",    # 门派（④，仅 factions[]）
    "map_data.json",              # 地点（⑤）
    "items_catalog.json",         # 物品（⑥，新增）
]

# ====== 检索配置 ======
_DEFAULT_MAX_CHARS = 2000   # 每轮注入AI上下文字数上限
_DEFAULT_TOP_K = 24         # 最大返回条目数（6类 × 4条 ≈ 24）
_BUILD_INTERVAL = 5         # 最小重建间隔（秒），防止高频操作抖动

# ====== 物品稀有度权重（base_score × 稀有度倍率）======
_ITEM_RARITY_WEIGHT = {
    "S": 3.0,   # 传世至宝
    "A": 2.0,   # 绝顶之宝
    "B": 1.2,   # 罕见好物
    "C": 0.8,   # 江湖常见
    "D": 0.4,   # 普通物品
}

# ====== v2 分类映射：6源category → 6输出类 ======
_CATEGORY_MAP = {
    "剧情": "task",           # ①任务（只要 mainline_catalog.tasks[]）
    "人物": "npc",            # ②NPC（只要 npc_agents.npc_list[]）
    "武功": "martial",        # ③武功（martial_arts_bonus，grade≥3）
    "门派": "faction",        # ④门派（timeline_reference.factions[]）
    "地理": "location",       # ⑤地点（map_data 三级嵌套）
    "物品": "item",           # ⑥物品（items_catalog.items[]）
}

# 输出标题（按用户指定命名+编号）
_GROUP_TITLES = {
    "task":     "【①任务】",
    "npc":      "【②NPC】",
    "martial":  "【③武功】",
    "item":     "【④物品】",
    "faction":  "【⑤门派】",
    "location": "【⑥地点】",
}

# 6大类字数配额比例（合计100%，总上限_DEFAULT_MAX_CHARS）
_GROUP_CHAR_RATIO = {
    "task": 0.15,       # 300字：任务描述通常精简
    "npc": 0.25,        # 500字：交互核心，条目多且长
    "martial": 0.15,    # 300字：武功描述中等
    "item": 0.20,       # 400字：物品870条，命中率会上升
    "faction": 0.15,    # 300字：门派阶段信息有价值
    "location": 0.10,   # 200字：地点短句
}

# 某类配额未耗尽时，溢出补给优先级（高→低）
# v2: 移除 item —— 870条物品自身配额400字已够，不应吃溢出霸屏
_GROUP_OVERFLOW_PRIORITY = ["npc", "task", "faction", "martial", "location"]

# v2: L3 gram 匹配按类别设权重（物品870条gram太容易刷分，大幅降低）
_L3_GRAM_WEIGHT_BY_GROUP = {
    "task": 0.3,       # 任务条目少，gram补召回
    "npc": 0.3,        # NPC关键词少，gram补召回
    "faction": 0.2,    # 门派中等
    "martial": 0.15,   # 武功492条，适度降
    "location": 0.15,  # 地点231条，适度降
    "item": 0.05,      # 物品870条，gram匹配极易刷屏，降至最低
}

# v2: 每类最低候选槽位（保证核心类别不被priority=1的大类挤占）
# v3: 收窄槽位，防止L3 gram噪声条目大量涌入
_PER_CATEGORY_SLOTS = {
    "npc": 8,          # 交互核心，但8条已够（L1命中的一定进）
    "task": 6,
    "martial": 6,
    "item": 6,
    "faction": 4,
    "location": 5,
}

# v3: score门槛——低于此分数的条目不进入候选（过滤L3 gram噪声）
# L1标题命中=10分(稳过)，L2关键词=1分/个(需1-2个)，L3纯gram=0.3分/个(需5个以上才过)
_SCORE_THRESHOLD = 1.5

# ====== 全局单例 ======
_index = None


def _load_json(filename):
    """安全加载JSON文件"""
    filepath = os.path.join(_DATA_DIR, filename)
    if not os.path.exists(filepath):
        print(f"[世界书] 文件不存在: {filepath}")
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception as e:
        print(f"[世界书] 加载失败 {filename}: {e}")
        return {}


def _get_file_mtime(filename):
    """获取文件mtime（纳秒级）"""
    filepath = os.path.join(_DATA_DIR, filename)
    try:
        return os.stat(filepath).st_mtime_ns
    except OSError:
        return 0


# ================================================================
#  条目生成函数（每个数据源一个，未来扩展新源直接加函数）
# ================================================================

def _format_skill_brief(skill, ma_book):
    """格式化单个武功为简要信息：武功名(品阶N级·境界)
    优先用武功书grade，无则标注"未入品"
    """
    if isinstance(skill, dict):
        sn = skill.get("skill_name", "")
        sl = skill.get("skill_level", "")
    elif isinstance(skill, str):
        sn = skill
        sl = ""
    else:
        return ""

    if not sn or sn in ("轻功", "内功", "点穴", "医术", "普通武功", "毒术"):
        return ""  # 过滤太泛的武功名

    # 查武功书获取grade
    grade_str = ""
    ma_info = ma_book.get(sn)
    if ma_info and isinstance(ma_info, dict):
        g = ma_info.get("grade", 0)
        if g:
            grade_str = f"品阶{g}级"

    # 组合
    parts = [sn]
    if grade_str:
        parts.append(grade_str)
    if sl:
        parts.append(sl)
    return "·".join(parts)


def _build_npc_entries(npc_data):
    """
    从 npc_agents.json 构建NPC索引条目
    【关键词】人名 + 身份前3字 + 门派 + 武功名
    【输出category】人物 → ②NPC
    【v2新增】content末尾追加武功简要（武功名·品阶·境界，最多4门）
    """
    # 加载武功书用于交叉补充grade
    ma_book = {}
    try:
        ma_path = os.path.join(_DATA_DIR, "martial_arts_bonus.json")
        if os.path.exists(ma_path):
            with open(ma_path, encoding="utf-8-sig") as f:
                ma_data = json.load(f)
            ma_book = ma_data.get("martial_arts", {}) or ma_data.get("skills", {})
            if isinstance(ma_book, dict):
                ma_book = {k: v for k, v in ma_book.items() if isinstance(v, dict)}
    except Exception as e:
        print(f"[世界书] 加载武功书用于NPC交叉补充失败: {e}")

    entries = []
    npc_list = npc_data.get("npc_list", [])
    print(f"[世界书] 加载NPC档案: {len(npc_list)} 人")

    for npc in npc_list:
        name = npc.get("name", "")
        if not name:
            continue
        identity = npc.get("identity", "")
        background = npc.get("background", "")
        skills = str(npc.get("skills", ""))
        faction = npc.get("faction", "")
        martial_skills = npc.get("martial_skills", [])

        # 关键词: 人名 + 身份 + 门派 + 武功名
        keywords = {name}
        if identity and len(identity) >= 2:
            keywords.add(identity[:3])
        if faction:
            keywords.add(faction)
        if background and len(background) <= 10:
            keywords.add(background)
        # v2: 武功名也加入关键词
        if isinstance(martial_skills, list):
            for sk in martial_skills:
                if isinstance(sk, dict):
                    sn = sk.get("skill_name", "")
                elif isinstance(sk, str):
                    sn = sk
                else:
                    continue
                if sn and len(sn) >= 2 and sn not in ("轻功", "内功", "点穴", "医术"):
                    keywords.add(sn)

        # content: 简短一行档案 + 武功简要
        content_bits = [f"【{name}】"]
        if identity:
            content_bits.append(identity)
        if faction:
            content_bits.append(f"门派：{faction}")
        if background and len(background) <= 30:
            content_bits.append(background)

        # v3: 追加 personality（2-8字精简版）
        personality = npc.get("personality", "").strip()
        if personality:
            content_bits.append(f"性格：{personality}")

        # v4: 追加出生年份（用于AI判断NPC当前年龄）
        year = npc.get("year")
        if year:
            content_bits.append(f"生于：{year}年")

        # v2: 追加武功简要（最多4门主要武功）
        if isinstance(martial_skills, list) and martial_skills:
            skill_briefs = []
            for sk in martial_skills[:6]:  # 最多取前6门筛选
                brief = _format_skill_brief(sk, ma_book)
                if brief:
                    skill_briefs.append(brief)
            if skill_briefs:
                content_bits.append(f"武功：{' / '.join(skill_briefs[:4])}")

        content = " | ".join(content_bits)

        entry = {
            "id": f"npc_{name}",
            "source": "npc_agents.json",
            "category": "人物",
            "title": name,
            "keywords": list(keywords),
            "content": content,
            "year_range": "",
            "stage": "",
            "priority": 1,     # NPC优先
            "weight": 1.0,
        }
        entries.append(entry)

    return entries


def _build_martial_entries(martial_data):
    """
    从 martial_arts_bonus.json 构建武功索引条目（grade≥3）
    【关键词】武功名 + 所属类别 + 门派 + 描述关键词
    【输出category】武功 → ③武功
    """
    entries = []
    # 兼容外层结构：martial_arts / skills / 直接 dict(全武功)
    martial_dict = (
        martial_data.get("martial_arts")
        or martial_data.get("skills")
        or martial_data if isinstance(martial_data, dict) else {}
    )
    # 过滤非武功条目（元数据如_description/_version/_grade_system）
    if isinstance(martial_dict, dict):
        martial_dict = {k: v for k, v in martial_dict.items() if isinstance(v, dict) and "grade" in v}
    print(f"[世界书] 加载武功书: ", end="")

    count = 0
    for skill_name, skill_info in martial_dict.items():
        if not isinstance(skill_info, dict):
            continue
        grade = skill_info.get("grade", 0)
        if grade < 3:   # 只保留品阶≥3的武功
            continue
        category = skill_info.get("category", "")
        desc = skill_info.get("description", "")
        brief_desc = skill_info.get("brief_desc", "")
        sect = skill_info.get("sect", "")
        features = skill_info.get("features", {})

        keywords = {skill_name, category}
        if sect:
            keywords.add(sect)
        # 效果关键词
        if isinstance(features, dict):
            for k, v in features.items():
                if isinstance(v, str):
                    keywords.add(v)
                keywords.add(str(k))
        # 描述关键词(门派/人名)
        if desc:
            words = [w for w in [sect, skill_name] if w]
            for w in words:
                keywords.add(w)

        content_parts = [f"【{skill_name}】"]
        content_parts.append(f"品阶{grade}级")
        if category:
            content_parts.append(f"| {category}类")
        if sect:
            content_parts.append(f"| {sect}")
        if brief_desc:
            content_parts.append(f"| 简介：{brief_desc}")
        elif desc:
            content_parts.append(f"| {desc[:40]}")
        content = " ".join(content_parts)

        # grade → priority/weight 映射
        priority = 2 if grade >= 7 else 3
        weight = {
            4: 0.6, 5: 0.8, 6: 1.0,
            7: 1.5, 8: 2.0, 9: 2.5, 10: 3.0
        }.get(grade, 0.5)

        entry = {
            "id": f"martial_{skill_name}",
            "source": "martial_arts_bonus.json",
            "category": "武功",
            "title": skill_name,
            "keywords": list(keywords),
            "content": content,
            "year_range": "",
            "stage": "",
            "priority": priority,
            "weight": weight,
        }
        entries.append(entry)
        count += 1

    print(f"{count} 条 (grade≥3)")
    return entries


def _build_task_entries(catalog_data):
    """
    从 mainline_catalog.json 构建任务/剧情索引条目
    【关键词】任务名 + NPC名 + 章节关键词 + 显式keywords
    【输出category】剧情 → ①任务
    """
    entries = []
    tasks = catalog_data.get("tasks", [])
    print(f"[世界书] 加载主线剧情: {len(tasks)} 条")

    for task in tasks:
        task_id = task.get("id", "")
        title = task.get("title", "")
        stage = task.get("stage", "")
        events = task.get("events", [])
        summary = task.get("summary", "")
        year_range = task.get("year", "") or task.get("year_range", "")
        main_chars = task.get("main_characters", [])
        extra_keywords = task.get("keywords", [])

        keywords = set()
        if title:
            keywords.add(title)
            # 标题含人名/派名，拆成中文2-gram
            for i in range(len(title)-1):
                piece = title[i:i+2]
                if all('\u4e00' <= c <= '\u9fff' for c in piece):
                    keywords.add(piece)
        for ev in events:
            keywords.add(ev[:4])
        for ch in main_chars:
            keywords.add(ch)
        for kw in extra_keywords:
            keywords.add(kw)
        if stage:
            keywords.add(stage)

        content_parts = [f"【{title}】"]
        if year_range:
            content_parts.append(f"剧情大概发生时间：{year_range}")
        if summary:
            content_parts.append(f"{summary[:60]}")
        if main_chars:
            content_parts.append(f"| 核心NPC：{'/'.join(main_chars[:3])}")
        content = " ".join(content_parts)

        entry = {
            "id": f"ml_{task_id}",
            "source": "mainline_catalog.json",
            "category": "剧情",
            "title": title,
            "keywords": list(keywords),
            "content": content,
            "year_range": year_range,
            "stage": stage,
            "priority": 1,
            "weight": 1.2,
        }
        entries.append(entry)

    return entries


def _build_faction_entries(timeline_data):
    """
    从 timeline_reference.json 的 factions[] 构建门派索引
    【v2 新增】按 stages[-1] 当前阶段的 power 值加权（power/5.0）
    【关键词】门派名 + 所在地 + 核心成员 + 武功 + 自定义keywords
    【输出category】门派 → ⑤门派
    """
    entries = []
    factions = timeline_data.get("factions", [])
    cats = {}
    for f in factions:
        c = f.get("category", "未分类")
        cats[c] = cats.get(c, 0) + 1
    cat_str = ", ".join(f"{k}{v}" for k, v in sorted(cats.items(), key=lambda x: -x[1]))
    print(f"[世界书] 加载门派: {len(factions)} 个 ({cat_str})")

    for f in factions:
        name = f.get("name", "")
        if not name:
            continue
        fid = f.get("id", name)
        novel = f.get("novel", "")
        category = f.get("category", "门派")
        location = f.get("location", "")
        stance = f.get("stance", "")
        core_members = f.get("core_members", [])
        martial_arts = f.get("martial_arts", [])
        allies = f.get("allies", [])
        enemies = f.get("enemies", [])
        keywords = set(f.get("keywords", []))
        flags = f.get("flags", [])

        # 关键词补全（检索逻辑不变，仍包含 stance/martial_arts/allies/enemies）
        keywords.add(name)
        if location:
            keywords.add(location)
        if stance:
            for w in stance.split():
                if len(w) >= 2:
                    keywords.add(w)
        for m in core_members:
            if len(m) >= 2 and len(m) <= 4:
                keywords.add(m)
        for ma in martial_arts:
            keywords.add(ma)
        for al in allies:
            if len(al) <= 6:
                keywords.add(al)
        for en in enemies:
            if len(en) <= 6:
                keywords.add(en)
        # flags分号拆分后加入keywords
        for fl in flags:
            if isinstance(fl, str):
                for w in fl.split(";；"):  # 兼容中英文分号
                    w = w.strip()
                    if 2 <= len(w) <= 8:
                        keywords.add(w)

        # content：精简摘要（只用 name/location/category/founding/core_members/flags）
        founding = f.get("founding", "")
        content_parts = [f"【{name}】"]
        if location:
            content_parts.append(f"[{location}")
            if category:
                content_parts[-1] += f"·{category}]"
            else:
                content_parts[-1] += "]"
        elif category:
            content_parts.append(f"[{category}]")
        if novel:
            content_parts.append(f"主要涉及剧情：《{novel}》")
        if founding:
            content_parts.append(f"创派：{founding[:40]}")
        if core_members:
            content_parts.append(f"核心：{'/'.join(core_members[:5])}")
        if flags:
            flags_text = ";".join(fl for fl in flags if isinstance(fl, str) and fl)
            if flags_text:
                content_parts.append(f"| 标记:{flags_text[:60]}")
        content = " ".join(content_parts)

        weight = 1.0
        priority = 2     # 门派优先级低于任务/NPC(priority=1)，高于武功/物品

        entry = {
            "id": fid,
            "source": "timeline_reference.json(factions)",
            "category": "门派",
            "title": name,
            "keywords": list(keywords),
            "content": content,
            "year_range": "",
            "stage": "",
            "priority": priority,
            "weight": weight,
        }
        entries.append(entry)

    return entries


def _build_location_entries(map_data):
    """
    从 map_data.json 构建地点索引（三级嵌套：region→settlement→location，字段名=children）
    【关键词】区域名 + 聚落名 + 地点名 + 所属上级
    【输出category】地理 → ⑥地点
    """
    entries = []
    regions = map_data.get("regions", []) if isinstance(map_data, dict) else []
    region_count = len(regions)
    total_loc = 0

    for region in regions:
        region_name = region.get("name", "")
        # 兼容 v3 结构：children[] 可能是聚落(settlement)
        settlements = region.get("settlements") or region.get("children") or []
        for settlement in settlements:
            if not isinstance(settlement, dict):
                continue
            settlement_name = settlement.get("name", "")
            settlement_type = settlement.get("type", "")
            settlement_kw = settlement.get("keywords", [])
            # 兼容：locations[] 或 children[] 作为叶子地点
            locations = settlement.get("locations") or settlement.get("children") or []
            for loc in locations:
                if not isinstance(loc, dict):
                    continue
                loc_name = loc.get("name", "")
                if not loc_name:
                    continue
                loc_desc = loc.get("description", "")
                loc_type = loc.get("type", "")
                loc_kw = loc.get("keywords", [])

                keywords = {loc_name}
                if settlement_name:
                    keywords.add(settlement_name)
                if region_name:
                    # 去掉"·东北"之类的前缀标记，保留纯区域名（如"东北·辽东"→"辽东"）
                    for part in region_name.replace("·", "/").split("/"):
                        if part:
                            keywords.add(part)
                    keywords.add(region_name)
                for k in settlement_kw + loc_kw:
                    keywords.add(k)

                # 路径格式：地点（聚落·区域）
                clean_region = region_name.split("·")[-1] if "·" in region_name else region_name
                path = "（" + "·".join([p for p in [settlement_name, clean_region] if p]) + "）"
                # 重要地点推断：镖局/庄/堡/寨/派/寺/峰/墓 结尾
                important = any(loc_name.endswith(suf) for suf in
                               ["镖局", "庄", "堡", "寨", "派", "寺", "宫", "谷", "堂",
                                "峰", "墓", "洞", "府", "衙门", "大营"])
                important = important or loc_type == "重要地点"
                content = f"【{loc_name}】{path}"
                if important:
                    content += " 重要地点"
                if loc_desc and not important:
                    content += f" {loc_desc[:30]}"

                entry = {
                    "id": f"map_{region.get('id', region_name)}_{settlement.get('id', settlement_name)}_{loc.get('id', loc_name)}",
                    "source": "map_data.json",
                    "category": "地理",
                    "title": loc_name,
                    "keywords": list(keywords),
                    "content": content,
                    "year_range": "",
                    "stage": "",
                    "priority": 1 if important else 3,
                    "weight": 1.2 if important else 0.7,
                }
                entries.append(entry)
                total_loc += 1

    print(f"[世界书] 加载地图: {region_count} 区域, {total_loc} 地点")
    return entries


def _build_item_entries(items_data):
    """
    【v2 新增】从 items_catalog.json 构建物品索引（870条）
    【关键词】name + subcategory + linked_martial + source + owner_hint + keywords[]
    【输出category】物品 → ④物品
    """
    items = items_data.get("items", {}) if isinstance(items_data, dict) else {}
    entries = []
    sub_counts = {}

    for iid, it in items.items():
        name = it.get("name", "")
        if not name:
            continue
        subcategory = it.get("subcategory", "")  # 秘籍/武器/防具/暗器/丹药/坐骑
        description = it.get("description", "")
        linked_martial = it.get("linked_martial", "")
        source = it.get("source", "")
        owner_hint = it.get("owner_hint", "")
        rarity = it.get("rarity", "C")
        keywords = list(it.get("keywords", []))  # 已在转换时生成

        # 补分类统计
        sub_counts[subcategory] = sub_counts.get(subcategory, 0) + 1

        # 内容格式：【name】[subcategory·rarity] description | 归属 | 对应武学
        content_parts = [f"【{name}】[{subcategory}·{rarity}]"]
        if description:
            content_parts.append(description[:50])
        if owner_hint:
            content_parts.append(f"| 归属：{owner_hint}")
        if linked_martial:
            content_parts.append(f"| 对应武学：{linked_martial}")
        if source:
            content_parts.append(f"| 出典：{source}")
        content = " ".join(content_parts)

        # priority/weight：按稀有度分配
        if rarity in ("S", "A"):
            priority = 2
        else:
            priority = 3
        weight = _ITEM_RARITY_WEIGHT.get(rarity, 0.5)

        entry = {
            "id": iid,
            "source": "items_catalog.json",
            "category": "物品",
            "subcategory": subcategory,  # 子类：秘籍/武器/...
            "rarity": rarity,
            "title": name,
            "keywords": keywords,
            "content": content,
            "year_range": "",
            "stage": "",
            "priority": priority,
            "weight": weight,
        }
        entries.append(entry)

    # DEBUG 日志
    sub_str = "/".join(f"{k}{v}" for k, v in sorted(sub_counts.items()))
    print(f"[世界书] 加载物品目录: {len(entries)} 条 ({sub_str})")
    return entries


# ================================================================
#  WorldbookIndex 核心类
# ================================================================

class WorldbookIndex:
    """世界书倒排索引类，支持懒加载 + 自动mtime检测重建"""

    def __init__(self, data_dir):
        self._data_dir = data_dir
        self._entries = {}           # id → entry dict
        self._inverted = {}          # keyword → set(ids)
        self._title_index = {}       # title 精确 → id
        self._year_index = {}        # year(str) → set(ids)
        self._file_mtimes = {}       # 源文件mtime缓存
        self._last_build = 0         # 上次构建时间戳(秒)
        self._build_interval = _BUILD_INTERVAL
        # 6大类统计
        self._stats = {
            "task": 0, "npc": 0, "martial": 0,
            "item": 0, "faction": 0, "location": 0
        }

    def _check_dirty(self):
        """检查源文件mtime是否有变化"""
        for fname in _SOURCE_FILES:
            fpath = os.path.join(self._data_dir, fname)
            try:
                mtime = os.stat(fpath).st_mtime_ns
            except OSError:
                continue
            if self._file_mtimes.get(fname, 0) != mtime:
                return True
        return False

    def _build(self, force=False):
        """构建/重建全部索引"""
        # 节流：5秒内不重复构建
        if not force and (time.time() - self._last_build) < self._build_interval:
            return
        self._last_build = time.time()
        t0 = time.time()

        self._entries.clear()
        self._inverted.clear()
        self._title_index.clear()
        self._year_index.clear()
        self._stats = {k: 0 for k in self._stats}

        # ---- 加载并构建6个数据源 ----
        builders = [
            # (文件名, 构建函数)
            ("npc_agents.json", _build_npc_entries),
            ("martial_arts_bonus.json", _build_martial_entries),
            ("mainline_catalog.json", _build_task_entries),
            ("timeline_reference.json", _build_faction_entries),
            ("map_data.json", _build_location_entries),
            ("items_catalog.json", _build_item_entries),
        ]

        for fname, builder_fn in builders:
            data = _load_json(fname)
            entries = builder_fn(data)
            for e in entries:
                self._entries[e["id"]] = e
                # 6大类计数
                cat = e.get("category", "")
                grp = _CATEGORY_MAP.get(cat, None)
                if grp and grp in self._stats:
                    self._stats[grp] += 1
                # mtime缓存
                self._file_mtimes[fname] = _get_file_mtime(fname)

        # ---- 建立倒排索引 ----
        for eid, entry in self._entries.items():
            title = entry.get("title", "")
            if title:
                self._title_index[title] = eid

            # 年代索引
            yr = entry.get("year_range", "")
            if yr:
                for ypart in yr.replace("~", "-").split("-"):
                    digits = "".join([c for c in ypart if c.isdigit()])
                    if len(digits) == 4:
                        y = int(digits)
                        for yy in range(max(1600, y - 1), min(1900, y + 2)):
                            self._year_index.setdefault(str(yy), set()).add(eid)

            # 关键词倒排
            for kw in entry.get("keywords", []):
                if len(kw) >= 2:
                    self._inverted.setdefault(kw, set()).add(eid)

            # 标题切分：中文2-gram补充进倒排
            if title and all('\u4e00' <= c <= '\u9fff' for c in title):
                for i in range(len(title) - 1):
                    gram = title[i:i+2]
                    self._inverted.setdefault(gram, set()).add(eid)

        kw_count = len(self._inverted)
        duration_ms = int((time.time() - t0) * 1000)
        stat_str = "/".join([
            f"{self._stats['task']}任务",
            f"{self._stats['npc']}NPC",
            f"{self._stats['martial']}武功",
            f"{self._stats['item']}物品",
            f"{self._stats['faction']}门派",
            f"{self._stats['location']}地点",
        ])
        print(f"[世界书] ✅ 索引构建完成: {len(self._entries)} 条目, {kw_count} 关键词")
        print(f"[世界书]    分类：{stat_str}")
        print(f"[世界书]    耗时 {duration_ms}ms")

        # === L5: 语义向量索引构建（安全降级） ===
        try:
            import semantic_index
            semantic_index.build_vectors(self._entries)
        except ImportError:
            pass  # semantic_index未安装，跳过
        except Exception as e:
            print(f"[世界书] L5语义向量构建失败（降级为纯关键词检索）: {e}")

    def search(self, text, current_year=None, top_k=None, max_chars=None):
        """
        世界书检索（对外唯一入口）
        【输入】
          text:        检索Query（上一轮AI完整输出 + 玩家最新输入）
          current_year: 当前游戏年份（可选，用于L4年代匹配加成）
          top_k:       最大候选条目数，默认24
          max_chars:   总字数上限，默认2000
        【输出】
          格式化文本（6大类独立标题+分组），空结果返回 ""
        """
        if max_chars is None:
            max_chars = _DEFAULT_MAX_CHARS
        if top_k is None:
            top_k = _DEFAULT_TOP_K

        # 懒加载 + 自动重建（mtime变更时）
        if not self._entries or self._check_dirty():
            self._build(force=True)

        try:
            if not text:
                return ""

            scores = {}   # eid → score

            # === L1: 标题精确匹配（最高权重 ×10） ===
            for title, eid in self._title_index.items():
                if title and title in text and len(title) >= 2:
                    weight = self._entries[eid].get("weight", 1.0)
                    add = 10.0 * weight
                    scores[eid] = scores.get(eid, 0) + add
                    print(f"[世界书] L1命中: '{title}' → {eid[:30]} (+{add:.1f})")

            # === L2: 关键词精确匹配（权重 ×1） ===
            if len(text) > 200:
                # 长文本时只考虑3字以上关键词，避免短词刷屏
                min_kw_len = 3
            else:
                min_kw_len = 2
            for kw, eids in self._inverted.items():
                if len(kw) < min_kw_len:
                    continue
                if kw in text:
                    for eid in eids:
                        weight = self._entries[eid].get("weight", 1.0)
                        add = 1.0 * weight
                        scores[eid] = scores.get(eid, 0) + add

            # === L3: 模糊子串匹配（中文2/3-gram，按类别设权重） ===
            # v2: 物品870条gram极易刷屏，权重从0.3降至0.05；NPC/任务保持0.3
            text_cn = "".join([c for c in text if '\u4e00' <= c <= '\u9fff'])
            grams = set()
            for n in [3, 2]:
                for i in range(len(text_cn) - n + 1):
                    grams.add(text_cn[i:i+n])
            for gram in grams:
                if len(gram) < 2:
                    continue
                for eid, entry in self._entries.items():
                    if gram in entry.get("title", "") or gram in " ".join(entry.get("keywords", [])) or gram in entry.get("content", ""):
                        # v2: 按类别取L3权重
                        src_cat = entry.get("category", "")
                        grp = _CATEGORY_MAP.get(src_cat, "")
                        l3_w = _L3_GRAM_WEIGHT_BY_GROUP.get(grp, 0.15)
                        add = l3_w * entry.get("weight", 1.0)
                        scores[eid] = scores.get(eid, 0) + add

            # === L4: 年代范围匹配（权重 ×0.5，仅当current_year存在） ===
            if current_year:
                year_str = str(current_year)
                for eid in self._year_index.get(year_str, set()):
                    add = 0.5 * self._entries[eid].get("weight", 1.0)
                    scores[eid] = scores.get(eid, 0) + add

            # === L5: 语义向量匹配（权重 ×2.0，需 similarity > 门槛） ===
            try:
                import semantic_index
                if semantic_index.is_available():
                    sem_results = semantic_index.search_semantic(text, top_k=30)
                    sem_weight = semantic_index.get_score_weight()
                    for eid, sim in sem_results:
                        if eid in self._entries:
                            w = self._entries[eid].get("weight", 1.0)
                            add = sim * sem_weight * w
                            scores[eid] = scores.get(eid, 0) + add
            except ImportError:
                pass
            except Exception as e:
                print(f"[世界书] L5语义检索异常（降级）: {e}")

            # ---- 排序：priority(降序) → score(降序) → weight(降序) ----
            must_ids = {eid for eid, e in self._entries.items() if e["priority"] == 1}
            scored_ids = set(scores.keys())
            all_ids = scored_ids | must_ids

            # v2 修复：must_ids(priority=1)即使没有score也必须有进入候选的机会
            # 给 priority=1 但无score的条目一个基础分 0.5（保证排在有score的后，但进入前N）
            for eid in (must_ids - scored_ids):
                scores[eid] = 0.5
            all_ids = scored_ids | must_ids

            ranked = sorted(all_ids, key=lambda eid: (
                -self._entries[eid]["priority"],
                -scores.get(eid, 0),
                -self._entries[eid]["weight"],
            ))

            # ---- 6大类分组 + 按比例分配字数配额 ----
            # v2: 按类别独立槽位，保证核心类别不被 priority=1 大类挤占
            # v3: 加 score 门槛，过滤 L3 gram 噪声条目
            group_ids = {"task": [], "npc": [], "martial": [], "item": [], "faction": [], "location": []}

            for eid in ranked:
                # v3: score门槛——低于阈值的条目直接跳过（L3纯gram噪声过滤）
                if scores.get(eid, 0) < _SCORE_THRESHOLD:
                    continue
                entry = self._entries[eid]
                src_cat = entry.get("category", "")
                grp = _CATEGORY_MAP.get(src_cat, None)
                if grp is None or grp not in group_ids:
                    # 兜底分类（根据特征猜测）
                    title = entry.get("title", "")
                    if any(k in title for k in ["镖局", "寺", "谷", "庄", "堂", "堡", "寨", "府", "州", "县", "省", "河", "山", "派"]):
                        if "派" in title or "门" in title or "帮" in title or "会" in title or "教" in title:
                            grp = "faction"
                        else:
                            grp = "location"
                    elif "·" in entry.get("year_range", "") or entry.get("stage", ""):
                        grp = "task"
                    elif entry.get("rarity") or entry.get("subcategory"):
                        grp = "item"
                    else:
                        grp = "npc"
                group_ids[grp].append(eid)

            # v3: 每类截断到槽位数（不再x2，直接用 _PER_CATEGORY_SLOTS）
            for g in group_ids:
                max_slots = _PER_CATEGORY_SLOTS.get(g, 6)
                if len(group_ids[g]) > max_slots:
                    group_ids[g] = group_ids[g][:max_slots]

            # 每类字数上限
            group_limits = {}
            for g, ratio in _GROUP_CHAR_RATIO.items():
                group_limits[g] = int(max_chars * ratio)

            # 每组按上限截断
            group_lines = {g: [] for g in group_ids}
            group_chars = {g: 0 for g in group_ids}
            for g, ids in group_ids.items():
                limit = group_limits[g]
                for eid in ids:
                    content = self._entries[eid]["content"]
                    if group_chars[g] + len(content) > limit:
                        break
                    group_lines[g].append(content)
                    group_chars[g] += len(content)

            # 溢出分配：某类配额没耗尽时，按 _GROUP_OVERFLOW_PRIORITY 补给其他组
            # v2: 移除 item（物品自身配额已够）；加门槛（候选≥2条才接收溢出）
            used_total = sum(group_chars.values())
            leftover = max_chars - used_total
            if leftover > 0:
                for g_priority in _GROUP_OVERFLOW_PRIORITY:
                    if leftover <= 0:
                        break
                    remaining_ids = group_ids[g_priority][len(group_lines[g_priority]):]
                    # v2 门槛：剩余候选不足2条时不接收溢出（避免1条吃满）
                    if len(remaining_ids) < 2:
                        continue
                    for eid in remaining_ids:
                        content = self._entries[eid]["content"]
                        if len(content) > leftover:
                            continue
                        group_lines[g_priority].append(content)
                        group_chars[g_priority] += len(content)
                        leftover -= len(content)
                        if leftover <= 0:
                            break

            # ---- 拼接最终输出（6大类标题顺序） ----
            output_groups = []
            has_content = False
            for g in ["task", "npc", "martial", "item", "faction", "location"]:
                if group_lines[g]:
                    output_groups.append(_GROUP_TITLES[g])
                    output_groups.extend(group_lines[g])
                    has_content = True

            if not has_content:
                return ""

            result = "\n".join(output_groups)

            # DEBUG: 检索摘要（分组计数 + 字数 + Top3）
            if scores:
                top3 = sorted(scores.items(), key=lambda x: -x[1])[:3]
                top3_ids = [eid[:30] for eid, _ in top3]
                total = sum(len(g) for g in group_lines.values())
                group_counts = (
                    f"任务{len(group_lines['task'])}/"
                    f"NPC{len(group_lines['npc'])}/"
                    f"武功{len(group_lines['martial'])}/"
                    f"物品{len(group_lines['item'])}/"
                    f"门派{len(group_lines['faction'])}/"
                    f"地点{len(group_lines['location'])}"
                )
                print(f"[世界书] 检索命中 {total} 条 ({group_counts})")
                print(f"[世界书]   字数 {sum(group_chars.values())}/{max_chars}, Query长度 {len(text)} 字")
                print(f"[世界书]   Top3: {', '.join(top3_ids)}")

            return result
        except Exception as e:
            # 安全降级：任何异常都返回空，不影响主逻辑
            print(f"[世界书] ❌ 检索异常（安全降级）: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def rebuild(self):
        """手动强制重建"""
        print("[世界书] 手动触发重建...")
        self._build(force=True)

    def get_status(self):
        """获取Web显示的状态信息"""
        # 语义检索状态
        try:
            import semantic_index
            sem_status = semantic_index.get_status()
        except ImportError:
            sem_status = {"enabled": False, "available": False}
        except Exception:
            sem_status = {"enabled": False, "available": False}

        return {
            "ready": bool(self._entries),
            "entries_count": len(self._entries),
            "keywords_count": len(self._inverted),
            "last_build": self._last_build,
            "groups": self._stats,
            "source_files": _SOURCE_FILES,
            "semantic": sem_status,
        }


# ================================================================
#  对外函数式API（零侵入：外部世界只需要import 3个函数）
# ================================================================

def init():
    """启动时初始化（不立即构建，首次search时懒加载）"""
    global _index
    _index = WorldbookIndex(_DATA_DIR)
    print("[世界书] ✅ 初始化完成，可正常检索（懒加载，首次检索时构建索引）")


def search(text, current_year=None, top_k=None, max_chars=None):
    """检索并返回格式化文本"""
    try:
        global _index
        if _index is None:
            init()
        return _index.search(text, current_year=current_year, top_k=top_k, max_chars=max_chars)
    except Exception as e:
        print(f"[世界书] ❌ search异常（安全降级为空）: {e}")
        return ""


def rebuild():
    """Web端手动触发重建"""
    global _index
    if _index is None:
        init()
    _index.rebuild()


def get_status():
    """Web端状态查询"""
    global _index
    if _index is None:
        return {"ready": False, "entries_count": 0, "keywords_count": 0, "groups": {}}
    return _index.get_status()
