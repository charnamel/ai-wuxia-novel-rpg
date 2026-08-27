# -*- coding: utf-8 -*-
"""临时脚本：列出batch中所有NPC的 name/identity/personality/year，用于人工审查"""
import json

b = json.load(open(r'd:\code\NEW6\tools\batch_npc_avatars.json', encoding='utf-8'))
a = {n['name']: n for n in json.load(open(r'd:\code\NEW6\data\npc_agents.json', encoding='utf-8'))['npc_list']}

with open(r'd:\code\NEW6\tools\_tmp_batch_list.txt', 'w', encoding='utf-8') as f:
    for i, item in enumerate(b):
        name = item['name']
        ag = a.get(name, {})
        f.write(f"{i+1}. {name}\n")
        f.write(f"   identity: {item['identity']}\n")
        f.write(f"   personality: {ag.get('personality', '')}\n")
        f.write(f"   year: {ag.get('year', '')}\n")
        f.write(f"   life: {ag.get('life_experience', '')[:100]}\n\n")

print("done:", len(b))