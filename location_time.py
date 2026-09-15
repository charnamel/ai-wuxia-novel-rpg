import os
import random
import re
from file_utils import save_json, load_json

LOCATION_TIME_FILE = "data/location_time.json"

# ===== 时间序列 =====
TIME_SEQUENCE = ["子时", "丑时", "寅时", "卯时", "辰时", "巳时", "午时", "未时", "申时", "酉时", "戌时", "亥时"]
# 合法时辰白名单（12标准值）；任何时辰字段写入/读取前必须过这张表
VALID_SHICHEN = set(TIME_SEQUENCE)
# 从任意文本中提取第一个出现的标准时辰（兼容AI乱加的"略耗""三刻""次日"等附加文字）
# 按 TIME_SEQUENCE 顺序优先匹配长的"X时"，保证"子时"不被"子"先截断
_RE_SHICHEN_EXTRACT = re.compile(r"(子|丑|寅|卯|辰|巳|午|未|申|酉|戌|亥)时")


def normalize_shichen(raw_text):
    """把AI输出的时辰文本清洗为12标准值之一。
    - 合法原值（完全等于标准值）：直接返回
    - 含附加文字：提取第一个匹配的标准时辰（例："辰时（略耗）"→"辰时"，"午时三刻出发"→"午时"）
    - 完全匹配不到：返回 None（调用方据此拒绝写入）
    - None / 空串 / 非字符串：返回 None
    """
    if raw_text is None:
        return None
    if not isinstance(raw_text, str):
        try:
            raw_text = str(raw_text)
        except Exception:
            return None
    s = raw_text.strip()
    if not s:
        return None
    if s in VALID_SHICHEN:
        return s
    m = _RE_SHICHEN_EXTRACT.search(s)
    if m:
        return m.group(1) + "时"
    return None

# ===== 时辰对应的24小时制对照表 =====
TIME_24H_MAP = {
    "子时": "23:00-01:00", "丑时": "01:00-03:00", "寅时": "03:00-05:00",
    "卯时": "05:00-07:00", "辰时": "07:00-09:00", "巳时": "09:00-11:00",
    "午时": "11:00-13:00", "未时": "13:00-15:00", "申时": "15:00-17:00",
    "酉时": "17:00-19:00", "戌时": "19:00-21:00", "亥时": "21:00-23:00"
}

# ===== 统一天气池（兜底用，与原 WEATHER_SEQUENCE 保持完全一致，不新增任何天气名）=====
WEATHER_SEQUENCE = [
    "晴", "晴", "万里无云", "艳阳高照", "微风",
    "多云", "多云", "阴天", "雾霾",
    "小雨", "毛毛雨", "大雨", "雷雨", "雨过天晴",
    "小雪", "大雪", "雨夹雪",
    "大风", "狂风", "沙尘暴",
    "大雾", "闷热", "霜冻"
]

# ===== 季节天气池（全部从通用池现有名称拆选，不新增天气，保证前端显示兼容）=====
SPRING_WEATHER = [
    "晴", "晴", "万里无云", "多云", "多云", "阴天", "微风",
    "毛毛雨", "小雨", "雨过天晴", "大雾"
]
SUMMER_WEATHER = [
    "晴", "万里无云", "艳阳高照", "多云", "阴天", "闷热", "闷热",
    "毛毛雨", "小雨", "大雨", "雷雨", "雷雨", "大风", "雾霾", "雨过天晴"
]
AUTUMN_WEATHER = [
    "晴", "晴", "万里无云", "多云", "多云", "阴天", "微风",
    "毛毛雨", "小雨", "雨过天晴", "霜冻", "大雾"
]
WINTER_WEATHER = [
    "晴", "多云", "阴天",
    "小雪", "大雪", "雨夹雪",
    "大风", "狂风", "霜冻", "大雾"
]

_SEASON_POOL_MAP = {
    "春": SPRING_WEATHER,
    "夏": SUMMER_WEATHER,
    "秋": AUTUMN_WEATHER,
    "冬": WINTER_WEATHER,
}

