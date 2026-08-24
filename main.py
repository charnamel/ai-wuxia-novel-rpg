# 你是一名熟读小说背景的现代大学生，一年前穿越到金庸小说世界，随着穿越，你脑海里还有《北冥神功》全套心法口诀，现在离正式小说剧情还有1年多时间。
# ====================== DeepSeek API 配置 ======================
# DEEPSEEK_API_KEY（线下） = "***REMOVED_API_KEY***"
# DEEPSEEK_API_KEY（线上） = "***REMOVED_API_KEY***"
# DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# powershell -ExecutionPolicy Bypass -File .\venv\Scripts\Activate.ps1
# mimo ***REMOVED_API_KEY***
import os
import sys
import json
import re
import time
import textwrap
import colorama
import threading
# 在 main.py 中删除原来的定义，改为导入
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, COMMON_TIMEOUT, MAIN_LOOP_API_KEY, MAIN_LOOP_BASE_URL, MAIN_LOOP_MODEL, MAIN_LOOP_TIMEOUT, CLOUD_MEM_SLOT_ID
from player_manager import Player, get_player, set_player,edit_player_raw, save_player_raw, set_player_field #导入作弊器代码
# ===== 骰子检定系统（最小侵入导入） =====
import dice_system
from dice_system import should_skip as dice_should_skip
from dice_system import resolve_check_v4 as dice_resolve_check_v4, clear_web_state_v4 as dice_clear_web_state_v4
# 在 main.py 文件顶部（其他 import 之后）
from task_manager import create_task, list_tasks, complete_task, delete_task,update_task_progress,set_task_type,get_active_tasks,toggle_task_suspend,get_task_brief_for_ai,get_task_info
from save_manager import save_game, load_game, list_saves, delete_save

from file_utils import save_json, load_json, ensure_dir, load_context_cache, save_context_cache, append_interact_log, rewrite_interact_log
from practice_system import do_practice
from openai import OpenAI
# 导入动态主线模块
from mainline_dynamic import advance_mainline
from location_time import load_location_time, update_location_time, advance_world_time, format_time_with_24h
def get_llm_content(response):
    """从 llm_call_common 返回值中提取文本内容（兼容新旧格式）"""
    if isinstance(response, dict):
        return response.get("content", "")
    return response
# ===== 新增：云记忆向量库模块 =====
# ===== 云记忆向量库模块 =====
from cloud_memory_v2 import (
    upload_plot_memory,
    get_relevant_history,
    MemoryCategory,
    upload_chapter_summary,
    upload_npc_memory,
    upload_task_memory,
    upload_rumor_item,
)
from colorama import init, just_fix_windows_console
# ===== 世界书检索模块（零侵入注入）=====
try:
    import worldbook
    _WORLDBOOK_AVAILABLE = True
except ImportError:
    _WORLDBOOK_AVAILABLE = False

os.environ["TERM"] = "xterm"   # 强制 Linux 终端模式

# ===================== DeepSeek v4-flash 配置 =====================


# ===================== 【配图模块】=====================
from image_generator import draw_ascii
# ===================== 【对战模块 独立导入 零侵入核心】 =====================
from battle_system import run_battle_system, get_last_battle_context, clear_battle_cache

# 全局加一把线程锁
PLOT_PROCESS_LOCK = threading.Lock()
# 第一重保险：强制禁用 Windows 转换引擎（防止调用 win32 API）
colorama.ansi.win32 = None


# 第二重保险：官方跨平台修复（Linux 上会静默跳过）
just_fix_windows_console()

# 第三重保险：初始化时彻底关闭转换和剥离
init(autoreset=True, convert=False, strip=False)



# 全局强制UTF-8，解决中文ASCII编码报错
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")
os.environ["PYTHONIOENCODING"] = "utf-8"



# ===================== 颜色常量 =====================
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
COLOR_PLOT = Color.WHITE
COLOR_NPC = Color.YELLOW
COLOR_PLAYER = Color.GREEN
COLOR_OPTION = Color.BLUE
COLOR_CHANGE = Color.PURPLE
COLOR_WARN = Color.RED
COLOR_END = Color.END
COLOR_GREEN = Color.GREEN
COLOR_YELLOW = Color.YELLOW

# ===== NPC好感→态度标签映射（18档，武侠语境）=====
FAVOR_ATTITUDE_MAP = [
    ( -91, "不共戴天"), ( -76, "死敌"), ( -61, "仇视"), ( -46, "怨恨"),
    ( -31, "厌恶"),     ( -21, "反感"), ( -11, "冷淡"), (  -6, "漠然"),
    (   4, "寻常"),     (  14, "留意"), (  24, "客气"), (  39, "友善"),
    (  54, "亲近"),     (  69, "信赖"), (  79, "知己"), (  89, "挚友"),
    (  99, "莫逆"),
]

def get_favor_attitude(favor: int) -> str:
    for threshold, label in FAVOR_ATTITUDE_MAP:
        if favor <= threshold:
            return label
    return "生死之交"

# ===== 名气数值→武侠称号映射（16档，精细化）=====
REPUTATION_TITLE_MAP = [
    (-5000, "武林公敌"),    (-2000, "臭名昭著"), (-1000, "声名狼藉"),
    ( -500, "为人不齿"),    ( -100, "口碑不佳"),    (   0, "默默无闻"),
    (   50, "籍籍无名"),    (  100, "崭露头角"),    (  200, "初出茅庐"),
    (  500, "小有名气"),    ( 1000, "名动一方"),    ( 2000, "声名鹊起"),
    ( 3500, "威震江湖"),    ( 5000, "一代宗师"),    ( 7500, "武林神话"),
]

def get_reputation_title(reputation: int) -> str:
    """将名气数值映射为精细化的武侠称号"""
    for threshold, label in REPUTATION_TITLE_MAP:
        if reputation <= threshold:
            return label
    return "江湖至尊"


def _top_skills(skill_list, n=4):
    """取exp最高的n门武功，用于AI和web展示"""
    if not skill_list:
        return []
    return sorted(skill_list, key=lambda s: s.get("exp", 0), reverse=True)[:n]

# 【NPC专用超长超时配置，解决大文本提取超时】
NPC_GEN_TIMEOUT = 90
NPC_RETRY_SLEEP = 3
# 超长文本容错：NPC生成单次最大输入字符
MAX_STORY_CHARS_FOR_NPC = 20000
# 分段提取：每一段文本最大长度
CHUNK_SIZE = 500
# 文件路径
STORY_PATH = "story_source.txt"
WORLD_FILE = "data/world_setting.json"
PLAYER_FILE = "data/player.json"
NPC_AGENT_FILE = "data/npc_agents.json"
SAVE_FILE = "data/game_save.json"
CONTEXT_CACHE_FILE = "data/context_cache.json"
MAX_CONTEXT_LOG = 2000
# ===== 云记忆全局槽位ID（从 config.py → .env 读取）======
# CLOUD_MEM_SLOT_ID 已从 config 导入，无需在此硬编码
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
# ---- 【新增】事件触发与进度配置 ----4. 武功经验类：skill_exp_gain（经验分级：战斗厮杀+3~15、日常勤练+1~50、月余苦练+10~100、数年苦修+50~300、顿悟突破+50~300、奇遇机缘自行给出）
PROGRESS_FILE = "data/progress.json"
RANDOM_EVENT_PROBABILITY = 0.02  # 日常行动触发随机意外事件的概率（2%）
PLOT_PROGRESS_PER_ACTION = 0.2   # 每次日常交互推进的剧情进度值
MAJOR_PLOT_TRIGGER_POINT = 20  # 每当进度累计增加 20 点，触发一次原著主线关键节点
STATIC_SYSTEM_PROMPT = """
你是金庸武侠世界的叙事者与登场NPC的扮演者，须根据玩家行动推进剧情。所有回应以本轮上下文传入的世界观、江湖规则、武学设定、任务剧情、门派设定、NPC人设与行为逻辑等全部信息为基准，优先遵循检索到的设定与档案；剧情需要新增角色或展开演绎时，须在已有设定世界框架内自洽生成、不得违背；严禁打破第四面墙。
【核心铁律】
所有输出必须严格遵守以下规则，违反任意一条均视为无效生成。
1.玩家主权：玩家是剧情唯一决策者，NPC基于剧情被动响应，绝对禁止代替玩家说话、做决定、强制推进剧情；单轮只推进一个场景节拍（玩家行动→即时反应→结束），禁止连锁推进多个事件、跳转时间或切换场景。
2.场景连续：必须从「L1即时场景锚点」的最后一句无缝续写，不得跳脱场景、跳转时间、凭空切换人物。
3.叙事文风：采用金庸武侠文风，以人物对话为核心，环境描写精简克制（单处不超过30字），禁止大段写景。
4.工具调用：每轮回复必须调用 update_game_state 工具，严禁省略或在正文输出JSON。
5.任务进度：主线剧情必须与任务进度百分比严格匹配，达到75%时自然收尾本阶段事件。
6.对打演绎：所有打斗、对战、比武、偷袭必须等待玩家指令逐步演绎，不能直接输出完整对战结果。
7.NPC出场：已故NPC绝对禁止主动出场、说话、动作，仅可在对话、回忆、江湖见闻中提及。
8.武功检定：当输入中包含【!系统检定·必须遵循!】区块时，剧情走向必须严格服从8档检定结论。档位对应成功程度：完美碾压→超凡表现远超极限附带巨大收益；超常发挥→超过平时水准附带收益；正常发挥→符合预期顺利达成；差强人意→虽不精彩但目标达成无额外收益；功亏一篑→差一线但主要目标失败；拙于应对→应对失当招式生涩失败；力屈受挫→力有不逮遭受重挫身受中等伤害；惨败而归→差距悬殊身受重创衍生恶果。natural=20在原基础上提升2档发挥，natural=1在原基础上降低2档发挥。绝对不得违背检定结论。叙事必须体现武功境界差异，但禁止出现"骰子""DC""检定""档位""差值""d20"等游戏术语。

【输出格式】
【本轮剧情内容】（250字以内）
【NPC状态变动】格式：角色名：好感±X / 无变化
【道具/自身健康状态】综合修为：武功名 等级 / ... / 新增武功：XX / 新增道具：XX 消耗道具：XX
【时间变更】时辰名（仅耗时动作标注）
【地点变更】新地点（仅移动时标注）
【行动选项】格式：选项1 / 选项2 / 选项3（每个10字以内）
可选：【近期剧情记录】一句话本轮关键事件
可选：【任务进度】格式：任务编号/任务名 → 进度XX%，当前阶段：描述


【工具调用规则】
1. 基础规则：每轮必须主动调用 update_game_state，根据剧情输出数值，数值变化必须与剧情对应。
2. 玩家属性类：reputation_delta（根据玩家剧情，江湖声望名气变化，单次-5~+5，重大事件-50~+50）。
3. 世界状态类：world_trend（江湖大势30字内）、faction_balance（本轮NPC记忆，每条格式：姓名|记忆内容，30字内，可多条）、mood（情绪）、new_rumor（玩家主线剧情原子记录30字内，NPC有可能知道）。
4. 武功经验类：skill_exp_gain（武学经验增长时填写，按照日常勤练、战斗厮杀、月余苦练、数年苦修、顿悟突破、奇遇机缘等不同场景分别给出合理数值）、skill_exp_update（感悟更新）、bottleneck_progress_delta（瓶颈增量）。
5. 任务进度类：task（任务进展，name优先传完整任务名，单轮涨幅≤5%）。
6. 武功学习类：new_skills（习得新武功时填写）。
7. NPC状态类：npc_status_update（状态变化时填写）、npc_favor_update（好感实质变化时填写，单次±1~±8；施恩/契合性格则增，冒犯/违背立场则减，闲聊不触发）、npc_relationship_update（关系标签4字内）。
8. 主角状态类：self_state（身体/精神状态变化时填写，30字内）。
9. 小说节点类：novel_node（必须以“YYYY年M季，”开头，如“1751年春，萧半和寿宴在即”；无变化时填空字符串）。

【武学境界体系】14档分级（每档战力约1.5倍递增，☆为瓶颈境，需积累突破）
1.初学入门 2.初窥门径☆
3.略有小成 4.略有所成☆
5.渐入佳境 6.融会贯通☆
7.登堂入室 8.炉火纯青☆
9.出神入化 10.登峰造极☆
11.超凡入圣 12.返璞归真☆
13.天人合一 14.破碎虚空

实力七层参照（DC为对手对应基础DC，按金庸十四部小说整体标准判定，"掌门"是门内地位非江湖地位）：
■ 入门层(1-2档|DC7-9)：江湖新丁、外门弟子、庄客、非武人(如韦小宝/程灵素武功)。修炼0-3年。能对付寻常壮汉，不敌兵卒。
■ 小成层(3-4档|DC11-13)：内门弟子、镖师、小头目、权臣非武人(如福康安)。修炼3-8年。可独走江湖，不敌成名人物。
■ 中坚层(5-6档|DC15-17)：精英弟子、总镖头、香主、地方小派掌门(八仙剑蓝秦/八极门秦耐之/五湖门桑飞虹/中抓门哈赤)。修炼8-20年。一方好手，与一流高手差距明显。
■ 一流层(7-8档|DC19-21)：名门长老、邪派堂主、中等门派掌门(天龙门田归农/五虎门凤天南/八卦门分支商剑鸣)、名门掌门(胡家胡一刀/苗家苗人凤/红花会陈家洛/晋阳萧半和/少林方丈/武当掌门)。修炼20-40年。可开宗立派，寻常围攻不足为惧。本四书(飞狐/雪山/书剑/连城诀/鸳鸯刀)天花板。
■ 绝顶层(9-10档|DC23-25)：邪教教主、大内供奉、神功大成者(连城诀狄云/丁典神照功)。修炼40-70年或天赋异禀。威震一方。对标高武世界(射雕/神雕/倚天/笑傲)的五绝/郭靖/张无忌。
■ 宗师层(11-12档|DC27-28)：隐世高人、武林神话(东方不败/风清扬/石破天太玄经)。百年难遇，需天赋+奇遇+机缘。超凡脱俗。
■ 传说层(13-14档|DC29-30)：三丰真人、扫地僧、达摩祖师之流。千古难遇，近乎神话。与天地共鸣，非凡人可敌。

【附属规则】
- 主线任务仅在玩家做出实质推进时更新进度，日常对话保持不变；支线仅自然涉及相关剧情时更新。
- NPC人物对话需贴合身份、性格、状态和好感度以及玩家声望，口语化符合江湖语境。*重要*NPC除非是事件当事人，否则只能通过江湖见闻了解玩家信息。
- 除非特殊剧情安排、NPC自身阅历身份特性，或者玩家主动说出，一般情况下，NPC是无法认出玩家武功路数和武功名称。
- 无特殊事件时，剧情以日常对话、细节互动为主，不强行制造冲突。
"""

# ===================== 【新增：每轮重复打印标题与指令】 =====================
def print_game_header():
    print(f"\n{COLOR_SYSTEM}==================== V4-Flash 版 小说自由交互剧情游戏 ===================={COLOR_END}")
    print(f"{COLOR_SYSTEM}【核心规则：玩家全权决策，“（）”代表旁边，AI仅负责叙事、NPC扮演、场景推进】{COLOR_END}")
    print(f"{COLOR_SYSTEM}【快捷指令】等级·功法·物品·传闻·配图·查看时空/ 任务·查询历史·看看江湖见闻·回归主线·主线完成/ 对战·练功 / 遗忘功法·扔掉物品/ 设置NPC状态 · 治愈NPC / 存档管理·exit {COLOR_END}")
# ===================== 工具函数 =====================
def find_archive_for_round(target_round):
    """根据轮次查找对应的归档文件路径"""
    archive_dir = "data/history_archive"
    if not os.path.exists(archive_dir):
        return None
    
    # 计算该轮次所在的归档区间（每100轮一个文件）
    start_round = ((target_round - 1) // 100) * 100 + 1
    end_round = start_round + 99
    archive_name = f"archive_{start_round:05d}-{end_round:05d}.json"
    archive_path = os.path.join(archive_dir, archive_name)
    
    if os.path.exists(archive_path):
        return archive_path
    return None


def load_archive_summary(archive_path):
    """加载归档文件，返回摘要内容"""
    try:
        with open(archive_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"{COLOR_WARN}读取归档失败：{e}{COLOR_END}")
        return None


def query_history(round_num):
    """查询指定轮次的历史记录"""
    if round_num < 1:
        print(f"{COLOR_WARN}轮次必须大于0{COLOR_END}")
        return
    
    archive_path = find_archive_for_round(round_num)
    if not archive_path:
        print(f"{COLOR_WARN}未找到第 {round_num} 轮的历史归档（可能尚未归档，需达到100轮后）{COLOR_END}")
        return
    
    data = load_archive_summary(archive_path)
    if not data:
        return
    
    # 显示归档信息
    print(f"\n{COLOR_SYSTEM}========== 历史档案：{data.get('round_range', '')} =========={COLOR_END}")
    
    # 显示章节摘要
    chapter = data.get("chapter_summary", {})
    if chapter:
        print(f"{COLOR_PLOT}【章节摘要】{COLOR_END}")
        print(f"{COLOR_PLOT}{chapter.get('summary', '无摘要')[:300]}...{COLOR_END}")
    
    # 显示大事记
    milestones = data.get("milestones", [])
    if milestones:
        print(f"\n{COLOR_YELLOW}【大事记】{COLOR_END}")
        for m in milestones[:10]:
            print(f"{COLOR_YELLOW}  - {m}{COLOR_END}")
    
    # 显示传记状态
    bio = data.get("biography", {})
    if bio:
        print(f"\n{COLOR_GREEN}【人物状态】{COLOR_END}")
        protagonist = bio.get("protagonist", {})
        if protagonist:
            print(f"{COLOR_GREEN}  姓名：{protagonist.get('name', '未知')}{COLOR_END}")
            print(f"{COLOR_GREEN}  身份：{protagonist.get('identity', '未知')}{COLOR_END}")
            allies = protagonist.get("allies", [])
            if allies:
                print(f"{COLOR_GREEN}  盟友：{', '.join(allies)}{COLOR_END}")
            enemies = protagonist.get("enemies", [])
            if enemies:
                print(f"{COLOR_GREEN}  敌人：{', '.join(enemies)}{COLOR_END}")
    
    # 显示最近的对话（可选）
    logs = data.get("interact_log", [])
    if logs:
        print(f"\n{COLOR_PLOT}【最近对话片段】（共{len(logs)}条）{COLOR_END}")
        for log in logs[-3:]:  # 只显示最后3条
            print(f"{COLOR_PLOT}  {log[:150]}...{COLOR_END}")
def cleanup_archives(archive_dir, max_keep=100):
    """
    清理归档目录，只保留最新的 max_keep 个归档文件。
    文件名格式：archive_00001-00100.json，按字典序排序即可对应轮次顺序。
    """
    if not os.path.exists(archive_dir):
        return
    
    # 获取所有归档文件
    files = [f for f in os.listdir(archive_dir) 
             if f.startswith("archive_") and f.endswith(".json")]
    
    if len(files) <= max_keep:
        return
    
    # 按文件名排序（字典序自然对应轮次顺序）
    files.sort()
    
    # 删除最旧的文件（前 len(files)-max_keep 个）
    to_delete = files[:len(files)-max_keep]
    for fname in to_delete:
        path = os.path.join(archive_dir, fname)
        try:
            os.remove(path)
            print(f"{COLOR_SYSTEM}🗑️ 已删除过期归档：{fname}{COLOR_END}")
        except Exception as e:
            print(f"{COLOR_WARN}删除归档失败 {fname}: {e}{COLOR_END}")
#  【新增】进度轴与随机事件模块 
def init_progress():
    if os.path.exists(PROGRESS_FILE):
        prog = load_json(PROGRESS_FILE)
        # 如果读出来的不是字典，证明文件损坏，忽略它继续新建
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
    prog = init_progress()
    prog["current_progress"] += delta
    # 动态计算下一次触发阈值（每1000轮增加5）
    # 注意：我们读取当前轮次，但 update_progress 不知道当前轮次，可以从 progress.json 中的 current_progress 推算，但更准确的是从 context_cache 中获取轮次。
    # 为了简化，我们可以在 game_core_loop 中传递 new_round，但这里先使用简单方法：每次触发后，阈值增加固定值，这个固定值可以随轮次增长。
    # 但更好的方法是：每次触发时，根据当前已触发的次数或轮次，动态增加下一次阈值。
    # 我们可以在 progress.json 中增加一个字段 "trigger_count" 来记录已触发次数，每次触发时增加 5。
    if prog["current_progress"] >= prog["trigger_threshold"]:
        # 动态增加下一次阈值：基础值 20 + 已触发次数 * 5
        trigger_count = prog.get("trigger_count", 0) + 1
        prog["trigger_threshold"] = 20 + trigger_count * 5
        prog["trigger_count"] = trigger_count
        prog["flags"].append("trigger_mainline")
    save_json(PROGRESS_FILE, prog)
    return prog

def check_and_consume_mainline_flag():
    prog = init_progress()
    if "trigger_mainline" in prog["flags"]:
        prog["flags"].remove("trigger_mainline")
        save_json(PROGRESS_FILE, prog)
        return True
    return False
def read_raw_story():
    if not os.path.exists(STORY_PATH):
        print(f"{COLOR_WARN}【提示】本地无 story_source.txt 原著文件，将由AI生成基础通用设定{COLOR_END}")
        return ""
    try:
        with open(STORY_PATH, "r", encoding="utf-8") as f:
            local_story_content = f.read().strip()
        print(f"{COLOR_SYSTEM}✅ 优先加载本地 story_source.txt 作为NPC/世界观核心数据源{COLOR_END}")
        return local_story_content
    except Exception as e:
        print(f"{COLOR_WARN}【警告】读取 story_source.txt 失败: {e}，将使用AI生成设定{COLOR_END}")
        return ""
def extract_plot_npc_names(plot_text: str, full_npc_data) -> list:
    if not plot_text or not full_npc_data or "npc_list" not in full_npc_data:
        return []
    # 取出数据库全部NPC名称
    db_all_names = [npc["name"].strip() for npc in full_npc_data["npc_list"]]
    db_name_str = "、".join(db_all_names)
    prompt = f"""
你是NPC筛选助手，任务：
1. 已知数据库所有NPC名称列表：{db_name_str}
2. 给定一段武侠剧情文本：{plot_text}
3. 只筛选：同时【在名称列表里】AND【剧情中实际出场对话/出现】的NPC名字
4. 规则：
   - 只输出纯JSON数组，无任何文字、注释、markdown
   - 无符合NPC返回空数组[]
输出示例：["张三","李四"]
"""
    # 调用通用LLM过滤
    raw_res = get_llm_content(llm_call_common(prompt, "筛选剧情内数据库存在NPC", temp=0.2))
    clean_txt = clean_json(raw_res)
    try:
        res_list = json.loads(clean_txt)
        # 校验只保留字符串名称
        valid = [x.strip() for x in res_list if isinstance(x, str) and x.strip() in db_all_names]
        return list(set(valid))
    except Exception as e:
        # AI解析失败兜底：空列表
        print(f"{COLOR_WARN}⚠️ NPC名字解析失败: {e}{COLOR_END}")
        return []
def clean_json(raw: str) -> str:
    if not raw:
        return ""
    raw = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", raw).strip()
    
    extracted = ""
    # 尝试提取大括号或中括号
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start_idx = raw.find(start_char)
        if start_idx != -1:
            count = 0
            end_idx = -1
            for i, ch in enumerate(raw[start_idx:], start=start_idx):
                if ch == start_char:
                    count += 1
                elif ch == end_char:
                    count -= 1
                    if count == 0:
                        end_idx = i + 1
                        break
            if end_idx != -1:
                extracted = raw[start_idx:end_idx]
            else:
                # ★ 未闭合：返回从起始到末尾的内容
                extracted = raw[start_idx:]
            break
    if not extracted:
        return ""
    
    # 清洗...
    json_str = extracted
    json_str = json_str.replace('“', '"').replace('”', '"')
    json_str = json_str.replace('‘', '"').replace('’', '"')
    json_str = re.sub(r'[\x00-\x1f\x7f]', '', json_str)
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    
    # 尝试解析
    try:
        json.loads(json_str)
        return json_str
    except json.JSONDecodeError:
        # 尝试 ast.literal_eval
        try:
            import ast
            obj = ast.literal_eval(json_str)
            return json.dumps(obj, ensure_ascii=False)
        except Exception as e:
            # 返回提取的内容（即使不完整）
            print(f"{COLOR_WARN}⚠️ JSON修复失败: {e}{COLOR_END}")
            return json_str

# 通用LLM调用（优化：阶梯重试+文本清洗+彻底兜底，API挂掉也必有剧情输出）
def llm_call_common(sys_prompt: str, user_prompt: str, temp=0.65, retry_times=3, stream=False, tools=None, tool_choice="auto", max_tokens=1000, timeout=None, api_key=None, base_url=None, model=None):
    """
    通用LLM调用，支持工具调用。
    返回一个字典: {"content": str, "tool_calls": list} 或仅字符串（当 stream=True 时）
    """
    def clean_text_block(text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    clean_sys = clean_text_block(sys_prompt)
    clean_user = clean_text_block(user_prompt)
    delay_base = 1.2
    # 确定实际的 timeout 值
    actual_timeout = timeout if timeout is not None else COMMON_TIMEOUT
    print(f"{COLOR_SYSTEM}⏳ 正在向AI请求剧情...{COLOR_END}")

    for i in range(retry_times + 1):
        # 新增：第2次重试起自动裁剪上下文，越重试越短，成功率越高
        if i >= 1:
            clean_sys = textwrap.shorten(clean_sys, width=1500, placeholder="...")
            clean_user = textwrap.shorten(clean_user, width=2000, placeholder="...")
        if i >= 2:
            clean_sys = textwrap.shorten(clean_sys, width=800, placeholder="...")
            clean_user = textwrap.shorten(clean_user, width=1200, placeholder="...")
        try:
            # 构建请求参数
            kwargs = {
                "model": model if model else DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": clean_sys},
                    {"role": "user", "content": clean_user}
                ],
                "temperature": temp,
                "max_tokens": max_tokens, 
                "top_p": 1.0,
                "stream": stream,
                "timeout": actual_timeout
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice
                print(f"[DEBUG 工具调用] 已注入tools，tool_choice = {tool_choice}")
            # 显式关闭思考模式：保证 temperature/top_p 生效，提升小说创作自然度、降低成本、加速推理
            # max_tokens 与 max_completion_tokens 互斥：MiMo 用后者，DeepSeek 用前者，同时发会触发 400
            _is_mimo = "mimo" in (model or DEEPSEEK_MODEL).lower()
            if _is_mimo:
                kwargs.pop("max_tokens", None)
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}, "max_completion_tokens": max_tokens}
            else:
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            _client = OpenAI(api_key=api_key, base_url=base_url) if (api_key and base_url) else client

            # ===== DEBUG 诊断日志（LLM_DEBUG=1 开启）=====
            if os.getenv("LLM_DEBUG", "0") == "1":
                _api_masked = ((api_key or "")[:8] + "…") if api_key else "(默认DeepSeek)"
                _bu = base_url or "(默认DeepSeek)"
                print(f"[DEBUG-REQ] model={model or DEEPSEEK_MODEL} base_url={_bu} key={_api_masked}")
                print(f"[DEBUG-REQ] max_tokens={max_tokens} temp={temp} stream={stream} extra_body={kwargs['extra_body']}")
                if tools:
                    print(f"[DEBUG-REQ] tools={len(tools)}个 tool_choice={tool_choice}")
                    for _t in tools:
                        print(f"  └─ {_t.get('function',{}).get('name','?')}")

            resp = _client.chat.completions.create(**kwargs)

            # ===== DEBUG 响应诊断 =====
            if os.getenv("LLM_DEBUG", "0") == "1":
                _ch = resp.choices[0]
                _msg = _ch.message
                _c_len = len(_msg.content or "")
                _r = getattr(_msg, 'reasoning_content', None) or ""
                _r_len = len(_r)
                _tc = getattr(_msg, 'tool_calls', None)
                _tc_n = len(_tc) if _tc else 0
                _fin = getattr(_ch, 'finish_reason', 'N/A')
                print(f"[DEBUG-RESP] finish_reason={_fin} content={_c_len}字 reasoning={_r_len}字 tool_calls={_tc_n}个")
                _u = getattr(resp, 'usage', None)
                if _u:
                    print(f"[DEBUG-USAGE] prompt={getattr(_u,'prompt_tokens',0)} completion={getattr(_u,'completion_tokens',0)} cache_hit={getattr(_u,'prompt_cache_hit_tokens',0)}")
                    # 尝试读取 reasoning_tokens（嵌套字段）
                    _ctd = getattr(_u, 'completion_tokens_details', None)
                    if _ctd:
                        _rt = getattr(_ctd, 'reasoning_tokens', None)
                        if _rt is not None:
                            print(f"[DEBUG-USAGE] reasoning_tokens={_rt} ← {'思考模式开启!' if _rt > 0 else '思考模式已关闭'}")
                if _r_len > 0:
                    print(f"[DEBUG-WARN] reasoning_content 非空({_r_len}字)，思考模式可能未关闭！前200字: {_r[:200]}")
                if _tc_n > 0 and _c_len == 0:
                    _tc0 = _tc[0] if _tc else None
                    _tc_name = getattr(getattr(_tc0, 'function', None), 'name', '?') if _tc0 else '?'
                    print(f"[DEBUG-WARN] 仅返回tool_calls无文本！第一个tool={_tc_name}")
                if _c_len == 0 and _r_len == 0 and _tc_n == 0:
                    print(f"[DEBUG-ERROR] content/reasoning/tool_calls 全部为空！原始响应: {resp.model_dump_json()[:500]}")

            # ===== 缓存命中监测（DeepSeek Prompt Caching）=====
            # 官方直连：prompt_cache_hit_tokens 反映 system 前缀命中情况（命中部分0.1元/M）
            # 第三方代理（数眼等）：可能不返回此字段，此时无法统计命中率
            try:
                _usage = getattr(resp, 'usage', None)
                if _usage:
                    _hit = getattr(_usage, 'prompt_cache_hit_tokens', 0) or 0
                    _miss = getattr(_usage, 'prompt_cache_miss_tokens', 0) or 0
                    _prompt_tokens = getattr(_usage, 'prompt_tokens', 0) or 0
                    _total_in = _hit + _miss
                    if _total_in > 0:
                        _rate = _hit / _total_in * 100
                        print(f"{COLOR_SYSTEM}[缓存] 命中={_hit} 未命中={_miss} 命中率={_rate:.1f}% (输入{_prompt_tokens}tokens){COLOR_END}")
                    elif _prompt_tokens > 0:
                        print(f"{COLOR_SYSTEM}[缓存] 输入={_prompt_tokens}tokens，该端点未返回缓存命中字段（无法统计命中率）{COLOR_END}")
            except Exception:
                pass

            if stream:
                # 流式模式暂不支持工具调用（通常不会用流式+工具），保持原有逻辑
                print(f"\n{COLOR_PLOT}【本轮剧情内容】{COLOR_END}", end="", flush=True)
                print(COLOR_PLOT, end="", flush=True)
                full_text = ""
                for chunk in resp:
                    # 安全检查：delta.content 可能为 None
                    delta = getattr(chunk.choices[0].delta, 'content', None)
                    if delta:
                        if '【世界状态更新】' in full_text:
                            pass
                        else:
                            if '【世界状态更新】' in delta:
                                before_json = delta.split('【世界状态更新】')[0]
                                print(before_json, end="", flush=True)
                            else:
                                print(delta, end="", flush=True)
                        full_text += delta
                print(COLOR_END, flush=True)
                print()
                return {"content": full_text, "tool_calls": None}

            else:
                # 非流式：可能返回工具调用
                choice = resp.choices[0]
                content = choice.message.content or ""
                tool_calls = choice.message.tool_calls if hasattr(choice.message, 'tool_calls') else None
                if content and content.strip():
                    return {"content": content.strip(), "tool_calls": tool_calls}
                elif tool_calls:
                    # ★ 方案A：模型只返回tool_calls无文字（MiMo/GPT等标准函数调用行为）
                    # 去掉tools做第二轮调用获取剧情文字，DeepSeek不会走到这里
                    print(f"{COLOR_WARN}[MiMo兜底] 第一轮仅返回tool_calls({len(tool_calls)}个)，正在补充调用获取文字...{COLOR_END}")
                    _kwargs2 = dict(kwargs)
                    _kwargs2.pop("tools", None)
                    _kwargs2.pop("tool_choice", None)
                    # ★ 注入第一轮 tool_calls 摘要到第二轮 user_prompt，确保文字与状态判定一致
                    _state_summary = format_tool_calls_summary(tool_calls)
                    if _state_summary:
                        _orig_msgs = _kwargs2["messages"]
                        _new_msgs = list(_orig_msgs)
                        _new_msgs[-1] = dict(_orig_msgs[-1])
                        _new_msgs[-1]["content"] = _orig_msgs[-1]["content"] + "\n\n" + _state_summary
                        _kwargs2["messages"] = _new_msgs
                        print(f"{COLOR_WARN}[MiMo兜底] 已注入状态判定摘要({len(_state_summary)}字符)到第二轮prompt{COLOR_END}")
                    try:
                        resp2 = _client.chat.completions.create(**_kwargs2)
                        _ch2 = resp2.choices[0]
                        _content2 = _ch2.message.content or ""
                        if not _content2:
                            # 第二轮content也为空，尝试reasoning_content兜底
                            _reasoning2 = getattr(_ch2.message, 'reasoning_content', None) or ""
                            if _reasoning2:
                                print(f"{COLOR_WARN}[MiMo兜底] 第二轮content仍为空，提取reasoning_content({len(_reasoning2)}字符){COLOR_END}")
                                _content2 = _reasoning2
                        if _content2:
                            return {"content": _content2.strip(), "tool_calls": tool_calls}
                        # 第二轮也空，返回空content但保留tool_calls（至少保住游戏状态更新）
                        print(f"{COLOR_WARN}[MiMo兜底] 第二轮仍无文字，返回空content+tool_calls{COLOR_END}")
                        return {"content": "", "tool_calls": tool_calls}
                    except Exception as e2:
                        print(f"{COLOR_WARN}[MiMo兜底] 第二轮调用失败({e2})，返回空content+tool_calls{COLOR_END}")
                        return {"content": "", "tool_calls": tool_calls}
                else:
                    # ★ 兜底：思考模式未关闭时，提取 reasoning_content（与 llm_call_npc_gen 一致）
                    reasoning = getattr(choice.message, 'reasoning_content', None) or ""
                    if reasoning:
                        print(f"{COLOR_WARN}[主循环思考模式兜底] content为空，提取reasoning_content({len(reasoning)}字符){COLOR_END}")
                        return {"content": reasoning.strip(), "tool_calls": None}
                    raise Exception("模型返回空内容且无工具调用")

        except Exception as e:
            err_msg = str(e).lower()
            # 修改后
            if "429" in err_msg or "rate limit" in err_msg:
                wait_sec = 3 * (2 ** i)  # 限流场景退避更长，避免触发更严封禁
            else:
                wait_sec = delay_base * (2 ** i)
            if "timeout" in err_msg or "timed out" in err_msg:
                err_type = "请求超时"
            elif "429" in err_msg or "rate limit" in err_msg:
                err_type = "接口限流"
            else:
                err_type = "服务异常"
            if i < retry_times:
                print(f"{COLOR_WARN}【{model or DEEPSEEK_MODEL} {err_type}】{str(e)[:200]} | 等待{wait_sec:.1f}秒，第{i+1}次重试...{COLOR_END}")
                time.sleep(wait_sec)
                if i + 1 == retry_times:
                    clean_sys = textwrap.shorten(clean_sys, width=1200, placeholder="...")
            else:
                print(f"{COLOR_WARN}【{model or DEEPSEEK_MODEL} {err_type}】全部重试耗尽，启用本地兜底剧情{COLOR_END}")
                fallback = f"""【本轮剧情内容】你{user_prompt.strip()}，周遭一片安静，暂无特殊人与变故。
                【NPC状态变动】无
                【道具/自身健康状态】无"""
                if stream:
                    print(f"\n{COLOR_PLOT}【本轮剧情内容】{COLOR_END}", end="", flush=True)
                    print(f"{COLOR_PLOT}{user_prompt.strip()}，周遭一片安静，暂无特殊人与变故。{COLOR_END}")
                return {"content": fallback, "tool_calls": None}
    return {"content": "", "tool_calls": None}

