# -*- coding: utf-8 -*-
"""
config.py — 全局配置中心
==================================
【设计原则】密钥与代码分离，所有 API 配置从 .env 读取
"""
import os

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

# ====== 百炼配置（cloud_memory_v2.py 也直接读取 .env，此处仅做透传）======
DASHSCOPE_API_KEY = _env("DASHSCOPE_API_KEY")
BAILIAN_PLOT_MEMORY_ID = _env("BAILIAN_PLOT_MEMORY_ID")
BAILIAN_WORLD_KNOWLEDGE_ID = _env("BAILIAN_WORLD_KNOWLEDGE_ID")
ENABLE_CLOUD_MEMORY = _env("ENABLE_CLOUD_MEMORY", "true").lower() == "true"
CLOUD_MEM_SLOT_ID = _env("CLOUD_MEM_SLOT_ID", "default_player")

# ====== 主循环（3选1，MAIN_LOOP_ACTIVE=A/B/C）======
_ml_active = _env("MAIN_LOOP_ACTIVE", "A")
MAIN_LOOP_API_KEY = _env(f"MAIN_LOOP_{_ml_active}_API_KEY")
MAIN_LOOP_BASE_URL = _env(f"MAIN_LOOP_{_ml_active}_BASE_URL")
MAIN_LOOP_MODEL = _env(f"MAIN_LOOP_{_ml_active}_MODEL")
MAIN_LOOP_TIMEOUT = _env_int(f"MAIN_LOOP_{_ml_active}_TIMEOUT", 120)
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
