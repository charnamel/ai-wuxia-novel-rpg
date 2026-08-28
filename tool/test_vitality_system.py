# -*- coding: utf-8 -*-
# 气血内力系统 V5 单元测试
# 覆盖：正则解析 / 钳制 / 哨兵值 / 恢复命令 / 存档迁移 / 结算管线 / 状态块渲染
# 运行前提：在项目根目录 d:/code/NEW6 下执行
#   python tool/test_vitality_system.py
# 测试会备份 data/npc_agents.json 和 data/player.json，结束后还原。
import os
import sys
import json
import shutil

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)

import vitality_system as vs
from file_utils import load_json, save_json

NPC_FILE = os.path.join(_PROJECT_ROOT, "data", "npc_agents.json")
PLAYER_FILE = os.path.join(_PROJECT_ROOT, "data", "player.json")
BACKUP_DIR = os.path.join(_PROJECT_ROOT, "tool", "_vit_test_backup")

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


def backup():
    if os.path.exists(BACKUP_DIR):
        shutil.rmtree(BACKUP_DIR)
    os.makedirs(BACKUP_DIR)
    for f in [NPC_FILE, PLAYER_FILE]:
        if os.path.exists(f):
            shutil.copy2(f, BACKUP_DIR)


def restore():
    for f in [NPC_FILE, PLAYER_FILE]:
        bf = os.path.join(BACKUP_DIR, os.path.basename(f))
        if os.path.exists(bf):
            shutil.copy2(bf, f)


def make_test_npcs():
    """构造最小NPC数据集：3个测试NPC"""
    return {
        "npc_list": [
            {"name": "测试高人", "identity": "大宗师", "body_status": "normal", "body_status_desc": "",
             "memory_list": [], "martial_skills": [], "initial_favor": 50},
            {"name": "测试小虾", "identity": "路人甲", "body_status": "normal", "body_status_desc": "",
             "memory_list": [], "martial_skills": [], "initial_favor": 50},
            {"name": "测试伤者", "identity": "伤员", "body_status": "heavy_injured", "body_status_desc": "旧伤",
             "memory_list": [], "martial_skills": [], "initial_favor": 50},
        ]
    }


def test_regex():
    print("\n== 1. 正则兜底解析 ==")
    text = "一番激斗。\n【体力结算】测试高人：气血-2，内力-5\n【体力结算】张三：气血+10，内力+0"
    r = vs.parse_vitality_regex(text)
    check("解析两条记录", len(r) == 2, str(r))
    check("负数解析", r[0]["hp_pct"] == -2 and r[0]["mp_pct"] == -5, str(r[0]))
    check("正数解析", r[1]["hp_pct"] == 10 and r[1]["mp_pct"] == 0, str(r[1]))
    r2 = vs.parse_vitality_regex("没有结算标记的正文")
    check("无标记返回空", r2 == [])
    r3 = vs.parse_vitality_regex("【体力结算】坏人：气血-3，内力0")
    check("内力无符号解析", len(r3) == 1 and r3[0]["mp_pct"] == 0, str(r3))
    # 带百分号+全角减号（web实战复现的失配bug）
    r4 = vs.parse_vitality_regex("【体力结算】李三奇李三奇：气血-2%，内力-5%")
    check("带%号解析", r4 == [{"name": "李三奇李三奇", "hp_pct": -2, "mp_pct": -5}], str(r4))
    r5 = vs.parse_vitality_regex("【体力结算】李三奇：气血−2，内力−5")
    check("全角减号解析", r5 == [{"name": "李三奇", "hp_pct": -2, "mp_pct": -5}], str(r5))
    # 续行带%也容忍
    r6 = vs.parse_vitality_regex(
        "【体力结算】李三奇：气血-2，内力-5\n十几名漕帮人：气血-4%，内力-1%")
    check("续行带%解析", len(r6) == 2 and r6[1]["hp_pct"] == -4, str(r6))


def test_clamp_and_sentinel():
    print("\n== 2. 钳制与哨兵值 ==")
    hp, mp, ev = vs.apply_delta(100, 100, -999, -999)
    check("巨量伤害被钳到-40", hp == 60 and mp == 60, f"{hp},{mp}")
    hp, mp, ev = vs.apply_delta(50, 50, 999, 999)
    check("巨量恢复被钳到+40（50→90）", hp == 90 and mp == 90, f"{hp},{mp}")
    hp, mp, ev = vs.apply_delta(100, 100, 999, 999)
    check("满值恢复封顶100", hp == 100 and mp == 100, f"{hp},{mp}")
    # 降到0以下→濒死锁血
    hp, mp, ev = vs.apply_delta(10, 50, -30, 0)
    check("HP归零→濒死锁血", hp == 0 and "濒死" in ev, f"{hp},{ev}")
    # 濒死恢复限制15
    hp, mp, ev = vs.apply_delta(0, 50, 40, 0)
    check("濒死单轮最多回复到15", hp == 15, str(hp))
    # 已故不可变
    hp, mp, ev = vs.apply_delta(-1, 50, 40, 40)
    check("已故角色变化被忽略", hp == -1 and mp == 50 and ev, f"{hp},{mp}")
    # 境界差异示例：低打高-1~-3，高打低-6~-12
    hp, _, _ = vs.apply_delta(100, 100, -2, 0)
    check("低打高数值(-2)落地", hp == 98)
    hp, _, _ = vs.apply_delta(100, 100, -10, 0)
    check("高打低数值(-10)落地", hp == 90)