# 【NPC专属LLM调用：独立超长超时+更长重试间隔，专门解决大文本提取超时】
def llm_call_npc_gen(sys_prompt: str, user_prompt: str, temp=0.5, retry_times=2):
    for i in range(retry_times + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temp,
                stream=False,
                timeout=NPC_GEN_TIMEOUT,
                extra_body={"thinking": {"type": "disabled"}}
            )
            # 安全检查：message.content 可能为 None
            _msg = resp.choices[0].message
            content = getattr(_msg, 'content', '') or ''
            result = content.strip()
            if not result:
                # ★ 兜底：思考模式未关闭时，提取 reasoning_content
                reasoning = getattr(_msg, 'reasoning_content', None) or ""
                if reasoning:
                    print(f"{COLOR_WARN}[NPC思考模式兜底] content为空，提取reasoning_content({len(reasoning)}字符){COLOR_END}")
                    return reasoning.strip()
                raise Exception("API返回空内容")
            return result
        except Exception as e:
            if i < retry_times:
                print(f"{COLOR_WARN}【NPC生成请求超时/异常】等待{NPC_RETRY_SLEEP}秒，第{i+1}次重试...{COLOR_END}")
                time.sleep(NPC_RETRY_SLEEP)
                continue
            else:
                print(f"{COLOR_WARN}【NPC生成最终请求失败】{e}{COLOR_END}")
                print(f"{COLOR_SYSTEM}【系统兜底】使用空白NPC模板{COLOR_END}")
                return ""
    return ""

# ===================== 上下文缓存（基础函数） =====================
def init_context_cache():
    # 1. 尝试加载已有缓存
    if os.path.exists(CONTEXT_CACHE_FILE):
        cache = load_context_cache()
        if cache and isinstance(cache, dict):
            # ★★★ 关键修复：兼容旧存档，自动补充缺失的新字段 ★★★
            if "chapter_summaries" not in cache:
                cache["chapter_summaries"] = []
            if "biography" not in cache:
                cache["biography"] = {
                    "protagonist": {
                        "name": "",
                        "identity": "",
                        "core_ability": "",
                        "allies": [],
                        "enemies": [],
                        "reputation": 0
                    },
                    "world_state": {}
                }
            if "milestones" not in cache:
                cache["milestones"] = []
            # 新增：全量摘要字段
            if "full_plot_summary" not in cache:
                cache["full_plot_summary"] = "故事初始，暂无完整脉络"
            return cache

    # 2. 如果文件不存在或无效，创建全新的默认缓存
    cache = {
        "last_plot_summary": "故事初始，暂无前置剧情",
        "interact_log": [],
        "round": 0,                    # 独立轮次计数器（解决封顶冻结bug）
        "last_appended_round": 0,      # 防重复追加基准
        "full_plot_history": "",
        "key_anchors": [],
        "current_goal": "江湖初探，寻找自己的立足之路",
        "chapter_summaries": [],          # L2
        "biography": {                    # L3
            "protagonist": {
                "name": "",
                "identity": "",
                "core_ability": "",
                "allies": [],
                "enemies": [],
                "reputation": 0
            },
            "world_state": {}
        },
        "milestones": [],                 # L4
        "full_plot_summary": "故事初始，暂无完整脉络",  # 新增全量摘要
        # 新增：L2/L3 生成轮次标记，防重复触发
        "last_l2_gen_round": 0,
        "last_l3_gen_round": 0
    }
    save_context_cache(cache)
    return cache

def refresh_context_cache():
    with _context_cache_lock:
        data = load_context_cache()
        if data and isinstance(data, dict):
            return data
        # 初始化也在锁内执行，保证首次创建文件的原子性
        return init_context_cache()
# ===== 主角动作正则（以"你"开头的关键行为句） =====
PROTAGONIST_PATTERNS = [
    # 战斗-攻击
    r'你(?:击败|战胜|斩杀|击退|打退|制服|擒住|打伤|重创|击杀|杀掉|杀死|刺中|刺伤|砍伤|砍中|打翻|打倒|战败|击倒|劈倒|一剑刺|一刀砍|一掌拍|掌心一吐).+?。',
    # 战斗-格挡/闪避
    r'你(?:举剑格挡|横剑架住|侧身避开|闪身躲过|翻身避过|旋身让过|挥袖荡开|提剑封住|运劲架开).+?。',
    # 战斗-招式/内力
    r'你(?:施展|使出|运转|催动|运起|提起|凝聚)(?:内力|真气|功法|真气于|内力于|剑招|掌法|拳法|步法|轻功).+?。',
    r'你(?:拔剑|出剑|挥剑|出掌|劈掌|收剑|出拳|提气|沉气|运气|吐纳|运劲|提剑|拔刀|出鞘).+?。',
    # 战斗-连招/对决
    r'你(?:\S{1,2}剑\S{1,2}招|\S{1,2}剑齐出|连环\S{1,2}剑|连刺\S{1,2}剑|一口气\S{1,2}剑|使出\S{1,2}式|连出|连拍|连劈|快攻|猛攻|疾攻).+?。',
    # 移动
    r'你(?:前往|抵达|进入|离开|走出|踏上|返回|下山|上山|连夜|赶往|直奔|一路|赶到|来到|走至|行至|奔至|掠至).+?。',
    r'你(?:施展轻功|纵身|飞身|翻身|跃起|跃下|跳下|翻墙|掠出|飘身|破窗|穿窗|踏过|飘然).+?。',
    # 隐身/潜行
    r'你(?:藏身|隐蔽|潜伏|埋伏|躲入|闪入|藏进|隐入|匿于|藏在|躲在|侧身藏).+?。',
    r'你(?:窃听|偷听|暗中观察|悄悄跟|蹑手蹑脚|屏息|屏住呼吸).+?。',
    # 学武/修炼/突破
    r'你(?:习得|学会|练成|悟出|领会|默记|记下|牢记|参透|悟透|悟出|领悟|豁然|顿悟|融会贯通|突破|晋升|贯通|大成|出关|闭关).+?。',
    r'你(?:盘膝|打坐|运功|练功|修炼|苦练|习练|演练|比划|揣摩|钻研).+?。',
    # 传授/教导
    r'你(?:传授|教导|指点|点化|教授|教会|示范|演示|指教|点拨|讲解).+?。',
    # 人际关系
    r'你(?:结拜|成婚|拜师|收徒|决裂|和解|告别|重逢|结盟|相认|结识|结交|引见|引荐|拜见|求见).+?。',
    r'你(?:下跪|跪地|跪下|叩首|磕头|抱拳|躬身|作揖|还礼|回礼|施礼|行礼).+?。',
    # 对话-告知/交涉
    r'你(?:告诉|告知|说出|透露|问出|承认|坦白|坦言|吐露|娓娓道|缓缓道|轻声道|低声道|沉声道).+?。',
    r'你(?:喝令|喝道|喝止|喝住|呵斥|怒斥|斥责|责问|质问|逼问|追问|盘问).+?。',
    r'你(?:劝说|劝道|劝住|劝止|劝解|开解|安抚|安慰|慰藉|鼓励|勉励).+?。',
    r'你(?:许诺|答应|应承|应允|承诺|发誓|保证|担保|应声|应道|点头应).+?。',
    r'你(?:威胁|警告|警示|提醒|告诫|叮嘱|嘱咐|叮咛).+?。',
    r'你(?:提议|建议|提出|主张|要求|请求|恳求|恳请|央求).+?。',
    # 抉择
    r'你(?:拒绝|答应|接受|选择|决定|喝止|阻拦|阻止|制止|拦住|挡住|拉住|拖住).+?。',
    r'你(?:犹豫|迟疑|踌躇|权衡|考虑了|思虑|思量后|最终决定|下定决心|咬咬牙).+?。',
    # 获得/接收/给予
    r'你(?:获得|拿到|找到|发现|收到|接过|掏出|取出|拾起|捡到|拾获|得手|到手).+?。',
    r'你(?:递给|交予|递给|送给|赠与|赠予|送给|交给|递给|塞给|掷给|抛给).+?。',
    r'你(?:放下|置下|搁下|丢下|扔下|抛下|掷出|扔出|抛出|甩出|射出|弹指射).+?。',
    # 穿戴/使用
    r'你(?:穿上|披上|脱下|解下|戴上|挂上|系上|别上|揣入|纳入|包好|裹好).+?。',
    # 观察/感知
    r'你(?:看见|望见|瞧见|瞅见|瞥见|发现|察觉|感知|感到|觉得|感觉|嗅到|闻到).+?。',
    r'你(?:侧耳|倾耳|仔细听|竖耳|凝神听|静静听|听得|闻得|听到|听见).+?。',
    # 救援/保护
    r'你(?:救下|救出|救了|搭救|相救|营救|解救|救护|护住|护在|挡在|拦在).+?。',
    # 饮食/休整
    r'你(?:饮酒|喝酒|喝下|饮下|吃下|吞下|咽下|灌下|一饮而尽|举杯).+?。',
    r'你(?:躺下|坐下|歇下|休息|入睡|阖眼|闭目|躺倒|靠坐).+?。',
    # 书写/标记
    r'你(?:写下|写上|记下|画下|划下|刻下|留下字|留书|留信|密信|书信).+?。',
]
# 简单关键词列表（供上传门控使用）
KEY_ACTION_WORDS = [
    "击败","战胜","斩杀","击退","制服","打伤","重创",
    "获得","找到","发现","收到","接过","掏出",
    "习得","学会","练成","悟出","突破","晋升","贯通","大成",
    "前往","抵达","进入","离开","返回","下山","上山",
    "结拜","成婚","拜师","收徒","决裂","和解","告别","重逢","结盟",
    "拒绝","答应","接受","选择","决定","喝止","阻拦",
    "告诉","告知","透露","承认",
    "施展","使出","运转","催动",
    "拔剑","出剑","挥剑","出掌",
]

# ===== 里程碑否定词：排除未发生/假设/心理描写的语句 =====
MILESTONE_DENY_WORDS = [
    "听说", "传言", "据说", "仿佛", "好似", "以为", "传闻", "回忆", "梦中", "如果", "倘若",
    "正要", "打算", "准备", "思量", "暗想", "心想", "盘算", "犹豫", "或许", "也许", "不如",
    "若是", "若", "便想", "便打算",
]

# ===== 占位符过滤 =====
PLACEHOLDER_PATTERNS = [
    "四周静悄悄的，暂无动静", "周遭一片安静", "暂无特殊人与变故", "暂无动静",
    "天色渐晚", "夜色渐深", "次日清晨", "一夜无话", "各自散去", "暂且无话",
    "你（你", "你你喃喃导", "一路上倒也平静", "便也不再多言", "暂且按下不表",
]

# ===== 背景知识/心理活动过滤 =====
BACKGROUND_STARTS = [
    "原著中", "你算了算日子", "你回忆起", "你你",
    "你心中暗", "你暗自", "你默念", "你心想",
]
# ===== add_milestone 先定义 =====
def add_milestone(cache, text):
    if "milestones" not in cache:
        cache["milestones"] = []
    if text not in cache["milestones"]:
        cache["milestones"].append(text)
        if len(cache["milestones"]) > 50:
            # 安全保护：确保至少有2个元素才合并
            if len(cache["milestones"]) >= 2:
                cache["milestones"][0:2] = [f"（早期）{cache['milestones'][0]}；{cache['milestones'][1]}"]
            
def _should_skip_milestone(paragraph):
    """排除占位符/背景知识/心理活动/未发生事件"""
    for start in BACKGROUND_STARTS:
        if paragraph.startswith(start):
            return True
    for pat in PLACEHOLDER_PATTERNS:
        if pat in paragraph:
            return True
    if any(dw in paragraph for dw in MILESTONE_DENY_WORDS):
        return True
    return False

def detect_and_add_milestone(cache, new_plot, new_round):
    """检测本轮剧情关键事件，写入里程碑列表"""
    if len(new_plot) < 20:
        return
    # 拆句，遍历主角动作正则，允许多命中
    sentences = re.split(r'([。！？…]+)', new_plot)
    sentences = ["".join(sentences[i:i+2]).strip() for i in range(0, len(sentences)-1, 2)] if len(sentences) > 1 else [new_plot]
    for sentence in sentences:
        if len(sentence) < 8:
            continue
        if _should_skip_milestone(sentence):
            continue
        for pat in PROTAGONIST_PATTERNS:
            if re.search(pat, sentence):
                clean = re.sub(r'你', '李三奇', sentence)
                clean = re.sub(r'【[^】]+】', '', clean)
                milestone_text = f"第{new_round}轮：{clean[:75]}"
                add_milestone(cache, milestone_text)
                break  # 一句只取第一个命中


# ===== 后台任务锁 =====
_context_cache_lock = threading.Lock()

# ===== L2生成状态控制（最小侵入方案） =====
# Event机制：set()=可继续，clear()=生成中
_l2_generating_event = threading.Event()
_l2_generating_event.set()

def _l2_is_generating():
    """检查L2是否正在生成中"""
    return not _l2_generating_event.is_set()

def _l2_set_generating():
    """标记L2开始生成（上锁）"""
    _l2_generating_event.clear()

def _l2_set_done():
    """标记L2生成完成（解锁）"""
    _l2_generating_event.set()

def _background_generate_l2(new_round, logs_slice):
    """后台生成 L2 章节摘要 和 全量融合摘要（线程安全）"""

    try:
        # 前置校验：日志切片为空直接返回
        if not logs_slice or len(logs_slice) < 10:
            print(f"{COLOR_WARN}⚠️ L2生成跳过：日志切片不足10轮{COLOR_END}")
            return

        logs_text = "\n\n".join(logs_slice)

        # ========== 1. 生成 L2 独立章节摘要 ==========
        chapter_prompt = f"""你是一位武侠小说编辑，请为最近的一章剧情生成独立摘要。

【本章剧情】
{logs_text}

【写作要求】
1. 先写一句 7-10 字的章回式小标题，换行再写正文  
2.**叙事逻辑**：以「核心事件→人物互动→转折收尾」的脉络组织，不要按时间逐条罗列事件，禁止出现“第X轮”“玩家”“交互”等元词汇。
3.  **信息必留**：必须精准保留以下核心要素：
    - 出场的关键人物及其身份、态度转变
    - 核心冲突与剧情转折
    - 重要物品、武功、线索的得失
    - 埋下的关键伏笔
4.  **详略原则**：核心对手戏、剧情转折点详写；赶路、闲聊、练功等过渡内容一笔带过，不堆砌细节。
5.  **文风要求**：第三人称客观叙事，凝练有武侠感，不用口语化表达。
6.  **篇幅控制**：严格控制在300~400字之间，只输出纯摘要正文，不要标题、序号、解释性文字、JSON。

输出："""
        chapter_summary = get_llm_content(llm_call_common("", chapter_prompt, temp=0.3, timeout=60, max_tokens=2000)).strip()

        # ===== 全量融合摘要已移至 _background_generate_l3 =====
        full_summary = None

        # ========== 3. 写入缓存 ==========
        if chapter_summary or full_summary:
            with _context_cache_lock:
                cache = load_context_cache() or {}

                # 3.1 更新 L2 章节摘要（修复作用域bug，统一计算变量）
                if chapter_summary:
                    existing_chapters = cache.get("chapter_summaries", [])
                    
                    # 统一计算章节ID和轮次范围
                    if existing_chapters:
                        last_chapter = existing_chapters[-1]
                        old_chapter_id = last_chapter.get("chapter_id", 0)
                        new_chapter_id = old_chapter_id + 1
                        
                        last_range = last_chapter.get("round_range", "")
                        if last_range and '~' in last_range:
                            # 安全检查：split结果可能只有1个元素
                            range_parts = last_range.split('~')
                            if len(range_parts) >= 2 and range_parts[1].isdigit():
                                prev_end = int(range_parts[1])
                                new_range = f"{prev_end + 1}~{new_round}"
                            else:
                                new_range = f"1~{new_round}"
                        else:
                            new_range = f"1~{new_round}"
                    else:
                        # 首次生成
                        new_chapter_id = 1
                        new_range = f"1~{new_round}"
                    
                    # 守卫：防重复触发导致 start > end
                    if '~' in new_range:
                        parts = new_range.split('~')
                        if int(parts[0]) > int(parts[1]):
                            print(f"{COLOR_WARN}⚠️ L2章节跳过：轮次范围异常 {new_range}（重复触发）{COLOR_END}")
                            return
                    
                    # 追加新章节，并限制最多保留100章防止缓存文件膨胀
                    existing_chapters.append({
                        "chapter_id": new_chapter_id,
                        "round_range": new_range,
                        "summary": chapter_summary[:500]
                    })
                    if len(existing_chapters) > 100:
                        existing_chapters = existing_chapters[-100:]

                    
                    
                    cache["chapter_summaries"] = existing_chapters

                    # ===== 同步章节摘要到云端向量库（L4中长期记忆）=====
                    upload_chapter_summary(CLOUD_MEM_SLOT_ID, new_chapter_id, new_range, chapter_summary[:300])

                # 全量融合摘要已移至L3，此处不再保存
                # if full_summary:
                #     cache["full_plot_summary"] = full_summary[:500]

                # 持久化保存
                save_context_cache(cache)
                print(f"{COLOR_SYSTEM}✅ 后台L2章节与全量摘要已生成（更新至第{new_round}轮）{COLOR_END}")
                # _try_memory_scoring()  # 已停用
        else:
            print(f"{COLOR_WARN}❌ 后台L2生成失败：模型返回空内容{COLOR_END}")

    except Exception as e:
        print(f"{COLOR_WARN}❌ 后台L2生成异常：{str(e)}{COLOR_END}")
    finally:
        # 无论成功失败，都解锁（防死锁）
        _l2_set_done()

    # ===== L2完成后：蒸馏NPC记忆 → 上传云向量（补充原始记忆） =====
    # 章节摘要已写入缓存，蒸馏基于摘要提取NPC认知，不阻塞主线程
    if chapter_summary and len(chapter_summary) >= 20:
        _distill_npc_memories(new_round)

# ===== 新增：记忆重要性评分（后台异步，不阻塞主流程）=====
def _score_memory_importance(cache, start_round, end_round):
    """后台运行：用LLM评估最近N轮剧情的重要性，高分者追加到向量库"""
    interact_logs = cache.get("interact_log", [])
    round_snippets = []
    for i in range(start_round, end_round + 1):
        if i <= len(interact_logs):
            log = interact_logs[i - 1]
            plot_match = re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", log, re.S)
            if plot_match:
                snippet = plot_match.group(1).strip()[:80]
                round_snippets.append((i, snippet))
    if len(round_snippets) < 5:
        return

    rounds_text = "\n".join([f"{r}. {s}" for r, s in round_snippets])
    prompt = f"""你是一个剧情重要性评估器。评估以下最近发生的剧情事件，从1-10打分。
评分标准：
- 8-10分：核心主线推进、重要人物生死、重大关系转折、关键秘密揭露
- 5-7分：人物互动有实质进展、获得重要物品/信息、次要剧情推进
- 1-4分：日常对话、练功、闲逛、无实质推进的过渡事件

仅输出JSON数组，不要任何解释：
[{{"round": 轮次, "score": 分数, "brief": "3字简述"}}, ...]

【待评估剧情】
{rounds_text}
"""
    try:
        from cloud_memory_v2 import upload_important_memory
        result = get_llm_content(
            llm_call_common(prompt, "记忆重要性评分", max_tokens=300, temp=0.1, timeout=45)
        )
        if not result or not isinstance(result, str):
            return
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", result.strip())
        scores = json.loads(clean)
        if not isinstance(scores, list):
            return

        uploaded = 0
        for item in scores:
            r = item.get("round", 0)
            score = item.get("score", 0)
            brief = item.get("brief", "")
            if isinstance(score, (int, float)) and score >= 7 and 1 <= r <= len(interact_logs):
                log = interact_logs[r - 1]
                plot_match = re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", log, re.S)
                if plot_match:
                    content = f"{brief}。{plot_match.group(1).strip()[:150]}"
                    upload_important_memory(CLOUD_MEM_SLOT_ID, r, content, int(score))
                    uploaded += 1
        print(f"{COLOR_SYSTEM}✅ 记忆评分完成：{start_round}-{end_round}轮，{uploaded}条高分入库{COLOR_END}")
    except Exception as e:
        print(f"{COLOR_WARN}⚠ 记忆评分失败（不影响主流程）：{e}{COLOR_END}")


def _try_memory_scoring():
    """后台调用：检查是否有未评分的轮次，有则分批触发评分"""
    cache = load_context_cache() or {}
    current_round = cache.get("round", len(cache.get("interact_log", [])))
    last_scored = cache.get("last_scored_round", 0)
    BATCH_SIZE = 30
    if current_round - last_scored >= BATCH_SIZE:
        end_round = min(last_scored + BATCH_SIZE, current_round)
        _score_memory_importance(cache, last_scored + 1, end_round)
        cache["last_scored_round"] = end_round
        save_context_cache(cache)
    # 每20轮打印健康度
    if current_round % 20 == 0 and current_round > 0:
        gap = current_round - cache.get("last_scored_round", 0)
        print(f"📊 [记忆健康] 总轮次:{current_round} 已评分:{cache.get('last_scored_round', 0)} 缺口:{gap}")


def _background_generate_l3(new_round):
    """后台生成L3全文脉络+传记并写入缓存（线程安全）"""

    import json

   # 读取当前缓存
    with _context_cache_lock:
        cache = load_context_cache() or {}

    # ===== 1. 先生成全量融合摘要 =====
    old_full = cache.get("full_plot_summary", "故事初始，暂无完整脉络")
    recent_ch = cache.get("chapter_summaries", [])[-2:]
    if recent_ch:
        ch_text = "\n".join([c.get("summary", "") for c in recent_ch])
        full_prompt = f"""你是一位武侠小说编辑。你的任务：将【旧剧情概述】与【新增章节】融合，重新生成一份完整的全剧情概述。

【旧剧情概述】（此前全部剧情的浓缩，唯一权威底本）
{old_full}

【新增章节】（需要融入的增量剧情）
{ch_text}

【融合规则】
1. 以旧概述为底本：核心设定、重大转折、关键人物关系必须全部保留，不得遗漏、不得改写既有事实
2. 增量融入：新章节只提炼核心事件与格局变化，融入对应位置；赶路、闲聊、日常练功等过渡情节一律舍弃
3. 冲突与演进：新章节与旧概述矛盾时以新章节为准（剧情演进）；已故人物不得再以活跃身份出现，人物关系变化（结盟、反目、定情）要更新到位
4. 结构：按「江湖大势→核心主线→人物格局」三层逻辑行文，层层递进，连贯成文
5. 文风：第三人称客观叙事，凝练厚重有江湖感；不用口语、不用列表、不按章节罗列；禁止「第X章」「本轮」「玩家」等元词汇
6. 篇幅：全文不超过500字（含标点），只输出概述正文，无标题、序号、解释

输出："""
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是小说编辑。根据旧脉络和新章节，融合生成全量剧情脉络。只输出纯文本。"},
                    {"role": "user", "content": full_prompt}
                ],
                max_tokens=2000, temperature=0.3, timeout=75,
                extra_body={"thinking": {"type": "disabled"}}
            )
            # 安全检查：message.content 可能为 None
            content = getattr(resp.choices[0].message, 'content', '') or ''
            new_full_raw = content.strip()
            if new_full_raw:
                full_summary = new_full_raw
                # 【二次压缩】超600字时专职压缩（质量已由首次生成保证，此处只管字数）
                if len(full_summary) > 600:
                    try:
                        resp2 = client.chat.completions.create(
                            model=DEEPSEEK_MODEL,
                            messages=[
                                {"role": "system", "content": "你是小说编辑，专职压缩剧情概述，只输出压缩后的纯文本。"},
                                {"role": "user", "content": f"以下剧情概述当前{len(full_summary)}字，必须压缩到600字以内（含标点）：\n- 保留优先级从高到低：主线关键事件与结局、人物关系变化、未解伏笔；先删战斗过程与招式细节、日常相处、风物描写\n- 允许大幅合并改写、句式极简，信息要点尽量保留但表述精炼\n- 600字是硬性上限，宁可多删不得超出\n\n{full_summary}"}
                            ],
                            max_tokens=1200, temperature=0.3, timeout=60,
                            extra_body={"thinking": {"type": "disabled"}}
                        )
                        compressed = (getattr(resp2.choices[0].message, 'content', '') or '').strip()
                        if compressed and len(compressed) < len(full_summary):
                            full_summary = compressed
                            print(f"{COLOR_SYSTEM}✅ L3脉络二次压缩：{len(new_full_raw)}字 → {len(full_summary)}字{COLOR_END}")
                    except Exception:
                        pass
                print(f"{COLOR_SYSTEM}✅ 后台L3全量脉络已生成（{len(full_summary)}字）{COLOR_END}")
            else:
                full_summary = old_full
        except Exception as e:
            print(f"{COLOR_WARN}⚠️ L3全量脉络生成异常，使用旧值: {e}{COLOR_END}")
            full_summary = old_full
    else:
        full_summary = old_full

    # ===== 2. 用新全量脉络生成传记 =====
    bio_prompt = f"""根据以下剧情，更新主角传记与世界状态，只输出标准JSON，不要任何多余文字、解释、代码块标记。
现有传记：
{json.dumps(cache.get('biography', {}), ensure_ascii=False, indent=2)}

全量剧情脉络：
{full_summary}

必须严格按以下JSON结构输出（**重要**必须输出完整JSON，禁止截断。identity/core_ability各30字内，allies/enemies每项10字内，main_plot 50字内）：
{{
  "protagonist": {{
    "name": "主角姓名",
    "identity": "身份与门派地位",
    "core_ability": "核心武功与修为",
    "allies": ["盟友1", "盟友2"],
    "enemies": ["敌人1", "敌人2"],
    "reputation": 江湖声望数值整数
  }},
  "world_state": {{
    "main_plot": "当前主线剧情概括",
    "unresolved_arcs": ["未解决伏笔1", "未解决伏笔2"]
  }}
}}

"""

    try:
        # 裸API调用，不带游戏系统提示词，避免LLM误生成剧情
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是小说传记编辑器。根据全量剧情脉络，更新主角传记JSON。只输出标准JSON。"},
                {"role": "user", "content": bio_prompt}
            ],
            max_tokens=2000, temperature=0.3, timeout=75,
            extra_body={"thinking": {"type": "disabled"}}
        )
        # 安全检查：message.content 可能为 None
        content = getattr(resp.choices[0].message, 'content', '') or ''
        new_bio_text = content.strip()
        
        # ========== 增强JSON解析：自动剥离 + 修复 + 三级兜底 ==========
        # 第一步：剥离代码块、多余文字
        json_match = re.search(r'```json\s*(\{.*\})\s*```', new_bio_text, re.DOTALL)
        if json_match:
            new_bio_text = json_match.group(1)
        else:
            start = new_bio_text.find('{')
            end = new_bio_text.rfind('}')
            if start != -1 and end != -1:
                new_bio_text = new_bio_text[start:end+1]

        # 第二步：尝试正常解析
        new_bio = None
        try:
            new_bio = json.loads(new_bio_text)
        except json.JSONDecodeError:
            # 第三步：修复常见问题——补全缺失的 world_state 外层闭合
            try:
                # 如果只有 protagonist 没写完，手动补全结构
                repaired_text = new_bio_text.rstrip()
                # 缺末尾闭合括号
                if repaired_text.count('{') > repaired_text.count('}'):
                    repaired_text += '}' * (repaired_text.count('{') - repaired_text.count('}'))
                new_bio = json.loads(repaired_text)
            except Exception:
                pass

        # 第四步：最终兜底：解析彻底失败就跳过本次更新，保留旧传记
        if not new_bio:
            print(f"{COLOR_WARN}⚠️ L3传记JSON解析失败，跳过本次更新{COLOR_END}")
            print(f"{COLOR_WARN}模型返回内容：{new_bio_text[:300]}{COLOR_END}")
            return

        # 写回缓存（增量合并）
        with _context_cache_lock:
            cache = load_context_cache() or {}
            old_bio = cache.get("biography", {})
            
            # 增量合并新老数据，缺的字段保留旧值
            if "protagonist" in new_bio:
                old_bio["protagonist"] = {**old_bio.get("protagonist", {}), **new_bio["protagonist"]}
            if "world_state" in new_bio:
                old_bio["world_state"] = {**old_bio.get("world_state", {}), **new_bio["world_state"]}
            
            # 防膨胀裁剪
            if "protagonist" in old_bio:
                if "allies" in old_bio["protagonist"]:
                    old_bio["protagonist"]["allies"] = old_bio["protagonist"]["allies"][:8]
                if "enemies" in old_bio["protagonist"]:
                    old_bio["protagonist"]["enemies"] = old_bio["protagonist"]["enemies"][:8]
            if "world_state" in old_bio and "unresolved_arcs" in old_bio["world_state"]:
                old_bio["world_state"]["unresolved_arcs"] = old_bio["world_state"]["unresolved_arcs"][:5]
            
            cache["biography"] = old_bio
            cache["full_plot_summary"] = full_summary
            cache["last_l3_gen_round"] = new_round  # 防止主线程值被覆盖
            # （旧全量生成块已移除，全量在前面 step 1 中生成）
            save_context_cache(cache)
 
            print(f"{COLOR_SYSTEM}✅ 后台L3传记已更新{COLOR_END}")
            # ===== 同步传记到云端向量库（L4人物关系演进记忆）=====
            protagonist = old_bio.get("protagonist", {})
            bio_snapshot = f"主角{protagonist.get('name','')}，身份{protagonist.get('identity','')}，武功{protagonist.get('core_ability','')}，声望{protagonist.get('reputation',0)}，盟友{'、'.join(protagonist.get('allies',[])[:3])}，敌人{'、'.join(protagonist.get('enemies',[])[:3])}"
            # upload_biography_update(CLOUD_MEM_SLOT_ID, bio_snapshot)
           
            # ===== FORESHADOW/BIOGRAPHY上传已停用，仅保留PLOT_ROUND/CHAPTER/NPC_MEMORY =====
            # if "world_state" in old_bio and "unresolved_arcs" in old_bio["world_state"]:
            #     arcs_list = old_bio["world_state"]["unresolved_arcs"]
            #     last_uploaded = cache.get("last_uploaded_foreshadowings", [])
            #     for arc in arcs_list:
            #         if arc not in last_uploaded:
            #             upload_foreshadowing(CLOUD_MEM_SLOT_ID, arc)
            #     cache["last_uploaded_foreshadowings"] = list(arcs_list)
 
 
            
    except Exception as e:
        print(f"{COLOR_WARN}❌ 后台L3生成异常：{str(e)}{COLOR_END}")
        if 'new_bio_text' in locals():
            print(f"{COLOR_WARN}模型原始返回片段：{new_bio_text[:200]}{COLOR_END}")