# ===== 统一触发常量 =====
_WEATHER_ROLL_INTERVAL = 5   # 每N轮一次抽奖机会
_WEATHER_ROLL_PROB = 0.25    # 到达阈值后的中奖概率
# 玩家旁白指定天气后，跳过接下来 N 次抽奖机会（抽奖 5 轮才一次，1 次≈最多锁 5 轮）
_PLAYER_WEATHER_LOCK_ROLLS = 1
# 季节解析正则（优先匹配"YYYY年X(天/季)"，抓不到再全文抓第一个春夏秋冬字兜底）
_RE_YEAR_SEASON = re.compile(r"(\d{1,4})年\s*(春|夏|秋|冬)(?:天|季)?")
_RE_FIRST_SEASON = re.compile(r"(春|夏|秋|冬)(?:天|季)?")

def init_location_time():
    if not os.path.exists(LOCATION_TIME_FILE):
        default = {
            "location": "",
            "time": "卯时",
            "weather": random.choice(["晴", "多云"])
        }
        save_json(LOCATION_TIME_FILE, default)

def load_location_time():
    init_location_time()
    data = load_json(LOCATION_TIME_FILE)
    if data is None:
        return None
    dirty = False

    # weather 兜底补
    if "weather" not in data:
        data["weather"] = random.choice(["晴", "多云"])
        dirty = True

    # ===== 时辰脏数据自动清洗（读端兜底，修一次存档就干净了）=====
    raw_t = data.get("time")
    if raw_t is None or not isinstance(raw_t, str) or raw_t not in VALID_SHICHEN:
        cleaned = normalize_shichen(raw_t)
        if cleaned is not None:
            print(f"[时辰] 存档脏值修复：{repr(raw_t)} → {cleaned}")
            data["time"] = cleaned
            dirty = True
        else:
            # 完全清洗不出来，兜底到卯时（与 init_location_time 默认值一致）
            print(f"[时辰] 存档值 {repr(raw_t)} 无法清洗，兜底为『卯时』")
            data["time"] = "卯时"
            dirty = True

    if dirty:
        save_location_time(data)
    return data

def save_location_time(data):
    save_json(LOCATION_TIME_FILE, data)

def update_location_time(location=None, time=None, weather=None):
    """写入端时辰校验：任何调用方传入的 time 必须先过 normalize_shichen。
    - 合法/可清洗 → 写入标准值
    - 完全非法（None、空、清洗失败）→ 不写入 time 字段，并打印警告。
    返回 (写入后的数据, time_was_accepted:bool) 便于调用方判断。
    """
    data = load_location_time()
    if data is None:
        return None, False
    if location is not None:
        data["location"] = location
    time_ok = False
    if time is not None:
        cleaned = normalize_shichen(time)
        if cleaned is not None:
            if cleaned != (time if isinstance(time, str) else time):
                print(f"[时辰] 写入清洗：{repr(time)} → {cleaned}")
            data["time"] = cleaned
            time_ok = True
        else:
            print(f"[时辰] 写入被拒（非法值）：{repr(time)}")
    if weather is not None:
        data["weather"] = weather
    save_location_time(data)
    return data, time_ok

# ===== 【新增】将时辰转换为带 24 小时制的显示格式 =====
def format_time_with_24h(time_str):
    if time_str in TIME_24H_MAP:
        return f"{time_str}（{TIME_24H_MAP[time_str]}）"
    return time_str

# ===== 时间推进（仅推进时辰，不再处理天气；天气统一走 roll_weather_if_needed 轮次入口）=====
def advance_world_time(current_data=None):
    if current_data is None:
        current_data = load_location_time()

    current_time = current_data.get("time", TIME_SEQUENCE[0])
    try:
        idx = TIME_SEQUENCE.index(current_time)
        next_idx = (idx + 1) % len(TIME_SEQUENCE)
        current_data["time"] = TIME_SEQUENCE[next_idx]
    except ValueError:
        current_data["time"] = TIME_SEQUENCE[0]

    save_location_time(current_data)
    return current_data