def test_hp_status_mapping():
    print("\n== 3. HP→body_status 映射 ==")
    check("HP=-1→deceased", vs.hp_to_status(-1) == "deceased")
    check("HP=0→dying", vs.hp_to_status(0) == "dying")
    check("HP=25→heavy_injured", vs.hp_to_status(25) == "heavy_injured")
    check("HP=50→light_injured", vs.hp_to_status(50) == "light_injured")
    check("HP=85→normal", vs.hp_to_status(85) == "normal")


def test_settlement():
    print("\n== 4. 结算管线（玩家+落盘NPC+临时NPC） ==")
    save_json(NPC_FILE, make_test_npcs())
    save_json(PLAYER_FILE, {"name": "测试主角", "vitality": {"hp": 100, "mp": 100, "poisoned": False}})

    changes = [
        {"name": "测试主角", "hp_pct": -10, "mp_pct": -4},   # 玩家：高人打我一掌
        {"name": "测试高人", "hp_pct": -2, "mp_pct": -1},    # 我打高人
        {"name": "测试小虾", "hp_pct": -8, "mp_pct": -3},    # 顺手打路人
        {"name": "路人乙", "hp_pct": -5, "mp_pct": 0},       # 临时NPC
    ]
    r = vs.settle_vitality(changes, player_name="测试主角", scene_npc_names=["路人乙"])
    check("结算返回4条", len(r) == 4, str(r.keys()))
    p = vs.get_player_vitality()
    check("玩家HP=90/MP=96", p["hp"] == 90 and p["mp"] == 96, str(p))
    v = vs.get_npc_vitality("测试高人")
    check("高人HP=98", v and v["hp"] == 98, str(v))
    v = vs.get_npc_vitality("测试小虾")
    check("小虾HP=92", v and v["hp"] == 92, str(v))
    # HP>70 本就是normal；再打一下让HP跌破70验证状态自动同步
    vs.settle_vitality([{"name": "测试小虾", "hp_pct": -30}], player_name="测试主角", scene_npc_names=[])
    npc_data = load_json(NPC_FILE)
    xia = [n for n in npc_data["npc_list"] if n["name"] == "测试小虾"][0]
    check("HP跌破70后body_status自动变light_injured", xia["body_status"] == "light_injured", xia["body_status"])
    vs.settle_vitality([{"name": "测试小虾", "hp_pct": -40}], player_name="测试主角", scene_npc_names=[])
    npc_data = load_json(NPC_FILE)
    xia = [n for n in npc_data["npc_list"] if n["name"] == "测试小虾"][0]
    check("HP跌破30后body_status自动变heavy_injured", xia["body_status"] == "heavy_injured", xia["body_status"])
    t = vs.get_temp_vitality("路人乙")
    check("临时NPC内存HP=95", t["hp"] == 95, str(t))

    # 吸内力：玩家MP+4 高人MP-4
    r = vs.settle_vitality(
        [{"name": "测试主角", "mp_pct": 4}, {"name": "测试高人", "mp_pct": -4}],
        player_name="测试主角", scene_npc_names=[],
    )
    p = vs.get_player_vitality()
    v = vs.get_npc_vitality("测试高人")
    check("吸内力：玩家MP+4→100", p["mp"] == 100, str(p))
    check("吸内力：高人MP-4→95", v and v["mp"] == 95, str(v))