# ===== NPC记忆蒸馏：从章节摘要提取NPC认知，上传云向量 =====
_distill_lock = threading.Lock()

def _distill_npc_memories(new_round):
    """后台蒸馏NPC记忆并上传云向量（不阻塞主线程，不影响web端稳定性）

    原料：最新章节摘要（300-400字）
    产物：每位变动NPC ≤120字记忆，格式与原始记忆一致
    上传：upload_npc_memory，带当前novel_node时间戳，同池检索
    """
    # 防重入：同一轮只蒸馏一次
    if not _distill_lock.acquire(blocking=False):
        print(f"{COLOR_WARN}⚠️ [NPC蒸馏] 第{new_round}轮已有蒸馏在执行，跳过{COLOR_END}")
        return
    try:
        # ① 读章节摘要（短暂持_context_cache_lock，读完立即释放）
        with _context_cache_lock:
            cache = load_context_cache() or {}
        chapters = cache.get("chapter_summaries", [])
        if not chapters:
            print(f"{COLOR_SYSTEM}[NPC蒸馏] 无章节摘要，跳过{COLOR_END}")
            return
        latest_ch = chapters[-1]
        chapter_summary = latest_ch.get("summary", "")
        round_range = latest_ch.get("round_range", f"{new_round-49}-{new_round}")
        chapter_id = latest_ch.get("chapter_id", "")
        if not chapter_summary or len(chapter_summary) < 20:
            print(f"{COLOR_SYSTEM}[NPC蒸馏] 章节摘要过短，跳过{COLOR_END}")
            return

        # ② 获取当前novel_node（不持锁）
        novel_node = ""
        try:
            player = get_player()
            if player and player.novel_node:
                novel_node = player.novel_node
        except Exception:
            pass

        # ③ AI蒸馏（不持任何锁，不阻塞主线程）
        distill_prompt = f"""请从以下章节摘要中，为有态度或关系变化的NPC各蒸馏一段记忆。

【章节摘要】（第{chapter_id}章，轮次{round_range}）
{chapter_summary}

要求：
1. 只输出有变化的NPC，无变化的不输出
2. 每位NPC不超过120字
3. 必须包含：关系演变(从→到)、关键转折(1-3个)、认知边界(知晓X，不知Y)
4. 格式：{chr(123)}NPC名{chr(125)}：{chr(123)}旧态度{chr(125)}→{chr(123)}新态度{chr(125)}，经{chr(123)}转折{chr(125)}。知晓{chr(123)}知道的事{chr(125)}，不知{chr(123)}不知道的事{chr(125)}

只输出纯文本，每位NPC一段，用===分隔：
=== 胡斐 ===
胡斐：留意→信赖，经并肩御敌·相救脱险。知晓胡家刀法，不知血刀门秘籍。
=== 苗人凤 ===
苗人凤：冷淡→留意，经切磋武艺。知晓玩家是胡一刀之子，不知血刀门武功。"""

        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是小说编辑。从章节摘要中蒸馏NPC对玩家的认知记忆。只输出纯文本。"},
                    {"role": "user", "content": distill_prompt}
                ],
                max_tokens=800, temperature=0.3, timeout=30,
                extra_body={"thinking": {"type": "disabled"}}
            )
            content = getattr(resp.choices[0].message, 'content', '') or ''
            content = content.strip()
        except Exception as e:
            print(f"{COLOR_WARN}⚠️ [NPC蒸馏] AI调用失败，跳过: {e}{COLOR_END}")
            return

        if not content:
            print(f"{COLOR_SYSTEM}[NPC蒸馏] AI返回为空，跳过{COLOR_END}")
            return

        # ④ 正则解析 === NPC名 === 段落
        pattern = r'===\s*(.+?)\s*===\s*\n([\s\S]+?)(?====|\Z)'
        matches = re.findall(pattern, content)
        if not matches:
            print(f"{COLOR_SYSTEM}[NPC蒸馏] 解析为空（格式不符），跳过。原始输出: {content[:200]}{COLOR_END}")
            return

        # ⑤ 逐个上传（不持锁，每个独立try-except）
        uploaded = 0
        for npc_name, memory_text in matches:
            npc_name = npc_name.strip()
            memory_text = memory_text.strip()
            if not npc_name or not memory_text:
                continue
            # 截断到120字
            if len(memory_text) > 120:
                memory_text = memory_text[:120]
            try:
                upload_npc_memory(
                    user_id=CLOUD_MEM_SLOT_ID,
                    npc_name=npc_name,
                    memory_text=f"【章末总结·第{round_range}轮】{memory_text}",
                    novel_node=novel_node
                )
                uploaded += 1
                print(f"{COLOR_SYSTEM}[NPC蒸馏] {npc_name} 记忆已上传（{len(memory_text)}字）{COLOR_END}")
            except Exception as e:
                print(f"{COLOR_WARN}⚠️ [NPC蒸馏] {npc_name} 上传失败: {e}{COLOR_END}")
                # 静默跳过，不影响其他NPC

        print(f"{COLOR_SYSTEM}✅ [NPC蒸馏] 第{chapter_id}章完成，{uploaded}位NPC记忆已上传{COLOR_END}")

    except Exception as e:
        print(f"{COLOR_WARN}⚠️ [NPC蒸馏] 异常，跳过: {e}{COLOR_END}")
        # 静默跳过，不影响游戏运行
    finally:
        _distill_lock.release()


# ===== 上下文缓存（重磅升级：分层记忆 + 增量压缩摘要） =====
def update_context_cache(new_plot, user_action=""):
    if not new_plot:
        return refresh_context_cache()["last_plot_summary"]
    
    cache = refresh_context_cache()
    
    # 当前轮次（独立计数器，不依赖 interact_log 长度，解决封顶冻结bug）
    new_round = cache.get("round", 0) + 1
    record = f"【第 {new_round} 轮交互】\n【玩家行动】{user_action}\n【本轮剧情内容】{new_plot}"

    # 防重复追加校验：基于独立计数器 last_appended_round，不再解析日志字符串
    # 避免 interact_log 截断后末条日志轮次号与 new_round 字符串误判导致冻结
    if cache.get("last_appended_round", 0) >= new_round:
        # 已经追加过，直接返回现有摘要，后续L2/L3也不会重复触发
        return cache["last_plot_summary"]

    cache["interact_log"].append(record)
    append_interact_log(record)  # 同步追加到 jsonl（O(1)，避免每轮重写整个 cache）
    cache["round"] = new_round              # 写回独立轮次计数器
    cache["last_appended_round"] = new_round
    
    if len(cache["interact_log"]) > MAX_CONTEXT_LOG:
        cache["interact_log"] = cache["interact_log"][-MAX_CONTEXT_LOG:]

    # ===== L4 里程碑：实时检测关键事件 =====
    detect_and_add_milestone(cache, new_plot, new_round)

    # 玩家锚点
    player = get_player()
    if player:
        player_state = f"当前状态：{player.self_state}，综合修为：{player.overall_martial_level}"
        rum_list = player.rumor_list
        if rum_list:
            # 每条传闻添加编号，格式更清晰
            rumor_lines = [f"{i+1}. {rum.strip()[:40]}" for i, rum in enumerate(rum_list[-5:]) if rum and rum.strip() != "无"]
            if rumor_lines:
                rum_snippet = "\n".join(rumor_lines)
                player_anchor = f"【主角状态】{player_state}。\n【近期剧情记录】\n{rum_snippet}"
            else:
                player_anchor = f"【主角状态】{player_state}。\n【近期剧情记录】暂无。"
        else:
            player_anchor = f"【主角状态】{player_state}。\n【近期剧情记录】暂无。"
    else:
        player_anchor = "【主角状态】暂无档案，视为普通江湖游侠。"

    # 最近详细记录（保留20条）# 固定滚动保留最新20条交互作为last_plot_summary（暂时删掉）
    # SUMMARY_KEEP_RECENT_COUNT = 5
    # recent_records = cache["interact_log"][-SUMMARY_KEEP_RECENT_COUNT:]
    # recent_context = "\n\n".join(recent_records)
    
    # ===== 替换为精简版 =====
    # 替换原 recent_context 组装逻辑
    SUMMARY_KEEP_RECENT_COUNT = 3
    recent_records = cache["interact_log"][-SUMMARY_KEEP_RECENT_COUNT:]
    recent_lines = []
    for log in recent_records:
        action_match = re.search(r"【玩家行动】\s*(.*?)(?=\n【|$)", log, re.S)
        plot_match = re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", log, re.S)
        action = action_match.group(1).strip() if action_match else ""
        plot = plot_match.group(1).strip()[:120] if plot_match else ""
        recent_lines.append(f"玩家：{action}\n剧情：{plot}")
    recent_context = "\n\n".join(recent_lines)

    # ===== 自动归档：每5000轮将旧日志移出，并限制归档文件总数 =====
    if new_round % 5000 == 0 and new_round > 0:
        # 保留最近2000轮日志（与MAX_CONTEXT_LOG一致）
        keep_count = 2000
        if len(cache["interact_log"]) > keep_count:
            # 要归档的日志为前 (len - keep_count) 条
            archive_logs = cache["interact_log"][:-keep_count]
            archive_dir = "data/archive"
            ensure_dir(archive_dir)

            # 计算本轮涉及的轮次范围（基于独立轮次号，不再用 len 计算）
            total_before = len(cache["interact_log"])
            end_round = new_round
            start_round = end_round - keep_count + 1
            archive_file = f"{archive_dir}/archive_{start_round:05d}-{end_round:05d}.json"

            # 保存归档
            with open(archive_file, "w", encoding="utf-8") as f:
                json.dump(archive_logs, f, ensure_ascii=False, indent=2)
            print(f"{COLOR_SYSTEM}✅ 已归档 {start_round}~{end_round} 轮剧情到 {archive_file}{COLOR_END}")

            # 从内存中移除已归档的日志
            cache["interact_log"] = cache["interact_log"][-keep_count:]
            rewrite_interact_log(cache["interact_log"])  # 同步截断 jsonl（归档低频，可接受重写）

            # ---------- 自动清理旧归档（保留最近 50 个文件） ----------
            all_archives = sorted([f for f in os.listdir(archive_dir) if f.startswith("archive_") and f.endswith(".json")])
            max_keep = 50
            if len(all_archives) > max_keep:
                to_delete = all_archives[:-max_keep]  # 保留最新的 max_keep 个
                for fname in to_delete:
                    path = os.path.join(archive_dir, fname)
                    os.remove(path)
                    print(f"{COLOR_SYSTEM}🗑️ 已删除过期归档：{fname}{COLOR_END}")
            
    # ===== 增量压缩摘要（全局迭代） =====
    if "compressed_global_summary" not in cache:
        cache["compressed_global_summary"] = "故事初始，暂无前置剧情"
    
    last_compress_round = cache.get("last_compress_round", 0)
    if new_round - last_compress_round >= 20 or last_compress_round == 0:
        # 使用旧的全局摘要 + 新发生的最近详细内容，生成新的全局摘要
        # 为了减少API输入负载，只取最近5轮作为"新发生的剧情"
        compress_recent = recent_records[-5:] if len(recent_records) >= 5 else recent_records
        compress_recent_context = "\n\n".join(compress_recent)
        new_input = f"旧摘要：{cache['compressed_global_summary']}\n\n新发生的剧情：\n{compress_recent_context}"
        
        # 压缩提示词，强制要求输出非空文本
        compress_prompt = f"""请完成以下任务，输出格式严格如下（不要输出其他内容）：

【远古核心剧情提要】
（将武侠剧情历史压缩为不超过300字的精炼摘要，保留核心人物关系和重大转折，必须包含新发生的重要事件。如果内容很少，请输出“故事继续，暂无重大事件”。）

输入内容：
{new_input}"""
        
        try:
            compress_resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": compress_prompt}],
                temperature=0.3,
                max_tokens=400,
                timeout=45,
                extra_body={"thinking": {"type": "disabled"}}
            )
            # 安全检查：message.content 可能为 None
            content = getattr(compress_resp.choices[0].message, 'content', '') or ''
            full_output = content.strip()
            print(f"DEBUG: {full_output}") 
            
            # 提取【远古核心剧情提要】
            summary_match = re.search(r"【远古核心剧情提要】\s*(.*)", full_output, re.S)
            if summary_match:
                cache["compressed_global_summary"] = summary_match.group(1).strip()
            else:
                cache["compressed_global_summary"] = "故事继续，暂无重大事件"
            
                        
                
                
                
            cache["last_compress_round"] = new_round
        except Exception as e:
            print(f"{COLOR_WARN}【压缩摘要API调用失败】{e}{COLOR_END}")
            # 如果旧摘要为空，设置一个默认值
            if not cache.get("compressed_global_summary"):
                cache["compressed_global_summary"] = "故事初始，暂无前置剧情"
            if not cache.get("key_anchors"):
                cache["key_anchors"] = []
            # 无论是否设置了默认值，都必须更新 last_compress_round，避免反复重试
            cache["last_compress_round"] = new_round
                
    # ===== 最终组合成 last_plot_summary =====
    cache["last_plot_summary"] = f"{player_anchor}\n\n【远古核心剧情提要】{cache['compressed_global_summary']}\n\n【最新详细剧情】\n{recent_context}"
    
    # 完整历史追加（截断）
    cache["full_plot_history"] += f"\n\n===== 第 {new_round} 轮 =====\n{record}"
    if len(cache["full_plot_history"]) > 20000:
        cache["full_plot_history"] = cache["full_plot_history"][-20000:]

     # ===== L2: 章节摘要（后台异步生成） =====
    if new_round % 50 == 0 and new_round > 0:
        # 新增：同轮防重复触发校验，避免同一轮多次启动生成
        last_l2_round = cache.get("last_l2_gen_round", 0)
        if last_l2_round >= new_round:
            pass  # 本轮已经生成过，直接跳过
        else:
            start_idx = new_round - 100
            if start_idx < 0:
                start_idx = 0
            logs_slice = cache["interact_log"][start_idx:new_round]
            if len(logs_slice) >= 10:
                # 先标记本轮已生成（线程执行前先占坑，防重复）
                cache["last_l2_gen_round"] = new_round
                # 上锁：阻止下一轮开始，直到L2生成完成
                _l2_set_generating()
                threading.Thread(
                    target=_background_generate_l2,
                    args=(new_round, logs_slice),
                    daemon=True
                ).start()
                print(f"{COLOR_SYSTEM}⏳ L2摘要生成已提交后台（第{new_round//50}章）{COLOR_END}")
    # ===== L3: 传记状态（后台异步生成） =====
    # 触发轮次：101/201/301... 错开L2（100/200轮）1轮，保证L2章节已写入缓存
    if new_round % 100 == 1 and new_round > 1:
        # 同轮防重复：已生成过直接跳过
        last_l3_round = cache.get("last_l3_gen_round", 0)
        if last_l3_round < new_round:
            # 先占坑标记，再启动线程，杜绝同轮重复启动
            cache["last_l3_gen_round"] = new_round
            threading.Thread(
                target=_background_generate_l3,
                args=(new_round,),
                daemon=True
            ).start()
            print(f"{COLOR_SYSTEM}⏳ L3传记更新已提交后台{COLOR_END}")
    # ===== L4: 大事记（实时检测关键事件） =====
    
    # 每 200 轮生成一个归档文件
    if new_round % 200 == 0 and new_round > 0:
        archive_data = {
            "round_range": f"{new_round-99}~{new_round}",
            "chapter_summary": cache.get("chapter_summaries", [])[-1] if cache.get("chapter_summaries", []) else {},    # 最新一章摘要
            "milestones": cache.get("milestones", [])[-10:],  # 最近10条大事记
            "biography": cache.get("biography", {}),  # 当时的传记快照
            "interact_log": cache["interact_log"][-200:]  # 最近100轮对话
        }
        archive_file = f"data/history_archive/archive_{new_round-99:05d}-{new_round:05d}.json"
        ensure_dir("data/history_archive")
        with open(archive_file, "w", encoding="utf-8") as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        # 只保留最近 100 个归档文件（即 10000 轮）
        cleanup_archives("data/history_archive", max_keep=100)
    
    # ===== PLOT_ROUND上传：智能关键词匹配 =====
    # 武侠小说常见关键场景关键词
    plot_trigger_keywords = {
        # 任务相关
        "任务", "完成", "提交", "结束", "达成", "领取", "接受", "接下", "接了",
        "托付", "嘱托", "奉命", "受命", "执行", "了结", "办妥",
        "追查", "调查", "打探", "寻找", "搜寻", "探索", "探险",
        
        # 战斗/冲突
        "战斗", "对决", "交手", "过招", "比武", "较量", "切磋",
        "击败", "战胜", "打败", "击杀", "斩杀", "重创", "击退",
        "受伤", "重伤", "负伤", "濒死", "昏迷", "死亡", "牺牲",
        "逃跑", "撤退", "突围", "埋伏", "偷袭", "围攻", "合击",
        
        # 剧情转折
        "发现", "揭示", "揭露", "真相", "秘密", "阴谋", "诡计",
        "背叛", "反目", "决裂", "和解", "结盟", "联手", "合作",
        "误会", "澄清", "真相大白", "水落石出",
        
        # 角色发展
        "拜师", "收徒", "学艺", "修炼", "突破", "晋级", "进阶",
        "境界", "内功", "心法", "招式", "秘籍", "绝学", "传承",
        "顿悟", "悟道", "闭关", "出关",
        
        # 关系变化
        "结识", "相遇", "重逢", "分别", "告别", "送行",
        "提亲", "订婚", "成亲", "结婚",
        "结拜", "义结金兰", "兄弟", "姐妹",
        
        # 重要事件
        "劫狱", "救人", "护宝", "夺宝", "寻宝",
        "赴约", "赴宴", "谈判", "交涉", "对峙",
        "中毒", "解毒", "疗伤", "救治",
        "启程", "抵达", "离开", "归来", "返回",
        
        # 江湖见闻相关关键词
        "传闻", "消息", "风声", "流言", "谣言",
        "悬赏", "通缉", "追杀", "逃亡",
        
        # 门派/势力
        "加入", "退出", "清理门户",
        "掌门", "帮主", "盟主", "护法", "堂主",
        
        # 物品/道具
        "获得", "得到", "失去", "丢失", "找回",
        "宝剑", "宝刀", "暗器", "丹药", "药材",
        "信物", "令牌", "密信", "地图", "藏宝图",
        
        # 情感
        "爱恨", "情仇", "恩怨", "报仇", "报恩", "雪耻",
        "感激", "愤怒", "悲痛", "狂喜", "震惊",
        
        # 地点探索
        "进入", "闯入", "深入", "走出",
        "山洞", "秘境", "禁地", "宝藏", "遗迹",
        "山庄", "府邸", "山寨", "总坛", "分舵",
        "客栈", "酒楼", "茶馆", "镖局", "当铺",
        
        # 时间节点
        "三年后", "数月后", "几天后", "一夜之间",
        "黎明", "深夜", "午时", "子时",
    }
    
    # 判断是否触发剧情上传（关键词匹配）
    should_upload_plot = False
    user_action_lower = user_action.strip()
    for keyword in plot_trigger_keywords:
        if keyword in user_action_lower:
            should_upload_plot = True
            break
    
    # 额外规则：如果用户输入超过20字且包含动词，也触发上传
    if not should_upload_plot and len(user_action_lower) > 20:
        # 检查是否包含动作类词汇
        action_words = ["去", "到", "找", "杀", "救", "拿", "取", "放", "走", "跑", "追", "逃"]
        for action in action_words:
            if action in user_action_lower:
                should_upload_plot = True
                break
    
    if should_upload_plot:
        _nn = player.novel_node if player and player.novel_node else ""
        upload_plot_memory(
            CLOUD_MEM_SLOT_ID,
            round_num=new_round,
            plot_content=new_plot,
            user_action=user_action,
            novel_node=_nn
        )


    # ========== 线程安全写入：加锁 + 合并后台最新数据 ==========
    with _context_cache_lock:
        # 1. 重新读取磁盘上的最新缓存（可能已被后台L2/L3线程更新过）
        latest_disk_cache = load_context_cache()
        if not latest_disk_cache or not isinstance(latest_disk_cache, dict):
            latest_disk_cache = {}

        # 2. 增量合并：只写入主线程本次的更新，保留后台线程的修改
        # 2.1 交互日志：防重复追加，避免同轮日志写两次
        our_new_log = cache["interact_log"][-1] if cache.get("interact_log") else ""
        disk_logs = latest_disk_cache.get("interact_log", [])
        if our_new_log and (not disk_logs or disk_logs[-1] != our_new_log):
            disk_logs.append(our_new_log)
            # 保持长度上限
            if len(disk_logs) > MAX_CONTEXT_LOG:
                disk_logs = disk_logs[-MAX_CONTEXT_LOG:]
        latest_disk_cache["interact_log"] = disk_logs

        # 2.2 主线程专属更新字段（直接覆盖，这些只能由主线程修改）
        latest_disk_cache["last_plot_summary"] = cache.get("last_plot_summary", "")
        latest_disk_cache["full_plot_history"] = cache.get("full_plot_history", "")
        latest_disk_cache["current_goal"] = cache.get("current_goal", "")
        latest_disk_cache["key_anchors"] = cache.get("key_anchors", [])
        latest_disk_cache["milestones"] = cache.get("milestones", [])
        latest_disk_cache["round"] = cache.get("round", 0)                      # 独立轮次计数器
        latest_disk_cache["last_appended_round"] = cache.get("last_appended_round", 0)  # 防重复追加基准

        # 2.3 全局压缩摘要（本次更新了才覆盖）
        if "compressed_global_summary" in cache:
            latest_disk_cache["compressed_global_summary"] = cache["compressed_global_summary"]
            latest_disk_cache["last_compress_round"] = cache.get("last_compress_round", 0)

        # 2.4 L2/L3 生成标记（防止重复触发后台任务）
        if "last_l2_gen_round" in cache:
            latest_disk_cache["last_l2_gen_round"] = cache["last_l2_gen_round"]
        if "last_l3_gen_round" in cache:
            latest_disk_cache["last_l3_gen_round"] = cache["last_l3_gen_round"]

        # 2.5 云端向量库上传标记
        if "last_uploaded_world_state" in cache:
            latest_disk_cache["last_uploaded_world_state"] = cache["last_uploaded_world_state"]

        # 3. 原子写入合并后的最终文件
        save_context_cache(latest_disk_cache)
    # ========== 线程安全写入结束 ==========

    # 原函数的 return 保持不变
    return cache["last_plot_summary"]

def parse_tool_calls_to_update_data(tool_calls):
    """从工具调用中提取状态更新数据，返回与原来 update_data 相同的字典"""
    if not tool_calls:
        return {}
    for tc in tool_calls:
        if tc.function.name == "update_game_state":
            try:
                args = json.loads(tc.function.arguments)
                # 只保留我们关心的字段
                valid_keys = ["reputation_delta", "world_trend", "faction_balance", "new_rumor", 
                              "mood", "event_action", "event_name", "skill_exp_gain", 
                              "skill_exp_update", "task", "bottleneck_progress_delta", "new_skills",
                              "self_state", "novel_node", "location"]
                return {k: v for k, v in args.items() if k in valid_keys}
            except Exception:
                return {}
    return {}

def format_tool_calls_summary(tool_calls):
    """将 tool_calls 解析为自然语言摘要，注入第二轮调用的 user_prompt，确保文字与状态判定一致"""
    if not tool_calls:
        return ""
    try:
        for tc in tool_calls:
            if tc.function.name == "update_game_state":
                args = json.loads(tc.function.arguments)
                lines = []
                if args.get("reputation_delta"):
                    d = args["reputation_delta"]
                    lines.append(f"- 江湖名气：{'+' if d > 0 else ''}{d}")
                skill_gains = args.get("skill_exp_gain", [])
                if skill_gains:
                    lines.append("- 武功经验：" + "，".join(f"{s.get('name','?')}+{s.get('exp',0)}" for s in skill_gains))
                new_skills = args.get("new_skills", [])
                if new_skills:
                    lines.append("- 新学武功：" + "，".join(s.get("name","?") for s in new_skills))
                favors = args.get("npc_favor_update", [])
                if favors:
                    lines.append("- NPC好感：" + "，".join(f"{f.get('name','?')}{'+' if f.get('delta',0)>=0 else ''}{f.get('delta',0)}" for f in favors))
                statuses = args.get("npc_status_update", [])
                if statuses:
                    sm = {"light_injured":"轻伤","heavy_injured":"重伤","dying":"濒死","deceased":"死亡","poisoned":"中毒","normal":"正常"}
                    lines.append("- NPC状态：" + "，".join(f"{s.get('name','?')}{sm.get(s.get('status',''),'?')}" for s in statuses))
                rels = args.get("npc_relationship_update", [])
                if rels:
                    lines.append("- NPC关系：" + "，".join(f"{r.get('name','?')}{r.get('relation','')}" for r in rels))
                if args.get("self_state"):
                    lines.append(f"- 主角状态：{args['self_state']}")
                if args.get("location"):
                    lines.append(f"- 地点：{args['location']}")
                task = args.get("task")
                if task and task.get("name"):
                    lines.append(f"- 任务：{task['name']}({task.get('stage','')},{task.get('percent',0)}%)")
                if args.get("world_trend"):
                    lines.append(f"- 江湖大势：{args['world_trend']}")
                if not lines:
                    return ""
                return "【本回合已确定的状态判定】\n" + "\n".join(lines) + "\n请基于以上判定结果生成剧情，确保剧情与状态变更一致。"
        return ""
    except Exception:
        return ""

# ===== 物品名称清洗工具（过滤格式标签/武功信息/分隔符残留）=====
def _clean_item_name(item: str) -> str:
    """返回清洗后的物品名，无效则返回空字符串"""
    if not item or not isinstance(item, str):
        return ""
    item = item.strip()
    # 过短或纯符号
    if len(item) < 2 or item in ("/", "无", "（无）", "(无)", "无。", "-", "--", "；", "；无"):
        return ""
    # 含格式标签关键词（消耗道具/丢弃道具/新增武功等标签残留）
    format_tags = ["消耗道具", "丢弃道具", "新增道具", "新增武功", "持有道具",
                   "消耗：", "丢弃：", "新增：", "持有：", "综合修为", "整体修为",
                   "尚需实战打磨", "尚需打磨"]
    if any(tag in item for tag in format_tags):
        return ""
    # 含武功境界关键词
    realm_kw = ["初窥门径", "登堂入室", "融会贯通", "出神入化", "登峰造极",
                "返璞归真", "天人合一", "略有所成", "渐入佳境"]
    if any(rk in item for rk in realm_kw):
        return ""
    # 含武功类关键词且长度较短（长物品名如"华山剑法秘籍"含"剑法"但为合法物品）
    martial_signals = ["武功", "修为", "功法", "心法", "掌法", "刀法", "拳法", "腿法"]
    if any(ms in item for ms in martial_signals) and len(item) < 15:
        return ""
    # 残缺括号（只有右括号没有左括号 → 被截断的片段）
    if item.endswith("）") and "（" not in item:
        return ""
    if item.endswith(")") and "(" not in item:
        return ""
    # 去掉尾部分隔符残留
    item = re.sub(r'[；;，,、/]+$', '', item).strip()
    if len(item) < 2:
        return ""
    return item


