# -*- coding: utf-8 -*-
"""测试：NPC档案多门武功的境界识别（应取最高境界）"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from battle_system import calc_realm_index, REALM_ORDER

d = json.load(open('data/npc_agents.json', encoding='utf-8'))
for n in d['npc_list']:
    idx = calc_realm_index(n)
    # 展示每门武功的独立境界
    skills = n.get('martial_skill_list', [])
    skill_info = "、".join(
        f"{s.get('skill_name','?')}={s.get('skill_level','?')}" for s in skills[:5]
    ) or "（无武功列表）"
    print(f"{n['name']}: 识别={REALM_ORDER[idx]} | level字段={n.get('level','')} | 武功: {skill_info}")