# ===== 季节池选择 =====
def get_season_weather_pool(novel_node_text):
    """从 novel_node（"1755年秋，..." 等形式）解析季节并返回对应天气池。
    两级兜底：
    1) 优先匹配「YYYY年X(天/季)?」格式；
    2) 抓不到年，就在全文里找第一个春夏秋冬字作为兜底（支持"乾隆二十年秋初"这类脏值）；
    3) 完全匹配不上 → 返回统一天气池 WEATHER_SEQUENCE。
    """
    text = novel_node_text or ""
    if not text:
        return WEATHER_SEQUENCE
    m = _RE_YEAR_SEASON.search(text)
    if m:
        season = m.group(2)
        if season in _SEASON_POOL_MAP:
            return _SEASON_POOL_MAP[season]
    m2 = _RE_FIRST_SEASON.search(text)
    if m2:
        season = m2.group(1)
        if season in _SEASON_POOL_MAP:
            return _SEASON_POOL_MAP[season]
    return WEATHER_SEQUENCE


# ===== ★ 天气变更唯一入口：每 5 轮剧情，25% 概率从季节池随机换天气 ★ =====
def roll_weather_if_needed(round_num, novel_node_text=""):
    """剧情轮次统一触发。
    - round_num <= 0：新开局守卫，直接返回（避免首轮抽 0%5==0 误触发）
    - 非 5 的倍数轮次：零开销直接返回
    - 到达阈值：25% 概率按 novel_node 选池抽奖；抽到同值不覆写、不计日志
    异常全捕获只打印，不影响主循环返回。
    """
    try:
        if round_num is None or round_num <= 0:
            return None
        if round_num % _WEATHER_ROLL_INTERVAL != 0:
            return None
        if random.random() >= _WEATHER_ROLL_PROB:
            return None

        pool = get_season_weather_pool(novel_node_text)
        new_weather = random.choice(pool)

        data = load_location_time()
        old = data.get("weather", "")

        # ===== 玩家旁白指定过天气 → 跳过接下来 N 次抽奖机会（不覆盖玩家的指定）=====
        try:
            lock_rolls = int(data.get("weather_lock_rolls") or 0)
        except Exception:
            lock_rolls = 0
        if lock_rolls > 0:
            lock_rolls -= 1
            if lock_rolls > 0:
                data["weather_lock_rolls"] = lock_rolls
            else:
                data.pop("weather_lock_rolls", None)
            save_location_time(data)
            print(f"[天气] 玩家指定锁定中（还剩 {lock_rolls} 次抽奖），本轮跳过")
            return None

        if new_weather == old:
            return None  # 抽到相同就静默，不写盘不日志

        data["weather"] = new_weather
        # 清掉旧计数器（之前 v1.7.8 残留 _weather_tick，避免脏值长期占存档）
        if "_weather_tick" in data:
            del data["_weather_tick"]
        save_location_time(data)
        try:
            season_hit = None
            m = _RE_YEAR_SEASON.search(novel_node_text or "")
            if m: season_hit = m.group(2) + "季"
            else:
                m2 = _RE_FIRST_SEASON.search(novel_node_text or "")
                if m2: season_hit = m2.group(1) + "季"
            pool_tag = season_hit if season_hit else "通用池"
            print(f"[天气] 第{round_num}轮触发（{pool_tag}）：{old} → {new_weather}")
        except Exception:
            print(f"[天气] 第{round_num}轮触发：{old} → {new_weather}")
        return (old, new_weather)
    except Exception as e:
        print(f"[天气] roll异常（已吞）：{e}")
        return None


# ============================================================================
# ★ 玩家旁白指定天气（#旁白段）→ 匹配天气词 → 就近落进「当前季节池」
#   规则：最长词优先 → 否定/结束句处理 → 同族裸词不改写 → 跨季同族降级
# ============================================================================

