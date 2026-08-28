# -*- coding: utf-8 -*-
"""独立状态系统（effects）V5全链路测试
覆盖：
1. 状态库加载（effect_config.json v3.0，无dot/无_default_base_rate）
2. apply_effect：上状态/叠层封顶/乱编id忽略/rounds钳制1-5/
   debuff上限3条挤旧/临时NPC轨道
3. tick_effects：纯播报（无数值结算）/回合递减/到期移除/亡故冻结
4. remove_effect：手动解除
5. render_effects_line：词条渲染
6. parse_effect_tool_calls + apply_effect_updates：tool上报链路
7. parse_effect_regex：正则兜底（【状态·op·target·id·N轮】标记行）
8. 旧poisoned布尔读兼容
9. BATTLE_VITALITY_TOOL / EFFECT_UPDATE_SCHEMA 挂载验证
10. render_effects_brief / render_vitality_block 面板注入
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


# ===== 备份真实数据 =====
BAK = os.path.join("tool", "_bak_effects_test")
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
    # ===== 0. 测试数据准备 =====
    PLAYER = "测试大侠"
    player_data = {
        "name": PLAYER, "year": 1730,
        "vitality": {"hp": 100, "mp": 100, "poisoned": False},
    }
    npc_data = {"npc_list": [
        {"name": "胡一刀", "identity": "镖头", "body_status": "normal",
         "vitality": {"hp": 100, "mp": 100, "poisoned": False}},
        {"name": "已故老者", "identity": "前辈", "body_status": "deceased",
         "vitality": {"hp": -1, "mp": 50, "poisoned": False}},
    ]}
    with open("data/player.json", "w", encoding="utf-8") as f:
        json.dump(player_data, f, ensure_ascii=False)
    with open("data/npc_agents.json", "w", encoding="utf-8") as f:
        json.dump(npc_data, f, ensure_ascii=False)

    print("===== 1. 状态库加载（V5零概率） =====")
    cfg = vs._load_effect_config()
    check("状态库含fire_poison", "fire_poison" in cfg)
    check("dot字段已全量移除", all("dot" not in c for c in cfg.values()),
          str([k for k, c in cfg.items() if "dot" in c]))
    check("_default_base_rate已移除", "_default_base_rate" not in cfg)
    check("_formula已移除", "_formula" not in cfg)
    check("fire_poison max_stacks=1", cfg.get("fire_poison", {}).get("max_stacks") == 1)
    FP_ROUNDS = int(cfg.get("fire_poison", {}).get("default_rounds", 3))
    check("absorb.also为挂词条(dissolve)",
          cfg.get("absorb", {}).get("martial_trigger", {}).get("also", {})
          .get("effect_id") == "dissolve")

    print("===== 2. apply_effect =====")
    vs._TEMP_EFFECTS.clear()
    log = vs.apply_effect(PLAYER, "fire_poison", player_name=PLAYER)
    check("玩家上火毒成功", "获得" in log and "火毒" in log, log)
    effs, track = vs._get_effects_raw(PLAYER, PLAYER)
    check("玩家轨道=player", track == "player")
    check(f"条目remain={FP_ROUNDS}（默认回合）", effs and effs[0].get("remain_rounds") == FP_ROUNDS)

    log2 = vs.apply_effect(PLAYER, "fire_poison", stacks=3, player_name=PLAYER)
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    check("叠层封顶max_stacks=1", effs and effs[0].get("stacks") == 1)

    log3 = vs.apply_effect(PLAYER, "乱编的状态", player_name=PLAYER)
    check("乱编id静默忽略", log3 == "")

    # rounds钳制1-5
    vs.apply_effect(PLAYER, "cold_poison", rounds=99, player_name=PLAYER)
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    _cp = [e for e in effs if e["id"] == "cold_poison"]
    check("rounds=99钳制为5", _cp and _cp[0].get("remain_rounds") == 5, str(_cp))
    vs.apply_effect(PLAYER, "cold_poison", rounds=0, player_name=PLAYER)
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    _cp = [e for e in effs if e["id"] == "cold_poison"]
    check("rounds=0钳制为1", _cp and _cp[0].get("remain_rounds") == 1, str(_cp))

    log4 = vs.apply_effect("临时路人", "fire_poison", source=PLAYER, player_name=PLAYER)
    check("临时NPC可上毒（内存缓存）", "临时路人" in log4)
    check("临时NPC轨道=temp", vs._get_effects_raw("临时路人", PLAYER)[1] == "temp")

    log5 = vs.apply_effect("胡一刀", "fire_poison", player_name=PLAYER)
    check("落盘NPC可上毒", "胡一刀" in log5)
    with open("data/npc_agents.json", encoding="utf-8") as f:
        _saved = json.load(f)
    _h = [n for n in _saved["npc_list"] if n["name"] == "胡一刀"][0]
    check("落盘NPC条目已持久化", isinstance(_h.get("effects"), list) and len(_h["effects"]) == 1)

    print("===== 2b. debuff上限3条（挤掉最旧） =====")
    # 玩家当前: fire_poison, cold_poison（均debuff）→ 再上2条触发挤出
    log_a = vs.apply_effect(PLAYER, "poison", player_name=PLAYER)
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    check("第3条debuff正常挂上", len(effs) == 3, str([e["id"] for e in effs]))
    log_b = vs.apply_effect(PLAYER, "weakness", player_name=PLAYER)
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    check("第4条debuff挤掉最旧(fire_poison)",
          len(effs) == 3 and "fire_poison" not in [e["id"] for e in effs]
          and "weakness" in [e["id"] for e in effs], str([e["id"] for e in effs]))
    check("挤出日志提示", "被挤下" in log_b, log_b)

    print("===== 3. tick_effects（V5纯播报） =====")
    vit_before = vs.get_player_vitality()
    t_log = vs.tick_effects(PLAYER, player_name=PLAYER, scene_npc_names=[])
    vit_after = vs.get_player_vitality()
    check("tick不动HP（纯播报）", vit_after["hp"] == vit_before["hp"],
          f"{vit_before['hp']}→{vit_after['hp']}")
    check("tick不动MP（纯播报）", vit_after["mp"] == vit_before["mp"],
          f"{vit_before['mp']}→{vit_after['mp']}")
    check("tick日志含debuff发作播报", "发作" in t_log, t_log)
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    ids_now = [e["id"] for e in effs]
    check("回合已递减", all(e.get("remain_rounds") < 5 for e in effs)
          or "cold_poison" not in ids_now, str(effs))

    # 连续tick到过期
    for _ in range(10):
        vs.tick_effects(PLAYER, player_name=PLAYER, scene_npc_names=[])
    effs, _ = vs._get_effects_raw(PLAYER, PLAYER)
    check("到期自动移除", not effs, f"剩余{len(effs or [])}条")

    # 亡故冻结
    vs.apply_effect("已故老者", "fire_poison", player_name=PLAYER)
    t_dead = vs.tick_effects("已故老者", player_name=PLAYER, scene_npc_names=["已故老者"])
    check("亡故NPC冻结不tick", t_dead == "", t_dead)
    vit_d = vs.get_npc_vitality("已故老者")
    check("亡故者hp保持-1", vit_d and vit_d["hp"] == -1)

    print("===== 4. remove_effect =====")
    vs.apply_effect("胡一刀", "fire_poison", player_name=PLAYER)
    r_log = vs.remove_effect("胡一刀", "fire_poison", player_name=PLAYER)
    check("手动解除成功", "已解除" in r_log, r_log)
    r_log2 = vs.remove_effect("胡一刀", "fire_poison", player_name=PLAYER)
    check("重复解除返回空", r_log2 == "")

    print("===== 5. render_effects_line（DC/剧情AI注入） =====")
    vs.apply_effect("胡一刀", "fire_poison", player_name=PLAYER)
    line = vs.render_effects_line("胡一刀", player_name=PLAYER)
    check("词条含状态名", "火毒" in line, line)
    check("词条含desc", "灼痛" in line, line)
    check("词条含dc_hint", "经脉灼烧" in line, line)
    check("词条含剩余轮数", "剩" in line, line)
    empty = vs.render_effects_line("路人甲乙", player_name=PLAYER)
    check("无状态角色返回空串", empty == "")


    print("===== 6. tool上报链路 =====")

    class _FakeFunc:
        def __init__(self, name, args):
            self.name = name
            self.arguments = json.dumps(args, ensure_ascii=False)

    class _FakeTC:
        def __init__(self, name, args):
            self.function = _FakeFunc(name, args)

    tcs = [_FakeTC("update_game_state", {
        "vitality_change": [{"name": "胡一刀", "hp_pct": -5, "mp_pct": 0}],
        "effect_update": [
            {"op": "add", "target": "胡一刀", "effect_id": "fire_poison", "rounds": 3},
        ],
    })]
    ups = vs.parse_effect_tool_calls(tcs)
    check("parse提取effect_update", len(ups) == 1 and ups[0]["op"] == "add")
    vs.remove_effect("胡一刀", "fire_poison", player_name=PLAYER)
    log = vs.apply_effect_updates(ups, player_name=PLAYER)
    check("apply执行add成功", "获得" in log, log)
    effs, _ = vs._get_effects_raw("胡一刀", PLAYER)
    check("rounds覆盖生效（3轮）", effs and effs[0].get("remain_rounds") == 3)

    # battle tool名也兼容
    tcs2 = [_FakeTC("battle_settle_vitality", {
        "vitality_change": [],
        "effect_update": [{"op": "remove", "target": "胡一刀", "effect_id": "fire_poison"}],
    })]
    ups2 = vs.parse_effect_tool_calls(tcs2)
    check("battle工具名兼容", len(ups2) == 1)
    log2 = vs.apply_effect_updates(ups2, player_name=PLAYER)
    check("apply执行remove成功", "已解除" in log2, log2)

    # 非法条目不阻塞
    log3 = vs.apply_effect_updates([
        {"op": "bad_op", "target": "胡一刀", "effect_id": "fire_poison"},
        {"op": "add", "target": "", "effect_id": "fire_poison"},
        {"op": "add", "target": "胡一刀", "effect_id": "不存在"},
    ], player_name=PLAYER)
    check("非法条目全部跳过", log3 == "")

    print("===== 7. parse_effect_regex正则兜底 =====")
    # 标准格式：op+target+id+轮数
    r1 = vs.parse_effect_regex("……刀光一闪！【状态·add·对手·poison·2轮】对方脸色发青。")
    check("标准add解析", len(r1) == 1 and r1[0] == {
        "op": "add", "target": "opponent", "effect_id": "poison", "rounds": 2}, str(r1))
    # 中文op+self
    r2 = vs.parse_effect_regex("【状态·挂·自己·shield】")
    check("中文挂/自己解析", r2 == [{"op": "add", "target": "self", "effect_id": "shield"}], str(r2))
    # remove
    r3 = vs.parse_effect_regex("运功驱毒！【状态·remove·self·poison】毒解了。")
    check("remove解析", r3 == [{"op": "remove", "target": "self", "effect_id": "poison"}], str(r3))
    # 中文名反查
    r4 = vs.parse_effect_regex("【状态·对手·剧毒·3轮】")
    check("中文名反查poison", r4 == [{"op": "add", "target": "opponent",
                                     "effect_id": "poison", "rounds": 3}], str(r4))
    # 乱编id静默丢弃
    r5 = vs.parse_effect_regex("【状态·add·对手·乱编的状态·3轮】")
    check("乱编id静默丢弃", r5 == [], str(r5))
    # 兜底链路执行：相对标记无映射时静默跳过（不再挂幽灵角色"opponent"）
    log_ghost = vs.apply_effect_updates(r1, player_name=PLAYER)
    check("相对标记无映射静默跳过", log_ghost == "", log_ghost)
    _gh, _ = vs._get_effects_raw("opponent", PLAYER)
    check("无幽灵opponent角色", not _gh, str(_gh))
    # 有映射时正确翻译挂载
    log_r = vs.apply_effect_updates(
        r1, player_name=PLAYER, self_name=PLAYER, opponent_name="胡一刀")
    check("相对标记翻译后挂载", "剧毒" in log_r and "胡一刀" in log_r, log_r)
    # self标记挂玩家自己
    log_s = vs.apply_effect_updates(
        r2, player_name=PLAYER, self_name=PLAYER, opponent_name="胡一刀")
    check("self标记挂玩家", PLAYER in log_s and "护体" in log_s, log_s)
    vs.remove_effect("胡一刀", "poison", player_name=PLAYER)
    vs.remove_effect(PLAYER, "shield", player_name=PLAYER)
    # 空文本
    check("空文本返回空列表", vs.parse_effect_regex("") == [])

    print("===== 8. 旧poisoned读兼容 =====")
    with open("data/player.json", encoding="utf-8") as f:
        _pd = json.load(f)
    _pd["vitality"]["poisoned"] = True
    with open("data/player.json", "w", encoding="utf-8") as f:
        json.dump(_pd, f, ensure_ascii=False)
    line_p = vs.render_effects_line(PLAYER, player_name=PLAYER)
    check("旧poisoned布尔渲染为中毒词条", "中毒" in line_p, line_p)

    print("===== 9. schema挂载验证 =====")
    check("BATTLE_VITALITY_TOOL含effect_update字段",
          "effect_update" in vs.BATTLE_VITALITY_TOOL["function"]["parameters"]["properties"])
    check("EFFECT_UPDATE_SCHEMA必填op/target/effect_id",
          set(vs.EFFECT_UPDATE_SCHEMA["items"]["required"]) == {"op", "target", "effect_id"})
    # main.py的update_game_state挂载检查（文本级）
    with open("main.py", encoding="utf-8") as f:
        _main_txt = f.read()
    check("main.py挂载effect_update", '"effect_update": vit_sys.EFFECT_UPDATE_SCHEMA' in _main_txt)
    check("main.py挂载tick结算", "vit_sys.tick_effects" in _main_txt)
    check("main.py挂载上报解析", "vit_sys.parse_effect_tool_calls" in _main_txt)
    check("main.py正则兜底接线", "parse_effect_regex" in _main_txt)
    # battle_system挂载
    with open("battle_system.py", encoding="utf-8") as f:
        _bs_txt = f.read()
    check("battle_system挂载effects结算函数", "settle_battle_round_effects" in _bs_txt)
    check("battle_system正则兜底接线", "parse_effect_regex" in _bs_txt)
    check("battle_system传round_plot", "round_plot=round_plot" in _bs_txt)
    # web_server挂载
    with open("web_server.py", encoding="utf-8") as f:
        _ws_txt = f.read()
    check("web_server挂载effects结算", "settle_battle_round_effects" in _ws_txt)
    check("web传round_plot", "round_plot=round_plot" in _ws_txt)
    # dice_system注入
    with open("dice_system.py", encoding="utf-8") as f:
        _ds_txt = f.read()
    check("dice_system DC注入render_effects_line", "render_effects_line" in _ds_txt)
    check("dice_system零概率（无final_rate计算）", "final_rate" not in _ds_txt)

    print("===== 10. 面板注入 =====")
    # 重置第8步残留的poisoned布尔
    with open("data/player.json", encoding="utf-8") as f:
        _pd = json.load(f)
    _pd["vitality"]["poisoned"] = False
    with open("data/player.json", "w", encoding="utf-8") as f:
        json.dump(_pd, f, ensure_ascii=False)
    vs.apply_effect(PLAYER, "fire_poison", player_name=PLAYER)
    vs.apply_effect("胡一刀", "fire_poison", player_name=PLAYER)
    block = vs.render_vitality_block(PLAYER, scene_npc_names=["胡一刀"])
    check("面板含状态词条区", "状态词条" in block, block)
    check("面板含双方词条", PLAYER in block and "胡一刀" in block)
    brief = vs.render_effects_brief(PLAYER, scene_npc_names=["胡一刀"])
    check("brief含两行", brief.count("\n") == 1 and "火毒" in brief, brief)
    # 无状态时面板不出现词条区
    vs.remove_effect(PLAYER, "fire_poison", player_name=PLAYER)
    vs.remove_effect("胡一刀", "fire_poison", player_name=PLAYER)
    block2 = vs.render_vitality_block(PLAYER, scene_npc_names=["胡一刀"])
    check("无状态不占行", "状态词条" not in block2)

    print("===== 11. 临时NPC清场 =====")
    vs.apply_effect("临时路人", "fire_poison", player_name=PLAYER)
    vs.clear_temp_effects("临时路人")
    check("指定清除临时状态", vs._get_effects_raw("临时路人", PLAYER)[0] == [])

finally:
    restore()
    # 清理临时缓存
    try:
        vs._TEMP_EFFECTS.clear()
        vs._TEMP_VITALITY.clear()
    except Exception:
        pass
    print(f"\n{'='*40}\n结果：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
