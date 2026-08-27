"""列出所有有effect的武功及其分类"""
import json
with open('data/martial_arts_bonus.json', 'r', encoding='utf-8-sig') as f:
    data = json.load(f)
arts = data['martial_arts']
for name in sorted(arts.keys()):
    art = arts[name]
    if art.get('effect'):
        cat = art.get('category', '?')
        etype = art.get('effect', {}).get('type', '?')
        print(f"{name} | {cat} | {etype}")