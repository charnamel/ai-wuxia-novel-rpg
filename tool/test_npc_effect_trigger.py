# -*- coding: utf-8 -*-
"""NPC反手招锚点制测试（V5零概率）
覆盖：7/8档硬挂恰1条（target语义self/opponent）、非7/8档返回空、
未配置走directive指令兜底、挂载目标（玩家/NPC自己）、
AI上报优先级（system条目防AI重复add）、失效保障。"""
import json
import shutil
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
    import vitality_system as vs

    PLAYER = "测试玩家NPC特效"
    NPC = "测试NPC特效"

    # 备份玩家/NPC数据
    shutil.copy2("data/player.json", "tool/_bak_player.json")
    shutil.copy2("data/npc_agents.json", "tool/_bak_npc.json")
    try:
        # 玩家归位
        with open("data/player.json", encoding="utf-8") as f:
            pd = json.load(f)
        pd["name"] = PLAYER
        pd["vitality"] = {"hp": 80, "mp": 60, "poisoned": False}
        pd["effects"] = []
        with open("data/player.json", "w", encoding="utf-8") as f:
            json.dump(pd, f, ensure_ascii=False)

        # 构造测试NPC（effect_triggers为V5 dict格式）
        npc_data = {
            "name": NPC,
            "identity": "测试",
            "martial_skills": [{"skill_name": "化骨绵掌", "skill_level": "融会贯通"}],
            "effect_triggers": {
                "poison": {"target": "opponent"},
                "shield": {"target": "self"},
                "weakness": {},
            },
        }
        with open("data/npc_agents.json", encoding="utf-8") as f:
            nd = json.load(f)
        nd["npc_list"] = [n for n in nd.get("npc_list", []) if n.get("name") != NPC]
        nd["npc_list"].append(dict(npc_data, name="测试NPC2"))
        with open("data/npc_agents.json", "w", encoding="utf-8") as f:
            json.dump(nd, f, ensure_ascii=False)

        print("===== 1. 锚点计算 compute_npc_effect_trigger =====")
        print("===== 1b. 2-7档招牌提示 compute_npc_effect_hint =====")
        hint = ds.compute_npc_effect_hint(npc_data)
        check("提示非空", bool(hint), hint)
        check("提示含NPC名", "测试NPC特效" in hint, hint)
        check("提示含状态名", ("剧毒" in hint) and ("虚弱" in hint), hint)
        check("提示含上报指引", "effect_update" in hint, hint)
        check("无配置返回空串", ds.compute_npc_effect_hint({"name": "路人"}) == "")
        check("None返回空串", ds.compute_npc_effect_hint(None) == "")

        # 非7/8档一律空
        for g in (1, 2, 5, 6):
            r = ds.compute_npc_effect_trigger(npc_data, g)
            check(f"{g}档返回空", r == [], str(r))
        # 7/8档硬挂恰1条
        for g in (7, 8):
            rg = ds.compute_npc_effect_trigger(npc_data, g)
            check(f"{g}档恰挂1条", len(rg) == 1, str(len(rg)))
            check(f"{g}档硬挂条带grade78锚点", rg[0].get("anchor") == "grade78", str(rg[0]))
            check(f"{g}档硬挂条triggered=True", rg[0].get("triggered") is True)
            check(f"{g}档target在候选集内", rg[0].get("target") in ("opponent", "self"),
                  str(rg[0].get("target")))
        # 多次取样仍每次恰1条（从3候选中随机）
        for _ in range(20):
            rr = ds.compute_npc_effect_trigger(npc_data, 8)
            if len(rr) != 1:
                check("20次取样均恰1条", False, str(rr))
                break
        else:
            check("20次取样均恰1条", True)

        # 无effect_triggers字段 → directive兜底
        r_no = ds.compute_npc_effect_trigger(
            {"name": "路人甲", "martial_skills": []}, 8)
        check("未配置返回directive兜底",
              len(r_no) == 1 and r_no[0].get("anchor") == "directive"
              and r_no[0].get("npc_name") == "路人甲", str(r_no))
        # 非dict输入 → directive兜底
        r_bad = ds.compute_npc_effect_trigger(None, 8)
        check("None输入走directive", len(r_bad) == 1
              and r_bad[0].get("anchor") == "directive", str(r_bad))
        # 旧int格式条目容错（conf非dict按空处理）
        r_legacy = ds.compute_npc_effect_trigger(
            {"name": "老古董", "effect_triggers": {"poison": 10}}, 8)
        check("旧int格式容错(默认opponent)",
              len(r_legacy) == 1 and r_legacy[0].get("effect_type") == "poison"
              and r_legacy[0].get("target") == "opponent", str(r_legacy))

        print("===== 2. 挂载目标 mount_npc_effect_triggers =====")
        # opponent语义 → 挂给玩家
        vs._TEMP_EFFECTS.clear()
        log = vs.mount_npc_effect_triggers(
            [{"effect_type": "poison", "triggered": True, "target": "opponent"}],
            PLAYER, NPC)
        check("挂载日志含玩家名", PLAYER in log, log)
        effs_p, _ = vs._get_effects_raw(PLAYER, PLAYER)
        check("玩家身上有剧毒", "poison" in [e["id"] for e in effs_p], str(effs_p))
        check("词条为system来源", all(e.get("source") == "system" for e in effs_p),
              str(effs_p))

        print("===== 3. self语义（NPC自增益） =====")
        log2 = vs.mount_npc_effect_triggers(
            [{"effect_type": "shield", "triggered": True, "target": "self"}],
            PLAYER, NPC)
        check("shield挂给NPC自己", NPC in log2 and PLAYER not in log2, log2)
        effs_n, _ = vs._get_effects_raw(NPC, PLAYER)
        check("NPC身上有护体", "shield" in [e["id"] for e in effs_n], str(effs_n))

        print("===== 4. absorb双目标（纯挂词条，零数值结算） =====")
        vit_b = vs.get_player_vitality()
        log3 = vs.mount_npc_effect_triggers(
            [{"effect_type": "absorb", "triggered": True, "target": "self"}],
            PLAYER, NPC)
        vit_a = vs.get_player_vitality()
        check("玩家HP/MP零变化（纯播报制）",
              vit_a["hp"] == vit_b["hp"] and vit_a["mp"] == vit_b["mp"],
              f"{vit_b}→{vit_a}")
        effs_n2, _ = vs._get_effects_raw(NPC, PLAYER)
        ids_n = [e["id"] for e in effs_n2]
        effs_p4, _ = vs._get_effects_raw(PLAYER, PLAYER)
        check("absorb挂NPC自己+also挂玩家散功",
              "absorb" in ids_n and "dissolve" in [e["id"] for e in effs_p4],
              str(ids_n))

        print("===== 5. AI上报优先级（system条目防AI重复add） =====")
        ai_log = vs.apply_effect_updates(
            [{"op": "add", "target": PLAYER, "effect_id": "poison", "rounds": 9}],
            player_name=PLAYER,
        )
        check("AI重复add被忽略", ai_log == "", ai_log)
        ai_rm = vs.apply_effect_updates(
            [{"op": "remove", "target": PLAYER, "effect_id": "poison"}],
            player_name=PLAYER,
        )
        check("AI remove可解除", "解除" in ai_rm, ai_rm)

        print("===== 6. 失效保障 =====")
        check("空结果静默", vs.mount_npc_effect_triggers([], PLAYER, NPC) == "")
        check("无玩家名静默", vs.mount_npc_effect_triggers(
            [{"effect_type": "poison", "triggered": True}], "", NPC) == "")
        check("无NPC名静默", vs.mount_npc_effect_triggers(
            [{"effect_type": "poison", "triggered": True}], PLAYER, "") == "")
        # 库里不存在的id
        log_bad = vs.mount_npc_effect_triggers(
            [{"effect_type": "not_exist_id", "triggered": True}], PLAYER, NPC)
        check("未知id静默", log_bad == "", log_bad)
        # directive兜底条不带triggered → 挂载层静默跳过
        log_dir = vs.mount_npc_effect_triggers(
            [{"anchor": "directive", "npc_name": NPC}], PLAYER, NPC)
        check("directive条不进挂载层", log_dir == "", log_dir)
        # 状态库无martial_trigger的条目（如AI专属状态）
        cfg = vs._load_effect_config()
        no_trig = [k for k, v in cfg.items()
                   if not v.get("martial_trigger") and not k.startswith("_")]
        if no_trig:
            log_nt = vs.mount_npc_effect_triggers(
                [{"effect_type": no_trig[0], "triggered": True}], PLAYER, NPC)
            check(f"无martial_trigger条目({no_trig[0]})静默", log_nt == "", log_nt)

        print("===== 7. 玩家侧不受影响（mount_martial_effect_triggers照常） =====")
        log_p = vs.mount_martial_effect_triggers(
            [{"effect_type": "poison", "triggered": True}],
            player_name=PLAYER, opponent_name=NPC)
        check("玩家侧挂给对手NPC", NPC in log_p, log_p)
        vs.remove_effect(NPC, "poison", player_name=PLAYER)

    finally:
        # 恢复数据
        shutil.copy2("tool/_bak_player.json", "data/player.json")
        shutil.copy2("tool/_bak_npc.json", "data/npc_agents.json")
        for f in ("tool/_bak_player.json", "tool/_bak_npc.json"):
            if os.path.exists(f):
                os.remove(f)

    print(f"\n{'='*50}\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
