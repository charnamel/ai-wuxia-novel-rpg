# -*- coding: utf-8 -*-
"""
config.py — 全局配置中心 v2
==================================
【设计原则】密钥与代码分离，所有 API 配置从 .env 读取
【备份】原硬编码版本见 config.py.bak
【回滚】cp config.py.bak config.py 即可恢复
"""
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def _env(key, default=""):
    """安全读取环境变量"""
    return os.getenv(key, default)

def _env_int(key, default=90):
    """安全读取环境变量（整数）"""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def _env_float(key, default=0.0):
    """安全读取环境变量（浮点数）"""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

# ====== 百炼配置（cloud_memory_v2.py 也直接读取 .env，此处仅做透传）======
DASHSCOPE_API_KEY = _env("DASHSCOPE_API_KEY")
BAILIAN_PLOT_MEMORY_ID = _env("BAILIAN_PLOT_MEMORY_ID")
BAILIAN_WORLD_KNOWLEDGE_ID = _env("BAILIAN_WORLD_KNOWLEDGE_ID")
ENABLE_CLOUD_MEMORY = _env("ENABLE_CLOUD_MEMORY", "true").lower() == "true"
CLOUD_MEM_SLOT_ID = _env("CLOUD_MEM_SLOT_ID", "default_player_XSFH6")

# ====== 主循环（3选1，MAIN_LOOP_ACTIVE=A/B/C）======
_ml_active = _env("MAIN_LOOP_ACTIVE", "A")
MAIN_LOOP_API_KEY = _env(f"MAIN_LOOP_{_ml_active}_API_KEY")
MAIN_LOOP_BASE_URL = _env(f"MAIN_LOOP_{_ml_active}_BASE_URL")
MAIN_LOOP_MODEL = _env(f"MAIN_LOOP_{_ml_active}_MODEL")
MAIN_LOOP_TIMEOUT = _env_int(f"MAIN_LOOP_{_ml_active}_TIMEOUT", 120)

# ====== OpenCode Go 会话头（09/06 起缺 x-opencode-session 头可能被拒）======
# 三个主循环各自独立的会话 ID；留空则该槽不发送该头。可经 web 端「系统/API预设」编辑。
MAIN_LOOP_A_SESSION_ID = _env("MAIN_LOOP_A_SESSION_ID", "")
MAIN_LOOP_B_SESSION_ID = _env("MAIN_LOOP_B_SESSION_ID", "")
MAIN_LOOP_C_SESSION_ID = _env("MAIN_LOOP_C_SESSION_ID", "")
# 按当前激活槽选择（main.py 继续使用 MAIN_LOOP_SESSION_ID，无需改动）
MAIN_LOOP_SESSION_ID = {"A": MAIN_LOOP_A_SESSION_ID, "B": MAIN_LOOP_B_SESSION_ID, "C": MAIN_LOOP_C_SESSION_ID}.get(_ml_active, "")

if not MAIN_LOOP_API_KEY:
    print(f"[config] 警告: MAIN_LOOP_{_ml_active}_API_KEY 未设置，请检查 .env")

# ====== 辅助（2选1，AUX_ACTIVE=A/B）======
_aux_active = _env("AUX_ACTIVE", "A")
DEEPSEEK_API_KEY = _env(f"AUX_{_aux_active}_API_KEY")
DEEPSEEK_BASE_URL = _env(f"AUX_{_aux_active}_BASE_URL")
DEEPSEEK_MODEL = _env(f"AUX_{_aux_active}_MODEL")
COMMON_TIMEOUT = _env_int(f"AUX_{_aux_active}_TIMEOUT", 90)
if not DEEPSEEK_API_KEY:
    print(f"[config] 警告: AUX_{_aux_active}_API_KEY 未设置，请检查 .env")

# ====== LLM 温度与 top_p 设置（两套：主循环 / 辅助）======
# 均从 .env 读取（MAIN_LOOP_TEMP 等），未设置时用下方默认值；可在 Web「API 设置」面板编辑
# 主循环（剧情生成，main.py 主循环 / web 主剧情共用）
MAIN_LOOP_TEMP = _env_float("MAIN_LOOP_TEMP", 0.65)
MAIN_LOOP_TOP_P = _env_float("MAIN_LOOP_TOP_P", 1.0)
# 辅助（后台总结/传记/记忆/章节摘要/世界观/任务/NPC档案等）
AUX_LOOP_TEMP = _env_float("AUX_LOOP_TEMP", 0.3)
AUX_LOOP_TOP_P = _env_float("AUX_LOOP_TOP_P", 1.0)
# 特殊辅助常量（保留较高创造性，不并入统一0.3）
OPENING_INSIGHT_TEMP = _env_float("OPENING_INSIGHT_TEMP", 0.7)   # 开局面貌 / 初始感悟
TEMP_NPC_PROFILE_TEMP = _env_float("TEMP_NPC_PROFILE_TEMP", 0.6)  # web 临时对手档案生成