def parse_and_update_player_state(reply_text: str, tool_calls=None):
    
    player = get_player()
    if not player:
        return

    # ---- 优先从工具调用获取更新数据 ----
    update_data = parse_tool_calls_to_update_data(tool_calls) if tool_calls else {}
    print(f"[DEBUG 状态更新] 工具调用数据量：{len(update_data)} 个字段")
    # 如果工具调用没有提供数据，则回退到正则提取（保持兼容）
    if not update_data:
        # 放宽匹配：只要包含核心状态字段的JSON块都尝试提取
        start_match = re.search(r'\{[^{}]*"(?:reputation_delta|skill_exp_gain|task|new_skills)"', reply_text)
        if start_match:
            start = start_match.start()
            brace_count = 0
            end = start
            in_string = False
            escape = False
            for i in range(start, len(reply_text)):
                char = reply_text[i]
                if escape:
                    escape = False
                    continue
                if char == '\\':
                    escape = True
                    continue
                if char == '"' and not escape:
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end = i + 1
                            break
            if brace_count == 0 and end > start:
                json_str = reply_text[start:end]
                try:
                    update_data = json.loads(json_str)
                except json.JSONDecodeError:
                    update_data = {}

    # ===================== 新增武功捕获（三层兜底） =====================
    skill_added = False  # 全局标记：本轮是否成功新增了武功
    skip_overall_parse = False

    # ========== 第一层：工具调用新增武功（最高优先级） ==========
    new_skills_data = update_data.get("new_skills")
    if new_skills_data and isinstance(new_skills_data, list):
        for sk_info in new_skills_data:
            name = sk_info.get("name", "").strip()
            level = sk_info.get("level", "初窥门径")
            exp_text = sk_info.get("exp_text", "")
            if not name:
                continue
            # 防重复
            exists = any(sk["skill_name"] == name for sk in player.martial_skill_list)
            if not exists:
                try:
                    level_index = player.REALM_LIST.index(level)
                    initial_exp = player.EXP_THRESHOLDS[level_index]
                except (ValueError, IndexError):
                    initial_exp = 0
                    print(f"[WARN] 工具武功「{name}」等级「{level}」不在境界列表，使用0经验")
                player.add_skill(name, initial_exp, exp_text)
                print(f"✅【工具新增武功】{name}（{level}）")
                skill_added = True
            else:
                # 已存在则尝试更新等级
                for sk in player.martial_skill_list:
                    if sk["skill_name"] == name:
                        try:
                            sk["skill_level"] = level
                        except Exception as e:
                            print(f"{COLOR_WARN}⚠️ 设置技能等级失败: {e}{COLOR_END}")
                        break
        if skill_added:
            player.sync_overall_level()
            player.save()  # 立刻落盘，避免丢失
            print("[DEBUG] 工具新增武功已写入 player.json")
            skip_overall_parse = True

    # ========== 第二层：从【道具/自身健康状态】块提取正文格式 ==========
    item_block = ""
    block_match = re.search(r"【道具/自身健康状态】\s*(.+?)(?=\n【|$)", reply_text, re.S)
    if block_match:
        item_block = block_match.group(1).strip()

    if not skill_added and item_block:
        # 全局匹配「新增武功」，不依赖前后顺序
        skill_in_block = re.search(r"新增武功[:：]\s*(.+?)(?=\s*/\s*(?:新增|消耗|丢弃|综合|整体)|$)", item_block)
        if skill_in_block:
            skill_raw = skill_in_block.group(1).strip()
            level_keywords = "|".join(player.REALM_LIST)
            sk_match = re.search(r'(.*?)\s*(' + level_keywords + r')', skill_raw)

            if sk_match:
                skill_name = sk_match.group(1).strip().strip("（）()「」『』")
                skill_level = sk_match.group(2).strip()
                # 提取括号内的感悟描述
                exp_match = re.search(r'[（(](.+?)[）)]', skill_raw)
                exp_text = exp_match.group(1).strip() if exp_match else ""

                exists = any(sk["skill_name"] == skill_name for sk in player.martial_skill_list)
                if skill_name and not exists:
                    try:
                        level_index = player.REALM_LIST.index(skill_level)
                        initial_exp = player.EXP_THRESHOLDS[level_index]
                    except (ValueError, IndexError):
                        initial_exp = 0
                    try:
                        player.add_skill(skill_name, initial_exp, exp_text)
                        player.sync_overall_level()
                        player.save()  # 立刻落盘
                        print(f"✅【正文新增武功】{skill_name}（{skill_level}），已写入 player.json")
                        skill_added = True
                        skip_overall_parse = True
                    except Exception as e:
                        print(f"[ERROR] 正文新增武功失败：{e}")
                else:
                    print(f"[INFO] 正文武功「{skill_name}」已存在，跳过")
            else:
                print(f"[DEBUG] 正文武功等级未匹配，原始内容：{skill_raw[:50]}")

    # 关键：无论是否从块里抓到武功，都先把武功相关内容从item_block里剥离，避免污染物品
    if item_block:
        item_block = re.sub(r"新增武功[:：].*?(\s*/\s*|$)", "", item_block).strip()

    # ========== 第三层：全文模糊匹配兜底（极端情况） ==========
    if not skill_added:
        fuzzy_pattern = re.search(
            r'(?:习得|学会|掌握|新增)\s*[武功「「]?\s*([^，。\s「」（）()]{2,12})\s*[」」]?\s*.*?(初窥门径|登堂入室|融会贯通|出神入化|登峰造极)',
            reply_text
        )
        if fuzzy_pattern:
            skill_name = fuzzy_pattern.group(1).strip()
            skill_level = fuzzy_pattern.group(2).strip()
            exists = any(sk["skill_name"] == skill_name for sk in player.martial_skill_list)
            if skill_name and len(skill_name) <= 10 and not exists:
                try:
                    level_index = player.REALM_LIST.index(skill_level)
                    initial_exp = player.EXP_THRESHOLDS[level_index]
                except (ValueError, IndexError):
                    initial_exp = 0
                player.add_skill(skill_name, initial_exp, "初窥门径，尚需打磨")
                player.sync_overall_level()
                player.save()
                print(f"✅【模糊匹配新增武功】{skill_name}（{skill_level}），已写入 player.json")
                skill_added = True
                skip_overall_parse = True

    # ---- 兼容原有逻辑：旧版竖线分隔的新增武功 ----
    if not skill_added and not skip_overall_parse:
        new_skill_pattern = re.compile(r"新增武功\|(.+?)\|(.+?)\|(.+?)", re.S)
        new_skill_match = new_skill_pattern.search(reply_text)
        if new_skill_match:
            raw = new_skill_match.group(1).strip()
            level_keywords = "|".join(player.REALM_LIST)
            match = re.search(r'(.*?)\s*(' + level_keywords + r')', raw)
            if match:
                skill_name = match.group(1).strip()
                skill_level = match.group(2).strip()
            else:
                skill_name = raw
                skill_level = ""
            skill_name = re.sub(r'^新增武功[：:]', '', skill_name).strip()
            skill_exp = new_skill_match.group(3).strip() if len(new_skill_match.groups()) >= 3 else ""

            if skill_name:
                try:
                    level_index = player.REALM_LIST.index(skill_level)
                    initial_exp = player.EXP_THRESHOLDS[level_index]
                except (ValueError, IndexError):
                    initial_exp = 0
                exists = any(sk["skill_name"] == skill_name for sk in player.martial_skill_list)
                if not exists:
                    player.add_skill(skill_name, initial_exp, skill_exp)
                    player.sync_overall_level()
                    player.save()
                    print(f"✅【兼容格式新增武功】{skill_name}（{skill_level}）")
                    skill_added = True
                    skip_overall_parse = True

    # ---- 2. 处理经验增益（瓶颈进度由 add_exp 自动转化） ----
    # 双格式兼容：新格式 [{name, exp}]，旧格式 {武功名: 经验值}
    exp_gain_data = update_data.get("skill_exp_gain", {})
    gain_items = []
    exp_gain_lines = []
    if isinstance(exp_gain_data, dict):
        gain_items = [{"name": k, "exp": v} for k, v in exp_gain_data.items()]
    elif isinstance(exp_gain_data, list):
        gain_items = exp_gain_data
    for item in gain_items:
        if not isinstance(item, dict):
            continue
        skill_name = item.get("name")
        gain = item.get("exp")
        if skill_name and isinstance(gain, int) and gain > 0:
            player.add_exp(str(skill_name).strip(), gain)
            exp_gain_lines.append(f"{skill_name} +{gain}经验")
            print(f"【经验增益】{skill_name} +{gain} 经验")
    if gain_items:
        player.sync_overall_level()
        player.save()

    # ---- 3. 处理感悟更新 ----
    # 双格式兼容：新格式 [{name, text}]，旧格式 {武功名: 感悟文字}
    exp_update_data = update_data.get("skill_exp_update", {})
    update_items = []
    exp_update_lines = []
    if isinstance(exp_update_data, dict):
        update_items = [{"name": k, "text": v} for k, v in exp_update_data.items()]
    elif isinstance(exp_update_data, list):
        update_items = exp_update_data
    for item in update_items:
        if not isinstance(item, dict):
            continue
        skill_name = item.get("name")
        new_text = item.get("text")
        if skill_name and isinstance(new_text, str) and new_text.strip():
            player.update_exp_text(str(skill_name).strip(), new_text.strip())
            exp_update_lines.append(f"{skill_name}：{new_text.strip()}")
            print(f"【感悟更新】{skill_name}：{new_text[:30]}...")

    # ===================== 物品处理（基于已剥离武功的干净 item_block） =====================
    if item_block:
        # ---------- 4.1 新增道具 ----------
        add_match = re.search(r"新增道具[:：]\s*(.+?)(?=\s*/\s*(?:消耗|丢弃|新增)|$)", item_block)
        if add_match:
            add_raw = add_match.group(1).strip()
            raw_items = re.split(r'[、，,；;\n]+', add_raw)
            for raw in raw_items:
                item = _clean_item_name(raw)
                if not item:
                    continue
                if item not in player.item_list:
                    player.add_item(item)
                    print(f"【新增道具】{item}")

        # ---------- 4.2 消耗道具 ----------
        consume_match = re.search(r"消耗道具[:：]\s*(.+?)(?=\s*/\s*(?:新增|丢弃|消耗)|$)", item_block)
        if consume_match:
            consume_raw = consume_match.group(1).strip()
            raw_items = re.split(r'[、，,；;\n]+', consume_raw)
            for raw in raw_items:
                item = _clean_item_name(raw)
                if not item:
                    continue
                found = None
                # 第1轮：精确匹配 / 子串匹配
                for existing in player.item_list:
                    if existing == item or existing == raw.strip() or item in existing or existing in item:
                        found = existing
                        break
                # 第2轮：去掉括号说明后模糊匹配（处理 "银两（花掉了）"→"银两" 这类情况）
                if not found:
                    core = re.sub(r'[（(][^）)]*[）)]', '', item).strip()
                    if core and core != item:
                        for existing in player.item_list:
                            if core in existing or existing in core:
                                found = existing
                                break
                if found:
                    player.item_list.remove(found)
                    print(f"【物品消耗】{found}")
                else:
                    print(f"【物品消耗提示】背包中未找到：{item}")

        # ---------- 4.3 丢弃道具 ----------
        discard_match = re.search(r"丢弃道具[:：]\s*(.+?)(?=\s*/\s*(?:新增|消耗|丢弃)|$)", item_block)
        if discard_match:
            discard_raw = discard_match.group(1).strip()
            raw_items = re.split(r'[、，,；;\n]+', discard_raw)
            for raw in raw_items:
                item = _clean_item_name(raw)
                if not item:
                    continue
                found = None
                for existing in player.item_list:
                    if existing == item or existing == raw.strip() or item in existing or existing in item:
                        found = existing
                        break
                if not found:
                    core = re.sub(r'[（(][^）)]*[）)]', '', item).strip()
                    if core and core != item:
                        for existing in player.item_list:
                            if core in existing or existing in core:
                                found = existing
                                break
                if found:
                    player.item_list.remove(found)
                    print(f"【物品丢弃】{found}")
                else:
                    print(f"【物品丢弃提示】背包中未找到：{item}")

    # ---- 5. 处理传闻 ----
    rumor_match = re.search(r"【(?:传闻内容|江湖见闻|近期关键记忆|近期剧情记录)】\s*(.+?)(?=\n【|$)", reply_text, re.S)
    if rumor_match:
        rumor_text = rumor_match.group(1).strip()
        player.add_rumor(rumor_text)
        upload_rumor_item(CLOUD_MEM_SLOT_ID, rumor_text, player.novel_node)
        # 新增：自动截断传闻列表，只保留最新20条
    if len(player.rumor_list) > 20:
        player.rumor_list = player.rumor_list[-20:]
    
# ---- 插队解析 AI 的任务进展更新（四层兜底） ----
    task_data = None
    
    # ========== 第一层：优先从工具调用提取（最精准） ==========
    if update_data and "task" in update_data:
        task_data = update_data["task"]
    
    # ========== 第二层：从【任务进度】标签提取（正文标签兜底） ==========
    if not task_data:
        task_tag_match = re.search(r"【任务进度】\s*(.+?)(?=\n【|$)", reply_text, re.S)
        if task_tag_match:
            task_raw = task_tag_match.group(1).strip()
            
            # 修复1：兼容「→ 进度」「：进度」「直接进度」等多种分隔组合
            name_percent_match = re.search(r"^(.*?)\s*(?:→|：|:|—)?\s*进度?\s*(\d{1,3})\s*%", task_raw)
            # 修复2：阶段完整提取到行尾，不被逗号截断
            stage_match = re.search(
                r"(?:当前阶段|阶段)[:：]\s*(.+?)$",
                task_raw
            )
            
            if name_percent_match:
                task_name = name_percent_match.group(1).strip().strip("「」：:→/")
                percent = int(name_percent_match.group(2))
                stage = stage_match.group(1).strip() if stage_match else ""
                task_data = {
                    "name": task_name,
                    "stage": stage,
                    "percent": percent
                }
    
    # ========== 第三层：放宽JSON匹配，提取含task字段的任意JSON块 ==========
    if not task_data:
        # 匹配所有包含"task"的大括号块，不强制依赖reputation_delta
        json_blocks = re.findall(r'\{[^{}]*"task"[^{}]*\}', reply_text)
        for block in json_blocks:
            try:
                block_data = json.loads(block)
                if "task" in block_data and isinstance(block_data["task"], dict):
                    task_data = block_data["task"]
                    break
            except Exception:
                continue
    
    # ========== 第四层：全文本模糊匹配（纯自然语言兜底） ==========
    if not task_data:
        # 匹配模式：任务XXX进度XX% / XXX任务完成XX% / 任务1：35%
        fuzzy_match = re.search(r"(任务\s*\d+|「[^」]+」任务|[^\s，。]{2,10}任务?)\s*[:：\s]*.*?(\d{1,3})\s*%", reply_text)
        if fuzzy_match:
            task_name = fuzzy_match.group(1).strip().strip("「」：:")
            percent = int(fuzzy_match.group(2))
            # 百分比钳位
            if 0 <= percent <= 100:
                task_data = {
                    "name": task_name,
                    "stage": "",
                    "percent": percent
                }
    
    # ========== 统一执行任务更新 ==========
    if task_data and isinstance(task_data, dict):
        name = task_data.get("name", "").strip()
        stage = task_data.get("stage", "")
        percent = task_data.get("percent")
        
        if name and percent is not None:
            from task_manager import update_task_progress, _load_tasks
            
            # 任务名模糊匹配：支持编号、简称、全名
            tasks = _load_tasks()
            matched_task = None
            
# ========== 第一层：任务编号匹配（兼容所有常见格式） ==========
            # 兼容：任务1 / 1/任务名 / 1.任务名 / 1：任务名 / 「任务1」
            num_match = re.search(r"(?:任务\s*)?(\d+)\s*[/.：:、]", name)
            if not num_match:
                num_match = re.search(r"^(\d+)\s*[/.：:、]", name)
            if num_match:
                task_number = num_match.group(1).strip()
                for t in tasks:
                    if str(t.get("name", "")).strip() == task_number:
                        matched_task = t
                        break
            
            # ========== 第二层：名称双向模糊匹配（核心修复） ==========
            if not matched_task:
                # 深度清洗：去掉编号、斜杠、任务前缀、各类括号标点
                clean_name = re.sub(r'^\d+\s*[/.：:、]\s*', '', name).strip()
                clean_name = clean_name.replace("任务", "").strip("「」『』【】（）():：/·")
                
                for t in tasks:
                    task_name = t.get("name", "").strip()
                    if not clean_name or not task_name:
                        continue
                    # 双向包含匹配：长短文本都能命中，避免单向匹配失败
                    if clean_name in task_name or task_name in clean_name:
                        matched_task = t
                        break
                    # 额外匹配 display_name（AI可能传长描述而非简称）
                    disp = t.get("display_name", "")
                    if disp and (clean_name in disp or disp in clean_name):
                        matched_task = t
                        break
            
            # ========== 第三层：相似度兜底（极端模糊场景） ==========
            if not matched_task:
                best_score = 0
                best_task = None
                for t in tasks:
                    task_name = t.get("name", "")
                    if not task_name:
                        continue
                    # 简单字符重合度计算
                    common_chars = len(set(clean_name) & set(task_name))
                    score = common_chars / max(len(clean_name), len(task_name))
                    if score > best_score and score > 0.4:  # 重合度超40%才算
                        best_score = score
                        best_task = t
                if best_task:
                    matched_task = best_task

            # ========== 调试打印（方便定位，正常运行可注释） ==========
            if matched_task:
                print(f"[DEBUG 任务匹配] 原始名：{name} → 命中：{matched_task['name']}")
            else:
                print(f"[DEBUG 任务匹配失败] 原始名：{name}，未找到对应任务")
            
            if matched_task:
                # 查询任务类型（用于日志）
                task_type = "主线" if matched_task.get("type") == "main" else "支线"
                success = update_task_progress(matched_task["name"], stage=stage, percent=percent)
                if success:
                    icon = "⭐" if task_type == "主线" else "○"
                    stage_info = f"（{stage}）" if stage else ""
                    print(f"📋 {icon} {task_type}更新：{matched_task['name']} → {percent}% {stage_info}")
                else:
                    print(f"⚠️ 任务「{matched_task['name']}」更新失败")
            else:
                print(f"⚠️ 未匹配到对应任务：{name}")

    # ---- 6. 整体修为行（仅更新已有武功等级，不再新增） ----
    if not skip_overall_parse:
        level_match = re.search(r"整体修为[:：]\s*([^\n\r]+)", reply_text)
        if level_match:
            raw_overall = level_match.group(1).strip()
            raw_overall = re.sub(r'[、，；;|｜]', ' / ', raw_overall)
            raw_overall = re.sub(r'\s*/\s*', ' / ', raw_overall)
            raw_overall = re.sub(r'\s+', ' ', raw_overall).strip()
            parts = [p.strip() for p in raw_overall.split(' / ') if p.strip()]

            for part in parts:
                match = re.search(r'(.*?)\s*(' + '|'.join(player.REALM_LIST) + r')', part)
                if not match:
                    continue
                raw_name = match.group(1).strip()
                level_str = match.group(2).strip()
                if not raw_name:
                    continue

                # 清洗武功名（仅用于匹配）
                clean_name = re.sub(r'[（(『「【].*?[）)』」】]', '', raw_name).strip()
                clean_name = re.sub(r'[·、，。；：！？\s「」『』【】（）()]', '', clean_name)
                if not clean_name:
                    continue

                # ★ 只更新已有武功的等级，不再新增
                for sk in player.martial_skill_list:
                    if sk["skill_name"] == clean_name:
                        sk["skill_level"] = level_str
                        print(f"【整体修为更新等级】{clean_name} → {level_str}")
                        break

 # ---- 处理瓶颈进度（来自工具调用） ----
    bottleneck_delta = update_data.get("bottleneck_progress_delta")
    if bottleneck_delta is not None and isinstance(bottleneck_delta, int) and player.bottleneck_level > 0:
            # 单次感悟增量钳位：1~5 点，防止AI乱传大数
        bottleneck_delta = max(1, min(5, bottleneck_delta))
        new_progress = player.bottleneck_progress + bottleneck_delta
        threshold = player.get_bottleneck_threshold()
        if player.bottleneck_level == 6:
            if new_progress >= threshold:
                player.bottleneck_ready = True
                player.bottleneck_progress = threshold
                print("⚡ 终极瓶颈已满，等待AI触发突破！")
            else:
                player.bottleneck_progress = min(threshold, new_progress)
        else:
            if new_progress >= threshold:
                player.bottleneck_ready = True
                player.bottleneck_progress = threshold
                print("✅ 瓶颈进度已满，准备突破！")
            else:
                player.bottleneck_progress = new_progress
        player.save()

    # ---- ★ 新增：主角自身状态更新（来自工具调用） ----
    new_self_state = update_data.get("self_state", "").strip()
    if new_self_state and new_self_state != player.self_state:
        player.self_state = new_self_state
        print(f"【自身状态变更】{new_self_state}")
    # ---- 6.5 小说节点更新（来自工具调用） ----
    new_novel_node = update_data.get("novel_node", "").strip()
    if new_novel_node and new_novel_node != player.novel_node:
        player.novel_node = new_novel_node
        print(f"【小说节点更新】{new_novel_node}")
    # ---- 7. 最终同步 ----
    player.sync_overall_level()
    player.save()

    # ---- 8. 瓶颈检测与重置（仅处理突破，不再处理进度） ----
    player.update_bottleneck_status()

    return {
        "exp_gain_lines": exp_gain_lines,
        "exp_update_lines": exp_update_lines,
    }


    
def parse_and_update_npc_state(reply_text: str, tool_calls=None, user_action=""):
    npc_data = load_json(NPC_AGENT_FILE)
    if not npc_data or "npc_list" not in npc_data:
        return

    # 兼容旧存档：补全缺失字段
    for npc in npc_data["npc_list"]:
        if "body_status" not in npc:
            npc["body_status"] = "normal"
        if "body_status_desc" not in npc:
            npc["body_status_desc"] = ""
        if "relation_to_player" not in npc:
            npc["relation_to_player"] = ""

    # 记录已被工具调用更新过的NPC，正则兜底不再处理
    tool_updated_npcs = set()

    # ========== 第一层：工具调用捕获状态（最高优先级，直接修改内存） ==========
    if tool_calls:
        for tc in tool_calls:
            if tc.function.name == "update_game_state":
                try:
                    args = json.loads(tc.function.arguments)
                    # 读取身体情况
                    status_list = args.get("npc_status_update", [])
                    if status_list and isinstance(status_list, list):
                        for item in status_list:
                            name = item.get("name", "").strip()
                            status = item.get("status", "")
                            desc = item.get("desc", "")
                            if not name or not status:
                                continue
                            # 直接修改内存中的NPC数据
                            for npc in npc_data["npc_list"]:
                                if npc["name"] == name:
                                    # ===== 新增：已故NPC禁止任何状态变更 =====
                                    if npc.get("body_status") == "deceased":
                                        print(f"{COLOR_WARN}⚠️ 已故NPC「{name}」禁止更改状态，忽略本次更新{COLOR_END}")
                                        break
                                    npc["body_status"] = status
                                    npc["body_status_desc"] = desc.strip()
                                    append_npc_memory(name, user_action, npc_data=npc_data)
                                    tool_updated_npcs.add(name)
                                    # 打印日志（和原函数保持一致）
                                    status_cn = {
                                        "normal": "健康",
                                        "light_injured": "轻伤",
                                        "heavy_injured": "重伤",
                                        "dying": "濒死",
                                        "deceased": "已故",
                                        "poisoned": "中毒"
                                    }
                                    show_desc = f"（{desc}）" if desc else ""
                                    print(f"{COLOR_GREEN}✅ NPC「{name}」状态已设为：{status_cn.get(status, status)}{show_desc}{COLOR_END}")
                                    break
                                                # ========== 新增：NPC好感度更新 ==========
                    favor_list = args.get("npc_favor_update", [])
                    if favor_list and isinstance(favor_list, list):
                        for item in favor_list:
                            name = item.get("name", "").strip()
                            delta = item.get("delta", 0)
                            if not name or not isinstance(delta, int) or delta == 0:
                                continue
                            # 数值钳位：单次波动限制在 ±10 以内，防止AI乱传大数
                            delta = max(-10, min(10, delta))
                            # 直接调用已有函数更新好感并追加记忆
                            append_npc_memory(name, user_action, npc_data=npc_data)
                            modify_npc_favor(name, delta, npc_data=npc_data)
                            tool_updated_npcs.add(name)  # 标记为已工具更新，后续正则不再重复处理
                            print(f"{COLOR_GREEN}✅ NPC「{name}」好感度 {delta:+d}{COLOR_END}")
                    # ========== 新增：NPC关系描述更新 ==========
                    relation_list = args.get("npc_relationship_update", [])
                    if relation_list and isinstance(relation_list, list):
                        for item in relation_list:
                            rname = item.get("name", "").strip()
                            rrel = item.get("relation", "").strip()
                            if not rname or not rrel:
                                continue
                            for npc in npc_data["npc_list"]:
                                if npc["name"] == rname:
                                    npc["relation_to_player"] = rrel[:8]
                                    append_npc_memory(rname, user_action, npc_data=npc_data)
                                    print(f"{COLOR_GREEN}✅ NPC「{rname}」关系→{rrel}{COLOR_END}")
                                    break
                except Exception:
                    pass

    # ===== 正则兜底：AI文本中的好感变化（仅处理工具未覆盖的NPC） =====
    favor_text_match = re.findall(r"(.+?)：好感度?\s*([+-])\s*(\d+)", reply_text)
    for n_name, symbol, num in favor_text_match:
        n_name = n_name.strip()
        # 去掉可能的标签前缀（【NPC状态变动】等）
        n_name = re.sub(r'【[^】]+】', '', n_name).strip()
        if not n_name or n_name in tool_updated_npcs:
            continue  # 工具已处理或无有效名称，跳过
        try:
            delta = int(num) if symbol == "+" else -int(num)
            append_npc_memory(n_name, user_action, npc_data=npc_data)
            modify_npc_favor(n_name, delta, npc_data=npc_data)
            print(f"{COLOR_GREEN}✅ NPC「{n_name}」好感度 {delta:+d}（正则兜底）{COLOR_END}")
        except Exception as e:
            print(f"{COLOR_WARN}⚠️ 正则兜底异常 {n_name}：{e}{COLOR_END}")

    # ---------- 1. 处理已有NPC的好感/记忆/性格/身份（原有逻辑不变） ----------
    npc_pattern = re.compile(r"【NPC变更】(.+?)\|(.+?)\|(.+?)\|(.+?)\|(.+?)(?=\n【|$)", re.S)
    matches = npc_pattern.findall(reply_text)
    for name, favor_delta, new_memory, char_change, id_change in matches:
        name = name.strip()
        target_npc = None
        for npc in npc_data["npc_list"]:
            if npc.get("name") == name:
                target_npc = npc
                break
        if not target_npc:
            continue
        if favor_delta:
            try:
                delta_val = int(favor_delta)
                # 原代码：target_npc["initial_favor"] = max(0, min(100, target_npc["initial_favor"] + delta_val))
                target_npc["initial_favor"] = max(-100, min(100, target_npc["initial_favor"] + delta_val))
            except ValueError:
                pass

        if new_memory and new_memory.strip() not in ["无", "（无）", "(无)", "无。"] and not new_memory.strip().startswith("无"):
            if new_memory not in target_npc["memory_list"]:
                target_npc["memory_list"].append(new_memory)
        if char_change and char_change != "无":
            target_npc["personality"] = char_change
        if id_change and id_change != "无":
            target_npc["identity"] = id_change

    # ---------- 2. 处理新增NPC（原有逻辑不变） ----------
    new_npc_pattern = re.compile(r"【新NPC】(.+?)\|(.+?)\|(.+?)\|(\d+)(?=\n【|$)", re.S)
    new_matches = new_npc_pattern.findall(reply_text)
    for name, identity, personality, initial_favor in new_matches:
        name = name.strip()
        identity = identity.strip()
        personality = personality.strip()
        try:
            favor = int(initial_favor.strip())
        except ValueError:
            favor = 15
        exists = any(npc.get("name") == name for npc in npc_data["npc_list"])
        if exists:
            continue
        new_npc = {
            "name": name,
            "identity": identity,
            "personality": personality,
            "life_experience": "",
            "secret": "",
            "initial_favor": max(-100, min(100, favor)),
            "memory_list": [],
            "martial_skills": [],
            "body_status": "normal",
            "body_status_desc": "",
            "relation_to_player": ""
        }
        npc_data["npc_list"].append(new_npc)
        print(f"{COLOR_GREEN}✅ 新增NPC：{name}（{identity}）{COLOR_END}")

    # ========== 第二层：正文正则兜底（仅工具未处理的NPC生效） ==========
    severity = {
        "normal": 0,
        "light_injured": 1,
        "poisoned": 2,
        "heavy_injured": 3,
        "dying": 4,
        "deceased": 5
    }
    status_rules = [
        ("normal", ["伤势痊愈", "恢复如初", "已然痊愈", "毒已解", "伤势大好", "身体恢复", "伤愈"]),
        ("deceased", ["身亡", "毙命", "当场死去", "气绝身亡", "不治身亡", "已死", "死去", "丧命"]),
        ("dying", ["性命垂危", "奄奄一息", "濒死", "只剩一口气", "危在旦夕"]),
        ("heavy_injured", ["身受重伤", "重伤", "伤势不轻", "遍体鳞伤", "断了", "碎了","呕血", "口吐鲜血"]),
        ("light_injured", ["受了轻伤", "轻伤", "擦破", "划伤", "皮肉伤"]),
        ("poisoned", ["身中剧毒", "中毒", "毒发", "中了毒"])
    ]
    deny_words = ["听说", "传言", "据说", "仿佛", "好似", "以为", "传闻", "回忆", "梦中", "如果", "倘若"]

    # 先收集每个NPC匹配到的最严重状态
    npc_final_status = {}  # {npc_name: (status, keyword)}
    for status, keywords in status_rules:
        for kw in keywords:
            for npc in npc_data["npc_list"]:
                name = npc["name"]
                # 工具已更新的NPC直接跳过
                if name in tool_updated_npcs:
                    continue
                if name not in reply_text:
                    continue
                pattern = f"{name}[^。！？]*?{kw}"
                match = re.search(pattern, reply_text)
                if not match:
                    continue
                sentence = match.group(0)
                if any(w in sentence for w in deny_words):
                    continue
                current_sev = severity.get(status, 0)
                # 只保留最严重的状态
                if name not in npc_final_status or current_sev > severity.get(npc_final_status[name][0], 0):
                    npc_final_status[name] = (status, kw)

    # 统一应用到内存数据
    status_cn = {
        "normal": "健康",
        "light_injured": "轻伤",
        "heavy_injured": "重伤",
        "dying": "濒死",
        "deceased": "已故",
        "poisoned": "中毒"
    }
    for name, (status, kw) in npc_final_status.items():
        for npc in npc_data["npc_list"]:
            if npc["name"] == name:
                current_status = npc.get("body_status", "normal")
                # ===== 修改：已故NPC禁止任何状态更新（不仅仅是normal） =====
                if current_status == "deceased":
                # 已故角色绝对禁止更改任何状态（无论是受伤还是恢复）
                    break
                # 状态无变化跳过
                if current_status == status:
                    break
                # 死亡状态禁止正则自动复活
                if current_status == "deceased" and status == "normal":
                    break
                npc["body_status"] = status
                npc["body_status_desc"] = kw
                print(f"{COLOR_GREEN}✅ NPC「{name}」状态已设为：{status_cn[status]}（{kw}）{COLOR_END}")
                break

    # ---------- 3. 限制NPC记忆数量（原有逻辑不变） ----------
    for npc in npc_data["npc_list"]:
        if "memory_list" in npc and len(npc["memory_list"]) > 100:
            npc["memory_list"] = npc["memory_list"][-100:]

    # 最后统一保存一次文件（所有修改都在内存里，不会再被覆盖）
    save_json(NPC_AGENT_FILE, npc_data)

# ===================== 世界观构建（优化版） =====================
# ===================== 世界观构建（Function Calling + 回退） =====================
def build_novel_world():
    """
    构建武侠世界观
    优先方式：Function Calling（结构化输出，永不格式错误）
    回退方式：常规 JSON 提取
    终极兜底：预设通用世界观
    """
    # 1. 如果已存在，直接加载
    if os.path.exists(WORLD_FILE):
        data = load_json(WORLD_FILE)
        if data and isinstance(data, dict):
            return data

    local_story = read_raw_story()
    
    # ===== 2. 尝试 Function Calling =====
    print(f"{COLOR_SYSTEM}🔄 正在通过 AI 生成世界观（Function Calling）...{COLOR_END}")
    
    # 定义工具
    world_tool = {
        "type": "function",
        "function": {
            "name": "generate_world_setting",
            "description": "根据武侠小说原文生成完整的世界观设定。",
            "parameters": {
                "type": "object",
                "properties": {
                    "world_name": {
                        "type": "string",
                        "description": "世界名称，如'笑傲江湖'、'射雕英雄传'等"
                    },
                    "background_history": {
                        "type": "string",
                        "description": "世界起源、远古历史、重大过往事件，200字以内"
                    },
                    "geography_region": {
                        "type": "string",
                        "description": "地域分布、主要宗门、城池、秘境，150字以内"
                    },
                    "power_system": {
                        "type": "string",
                        "description": "修炼等级、力量规则、功法体系，100字以内"
                    },
                    "major_faction": {
                        "type": "string",
                        "description": "各大势力阵营、矛盾关系，100字以内"
                    },
                    "world_rules": {
                        "type": "string",
                        "description": "世界底层法则、江湖禁忌、道德准则，80字以内"
                    },
                    "core_plot_background": {
                        "type": "string",
                        "description": "原著核心主线冲突、主角宿命与身世设定，150字以内"
                    }
                },
                "required": [
                    "world_name", "background_history", "geography_region",
                    "power_system", "major_faction", "world_rules", "core_plot_background"
                ]
            }
        }
    }

    try:
        # 调用 AI（强制使用工具，并给予足够的 token）
        response = llm_call_common(
            sys_prompt="你是一位专业的武侠世界观构建师。请根据用户提供的小说原文，提取并生成完整的世界观设定。你只需要调用工具，不要输出任何其他文字、注释或说明。",
            user_prompt=f"请根据以下小说原文生成武侠世界观设定：\n\n{local_story}" if local_story else "请生成一个经典的武侠世界观设定。",
            temp=0.4,
            timeout=60,
            tools=[world_tool],
            tool_choice={"type": "function", "function": {"name": "generate_world_setting"}},
            max_tokens=2048  # 确保有足够空间生成完整内容
        )
        
        # 提取工具调用参数
        tool_calls = response.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                if tc.function.name == "generate_world_setting":
                    try:
                        world_data = json.loads(tc.function.arguments)
                        # 检查必要字段
                        required = [
                            "world_name", "background_history", "geography_region",
                            "power_system", "major_faction", "world_rules", "core_plot_background"
                        ]
                        if all(k in world_data and world_data[k] for k in required):
                            save_json(WORLD_FILE, world_data)
                            print(f"{COLOR_SYSTEM}✅ 基于本地文本生成世界观（Function Calling）{COLOR_END}")
                            return world_data
                        else:
                            missing = [k for k in required if k not in world_data or not world_data[k]]
                            print(f"[WARN] 工具调用返回字段不完整，缺失: {missing}")
                    except json.JSONDecodeError as e:
                        print(f"[WARN] 工具调用参数 JSON 解析失败: {e}")
    except Exception as e:
        print(f"[WARN] Function Calling 失败: {e}")

    # ===== 3. 回退方案：常规 JSON 提取 =====
    print(f"{COLOR_SYSTEM}🔄 Function Calling 失败，尝试常规 JSON 提取...{COLOR_END}")
    
    if local_story:
        system = """
【任务】根据用户提供的武侠小说原文，生成以下世界观 JSON。
【规则】
1. 严格依据原文提取，原文未提及的内容可基于武侠常识合理补齐。
2. 仅输出标准 JSON，禁止多余文字、注释、markdown。
3. 如果原文为空，则生成通用武侠世界观。

JSON结构必须严格为（注意各字段字数上限）：
{
  "world_name": "世界名称",
  "background_history": "世界起源、远古历史、重大过往事件，200字以内",
  "geography_region": "地域、宗门、城池、秘境分布，150字以内",
  "power_system": "修炼等级、力量规则、功法体系，100字以内",
  "major_faction": "各大势力阵营、矛盾关系，100字以内",
  "world_rules": "世界底层法则、禁忌约束，80字以内",
  "core_plot_background": "原著核心主线冲突、主角宿命与身世设定，150字以内"
}
"""
        raw_response = llm_call_common(system, local_story, temp=0.4, max_tokens=2048)
        raw_text = get_llm_content(raw_response)
        
        # 使用增强的提取和解析
        world_data = _extract_and_parse_world_json(raw_text)
        if world_data:
            save_json(WORLD_FILE, world_data)
            if local_story:
                print(f"{COLOR_SYSTEM}✅ 基于本地文本生成世界观（常规提取）{COLOR_END}")
            else:
                print(f"{COLOR_SYSTEM}✅ 生成通用武侠世界观（常规提取）{COLOR_END}")
            return world_data

    # ===== 4. 终极兜底 =====
    print(f"{COLOR_WARN}【所有方法失败】加载本地兜底通用世界观{COLOR_END}")
    
    fallback = {
        "world_name": "未知武侠世界",
        "background_history": "江湖风云变幻，恩怨情仇交织，正邪纷争从未停歇。各大门派林立，侠客浪子辈出，暗中更有神秘势力蠢蠢欲动。",
        "geography_region": "中原、江南、塞北、西域等广袤地域，分布着少林、武当、峨眉等名门正派，也有黑木崖、恶人谷等凶险之地。",
        "power_system": "内功修为分十四档七层：入门(初学入门/初窥门径)、小成(略有小成/略有所成)、中坚(渐入佳境/融会贯通)、一流(登堂入室/炉火纯青)、绝顶(出神入化/登峰造极)、宗师(超凡入圣/返璞归真)、传说(天人合一/破碎虚空)。掌门按江湖地位分三档：名门掌门(7-8档,如胡一刀/苗人凤)、中等门派掌门(6档,如马行空/田归农)、地方小派掌门(5档,如蓝秦/桑飞虹)。外功招式各具特色，轻功、暗器、毒术亦为江湖一绝。",
        "major_faction": "正道以少林、武当为首，邪派有魔教、五毒教等，另有镖局、帮派、山寨等势力盘踞，朝廷与武林明争暗斗。",
        "world_rules": "江湖规矩以实力为尊，门派传承、恩怨报应、侠义道统皆为准则；禁忌包括背叛师门、滥杀无辜、使用禁术等。",
        "core_plot_background": "玩家初入江湖，身世成谜，在风云诡谲的武林中探索真相，习武历练，结交侠客，揭开上古秘宝与惊天阴谋。"
    }
    save_json(WORLD_FILE, fallback)
    return fallback


