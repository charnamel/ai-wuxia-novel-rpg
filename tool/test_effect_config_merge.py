# -*- coding: utf-8 -*-
"""合并 martial_effects.json → effect_config.json 后的回归校验（V5锚点制）
验证：①旧22特效的name/category/desc全量保留 ②dice_system读取正常
③web下拉框逻辑过滤正常 ④状态库id清单不含元信息键 ⑤旧文件已归档
⑥V5去概率化：无dot/_formula/_default_base_rate，absorb.also为effect_id
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# ① 旧文件（归档版）与新配置对比
with open("_archive/old_versions/martial_effects.json", encoding="utf-8") as f:
    old = json.load(f)
with open("data/effect_config.json", encoding="utf-8") as f:
    new = json.load(f)

old_effects = old["effects"]
check("旧22特效id全部存在", set(old_effects) <= set(new), str(set(old_effects) - set(new)))
mismatch = []
for eid, e in old_effects.items():
    ne = new.get(eid, {})
    for k in ("name", "category"):  # desc已按状态库新文案迭代,只校验非空
        if e.get(k) != ne.get(k):
            mismatch.append(f"{eid}.{k}: {e.get(k)!r} != {ne.get(k)!r}")
    if not str(ne.get("desc", "")).strip():
        mismatch.append(f"{eid}.desc为空")
check("name/category逐项一致且desc非空", not mismatch, "; ".join(mismatch))

# V5：_default_base_rate 已彻底移除（全局）
check("_default_base_rate已移除", "_default_base_rate" not in new)
bad_meta = [eid for eid, c in new.items()
            if not str(eid).startswith("_") and (
                "dot" in c or "_formula" in c or "base_rate" in json.dumps(c))]
check("零dot/_formula/base_rate残留", not bad_meta, str(bad_meta))
_abs_also = new.get("absorb", {}).get("martial_trigger", {}).get("also", {})
check("absorb.also.effect_id=dissolve", _abs_also.get("effect_id") == "dissolve",
      str(_abs_also))

# ② dice_system 读取
import dice_system as ds
meta = ds._load_effect_meta()
check("dice读effects共22条", len(meta.get("effects", {})) == 22, str(len(meta.get("effects", {}))))
check("dice无_default_base_rate", "_default_base_rate" not in meta)
check("poison元数据可查", meta["effects"]["poison"]["category"] == "attack")
check("_开头键被过滤", all(not k.startswith("_") for k in meta["effects"]))
check("内部状态已删(absorb_drain)", "absorb_drain" not in meta["effects"])
check("内部状态已删(poison_huagong)", "poison_huagong" not in meta["effects"])
ok_reload = ds.reload_effect_meta()
check("reload_effect_meta成功", ok_reload)

# ③ web下拉框逻辑（模拟web_server.py）
cat_order = ["attack", "internal", "lightfoot", "special"]
effects_dict = meta.get("effects", {})
effects_list = []
for cat in cat_order:
    for eid, einfo in effects_dict.items():
        if einfo.get("category") == cat:
            effects_list.append(eid)
check("下拉框恰22项(22特效全带category)", len(effects_list) == 22, str(len(effects_list)))

# ④ 状态库id清单（模拟main.py/battle_system注入）
import vitality_system as vs
cfg = vs._load_effect_config()
ids = [eid for eid, c in cfg.items() if c.get("visible_to_ai", True)]
check("状态库22条(元信息键被过滤)", len(cfg) == 22, str(len(cfg)))
check("清单无_default_base_rate", "_default_base_rate" not in ids and "_version" not in ids)
check("martial_trigger保留", cfg["poison"].get("martial_trigger", {}).get("target") == "opponent")
check("absorb双目标保留(挂词条)",
      cfg["absorb"].get("martial_trigger", {}).get("also", {}).get("effect_id") == "dissolve")

# ⑤ mtime热重载（手改json保存后无需重启，下一轮自动生效）
import time
import shutil
_bak_cfg = "tool/_bak_effect_cfg.json"
shutil.copy2("data/effect_config.json", _bak_cfg)
try:
    _tmp = dict(new)
    _tmp["test_hotreload"] = {"type": "debuff", "name": "热重载测试", "desc": "临时",
                              "default_rounds": 2, "max_stacks": 1,
                              "visible_to_ai": True}
    time.sleep(0.05)
    with open("data/effect_config.json", "w", encoding="utf-8") as f:
        json.dump(_tmp, f, ensure_ascii=False)
    time.sleep(0.05)
    cfg2 = vs._load_effect_config()
    check("mtime热重载生效(新增状态可见)", "test_hotreload" in cfg2)
    meta2 = ds._load_effect_meta()
    check("dice侧mtime热重载生效", "test_hotreload" in meta2["effects"])
finally:
    shutil.copy2(_bak_cfg, "data/effect_config.json")
    time.sleep(0.05)
    vs.reload_effect_config()
    ds.reload_effect_meta()
check("恢复后临时状态消失", "test_hotreload" not in vs._load_effect_config())

# ⑥ 归档位置
check("旧文件已归档", os.path.exists("_archive/old_versions/martial_effects.json"))
check("data下旧文件已移除", not os.path.exists("data/martial_effects.json"))

print(f"\n========================================\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
