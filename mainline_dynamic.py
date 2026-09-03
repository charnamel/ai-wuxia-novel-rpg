# mainline_dynamic.py  目录锚点版：基于固定原著桥段生成，严格按顺序推进
import json
import re
import os
from llm_utils import get_llm_content
from file_utils import save_json, load_json, load_context_cache

# ========== 常量配置 ==========
HISTORY_FILE = "data/mainline_history.json"
CONTEXT_CACHE_FILE = "data/context_cache.json"
PLAYER_FILE = "data/player.json"
LOCATION_FILE = "data/location_time.json"
WORLD_STATE_FILE = "data/world_state.json"
NPC_AGENT_FILE = "data/npc_agents.json"
MAINLINE_CATALOG_FILE = "data/mainline_catalog.json"  # 新增：原著固定桥段目录

# ========== 主线进度累计（模块化：累计阈值/公式统一收口到本模块） ==========
# 原位于 main.py，现下沉至此，main.py 仅作转发导入，保证唯一数据源。
# 设计说明（公式）：
#   - 每次普通日常交互        current_progress += PLOT_PROGRESS_PER_ACTION(=1)
#   - 每次「对战」结算        current_progress += 5
#   - 每次「回归主线」指令     current_progress += 8
#   - 当 current_progress >= MAJOR_PLOT_TRIGGER_POINT(=100) 时触发一次，
#     触发后 current_progress 归零重新累计（固定阈值，不再递增）。
#   - 触发只产生一个 "trigger_mainline" 标记，由 check_and_consume_mainline_flag()
#     在下一轮主循环消费，消费时才注入「主线暗线牵引」提示词（指向 X+1 号桥段，不推进编号）。
PROGRESS_FILE = "data/progress.json"
PLOT_PROGRESS_PER_ACTION = 1.0   # 每次日常交互推进的剧情进度值
MAJOR_PLOT_TRIGGER_POINT = 100   # 每当进度累计满 100 点，触发一次原著主线关键节点

def init_progress():
    # 读取/初始化主线程度进度文件：current_progress 当前累计量 / trigger_threshold 触发门槛 / flags 待消费标记 / trigger_count 已触发次数
    if os.path.exists(PROGRESS_FILE):
        prog = load_json(PROGRESS_FILE)
        if prog and isinstance(prog, dict):
            return prog
    progress = {
        "current_progress": 0.0,
        "trigger_threshold": MAJOR_PLOT_TRIGGER_POINT,
        "flags": [],
        "trigger_count": 0
    }
    save_json(PROGRESS_FILE, progress)
    return progress

def update_progress(delta: float):
    # 累加主线进度；累计满阈值(100)即触发一次，触发后归零重新累计
    prog = init_progress()
    prog["current_progress"] += delta
    if prog["current_progress"] >= prog["trigger_threshold"]:
        prog["trigger_count"] = prog.get("trigger_count", 0) + 1
        prog["current_progress"] = 0.0
        prog["trigger_threshold"] = MAJOR_PLOT_TRIGGER_POINT
        prog["flags"].append("trigger_mainline")
    save_json(PROGRESS_FILE, prog)
    return prog

def check_and_consume_mainline_flag():
    # 下一轮主循环消费自动主线触发标记：存在则移除并返回 True，表示本轮应注入主线牵引
    prog = init_progress()
    if "trigger_mainline" in prog["flags"]:
        prog["flags"].remove("trigger_mainline")
        save_json(PROGRESS_FILE, prog)
        return True
    return False


# ========== 基础历史读写（完全保留原有逻辑） ==========
def init_history():
    # 初始化主线历史文件
    if not os.path.exists(HISTORY_FILE):
        save_json(HISTORY_FILE, {
            "events": [],
            "current_order": 1,
            "last_trigger_round": 0
        })

def load_history():
    # 加载主线历史数据
    init_history()
    return load_json(HISTORY_FILE)

def save_history(history):
    # 保存主线历史数据
    save_json(HISTORY_FILE, history)


# ========== 新增：原著目录读取与进度控制 ==========
def load_mainline_catalog():
    # 加载本地原著主线目录，按id升序排列
    if not os.path.exists(MAINLINE_CATALOG_FILE):
        print("[主线系统] 警告：未找到 mainline_catalog.json，将降级为自由生成模式")
        return []
    
    data = load_json(MAINLINE_CATALOG_FILE)
    if not isinstance(data, dict) or "tasks" not in data:
        print("[主线系统] 警告：目录文件格式异常，降级为自由生成模式")
        return []
    
    tasks = data["tasks"]
    tasks.sort(key=lambda x: x.get("id", 0))
    return tasks