def test_death_and_restore():
    print("\n== 5. 死亡哨兵与恢复命令 ==")
    # 打死小虾
    vs.settle_vitality(
        [{"name": "测试小虾", "hp_pct": -40}, {"name": "测试小虾", "hp_pct": -40}, {"name": "测试小虾", "hp_pct": -40}],
        player_name="测试主角", scene_npc_names=[],
    )
    v = vs.get_npc_vitality("测试小虾")
    check("三连击后HP=0濒死", v["hp"] == 0, str(v))
    # 正常结算无法再降
    vs.settle_vitality([{"name": "测试小虾", "hp_pct": -10}], player_name="测试主角", scene_npc_names=[])
    v = vs.get_npc_vitality("测试小虾")
    check("濒死后无法继续掉血", v["hp"] == 0, str(v))
    # AI报死亡→哨兵-1
    npc_data = load_json(NPC_FILE)
    xia = [n for n in npc_data["npc_list"] if n["name"] == "测试小虾"][0]
    xia["body_status"] = "deceased"
    xia["body_status_desc"] = "伤重不治"
    xia["vitality"]["hp"] = -1
    save_json(NPC_FILE, npc_data)
    # 已故后结算应被忽略（气血内力全部冻结）
    r = vs.settle_vitality([{"name": "测试小虾", "hp_pct": -10, "mp_pct": -10}], player_name="测试主角", scene_npc_names=[])
    v = vs.get_npc_vitality("测试小虾")
    check("已故NPC结算被忽略", v["hp"] == -1 and v["mp"] == 97, str(v))
    # 恢复NPC命令：无视哨兵
    ok, msg = vs.restore_npc_full("测试小虾")
    v = vs.get_npc_vitality("测试小虾")
    npc_data = load_json(NPC_FILE)
    xia = [n for n in npc_data["npc_list"] if n["name"] == "测试小虾"][0]
    check("恢复NPC成功", ok)
    check("恢复后HP/MP=100", v["hp"] == 100 and v["mp"] == 100, str(v))
    check("恢复后body_status=normal", xia["body_status"] == "normal", xia["body_status"])
    # 恢复主角
    save_json(PLAYER_FILE, {"name": "测试主角", "vitality": {"hp": 0, "mp": 10, "poisoned": True}})
    ok, msg = vs.restore_player_full()
    p = vs.get_player_vitality()
    check("恢复主角HP/MP=100且解毒", ok and p["hp"] == 100 and p["mp"] == 100 and not p["poisoned"], str(p))
    # 恢复不存在的NPC
    ok, msg = vs.restore_npc_full("不存在的人")
    check("恢复不存在的NPC报错", not ok)


def test_migration():
    print("\n== 6. 旧存档迁移 ==")
    old = {"npc_list": [
        {"name": "旧A", "body_status": "normal", "body_status_desc": "", "memory_list": []},
        {"name": "旧B", "body_status": "light_injured", "body_status_desc": "", "memory_list": []},
        {"name": "旧C", "body_status": "heavy_injured", "body_status_desc": "", "memory_list": []},
        {"name": "旧D", "body_status": "dying", "body_status_desc": "", "memory_list": []},
        {"name": "旧E", "body_status": "deceased", "body_status_desc": "病逝", "memory_list": []},
        {"name": "旧F", "body_status": "poisoned", "body_status_desc": "", "memory_list": []},
    ]}
    save_json(NPC_FILE, old)
    n = vs.migrate_all_npcs()
    data = load_json(NPC_FILE)
    m = {x["name"]: x["vitality"] for x in data["npc_list"]}
    check("迁移6个NPC", n == 6, str(n))
    check("normal→100", m["旧A"]["hp"] == 100)
    check("light_injured→80", m["旧B"]["hp"] == 80)
    check("heavy_injured→40", m["旧C"]["hp"] == 40)
    check("dying→0", m["旧D"]["hp"] == 0)
    check("deceased→-1", m["旧E"]["hp"] == -1)
    check("poisoned→hp100+中毒位", m["旧F"]["hp"] == 100 and m["旧F"]["poisoned"] is True)
    # 二次迁移幂等
    n2 = vs.migrate_all_npcs()
    check("二次迁移幂等", n2 == 0, str(n2))


def test_render():
    print("\n== 7. 状态块渲染 ==")
    save_json(NPC_FILE, make_test_npcs())
    save_json(PLAYER_FILE, {"name": "测试主角", "vitality": {"hp": 66, "mp": 42, "poisoned": False}})
    vs.clear_temp_vitality()
    vs.set_temp_vitality("神秘客", {"hp": 88, "mp": 100, "poisoned": False})
    block = vs.render_vitality_block("测试主角", ["测试高人", "神秘客"])
    check("含主角HP66%", "测试主角：HP 66% / MP 42%" in block, block)
    check("含NPC行", "测试高人：HP 100% / MP 100%" in block, block)
    check("临时角色标注", "神秘客（临时角色）：HP 88%" in block, block)
    # 濒死/已故显示
    vs.set_temp_vitality("神秘客", {"hp": 0, "mp": 100, "poisoned": False})
    block = vs.render_vitality_block("测试主角", ["神秘客"])
    check("濒死显示", "0%（濒死锁血）" in block, block)
    vs.set_temp_vitality("神秘客", {"hp": -1, "mp": 100, "poisoned": False})
    block = vs.render_vitality_block("测试主角", ["神秘客"])
    check("已故显示", "0%（已故）" in block, block)


def test_tool_schema():
    print("\n== 8. 工具schema完整性 ==")
    s = vs.VITALITY_TOOL_SCHEMA
    check("是array类型", s.get("type") == "array")
    check("items有name必填", "name" in s["items"].get("required", []))
    check("描述含境界定性原则", "重创" in s.get("description", ""))


if __name__ == "__main__":
    backup()
    try:
        test_regex()
        test_clamp_and_sentinel()
        test_hp_status_mapping()
        test_settlement()
        test_death_and_restore()
        test_migration()
        test_render()
        test_tool_schema()
    finally:
        restore()
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        vs.clear_temp_vitality()
    print(f"\n{'='*40}\n结果：✅{PASS} 通过 / ❌{FAIL} 失败")
    sys.exit(1 if FAIL else 0)