# 每族「候选天气名」按强度分组（weak 温和 / none 裸词 / strong 猛烈），
# 取值时取第一个「在当前季节池里」的；池内没有该族 → 按 _FAMILY_FALLBACK 换族再来。
_FAMILY_CANDIDATES = {
    "晴":   {"weak": ["晴"],                      "none": ["晴"],                      "strong": ["艳阳高照", "万里无云", "晴"]},
    "云":   {"weak": ["多云", "晴"],              "none": ["多云", "晴"],              "strong": ["阴天", "多云"]},
    "阴":   {"weak": ["阴天", "多云"],            "none": ["阴天", "多云"],            "strong": ["阴天", "多云"]},
    "雾":   {"weak": ["雾霾", "大雾"],            "none": ["大雾", "雾霾"],            "strong": ["大雾", "雾霾"]},
    "雨":   {"weak": ["毛毛雨", "小雨"],          "none": ["小雨", "毛毛雨"],          "strong": ["大雨", "雷雨", "小雨"]},
    "雷":   {"weak": ["雷雨", "大雨"],            "none": ["雷雨", "大雨"],            "strong": ["雷雨", "大雨"]},
    "雪":   {"weak": ["小雪"],                    "none": ["小雪"],                    "strong": ["大雪", "小雪"]},
    "夹雪": {"weak": ["雨夹雪", "小雪"],          "none": ["雨夹雪", "小雪"],          "strong": ["大雪", "雨夹雪"]},
    "风":   {"weak": ["微风", "大风"],            "none": ["大风", "微风"],            "strong": ["狂风", "大风"]},
    "闷热": {"weak": ["闷热"],                    "none": ["闷热"],                    "strong": ["闷热", "艳阳高照", "晴"]},
    "霜":   {"weak": ["霜冻"],                    "none": ["霜冻"],                    "strong": ["霜冻"]},
    "晴后": {"weak": ["雨过天晴"],                "none": ["雨过天晴"],                "strong": ["雨过天晴"]},
}

# 跨季降级：当前季节池里没有这个族时，改用这些族（同强度再就近取）
_FAMILY_FALLBACK = {
    "雪": "雨", "夹雪": "雨", "霜": "雾", "闷热": "晴", "雷": "雨", "晴后": "晴",
    "雨": "雪",
}

# 同族内强度降级顺序（请求的强度在池里没有时，按这个顺序退而求其次）
_INTENSITY_ORDER = {
    "strong": ["none", "weak"],
    "none": ["weak", "strong"],
    "weak": ["none", "strong"],
}

# 天气名 → 族（用于「同族裸词不改写」判定，覆盖通用池全部名字）
_NAME_FAMILY = {
    "晴": "晴", "万里无云": "晴", "艳阳高照": "晴",
    "多云": "云", "阴天": "阴", "雾霾": "雾", "大雾": "雾",
    "小雨": "雨", "毛毛雨": "雨", "大雨": "雨", "雨过天晴": "晴后", "雷雨": "雷",
    "小雪": "雪", "大雪": "雪", "雨夹雪": "夹雪",
    "微风": "风", "大风": "风", "狂风": "风", "沙尘暴": "风",
    "闷热": "闷热", "霜冻": "霜",
}