def _get_current_catalog_progress():
    # 获取当前已激活的最大桥段ID，手动跳转优先级最高
    history = load_history()
    skip_id = history.get("manual_skip_id", 0)
    if skip_id > 0:
        return skip_id
    events = history.get("events", [])
    if not events:
        return 0
    
    max_id = 0
    for evt in events:
        cid = evt.get("catalog_id", 0)
        if cid > max_id:
            max_id = cid
    return max_id

def _get_next_catalog_task():
    # 获取下一个待生成的原著基准桥段，已到结局则返回None
    catalog = load_mainline_catalog()
    if not catalog:
        return None
    
    current_id = _get_current_catalog_progress()
    for task in catalog:
        if task["id"] > current_id:
            return task
    return None


def set_mainline_skip(target_id):
    # 手动设置下一次回归主线的目标桥段ID
    history = load_history()
    catalog = load_mainline_catalog()
    if target_id < 1 or target_id > len(catalog):
        return False, f"❌ ID超出范围（1-{len(catalog)}）"
    history["manual_skip_id"] = target_id - 1
    save_history(history)
    task = catalog[target_id - 1]
    year_tag = f"（{task.get('year','?')}年）" if task.get('year') else ""
    return True, f"✅ 已跳转到第{target_id}号{year_tag}「{task['title']}」，下次「回归主线」生效"

def list_upcoming_mainlines(count=5):
    # 查看即将到来的主线清单
    catalog = load_mainline_catalog()
    current = _get_current_catalog_progress()
    upcoming = [t for t in catalog if t["id"] > current][:count]
    lines = [f"📖 即将到来的主线（当前进度：第{current}号）："]
    for t in upcoming:
        year_tag = f" [{t.get('year','?')}]" if t.get('year') else ""
        lines.append(f"  {t['id']}.{year_tag} {t['title']} — {t['summary'][:60]}")
    return "\n".join(lines)


