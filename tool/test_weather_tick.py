"""天气间接触发逻辑快速验证（放 tool 目录，不污染主目录）
运行：python tool/test_weather_tick.py
"""
import os, sys, json, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 备份真实存档，测试完还原
REAL_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "location_time.json")
backup = None
if os.path.exists(REAL_FILE):
    with open(REAL_FILE, "r", encoding="utf-8") as f:
        backup = f.read()

try:
    # 固定种子保证可复现
    import random
    random.seed(42)

    from file_utils import save_json
    # 初始化一个测试用存档：weather=大雪，无_weather_tick
    save_json(REAL_FILE, {"location": "测试地", "time": "子时", "weather": "大雪"})

    from location_time import tick_weather_on_time_change, _WEATHER_CHANGE_INTERVAL, _WEATHER_CHANGE_PROB

    print(f"[参数] 触发间隔={_WEATHER_CHANGE_INTERVAL}, 概率={_WEATHER_CHANGE_PROB}, 种子=42")
    print(f"[初始] {json.load(open(REAL_FILE, encoding='utf-8'))}")
    print("-" * 60)

    changes = []
    for i in range(1, 13):  # 跑12轮时间变更
        before = json.load(open(REAL_FILE, encoding="utf-8"))
        result = tick_weather_on_time_change()
        after = json.load(open(REAL_FILE, encoding="utf-8"))
        tick_after = after.get("_weather_tick")
        w_before = before.get("weather")
        w_after = after.get("weather")
        changed = w_before != w_after
        mark = " ★天气变了" if changed else ""
        print(f"第{i:>2}次调用: tick={tick_after}  weather={w_before}→{w_after}{mark}")
        if changed:
            changes.append((i, w_before, w_after))

    print("-" * 60)
    print(f"[结果] 12轮时间变更共触发天气变更 {len(changes)} 次: {changes}")

    # 理论：12轮 / 3 = 4次抽奖机会，25%概率 → 期望1次；seed42 实际看结果
    assert after.get("_weather_tick", -1) == 0, f"计数器应归零但={after.get('_weather_tick')}"  # 12是3倍数
    print("[断言] 12次后计数器归零: OK")
finally:
    # 还原真实存档
    if backup is not None:
        with open(REAL_FILE, "w", encoding="utf-8") as f:
            f.write(backup)
        print("[清理] 真实 location_time.json 已还原")
