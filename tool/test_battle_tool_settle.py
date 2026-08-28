# -*- coding: utf-8 -*-
"""测试：对战体力结算 tool优先+正则兜底（battle_settle_vitality）
验证：
1. parse_vitality_tool_calls 解析 tool_calls（正常/非法json/其他工具名忽略）
2. settle_battle_round_vitality tool优先（正文矛盾结算行被忽略）
3. 无tool时正则兜底
4. gen_single_battle_round 挂载 BATTLE_VITALITY_TOOL 并返回 (content, tool_calls)
"""
import sys, os, json, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BK = "tool/_vit_tool_backup"
if os.path.exists(BK):
    shutil.rmtree(BK)
os.makedirs(BK)
shutil.copy("data/player.json", BK)
shutil.copy("data/npc_agents.json", BK)

import vitality_system as vs
import battle_system as bs


class FakeFunc:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeTC:
    def __init__(self, name, arguments):
        self.function = FakeFunc(name, arguments)


def check(tag, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} | {tag} {detail}")
    return bool(cond)


try:
    ok = True

    # ===== 1. parse_vitality_tool_calls =====
    tc = FakeTC("battle_settle_vitality", json.dumps({"vitality_change": [
        {"name": "李沉舟", "hp_pct": -5, "mp_pct": -10},
        {"name": "胡一刀", "hp_pct": -8, "mp_pct": 0},
    ]}))
    changes = vs.parse_vitality_tool_calls([tc])
    ok &= check("工具解析：提取2条", len(changes) == 2, str(changes))

    tc_bad = FakeTC("battle_settle_vitality", "{not json")
    tc_other = FakeTC("update_game_state", json.dumps({"reputation_delta": 1}))
    tc_empty = FakeTC("battle_settle_vitality", json.dumps({}))
    ok &= check("非法json/其他工具名/空vitality均忽略",
                vs.parse_vitality_tool_calls([tc_bad, tc_other, tc_empty]) == [])
    ok &= check("None输入返回空", vs.parse_vitality_tool_calls(None) == [])

    # ===== 2. tool优先（正文带矛盾结算行，必须以tool为准） =====
    vs.set_player_vitality({"hp": 100, "mp": 100, "poisoned": False})
    plot_with_regex = "刀光剑影，掌风交错。\n【体力结算】李沉舟：气血-1，内力-1"
    log = bs.settle_battle_round_vitality(
        plot_with_regex, player_name="李沉舟", target_name=None, tool_calls=[tc])
    pv = vs.get_player_vitality()
    ok &= check("tool优先：HP 100→95（正文-1被忽略）", pv["hp"] == 95, f"hp={pv['hp']}")
    ok &= check("tool优先：MP 100→90", pv["mp"] == 90, f"mp={pv['mp']}")
    ok &= check("结算日志非空", bool(log), log)

    # ===== 3. 无tool → 正则兜底 =====
    vs.set_player_vitality({"hp": 95, "mp": 90, "poisoned": False})
    log2 = bs.settle_battle_round_vitality(plot_with_regex, player_name="李沉舟", target_name=None)
    pv2 = vs.get_player_vitality()
    ok &= check("正则兜底：HP 95→94", pv2["hp"] == 94, f"hp={pv2['hp']}")

    # ===== 4. gen_single_battle_round 挂载tool并返回元组 =====
    captured = {}

    def mock_llm(sys_p, user_p, temp=0.65, **kw):
        captured["sys"] = sys_p
        captured["user"] = user_p
        captured.update(kw)
        return {"content": "一记劈空掌拍出，尘土飞扬。", "tool_calls": [tc]}

    p_data = json.dumps({"name": "李沉舟", "overall_martial_level": "略有小成",
                         "martial_skill_list": []}, ensure_ascii=False)
    n_data = json.dumps({"name": "胡一刀", "identity": "镖头", "level": "融会贯通"},
                        ensure_ascii=False)
    content, tcs = bs.gen_single_battle_round(
        llm_func=mock_llm, player_data=p_data, npc_data=n_data, round_num=1,
        player_attack_text="出掌", last_process="", battle_style_desc="切磋",
        scene_info="荒庙", player_name="李沉舟", target_npc_name="胡一刀",
        target_npc_persisted=True,
    )
    ok &= check("gen返回content文本", content == "一记劈空掌拍出，尘土飞扬。", content[:30])
    ok &= check("gen返回tool_calls", tcs is not None and len(tcs) == 1)
    ok &= check("llm挂载tools（battle_settle_vitality）",
                "tools" in captured and captured["tools"][0]["function"]["name"] == "battle_settle_vitality")
    ok &= check("prompt含工具优先说明", "battle_settle_vitality" in captured["sys"])

    # ===== 5. 兼容：llm返回纯字符串（旧格式/流式）不炸 =====
    def mock_llm_str(sys_p, user_p, temp=0.65, **kw):
        return "旧格式纯文本回合。"
    content2, tcs2 = bs.gen_single_battle_round(
        llm_func=mock_llm_str, player_data=p_data, npc_data=n_data, round_num=2,
        player_attack_text="再出掌", last_process="", battle_style_desc="切磋",
    )
    ok &= check("纯字符串返回兼容", content2 == "旧格式纯文本回合。" and tcs2 is None)

    print("\n" + ("✅ 全部通过" if ok else "❌ 存在失败项"))
finally:
    shutil.copy(BK + "/player.json", "data/player.json")
    shutil.copy(BK + "/npc_agents.json", "data/npc_agents.json")
    shutil.rmtree(BK)
    print("[现场已还原]")
    sys.exit(0 if ok else 1)