# ========== 上下文读取（完全保留原有逻辑） ==========
def _load_current_game_context():
    # 读取当前游戏最新状态，为主线生成提供分层锚点
    # 分层结构与 main.py 完全对齐：L1 即时锚点 / L2 章节摘要 / L3 全局传记
    # 全部从本地文件读取，避免循环依赖
    context = {}
    cache = load_context_cache() or {}
    interact_logs = cache.get("interact_log", [])

    # ========== L1：即时场景锚点（最新1轮完整剧情，精确承接） ==========
    l1_round_text = ""
    if interact_logs:
        last_log = interact_logs[-1]
        plot_match = re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", last_log, re.S)
        if plot_match:
            l1_round_text = plot_match.group(1).strip()
    context["l1_latest_plot"] = l1_round_text if l1_round_text else "剧情初始阶段"
    context["current_round"] = cache.get("round", len(interact_logs))

    # ========== L2：近期章节摘要（最近2章，中期剧情脉络） ==========
    chapter_summaries = cache.get("chapter_summaries", [])
    recent_chapters = chapter_summaries[-2:] if len(chapter_summaries) >= 2 else chapter_summaries
    l2_chapter_text = ""
    if recent_chapters:
        chapter_lines = []
        for ch in recent_chapters:
            chapter_lines.append(f"第{ch['chapter_id']}章（{ch['round_range']}）：{ch['summary']}")
        l2_chapter_text = "\n".join(chapter_lines)
    context["l2_chapter_summaries"] = l2_chapter_text if l2_chapter_text else "暂无章节摘要"

    # ========== L3：全局传记与世界状态（长期脉络） ==========
    bio = cache.get("biography", {})
    world_state_bio = bio.get("world_state", {})
    protagonist = bio.get("protagonist", {})
    
    context["l3_protagonist"] = {
        "name": protagonist.get("name", "无名少侠"),
        "identity": protagonist.get("identity", "普通江湖人"),
        "core_ability": protagonist.get("core_ability", "基础内功"),
        "allies": protagonist.get("allies", [])[:5],
        "enemies": protagonist.get("enemies", [])[:5],
        "reputation": protagonist.get("reputation", 0)
    }
    context["l3_world_state"] = {
        "main_plot": world_state_bio.get("main_plot", "故事初始"),
        "unresolved_arcs": world_state_bio.get("unresolved_arcs", [])[:3]
    }
    context["full_plot_summary"] = cache.get("full_plot_summary", "故事初始")[:250]

    # ========== 玩家修为状态 ==========
    try:
        from player_manager import Player
        player = Player.load()
        if player:
            context["player_realm"] = player.overall_realm
            context["core_skill"] = player.core_ability
            context["player_name"] = player.name
            skill_list = []
            for sk in sorted(player.martial_skill_list, key=lambda s: s.get("exp", 0), reverse=True)[:4]:
                exp = sk.get("exp", 0)
                realm = player.get_realm(exp)
                skill_list.append(f"{sk['skill_name']}（{realm}）")
            context["player_skills"] = skill_list
        else:
            context["player_realm"] = "初窥门径"
            context["core_skill"] = "基础内功"
            context["player_skills"] = []
    except Exception:
        context["player_realm"] = "初窥门径"
        context["core_skill"] = "基础内功"
        context["player_skills"] = []

    # ========== 当前时空：地点、时间、天气 ==========
    try:
        loc_time = load_json(LOCATION_FILE) or {}
        context["current_location"] = loc_time.get("location", "未知地点")
        context["current_time"] = loc_time.get("time", "未知时辰")
        context["current_weather"] = loc_time.get("weather", "晴")
    except Exception:
        context["current_location"] = "未知地点"
        context["current_time"] = "未知时辰"
        context["current_weather"] = "晴"

    # ========== 江湖大势 ==========
    try:
        world_state = load_json(WORLD_STATE_FILE) or {}
        context["world_trend"] = world_state.get("world_trend", "江湖平静")
        context["recent_rumor"] = world_state.get("recent_rumor", "暂无传闻")
        context["active_events"] = world_state.get("active_events", [])
    except Exception:
        context["world_trend"] = "江湖平静"
        context["recent_rumor"] = "暂无传闻"
        context["active_events"] = []

    # ========== 活跃NPC（最近5轮剧情中实际出场的角色）==========
    try:
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        all_npc_list = npc_data.get("npc_list", [])
        all_npc_names = [n["name"] for n in all_npc_list if n.get("name")]
        # 扫描最近5轮剧情，提取出场NPC
        active_npc_names = set()
        for log in interact_logs[-5:]:
            plot_match = re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", log, re.S)
            if plot_match:
                plot_text = plot_match.group(1)
                for name in all_npc_names:
                    if name and name in plot_text:
                        active_npc_names.add(name)
        # 构建NPC列表（带态度标签和关系描述）
        active_npcs = []
        try:
            from main import get_favor_attitude
        except ImportError:
            def get_favor_attitude(f): return "陌生"
        for n in all_npc_list:
            if n["name"] in active_npc_names:
                favor = n.get("initial_favor", 50)
                attitude = get_favor_attitude(favor)
                relation = n.get("relation_to_player", "")
                active_npcs.append({
                    "name": n["name"],
                    "identity": n.get("identity", "江湖人士"),
                    "favor": favor,
                    "attitude": attitude,
                    "relation": relation,
                    "body_status": n.get("body_status", "normal")
                })
        active_npcs.sort(key=lambda x: abs(x["favor"]), reverse=True)
        context["active_npcs"] = active_npcs[:6]
    except Exception:
        context["active_npcs"] = []

    # ========== 里程碑时间线（最近10条关键事件）==========
    try:
        milestones = cache.get("milestones", [])
        context["milestone_timeline"] = "\n".join(f"  • {m}" for m in milestones[-10:]) if milestones else "暂无"
    except Exception:
        context["milestone_timeline"] = "暂无"

    # ========== 当前进行中的任务简报 ==========
    try:
        from task_manager import get_task_brief_for_ai
        context["task_brief"] = get_task_brief_for_ai()
    except Exception:
        context["task_brief"] = ""

    return context