def _extract_and_parse_world_json(raw_text: str):
    """
    从 AI 原始回复中提取并解析世界观 JSON
    支持多层容错
    """
    if not raw_text:
        return None
    
    # 1. 提取最外层 JSON
    def extract_json(text):
        if not text:
            return ""
        # 去除 markdown
        text = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", text).strip()
        
        # 查找最外层大括号
        brace_count = 0
        start = -1
        end = -1
        for i, ch in enumerate(text):
            if ch == '{':
                if brace_count == 0:
                    start = i
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0 and start != -1:
                    end = i + 1
                    break
        
        if start != -1 and end != -1:
            return text[start:end]
        
        # 如果找不到大括号，尝试找中括号（数组）
        bracket_count = 0
        start = -1
        end = -1
        for i, ch in enumerate(text):
            if ch == '[':
                if bracket_count == 0:
                    start = i
                bracket_count += 1
            elif ch == ']':
                bracket_count -= 1
                if bracket_count == 0 and start != -1:
                    end = i + 1
                    break
        
        if start != -1 and end != -1:
            return text[start:end]
        return ""
    
    # 2. 使用现有的 clean_json 清洗
    extracted = extract_json(raw_text)
    if not extracted:
        return None
    
    cleaned = clean_json(extracted)
    if not cleaned:
        return None
    
    # 3. 尝试解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # 4. 尝试 ast.literal_eval
    try:
        import ast
        obj = ast.literal_eval(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    
    # 5. 尝试正则提取（最后手段）
    try:
        result = {}
        keys = ["world_name", "background_history", "geography_region", 
                "power_system", "major_faction", "world_rules", "core_plot_background"]
        for key in keys:
            pattern = f'"{key}"\\s*:\\s*"([^"]*)"'
            match = re.search(pattern, cleaned)
            if match:
                result[key] = match.group(1)
            else:
                # 尝试匹配带中文引号的
                pattern_cn = f'"{key}"\\s*:\\s*"([^"]*)"'
                match_cn = re.search(pattern_cn, cleaned)
                if match_cn:
                    result[key] = match_cn.group(1)
        if all(k in result for k in keys):
            return result
    except Exception:
        pass
    
    return None
# ===================== NPC生成核心函数【全文切片分批提取+同名NPC合并去重 完整版】 =====================
def init_npc_agents(force_regen: bool = False):
    # 非强制重新生成且文件已存在，直接加载旧存档
    if not force_regen and os.path.exists(NPC_AGENT_FILE):
        old_data = load_json(NPC_AGENT_FILE)
        # 在 init_npc_agents 函数中，加载旧数据后
        if old_data and "npc_list" in old_data:
            updated = False
            for npc in old_data["npc_list"]:
                # ========== 新增：统一身体状态字段（从头初始化，兼容旧存档） ==========
                if "body_status" not in npc:
                    npc["body_status"] = "normal"       # 默认健康正常
                    npc["body_status_desc"] = ""         # 状态补充描述（受伤原因、死因等）
                    updated = True
                # 清理 memory_list：删除所有以 "无" 开头的条目（或纯占位符）
                if "memory_list" in npc:
                    original_len = len(npc["memory_list"])
                    npc["memory_list"] = [
                        m for m in npc["memory_list"]
                        if m and not m.strip().startswith("无") and m.strip() not in ["无", "（无）", "(无)", "无。"]
                    ]
                if len(npc["memory_list"]) != original_len:
                        updated = True
        
                # 清理 martial_skills（已有）
                if "martial_skills" in npc:
                    npc["martial_skills"] = [sk for sk in npc["martial_skills"] if sk.get("skill_name")]
        
                # 补全字段（已有）
                if "martial_skills" not in npc:
                    npc["martial_skills"] = []
                    updated = True
                if "relation_to_player" not in npc:
                    npc["relation_to_player"] = ""
                    updated = True
    
            if updated:
                save_json(NPC_AGENT_FILE, old_data)
                print(f"{COLOR_SYSTEM}✅ 已清理NPC档案中的无效数据并补全字段{COLOR_END}")
            return old_data
    # ... 后面是重新生成的逻辑不变
    full_text = read_raw_story()
    total_len = len(full_text)
    all_npc_map = {}
    # 原文为空兜底
    if total_len == 0:
        print(f"{COLOR_YELLOW}📄 原著文本为空，直接生成默认NPC模板{COLOR_END}")
        default_npc = {
            "npc_list": [
                {
                    "name": "宗门长老",
                    "identity": "宗门管事",
                    "personality": "稳重古板，秉公处事",
                    "life_experience": "修行多年，坐镇山门",
                    "secret": "暗中培养传人",
                    "initial_favor": 15,
                    "memory_list": [],
                    "martial_skills": [{"skill_name": "基础内功", "skill_level": "筑基后期"}],
                    "relation_to_player": ""
                }
            ]
        }
        save_json(NPC_AGENT_FILE, default_npc)
        return default_npc
    # 1、全文按CHUNK_SIZE自动切片
    chunks = []
    start = 0
    while start < total_len:
        end = start + CHUNK_SIZE
        chunks.append(full_text[start:end])
        start = end
    chunk_count = len(chunks)
    print(f"{COLOR_SYSTEM}📚 全文总字符：{total_len}，自动切分为 {chunk_count} 段分批提取角色{COLOR_END}")
    # 单段提取提示词
    extract_prompt = """
你只提取本段文字内出现的人物，输出JSON格式，外层key为npc_list。
单个人物结构：
{
    "name": "姓名",
    "identity": "身份",
    "personality": "性格特点",
    "life_experience": "本段相关经历",
    "secret": "本段体现的隐秘心事",
    "initial_favor": 15,
    "memory_list": [],
    "martial_skills": [{"skill_name":"功法名","skill_level":"修为水平"}]
}
要求：
1. 只出现本段出现的角色，不要编造不存在人物
2. 只返回纯净JSON，不要任何解释、前言、markdown标记
"""
    # 2、逐段调用AI提取本段NPC
    for idx, seg_text in enumerate(chunks, 1):
        print(f"\n{COLOR_GREEN}—————— 正在处理第 {idx}/{chunk_count} 文本片段 ——————{COLOR_END}")
        raw_resp = llm_call_npc_gen(extract_prompt, seg_text)
        print(f"[DEBUG] raw_resp 长度: {len(raw_resp)}，前200字符: {raw_resp[:200]}")
        clean_txt = clean_json(raw_resp)
        seg_npc_list = []
        try:
            seg_data = json.loads(clean_txt)
            seg_npc_list = seg_data.get("npc_list", [])
            print(f"{COLOR_SYSTEM}本段识别到 {len(seg_npc_list)} 名角色{COLOR_END}")
        except Exception as e:
            print(f"{COLOR_WARN}本段JSON解析失败，跳过本段：{e}{COLOR_END}")
            continue
        # 3、全局字典合并同名NPC，信息拼接、武功去重
        for npc in seg_npc_list:
            n_name = npc.get("name", "").strip()
            if not n_name:
                continue
            if n_name not in all_npc_map:
                all_npc_map[n_name] = npc
            else:
                old = all_npc_map[n_name]
                # 生平、性格、隐秘拼接
                old["life_experience"] = old["life_experience"] + "；" + npc.get("life_experience", "")
                old["personality"] = old["personality"] + " " + npc.get("personality", "")
                old["secret"] = old["secret"] + " " + npc.get("secret", "")
                # 武功去重追加
                exist_skill_names = [s["skill_name"] for s in old["martial_skills"]]
                for sk in npc.get("martial_skills", []):
                    if sk["skill_name"] not in exist_skill_names:
                        old["martial_skills"].append(sk)
    # 4、汇总最终NPC列表
    final_npc_list = list(all_npc_map.values())
    # 全文一个角色都没识别到兜底
    if not final_npc_list:
        print(f"{COLOR_WARN}❌ 全文分段提取后未识别到任何角色，启用兜底NPC{COLOR_END}")
        final_npc_list = [
            {
                "name": "宗门长老",
                "identity": "宗门管事",
                "personality": "稳重古板，秉公处事",
                "life_experience": "修行多年，坐镇山门",
                "secret": "暗中培养传人",
                "initial_favor": 15,
                "memory_list": [],
                "martial_skills": [{"skill_name": "基础内功", "skill_level": "筑基后期"}],
                "relation_to_player": ""
            }
        ]
    result_data = {"npc_list": final_npc_list}
    save_json(NPC_AGENT_FILE, result_data)
    print(f"\n{COLOR_GREEN}✅ 分段提取完成，总共识别汇总 {len(final_npc_list)} 名角色，已写入npc_agents.json{COLOR_END}")
    return result_data
def modify_npc_favor(npc_name, delta, npc_data=None):
    # 如果传入了npc_data，直接修改内存（由调用方统一save）
    if npc_data is not None:
        for npc in npc_data.get("npc_list", []):
            if npc["name"] == npc_name:
                npc["initial_favor"] = max(-100, min(100, npc["initial_favor"] + delta))
                return
        return
    # 回退：独立load/save（兼容外部调用）
    npc_all = load_json(NPC_AGENT_FILE)
    if not npc_all or "npc_list" not in npc_all:
        return
    for npc in npc_all["npc_list"]:
        if npc["name"] == npc_name:
            new_val = npc["initial_favor"] + delta
            # 原代码：npc["initial_favor"] = max(0, min(100, new_val))
            npc["initial_favor"] = max(-100, min(100, new_val))
            break
    save_json(NPC_AGENT_FILE, npc_all)
def add_npc_manual(name, identity="江湖人士", personality="", initial_favor=15):
    """手动添加NPC到npc_agents.json，已存在则拒绝"""
    npc_all = load_json(NPC_AGENT_FILE) or {"npc_list": []}
    for npc in npc_all.get("npc_list", []):
        if npc["name"] == name:
            return False, f"❌ NPC「{name}」已存在"
    npc_all["npc_list"].append({
        "name": name, "identity": identity, "personality": personality,
        "life_experience": "", "secret": "",
        "initial_favor": max(-100, min(100, initial_favor)),
        "memory_list": [], "martial_skills": [],
        "body_status": "normal", "body_status_desc": "",
        "relation_to_player": ""
    })
    save_json(NPC_AGENT_FILE, npc_all)
    return True, f"✅ NPC「{name}」已添加"
def append_npc_memory(npc_name, content, reason="", npc_data=None):
    full_text = f"{content}（{reason}）" if reason else content
    # 获取当前剧情节点
    _nn = ""
    try:
        _p = get_player()
        if _p and _p.novel_node:
            _nn = _p.novel_node
    except Exception:
        pass
    # 如果传入了npc_data，直接修改内存（由调用方统一save）
    if npc_data is not None:
        for npc in npc_data.get("npc_list", []):
            if npc["name"] == npc_name:
                if npc["memory_list"] and npc["memory_list"][-1] == full_text:
                    return  # 同轮重复变动跳过
                npc["memory_list"].append(full_text)
                if len(npc["memory_list"]) > 25:
                    npc["memory_list"] = npc["memory_list"][-25:]
                break
        try:
            upload_npc_memory(CLOUD_MEM_SLOT_ID, npc_name, full_text, novel_node=_nn)
        except Exception as e:
            print(f"{COLOR_WARN}⚠️ 上传NPC记忆失败: {e}{COLOR_END}")
        return
    # 回退：独立load/save（兼容外部调用）
    npc_all = load_json(NPC_AGENT_FILE)
    if not npc_all or "npc_list" not in npc_all:
        return
    for npc in npc_all["npc_list"]:
        if npc["name"] == npc_name:
            if npc["memory_list"] and npc["memory_list"][-1] == full_text:
                return
            npc["memory_list"].append(full_text)
            if len(npc["memory_list"]) > 25:
                npc["memory_list"] = npc["memory_list"][-25:]
            break
    save_json(NPC_AGENT_FILE, npc_all)
    try:
        upload_npc_memory(CLOUD_MEM_SLOT_ID, npc_name, full_text, novel_node=_nn)
    except Exception as e:
        print(f"{COLOR_WARN}⚠️ 上传NPC记忆失败: {e}{COLOR_END}")
def update_npc_skill(npc_name, skill_name, new_level):
    npc_all = load_json(NPC_AGENT_FILE)
    if not npc_all or "npc_list" not in npc_all:
        return
    for npc in npc_all["npc_list"]:
        if npc["name"] == npc_name:
            exist = False
            for sk in npc["martial_skills"]:
                if sk["skill_name"] == skill_name:
                    sk["skill_level"] = new_level
                    exist = True
                    break
            if not exist:
                npc["martial_skills"].append({"skill_name": skill_name, "skill_level": new_level})
            break
    save_json(NPC_AGENT_FILE, npc_all)
    
# ========== 新增：NPC身体状态统一设置函数 ==========
def set_npc_body_status(npc_name, status="normal", desc=""):
    """
    设置NPC身体状态（统一入口）
    :param npc_name: NPC姓名
    :param status: 状态枚举：normal/light_injured/heavy_injured/dying/deceased/poisoned
    :param desc: 状态补充描述，如“被黑衣人砍伤左臂”
    """
    npc_all = load_json(NPC_AGENT_FILE)
    if not npc_all or "npc_list" not in npc_all:
        return False

    # 合法状态校验
    valid_status = ["normal", "light_injured", "heavy_injured", "dying", "deceased", "poisoned"]
    if status not in valid_status:
        print(f"{COLOR_WARN}⚠️ 无效状态值，仅支持：{', '.join(valid_status)}{COLOR_END}")
        return False

    # 状态对应的中文显示
    status_cn = {
        "normal": "健康",
        "light_injured": "轻伤",
        "heavy_injured": "重伤",
        "dying": "濒死",
        "deceased": "已故",
        "poisoned": "中毒"
    }

    for npc in npc_all["npc_list"]:
        if npc["name"] == npc_name:
            npc["body_status"] = status
            npc["body_status_desc"] = desc.strip()
            save_json(NPC_AGENT_FILE, npc_all)
            show_desc = f"（{desc}）" if desc else ""
            print(f"{COLOR_GREEN}✅ NPC「{npc_name}」状态已设为：{status_cn[status]}{show_desc}{COLOR_END}")
            return True

    print(f"{COLOR_WARN}⚠️ 未找到 NPC「{npc_name}」{COLOR_END}")
    return False

def handle_admin_commands(user_input: str):
  
    user_input = user_input.strip()
      # 0. 帮助/指令说明
    if user_input in ["帮助", "指令", "管理指令", "help"]:
        help_msg = """【NPC管理指令用法】
设置NPC状态 角色名 状态值 描述
支持状态：normal/light_injured/heavy_injured/dying/deceased/poisoned
示例：设置NPC状态 仪琳 dying 被从二楼掷下，全身重伤

治愈NPC 角色名 [描述]
示例：治愈NPC 仪琳 伤势痊愈"""
        return True, help_msg
    # 1. 设置NPC身体状态
    if user_input.startswith("设置NPC状态"):
        parts = user_input.split(maxsplit=3)
        if len(parts) >= 3:
            name = parts[1].strip()
            status = parts[2].strip()
            desc = parts[3].strip() if len(parts) >= 4 else ""
            success = set_npc_body_status(name, status, desc)
            if success:
                return True, f"✅ NPC「{name}」状态已更新为：{status}"
            else:
                return True, "❌ 设置失败，未找到NPC或状态值无效"
        else:
            return True, "⚠️ 用法：设置NPC状态 角色名 状态值 描述\n支持状态：normal/light_injured/heavy_injured/dying/deceased/poisoned"
    
    # 2. 快速治愈NPC
    if user_input.startswith("治愈NPC"):
        parts = user_input.split(maxsplit=2)
        if len(parts) >= 2:
            name = parts[1].strip()
            desc = parts[2].strip() if len(parts) >= 3 else "伤势痊愈"
            success = set_npc_body_status(name, "normal", desc)
            if success:
                return True, f"✅ NPC「{name}」已恢复健康"
            else:
                return True, "❌ 治愈失败，未找到该NPC"
        else:
            return True, "⚠️ 用法：治愈NPC 角色名"
    
    # 未命中任何管理指令
    return False, ""

# ===================== 玩家档案 =====================
latest_plot1_text = ""
_plot_text_lock = threading.Lock()  # latest_plot1_text 的线程安全锁

def create_player_profile(name: str, origin: str, ability: str):
    player = Player.create_new(name, origin, ability)
    set_player(player)
    # 初始感悟（AI生成）
    prompt = f"玩家本命功法为「{ability}」，请为这门功法生成一段初始感悟文字（20~30字），描述初学时的体会。只输出文字，不要其他。"
    try:
        initial_text = get_llm_content(llm_call_common("", prompt, temp=0.7))
        if initial_text and len(initial_text) > 5:
            player.update_exp_text(ability, initial_text.strip())
            player.save()
    except Exception as e:
        print(f"{COLOR_WARN}⚠️ 生成初始感悟失败: {e}{COLOR_END}")
    print(f"\n{COLOR_SYSTEM}✅ 主角档案创建完成！开始首次练功...{COLOR_END}")
    success, msg = do_practice(is_first_init=True)
    if success:
        print(f"{COLOR_GREEN}✅ 首次练功结果：{msg}{COLOR_END}")
    else:
        print(f"{COLOR_WARN}⚠️ 首次练功异常：{msg}{COLOR_END}")
    return player
def init_player():
    player = Player.load()
    if player:
        # 执行清理操作（保证数据干净）
        player.rumor_list = [
            r for r in player.rumor_list
            if r and r.strip() not in ["（无）", "无", "(无)"] and not r.strip().startswith("（无）")
        ]
        player.item_list = [
            c for i in player.item_list
            if i and isinstance(i, str) and (c := _clean_item_name(i))
        ]
        player.martial_skill_list = [sk for sk in player.martial_skill_list if sk.get("skill_name")]
        # 补全缺失字段
        if not player.martial_skill_list:
            player.martial_skill_list = []
        if not player.overall_martial_level:
            player.overall_martial_level = "初窥门径"
        if "age" not in player._data:
            player._data["age"] = 0
        player.save()
        set_player(player)
        return player

    print(f"{COLOR_SYSTEM}==== 初始化主角完整档案（含武功库） ===={COLOR_END}")
    name = input("主角姓名：")
    origin = input("原著身世背景：")
    ability = input("核心天赋/本命功法：")
    return create_player_profile(name, origin, ability)
    
def update_player_state(item_change, state_change, overall_level="", new_rumor="", skill_update_list=None):
    player = get_player()
    if not player:
        return

    if state_change.strip() != "":
        player.self_state = state_change

    if isinstance(item_change, list):
        for item in item_change:
            player.add_item(item)

    if overall_level.strip() != "":
        player.overall_martial_level = overall_level
        # 如果没有指定具体功法，则自动同步主修功法
        if not skill_update_list and player.martial_skill_list:
            max_skill = max(player.martial_skill_list, key=lambda x: x.get("skill_level", "初窥门径"))
            if max_skill["skill_level"] != overall_level:
                max_skill["skill_level"] = overall_level
                print(f"{COLOR_CHANGE}【联动】主修功法《{max_skill['skill_name']}》自动同步至 {overall_level}{COLOR_END}")

    if new_rumor and new_rumor.strip() and new_rumor.strip() != "无":
        rumor_text = new_rumor.strip()
        player.add_rumor(rumor_text)
        upload_rumor_item(CLOUD_MEM_SLOT_ID, rumor_text, player.novel_node)

    if skill_update_list:
        for new_sk in skill_update_list:
            s_name = new_sk.get("skill_name", "")
            s_level = new_sk.get("skill_level", "")
            s_exp = new_sk.get("skill_exp", "")
            if s_name:
                # 检查是否存在
                found = False
                for sk in player.martial_skill_list:
                    if sk["skill_name"] == s_name:
                        sk["skill_level"] = s_level
                        if s_exp:
                            sk["skill_exp"] = s_exp
                        found = True
                        break
                if not found:
                    player.martial_skill_list.append({
                        "skill_name": s_name,
                        "skill_level": s_level,
                        "skill_exp": s_exp or "尚需打磨"
                    })

    player.save()
# ===================== 全局存档 =====================


def init_save_data():
    if os.path.exists(SAVE_FILE):
        raw_data = load_json(SAVE_FILE)
        # 判空，修复未使用raw警告
        if raw_data is not None and isinstance(raw_data, dict):
            # 兼容旧版本字符串历史，转数组
            if "history_main_plot" in raw_data and isinstance(raw_data["history_main_plot"], str):
                raw_data["history_main_plot"] = [raw_data["history_main_plot"]]
            # 缺失字段初始化
            if "history_main_plot" not in raw_data:
                raw_data["history_main_plot"] = []
            if "branch_plot_content" not in raw_data:
                raw_data["branch_plot_content"] = ""
            # 强制限制最多100条主线剧情
            if len(raw_data["history_main_plot"]) > 100:
                raw_data["history_main_plot"] = raw_data["history_main_plot"][-100:]
            save_json(SAVE_FILE, raw_data)
            return raw_data
    # 文件不存在，新建存档
    save_data = {
        "history_main_plot": [],
        "branch_plot_content": ""
    }
    save_json(SAVE_FILE, save_data)
    return save_data

def update_plot_save(main_text, branch_text):
    save_data = load_json(SAVE_FILE)
    if not save_data:
        save_data = {
            "history_main_plot": [],
            "branch_plot_content": ""
        }
        # 修复：兼容列表/字符串输入，统一转为字符串处理
    if isinstance(main_text, list):
        # 如果是列表，拼接为字符串（按换行分隔）
        main_text_str = "\n".join([str(item).strip() for item in main_text if item])
    else:
        # 如果是字符串，直接去空格
        main_text_str = str(main_text).strip()
    
    # 新增单条主线剧情（仅非空时添加）
    if main_text_str:
        save_data["history_main_plot"].append(main_text_str)
    
    # 严格上限100条，超量删除最早记录
    if len(save_data["history_main_plot"]) > 100:
        save_data["history_main_plot"] = save_data["history_main_plot"][-100:]
    
    # 处理分支剧情（同样兼容非字符串输入）
    branch_text_str = str(branch_text).strip()
    save_data["branch_plot_content"] = branch_text_str
    
    save_json(SAVE_FILE, save_data)




# ===================== 查询指令 =====================
def query_player_level():
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}【未读取到玩家存档】{COLOR_END}")
        return

    print(f"\n{COLOR_PLOT}【综合修为】{p.overall_martial_level}{COLOR_END}")
    print(f"{COLOR_PLOT}【总境界】{p.overall_realm}{COLOR_END}")

    # 显示瓶颈状态
    if p.bottleneck_level > 0:
        threshold = p.get_bottleneck_threshold()
        progress = p.bottleneck_progress
        ready = "（可突破）" if p.bottleneck_ready else ""
        print(f"{COLOR_YELLOW}【瓶颈状态】第 {p.bottleneck_level} 重，进度 {progress}/{threshold} {ready}{COLOR_END}")
    else:
        print(f"{COLOR_GREEN}【瓶颈状态】无瓶颈{COLOR_END}")

    print(f"{COLOR_PLOT}【功法详情】{COLOR_END}")
    if not p.martial_skill_list:
        print(f"{COLOR_PLAYER}- 暂无习得功法{COLOR_END}")
        return

    for sk in p.martial_skill_list:
        name = sk["skill_name"]
        exp = sk.get("exp", 0)
        realm = p.get_realm(exp)
        next_exp = p.get_next_realm_exp(exp)
        exp_text = sk.get("exp_text", "尚无感悟。")
        print(f"{COLOR_PLAYER}- {name}：{realm}（经验 {exp}，升下级需 {next_exp} 点）{COLOR_END}")
        print(f"{COLOR_PLAYER}  “{exp_text}”{COLOR_END}")
def query_player_skill():
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}【未读取到玩家存档】{COLOR_END}")
        return
    print(f"\n{COLOR_PLAYER}========== 个人功法全览 =========={COLOR_END}")
    print(f"{COLOR_PLAYER}当前总境界：{p.overall_realm}{COLOR_END}")
    if not p.martial_skill_list:
        print(f"{COLOR_PLAYER}暂无习得任何武学功法{COLOR_END}")
        return
    for idx, sk in enumerate(p.martial_skill_list, 1):
        name = sk["skill_name"]
        exp = sk.get("exp", 0)
        realm = p.get_realm(exp)
        exp_text = sk.get("exp_text", "")
        print(f"{COLOR_PLAYER}{idx}. 【{name}】境界：{realm}　经验：{exp}{COLOR_END}")
        print(f"{COLOR_PLAYER}   感悟：{exp_text}{COLOR_END}")
        print(f"{COLOR_PLAYER}{'-'*40}{COLOR_END}")
def query_player_item():
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}【未读取到玩家存档】{COLOR_END}")
        return
    all_item = p.item_list
    valid_items = [c for it in all_item if (c := _clean_item_name(it))]
    if not valid_items:
        print(f"\n{COLOR_PLOT}【背包物品】无{COLOR_END}")
        return
    print(f"\n{COLOR_PLAYER}【当前持有物品】{COLOR_END}")
    for idx, item in enumerate(valid_items, 1):
        print(f"{COLOR_PLAYER}{idx}. {item}{COLOR_END}")
def query_player_rumor():
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}【未读取到玩家存档】{COLOR_END}")
        return
    rumor_all = p.rumor_list
    clean_rumor = [r for r in rumor_all if r.strip() != "无"]
    if not clean_rumor:
        print(f"\n{COLOR_PLAYER}【近期剧情记录】暂无相关记录{COLOR_END}")
        return
    show_rumor = clean_rumor[-10:]
    print(f"\n{COLOR_PLAYER}【最新10条剧情记录】{COLOR_END}")
    for rumor in show_rumor:
        print(f"{COLOR_PLAYER}- {rumor}{COLOR_END}")
# ===================== 新增：遗忘功法/扔掉物品功能 =====================
def forget_player_skill():
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}【未读取到玩家存档】{COLOR_END}")
        return

    skill_list = p.martial_skill_list
    if not skill_list:
        print(f"{COLOR_WARN}【暂无习得任何功法，无需遗忘】{COLOR_END}")
        return

    print(f"\n{COLOR_PLAYER}========== 当前习得功法 =========={COLOR_END}")
    for idx, sk in enumerate(skill_list, 1):
        name = sk["skill_name"]
        exp = sk.get("exp", 0)
        realm = p.get_realm(exp)
        exp_text = sk.get("exp_text", "")
        print(f"{COLOR_PLAYER}{idx}. {name}（境界：{realm}，经验：{exp}）{COLOR_END}")

    try:
        select_idx = input(f"\n{COLOR_GREEN}请输入要遗忘的功法序号（输入0取消）：{COLOR_END}").strip()
        select_idx = int(select_idx)
        if select_idx == 0:
            print(f"{COLOR_SYSTEM}【取消遗忘功法操作】{COLOR_END}")
            return
        if select_idx < 1 or select_idx > len(skill_list):
            print(f"{COLOR_WARN}【无效序号，请重新操作】{COLOR_END}")
            return

        target_skill = skill_list[select_idx - 1]
        confirm = input(f"{COLOR_YELLOW}确认要遗忘【{target_skill['skill_name']}】吗？(y/n)：{COLOR_END}").strip().lower()
        if confirm != "y":
            print(f"{COLOR_SYSTEM}【取消遗忘功法操作】{COLOR_END}")
            return

        # 移除该武功
        skill_list.pop(select_idx - 1)
        p.martial_skill_list = skill_list
        p.sync_overall_level()          # 重新计算整体修为
        p.update_bottleneck_status()    # 重新检测瓶颈状态
        p.save()

        print(f"{COLOR_GREEN}✅ 成功遗忘功法：{target_skill['skill_name']}{COLOR_END}")
        print(f"{COLOR_YELLOW}【当前整体修为】{p.overall_martial_level}{COLOR_END}")
        print(f"{COLOR_YELLOW}【总境界】{p.overall_realm}{COLOR_END}")

        if not skill_list:
            print(f"{COLOR_YELLOW}【提示】所有功法已遗忘，整体修为重置为：初学入门{COLOR_END}")

    except ValueError:
        print(f"{COLOR_WARN}【输入错误，请输入有效数字】{COLOR_END}")
    except Exception as e:
        print(f"{COLOR_WARN}【操作失败】{e}{COLOR_END}")

def discard_player_item():
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}【未读取到玩家存档】{COLOR_END}")
        return

    item_list = [it for it in p.item_list if it.strip() != "" and it.strip() != "无"]
    if not item_list:
        print(f"{COLOR_WARN}【背包为空，无需扔掉物品】{COLOR_END}")
        return

    print(f"\n{COLOR_PLAYER}========== 当前持有物品 =========={COLOR_END}")
    for idx, item in enumerate(item_list, 1):
        print(f"{COLOR_PLAYER}{idx}. {item}{COLOR_END}")

    try:
        select_idx = input(f"\n{COLOR_GREEN}请输入要扔掉的物品序号（输入0取消）：{COLOR_END}").strip()
        select_idx = int(select_idx)
        if select_idx == 0:
            print(f"{COLOR_SYSTEM}【取消扔掉物品操作】{COLOR_END}")
            return
        if select_idx < 1 or select_idx > len(item_list):
            print(f"{COLOR_WARN}【无效序号，请重新操作】{COLOR_END}")
            return

        target_item = item_list[select_idx - 1]
        confirm = input(f"{COLOR_YELLOW}确认要扔掉【{target_item}】吗？(y/n)：{COLOR_END}").strip().lower()
        if confirm != "y":
            print(f"{COLOR_SYSTEM}【取消扔掉物品操作】{COLOR_END}")
            return

        p.item_list.remove(target_item)   # 直接从原始列表移除
        p.save()
        print(f"{COLOR_GREEN}✅ 成功扔掉物品：{target_item}{COLOR_END}")

    except ValueError:
        print(f"{COLOR_WARN}【输入错误，请输入有效数字】{COLOR_END}")
    except Exception as e:
        print(f"{COLOR_WARN}【操作失败】{e}{COLOR_END}")

# 在游戏循环开始前
world_data = load_json(WORLD_FILE) or {}
npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}

