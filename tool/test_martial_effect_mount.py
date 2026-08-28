# -*- coding: utf-8 -*-
"""
武功特效程序触发挂状态（主动触发 > AI调tool）全链路测试（V5锚点制）
覆盖：
1. mount_martial_effect_triggers：triggered=True且带martial_trigger → 挂载
2. 未触发/无martial_trigger的特效 → 不挂载
3. purify解毒：remove_prefix清除毒类条目
4. 优先级：system挂载后，AI路径重复add被忽略；system自身可刷新
5. 挂载日志注入constraint_text（resolve_check_v4链路）
6. opponent_name为None时不挂（无目标不出错）
7. dot已移除：tick纯播报（HP/MP零变化）
8. absorb纯挂词条：自己+also.effect_id双目标挂载，零数值结算
"""
import os
import sys
import json
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


BAK = os.path.join("tool", "_bak_martial_eff_test")
os.makedirs(BAK, exist_ok=True)
for f in ("data/player.json", "data/npc_agents.json"):
    if os.path.exists(f):
        shutil.copy2(f, os.path.join(BAK, os.path.basename(f)))


def restore():
    for f in ("data/player.json", "data/npc_agents.json"):
        src = os.path.join(BAK, os.path.basename(f))
        if os.path.exists(src):
            shutil.copy2(src, f)


import vitality_system as vs