# ========== 核心修改：主线生成加入固定目录锚点 ==========
def generate_next_event(world_data, npc_data, history):
    # 优化版：基于固定原著桥段生成主线
    # 1. 先从目录取下一个基准桥段，核心事件、人物、剧情100%遵循原著
    # 2. AI仅负责将触发入口适配到玩家当前场景，实现无缝衔接
    # 3. 保留原有多层JSON解析兜底
    from main import llm_call_common  # 延迟导入，避免循环依赖

    # ===== 新增：获取下一个原著基准桥段 =====
    catalog_task = _get_next_catalog_task()
    catalog_id = catalog_task["id"] if catalog_task else 0
    catalog_title = catalog_task["title"] if catalog_task else "无"
    catalog_summary = catalog_task["summary"] if catalog_task else "自由推演"
    catalog_original = catalog_task.get("original_plot", "") if catalog_task else ""
    catalog_npcs = catalog_task.get("involved_npcs", []) if catalog_task else []
    catalog_year = catalog_task.get("year", "") if catalog_task else ""

    # ===== 1. 加载当前游戏上下文 =====
    game_ctx = _load_current_game_context()

    # ===== 2. 整理已发生主线历史 =====
    past_events = history["events"][-3:]
    past_summary = "\n".join([
        f"- 第{e.get('order', 0)}件：{e.get('title', '')}（{e.get('summary', '')}）"
        for e in past_events
    ]) if past_events else "暂无已发生的主线事件，从开局阶段起步。"

    # ===== 3. 精简NPC信息 =====
    npc_simple = [
        {"name": n["name"], "identity": n["identity"]}
        for n in npc_data.get("npc_list", [])[:10]
    ]
    npc_pool_text = json.dumps(npc_simple, ensure_ascii=False)

    # ===== 提取上一条主线节点 =====
    all_history_events = history.get("events", [])
    if all_history_events:
        last_main = all_history_events[-1]
        last_main_text = f"{last_main['title']}：{last_main['summary']}"
    else:
        last_main_text = "暂无前置主线，为首条主线事件"

    # ===== 4. 构造强约束Prompt（核心改动：强制遵循基准桥段） =====
    prompt = f"""你是一个金庸原著剧情任务生成器，严格按照给定的【基准原著桥段】与【原著世界观背景】生成剧情。
【核心铁律】
本次生成必须100%围绕【基准原著桥段】延续展开，核心事件、关键人物、剧情内核绝对不能修改、不能原创，仅可优化触发方式，可以是听说、传闻或者直接出发，自然衔接玩家当前场景。年代时间必须严格一致，不允许提前出现未来的人物、事件、物品。
【基准原著桥段（必须严格遵循）】
桥段编号：第{catalog_id}号
年代时间：{catalog_year}
事件标题：{catalog_title}
核心剧情：{catalog_summary}
原著出处：{catalog_original}
核心涉及人物：{', '.join(catalog_npcs)}

【输出铁律（违反即无效）】
1. 只输出一个标准JSON对象，绝对禁止输出任何前言、解释、注释、问候语、markdown标记
2. 输出内容必须可以直接被Python json.loads()解析，不允许有JSON之外的任何字符
3. 所有键名严格使用给定名称，不得增删、改名
4. 字符串内容中的双引号必须转义为 \"

【原著世界观背景】
{world_data.get('core_plot_background', '')}

【分层剧情锚点（从近到远，必须严格承接）】
■ L1 即时场景（上一轮刚发生的剧情，必须从这里无缝延伸到基准桥段）
{game_ctx['l1_latest_plot']}
■ L2 近期章节（最近剧情脉络）
{game_ctx['l2_chapter_summaries']}
■ L3 全局脉络（人物关系与世界大势）
全量剧情概要：{game_ctx['full_plot_summary']}
主角身份：{game_ctx['l3_protagonist']['identity']}
当前盟友：{', '.join(game_ctx['l3_protagonist']['allies'])}
当前仇敌：{', '.join(game_ctx['l3_protagonist']['enemies'])}


【玩家当前状态（仅用于设计触发入口，不改事件本身）】
姓名：{game_ctx.get('player_name', '少侠')}
修为境界：{game_ctx.get('player_realm', '初窥门径')}
核心功法：{game_ctx.get('core_skill', '基础内功')}
当前地点：{game_ctx.get('current_location', '未知地域')}
当前时辰：{game_ctx.get('current_time', '未知时辰')}

【已结识活跃NPC（仅可从这些人物中设计触发入口）】
{chr(10).join([f"• {n['name']}（{n['identity']}）{n['attitude']}" + (f"·{n['relation']}" if n.get('relation') else "") + f" {n['body_status']}" for n in game_ctx.get('active_npcs', [])])}

【上一条主线事件（必须承接它继续发展）】
{last_main_text}

【硬性生成规则】
1. 原著为本：事件核心基于【基准原著桥段】发挥演绎，剧情自然，标题可微调但内核不变。
2. 场景衔接：仅把事件的「触发入口」适配到玩家当前地点，通过已结识江湖传闻、NPC偶遇等方式让玩家了解到剧情，绝不突兀，也不许瞬移
3. 伏笔承接：若有未解决伏笔，可在事件开端自然关联
4. 明确入口：写清玩家在当前地点如何遇上这件事
5. 标注出处：必须保留原著对应桥段名称

【输出格式】仅输出JSON对象，除此以外无任何文字：
{{
  "title": "事件标题（简洁有力，符合原著章回感）",
  "summary": "事件核心内容，30-50字",
  "trigger_scene": "触发场景描述（30字内，说明玩家如何遭遇此事，实现无缝衔接）",
  "involved_npcs": ["人物1", "人物2"],
  "related_foreshadowing": "承接了哪个伏笔/埋下了什么新伏笔",
  "stage": "早期/中期/后期",
  "原著对应桥段": "一句话说明对应原著哪个情节"
}}
"""

    # ===== 5. 调用LLM生成 =====
    raw = get_llm_content(llm_call_common(prompt, "生成贴合当前剧情的主线事件", max_tokens=2000, temp=0.4))

    # ===== 6. 多层级健壮JSON解析（完全保留原有兜底逻辑） =====
    raw_text = raw.strip()
    event = None

    # ---------- 第1层：快速尝试 ----------
    clean_text = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", raw_text).strip()
    try:
        event = json.loads(clean_text)
    except json.JSONDecodeError:
        pass

    # ---------- 第2层：精准提取大括号 ----------
    if not event:
        brace_count = 0
        start_idx = -1
        end_idx = -1
        for i, ch in enumerate(clean_text):
            if ch == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    end_idx = i + 1
                    break
        if start_idx != -1 and end_idx != -1:
            json_body = clean_text[start_idx:end_idx]
            json_body = json_body.replace('“', '"').replace('”', '"')
            json_body = json_body.replace('‘', '"').replace('’', '"')
            json_body = re.sub(r'[\x00-\x1f\x7f]', '', json_body)
            json_body = re.sub(r',\s*}', '}', json_body)
            json_body = re.sub(r',\s*]', ']', json_body)
            try:
                event = json.loads(json_body)
            except json.JSONDecodeError:
                if json_body.count('{') > json_body.count('}'):
                    json_body += '}' * (json_body.count('{') - json_body.count('}'))
                    try:
                        event = json.loads(json_body)
                    except json.JSONDecodeError:
                        pass

    # ---------- 第3层：字段级正则提取兜底 ----------
    if not event:
        def extract_field(pattern, text, default=""):
            m = re.search(pattern, text, re.S)
            return m.group(1).strip().strip('"').strip("'") if m else default

        title = extract_field(r'"title"\s*:\s*"([^"]*?)"', clean_text, catalog_title)
        summary = extract_field(r'"summary"\s*:\s*"([^"]*?)"', clean_text, catalog_summary)
        trigger = extract_field(r'"trigger_scene"\s*:\s*"([^"]*?)"', clean_text, "你在当地听闻消息，意外卷入其中。")
        foreshadowing = extract_field(r'"related_foreshadowing"\s*:\s*"([^"]*?)"', clean_text, "引出后续主线线索")
        stage = extract_field(r'"stage"\s*:\s*"([^"]*?)"', clean_text, "中期")
        original = extract_field(r'"原著对应桥段"\s*:\s*"([^"]*?)"', clean_text, catalog_original)

        npcs_match = re.search(r'"involved_npcs"\s*:\s*\[(.*?)\]', clean_text, re.S)
        involved_npcs = catalog_npcs.copy()
        if npcs_match:
            npcs_raw = npcs_match.group(1)
            parsed_npcs = [n.strip().strip('"').strip("'") for n in npcs_raw.split(',') if n.strip()]
            if parsed_npcs:
                involved_npcs = parsed_npcs

        event = {
            "title": title,
            "summary": summary,
            "trigger_scene": trigger,
            "involved_npcs": involved_npcs,
            "related_foreshadowing": foreshadowing,
            "stage": stage,
            "原著对应桥段": original
        }

    # ---------- 字段兜底补全，核心字段强制对齐基准桥段 ----------
    if not event.get("title"):
        event["title"] = catalog_title
    if not event.get("summary"):
        event["summary"] = catalog_summary
    if not event.get("involved_npcs") or not isinstance(event["involved_npcs"], list):
        event["involved_npcs"] = catalog_npcs
    if not event.get("trigger_scene"):
        event["trigger_scene"] = "你在当地听闻消息，意外卷入其中。"
    if "原著对应桥段" not in event:
        event["原著对应桥段"] = catalog_original

    # 附带catalog_id和catalog_year，用于进度推进和存档
    event["_catalog_id"] = catalog_id
    event["_catalog_year"] = catalog_year
    return event