# ===================== 核心交互函数（Web & 命令行共用） =====================
def process_one_round(user_input: str, is_web: bool = False):
      
     # Web端入口加锁，超时30秒防死锁
    if is_web:
        acquired = PLOT_PROCESS_LOCK.acquire(timeout=30)
        if not acquired:
            # 超时兜底，直接返回繁忙，不破坏状态
            loc_time = load_location_time()
            return {
                "plot": "系统繁忙，请稍后再试。",
                "npc_change": "无",
                "item_status": "无",
                "location": loc_time.get("location", "未知地点"),
                "time": format_time_with_24h(loc_time.get("time", "未知时辰")),
                "weather": loc_time.get("weather", "晴")
            }
    
    # ===== L2生成状态检查（最小侵入） =====
    # 如果L2正在生成，阻塞等待直到完成或超时
    if _l2_is_generating():
        if is_web:
            # Web端：等待15秒，超时返回"生成中"提示
            l2_ready = _l2_generating_event.wait(timeout=15)
            if not l2_ready:
                # 必须先释放PLOT_PROCESS_LOCK再返回，防止死锁
                PLOT_PROCESS_LOCK.release()
                loc_time = load_location_time()
                return {
                    "plot": "⏳ 章节摘要生成中，请稍后重试...",
                    "npc_change": "无",
                    "item_status": "无",
                    "location": loc_time.get("location", "未知地点"),
                    "time": format_time_with_24h(loc_time.get("time", "未知时辰")),
                    "weather": loc_time.get("weather", "晴"),
                    "l2_generating": True
                }
        else:
            # CLI端：阻塞等待并显示提示
            print(f"{COLOR_SYSTEM}⏳ 章节摘要生成中，请稍候...{COLOR_END}")
            l2_ready = _l2_generating_event.wait(timeout=30)
            if not l2_ready:
                # CLI超时继续，但打印警告
                print(f"{COLOR_WARN}⚠️ L2生成超时，继续本轮（可能使用旧章节摘要）{COLOR_END}")
    
    result = {}
    try:
        """
        执行一轮剧情交互，返回结果字典。
        如果 is_web=True，则不会在控制台打印，只返回数据。
        注意：本函数假定所有全局状态已就绪（如文件已加载）。
        """
        
        global latest_plot1_text
        
        
        # --- 前置准备 ---
        context_cache = refresh_context_cache()
        current_goal = context_cache.get("current_goal", "暂无明确目标")
        # ★ 动态更新 current_goal：优先取活跃主线任务的 display_name，无主线时取支线，全无则保留缓存值
        active_tasks = get_active_tasks()
        main_tasks = [t for t in active_tasks if t.get("type") == "main" and not t.get("suspended", False)]
        if main_tasks:
            new_goal = main_tasks[0].get("display_name", main_tasks[0]["name"])
        else:
            side_tasks = [t for t in active_tasks if not t.get("suspended", False)]
            if side_tasks:
                new_goal = side_tasks[0].get("display_name", side_tasks[0]["name"])
            else:
                new_goal = current_goal
        if new_goal != current_goal:
            context_cache["current_goal"] = new_goal
            save_context_cache(context_cache)
            current_goal = new_goal

        # ===== 获取玩家对象（替代原来的 load_json） =====
        player_obj = get_player()
        # ===== 智能构建NPC档案：活跃NPC传完整，其他传精简（增强鲁棒性） =====
        npc_full_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        all_npc_names = [npc.get("name", "").strip() for npc in npc_full_data.get("npc_list", []) if npc.get("name")]
        all_npc_set = set(all_npc_names)

        # 1. 识别活跃NPC（最近5轮剧情 + 当前用户输入）
        active_names = set()
        interact_logs = context_cache.get("interact_log", [])
        _raw_last_log = interact_logs[-1] if interact_logs else ""  # 最后一轮完整记录
        # ★ L1锚点：取上一轮【本轮剧情内容】到下一个【标签】前的纯剧情文字，截取末400字
        if _raw_last_log:
            _l1_plot_match = re.search(r'【本轮剧情(?:内容)?】(.*?)(?=【[^】]+】|$)', _raw_last_log, re.DOTALL)
            if _l1_plot_match:
                last_log = _l1_plot_match.group(1).strip()[-400:] or ""
            else:
                last_log = _raw_last_log[-400:]
        else:
            last_log = ""
        # DEBUG: 打印L1场景锚点状态
        print(f"[DEBUG-L1] interact_log共{len(interact_logs)}条, last_log前80字: {str(last_log)[:80]}")
        recent_logs5 = interact_logs[-5:] if len(interact_logs) >= 5 else interact_logs  # 最近3轮
        #recent_context5 = "\n\n".join(recent_logs5)
        # ★ 缓存友好窗口：50轮一块，块内累加，跨块重置（最大化DeepSeek缓存命中）
        total = len(interact_logs)
        block_start = (total - 1) // 50 * 50
        cache_window = "\n\n".join(interact_logs[block_start:-1]) if len(interact_logs) > 1 else ""
        
        # 定义清洗函数：去除 Markdown、括号、书名号等干扰符号，保留中文、英文、数字
        def clean_plot_text(text):
            # 去除 Markdown 代码块 ``` ... ```
            text = re.sub(r'```[a-z]*\n?.*?\n```', '', text, flags=re.S)
            # 去除常见的强调符号 * 和 _
            text = re.sub(r'[＊*_]+', '', text)
            # 去除【】、「」等括号，但保留内容（避免误删人名）
            # 注意：人名不会被这些符号包围，去除符号后名字仍会保留
            text = re.sub(r'[【】「」『』（）()《》]', '', text)
            # 去除连续空白符（换行、空格等）
            text = re.sub(r'\s+', ' ', text)
            return text

        for log in recent_logs5:
            plot_match = re.search(r"【本轮剧情(?:内容)?】\s*(.*?)(?=\n【|$)", log, re.S)
            if plot_match:
                raw_plot = plot_match.group(1)
                cleaned = clean_plot_text(raw_plot)
                # 用人名列表做子串匹配（清洗后名字更容易匹配）
                for name in all_npc_names:
                    if name and name in cleaned:
                        active_names.add(name)

        # 玩家主动点名（即使没出现在剧情里，也要算活跃）
        user_cleaned = clean_plot_text(user_input)
        for name in all_npc_names:
            if name and name in user_cleaned:
                active_names.add(name)

        # 2. 处理AI自创NPC（玩家输入中可能提到的新名字）
        created_npcs = []
        if user_input:
            # 提取2~5个中文字符，且前后不是其他中文字符（避免截断长词）
            potential_names = re.findall(r'(?<![一-龥])[一-龥]{2,5}(?![一-龥])', user_input)
            # 过滤常见非人名词汇（扩充排除词库）
            exclude_words = {
                "什么", "怎么", "为什么", "如何", "这个", "那个", "自己", "我们", "你们", "他们",
                "已经", "可以", "没有", "不是", "还是", "就是", "但是", "因为", "所以", "如果",
                "然后", "现在", "这里", "那里", "怎样", "多少", "几个", "哪里",
                "大家", "各位", "兄弟", "朋友", "老兄", "小姐", "公子", "少侠", "女侠", "掌门",
                "师父", "徒儿", "师叔", "师伯", "师侄", "师兄弟", "师姐妹", "总镖头", "镖师",
                "店小二", "掌柜", "老板", "客人", "大侠", "高手", "前辈", "后生", "晚辈",
                "好说", "请坐", "多谢", "失陪", "告辞", "保重", "慢走","继续剧情"
            }
            for name in potential_names:
                if name not in all_npc_set and name not in exclude_words:
                    created_npcs.append(name)
        # 已舍弃L2 固定取最近2轮（N-2, N-1），milestones 已覆盖更早的关键事件
        #recent_logs4 = interact_logs[-3:-1] if len(interact_logs) >= 3 else interact_logs[:-1]
        #recent_context4 = "\n\n".join(recent_logs4)

    # ===== 定义工具（Function Calling）=====
        update_state_tool = {
            "type": "function",
            "function": {
                "name": "update_game_state",
                "description": "更新游戏状态工具，每轮回复必须调用。包含：玩家属性变化、武功经验增益、任务进度、NPC状态、江湖大势等。所有数值变化必须与剧情内容对应。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reputation_delta": {
                            "type": "integer",
                            "description": "江湖名气变化量（正数增加，负数减少）"
                        },
                        "world_trend": {
                            "type": "string",
                            "description": "当前江湖大势，30字以内"
                        },
                        "faction_balance": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "description": "格式：姓名|记忆内容，30字以内"
                            },
                            "description": "本轮NPC新增记忆，每条格式：姓名|记忆内容，30字以内。如：张三丰|玩家携刀来访。无则省略"
                        },
                        "new_rumor": {
                            "type": "string",
                            "description": "玩家主线剧情原子记录，30字内。记录玩家本轮实际经历的关键事件。NPC有可能知道（通过传闻、目击、当事人转述等渠道）。"
                        },
                        "mood": {
                            "type": "string",
                            "description": "当前江湖情绪，10字以内"
                        },
                        "event_action": {
                            "type": "string",
                            "enum": ["add", "remove", "update"],
                            "description": "对当前活跃事件的操作，不操作时省略此字段"
                        },
                        "event_name": {
                            "type": "string",
                            "description": "事件名称，40字以内"
                        },
                        "skill_exp_gain": {
                            "type": "array",
                            "description": "武功经验增益列表，仅在本轮有武功经验增长时填写，无增长填空数组",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "武功名称"},
                                    "exp": {"type": "integer", "description": "获得的经验值"}
                                },
                                "required": ["name", "exp"]
                            }
                        },
                        "skill_exp_update": {
                            "type": "array",
                            "description": "武功感悟更新列表，仅在感悟变化时填写，无变化填空数组",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "武功名称"},
                                    "text": {"type": "string", "description": "新的感悟文字"}
                                },
                                "required": ["name", "text"]
                            }
                        },
                        "task": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "任务名称。优先传【任务简报】中的完整任务名；无完整名称时可传编号如'任务1'"},
                                "stage": {"type": "string", "description": "进展描述（10-20字）"},
                                "percent": {"type": "integer", "description": "进度百分比 0-100"}
                            },
                            "description": "任务进展更新"
                        },
                        "bottleneck_progress_delta": {
                            "type": "integer",
                            "description": "瓶颈进度增加量（仅当有瓶颈时）"
                        },
                        "new_skills": {
                            "type": "array",
                            "description": "本轮新学会的武功列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "武功名称"
                                    },
                                    "level": {
                                        "type": "string",
                                        "description": "初始境界"
                                    },
                                    "exp_text": {
                                        "type": "string",
                                        "description": "初始感悟"
                                    }
                                },
                                "required": ["name", "level"]
                            }
                        },
                        # ========== 新增：NPC身体状态更新字段 ==========
                        "npc_status_update": {
                            "type": "array",
                            "description": "NPC身体状态变化列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "NPC姓名"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["light_injured", "heavy_injured", "dying", "deceased", "poisoned", "normal"],
                                        "description": "身体状态"
                                    },
                                    "desc": {"type": "string", "description": "状态原因"}
                                },
                                "required": ["name", "status"]
                            }
                        },
                        # ========== 新增：NPC好感度更新字段 ==========
                        "npc_favor_update": {
                            "type": "array",
                            "description": "NPC好感度变化列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "NPC姓名"},
                                    "delta": {"type": "integer", "description": "好感变动值"}
                                },
                                "required": ["name", "delta"]
                            }
                        },
                        # ========== 新增：NPC关系描述字段 ==========
                        "npc_relationship_update": {
                            "type": "array",
                            "description": "NPC关系描述列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "NPC姓名"},
                                    "relation": {"type": "string", "description": "关系描述"}
                                },
                                "required": ["name", "relation"]
                            }
                        },
                        # ========== 新增：主角自身状态字段 ==========
                        "self_state": {
                            "type": "string",
                            "description": "主角当前身体/精神状态描述"
                        },
                        # ========== 新增：小说节点字段 ==========
                        "novel_node": {
                            "type": "string",
                            "description": "必须以\"YYYY年M季，\"开头，如\"1751年春，萧半和寿宴在即\"；无变化时填空字符串"
                        },
                        # ========== 新增：地点变更字段 ==========
                        "location": {
                            "type": "string",
                            "description": "地点变更，仅移动时填写新地点全称，未移动时填空字符串"
                        }
                    },
                    "required": ["skill_exp_gain"]   # 至少需要提供这个空数组
                }
            }
        }
        tools = [update_state_tool]
        
        # 读取存档数据
        save_obj = load_json(SAVE_FILE)
        if save_obj:
            full_history = save_obj.get("history_main_plot", [])
            branch_text = save_obj.get("branch_plot_content", "")
        else:
            full_history = []
            branch_text = ""

        
        # his_text 未使用，可删除，但保留为后续扩展
        last_context = context_cache["last_plot_summary"]

        # ===== 【智能】耗时动作识别 =====
        time_consuming_keywords = ["练功", "修炼", "休息", "睡觉", "赶路", "等待", "闲逛", "练", "修", "休", "逛", "睡", "散步", "走走"]
        should_advance_time = any(keyword in user_input for keyword in time_consuming_keywords)

        location_time = load_location_time()
        if location_time:
            if should_advance_time:
                location_time = advance_world_time(location_time)
            current_location = location_time.get("location", "未知地点")
            current_time = location_time.get("time", "未知时辰")
            current_weather = location_time.get("weather", "晴")
            time_display = format_time_with_24h(current_time)
        else:
            current_location = "未知地点"
            current_time = "未知时辰"
            current_weather = "晴"
            time_display = "未知时辰"

        world_data = load_json(WORLD_FILE) or {}
        npc_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}

        # --- 解析用户输入 ---
        mainline_force_instruction = ""
        stripped_input = user_input.strip()
        cmd_clean = stripped_input.replace("（", "").replace("）", "")
        actual_user_action = stripped_input

        # ========== 统一指令链：单链互斥，避免分支覆盖 ==========
        if cmd_clean == "回归主线":
            # ===== 前置校验：状态+冷却，不通过则直接返回，零API消耗 =====
            from mainline_dynamic import load_history, save_history
            mainline_hist = load_history()
            current_round = context_cache.get("round", len(context_cache.get("interact_log", [])))
            last_round = mainline_hist.get("last_trigger_round", 0)
            has_pending = any(e.get("status") == "pending" for e in mainline_hist.get("events", []))

            # 校验1：存在进行中的主线事件，禁止新开
            if has_pending:
                print(f"{COLOR_WARN}⚠️ 当前仍有主线事件进行中，请先完成当前剧情再触发新的主线。{COLOR_END}")
                return {
                    "plot": "你心中念头微动，想追寻主线脉络，但眼下之事尚未了结，还需先处理完当前局面。",
                    "npc_change": "无",
                    "item_status": "无",
                    "location": current_location,
                    "time": time_display,
                    "weather": current_weather,
                }
            # 校验2：距离上次触发不足3轮，触发冷却（首次触发除外）
            # ★ 修复：current_round < last_round 时（存档重置/截断）不触发冷却
            has_triggered_before = len(mainline_hist.get("events", [])) > 0
            if has_triggered_before and 0 <= current_round - last_round < 3:
                _wait = 3 - (current_round - last_round)
                print(f"{COLOR_WARN}⚠️ 主线触发过于频繁，还需推进{_wait}轮剧情。{COLOR_END}")
                # ★ 修复：冷却返回也计为1轮交互，避免反复点击导致死循环
                update_context_cache("（玩家尝试追寻主线，但时机未到，静待时机。）", actual_user_action)
                return {
                    "plot": f"江湖大事非朝夕可至，你稍作休整，静待时机。（还需推进{_wait}轮剧情方可再试）",
                    "npc_change": "无",
                    "item_status": "无",
                    "location": current_location,
                    "time": time_display,
                    "weather": current_weather,
                }

            new_event = advance_mainline(world_data, npc_data)
            if not new_event:
                return {
                    "plot": "你凝神追索江湖主线，却发现这一段宿命脉络已至尽头，眼下暂无新的原著节点可供推进。",
                    "npc_change": "无",
                    "item_status": "无",
                    "location": current_location,
                    "time": time_display,
                    "weather": current_weather,
                }
            # ★ 仅在 advance_mainline 成功后才记录触发轮次（避免失败也设冷却）
            # ★ 修复：必须重新加载history，因为advance_mainline内部已追加事件+current_order+1+清manual_skip_id
            #   若用旧mainline_hist保存会覆盖丢失新事件
            mainline_hist = load_history()
            mainline_hist["last_trigger_round"] = current_round
            save_history(mainline_hist)
            # ==========================================================
            # ========== 新增：自动生成对应主线任务 ==========
            try:
                task_title = new_event.get("title", "主线事件")
                task_desc = f"{new_event.get('summary', '')} 触发场景：{new_event.get('trigger_scene', '')}"
                success, msg = create_task(task_title, task_desc, task_type="main")
                if success:
                    print(f"{COLOR_GREEN}✅ 已自动生成对应主线任务：{task_title}{COLOR_END}")
                else:
                    print(f"{COLOR_WARN}⚠️ 主线任务创建失败：{msg}{COLOR_END}")
            except Exception as e:
                print(f"{COLOR_WARN}⚠️ 自动创建主线任务异常：{e}{COLOR_END}")
            # ==============================================

            actual_user_action = f"玩家决定直面宿命，推进主线：“{new_event['title']}”。"
            # 主线剧情推进指令（优化版：强制从触发场景无缝切入）
            mainline_force_instruction = f"""
    【!主线事件强制规则!】
    本次触发主线节点：{new_event['title']}
    事件核心内容：{new_event.get('summary', '')}
    触发入口：{new_event.get('trigger_scene', '')}

    1. **绝对禁止**直接说「主线事件触发了」，必须从玩家当前的动作、所在的场景自然过渡到事件中。
    2. 严格按照「触发入口」描写事件发生的过程，让玩家感觉是自己刚好遇上，而非系统投放。
    3. 事件涉及NPC的行为、台词严格符合其身份性格与和玩家的好感度。
    4. 本轮只展开事件开端，不要一次性把整个事件讲完，保留玩家选择空间。
    5. 收尾保留剧情延展性，无需强行一次性完结所有伏笔。
    """
    # ====== 快捷指令处理 ======
        elif cmd_clean == "主线完成":
            # 手动标记当前主线事件完成
            from mainline_dynamic import load_history, mark_last_event_completed
            mainline_hist = load_history()
            
            # 前置校验：是否存在进行中的事件
            has_pending = any(e.get("status") == "pending" for e in mainline_hist.get("events", []))
            if not has_pending:
                print(f"{COLOR_WARN}⚠️ 当前没有进行中的主线事件，无需标记完成。{COLOR_END}")
                return {
                    "plot": "你梳理了一下近期经历，眼下并没有正在跟进的主线大事，可先自由探索。",
                    "npc_change": "无",
                    "item_status": "无",
                    "location": current_location,
                    "time": time_display,
                    "weather": current_weather,
                }
            
            # 执行标记完成
            success = mark_last_event_completed()
            if success:
                print(f"{COLOR_GREEN}✅ 当前主线事件已标记为完成。{COLOR_END}")
                plot_content = "你将此事暂告一段落，心中盘算着下一步的打算。江湖风波不息，新的变数或许就在前方。"
                actual_user_action = "玩家确认当前主线节点已了结，阶段性收尾。"
            else:
                print(f"{COLOR_WARN}⚠️ 标记失败，未找到可完成的主线事件。{COLOR_END}")
                plot_content = "你试图了结此事，但总觉得还有未尽之处，暂且搁置。"
                actual_user_action = "玩家尝试标记主线完成"
            
            # 纯本地操作，直接返回，不调用LLM
            return {
                "plot": plot_content,
                "npc_change": "无",
                "item_status": "无",
                "location": current_location,
                "time": time_display,
                "weather": current_weather,
            }

        elif cmd_clean == "继续剧情":
            actual_user_action = "玩家决定继续当前剧情，顺着现有的轨迹自然前进。"
            mainline_force_instruction = """
    【!强制承接连贯指令!】
    1. 必须严格承接上一轮剧情的最后一句描写，从那一刻自然延伸。
    2. 禁止全程平淡无事，必须加入至少一个环境细节变化、NPC动作或线索暗示，不能用“一路平稳”“暂无动静”敷衍。
    3. 可以描写环境细节、人物反应、细微动静、远处声响，不得引入全新的核心人物或重大事件。
    4. 结束时用“【本轮剧情收束】”标记。
    你的任务是有细节地续写，不能流水账带过。
    """

        elif cmd_clean in ("看看江湖见闻", "看看江湖传闻"):
            actual_user_action = "玩家停下脚步，向茶馆里的路人打听江湖上的最新消息。"
            mainline_force_instruction = f"""
    【!剧情回顾触发指令!】
    当前江湖的核心暗流是：{current_goal}。
    请生成本轮主线剧情原子记录（30字内，玩家实际经历的关键事件）。
    这段记录必须与当前的核心目标 {current_goal} 有潜在的联系（可能是线索、暗示、或者某个相关人物的动向）。
    """

        else:
            # 普通玩家输入
            if stripped_input.startswith("（") and stripped_input.endswith("）"):
                actual_user_action = f"【玩家场景/心理描述】{stripped_input}"
            else:
                actual_user_action = f"【玩家台词】{stripped_input}"

        # ========== 新增：回归主线事件NPC注入 + 构建最终npc_info ==========
        # 回归主线轮次：把事件涉及的NPC加入活跃集合，保证人设一致
        if cmd_clean == "回归主线" and new_event is not None:
            for npc_name in new_event.get("involved_npcs", []):
                if npc_name in all_npc_set:
                    active_names.add(npc_name)
        # NPC记忆检索（提前到active_lines之前，确保AI prompt能注入回忆）
        npc_recalled = {}
        mentioned_npcs = [n for n in all_npc_names if n and len(n) >= 2 and n in stripped_input]
        for name in active_names:
            if name not in mentioned_npcs:
                mentioned_npcs.append(name)
        # 提取输入中的关键词用于NPC检索
        _stop = {"说道","谁能","咱们","其实","只是","哈哈","然后","现在","这里","那里","什么","怎么","大家","各位","那个","这个","于是","忽然","便道","笑道","问道","又道","一声","一眼","一时","一阵","一下","之类","似的"}
        _words = re.split(r'[，。！？、；：""''（）()\s]+', stripped_input)
        _kw = [w for w in _words if len(w) >= 3 and w not in _stop]
        _kw_text = " ".join(_kw[:6]) if _kw else stripped_input[:30]
        for npc_name in mentioned_npcs[:5]:
            mem_result = get_relevant_history(
                user_id=CLOUD_MEM_SLOT_ID,
                query=f"{npc_name} {_kw_text}".strip(),
                top_k=2,  # 蒸馏记忆+原始记忆都能召回
                min_score=0.45,
                category_filter=[MemoryCategory.NPC_MEMORY]
            )
            if mem_result:
                lines = mem_result.strip().split("\n")
                collected = []
                # 每行格式: "1. [npc_memory] 【令狐冲的记忆】好感+3（..."
                for line in lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    # 先提取记忆实际归属的 NPC 名（关键：防止"张冠李戴"）
                    owner_match = re.search(r'【([^】]+)的记忆】', line)
                    if owner_match:
                        actual_owner = owner_match.group(1).strip()
                        # 校验归属：必须是当前遍历的 npc_name 才采纳
                        if actual_owner != npc_name:
                            continue
                    mem_clean = re.sub(r'^\d+\.\s*\[npc_memory\]\s*', '', line)
                    mem_clean = re.sub(r'【[^】]+的记忆】\s*', '', mem_clean)
                    mem_clean = re.sub(r'【[^】]+】\s*', '', mem_clean)
                    if mem_clean:
                        collected.append(mem_clean)
                if collected:
                    npc_recalled[npc_name] = "；".join(collected)
        # 3. 构建活跃NPC信息 + 收集全量已故NPC
        active_lines = []
        passive_list = []
        all_deceased_npcs = []
        # 状态中文映射：补全健康状态，所有情况都明确标注
        status_label = {
            "normal": " 健康",
            "light_injured": " 轻伤",
            "heavy_injured": " 重伤",
            "dying": " 濒死",
            "deceased": " 已故",
            "poisoned": " 中毒"
        }
        for npc in npc_full_data.get("npc_list", []):
            name = npc.get("name", "").strip()
            if not name:
                continue
            identity = npc.get("identity", "江湖人士").strip()
            status = npc.get("body_status", "normal")

            # 收集所有亡故角色，统一放进已故列表（已关闭：已故NPC直接显示在活跃区）
            if status == "deceased":
                all_deceased_npcs.append(f"{name}（{identity}）")
                # continue  # 不再跳过，已故NPC也显示在活跃区

            # 存活角色：活跃列表带态度·关系·状态
            if name in active_names:
                favor = npc.get("initial_favor", 0)
                attitude = get_favor_attitude(favor)
                relation = npc.get("relation_to_player", "")
                relation_part = f"·关系:{relation}" if relation else ""
                status_text = status_label.get(status, " 健康")
                npc_line = f"丨 {name}（{identity}）态度:{attitude}{relation_part} {status_text}"
                active_lines.append(npc_line)
            else:
                passive_list.append(f"丨{name}（{identity}）")

        # 4. 处理AI自创NPC（默认健康状态）
        for new_name in created_npcs:
            if new_name not in active_names:
                active_names.add(new_name)

        # 5. 拼装最终 npc_info（去掉自带标题，由 dynamic_info 统一管理标题）
        if active_lines:
            npc_info = "".join(active_lines)
        else:
            npc_info = "（暂无）"
        
        # （已关闭：已故NPC现在直接显示在活跃区，含已故标识）
        # if all_deceased_npcs:
        #     npc_info += "\n【已故人物】\n"
        #     npc_info += "、".join(all_deceased_npcs)
        # ==================================================================    
        
        # 随机事件与进度
        import random
        sys_event_instruction = ""
        # 手动触发回归主线的轮次，跳过自动主线，避免双重强制指令导致剧情混乱
        if cmd_clean != "回归主线" and check_and_consume_mainline_flag():
            chapter_hint = f"当前剧情已逼近原著第 {int(init_progress()['trigger_threshold'] / MAJOR_PLOT_TRIGGER_POINT)} 回"
            sys_event_instruction = f"""
    【!强制原著主线触发指令!】
    {chapter_hint}，与原著核心宿命相关的巨大冲突或重要NPC正在向玩家靠拢。
    **本轮玩家行动依然作为驱动源，但环境NPC必须主动引向原著主线大事件**，绝不可回避。
    """
        elif user_input not in ["回归主线", "对战", "练功", "exit"]:
            if random.random() < RANDOM_EVENT_PROBABILITY:
                sys_event_instruction = """
    【!系统随机变数指令!】
    本轮玩家日常行动中，可以自然穿插一条与当前主线/伏笔相关的江湖见闻或路人闲谈，由路人或在场NPC随口提及，不得生硬突兀。
    """
        if sys_event_instruction:
            mainline_force_instruction += sys_event_instruction

        # 获取玩家信息（使用 player_obj）
        if player_obj:
            player_obj.sync_overall_level()  # 确保overall_realm与武功exp实时同步
            realm = player_obj.overall_realm
            # 武功明细，供 AI 生成感悟时参考（按经验降序取前6门，确保主力武功优先可见）
            skill_detail_lines = []
            for sk in sorted(player_obj.martial_skill_list, key=lambda s: s.get("exp", 0), reverse=True)[:6]:
                name = sk["skill_name"]
                exp = sk.get("exp", 0)
                sk_realm = player_obj.get_realm(exp)
                skill_detail_lines.append(f"  - {name}：{sk_realm}")
            skill_details = "\n".join(skill_detail_lines) if skill_detail_lines else "  暂无武功"
            # 物品列表（清洗后仅传有效物品）
            if player_obj.item_list:
                clean_items = [c for i in player_obj.item_list if (c := _clean_item_name(i))]
                item_str = "、".join(clean_items[:10]) if clean_items else "（空）"
            else:
                item_str = "（空）"
        else:
            realm = ""
            skill_details = "暂无武功"
            item_str = "（空）"
    

        # ===== 战斗接续（如果上一轮是战斗） =====
        battle_cache = get_last_battle_context()
        battle_extra_prompt = ""
        if battle_cache["has_last_battle"]:
            current_state = player_obj.self_state if player_obj else "刚结束战斗，气息微乱，精神紧绷"
            current_level = player_obj.overall_martial_level if player_obj else "初窥门径"
            battle_summary_excerpt = battle_cache['battle_summary'][:500]
            if len(battle_cache['battle_summary']) > 500:
                battle_summary_excerpt += " ...（后续详细对战细节略）"
            battle_extra_prompt = f"""
    【!强制前置：承接上轮对战结局!】
    上一轮刚刚发生了一场重要对战：
    - 对战对手：{battle_cache['battle_target']}
    - 战斗结局：{battle_cache['battle_result']}
    - 战斗简述：{battle_summary_excerpt}

    【!本局人物状态参考!】
    1. 主角目前实际修为：{current_level}；主角当前身体/精神状况：{current_state}。
    2. NPC {battle_cache['battle_target']} 的态度必须根据战败/战胜结果产生合理变化（若战败：心存忌惮/愤恨；若战胜：警惕/轻视）。

    【!过渡指令!】
    本轮剧情场景**必须**发生在战斗刚结束的同一地点。
    必须平缓描写双方的呼吸、伤势、对峙后的沉默或对话，完成"武戏"到"文戏"的自然收束。
    严禁无视上轮对战直接跳跃到无关的日常场景。若结局是死战，NPC绝不可和颜悦色；若结局是切磋，可按结果打破僵局。
    """
            clear_battle_cache()


        
        

        # ===== 构建角色面板（替代散落的6个信息块）=====
        cache = context_cache
        # 瓶颈文本（紧凑版）
        if player_obj and player_obj.bottleneck_level > 0:
            threshold = player_obj.get_bottleneck_threshold()
            bottleneck_text = f"第{player_obj.bottleneck_level}重 {player_obj.bottleneck_progress}/{threshold}"
            if player_obj.bottleneck_ready:
                bottleneck_text += "（可突破）"
        else:
            bottleneck_text = "无"
        # 武学一行
        skills_parts = []
        for sk in _top_skills(player_obj.martial_skill_list or [], 8):
            name = sk["skill_name"]
            exp = sk.get("exp", 0)
            realm = player_obj.get_realm(exp)
            skills_parts.append(f"{name} {realm}")
        skills_compact = " / ".join(skills_parts) if skills_parts else "暂无武功"
        # 传闻（取最近4条，每条不超过30字）
        rumor_text = "暂无"
        if player_obj and player_obj.rumor_list:
            recent_rumors = []
            for rum in player_obj.rumor_list[-7:]:
                if rum and rum.strip() != "无":
                    recent_rumors.append(rum.strip()[:40])
            rumor_text = " \n · ".join(recent_rumors) if recent_rumors else "暂无"
        # 名气称号（从 player.json 读取）
        rep_value = player_obj.reputation if player_obj else 0
        rep_title = get_reputation_title(rep_value)
        # 最近行踪（近20轮地点变更，去重连续重复）
        #recent_locations = []
        #for log in (cache.get("interact_log", []) or [])[-20:]:
        #    loc_match = re.search(r"【地点变更】\s*([^【\n]{1,20})", log)
        #    if loc_match:
        #        loc = loc_match.group(1).strip()
        #        if not recent_locations or recent_locations[-1] != loc:
        #            recent_locations.append(loc)
        #if not recent_locations or recent_locations[-1] != current_location:
        #    recent_locations.append(current_location)
        #location_trail = " → ".join(recent_locations[-1:])
        # 装备信息（随身佩戴的武器/防具/物品，比行李内物品更显眼）
        equipped_parts = []
        try:
            eq = player_obj.equipped
            if eq.get("weapon"):
                equipped_parts.append(f"武器：{eq['weapon']}")
            if eq.get("armor"):
                equipped_parts.append(f"防具：{eq['armor']}")
            carried = eq.get("items", [])
            if isinstance(carried, list) and carried:
                equipped_parts.append(f"随身物品：{'、'.join(carried[:5])}")
        except Exception:
            pass
        equipped_str = " / ".join(equipped_parts) if equipped_parts else "无"
        # 组装角色面板（信息分级：AI内部视角，NPC不可全知）
        _age_display = f"{player_obj.age}岁" if player_obj.age and player_obj.age > 0 else "未知（见出身描述）"
        character_panel = f"""【*主角面板* — AI内部视角（仅供参考，NPC不可全知）】
・姓名：{player_obj.name}
・境界：{realm}
──以下信息AI知道，但NPC不一定知道──
・状态：{player_obj.self_state}
・瓶颈：{bottleneck_text}
・武学：{skills_compact} ← 仅玩家当面施展时NPC才能提及
・随身装备：{equipped_str} ← 随身佩戴的武器/防具/物品，比行李内物品更显眼，但未主动展示时NPC仍可能不知
・物品（行李）：{item_str} ← 正常藏在行李中，除非特殊剧情需要取出展示，否则NPC不可知
・名气：{rep_title}（{rep_value}） ← 可被江湖见闻提及
──以下信息NPC可能知道──
・年龄：{_age_display} ← 江湖可打听的公开信息
・玩家经历（NPC有可能知道，视渠道判断）：{rumor_text}"""

        # ===== 优化：分层剧情上下文 =====
        # L1: 最近5轮详细对话（已在开头定义 recent_context = "\n\n".join(recent_logs)）
        # L2: 章节摘要（取最近2章）
        chapter_summaries1 = cache.get("chapter_summaries", [])[-2:]
        chapter_text = ""
        if  chapter_summaries1:
            chapter_lines = []
            for ch in chapter_summaries1:
                chapter_lines.append(f"【第{ch['chapter_id']}章】（{ch['round_range']}）\n{ch['summary']}")
            chapter_text = "\n".join(chapter_lines)
        full_summary = cache.get("full_plot_summary", "暂无完整脉络")
        # L3: 传记状态（暂时删掉）
        # biography = cache.get("biography", {})
        # L3: 传记状态（精简版，减少token占用）
        bio = cache.get("biography", {})
        protagonist = bio.get("protagonist", {})
        bio_world_state = bio.get("world_state", {})
        bio_text = f"""主角：{protagonist.get("name","")}
        身份：{protagonist.get("identity","")}
        核心能力：{protagonist.get("core_ability","")}
        盟友：{', '.join(protagonist.get("allies",[])[:5])}
        敌人：{', '.join(protagonist.get("enemies",[])[:5])}
        声望：{protagonist.get("reputation",0)}
        主线：{bio_world_state.get("main_plot","")}
        伏笔：{', '.join(bio_world_state.get("unresolved_arcs",[])[:3])}"""


        # ===== 加载当前世界状态（供 AI 上下文使用） =====
        world_state_file = "data/world_state.json"
        world_state = load_json(world_state_file) or {
            "world_trend": "江湖平静，无大事发生",
            "faction_balance": [],
            "recent_rumor": "暂无明确传闻",
            "active_events": [],
            "mood": "平静",
            "last_updated_round": 0
        }