# 关键词 → (族, 强度)；匹配时按长度倒序，长词优先。
# 注意：不收录「风/云/阴/雾/霜」等单字，避免「风光/风俗/云游」这类误触发。
_WEATHER_KEYWORDS = {
    # —— 晴 ——
    "万里无云": ("晴", "strong"), "艳阳高照": ("晴", "strong"),
    "阳光明媚": ("晴", "strong"), "烈日当空": ("晴", "strong"),
    "骄阳似火": ("晴", "strong"),
    "晴空万里": ("晴", "none"), "晴朗": ("晴", "none"), "大晴天": ("晴", "none"),
    "放晴": ("晴", "none"), "转晴": ("晴", "none"), "天晴": ("晴", "none"),
    "晴天": ("晴", "none"), "阳光": ("晴", "none"), "日头": ("晴", "none"),
    "艳阳": ("晴", "strong"), "烈日": ("晴", "strong"), "骄阳": ("晴", "strong"),
    "晴": ("晴", "none"),
    # —— 云 / 阴 ——
    "乌云密布": ("阴", "strong"), "乌云翻滚": ("阴", "strong"),
    "阴云密布": ("阴", "strong"), "天色阴沉": ("阴", "none"),
    "天色暗": ("阴", "none"), "阴云": ("阴", "none"),
    "乌云": ("云", "none"), "云层": ("云", "none"), "云彩": ("云", "none"),
    "转多云": ("云", "none"), "多云": ("云", "none"),
    "阴天": ("阴", "none"), "转阴": ("阴", "none"), "天阴": ("阴", "none"),
    # —— 雾 ——
    "浓雾弥漫": ("雾", "strong"), "雾气弥漫": ("雾", "strong"),
    "雾蒙蒙": ("雾", "weak"),
    "浓雾": ("雾", "strong"), "大雾": ("雾", "strong"),
    "雾气": ("雾", "none"), "起雾": ("雾", "none"), "雾霾": ("雾", "weak"),
    # —— 雨 ——
    "倾盆大雨": ("雨", "strong"), "瓢泼大雨": ("雨", "strong"),
    "大雨倾盆": ("雨", "strong"), "暴雨倾盆": ("雨", "strong"),
    "狂风暴雨": ("雨", "strong"), "风雨交加": ("雨", "strong"),
    "暴风骤雨": ("雨", "strong"), "暴雨如注": ("雨", "strong"),
    "蒙蒙细雨": ("雨", "weak"), "毛毛雨": ("雨", "weak"),
    "淅淅沥沥": ("雨", "weak"), "细雨": ("雨", "weak"), "小雨": ("雨", "weak"),
    "暴雨": ("雨", "strong"), "骤雨": ("雨", "strong"),
    "阵雨": ("雨", "strong"), "大雨": ("雨", "strong"),
    "雷雨": ("雷", "strong"),
    "下雨": ("雨", "none"), "落雨": ("雨", "none"), "雨天": ("雨", "none"),
    "雨声": ("雨", "none"), "雨点": ("雨", "none"), "雨水": ("雨", "none"),
    # —— 雷 ——
    "电闪雷鸣": ("雷", "strong"), "雷电交加": ("雷", "strong"),
    "雷阵雨": ("雷", "strong"), "打雷": ("雷", "strong"),
    "雷声": ("雷", "strong"), "雷霆": ("雷", "strong"),
    # —— 雪 ——
    "鹅毛大雪": ("雪", "strong"), "大雪纷飞": ("雪", "strong"),
    "风雪交加": ("雪", "strong"), "暴风雪": ("雪", "strong"),
    "暴雪": ("雪", "strong"), "风雪": ("雪", "strong"), "大雪": ("雪", "strong"),
    "雪花": ("雪", "none"), "飘雪": ("雪", "none"), "飞雪": ("雪", "none"),
    "落雪": ("雪", "none"), "雪片": ("雪", "none"), "下雪": ("雪", "none"),
    "小雪": ("雪", "weak"),
    "雨夹雪": ("夹雪", "none"),
    # —— 风 ——
    "狂风大作": ("风", "strong"), "狂风呼啸": ("风", "strong"),
    "北风呼啸": ("风", "strong"), "微风拂面": ("风", "weak"),
    "朔风": ("风", "strong"), "狂风": ("风", "strong"), "大风": ("风", "strong"),
    "风沙": ("风", "strong"), "沙尘": ("风", "strong"), "风大": ("风", "strong"),
    "微风": ("风", "weak"), "清风": ("风", "weak"), "和风": ("风", "weak"),
    "起风": ("风", "none"), "刮风": ("风", "none"), "风起": ("风", "none"),
    # —— 冷热 ——
    "天寒地冻": ("霜", "strong"), "寒风刺骨": ("霜", "strong"),
    "酷热": ("闷热", "strong"), "炎热": ("闷热", "strong"),
    "暑气": ("闷热", "strong"), "热浪": ("闷热", "strong"),
    "闷热": ("闷热", "none"), "天热": ("闷热", "none"),
    "严寒": ("霜", "strong"), "结冰": ("霜", "strong"), "结霜": ("霜", "strong"),
    "寒冷": ("霜", "none"), "白霜": ("霜", "none"), "霜冻": ("霜", "none"),
}
_WEATHER_KEYWORDS_ORDERED = sorted(_WEATHER_KEYWORDS.keys(), key=len, reverse=True)

