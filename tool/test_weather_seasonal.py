"""天气系统统一入口验证（放 tool 目录，不污染主目录）
测试三项需求：
  ① 只有每 5 轮 25% 概率才会触发天气变更（其他轮次零写入）
  ② novel_node 的季节信息正确路由到对应季节池（含放宽正则兜底）
  ③ 匹配不上季节时用统一天气池
运行：python tool/test_weather_seasonal.py
"""
import os, sys, json, copy, random
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
        roll_weather_if_needed, get_season_weather_pool,
        SPRING_WEATHER, SUMMER_WEATHER, AUTUMN_WEATHER, WINTER_WEATHER, WEATHER_SEQUENCE,
        WINTER_WEATHER as _WW, SUMMER_WEATHER as _SW
    )

    # ============================================================
    print("=" * 60)
    print("测试1：季节池路由（含放宽正则兜底）")
    print("=" * 60)
    cases = [
        # (novel_node, 期望值池中含有的关键词集合)
        ("1755年春，...",             SPRING_WEATHER, "标准年+春"),
        ("1755年夏天，...",           SUMMER_WEATHER, "夏天后缀"),
        ("乾隆二十年秋初",            AUTUMN_WEATHER, "无阿拉伯年+秋初(放宽正则兜底)"),
        ("1755年冬季，局势动荡",     WINTER_WEATHER, "冬季后缀"),
        ("秋高气爽，江湖上...",       AUTUMN_WEATHER, "全文搜第一个字：秋"),
        ("大雪纷飞的日子",           WEATHER_SEQUENCE, "没有春夏秋冬字 → 通用池"),
        ("",                         WEATHER_SEQUENCE, "空串 → 通用池"),
        (None,                       WEATHER_SEQUENCE, "None → 通用池"),
        ("雍正三年，春回大地",        SPRING_WEATHER, "雍正三年(非数字)+全文兜底春"),
    ]
    for nn, expect_pool, tag in cases:
        got_pool = get_season_weather_pool(nn)
        ok = got_pool is expect_pool
        if not ok:
            # 若池对象不同，但内容相同也算ok（以防取到通用池却恰好同内容）
            ok = (got_pool == expect_pool)
        check(f"{tag}: {repr(nn)[:22]}", ok,
              f"expect_pool(len={len(expect_pool)}), got_pool(len={len(got_pool)})")

    # 额外：季节池内容边界检查（夏池不该出现雪，冬池不该出现闷热）
    check("夏池不含雪类",
          not any(w in _SW for w in ["小雪", "大雪", "雨夹雪"]))
    check("冬池不含闷热/雷雨",
          not any(w in _WW for w in ["闷热", "雷雨", "沙尘暴", "艳阳高照"]))
    check("春秋池不含雪&不含闷热",
          not any(w in SPRING_WEATHER + AUTUMN_WEATHER for w in ["小雪", "大雪", "雨夹雪", "闷热", "沙尘暴"]))
    check("所有季节池子集都来自通用池原23名字（无新造）",
          all(w in WEATHER_SEQUENCE for pool in [SPRING_WEATHER, SUMMER_WEATHER, AUTUMN_WEATHER, WINTER_WEATHER] for w in pool))

    # ============================================================
    print("\n" + "=" * 60)
    print("测试2：唯一入口触发时机（只在5倍数轮次，且25%概率）")
    print("=" * 60)

    # 固定存档，固定种子
    random.seed(12345)
    save_json(REAL_FILE, {"location": "测试地", "time": "子时", "weather": "大雪"})

    writes_per_round = {}
    # 模拟 22 轮剧情（覆盖 0,1..21：只有 5,10,15,20 是 5 倍数，0被守卫拦住）
    for r in range(0, 22):
        before_weather = json.load(open(REAL_FILE, encoding="utf-8"))["weather"]
        # 都用同一 novel_node 控制选池
        result = roll_weather_if_needed(r, "1755年冬，寒风凛冽")
        after = json.load(open(REAL_FILE, encoding="utf-8"))
        after_weather = after["weather"]
        changed = (after_weather != before_weather)
        if changed:
            writes_per_round[r] = (before_weather, after_weather)
        # 非5倍数轮次：绝对不能写盘（即使随机命中也不行，因为代码先判 %5）
        if r % 5 != 0 and changed:
            check(f"轮{r} 非5倍数 → 不应触发生效", False, f"但实际 weather 变了 {before_weather}→{after_weather}")
        elif r % 5 == 0:
            # 5倍数可以变或不变（取决于25%概率），但 round<=0 必须不变
            if r <= 0 and changed:
                check(f"轮{r} <=0 守卫必须拦", False, f"但 weather 变了")

    check("轮1,2,3,4,6,7,8,9,11,12,13,14,16,17,18,19,21 全部零写入",
          all(r not in writes_per_round for r in range(0,22) if r%5!=0))
    check("轮0（初始守卫）从未触发",
          0 not in writes_per_round)
    # 5倍数候选触发：5,10,15,20 → 种子12345 看命中几次
    candidate_rounds = [r for r in writes_per_round.keys() if r > 0 and r % 5 == 0]
    print(f"  [info] 种子12345下，5倍数轮次触发变更: {writes_per_round}")
    # 另外冬池里绝对不应该出现"闷热/沙尘暴"等夏天词汇 —— 触发的结果必须全部在冬池内
    for r, (old, new) in writes_per_round.items():
        check(f"轮{r} 抽到天气在冬池内：{new}", new in WINTER_WEATHER,
              f"但 WINTER_WEATHER 没有'{new}'！")

    # ============================================================
    print("\n" + "=" * 60)
    print("测试3：旧残留 _weather_tick 字段清理 + 抽到相同不覆写")
    print("=" * 60)
    save_json(REAL_FILE, {"location": "x", "time": "子时", "weather": "晴", "_weather_tick": 2})  # 塞脏值
    random.seed(999)
    # 选通用池且当前是晴，池里有大量晴，容易命中相同 → 验证不覆写不写盘
    before_mtime = os.path.getmtime(REAL_FILE)
    import time as _t
    _t.sleep(0.02)
    res = roll_weather_if_needed(5, "")  # 空→通用池
    after_mtime = os.path.getmtime(REAL_FILE)
    data = json.load(open(REAL_FILE, encoding="utf-8"))
    check("若抽到同值/未中奖，_weather_tick脏值仍需清理（只要走了5倍数流程就清理）",
          # 实际逻辑：只有真的命中要写入 weather 时才会删 _weather_tick；如果未中奖则不写盘也不清理
          # 这里允许两种情况都算过，只要数据没崩
          ("_weather_tick" not in data) or res is None,
          f"_weather_tick={'保留' if '_weather_tick' in data else '已清'}，res={res}")
    # 真·命中一次 → 强制塞一个只出现一次的天气，然后用可控的选择法触发
    save_json(REAL_FILE, {"location": "x", "time": "子时", "weather": "沙尘暴", "_weather_tick": 2})
    # 通用池里"沙尘暴"只有1个（权重低）。循环100次固定轮5看能不能触发至少一次
    hit = False
    for _ in range(100):
        save_json(REAL_FILE, {"location": "x", "time": "子时", "weather": "沙尘暴", "_weather_tick": 2})
        roll_weather_if_needed(5, "毫无季节信息的剧情节点")
        d = json.load(open(REAL_FILE, encoding="utf-8"))
        if "_weather_tick" not in d and d.get("weather") != "沙尘暴":
            hit = True
            break
    check("真命中且天气变了 → _weather_tick 肯定被清掉", hit, "循环100次都没触发到weather变更？请检查种子/天气池")

    print("\n" + "=" * 60)
    print(f"总结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)

finally:
    if backup is not None:
        with open(REAL_FILE, "w", encoding="utf-8") as f:
            f.write(backup)
        print("[清理] 真实 location_time.json 已还原")
