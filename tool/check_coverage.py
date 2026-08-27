"""检查覆盖进度"""
import json
with open('data/martial_arts_bonus.json', 'r', encoding='utf-8-sig') as f:
    data = json.load(f)
arts = data['martial_arts']
with_effect = [k for k, v in arts.items() if v.get('effect')]
with_move = [k for k in with_effect if arts[k].get('special_move_name')]
missing = [k for k in with_effect if not arts[k].get('special_move_name')]
print(f"有effect: {len(with_effect)}, 有特技: {len(with_move)}, 缺失: {len(missing)}")
if missing:
    for m in missing:
        art = arts[m]
        print(f"  {m} | {art.get('category')} | {art.get('effect',{}).get('type')}")