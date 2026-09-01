"""sanitize_desc 展示层守门验证（放 tool 目录，不污染主目录）
测试：
  1) desc 与 HP 档位矛盾 → 降级为档位默认词
  2) 合法的 AI 精细描述 → 原样保留
  3) 空 desc + 非健康态 → 返回默认词；空 desc + 健康态 → 空串
  4) poisoned 正交状态处理
  5) 存档不被修改（只改返回值）
  6) 异常输入不崩
运行：python tool/test_sanitize_desc.py
"""
import os, sys, copy, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    from vitality_system import sanitize_desc

    def mk(hp, desc, poisoned=False, mp=100):
        return {"name": "测试", "vitality": {"hp": hp, "mp": mp, "poisoned": poisoned},
                "body_status": "normal", "body_status_desc": desc}

    print("=" * 60)
    print("测试1：矛盾 desc 降级（HP已回但desc还是旧伤）")
    print("=" * 60)
    cases = [
        # (hp, desc, expect)
        (95, "重伤卧床，呕血不止",     "健康"),   # HP95健康 但desc写重伤
        (95, "伤势痊愈，恢复如初",     "伤势痊愈，恢复如初"),  # 一致 → 保留
        (50, "已故，被一剑穿心",       "轻伤"),   # HP50轻伤 desc写已故 → 降级
        (50, "轻伤，左臂擦伤",         "轻伤，左臂擦伤"),      # 一致 → 保留
        (20, "伤势痊愈活蹦乱跳",       "重伤"),   # HP20重伤 desc写痊愈 → 降级
        (0,  "只是有点累",             "只是有点累"),          # 濒死但desc无矛盾词 → 保留
        (-1, "伤势痊愈，谈笑自若",     "已故"),   # 已故 desc写痊愈 → 降级
    ]
    for hp, desc, exp in cases:
        got = sanitize_desc(mk(hp, desc))
        check(f"HP={hp:>3} desc={desc!r} → {got!r}", got == exp, f"expect={exp!r} got={got!r}")

    print("\n" + "=" * 60)
    print("测试2：合法 AI 精细描述保留（无矛盾词）")
    print("=" * 60)
    keep_cases = [
        (95, "精神饱满，红光满面"),
        (50, "左臂被砍伤，白布缠裹"),
        (20, "肋骨断裂，气息紊乱"),
        (0,  "倒在血泊中，出气多进气少"),
        (-1, "被黑衣人一剑封喉，当场毙命"),
    ]
    for hp, desc in keep_cases:
        got = sanitize_desc(mk(hp, desc))
        check(f"HP={hp:>3} 保留 {desc!r}", got == desc, f"got={got!r}")

    print("\n" + "=" * 60)
    print("测试3：空 desc 兜底")
    print("=" * 60)
    empty_cases = [
        (95, "",  ""),      # 健康 + 空 → 空
        (50, "",  "轻伤"),  # 轻伤 + 空 → 默认词
        (20, "",  "重伤"),
        (0,  "",  "濒死"),
        (-1, "",  "已故"),
        (95, None, ""),     # None desc
    ]
    for hp, desc, exp in empty_cases:
        got = sanitize_desc(mk(hp, desc))
        check(f"HP={hp:>3} desc={desc!r} → {got!r}", got == exp, f"expect={exp!r} got={got!r}")

    print("\n" + "=" * 60)
    print("测试4：poisoned 正交状态")
    print("=" * 60)
    # HP 95 但 poisoned=True → status 应按 poisoned 处理
    got = sanitize_desc(mk(95, "中毒，嘴唇发紫", poisoned=True))
    check("HP95+poisoned+「中毒，嘴唇发紫」→ 保留", got == "中毒，嘴唇发紫", f"got={got!r}")
    got = sanitize_desc(mk(95, "余毒散尽，健步如飞", poisoned=True))
    check("HP95+poisoned+「余毒散尽」→ 降级'中毒'", got == "中毒", f"got={got!r}")
    got = sanitize_desc(mk(95, "", poisoned=True))
    check("HP95+poisoned+空desc → '中毒'", got == "中毒", f"got={got!r}")

    print("\n" + "=" * 60)
    print("测试5：存档不被修改（只改返回值）")
    print("=" * 60)
    npc = mk(95, "重伤卧床，呕血不止")
    snapshot = copy.deepcopy(npc)
    _ = sanitize_desc(npc)
    check("调用后 npc 对象完全未被修改", npc == snapshot,
          f"npc被改了: {json.dumps(npc, ensure_ascii=False)}")

    print("\n" + "=" * 60)
    print("测试6：异常输入不崩")
    print("=" * 60)
    weird_cases = [
        {},                       # 空dict
        {"body_status_desc": "重伤"},   # 无vitality
        {"vitality": None, "body_status_desc": "重伤"},
        {"vitality": {"hp": "abc"}, "body_status_desc": "重伤"},  # hp非数字
        None,                     # None 输入
    ]
    for w in weird_cases:
        try:
            got = sanitize_desc(w)
            check(f"输入 {type(w).__name__}:{str(w)[:30]} 不崩 → {got!r}", isinstance(got, str))
        except Exception as e:
            check(f"输入 {type(w).__name__}:{str(w)[:30]} 不崩", False, f"抛异常: {e}")

    print("\n" + "=" * 60)
    print(f"总结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
finally:
    pass
