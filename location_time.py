import os
import random
from file_utils import save_json, load_json

LOCATION_TIME_FILE = "data/location_time.json"

# ===== 时间序列 =====
TIME_SEQUENCE = ["子时", "丑时", "寅时", "卯时", "辰时", "巳时", "午时", "未时", "申时", "酉时", "戌时", "亥时"]

# ===== 【新增】时辰对应的24小时制对照表 =====
TIME_24H_MAP = {
    "子时": "23:00-01:00", "丑时": "01:00-03:00", "寅时": "03:00-05:00",
    "卯时": "05:00-07:00", "辰时": "07:00-09:00", "巳时": "09:00-11:00",
    "午时": "11:00-13:00", "未时": "13:00-15:00", "申时": "15:00-17:00",
    "酉时": "17:00-19:00", "戌时": "19:00-21:00", "亥时": "21:00-23:00"
}

# 天气池（晴好类加权，极端天气低频出现）
WEATHER_SEQUENCE = [
    "晴", "晴", "万里无云", "艳阳高照", "微风",
    "多云", "多云", "阴天", "雾霾",
    "小雨", "毛毛雨", "大雨", "雷雨", "雨过天晴",
    "小雪", "大雪", "雨夹雪",
    "大风", "狂风", "沙尘暴",
    "大雾", "闷热", "霜冻"
]

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
    if data and "weather" not in data:
        data["weather"] = random.choice(["晴", "多云"])
        save_location_time(data)
    return data

def save_location_time(data):
    save_json(LOCATION_TIME_FILE, data)

def update_location_time(location=None, time=None, weather=None):
    data = load_location_time()
    if location is not None:
        data["location"] = location
    if time is not None:
        data["time"] = time
    if weather is not None:
        data["weather"] = weather
    save_location_time(data)

# ===== 【新增】将时辰转换为带 24 小时制的显示格式 =====
def format_time_with_24h(time_str):
    if time_str in TIME_24H_MAP:
        return f"{time_str}（{TIME_24H_MAP[time_str]}）"
    return time_str

# ===== 时间推进 =====
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

    if random.random() < 0.25:
        new_weather = random.choice(WEATHER_SEQUENCE)
        current_data["weather"] = new_weather

    save_location_time(current_data)
    return current_data