try:
    PLAYER = "测试大侠"
    player_data = {"name": PLAYER, "year": 1730,
                   "vitality": {"hp": 100, "mp": 100, "poisoned": False}}
    npc_data = {"npc_list": [
        {"name": "胡一刀", "identity": "镖头", "body_status": "normal",
         "vitality": {"hp": 100, "mp": 100, "poisoned": False}},
    ]}
    with open("data/player.json", "w", encoding="utf-8") as f:
        json.dump(player_data, f, ensure_ascii=False)
    with open("data/npc_agents.json", "w", encoding="utf-8") as f:
        json.dump(npc_data, f, ensure_ascii=False)
    vs._TEMP_EFFECTS.clear()
    vs.reload_effect_config()

    print("===== 1. mount_martial_effect_triggers 基础挂载 =====")
    results = [
        {"skill_name": "化骨绵掌", "effect_type": "poison", "effect_name": "剧毒",
         "triggered": True},
        {"skill_name": "震山掌", "effect_type": "shock", "effect_name": "震慑",
         "triggered": True},  # 22特效全挂载：shock挂1轮
        {"skill_name": "寒冰掌", "effect_type": "cold_poison", "effect_name": "寒毒",
         "triggered": False},  # 未触发 → 不挂
    ]
    log = vs.mount_martial_effect_triggers(results, player_name=PLAYER, opponent_name="胡一刀")
    check("剧毒挂载日志", "剧毒" in log and "胡一刀" in log, log)
    check("震慑也挂载(22特效全挂)", "震慑" in log, log)
    check("未触发特效不挂载", "寒毒" not in log)
    effs, track = vs._get_effects_raw("胡一刀", PLAYER)
    check("胡一刀身上剧毒+震慑共2条", len(effs) == 2 and {e["id"] for e in effs} == {"poison", "shock"}, str(effs))
    check("来源标记为system", all(e.get("source") == "system" for e in effs))
    check("剧毒默认5轮", [e for e in effs if e["id"] == "poison"][0].get("remain_rounds") == 5)
    check("震慑仅1轮(当轮)", [e for e in effs if e["id"] == "shock"][0].get("remain_rounds") == 1)

    print("===== 2. 无对手名不出错 =====")
    log2 = vs.mount_martial_effect_triggers(results, player_name=PLAYER, opponent_name=None)
    check("opponent为None时opponent类不挂", "剧毒" not in log2)

    print("===== 3. 优先级：system挂载 > AI调tool =====")
    # AI路径重复add（apply_effect_updates → apply_effect 默认 system=False）
    ai_log = vs.apply_effect_updates(
        [{"op": "add", "target": "胡一刀", "effect_id": "poison", "rounds": 9}],
        player_name=PLAYER,
    )
    check("AI重复add被忽略", ai_log == "", ai_log)
    effs, _ = vs._get_effects_raw("胡一刀", PLAYER)
    check("回合数未被AI刷新（仍5）", effs[0].get("remain_rounds") == 5)

    # system自身可刷新（同特效再触发）
    sys_log = vs.mount_martial_effect_triggers(results, player_name=PLAYER, opponent_name="胡一刀")
    check("system重复触发正常刷新", "剧毒" in sys_log)

    # AI可上非system的普通状态（不受影响）
    ai_log2 = vs.apply_effect_updates(
        [{"op": "add", "target": "胡一刀", "effect_id": "fire_poison"}],
        player_name=PLAYER,
    )
    check("AI仍可上普通状态", "火毒" in ai_log2)

    # AI remove仍可解除system状态（解毒剧情）
    ai_rm = vs.apply_effect_updates(
        [{"op": "remove", "target": "胡一刀", "effect_id": "poison"}],
        player_name=PLAYER,
    )
    check("AI remove可解除system状态", "已解除" in ai_rm)

    print("===== 4. purify解毒（remove_prefix） =====")
    vs.mount_martial_effect_triggers(results, player_name=PLAYER, opponent_name="胡一刀")
    purify_results = [
        {"skill_name": "解毒真气", "effect_type": "purify", "effect_name": "解毒",
         "triggered": True},
    ]
    # purify target=self → 作用于玩家；先给玩家上毒
    vs.apply_effect(PLAYER, "poison", player_name=PLAYER)
    p_log = vs.mount_martial_effect_triggers(purify_results, player_name=PLAYER, opponent_name="胡一刀")
    check("purify驱散玩家毒类状态", "驱散" in p_log and PLAYER in p_log, p_log)
    effs_p, _ = vs._get_effects_raw(PLAYER, PLAYER)
    ids = [e["id"] for e in effs_p]
    check("玩家毒类全清（poison前缀匹配）", "poison" not in ids, str(ids))

    print("===== 5. dice_system 接线验证 =====")
    import dice_system as ds
    import inspect
    sig = inspect.signature(ds.resolve_check_v4)
    check("resolve_check_v4有effect_opponent_name参数", "effect_opponent_name" in sig.parameters)
    src = inspect.getsource(ds.resolve_check_v4)
    check("Step 6.6挂载调用存在", "mount_martial_effect_triggers" in src)
    check("挂载日志注入constraint_text", "系统已挂载状态词条" in src)
    check("Step 6.7 NPC反手招接线存在", "mount_npc_effect_triggers" in src
          and "compute_npc_effect_trigger" in src, "")
    # 调用方接线
    with open("main.py", encoding="utf-8") as f:
        _m = f.read()
    check("main.py传effect_opponent_name", "effect_opponent_name=_effect_opponent" in _m)
    with open("battle_system.py", encoding="utf-8") as f:
        _b = f.read()
    check("battle_system传对手名", "effect_opponent_name=target_npc.get" in _b)
    with open("web_server.py", encoding="utf-8") as f:
        _w = f.read()
    check("web battle传target_name", "effect_opponent_name=WEB_BATTLE_STATE.get" in _w)
    check("web daily传匹配对手", "effect_opponent_name=_eff_opp" in _w)

    print("===== 6. dot已移除：tick纯播报 =====")
    # 清掉残留火毒，只留剧毒
    vs.remove_effect("胡一刀", "fire_poison", player_name=PLAYER)
    check("配置无dot字段", "dot" not in vs._load_effect_config()["poison"], "")
    vit_b = vs.get_npc_vitality("胡一刀")
    tick_log = vs.tick_effects("胡一刀", player_name=PLAYER, scene_npc_names=["胡一刀"])
    vit_a = vs.get_npc_vitality("胡一刀")
    check("tick不掉血（纯播报制）", vit_a["hp"] == vit_b["hp"],
          f"{vit_b['hp']}→{vit_a['hp']}")
    check("tick有发作播报", "剧毒" in str(tick_log), str(tick_log))

    print("===== 7. absorb纯挂词条（双目标，零数值结算） =====")
    absorb_results = [
        {"skill_name": "吸星大法", "effect_type": "absorb", "effect_name": "吸纳",
         "triggered": True},
    ]
    _abs = vs._load_effect_config()["absorb"]
    _also_id = str(_abs.get("martial_trigger", {}).get("also", {}).get("effect_id", ""))
    check("absorb.also.effect_id=dissolve", _also_id == "dissolve", _also_id)
    vit_o_b = vs.get_npc_vitality("胡一刀")
    vit_p_b = vs.get_player_vitality()
    a_log = vs.mount_martial_effect_triggers(absorb_results, player_name=PLAYER, opponent_name="胡一刀")
    check("absorb自己挂词条", "吸纳" in a_log and PLAYER in a_log, a_log)
    vit_o_a = vs.get_npc_vitality("胡一刀")
    vit_p_a = vs.get_player_vitality()
    check("对手HP/MP零变化（零数值结算）",
          vit_o_a["hp"] == vit_o_b["hp"] and vit_o_a["mp"] == vit_o_b["mp"],
          f"{vit_o_b}→{vit_o_a}")
    effs_pl, _ = vs._get_effects_raw(PLAYER, PLAYER)
    effs_oa, _ = vs._get_effects_raw("胡一刀", PLAYER)
    check("自己挂吸纳词条", "absorb" in [e["id"] for e in effs_pl], str(effs_pl))
    check("对手同步挂散功词条", "dissolve" in [e["id"] for e in effs_oa],
          str([e["id"] for e in effs_oa]))
    # 轮末tick同样零结算
    vit_p_b2 = vs.get_player_vitality()
    vs.tick_effects(PLAYER, player_name=PLAYER, scene_npc_names=[])
    vit_p_a2 = vs.get_player_vitality()
    check("自己MP轮末零变化", vit_p_a2["mp"] == vit_p_b2["mp"],
          f"{vit_p_b2['mp']}→{vit_p_a2['mp']}")

finally:
    restore()
    try:
        vs._TEMP_EFFECTS.clear()
        vs._TEMP_VITALITY.clear()
    except Exception:
        pass
    print(f"\n{'='*40}\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
