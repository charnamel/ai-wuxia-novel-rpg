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