# ========== 推进主线（接口完全兼容，新增进度记录） ==========
def advance_mainline(world_data, npc_data):
    # 触发下一段主线，返回事件对象（接口完全兼容旧版）
    history = load_history()

    # 检查是否已推进到结局
    if not _get_next_catalog_task():
        print("[主线系统] 已推进至原著最终结局，暂无后续主线")
        return None

    event = generate_next_event(world_data, npc_data, history)

    new_event = {
        "order": history["current_order"],
        "title": event["title"],
        "summary": event["summary"],
        "trigger_scene": event.get("trigger_scene", "你意外卷入此事。"),
        "status": "pending",
        "involved_npcs": event.get("involved_npcs", []),
        "related_foreshadowing": event.get("related_foreshadowing", ""),
        "original_plot": event.get("原著对应桥段", ""),
        "catalog_id": event.get("_catalog_id", 0),  # 记录桥段ID，用于顺序推进
        "catalog_year": event.get("_catalog_year", "")  # 记录年代，用于时间线追踪
    }

    history["events"].append(new_event)
    history["current_order"] += 1
    history["manual_skip_id"] = 0  # 跳转完成后清除
    save_history(history)

    print(f"[主线系统] 已激活第{new_event['catalog_id']}号原著桥段：{new_event['title']}")
    return new_event