# 旁白段提取：未转义的 # 开头到行尾/下一个 #
_RE_NARRATION_SEG = re.compile(r"(?<!\\)#([^\n#]+)")
# 否定词（命中词「之前」出现 → 不是在说天气，跳过）
_RE_NEG_BEFORE = re.compile(r"(不|没|没有|无|未|别|莫|岂|哪)\s*\S{0,2}$")
# 否定词（命中词「之后」出现 → 否定当前说法，跳过）
_RE_NEG_AFTER = re.compile(r"^\s*(不|没|无|未|别)")
# 天气「结束句」独立识别（不依赖词表）：雨停了 / 雪住了 / 风不刮了 → 雨过天晴
_RE_WEATHER_OVER = re.compile(
    r"(雨|雪|风|雾|雷)\s*(停|住|散|歇|止|过)了?"
    r"|(雨|雪|风)\s*(也)?\s*不\s*(下|刮|飘|落|见|停)?了"
)


def _resolve_weather_name(family, intensity, pool):
    """把 (族, 强度) 落到池内的具体天气名。
    顺序：该强度候选 → 同族其它强度 → 跨季换族 → 放弃(None)。
    """
    cands = _FAMILY_CANDIDATES.get(family, {})
    for key in [intensity] + _INTENSITY_ORDER.get(intensity, []):
        for name in (cands.get(key) or []):
            if name in pool:
                return name
    fb = _FAMILY_FALLBACK.get(family)
    if fb and fb != family:
        return _resolve_weather_name(fb, intensity, pool)
    return None


def _match_weather_in_text(text, pool, old=""):
    """在一段旁白里找天气意图 → 返回池内天气名（无命中/无需改动返回 None）。"""
    # 1) 天气结束句：雨停了 / 雪住了 / 风不刮了 → 雨过天晴（池内没有则同族降级）
    if _RE_WEATHER_OVER.search(text):
        return _resolve_weather_name("晴后", "none", pool)

    for kw in _WEATHER_KEYWORDS_ORDERED:
        idx = text.find(kw)
        if idx < 0:
            continue
        before = text[max(0, idx - 3):idx]
        after = text[idx + len(kw):idx + len(kw) + 3]
        # 2) 否定句：不下雪 / 没有下雨 / 雪不下了 → 跳过
        if _RE_NEG_BEFORE.search(before) or _RE_NEG_AFTER.match(after):
            continue
        family, intensity = _WEATHER_KEYWORDS[kw]
        # 3) 同族裸词不改写（"窗外雨声渐密"不该把 大雨 降级成 小雨）
        if intensity == "none" and _NAME_FAMILY.get(old) == family:
            return None
        return _resolve_weather_name(family, intensity, pool)
    return None


def apply_player_weather(user_text, novel_node_text="", round_num=None):
    """玩家旁白（#段）指定天气 → 就近写入当前季节池对应的天气。

    - user_text：玩家原始输入（只认未转义的 # 段）
    - novel_node_text：用于解析当前季节（"1755年秋，..."）
    - round_num：轮次（保留参数，便于日志/后续扩展）
    写入时会给天气打上 _PLAYER_WEATHER_LOCK_ROLLS 次抽奖的锁定期。
    返回写入后的天气名；未命中/无变化/异常 → None（绝不影响主流程）
    """
    try:
        if not user_text or "#" not in user_text:
            return None
        pool = get_season_weather_pool(novel_node_text)
        data = load_location_time()
        if data is None:
            return None
        old = data.get("weather", "")

        target = None
        for m in _RE_NARRATION_SEG.finditer(user_text):
            chunk = m.group(1).strip()
            if not chunk:
                continue
            target = _match_weather_in_text(chunk, pool, old)
            if target:
                break
        if not target or target == old:
            return None

        data["weather"] = target
        if _PLAYER_WEATHER_LOCK_ROLLS > 0:
            data["weather_lock_rolls"] = _PLAYER_WEATHER_LOCK_ROLLS
        if "_weather_tick" in data:
            del data["_weather_tick"]
        save_location_time(data)

        season_tag = ""
        mm = _RE_YEAR_SEASON.search(novel_node_text or "")
        if mm:
            season_tag = mm.group(2) + "季池"
        else:
            mm2 = _RE_FIRST_SEASON.search(novel_node_text or "")
            season_tag = (mm2.group(1) + "季池") if mm2 else "通用池"
        print(f"[天气] 玩家旁白指定（{season_tag}）：{old} → {target}")
        return target
    except Exception as e:
        print(f"[天气] 玩家指定异常（已吞）：{e}")
        return None