# ====== 配图 LLM（2选1，IMG_GEN_ACTIVE=A/B）======
_img_active = _env("IMG_GEN_ACTIVE", "A")
IMG_GEN_API_KEY = _env(f"IMG_GEN_{_img_active}_API_KEY")
IMG_GEN_BASE_URL = _env(f"IMG_GEN_{_img_active}_BASE_URL")
IMG_GEN_MODEL = _env(f"IMG_GEN_{_img_active}_MODEL")
IMG_GEN_TIMEOUT = _env_int(f"IMG_GEN_{_img_active}_TIMEOUT", 120)
if not IMG_GEN_API_KEY:
    print(f"[config] 警告: IMG_GEN_{_img_active}_API_KEY 未设置，请检查 .env")

# ====== Kolors 图片生成 ======
KOLORS_IMG_API_URL = _env("KOLORS_IMG_API_URL", "https://api.siliconflow.cn/v1/images/generations")
KOLORS_IMG_API_KEY = _env("KOLORS_IMG_API_KEY")
KOLORS_IMG_MODEL = _env("KOLORS_IMG_MODEL", "Kwai-Kolors/Kolors")
KOLORS_IMG_SIZE = _env("KOLORS_IMG_SIZE", "1024x1024")

# ====== 配图设置（非密钥，硬编码）======
KOLORS_PLOT_WIDTH = 400    # 配图缩放宽度（适配手机）
KOLORS_AVATAR_SIZE = 180   # NPC头像尺寸
PLOT_IMG_CACHE_DIR = "static/images/plot_cache"

# ====== Agnes 图片生成 API（备用，当前未使用）======
AGNES_IMG_API_URL = _env("AGNES_IMG_API_URL", "https://apihub.agnes-ai.com/v1/images/generations")
AGNES_IMG_API_KEY = _env("AGNES_IMG_API_KEY")
AGNES_IMG_MODEL = _env("AGNES_IMG_MODEL", "agnes-image-2.1-flash")
AGNES_IMG_SIZE = _env("AGNES_IMG_SIZE", "1024x1024")

# ====== NPC 生成配置 ======
NPC_GEN_TIMEOUT = 90
NPC_RETRY_SLEEP = 3
MAX_STORY_CHARS_FOR_NPC = 20000
CHUNK_SIZE = 500

# ====== 文件路径 ======
STORY_PATH = "story_source.txt"
WORLD_FILE = "data/world_setting.json"
PLAYER_FILE = "data/player.json"
NPC_AGENT_FILE = "data/npc_agents.json"
SAVE_FILE = "data/game_save.json"
CONTEXT_CACHE_FILE = "data/context_cache.json"
MAX_CONTEXT_LOG = 2000
SUMMARY_KEEP_RECENT_COUNT = 20

# ===== 主动检索小模型配置（独立于主循环模型） =====
# 用于云向量主动检索：小模型生成关键词 → 并行查向量库
# 失败时自动降级到被动检索，不影响主循环
ACTIVE_RETRIEVAL_API_KEY = _env("ACTIVE_RETRIEVAL_API_KEY", "") or DEEPSEEK_API_KEY
ACTIVE_RETRIEVAL_BASE_URL = _env("ACTIVE_RETRIEVAL_BASE_URL", "") or DEEPSEEK_BASE_URL
ACTIVE_RETRIEVAL_MODEL = _env("ACTIVE_RETRIEVAL_MODEL", "") or "deepseek-v4-flash"


# ===== thinking参数分派（按模型家族 + 面板开关返回extra_body） =====
# GLM-5.3/GLM-5.3-FLASH 强制思考：thinking.type传disabled直接400报错
# （官方文档：https://docs.bigmodel.cn/cn/guide/capabilities/thinking）
# DeepSeek 支持参数级开关：thinking.type=enabled/disabled + reasoning_effort=low/high/max
# （官方文档：https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/）
# ⚠️ 思考模式下 temperature 静默失效（不报错但不生效），top_p 仅 0.95-1.0 有效
# 面板键（web「API设置」；实时读 os.environ，面板保存后免重启生效）：
#   MAIN_LOOP_THINKING / AUX_LOOP_THINKING：auto=按家族默认（GLM开/其余关）/ enabled / disabled
#   MAIN_LOOP_REASONING_EFFORT / AUX_LOOP_REASONING_EFFORT：low / high / max
GLM_THINKING_EFFORT = _env("GLM_REASONING_EFFORT", "low")  # 兼容旧键：GLM 专用 effort（未设新键时回落）
_THINKING_EFFORTS = ("low", "high", "max")


def is_glm53(model_name):
    """是否GLM-5.3系列（强制思考，reasoning_content不可当正文用）"""
    return "glm-5.3" in (model_name or "").lower()


