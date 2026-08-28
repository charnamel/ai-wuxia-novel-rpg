# -*- coding: utf-8 -*-
"""绝招触发扩档专项断言：
玩家侧 1/2档 → triggered=True + anchor=grade12 + ⚡特技叙述
玩家侧 3-8档 → triggered=False + anchor=ai
NPC侧   7/8档 → 恰1条硬挂 grade78
NPC侧   1-6档 → 空列表"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} → {detail}")


def main():
    import dice_system as ds

    class _P:
        pass

    p = _P()

    print("===== 1. 玩家侧 compute_effect_trigger =====")
    # 从武功书找一条配了effect的武功
    skill_with_effect = None
    try:
        import json
        book_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "data", "martial_arts_bonus.json")
        with open(book_path, encoding="utf-8-sig") as f:
            arts = json.load(f).get("martial_arts", {})
        for k, v in arts.items():
            if isinstance(v, dict) and v.get("effect"):
                skill_with_effect = k
                break
    except Exception as e:
        print(f"  (读martial_arts_bonus.json异常: {e})")

    if skill_with_effect:
        print(f"  (测试武功: {skill_with_effect})")
        for g in range(1, 9):
            r = ds.compute_effect_trigger(skill_with_effect, p, None, g)
            if g in (1, 2):
                check(f"{g}档triggered=True", r and r["triggered"] is True, str(r))
                check(f"{g}档anchor=grade12", r and r.get("anchor") == "grade12", str(r))
            else:
                check(f"{g}档triggered=False", r and r["triggered"] is False, str(r))
                check(f"{g}档anchor=ai", r and r.get("anchor") == "ai", str(r))
    else:
        print("  [SKIP] 未找到配特效的武功，跳过玩家侧档位断言")

    print("===== 2. NPC侧 compute_npc_effect_trigger =====")
    npc_data = {
        "name": "断言NPC",
        "effect_triggers": {"poison": {"target": "opponent"}, "shield": {"target": "self"}},
    }
    for g in (1, 2, 3, 4, 5, 6):
        r = ds.compute_npc_effect_trigger(npc_data, g)
        check(f"{g}档返回空", r == [], str(r))
    for g in (7, 8):
        r = ds.compute_npc_effect_trigger(npc_data, g)
        check(f"{g}档恰1条", len(r) == 1, str(r))
        check(f"{g}档anchor=grade78", r[0].get("anchor") == "grade78", str(r))
        check(f"{g}档triggered=True", r[0].get("triggered") is True, str(r))

    print(f"\n{'='*50}\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