# ===== 向量检索 L4 相关历史线索 =====
        # L4 双通道：CHAPTER取最高1条 + PLOT_ROUND取最高1条（云端召回2条，按score降序取前1）
        relevant_l4_nodes = get_relevant_history(
            user_id=CLOUD_MEM_SLOT_ID,
            query=stripped_input[:100],
            top_k=1,
            min_score=0.45,
            category_filter=[MemoryCategory.CHAPTER]
        )
        # PLOT_ROUND：仅任务完成时上传，量少但高价值，保留检索
        relevant_plot = get_relevant_history(
            user_id=CLOUD_MEM_SLOT_ID,
            query=stripped_input[:100],
            top_k=1,
            min_score=0.45,
            category_filter=[MemoryCategory.PLOT_ROUND]
        )
        if relevant_plot and relevant_plot != "暂无相关历史线索":
            plot_lines = relevant_plot.strip().split("\n")
            plot_items = [l[2:].strip() for l in plot_lines if re.match(r'^\d+\.\s', l.strip())]
            for plot_text in plot_items[:3]:
                if relevant_l4_nodes and relevant_l4_nodes != "暂无相关历史线索":
                    relevant_l4_nodes += f"\n📜 [剧情] {plot_text}"
                else:
                    relevant_l4_nodes = f"📜 [剧情] {plot_text}"
        # TASK：任务完成总结，量少但高价值
        relevant_task = get_relevant_history(
            user_id=CLOUD_MEM_SLOT_ID,
            query=stripped_input[:100],
            top_k=1, min_score=0.45,
            category_filter=[MemoryCategory.TASK]
        )
        if relevant_task and relevant_task != "暂无相关历史线索":
            t_lines = relevant_task.strip().split("\n")
            t_items = [l[2:].strip() for l in t_lines if re.match(r'^\d+\.\s', l.strip())]
            for t_text in t_items[:3]:
                if relevant_l4_nodes and relevant_l4_nodes != "暂无相关历史线索":
                    relevant_l4_nodes += f"\n📋 [任务] {t_text}"
                else:
                    relevant_l4_nodes = f"📋 [任务] {t_text}"
        # RUMOR：玩家剧情记录，每轮上传，语义召回相关历史记录
        relevant_rumor = get_relevant_history(
            user_id=CLOUD_MEM_SLOT_ID,
            query=stripped_input[:100],
            top_k=3, min_score=0.45,
            category_filter=[MemoryCategory.RUMOR]
        )
        if relevant_rumor and relevant_rumor != "暂无相关历史线索":
            r_lines = relevant_rumor.strip().split("\n")
            r_items = [l[2:].strip() for l in r_lines if re.match(r'^\d+\.\s', l.strip())]
            for r_text in r_items[:3]:
                if relevant_l4_nodes and relevant_l4_nodes != "暂无相关历史线索":
                    relevant_l4_nodes += f"\n📰 [剧情记录] {r_text}"
                else:
                    relevant_l4_nodes = f"📰 [剧情记录] {r_text}"
        
    # ===== 向量记忆召回监测（调试用） =====
        current_round = cache.get("round", len(cache.get("interact_log", []))) + 1
        print(f"\n{COLOR_SYSTEM}========== 第 {current_round} 轮 向量记忆召回结果 =========={COLOR_END}")
        print(f"{COLOR_SYSTEM}检索Query：{stripped_input[:100]}{COLOR_END}")
        if relevant_l4_nodes and relevant_l4_nodes != "暂无相关历史线索":
            print(f"{COLOR_GREEN}召回命中：{COLOR_END}")
            print(f"{COLOR_PLOT}{relevant_l4_nodes}{COLOR_END}")
        else:
            print(f"{COLOR_WARN}召回为空 / 相似度不足，已触发本地兜底{COLOR_END}")
        print(f"{COLOR_SYSTEM}======================================================={COLOR_END}\n")

            # 新增：向量召回结果精简（放在 dynamic_info 组装后）
        if relevant_l4_nodes:
            lines = relevant_l4_nodes.strip().split("\n")
            filtered = [A for A in lines if A.strip().startswith(("1.", "2.", "3.", "📜", "📰", "📋"))][:5]
            simplified = []
            for idx, line in enumerate(filtered):
                if line.strip().startswith(("📜", "📰", "📋")):
                    simplified.append(line.strip())
                else:
                    clean_line = line[2:].strip()
                    simplified.append(f"{idx+1}. {clean_line}")
            relevant_l4_nodes = "\n".join(simplified)
        else:
            relevant_l4_nodes = "无相关历史线索"
        # ===== 世界书检索（零侵入注入）=====
        _wb_text = ""
        _wb_query_debug = ""  # 给后台 debug 打印保留原始 Query
        if _WORLDBOOK_AVAILABLE:
            try:
                # 【v2 按用户要求】检索Query范围：
                # ① 上一轮完整AI输出（_raw_last_log = interact_logs[-1] 完整记录，仍保留 600 字防止过长）
                # ② 玩家最新输入（stripped_input）
                #
                # ★ 注意：上方 3321 行的 local 变量 `last_log` 已被重写为【单字符串】
                #   （"本轮剧情内容[-250:]"），不可再对它用 [-1] 切片，否则取到的是"最后一个中文字"。
                #   此处必须使用 3316 行保存的原始完整交互日志 _raw_last_log。
                _last_ai_output = _raw_last_log[-600:] if _raw_last_log else ""
                _wb_query = f"{_last_ai_output} {stripped_input}"
                _wb_query_debug = _wb_query
                # 尝试提取当前年代（novel_node_info 可能在此路径未赋值，安全取值）
                _wb_year = None
                _novel_node = locals().get("novel_node_info", None)
                if _novel_node:
                    import re as _re
                    _ym = _re.search(r'(\d{4})', _novel_node)
                    if _ym:
                        _wb_year = int(_ym.group(1))
                # ★ DEBUG: 调用前检查 worldbook 内部状态（排查 web 端返回空问题）
                _wb_pre_status = worldbook.get_status()
                print(f"[世界书] DEBUG pre-search: _WORLDBOOK_AVAILABLE={_WORLDBOOK_AVAILABLE}, entries={_wb_pre_status.get('entries_count', '?')}, ready={_wb_pre_status.get('ready', '?')}")
                _wb_text = worldbook.search(
                    text=_wb_query,
                    current_year=_wb_year
                )
                print(f"[世界书] DEBUG post-search: 返回长度={len(_wb_text) if _wb_text else 0} 字")
            except Exception as _wb_e:
                print(f"[世界书] 检索异常（安全降级）: {_wb_e}")
                import traceback as _tb
                _tb.print_exc()
                _wb_text = ""
        worldbook_section = f"\n【*世界书检索*】（关键词匹配背景知识，仅供参考，需结合当前场景判断相关性）\n{_wb_text}\n" if _wb_text else ""

        # ===== 【DEBUG】把传给AI上下文的世界书检索信息打印到后台（CLI/Web端都会在各自进程 stdout 看到）=====
        print(f"\n{COLOR_SYSTEM}========== 第 {current_round} 轮 世界书检索 =========={COLOR_END}")
        print(f"{COLOR_PLOT}[Query({len(_wb_query_debug)}字)]: {_wb_query_debug[:120]}{'...' if len(_wb_query_debug)>120 else ''}{COLOR_END}")
        if _wb_text:
            print(f"{COLOR_PLOT}[返回({len(_wb_text)}字)] → 注入到 dynamic_info 的【*世界书检索*】段落{COLOR_END}")
            print(f"{COLOR_PLOT}{worldbook_section}{COLOR_END}")
        else:
            print(f"{COLOR_WARN}[返回空] → 本轮不写入【*世界书检索*】段落{COLOR_END}")
        print(f"{COLOR_SYSTEM}==============================================={COLOR_END}\n")

        # ===== 构建动态信息（可变部分） =====
        # ===== 插入任务简报（让 AI 知道玩家目标） =====
        task_brief = get_task_brief_for_ai()
        if task_brief:
            task_brief_section = f"{task_brief}\n\n"
        else:
            task_brief_section = ""
        # 构建里程碑时间线（最近10条，无数据时显示占位）
        #milestones = cache.get("milestones", [])
        #if milestones:
        #    milestone_timeline = "\n".join(f"  • {m}" for m in milestones[-5:])
        #else:
        #    milestone_timeline = "  • （暂无关键事件记录）"
        
        # 构建 NPC 记忆块（移至 L4 区域）
        npc_memory_lines = []
        for npc_name, recall_text in npc_recalled.items():
            if recall_text not in stripped_input and stripped_input not in recall_text and recall_text not in current_goal and current_goal not in recall_text:
                npc_memory_lines.append(f"【{npc_name}的记忆】{recall_text}")
        npc_memory_block = "\n    ".join(npc_memory_lines) if npc_memory_lines else ""
        #读取当前小说节点
        novel_node_info = player_obj.novel_node
        
        # 空块占位处理（保持上下文结构稳定）
        _SEP = "─────────────────────────"  # 关键位置分隔横线，防止长文本后AI注意力滑过
        _npc_mem_display = npc_memory_block if npc_memory_block.strip() else "（暂无）"
        _wb_display = worldbook_section if worldbook_section.strip() else "\n【*世界书检索*】\n（本轮无相关检索结果）\n"
        _task_display = task_brief_section if task_brief_section.strip() else "【*当前任务目标*】\n（暂无活跃任务）\n\n"
        _special_block = f"【!特殊指令!】\n{mainline_force_instruction}\n\n" if mainline_force_instruction.strip() else ""

        dynamic_info = f"""
【*L3-1 全局剧情脉络*】
・1-{cache.get('last_l3_gen_round', 0)}章剧情脉络：{full_summary}
・人物关系：
  ・当前身份：{protagonist.get("identity","")}
  ・当前盟友：{', '.join(protagonist.get("allies",[])[:2])}
  ・当前敌人：{', '.join(protagonist.get("enemies",[])[:2])}

【*L3-2 近期概要*】
・最新2章概要：{chapter_text}

【*L2 最近50轮细节 · 细节参考*】
{cache_window}

{_SEP}

【*L1 即时场景锚点 · 剧情承接*】
{last_log}

【*当前世界状态*】
・时辰：{time_display}
・地点：{current_location}
・天气：{current_weather}
・日期：{novel_node_info}

{_task_display}{character_panel}

【*L4-1 NPC个人记忆*】
{_npc_mem_display}

【*当前活跃NPC状态*】（好感/态度/状态，静态档案见下方世界书检索）
{npc_info}

【*L4-2 历史剧情线索*】
{relevant_l4_nodes}
{_wb_display}{_special_block}{_SEP}"""

        # 如果有战斗接续，附加到动态信息
        if battle_extra_prompt:
            dynamic_info += f"\n{battle_extra_prompt}"

        # 最终用户消息 = 动态信息 + 玩家实际输入
        # 提取玩家纯输入内容（去掉包装标签）
        pure_user_action = stripped_input

        # ===== 骰子检定系统 V4（武功品阶+境界双值 + AI判定 + 8档分级） =====
        dice_constraint = ""
        dice_result_for_frontend = None

        # 优先检查 Web 端是否已处理骰子（避免重复掷骰）
        _web_constraint = getattr(dice_system, 'WEB_PROCESSED_CONSTRAINT_V4', '')
        _web_result = getattr(dice_system, 'WEB_PROCESSED_RESULT_V4', None)
        _web_skipped = getattr(dice_system, 'WEB_SKIPPED_V4', False)
        if _web_constraint:
            # Web 端已确认并掷骰，直接使用其结果
            dice_clear_web_state_v4()
            dice_constraint = f"\n{_web_constraint}\n"
            dice_result_for_frontend = _web_result
            print(f"[骰子V4] 收到Web端约束文本，长度={len(_web_constraint)}字，结论={_web_result.get('verdict','?') if _web_result else '?'}")
        elif _web_skipped:
            # Web 端玩家选择跳过掷骰，不执行检定
            dice_clear_web_state_v4()
            dice_constraint = ""
            dice_result_for_frontend = None
        else:
            # CLI 模式或 Web 未处理时，自动执行 V4 检定
            try:
                # 获取 L1 场景锚点（最近一轮剧情）
                l1_scene = ""
                _interact_logs = context_cache.get("interact_log", [])
                if _interact_logs:
                    _last_log = str(_interact_logs[-1])
                    _plot_match = re.search(r'【本轮剧情(?:内容)?】(.*?)(?:【NPC|$)', _last_log, re.DOTALL)
                    if _plot_match:
                        l1_scene = _plot_match.group(1).strip()[-300:] or ""
                    else:
                        l1_scene = _last_log[-300:] or ""

                # AI 判定（始终启用，场景为空时AI仍能根据行动判断）
                _active_npcs_brief = dice_system.build_active_npcs_brief(
                    npc_full_data, pure_user_action, l1_scene
                )
                # 分类检测武功（支持内功轻功增幅检定）
                _classified_skills = dice_system.detect_martial_skill_classified(
                    pure_user_action, player_obj.martial_skill_list, player_obj
                )
                _check_result = dice_resolve_check_v4(
                    player_obj=player_obj,
                    user_action=pure_user_action,
                    l1_scene=l1_scene,
                    llm_func=llm_call_common,
                    active_npcs_text=_active_npcs_brief,
                    classified_skills=_classified_skills,
                )

                if _check_result:
                    dice_constraint = f"\n{_check_result['constraint_text']}\n"
                    dice_result_for_frontend = {
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
            except Exception as _e:
                # 骰子系统异常不应阻塞正常流程
                print(f"[WARN] 骰子V4检定异常（已跳过）: {_e}")
                dice_constraint = ""
                dice_result_for_frontend = None
        # ===== 骰子检定结束 =====

        _dice_sep = f"        {_SEP}\n\n" if dice_constraint.strip() else ""

        user_message = f"""{_SEP}

【本轮核心指令】
        要求：本轮剧情必须直接、完整、具体地响应玩家的行动/对话，不得回避、不得转移话题、不得一笔带过。

        {dynamic_info}
        {dice_constraint}
        {_dice_sep}【玩家本轮行动】
        {pure_user_action}

        {_SEP}

        【再次强调】
        - 必须以【玩家本轮行动】为主要驱动推进250字以内的主要剧情；【L1 即时场景锚点】仅作为承接背景，严禁复制或重复L1中已描述过的剧情文字，必须根据玩家本轮行动展开新内容
        - 相关剧情人物详细参考L2、L3-1、L3-2等上述已给的所有信息
        - 给出2-3个10字以内精简的玩家行动选项
        - NPC仅根据自身身份、立场与处境自然响应,绝对不能OOC；绝对禁止代替玩家做出任何决定、强制推进剧情、替玩家选择行动方向。
{"        - ⚠️必须严格遵循上方【!系统检定·必须遵循!】中的检定结论，剧情走向必须与检定结果完全一致，不得违背检定结论自行编造成功或失败。" if dice_constraint else ""}

        ！！输出剧情文字开头必须有【本轮剧情内容】
        """

    # 调用LLM（传递 tools）
        # ===== 构建世界设定结构化 Prompt（固定背景注入 system） =====
        def build_world_setting_prompt():
            if not os.path.exists(WORLD_FILE):
                return ""
            wd = load_json(WORLD_FILE) or {}
            if not wd:
                return ""
            lines = []
            lines.append("【★ 世界设定 · 固定背景 ★】")
            lines.append(f"1. 世界名称：{wd.get('world_name', '未设定')}")
            lines.append(f"2. 时间线：{wd.get('timeline', '')}")
            lines.append(f"3. 时代背景：{wd.get('background_history', '')}")
            lines.append(f"4. 地理区域：{wd.get('geography_region', '')}")
            lines.append(f"5. 武功体系：{wd.get('power_system', '')}")
            lines.append(f"6. 门派势力：{wd.get('major_faction', '')}")
            lines.append(f"7. 江湖规矩：{wd.get('world_rules', '')}")
            lines.append(f"8. 核心剧情脉络：{wd.get('core_plot_background', '')}")
            lines.append("【重要】以上为固定世界观，演绎剧情时严格遵守，不得冲突、不得随意修改")
            return "\n".join(lines) + "\n\n"

        world_prompt = build_world_setting_prompt()
        system_prompt_final = STATIC_SYSTEM_PROMPT + world_prompt

        response = llm_call_common(
            system_prompt_final,
            user_message,             
            api_key=MAIN_LOOP_API_KEY,
            base_url=MAIN_LOOP_BASE_URL,
            model=MAIN_LOOP_MODEL,
            temp=0.65, 
            stream=False, 
            tools=tools,
            max_tokens=2000,    # 剧情+工具调用完全足够，避免模型无意义生成长文
            timeout=MAIN_LOOP_TIMEOUT         # 使用配置的主循环超时，适配 V4-Flash-0731 更长的推理时间
        )
        reply = response["content"]
        tool_calls = response["tool_calls"]
        
        print(f"【DEBUG 100】传送给AI:  {user_message}")
        
        # ========== DEBUG 开始 ==========
        print("\n" + "="*60)
        print(f"【DEBUG 1】API返回正文长度: {len(reply)} 字符")
        print(f"【DEBUG 2】API返回原始前300字:\n{reply[:300]}")
        has_tools = tool_calls is not None and isinstance(tool_calls, list) and len(tool_calls) > 0
        print(f"【DEBUG 3】是否有工具调用: {has_tools}")
        print(f"【DEBUG 4】传入Prompt总长度: {len(system_prompt_final) + len(user_message)} 字符（其中世界设定约 {len(world_prompt)} 字符）")
        print("="*60 + "\n")
        # ========== DEBUG 结束 ==========
        
        # ★ 修复问题2：彻底移除【世界状态更新】及其后的JSON ★
        reply_clean = re.sub(
            r'【世界状态更新】\s*\{[^{}]*\}',
            '',
            reply,
            flags=re.DOTALL
        )
        reply_clean = re.sub(
            r'【世界状态更新】\s*\{.*\}',
            '',
            reply_clean,
            flags=re.DOTALL
        )
        # 彻底清洗回复文本（第三道保险，非贪婪匹配兜底）
        reply_clean = re.sub(r'【世界状态更新】\s*\{.*?\}', '', reply_clean, flags=re.S)
        # 去除多余的加粗标记、空行
        reply_clean = re.sub(r'\*{1,3}', '', reply_clean)
        reply_clean = re.sub(r'\n{3,}', '\n\n', reply_clean).strip()

        # 解析回复（使用清洗后的 reply_clean）
        part_split = re.split(r"(?:\*\*)?\s*\n*【(本轮剧情(?:内容)?|NPC状态变动|道具/自身健康状态|行动选项)】\s*(?:\*\*)?\s*\n*", reply_clean)
        plot_content = ""
        npc_change_content = ""
        item_state_content = ""
        action_options = ""  # 新增
        for idx, seg in enumerate(part_split):
            seg = seg.strip()
            if not seg:
                continue
            if seg in ("本轮剧情", "本轮剧情内容") and idx + 1 < len(part_split):
                plot_content = part_split[idx + 1].strip()
            elif seg == "NPC状态变动" and idx + 1 < len(part_split):
                npc_change_content = part_split[idx + 1].strip()
            elif seg == "道具/自身健康状态" and idx + 1 < len(part_split):
                item_state_content = part_split[idx + 1].strip()
            elif seg == "行动选项" and idx + 1 < len(part_split):
                action_options = part_split[idx + 1].strip()
        if not plot_content:
            print("\n⚠️ 【DEBUG 告警】触发本地剧情兜底！")
            print("⚠️ 【DEBUG 原因】正则未匹配到【本轮剧情内容】标签，或标签后无有效内容")
            # ========== 格式解析容错：无标准标签时自动截取正文 ==========
            if reply_clean and reply_clean.strip():
                clean_text = reply_clean.strip()
                
                # 第一步：砍掉末尾的选项列表、交互引导内容
                option_markers = [
                    "请选择你的行动", 
                    "---", 
                    "1. **", 
                    "1. ",
                    "【第",
                ]
                for marker in option_markers:
                    if marker in clean_text:
                        # 只保留第一个标记之前的正文部分
                        clean_text = clean_text.split(marker)[0].strip()
                        break
                
                # 第二步：过滤无效行（轮次标题、分割线）
                lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
                filtered_lines = []
                for line in lines:
                    # 跳过纯轮次标题、分割线
                    if line.startswith("【第") and "轮交互】" in line:
                        continue
                    if line.strip() in ("---", "===", "=" * 20):
                        continue
                    filtered_lines.append(line)
                
                extracted = "\n".join(filtered_lines).strip()
                
                # 第三步：截取前700字作为有效剧情
                if extracted:
                    plot_content = extracted[:700] + ("..." if len(extracted) > 700 else "")
                    npc_change_content = "无"
                    item_state_content = "无"
                    print("⚠️ 格式解析容错：未识别到标准标签，已自动截取正文")
                else:
                    # 提取失败终极兜底
                    plot_content = f"你{user_input}，四周静悄悄的，暂无动静。"
                    npc_change_content = "无"
                    item_state_content = "无"
            else:
                # API完全返回空内容的终极兜底
                plot_content = f"你{user_input}，四周静悄悄的，暂无动静。"
                npc_change_content = "无"
                item_state_content = "无"
        
    # ★★★ 关键修复：彻底从 plot_content 中移除【世界状态更新】及其后的 JSON ★★★
        plot_content = re.sub(
            r'【世界状态更新】\s*\{[^{}]*\}',
            '',
            plot_content,
            flags=re.DOTALL
        )
        plot_content = re.sub(
            r'【世界状态更新】\s*\{.*\}',
            '',
            plot_content,
            flags=re.DOTALL
        )
        # 清除残留的空白行
        plot_content = re.sub(r'\n\s*\n', '\n', plot_content).strip()

        # 解析时空变更
        # 无效值黑名单：AI 可能输出"无"表示不变，应忽略，保持上一轮值
        _SKIP_VALUES = frozenset({"无", "（无）", "(无)", "无。", "不变", "保持", "未变", "-", "--"})
        # ★ 优先从工具调用读取地点（可靠），工具未提供再回退正文正则
        loc_from_tool = None
        if tool_calls:
            for tc in tool_calls:
                if tc.function.name == "update_game_state":
                    try:
                        _targs = json.loads(tc.function.arguments)
                        if _targs.get("location"):
                            loc_from_tool = _targs["location"].strip()
                            break
                    except Exception:
                        pass
        if loc_from_tool and loc_from_tool not in _SKIP_VALUES:
            print(f"【地点变更】工具调用：{loc_from_tool}")
            update_location_time(location=loc_from_tool)
        else:
            location_match = re.search(r"【地点变更】\s*([^【\n]+)", reply)
            if location_match:
                raw_loc = location_match.group(1).strip()
                new_loc = re.sub(r'[。，、！？\s]+$', '', raw_loc).strip()
                if new_loc and new_loc not in _SKIP_VALUES:
                    print(f"【地点变更】检测到：{new_loc}")
                    update_location_time(location=new_loc)
                else:
                    print(f"【地点变更】AI输出'{raw_loc}'（无效/无变化）→ 保持原地")
        time_match = re.search(r"【时间变更】\s*([^【\n]+)", reply)
        if time_match:
            new_time = time_match.group(1).strip()
            if new_time and new_time not in _SKIP_VALUES:
                update_location_time(time=new_time)
            else:
                print(f"【时间变更】AI输出'{new_time}'（无效/无变化）→ 保持当前")

        # ★ 重新读取最新的位置时间（无论是否有变更，都强制读取一次）★
        updated_loc_time = load_location_time()
        if updated_loc_time:
            current_location = updated_loc_time.get("location", current_location)
            current_time = updated_loc_time.get("time", current_time)
            current_weather = updated_loc_time.get("weather", current_weather)
            time_display = format_time_with_24h(current_time)


        # 先更新玩家和NPC状态，再写入上下文，避免摘要与实际状态错位一轮
        _player_update_info = parse_and_update_player_state(reply, tool_calls)
        parse_and_update_npc_state(reply, tool_calls, user_action=actual_user_action)
        update_context_cache(plot_content, actual_user_action)

        # 推进进度
        progress_delta = PLOT_PROGRESS_PER_ACTION
        if user_input == "回归主线":
            progress_delta = 8.0
        elif user_input == "对战":
            progress_delta = 2.0
        update_progress(progress_delta)

        # 保存主线/支线
        new_main_single = plot_content
        if user_input == "回归主线":
            new_branch = "【支线已彻底收拢，核心主线正式重启】"
        else:
            new_branch = branch_text + "\n" + plot_content
        update_plot_save(new_main_single, new_branch)

        # 武功变更落地（好感变更已全部由工具调用处理）
        if npc_change_content != "无":
            lines = npc_change_content.splitlines()
            for line in lines:
                match_skill = re.match(r"(.*)：武功「(.*)」升至(.*)", line.strip())
                if match_skill:
                    n_name = match_skill.group(1).strip()
                    sk_name = match_skill.group(2).strip()
                    sk_lv = match_skill.group(3).strip()
                    update_npc_skill(n_name, sk_name, sk_lv)

        # ===== 正则兜底①：【任务进度】（工具未处理时才生效）=====
        task_handled_by_tool = False
        if tool_calls:
            for tc in tool_calls:
                if tc.function.name == "update_game_state":
                    try:
                        if "task" in tc.function.arguments:
                            task_handled_by_tool = True
                            break
                    except Exception:
                        pass
        if not task_handled_by_tool:
            task_match = re.search(r"【任务进度】\s*(.+?)(?:\n|$)", reply_clean)
            if task_match:
                task_text = task_match.group(1).strip()
                # 格式：任务编号/任务名 → 进度XX%，当前阶段：XXX
                m = re.match(r"(?:任务)?(\d+|[^→\s]+)\s*→\s*进度\s*(\d+)\s*%\s*，?\s*当前阶段：?(.*)", task_text)
                if m:
                    t_name = m.group(1).strip()
                    pct = m.group(2).strip()
                    stage = m.group(3).strip() if m.group(3) else None
                    tasks = get_active_tasks()
                    # 匹配任务（编号或名称）
                    matched = None
                    for t in tasks:
                        if t["name"] == t_name or t.get("display_name", "") == t_name or t_name in t["name"] or t["name"] in t_name:
                            matched = t
                            break
                    if matched:
                        update_task_progress(matched["name"], stage=stage, percent=int(pct))
                        print(f"📋 任务「{matched['name']}」→ {pct}%（正则兜底）")

        # ===== 正则兜底②：【传闻内容】（工具未提供 new_rumor 时生效）=====
        rumor_handled_by_tool = False
        if tool_calls:
            for tc in tool_calls:
                if tc.function.name == "update_game_state":
                    try:
                        if "new_rumor" in tc.function.arguments:
                            rumor_handled_by_tool = True
                            break
                    except (json.JSONDecodeError, AttributeError, KeyError, TypeError):
                        pass
        if not rumor_handled_by_tool:
            rumor_match = re.search(r"【(?:传闻内容|江湖见闻|近期关键记忆|近期剧情记录)】\s*(.+?)(?:\n|$)", reply_clean)
            if rumor_match:
                new_rumor = rumor_match.group(1).strip()[:80]
                world_state["recent_rumor"] = new_rumor
                save_json("data/world_state.json", world_state)
                print(f"📢 传闻更新：{new_rumor}（正则兜底）")

        # ===== 正则兜底③：【道具/自身健康状态】道具/武功变动（工具未处理时生效）=====
        if item_state_content and item_state_content != "无":
            # 新增道具
            item_add = re.findall(r"新增道具[：:]\s*(.+?)(?=消耗道具|丢弃道具|\n|$)", item_state_content)
            if item_add:
                player = get_player()
                if player:
                    for items_str in item_add:
                        for it in re.split(r"[、，,]", items_str):
                            it = _clean_item_name(it.strip())
                            if it:
                                player.add_item(it)
                                print(f"🎒 获得道具：{it}（正则兜底）")
            # 消耗道具
            item_use = re.findall(r"消耗道具[：:]\s*(.+?)(?=新增道具|丢弃道具|\n|$)", item_state_content)
            if item_use:
                player = get_player()
                if player:
                    for items_str in item_use:
                        for it in re.split(r"[、，,]", items_str):
                            it = _clean_item_name(it.strip())
                            if it and it in player.item_list:
                                player.item_list.remove(it)
                                print(f"🎒 消耗道具：{it}（正则兜底）")
            # 综合修为（兜底解析）
            # 综合修为部分已有工具处理，跳过

        # 最新剧情文本（供配图使用）
        with _plot_text_lock:
            latest_plot1_text = plot_content

        # ★ 最终返回前再读取一次，确保一致 ★
        final_loc_time = load_location_time()
        if final_loc_time:
            current_location = final_loc_time.get("location", current_location)
            current_time = final_loc_time.get("time", current_time)
            current_weather = final_loc_time.get("weather", current_weather)
            time_display = format_time_with_24h(current_time)
    # ===== Web端：从实际状态拼装显示数据（先重新加载，确保读到工具调用更新后的最新数据）=====
        npc_full_data = load_json(NPC_AGENT_FILE) or {"npc_list": []}
        related_npc_status = []
        npc_status_lines = []
        for npc in npc_full_data.get("npc_list", []):
            name = npc.get("name", "")
            if not name:
                continue
            if name in active_names:
                favor = npc.get("initial_favor", 15)
                attitude = get_favor_attitude(favor)
                relation = npc.get("relation_to_player", "")
                rel_text = f"·{relation}" if relation else ""
                body_map = {"normal": "健康", "light_injured": "轻伤", "injured": "重伤", "heavy_injured": "重伤", "dying": "濒死", "deceased": "已故", "poisoned": "中毒", "missing": "失踪"}
                body = body_map.get(npc.get("body_status", "normal"), "健康")
                npc_line = f"{name} {attitude}{rel_text} 好感{favor} {body}"
                npc_status_lines.append(npc_line)
                related_npc_status.append({
                    "name": name, "identity": npc.get("identity", ""),
                    "body_status": npc.get("body_status", "normal"),
                    "body_status_desc": npc.get("body_status_desc", ""), "favor": favor
                })
        npc_change_display = "\n".join(npc_status_lines) if npc_status_lines else "无活跃NPC"
        # 拼接AI原始输出（含伤势等自然语言描述）
        if npc_change_content and npc_change_content != "无":
            npc_change_display = npc_change_content + "\n" + npc_change_display
        # 道具/自身状态
        player_disp = get_player()
        item_lines = []
        if player_disp and player_disp.item_list:
            clean_items = [_clean_item_name(it) for it in player_disp.item_list[-8:] if _clean_item_name(it)]
            if clean_items:
                item_lines.append(f"持有：{'、'.join(clean_items)}")
        if player_disp and player_disp.martial_skill_list:
            sp = [f"{s['skill_name']} {player_disp.get_realm(s.get('exp',0))}" for s in _top_skills(player_disp.martial_skill_list, 4)]
            if sp:
                item_lines.append(f"武学：{' / '.join(sp)}")
        if player_disp:
            item_lines.append(f"状态：{player_disp.self_state}")
        item_status_display = "\n".join(item_lines) if item_lines else "无变化"
        # 追加本轮经验增益/感悟更新到【状态】
        if _player_update_info:
            _gain_lines = _player_update_info.get("exp_gain_lines") or []
            _update_lines = _player_update_info.get("exp_update_lines") or []
            _exp_extra = []
            if _gain_lines:
                _exp_extra.append(f"经验：{'、'.join(_gain_lines)}")
            if _update_lines:
                _exp_extra.append(f"感悟：{'、'.join(_update_lines)}")
            if _exp_extra:
                item_status_display = item_status_display + "\n" + "\n".join(_exp_extra)
        # 拼接AI原始输出（含武功感悟等自然语言描述）
        if item_state_content and item_state_content != "无":
            item_status_display = item_state_content + "\n\n" + item_status_display
        # 任务进度简报
        task_lines = []
        for t in get_active_tasks():
            if t.get("suspended", False):
                continue
            disp = t.get("display_name", t["name"])
            pct = t.get("progress_percent", 0)
            stage = t.get("current_stage", "")
            marker = "⭐" if t.get("type") == "main" else "○"
            task_lines.append(f"{marker}{disp} {pct}% {stage}")
        task_status_display = ""  # 任务不显示在web剧情区
        loc_time_display = f"📍{current_location} | 🕐{time_display} | 🌤{current_weather}"
        # 返回结果
        result = {
            "round": current_round,
            "plot": plot_content,
            "npc_change": npc_change_display,
            "item_status": item_status_display,
            "task_status": task_status_display,
            "location": loc_time_display,
            "npc_status_list": related_npc_status,
            "npc_memory": npc_memory_block,  # NPC记忆供web端单独展示
            "action_options": action_options,
            "dice_result": dice_result_for_frontend  # 骰子检定结果（None表示无检定）
        }
        #最新剧情文本（供配图使用）
        with _plot_text_lock:
            latest_plot1_text = plot_content

        # ★ 最终返回前再读取一次，确保一致 ★
        final_loc_time = load_location_time()
        if final_loc_time:
            current_location = final_loc_time.get("location", current_location)
            current_time = final_loc_time.get("time", current_time)
            current_weather = final_loc_time.get("weather", current_weather)
            time_display = format_time_with_24h(current_time)

        # ===== 世界状态更新（优先工具调用，回退正则） =====
        world_state_file = "data/world_state.json"
        world_state = load_json(world_state_file) or {
            "world_trend": "江湖平静，无大事发生",
            "faction_balance": [],
            "recent_rumor": "暂无明确传闻",
            "active_events": [],
            "mood": "平静",
            "last_updated_round": 0
        }

# 1. 尝试从工具调用中提取世界状态字段
        world_update_data = {}
        if tool_calls:
            for tc in tool_calls:
                if tc.function.name == "update_game_state":
                    try:
                        args = json.loads(tc.function.arguments)
                        world_keys = ["reputation_delta", "world_trend", "faction_balance", "new_rumor", "mood", "event_action", "event_name"]
                        world_update_data = {k: args.get(k) for k in world_keys if k in args}
                        break
                    except Exception:
                        pass

        # 2. 若工具调用未提供，则回退到正则提取
        if not world_update_data:
            json_match = re.search(r'\{[^{}]*"reputation_delta"[^{}]*\}', reply)
            if json_match:
                try:
                    world_update_data = json.loads(json_match.group())
                except Exception:
                    pass

        # 3. 应用更新
        if world_update_data:
            if "reputation_delta" in world_update_data:
                if player_obj:
                    new_rep = player_obj.reputation + world_update_data["reputation_delta"]
                    player_obj.reputation = max(-10000, min(10000, new_rep))
                    player_obj.save()
            if "world_trend" in world_update_data and world_update_data["world_trend"]:
                world_state["world_trend"] = world_update_data["world_trend"][:30]
            if "faction_balance" in world_update_data and world_update_data["faction_balance"]:
                _fb_list = world_update_data["faction_balance"]
                if isinstance(_fb_list, list):
                    for _fb_item in _fb_list[:10]:
                        if isinstance(_fb_item, str) and "|" in _fb_item:
                            _parts = _fb_item.split("|", 1)
                            _npc_name = _parts[0].strip()
                            _mem_text = _parts[1].strip()[:30]
                            if _npc_name and _mem_text:
                                try:
                                    append_npc_memory(_npc_name, _mem_text)
                                    print(f"{COLOR_SYSTEM}[NPC记忆] {_npc_name}: {_mem_text}{COLOR_END}")
                                except Exception as e:
                                    print(f"{COLOR_WARN}⚠️ NPC记忆存储失败: {e}{COLOR_END}")
            if "new_rumor" in world_update_data and world_update_data["new_rumor"]:
                world_state["recent_rumor"] = world_update_data["new_rumor"][:80]
            if "mood" in world_update_data and world_update_data["mood"]:
                world_state["mood"] = world_update_data["mood"][:10]
            if "event_action" in world_update_data and "event_name" in world_update_data:
                event = world_update_data["event_name"]
                action = world_update_data["event_action"]
                if isinstance(event, str) and event.strip():
                    event = event[:40]
                    if action == "add" and event not in world_state["active_events"]:
                        world_state["active_events"].append(event)
                        if len(world_state["active_events"]) > 3:
                            world_state["active_events"] = world_state["active_events"][-3:]
                    elif action == "remove" and event in world_state["active_events"]:
                        world_state["active_events"].remove(event)
                    elif action == "update":
                        for i, e in enumerate(world_state["active_events"]):
                            if event in e or e in event:
                                world_state["active_events"][i] = event
                                break

            world_state["last_updated_round"] = context_cache.get("round", len(context_cache.get("interact_log", [])))
            # ===== 新增：打包世界状态为【江湖见闻】节点上传向量库 =====
            current_round = context_cache.get("round", len(context_cache.get("interact_log", []))) + 1
            trend = world_state.get("world_trend", "")
            rumor = world_state.get("recent_rumor", "")
            events = world_state.get("active_events", [])
            events_text = "、".join(events) if events else "暂无重大事件"
            
            rumor_node_content = f"第{current_round}轮江湖状态：大势【{trend}】；核心传闻【{rumor}】；当前事件【{events_text}】"


            # 去重：和上一次上传的内容对比，无变化则不上传
            last_uploaded = cache.get("last_uploaded_world_state", "")
            if rumor_node_content != last_uploaded:
                # upload_rumor_snapshot(CLOUD_MEM_SLOT_ID, rumor_node_full, current_round)  # 已停用
                with _context_cache_lock:
                    latest_cache = load_context_cache()
                    if latest_cache and isinstance(latest_cache, dict):
                        latest_cache["last_uploaded_world_state"] = rumor_node_content
                        save_context_cache(latest_cache)

            save_json("data/world_state.json", world_state)

        # ===== 最终清洗：彻底移除 【世界状态更新】 及其后的 JSON =====
        if result.get("plot"):
            lines = result["plot"].splitlines()
            filtered = []
            skip = False
            for line in lines:
                if '【世界状态更新】' in line:
                    skip = True
                if not skip:
                    filtered.append(line)
                if skip and '}' in line and line.strip().endswith('}'):
                    skip = False
            result["plot"] = "\n".join(filtered)
    finally:
            # 无论正常/异常都释放锁（仅当前线程持有锁时才释放，避免竞态误释放）
            if is_web and PLOT_PROCESS_LOCK.locked():
                try:
                    PLOT_PROCESS_LOCK.release()
                except RuntimeError:
                    pass
    return result

# 从作弊器的接入代码程序
def player_edit_menu():
    """命令行版玩家属性编辑器"""
    p = get_player()
    if not p:
        print(f"{COLOR_WARN}未找到玩家存档，请先创建角色{COLOR_END}")
        return
    
    while True:
        print(f"\n{COLOR_SYSTEM}========== ⚙️  角色属性外挂编辑器 =========={COLOR_END}")
        print(f"{COLOR_GREEN}1. 查看完整属性JSON{COLOR_END}")
        print(f"{COLOR_GREEN}2. 修改单个字段（快捷）{COLOR_END}")
        print(f"{COLOR_GREEN}3. 导入完整JSON覆盖{COLOR_END}")
        print(f"{COLOR_GREEN}4. 一键满经验/满物品（作弊）{COLOR_END}")
        print(f"{COLOR_GREEN}0. 返回主菜单{COLOR_END}")
        
        choice = input(f"\n{COLOR_OPTION}请选择操作：{COLOR_END}").strip()
        
        if choice == "0":
            break
            
        elif choice == "1":
            import json
            success, data, _ = edit_player_raw()
            if success:
                print(f"\n{COLOR_PLAYER}{json.dumps(data, ensure_ascii=False, indent=2)}{COLOR_END}")
            input(f"\n{COLOR_SYSTEM}按回车继续...{COLOR_END}")
            
        elif choice == "2":
            print(f"\n{COLOR_SYSTEM}--- 快捷修改单个字段 ---{COLOR_END}")
            print(f"{COLOR_YELLOW}支持点语法定位，数组从0开始编号{COLOR_END}")
            print(f"{COLOR_YELLOW}示例：{COLOR_END}")
            print("  角色名 → name")
            print("  第1个武功经验 → martial_skill_list.0.exp")
            print("  第1个武功名称 → martial_skill_list.0.name")
            print("  第1个物品名 → item_list.0")
            print("  自身状态 → self_state")
            print("  瓶颈进度 → bottleneck_progress")
            print()
            field = input(f"{COLOR_OPTION}字段名（支持点语法，如 item_list.0、bottleneck_progress）：{COLOR_END}").strip()
            value = input(f"{COLOR_OPTION}新值：{COLOR_END}").strip()
            success, msg = set_player_field(field, value)
            if success:
                print(f"{COLOR_GREEN}✅ {msg}{COLOR_END}")
            else:
                print(f"{COLOR_WARN}❌ {msg}{COLOR_END}")
                
        elif choice == "3":
            print(f"{COLOR_YELLOW}⚠️  警告：将直接覆盖全部玩家数据，请谨慎操作{COLOR_END}")
            confirm = input(f"{COLOR_YELLOW}确认继续？(y/n)：{COLOR_END}").strip().lower()
            if confirm != "y":
                continue
            print(f"{COLOR_SYSTEM}请粘贴完整JSON（输入 END 结束）：{COLOR_END}")
            lines = []
            while True:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            import json
            try:
                new_data = json.loads("\n".join(lines))
                success, msg = save_player_raw(new_data)
                if success:
                    print(f"{COLOR_GREEN}✅ {msg}{COLOR_END}")
                else:
                    print(f"{COLOR_WARN}❌ {msg}{COLOR_END}")
            except Exception as e:
                print(f"{COLOR_WARN}❌ JSON格式错误：{e}{COLOR_END}")
                
        elif choice == "4":
            print(f"\n{COLOR_YELLOW}==== 作弊菜单 ===={COLOR_END}")
            print(f"{COLOR_GREEN}1. 所有武功+999经验{COLOR_END}")
            print(f"{COLOR_GREEN}2. 清空瓶颈进度{COLOR_END}")
            print(f"{COLOR_GREEN}3. 声望+100{COLOR_END}")
            print(f"{COLOR_GREEN}4. 恢复满血满状态{COLOR_END}")
            sub = input(f"{COLOR_OPTION}选择：{COLOR_END}").strip()
            
            player = get_player()
            if sub == "1":
                for sk in player.martial_skill_list:
                    sk["exp"] = sk.get("exp", 0) + 999
                player.sync_overall_level()
                player.save()
                print(f"{COLOR_GREEN}✅ 所有武功已增加999经验{COLOR_END}")
            elif sub == "2":
                player.bottleneck_progress = 0
                player.bottleneck_ready = False
                player.save()
                print(f"{COLOR_GREEN}✅ 瓶颈进度已重置{COLOR_END}")
            elif sub == "3":
                # 更新玩家江湖名气
                player.reputation = player.reputation + 100
                player.save()
                print(f"{COLOR_GREEN}✅ 江湖声望+100（当前：{player.reputation}）{COLOR_END}")
            elif sub == "4":
                player.self_state = "状态完好，气血充盈，精神饱满"
                player.save()
                print(f"{COLOR_GREEN}✅ 状态已完全恢复{COLOR_END}")
            else:
                print(f"{COLOR_WARN}无效选项{COLOR_END}")

# ===================== 主循环 =====================
def game_core_loop():
    # 新增这一行，声明使用全局变量
    global latest_plot1_text
    print(f"{COLOR_SYSTEM}🔄 正在加载全局存档数据，启用DeepSeek-V4-Flash模型...{COLOR_END}")
    print(f"{COLOR_SYSTEM}📌 数据源规则：本地story_source.txt优先，缺失内容AI智能补齐{COLOR_END}")
    build_novel_world()
    init_player()
    init_npc_agents()
    save_data = init_save_data()
    ctx_cache = init_context_cache()
    # ===== 世界书初始化 =====
    if _WORLDBOOK_AVAILABLE:
        try:
            worldbook.init()
        except Exception as _wb_e:
            print(f"[世界书] 初始化异常（安全降级）: {_wb_e}")
    
    
    # ========== 启动展示上一局最后剧情 ==========
    print(f"\n{COLOR_GREEN}========== 上一局收尾剧情回顾 =========={COLOR_END}")
    if ctx_cache.get("interact_log") and len(ctx_cache["interact_log"]) > 0:
        last_record = ctx_cache["interact_log"][-1]
        print(f"{COLOR_PLOT}{last_record}{COLOR_END}")
    else:
        print(f"{COLOR_WARN}暂无历史剧情存档，本次为全新开局{COLOR_END}")
    print(f"{COLOR_GREEN}========================================\n{COLOR_END}")
    print(f"{COLOR_SYSTEM}✅ DeepSeek-V4-Flash 模型加载成功！已关闭网页解析，纯本地+AI补齐模式{COLOR_END}\n")
    print(f"{COLOR_SYSTEM}✅ 上下文缓存已升级【2000条超长记忆】模式，摘要自动滚动保留最新5轮交互{COLOR_END}")
    print(f"{COLOR_GREEN}💡 新增指令：输入 regen_npc 可强制重新分段解析全文生成全部NPC档案 | 输入 对战 开启武林对决{COLOR_END}\n")
    while True:
        print_game_header()
        user_input = input(f"{COLOR_GREEN}你的行动：{COLOR_END}").strip()
        # ====== 快捷指令处理 ======
        if user_input == "等级":
            query_player_level()
            continue
        # ===== 任务系统：统一菜单 =====
        if user_input == "任务":
            while True:
                print(f"\n{COLOR_SYSTEM}========== 任务中心 =========={COLOR_END}")
                print(f"{COLOR_GREEN}1. 新建任务{COLOR_END}")
                print(f"{COLOR_GREEN}2. 查看所有任务{COLOR_END}")
                print(f"{COLOR_GREEN}3. 查看进行中的任务{COLOR_END}")
                print(f"{COLOR_GREEN}4. 查看已完成的任务{COLOR_END}")
                print(f"{COLOR_GREEN}5. 完成任务{COLOR_END}")
                print(f"{COLOR_GREEN}6. 删除任务{COLOR_END}")
                print(f"{COLOR_GREEN}7. 更新任务进度（手动）{COLOR_END}")
                print(f"{COLOR_GREEN}8. 调整任务类型（主线/支线）{COLOR_END}")   # 新增
                print(f"{COLOR_GREEN}9. 搁置/激活任务（切换状态）{COLOR_END}")    # 新增
                print(f"{COLOR_GREEN}0. 返回主菜单{COLOR_END}")
                choice = input(f"{COLOR_OPTION}请选择操作（0-9）：{COLOR_END}").strip()
                        
                if choice == "1":
                    # 新建任务
                    name = input(f"{COLOR_OPTION}请输入任务名称：{COLOR_END}").strip()
                    if not name:
                        print(f"{COLOR_WARN}❌ 任务名称不能为空{COLOR_END}")
                        continue
                    desc = input(f"{COLOR_OPTION}请输入任务描述：{COLOR_END}").strip()
                    if not desc:
                        print(f"{COLOR_WARN}❌ 任务描述不能为空{COLOR_END}")
                        continue
                    success, msg = create_task(name, desc)
                    print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
                
                elif choice == "2":
                    result = list_tasks()
                    print(f"\n{COLOR_PLAYER}{result}{COLOR_END}")
                
                elif choice == "3":
                    result = list_tasks("active")
                    print(f"\n{COLOR_PLAYER}{result}{COLOR_END}")
                
                elif choice == "4":
                    result = list_tasks("completed")
                    print(f"\n{COLOR_PLAYER}{result}{COLOR_END}")
                
                elif choice == "5":
                    name = input(f"{COLOR_OPTION}请输入要完成的任务名称：{COLOR_END}").strip()
                    if not name:
                        print(f"{COLOR_WARN}❌ 任务名称不能为空{COLOR_END}")
                        continue
                    success, msg, stage_hist = complete_task(name)
                    print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
                    if success:
                        # DEBUG: 任务总结流程
                        print(f"[DEBUG 任务总结] 开始生成总结 for 任务「{name}」")
                        # 安全检查：stage_hist 可能为 None
                        stage_hist_str = stage_hist if stage_hist else "暂无"
                        print(f"[DEBUG 任务总结] 过程记录: {stage_hist_str}")
                        try:
                            cache = load_context_cache() or {}
                            recent_logs = cache.get("interact_log", [])[-5:]
                            recent_text = "\n\n".join(recent_logs) if recent_logs else "暂无"
                            loc = load_location_time()
                            location_name = loc.get("location", "江湖某处") if loc else "江湖某处"
                            player = get_player()
                            player_name = player.name if player else "李三奇"
                            # 补查任务完整信息（description/display_name/type）
                            task_info = get_task_info(name) or {}
                            task_desc = task_info.get("description", "")
                            display_name = task_info.get("display_name", name)
                            task_type = task_info.get("type", "side")
                            # 统计阶段数
                            stage_count = stage_hist_str.count("→") + 1 if stage_hist_str and stage_hist_str != "暂无" else 0
                            summary_prompt = f"""请为玩家「{player_name}」完成的任务撰写一段180~200字的任务剧情总结。

【任务信息】
任务编号：{name}
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
                            # 裸API调用，不带游戏系统提示词，避免LLM误生成剧情
                            resp = client.chat.completions.create(
                                model=DEEPSEEK_MODEL,
                                messages=[
                                    {"role": "system", "content": "你是武侠小说总结者。根据任务过程记录，写一段180~200字的任务剧情总结。"},
                                    {"role": "user", "content": summary_prompt}
                                ],
                                max_tokens=400,
                                temperature=0.4,
                                timeout=60,
                                extra_body={"thinking": {"type": "disabled"}}
                            )
                            # 安全检查：message.content 可能为 None
                            content = getattr(resp.choices[0].message, 'content', '') or ''
                            task_summary = content.strip()
                            if task_summary:
                                # 作为一轮剧情写入上下文（仿战斗系统）
                                update_context_cache(task_summary, user_action="任务完成")
                                _nn = ""
                                try:
                                    _p = get_player()
                                    if _p and _p.novel_node:
                                        _nn = _p.novel_node
                                except Exception:
                                    pass
                                upload_task_memory(CLOUD_MEM_SLOT_ID, name, stage_hist, task_summary, novel_node=_nn)
                                print(f"\n{COLOR_PLOT}【任务总结】\n{task_summary}{COLOR_END}")
                                print(f"[DEBUG 任务总结] 完成，输出{len(task_summary)}字")
                            else:
                                print("[DEBUG 任务总结] ⚠️ AI返回空内容")
                        except Exception as e:
                            print(f"[DEBUG 任务总结] ❌ 异常: {e}")
                
                elif choice == "6":
                    name = input(f"{COLOR_OPTION}请输入要删除的任务名称：{COLOR_END}").strip()
                    if not name:
                        print(f"{COLOR_WARN}❌ 任务名称不能为空{COLOR_END}")
                        continue
                    success, msg = delete_task(name)
                    print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
                
                elif choice == "7":
                    name = input(f"{COLOR_OPTION}请输入任务名称：{COLOR_END}").strip()
                    if not name:
                        print(f"{COLOR_WARN}❌ 任务名称不能为空{COLOR_END}")
                        continue
                    stage = input(f"{COLOR_OPTION}请输入当前阶段描述：{COLOR_END}").strip()
                    percent = input(f"{COLOR_OPTION}请输入进度百分比（0-100）：{COLOR_END}").strip()
                    try:
                        percent = int(percent)
                    except Exception:
                        percent = None
                    if  update_task_progress(name, stage, percent):
                        print(f"{COLOR_SYSTEM}✅ 任务「{name}」进度已更新{COLOR_END}")
                    else:
                        print(f"{COLOR_WARN}❌ 未找到进行中的任务「{name}」{COLOR_END}")
                elif choice == "8":
                    # 调整任务类型
                    name = input(f"{COLOR_OPTION}请输入任务名称：{COLOR_END}").strip()
                    if not name:
                        print(f"{COLOR_WARN}❌ 任务名称不能为空{COLOR_END}")
                        continue
                    print(f"{COLOR_GREEN}请选择新类型：{COLOR_END}")
                    print("  1. 主线任务（⭐ AI 优先推进）")
                    print("  2. 支线任务（○ 作为背景推进）")
                    type_choice = input(f"{COLOR_OPTION}请输入 1 或 2：{COLOR_END}").strip()
                    task_type = "main" if type_choice == "1" else "side"
                    success, msg = set_task_type(name, task_type)
                    print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
                
                elif choice == "9":
                    # 搁置/激活任务
                    name = input(f"{COLOR_OPTION}请输入任务名称：{COLOR_END}").strip()
                    if not name:
                        print(f"{COLOR_WARN}❌ 任务名称不能为空{COLOR_END}")
                        continue
                    success, msg = toggle_task_suspend(name)
                    print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
                
                elif choice == "0":
                    break
                else:
                    print(f"{COLOR_WARN}❌ 无效选项，请输入 0-7{COLOR_END}")
            continue
        if user_input == "编辑属性" or user_input == "作弊":
            player_edit_menu()
            continue
        if user_input == "功法":
            query_player_skill()
            # 追加境界和瓶颈信息
            player = get_player()
            if player:
                realm = player.overall_realm
                level = player.bottleneck_level
                progress = player.bottleneck_progress
                threshold = player.get_bottleneck_threshold()
                if level > 0:
                    bottleneck_info = f"第 {level} 重，进度 {progress}/{threshold}"
                else:
                    bottleneck_info = "无瓶颈"
                print(f"{COLOR_YELLOW}【当前总境界】{realm}{COLOR_END}")
                print(f"{COLOR_YELLOW}【瓶颈状态】{bottleneck_info}{COLOR_END}")
            continue
        if user_input == "物品":
            query_player_item()
            continue
        if user_input == "当前主线":
            from mainline_dynamic import get_pending_mainline
            print(f"\n{COLOR_PLOT}{get_pending_mainline()}{COLOR_END}")
            continue
        if user_input == "传闻":
            query_player_rumor()
            continue
        if user_input == "配图":
            draw_ascii(latest_plot=latest_plot1_text)
            continue
        if user_input == "遗忘功法":
            forget_player_skill()
            continue
        if user_input == "扔掉物品":
            discard_player_item()
            continue
        if user_input == "练功":
            success, msg = do_practice(is_first_init=False)
            # 获取当前玩家境界和瓶颈信息
            player = get_player()
            if player:
                realm = player.overall_realm
                level = player.bottleneck_level
                progress = player.bottleneck_progress
                threshold = player.get_bottleneck_threshold()
                if level > 0:
                    bottleneck_info = f"第 {level} 重，进度 {progress}/{threshold}"
                else:
                    bottleneck_info = "无"
                extra_info = f"\n{COLOR_YELLOW}【当前总境界】{realm}{COLOR_END}\n{COLOR_YELLOW}【瓶颈】{bottleneck_info}{COLOR_END}"
            else:
                extra_info = ""
            
            if success:
                print(f"{COLOR_GREEN}✅ {msg}{extra_info}{COLOR_END}")
            else:
                print(f"{COLOR_WARN}{msg}{extra_info}{COLOR_END}")
            continue
        if user_input == "选择主线":
            from mainline_dynamic import list_upcoming_mainlines
            print(f"\n{list_upcoming_mainlines()}")
            continue
        if user_input.startswith("跳转主线"):
            parts = user_input.split()
            if len(parts) >= 2 and parts[1].isdigit():
                from mainline_dynamic import set_mainline_skip
                success, msg = set_mainline_skip(int(parts[1]))
                print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
            else:
                print(f"{COLOR_WARN}❌ 用法：跳转主线 编号{COLOR_END}")
            continue
        if user_input == "regen_npc":
            print(f"{COLOR_YELLOW}开始强制分段解析全文story_source.txt，分批生成全新NPC档案{COLOR_END}")
            init_npc_agents(force_regen=True)
            print(f"{COLOR_GREEN}✅ NPC重新生成完成{COLOR_END}\n")
            continue
        # ========== 替换原来的 设置NPC状态 / 治愈NPC 两段代码 ==========
        handled, msg = handle_admin_commands(user_input)
        if handled:
            print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
            continue
        
        if user_input == "查看时空":
            loc_time = load_location_time()
            print(f"{COLOR_PLOT}当前地点：{loc_time.get('location')}，时间：{loc_time.get('time')}{COLOR_END}")
            continue
        if user_input in ("新建NPC", "添加NPC"):
            name = input(f"{COLOR_OPTION}NPC姓名：{COLOR_END}").strip()
            if not name:
                print(f"{COLOR_WARN}❌ 姓名不能为空{COLOR_END}")
                continue
            identity = input(f"{COLOR_OPTION}身份（可选）：{COLOR_END}").strip() or "江湖人士"
            fav = input(f"{COLOR_OPTION}初始好感（-100~100，默认15）：{COLOR_END}").strip()
            try:
                fav = int(fav)
            except ValueError:
                fav = 15
            success, msg = add_npc_manual(name, identity, "", fav)
            print(f"{COLOR_SYSTEM}{msg}{COLOR_END}")
            continue
        if user_input == "对战":
            current_npc_full_data = load_json(NPC_AGENT_FILE)
            target_input = input(f"\n{COLOR_GREEN}请输入本次对决的对手姓名：{COLOR_END}").strip()
            if not target_input:
                print(f"{COLOR_WARN}对手名称不能为空，取消对战{COLOR_END}")
                continue
            print(f"\n{COLOR_SYSTEM}==== 选择对战形式 ===={COLOR_END}")
            print(f"{COLOR_GREEN}1：常规比武过招（点到即止，切磋练手）{COLOR_END}")
            print(f"{COLOR_GREEN}2：生死死战（无留手，分生死）{COLOR_END}")
            print(f"{COLOR_GREEN}3：暗中偷袭（先手突袭，阴招暗算）{COLOR_END}")
            print(f"{COLOR_GREEN}4：擂台竞技（有裁判，规则约束）{COLOR_END}")
            print(f"{COLOR_GREEN}5：江湖群斗（混战无规则）{COLOR_END}")
            type_opt = input(f"{COLOR_GREEN}输入数字选择对战类型：{COLOR_END}").strip()
            battle_type_map = {
                "1": "常规比武过招，点到即止，双方仅切磋武学，不会下死手",
                "2": "生死死战，双方不留任何余地，以击杀对方为目标，招式凶狠致命",
                "3": "暗中偷袭，我方先手突袭，使用隐蔽、暗算类招式，对手猝不及防",
                "4": "擂台竞技，有第三方裁判约束，禁止阴毒杀招，分出胜负即停",
                "5": "江湖群斗，无固定招式套路，混战拉扯，场面杂乱激烈"
            }
            if type_opt not in battle_type_map:
                print(f"{COLOR_WARN}输入无效，取消对战{COLOR_END}")
                continue
            battle_desc = battle_type_map[type_opt]
            manual_npc_list = [target_input]
            # 取最近3轮剧情作为对战上下文（不足5轮则取全部）
            # 安全检查：ctx_cache 可能为 None
            recent_logs = ctx_cache.get("interact_log", [])[-3:] if ctx_cache else []
            recent_3_rounds_text = "\n".join(recent_logs) if recent_logs else "暂无前置剧情"
            
            run_battle_system(
                llm_common_func=llm_call_common,
                update_ctx_func=update_context_cache,
                update_plot_func=update_plot_save,
                modify_favor_func=modify_npc_favor,
                append_memory_func=append_npc_memory,
                update_npc_skill_func=update_npc_skill,
                update_player_func=parse_and_update_player_state,
                update_npc_func=parse_and_update_npc_state,
                ctx_cache=ctx_cache,
                his_text=recent_3_rounds_text,
                branch_text=save_data["branch_plot_content"],
                npc_all_data=current_npc_full_data,
                current_plot_npc_names=manual_npc_list,
                battle_style_desc=battle_desc,
                api_key=DEEPSEEK_API_KEY
            )
            continue
        elif user_input.startswith("查询历史"):
            parts = user_input.split()
            if len(parts) >= 2:
                try:
                    round_num = int(parts[1])
                    query_history(round_num)
                except ValueError:
                    print(f"{COLOR_WARN}请输入有效的轮次数字，例如：查询历史 500{COLOR_END}")
            else:
                print(f"{COLOR_WARN}用法：查询历史 <轮次>，例如：查询历史 500{COLOR_END}")
            continue
        
        # ===== 存档管理（二级菜单） =====
        if user_input == "存档管理":
            while True:
                print(f"\n{COLOR_SYSTEM}========== 📂 存档管理 =========={COLOR_END}")
                print(f"{COLOR_GREEN}1. 保存进度（存档）{COLOR_END}")
                print(f"{COLOR_GREEN}2. 读取进度（读档）{COLOR_END}")
                print(f"{COLOR_GREEN}3. 删除存档{COLOR_END}")
                print(f"{COLOR_GREEN}4. 查看存档列表{COLOR_END}")
                print(f"{COLOR_GREEN}0. 返回主菜单{COLOR_END}")
                
                choice = input(f"{COLOR_OPTION}请选择操作（0-4）：{COLOR_END}").strip()
                
                if choice == "1":
                    # 保存
                    slot_name = input(f"{COLOR_OPTION}请输入存档名称（如：拜入华山）：{COLOR_END}").strip()
                    if slot_name:
                        save_game(slot_name)
                    else:
                        print(f"{COLOR_WARN}❌ 存档名不能为空{COLOR_END}")
                
                elif choice == "2":
                    # 读档（先展示列表，方便复制名称）
                    list_saves()
                    slot_name = input(f"{COLOR_OPTION}请输入要读取的存档名称：{COLOR_END}").strip()
                    if slot_name:
                        load_game(slot_name)
                    else:
                        print(f"{COLOR_WARN}❌ 存档名不能为空{COLOR_END}")
                
                elif choice == "3":
                    # 删除
                    list_saves()
                    slot_name = input(f"{COLOR_OPTION}请输入要删除的存档名称：{COLOR_END}").strip()
                    if slot_name:
                        delete_save(slot_name)
                    else:
                        print(f"{COLOR_WARN}❌ 存档名不能为空{COLOR_END}")
                
                elif choice == "4":
                    # 查看列表
                    list_saves()
                
                elif choice == "0":
                    print(f"{COLOR_SYSTEM}返回主菜单...{COLOR_END}")
                    break
                
                else:
                    print(f"{COLOR_WARN}❌ 无效选项，请输入 0-4{COLOR_END}")
            continue  # 结束本轮循环，回到主输入
        if user_input.lower() == "exit":
            print(f"{COLOR_SYSTEM}💾 已自动保存全部进度，游戏退出，下次启动自动续档{COLOR_END}")
            break

        # ====== 普通剧情交互 ======
        result = process_one_round(user_input, is_web=False)
        # ===== 最终防线：打印前再次清洗 =====
        if result.get("plot"):
            result["plot"] = re.sub(
                r'【世界状态更新】\s*\{[^{}]*\}',
                '',
                result["plot"],
                flags=re.DOTALL
            ).strip()
            result["plot"] = re.sub(r'\n\s*\n', '\n', result["plot"])
        # 在命令行打印结果
        print(f"\n{COLOR_PLOT}【本轮剧情内容】{COLOR_END}")
        print(f"{COLOR_PLOT}{result['plot']}{COLOR_END}\n")
        print(f"{COLOR_CHANGE}【NPC状态变动】{result['npc_change']}{COLOR_END}")
        print(f"{COLOR_CHANGE}【道具/自身状态】{result['item_status']}{COLOR_END}\n")
        print(f"{COLOR_CHANGE}【当前时空】{result['location']}{COLOR_END}")

def clean_player_now():
    p = get_player()
    if not p:
        return
    # 修复：正确的列表推导式，先清理再过滤非空
    cleaned_items = []
    for item in p.item_list:
        if item:
            cleaned = _clean_item_name(item)
            if cleaned:
                cleaned_items.append(cleaned)
    p.item_list = cleaned_items
    p.rumor_list = [r for r in p.rumor_list if r and r.strip() not in ["（无）", "无", "(无)"] and not r.strip().startswith("（无）")]
    p.save()
    print("✅ 已清理 player.json")

# 取消下面这行的注释，运行一次即可
# clean_player_now()
def ensure_archive_dir():
    archive_dir = "data/history_archive"
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
        print(f"{COLOR_SYSTEM}✅ 已创建历史归档目录{COLOR_END}")
        
if __name__ == "__main__":
    ensure_archive_dir()
    game_core_loop()