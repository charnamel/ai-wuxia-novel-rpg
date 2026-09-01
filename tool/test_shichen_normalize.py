"""时辰格式规范化验证（放 tool 目录）
测试 A+B 两项：
  1) normalize_shichen() 清洗各种AI乱输出
  2) update_location_time(time=...) 写入端拒写非法值
  3) load_location_time() 读端修复脏存档
运行：python tool/test_shichen_normalize.py
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REAL_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "location_time.json")
backup = None
if os.path.exists(REAL_FILE):
    with open(REAL_FILE, "r", encoding="utf-8") as f:
        backup = f.read()

PASS = 0
FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}  {detail}")

try:
    from file_utils import save_json
    from location_time import (
        TIME_SEQUENCE, VALID_SHICHEN, normalize_shichen,
        update_location_time, load_location_time,
        format_time_with_24h, advance_world_time
    )

    # ============================================================
    print("=" * 60)
    print("测试1：normalize_shichen 清洗AI乱输出（23个用例）")
    print("=" * 60)

    # 12 标准值：原样通过
    for std in TIME_SEQUENCE:
        got = normalize_shichen(std)
        check(f"标准值通过 {std}", got == std, f"got={got!r}")

    # AI乱加后缀：提取核心
    ai_mess_cases = [
        ("辰时（略耗）",        "辰时"),
        ("午时三刻",            "午时"),
        ("丑时初",              "丑时"),
        ("亥时末，月亮偏西",    "亥时"),
        ("  申时  ",            "申时"),   # 空格
        ("子时过后",            "子时"),
        ("卯时,天亮了",         "卯时"),  # 逗号
    ]
    for raw, exp in ai_mess_cases:
        got = normalize_shichen(raw)
        check(f"AI附加清洗 {raw!r}", got == exp, f"got={got!r} expect={exp!r}")

    # 完全非法值 → 返回None
    bad_cases = [
        None, "", "   ", "三天后", "三个月后", "次日清晨", "深夜",
        "黎明", "黄昏", "傍晚", "中午", "12:00", "404", 404, {},
    ]
    for raw in bad_cases:
        got = normalize_shichen(raw)
        check(f"非法清洗为None {raw!r}", got is None, f"got={got!r}")

    # ============================================================
    print("\n" + "=" * 60)
    print("测试2：update_location_time 写入端校验")
    print("=" * 60)

    # 初始化干净存档
    save_json(REAL_FILE, {"location": "X", "time": "卯时", "weather": "晴"})

    # 合法写入
    _, ok = update_location_time(time="辰时")
    data = json.load(open(REAL_FILE, encoding="utf-8"))
    check(f"合法写入'辰时' → accepted={ok} + 实际存储",
          ok is True and data.get("time") == "辰时", f"ok={ok}, data.time={data.get('time')!r}")

    # 可清洗写入（附加文字）
    _, ok = update_location_time(time="午时（略耗，准备吃饭）")
    data = json.load(open(REAL_FILE, encoding="utf-8"))
    check(f"清洗写入'午时（...）' → accepted={ok}+实际'午时'",
          ok is True and data.get("time") == "午时", f"ok={ok}, time={data.get('time')!r}")

    # 完全非法 → 拒写
    save_json(REAL_FILE, {"location": "X", "time": "卯时", "weather": "晴"})  # 先写卯时
    _, ok = update_location_time(time="三天后")
    data = json.load(open(REAL_FILE, encoding="utf-8"))
    check(f"非法'三天后' → accepted=False 且原'卯时'不动",
          ok is False and data.get("time") == "卯时",
          f"ok={ok}, time={data.get('time')!r}")

    # time=None → 跳过不处理（和原来一致）
    before = data.get("time")
    _, ok = update_location_time(time=None)
    data = json.load(open(REAL_FILE, encoding="utf-8"))
    check(f"time=None → 跳过且accepted=False", ok is False and data.get("time") == before)

    # location-only调用不影响time
    _, ok = update_location_time(location="新地点")
    data = json.load(open(REAL_FILE, encoding="utf-8"))
    check(f"location-only调用，time仍为'{before}'",
          data.get("location") == "新地点" and data.get("time") == before)

    # ============================================================
    print("\n" + "=" * 60)
    print("测试3：load_location_time 读端修复脏存档（一次修复即写盘）")
    print("=" * 60)

    dirty_cases = [
        ("辰时（略耗）",         "辰时",   "脏值可提取"),
        ("午时三刻赶到客栈",     "午时",   "含附加文字"),
        ("根本不是时辰",         "卯时",   "无法提取→兜底卯时"),
        (None,                  "卯时",   "time为None→兜底卯时"),
        (123,                   "卯时",   "time非字符串→兜底"),
    ]
    for raw_t, exp_t, tag in dirty_cases:
        # 直接塞脏值到JSON（绕过update_location_time的校验）
        save_json(REAL_FILE, {"location": "脏存档", "time": raw_t, "weather": "晴"})
        # 调用 load_location_time（会修复+写盘）
        data = load_location_time()
        actual_t = data.get("time")
        check(f"[{tag}] raw={raw_t!r} → load后time={actual_t!r}",
              actual_t == exp_t and actual_t in VALID_SHICHEN,
              f"expect={exp_t!r} actual={actual_t!r}")
        # 确认存档也被修复了（下次加载就干净了）
        disk_t = json.load(open(REAL_FILE, encoding="utf-8")).get("time")
        check(f"  → 存档同步修复", disk_t == exp_t, f"disk.time={disk_t!r}")

    # ============================================================
    print("\n" + "=" * 60)
    print("测试4：连锁影响（format_time_with_24h / advance_world_time 不再隐跳子时）")
    print("=" * 60)

    save_json(REAL_FILE, {"location": "X", "time": "辰时（略耗）", "weather": "晴"})
    data = load_location_time()   # 先修复
    # format_time_with_24h 现在肯定能查到24h映射
    display = format_time_with_24h(data["time"])
    check(f"修复后'辰时' → 24h显示正确: {display}",
          "（07:00-09:00）" in display, f"display={display!r}")

    # advance_world_time 不再 ValueError 跳回子时（脏值先被load修复了）
    save_json(REAL_FILE, {"location": "X", "time": "酉时（略耗）", "weather": "晴"})
    load_location_time()   # 修一次
    adv = advance_world_time()
    check(f"修脏后advance：酉时→下一个是戌时（不会跳回子时）",
          adv.get("time") == "戌时", f"adv.time={adv.get('time')!r}")

    print("\n" + "=" * 60)
    print(f"总结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)

finally:
    if backup is not None:
        with open(REAL_FILE, "w", encoding="utf-8") as f:
            f.write(backup)
        print("[清理] 真实 location_time.json 已还原")