# ========== 原有接口（完全保留，零改动兼容） ==========
def mark_last_event_completed():
    # 标记最近一个进行中的事件为已完成
    history = load_history()
    for i in range(len(history["events"]) - 1, -1, -1):
        if history["events"][i].get("status") == "pending":
            history["events"][i]["status"] = "completed"
            save_history(history)
            return True
    return False

def get_pending_mainline():
    # 查看未关闭的主线事件，返回格式化文本
    history = load_history()
    events = history.get("events", [])
    pending_events = [e for e in events if e.get("status") == "pending"]

    if not pending_events:
        return "📌 当前主线状态\n\n暂无进行中的主线事件，输入「回归主线」可触发新节点。"

    output_lines = []
    output_lines.append(f"📌 进行中主线（共 {len(pending_events)} 个未关闭节点）")
    output_lines.append("")
    for evt in pending_events:
        order = evt.get("order", 0)
        title = evt.get("title", "未知事件")
        summary = evt.get("summary", "无摘要")
        trigger = evt.get("trigger_scene", "场景未知")
        npcs = evt.get("involved_npcs", [])
        npc_text = "、".join(npcs) if npcs else "无"
        original = evt.get("original_plot", "")

        output_lines.append(f"第{order}回：{title}")
        output_lines.append(f"  核心剧情：{summary}")
        output_lines.append(f"  触发入口：{trigger}")
        output_lines.append(f"  涉及人物：{npc_text}")
        if original:
            output_lines.append(f"  原著出处：{original}")
        output_lines.append("")

    # 新增：原著进度显示 + 下一步预告
    catalog = load_mainline_catalog()
    if catalog:
        current = _get_current_catalog_progress()
        total = len(catalog)
        current_task = next((t for t in catalog if t['id'] == current), None)
        current_year = current_task.get('year', '?') if current_task else '?'
        output_lines.append(f"📊 原著进度：第 {current} / {total} 个桥段（当前年代：{current_year}年）")
        next_task = _get_next_catalog_task()
        if next_task:
            next_year = f"[{next_task.get('year','?')}] " if next_task.get('year') else ""
            output_lines.append(f"⏭ 下一桥段：第{next_task['id']}回 {next_year}「{next_task['title']}」")
            if next_task.get("summary"):
                output_lines.append(f"   剧情概要：{next_task['summary'][:120]}")
            if next_task.get("original_plot"):
                output_lines.append(f"   原著出处：{next_task['original_plot'][:100]}")

    return "\n".join(output_lines)
