# -*- coding: utf-8 -*-
"""
装备管理系统模块
管理玩家装备槽：内功、轻功、武器、防具、随身物品
负责装备/卸下校验、联动清空、装备状态查询
"""
import json
import re
import os

ITEMS_CATALOG_FILE = "data/items_catalog.json"
_items_catalog_cache = None


def _load_items_catalog():
    """加载物品目录（带缓存）"""
    global _items_catalog_cache
    if _items_catalog_cache is not None:
        return _items_catalog_cache
    try:
        with open(ITEMS_CATALOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _items_catalog_cache = data
        return data
    except Exception:
        return {"items": {}}


def _get_item_subcategory(item_name):
    """查物品的subcategory，先查catalog，查不到用启发式"""
    data = _load_items_catalog()
    items = data.get("items", {})
    # 精确匹配
    for item in items.values():
        if isinstance(item, dict) and item.get("name") == item_name:
            return item.get("subcategory", "")
    # 去括号模糊匹配
    base_name = re.sub(r'[（(].*?[）)]', '', item_name).strip()
    if base_name and base_name != item_name:
        for item in items.values():
            if isinstance(item, dict):
                cat_name = item.get("name", "")
                if cat_name == base_name:
                    return item.get("subcategory", "")
    # 启发式判断
    for kw in ("剑", "刀", "枪", "棍", "鞭", "锏", "锤", "斧", "匕", "钩"):
        if kw in item_name:
            return "武器"
    for kw in ("甲", "袍", "衣", "衫", "铠", "盾", "帽", "靴"):
        if kw in item_name:
            return "防具"
    return ""


class EquipmentSlots:
    """装备槽常量"""
    INNER = "inner_martial"
    LIGHT = "light_martial"
    WEAPON = "weapon"
    ARMOR = "armor"
    ITEMS = "items"  # 随身物品（可多个，list类型）

    # 单值槽位（string）和列表槽位（list）分开管理
    SINGLE_SLOTS = [INNER, LIGHT, WEAPON, ARMOR]
    LIST_SLOTS = [ITEMS]

    ALL = SINGLE_SLOTS + LIST_SLOTS
    LABELS = {
        INNER: "内功",
        LIGHT: "轻功",
        WEAPON: "武器",
        ARMOR: "防具",
        ITEMS: "随身物品",
    }


_DEFAULT_EQUIPPED = {
    EquipmentSlots.INNER: "",
    EquipmentSlots.LIGHT: "",
    EquipmentSlots.WEAPON: "",
    EquipmentSlots.ARMOR: "",
    EquipmentSlots.ITEMS: [],
}


class EquipmentManager:
    """装备管理器：校验、装备、卸下、联动清空"""

    @staticmethod
    def ensure_equipped(player):
        """确保player._data中有完整的equipped字段，缺失自动补全"""
        eq = player._data.get("equipped")
        if not isinstance(eq, dict):
            player._data["equipped"] = dict(_DEFAULT_EQUIPPED)
            return
        # 补全缺失的槽位
        for slot in EquipmentSlots.ALL:
            if slot not in eq:
                eq[slot] = [] if slot in EquipmentSlots.LIST_SLOTS else ""
            elif slot in EquipmentSlots.LIST_SLOTS and not isinstance(eq[slot], list):
                # 修复旧数据：list槽位存了string
                eq[slot] = [eq[slot]] if eq[slot] else []

    @staticmethod
    def get_equipped(player, slot=None):
        """获取装备状态，slot=None返回全部"""
        EquipmentManager.ensure_equipped(player)
        if slot:
            return player._data["equipped"].get(slot, "" if slot in EquipmentSlots.SINGLE_SLOTS else [])
        return dict(player._data["equipped"])

    @staticmethod
    def _get_skill_category(player, skill_name):
        """查武功category，先查武功书，查不到用启发式"""
        try:
            from player_manager import lookup_skill_in_book
            book_info = lookup_skill_in_book(skill_name)
            if book_info:
                cat = book_info.get("category", "")
                if cat:
                    return cat
        except Exception:
            pass
        # 启发式（与dice_system的_get_category一致）
        for kw in ("剑", "刀", "掌", "拳", "指", "爪", "腿", "脚"):
            if kw in skill_name:
                return ""
        for kw in ("鞭", "音", "琴", "箫", "声", "吼", "啸"):
            if kw in skill_name:
                return "special"
        for kw in ("功", "经", "气", "诀"):
            if kw in skill_name:
                return "internal"
        for kw in ("步", "轻功", "纵"):
            if kw in skill_name:
                return "lightfoot"
        return ""

    @staticmethod
    def validate(player, slot, name):
        """校验装备合法性，返回 {"ok": bool, "reason": str}"""
        if not name or not name.strip():
            return {"ok": False, "reason": "名称不能为空"}
        name = name.strip()

        if slot in (EquipmentSlots.INNER, EquipmentSlots.LIGHT):
            skill_names = [s.get("skill_name", "") for s in player.martial_skill_list]
            if name not in skill_names:
                return {"ok": False, "reason": f"未习得武功：{name}"}
            cat = EquipmentManager._get_skill_category(player, name)
            expected = "internal" if slot == EquipmentSlots.INNER else "lightfoot"
            if cat != expected:
                label = EquipmentSlots.LABELS.get(slot, slot)
                return {"ok": False, "reason": f"{name} 不是{label}"}
            return {"ok": True}

        elif slot == EquipmentSlots.WEAPON:
            if name not in player.item_list:
                return {"ok": False, "reason": f"未持有物品：{name}"}
            subcat = _get_item_subcategory(name)
            if subcat and subcat != "武器":
                return {"ok": False, "reason": f"{name} 不是武器（分类：{subcat}）"}
            return {"ok": True}

        elif slot == EquipmentSlots.ARMOR:
            if name not in player.item_list:
                return {"ok": False, "reason": f"未持有物品：{name}"}
            subcat = _get_item_subcategory(name)
            if subcat and subcat != "防具":
                return {"ok": False, "reason": f"{name} 不是防具（分类：{subcat}）"}
            return {"ok": True}

        elif slot == EquipmentSlots.ITEMS:
            # 随身物品：只要在item_list中即可，无类型限制
            if name not in player.item_list:
                return {"ok": False, "reason": f"未持有物品：{name}"}
            return {"ok": True}

        return {"ok": False, "reason": f"未知装备槽：{slot}"}

    @staticmethod
    def equip(player, slot, name):
        """装备，返回 {"ok": bool, "reason": str}"""
        EquipmentManager.ensure_equipped(player)
        result = EquipmentManager.validate(player, slot, name)
        if not result["ok"]:
            return result
        name = name.strip()
        if slot in EquipmentSlots.LIST_SLOTS:
            # 列表槽位：避免重复添加
            if name not in player._data["equipped"][slot]:
                player._data["equipped"][slot].append(name)
        else:
            player._data["equipped"][slot] = name
        return {"ok": True}

    @staticmethod
    def unequip(player, slot, name=None):
        """卸下。单值槽位直接清空；列表槽位需指定name移除该项"""
        EquipmentManager.ensure_equipped(player)
        if slot in EquipmentSlots.LIST_SLOTS:
            if name and name in player._data["equipped"][slot]:
                player._data["equipped"][slot].remove(name)
            return {"ok": True}
        else:
            player._data["equipped"][slot] = ""
            return {"ok": True}

    @staticmethod
    def clear_if_equipped(player, skill_name=None, item_name=None):
        """联动清空：遗忘武功/丢弃物品时自动检查并清空对应槽位"""
        EquipmentManager.ensure_equipped(player)
        eq = player._data["equipped"]
        cleared = []
        if skill_name:
            for slot in (EquipmentSlots.INNER, EquipmentSlots.LIGHT):
                if eq.get(slot) == skill_name:
                    eq[slot] = ""
                    cleared.append(EquipmentSlots.LABELS.get(slot, slot))
        if item_name:
            # 单值槽位
            for slot in (EquipmentSlots.WEAPON, EquipmentSlots.ARMOR):
                if eq.get(slot) == item_name:
                    eq[slot] = ""
                    cleared.append(EquipmentSlots.LABELS.get(slot, slot))
            # 列表槽位
            for slot in EquipmentSlots.LIST_SLOTS:
                lst = eq.get(slot, [])
                if isinstance(lst, list) and item_name in lst:
                    lst.remove(item_name)
                    cleared.append(EquipmentSlots.LABELS.get(slot, slot))
        return cleared