def _thinking_conf(model_name, loop):
    """返回 (enabled, effort)。GLM-5.3 强制开（官方不可关）；
    其余按面板开关，auto/未设置=家族默认（关，原行为）。非法 effort 回落 low/GLM旧键。"""
    forced = is_glm53(model_name)
    _key = {"main": "MAIN_LOOP_THINKING", "aux": "AUX_LOOP_THINKING"}.get(loop, "")
    mode = (os.getenv(_key, "auto") if _key else "auto").lower().strip()
    enabled = True if forced else (mode == "enabled")
    _eff_key = {"main": "MAIN_LOOP_REASONING_EFFORT", "aux": "AUX_LOOP_REASONING_EFFORT"}.get(loop, "")
    effort = (os.getenv(_eff_key, "") if _eff_key else "").lower().strip()
    if effort not in _THINKING_EFFORTS:
        # GLM 回落旧键 GLM_REASONING_EFFORT（实时读，与面板新键一致免重启）
        effort = (os.getenv("GLM_REASONING_EFFORT", "") if forced else "").lower().strip()
        if effort not in _THINKING_EFFORTS:
            effort = GLM_THINKING_EFFORT if forced else "low"
    return enabled, effort


def thinking_extra_body(model_name, loop="main"):
    """按模型名+回路返回thinking相关的extra_body dict。

    - glm-5.3系列：思考强制开启（不可关），用reasoning_effort控制成本
    - 其他模型：面板可配（loop="main"读MAIN_LOOP_*、loop="aux"读AUX_LOOP_*；auto=关，原行为）
    - loop="util"（主动检索等后台小任务）：恒关——开思考只增加延迟与成本
    """
    if loop == "util":
        return {"thinking": {"type": "disabled"}}
    enabled, effort = _thinking_conf(model_name, loop)
    if enabled:
        return {"thinking": {"type": "enabled"}, "reasoning_effort": effort}
    return {"thinking": {"type": "disabled"}}


def is_ds_thinking(model_name, loop="main"):
    """DeepSeek 且思考开启 → 主循环工具调用走「标准回传链路」。
    DeepSeek官方契约：带tools的请求必须回传reasoning_content（漏传400），
    回传后模型顺着自己的CoT续写正文，判定与剧情同源一致。
    其他模型（MiMo/GLM/DeepSeek关思考）无此契约，一律返回False走原MiMo兜底，行为不变。"""
    return "deepseek" in (model_name or "").lower() and _thinking_conf(model_name, loop)[0]


GLM53_MIN_MAX_TOKENS = 5000  # 思考token计入completion，额度不足时思考吃光导致content为空


def adjust_max_tokens(model_name, max_tokens, loop="main"):
    """思考开启时（任何模型）：max_tokens提到至少5000，给思维链留额度，防content为空。
    GLM-5.3恒开思考故恒保底；其他模型按面板开关判断。"""
    if loop != "util" and _thinking_conf(model_name, loop)[0]:
        return max(max_tokens or 0, GLM53_MIN_MAX_TOKENS)
    return max_tokens


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def strip_think_tags(text):
    """剥离模型内联思考块：<think>...▶（含未闭合前缀，即思考被max_tokens截断的情况）"""
    if not text:
        return text
    text = _THINK_RE.sub("", text)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


# ===== 裸思考泄漏清洗（思维链混入 content 的兜底） =====
# 场景：中转/聚合端点把思维链并进 content，或 content 为空时兜底提取 reasoning_content——
# 裸思维链（无标签包裹）直接进剧情/数据文件。依据：游戏正文与格式块全为中文，
# 裸思维链以英文为主，按"英文占比"逐行判定剔除。
_INTERJECTION_LINE_RE = re.compile(
    r"^(?:ok|okay|o\.k\.?|hmm+|ah+|oh+|alright|done|skip|wait|right|yeah|yes|no|"
    r"good|fine|so|now|then|let me|i'll|i think)[.!,~\s]*$", re.I)
_TRAILING_INTERJECTION_RE = re.compile(
    r"[\s\.,]*\s(?:OK|Okay|Hmm+|Alright|Done|Skip|Right)[\.\!]?\s*$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf【】]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def strip_reasoning_text(text):
    """剥离混入正文的思考过程（三层，防误伤中文正文/格式块）：
    1) ...▶ 标签块（复用 strip_think_tags，含未闭合前缀）
    2) 英文行：CJK=0 且字母≥8 的纯英文行；字母≥12 且字母≥3×CJK 的英文主导混合行
    3) 整行仅为英文口头禅（OK./Hmm./Let me…）的短行；行尾孤立口头禅（"无变化. OK."→"无变化"）
    中文主导行（含物品括号说明等）不受影响；数字/纯符号行保留。"""
    if not text:
        return text
    text = strip_think_tags(text)
    kept = []
    for line in text.splitlines():
        cjk = len(_CJK_RE.findall(line))
        latin = len(_LATIN_RE.findall(line))
        if latin >= 8 and cjk == 0:
            continue
        if latin >= 12 and cjk > 0 and latin >= 3 * cjk:
            continue
        if _INTERJECTION_LINE_RE.match(line.strip()):
            continue
        line = _TRAILING_INTERJECTION_RE.sub("", line)
        kept.append(line)
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
