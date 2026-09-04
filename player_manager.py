# 玩家管理模块
# 实现玩家角色的完整数据结构和操作，包括：
# - 修为境界系统（14个等级）
# - 武功修炼与经验系统
# - 瓶颈突破机制
# - 物品与传闻管理
# - 全局单例访问

import os
import json
import re
from file_utils import save_json, load_json

# 玩家数据文件路径
PLAYER_FILE = "data/player.json"
# 武功书文件路径（仿DND法术书，记录武功品阶与加成）
MARTIAL_ARTS_BOOK_FILE = "data/martial_arts_bonus.json"

# 武功书缓存（模块级，避免每次查表都读文件）
_martial_arts_book_cache = None


def clear_martial_arts_book_cache():
    """清空武功书缓存（武功书增删改后调用，确保下次重新从文件加载）"""
    global _martial_arts_book_cache
    _martial_arts_book_cache = None


def load_martial_arts_book():
    """加载武功书 JSON，返回 dict。失败返回空 dict。"""
    global _martial_arts_book_cache
    if _martial_arts_book_cache is not None:
        return _martial_arts_book_cache
    try:
        if os.path.exists(MARTIAL_ARTS_BOOK_FILE):
            with open(MARTIAL_ARTS_BOOK_FILE, encoding="utf-8") as f:
                _martial_arts_book_cache = json.load(f)
            return _martial_arts_book_cache
    except Exception:
        pass
    _martial_arts_book_cache = {"martial_arts": {}}
    return _martial_arts_book_cache


def lookup_skill_in_book(skill_name):
    """查武功书，返回 {grade, bonus, category, source, from_book}
    在书中→from_book=True；不在书中→from_book=False，使用兜底值
    支持模糊匹配: 去掉括号后缀（如"独孤九剑（残）"→"独孤九剑"）
    """
    book = load_martial_arts_book()
    arts = book.get("martial_arts", {})
    # 1. 精确匹配
    if skill_name in arts:
        info = arts[skill_name]
        return {
            "grade": int(info.get("grade", 4)),
            "bonus": int(info.get("bonus", 0)),
            "category": info.get("category", ""),
            "source": info.get("source", ""),
            "from_book": True,
        }
    # 2. 模糊匹配: 去掉中文括号和英文括号及其内容
    import re as _re
    _base_name = _re.sub(r'[（(].*?[）)]', '', skill_name).strip()
    if _base_name and _base_name != skill_name and _base_name in arts:
        info = arts[_base_name]
        return {
            "grade": int(info.get("grade", 4)),
            "bonus": int(info.get("bonus", 0)),
            "category": info.get("category", ""),
            "source": info.get("source", ""),
            "from_book": True,
        }
    # 3. 兜底值：中等级，无加成
    return {
        "grade": 4,
        "bonus": 0,
        "category": "",
        "source": "",
        "from_book": False,  # 不在书中，待手动丰富
    }


class Player:
    # 玩家角色类
    # 封装玩家的所有属性和操作方法
    
    # 14个修为境界，从低到高排列
    REALM_LIST = [
        "初学入门",      # 1档
        "初窥门径",      # 2档
        "略有小成",      # 3档
        "略有所成",      # 4档
        "渐入佳境",      # 5档
        "融会贯通",      # 6档
        "登堂入室",      # 7档
        "炉火纯青",      # 8档
        "出神入化",      # 9档
        "登峰造极",      # 10档
        "超凡入圣",      # 11档
        "返璞归真",      # 12档
        "天人合一",      # 13档
        "破碎虚空"       # 14档
    ]
    
    # 每个境界对应的经验阈值。曲线设计：初窥门径900/略有小成1800/略有所成2700/渐入佳境4300/
    # 融会贯通6000/登堂入室9000/炉火纯青12000/出神入化16500/登峰造极21000，
    # 超凡入圣(11档)起每档增量恒定8000。
    EXP_THRESHOLDS = [0, 900, 1800, 2700, 4300, 6000, 9000, 12000, 16500, 21000, 29000, 37000, 45000, 53000]

    @classmethod
    def get_realm(cls, exp):
        """根据经验值返回等级名称"""
        for i, threshold in enumerate(cls.EXP_THRESHOLDS):
            if exp < threshold:
                return cls.REALM_LIST[i - 1] if i > 0 else cls.REALM_LIST[0]
        return cls.REALM_LIST[-1]

    @classmethod
    def get_next_realm_exp(cls, exp):
        """返回升到下一级还需多少经验"""
        for i, threshold in enumerate(cls.EXP_THRESHOLDS):
            if exp < threshold:
                return threshold - exp
        return 0

    @classmethod
    def get_exp_by_realm(cls, realm):
        """根据等级名称返回对应的经验阈值"""
        try:
            idx = cls.REALM_LIST.index(realm)
            return cls.EXP_THRESHOLDS[idx]
        except (ValueError, IndexError):
            return 0

    def __init__(self, data=None):
        # 初始化玩家对象
        # data: 已有的玩家数据字典，None则创建新玩家
        if data:
            self._data = data
        else:
            self._data = {
                "name": "",
                "age": 0,
                "year": 0,
                "origin": "",
                "core_ability": "",
                "self_state": "状态平稳",
                "novel_node": "故事初始，尚未进入原著节点",
                "item_list": [],
                "overall_martial_level": "初学入门",
                "overall_realm": "初学入门",
                "martial_skill_list": [],
                "rumor_list": [],
                "equipped": {
                    "inner_martial": "",
                    "light_martial": "",
                    "weapon": "",
                    "armor": "",
                    "items": []
                },
                "vitality": {"hp": 100, "mp": 100, "poisoned": False},
                "bottleneck_level": 0,
                "bottleneck_progress": 0,
                "bottleneck_ready": False,
                "reputation": 0
            }
            if self._data.get("core_ability"):
                self._data["martial_skill_list"] = [{
                    "skill_name": self._data["core_ability"],
                    "exp": 0,
                    "exp_text": "初学入门，尚需时日打磨。"
                }]

    # ---------- 属性访问 ----------
    @property
    def name(self):
        # 玩家姓名
        return self._data.get("name", "")

    @name.setter
    def name(self, value):
        self._data["name"] = value

    @property
    def age(self):
        # 玩家年龄（0=未知，AI从origin推断）
        return self._data.get("age", 0)

    @age.setter
    def age(self, value):
        self._data["age"] = value

    @property
    def year(self):
        # 玩家出生年份（0=未知，AI从origin/novel_node推断）
        return self._data.get("year", 0)

    @year.setter
    def year(self, value):
        self._data["year"] = value

    @property
    def origin(self):
        # 玩家出身背景
        return self._data.get("origin", "")

    @origin.setter
    def origin(self, value):
        self._data["origin"] = value

    @property
    def core_ability(self):
        # 核心功法
        return self._data.get("core_ability", "")

    @core_ability.setter
    def core_ability(self, value):
        self._data["core_ability"] = value

    @property
    def self_state(self):
        # 自身状态描述
        return self._data.get("self_state", "状态平稳")

    @self_state.setter
    def self_state(self, value):
        self._data["self_state"] = value

    @property
    def novel_node(self):
        # 小说当前所处的原著节点
        return self._data.get("novel_node", "故事初始，尚未进入原著节点")

    @novel_node.setter
    def novel_node(self, value):
        self._data["novel_node"] = value

    @property
    def item_list(self):
        # 物品列表
        return self._data.get("item_list", [])

    @item_list.setter
    def item_list(self, value):
        self._data["item_list"] = value

    @property
    def overall_realm(self):
        # 总体修为境界
        return self._data.get("overall_realm", "初学入门")

    @overall_realm.setter
    def overall_realm(self, value):
        self._data["overall_realm"] = value

    @property
    def overall_martial_level(self):
        # 总体武功等级描述
        return self._data.get("overall_martial_level", "初学入门")

    @overall_martial_level.setter
    def overall_martial_level(self, value):
        self._data["overall_martial_level"] = value

    @property
    def martial_skill_list(self):
        # 武功列表
        return self._data.get("martial_skill_list", [])

    @martial_skill_list.setter
    def martial_skill_list(self, value):
        self._data["martial_skill_list"] = value

    @property
    def equipped(self):
        # 装备槽：内功/轻功/武器/防具
        from equipment_manager import EquipmentManager
        EquipmentManager.ensure_equipped(self)
        return self._data["equipped"]

    @equipped.setter
    def equipped(self, value):
        self._data["equipped"] = value

    @property
    def reputation(self):
        # 江湖名气（整数，正数=声望，负数=恶名）
        return self._data.get("reputation", 0)

    @reputation.setter
    def reputation(self, value):
        try:
            self._data["reputation"] = int(value)
        except (ValueError, TypeError):
            self._data["reputation"] = 0

    @property
    def rumor_list(self):
        # 传闻列表
        return self._data.get("rumor_list", [])

    @rumor_list.setter
    def rumor_list(self, value):
        self._data["rumor_list"] = value

    # ---------- V4 武功品阶加成系统 ----------
    # 瓶颈系数表：瓶颈重数 → 系数（本层差值×系数=瓶颈阈值）
    # 设计：早期瓶颈系数高（卡得紧，防早期突破太快），后期系数递减至×1.0（本层差值已大）
    BOTTLENECK_MULTIPLIER = {1: 1.5, 2: 1.4, 3: 1.3, 4: 1.2, 5: 1.1, 6: 1.0}

    # 基础修正表：整体境界 → 修正值（表A）
    BASE_BONUS_TABLE = {
        "初学入门": -1, "初窥门径": 0, "略有小成": 1, "略有所成": 2,
        "渐入佳境": 3, "融会贯通": 4, "登堂入室": 5, "炉火纯青": 6,
        "出神入化": 7, "登峰造极": 8, "超凡入圣": 9, "返璞归真": 10,
        "天人合一": 11, "破碎虚空": 12
    }
    # 武功境界加成表：武功境界 → 加成值（表B → 严格2境一档，瓶颈☆落在偶数档，突破瓶颈即晋档+1）
    # 初学入门0 略有小成1 渐入佳境2 登堂入室3 出神入化4 超凡入圣5 天人合一6 破碎虚空7
    SKILL_REALM_BONUS_TABLE = {
        "初学入门": 0, "初窥门径": 0, "略有小成": 1, "略有所成": 1,
        "渐入佳境": 2, "融会贯通": 2, "登堂入室": 3, "炉火纯青": 3,
        "出神入化": 4, "登峰造极": 4, "超凡入圣": 5, "返璞归真": 5,
        "天人合一": 6, "破碎虚空": 7
    }
    # 品阶加成表：grade → bonus（与martial_arts_bonus.json的MARTIAL_GRADE_BONUS严格一致）
    # V4.2 整体+2偏移：2级武功不再拖后腿，3级以上全部正向贡献
    GRADE_BONUS_TABLE = {
        9: 7, 8: 6, 7: 5, 6: 4, 5: 3,
        4: 2, 3: 1, 2: 0, 1: -1
    }

    @property
    def base_bonus(self):
        # V4 基础修正（基于整体境界 overall_realm）
        return self.BASE_BONUS_TABLE.get(self.overall_realm, 0)

    def get_skill_info(self, skill_name):
        # 查询玩家某门武功的完整信息
        # 返回: {skill_name, exp, skill_level, grade, bonus, realm_bonus, total_skill_bonus, from_book}
        # 若玩家未学此武功，返回 None
        # bonus/grade 缺失时自动查武功书兜底
        for skill in self.martial_skill_list:
            if skill.get("skill_name") == skill_name:
                exp = int(skill.get("exp", 0))
                # skill_level 缺失时自动从 exp 计算
                skill_level = skill.get("skill_level") or self.get_realm(exp)
                # bonus/grade 缺失时查武功书
                if "grade" not in skill or "bonus" not in skill:
                    _book_info = lookup_skill_in_book(skill_name)
                    skill["grade"] = _book_info["grade"]
                    skill["bonus"] = _book_info["bonus"]
                    skill["from_book"] = _book_info["from_book"]
                grade = int(skill.get("grade", 4))
                # V4平衡：用品阶查表值覆盖json存储的bonus，统一标定
                bonus = self.GRADE_BONUS_TABLE.get(grade, 0)
                from_book = bool(skill.get("from_book", True))
                realm_bonus = self.SKILL_REALM_BONUS_TABLE.get(skill_level, 0)
                return {
                    "skill_name": skill_name,
                    "exp": exp,
                    "skill_level": skill_level,
                    "grade": grade,
                    "bonus": bonus,            # 品阶基础加成
                    "realm_bonus": realm_bonus, # 境界加成
                    "total_skill_bonus": bonus + realm_bonus,
                    "from_book": from_book,     # 是否来自武功书权威值
                }
        return None

    def sync_skill_bonus_from_book(self):
        """同步武功书的 bonus/grade 到 player.json 的 martial_skill_list
        同时自动修正 skill_level（从 exp 重新计算，确保境界与经验匹配）
        场景: 玩家进入游戏或点击练功时调用
        作用:
          1. 自动从 exp 重新计算 skill_level（修正不匹配）
          2. 查武功书，在书中→取 grade/bonus，标记 from_book=True
          3. 不在书中→用兜底值(grade=4,bonus=0)，标记 from_book=False
        返回: (同步数量, 新增兜底数量, 修正境界数量)
        """
        synced_count = 0
        fallback_count = 0
        fixed_realm_count = 0
        for skill in self.martial_skill_list:
            skill_name = skill.get("skill_name", "")
            if not skill_name:
                continue
            # 1. 自动修正 skill_level（从 exp 重新计算）
            exp = int(skill.get("exp", 0))
            correct_level = self.get_realm(exp)
            stored_level = skill.get("skill_level", "")
            if stored_level != correct_level:
                skill["skill_level"] = correct_level
                fixed_realm_count += 1
            # 2. 查武功书填充 bonus/grade
            _book_info = lookup_skill_in_book(skill_name)
            skill["grade"] = _book_info["grade"]
            skill["bonus"] = _book_info["bonus"]
            skill["from_book"] = _book_info["from_book"]
            synced_count += 1
            if not _book_info["from_book"]:
                fallback_count += 1
        return synced_count, fallback_count, fixed_realm_count

    def get_skill_bonus(self, skill_name):
        # 获取某门武功的总加成（品阶基础+境界）
        # 玩家未学此武功时返回 0
        info = self.get_skill_info(skill_name)
        return info["total_skill_bonus"] if info else 0

    def get_skill_list_summary(self):
        # 获取所有武功的简短摘要（供AI检定用）
        # 按exp降序排列，让AI优先看到最强武功
        # 返回: ["紫霞神功：渐入佳境（第5档,品阶8）", ...]
        summary = []
        for skill in sorted(self.martial_skill_list, key=lambda s: int(s.get("exp", 0)), reverse=True):
            name = skill.get("skill_name", "")
            exp = int(skill.get("exp", 0))
            level = skill.get("skill_level") or self.get_realm(exp)
            grade = int(skill.get("grade", 4))
            try:
                level_idx = self.REALM_LIST.index(level) + 1
            except ValueError:
                level_idx = 1
            summary.append(f"{name}：{level}（第{level_idx}档,品阶{grade}级）")
        return summary

    # ---------- 瓶颈系统 ----------
    @property
    def bottleneck_level(self):
        # 瓶颈等级
        return self._data.get("bottleneck_level", 0)

    @bottleneck_level.setter
    def bottleneck_level(self, value):
        self._data["bottleneck_level"] = value

    @property
    def bottleneck_progress(self):
        # 瓶颈进度
        return self._data.get("bottleneck_progress", 0)

    @bottleneck_progress.setter
    def bottleneck_progress(self, value):
        self._data["bottleneck_progress"] = value

    @property
    def bottleneck_ready(self):
        # 瓶颈是否准备好突破
        return self._data.get("bottleneck_ready", False)

    @bottleneck_ready.setter
    def bottleneck_ready(self, value):
        self._data["bottleneck_ready"] = value
    
    def get_bottleneck_threshold(self):
        # 获取瓶颈阈值
        # 瓶颈阈值 = (下档阈值 − 当前阈值) × 瓶颈系数(递减：1.5→1.0)
        # 含义：早期瓶颈卡得紧（系数高），后期本层差值已大，系数递减至×1.0
        current_realm = self.overall_realm

        try:
            current_idx = self.REALM_LIST.index(current_realm)
        except ValueError:
            return 70

        if current_idx >= len(self.REALM_LIST) - 1:
            return 99999  # 最高境界无瓶颈

        current_exp = self.EXP_THRESHOLDS[current_idx]
        next_exp = self.EXP_THRESHOLDS[current_idx + 1]
        exp_diff = next_exp - current_exp

        # 按瓶颈重数查系数（1.5→1.4→1.3→1.2→1.1→1.0 递减）
        multiplier = self.BOTTLENECK_MULTIPLIER.get(self.bottleneck_level, 1.0)
        return max(10, int(exp_diff * multiplier))
    
    def get_bottleneck_map(self):
        # 返回瓶颈映射（便于其他方法使用）
        # 新版：每层末境为瓶颈（2/4/6/8/10/12档）
        return {
            "初窥门径": 1,   # 2档：入门→小成
            "略有所成": 2,   # 4档：小成→中坚
            "融会贯通": 3,   # 6档：中坚→一流
            "炉火纯青": 4,   # 8档：一流→绝顶（核心瓶颈·卡普通人一辈子）
            "登峰造极": 5,   # 10档：绝顶→宗师（天赋瓶颈·需奇遇）
            "返璞归真": 6    # 12档：宗师→传说（机缘瓶颈·神话级）
        }
    
    def get_highest_exp(self):
        # 返回当前经验最高的武功的经验值
        if not self.martial_skill_list:
            return 0
        return max(sk.get("exp", 0) for sk in self.martial_skill_list)

    def get_highest_skill_name(self):
        # 返回当前经验最高的武功名称
        if not self.martial_skill_list:
            return None
        highest = max(self.martial_skill_list, key=lambda x: x.get("exp", 0))
        return highest.get("skill_name")

    # ---------- 核心方法 ----------
    def add_exp(self, skill_name, exp_gain):
        # 为指定武功增加经验值，自动处理瓶颈转化
        # 核心规则：
        # - 无瓶颈：正常加经验，自动升级
        # - 有瓶颈：任何武功经验超过瓶颈锁定的境界阈值时，溢出部分转化为瓶颈进度，
        #   武功经验截断到阈值，瓶颈进度满则突破
        # skill_name: 武功名称
        # exp_gain: 增加的经验值
        # 返回: 成功返回True
        if exp_gain <= 0:
            return False

        # 查找武功
        target_sk = None
        for sk in self.martial_skill_list:
            if sk["skill_name"] == skill_name:
                target_sk = sk
                break
        if not target_sk:
            return False

        old_exp = target_sk.get("exp", 0)
        new_exp = old_exp + exp_gain

        # ---- 如果有瓶颈，处理溢出转化 ----
        if self.bottleneck_level > 0:
            # 获取当前锁定的境界（瓶颈期 overall_realm 被锁定）
            locked_realm = self.overall_realm
            try:
                idx = self.REALM_LIST.index(locked_realm)
                if idx >= len(self.REALM_LIST) - 1:
                    # 已达最高境界，瓶颈不应该存在，按无瓶颈处理
                    target_sk["exp"] = new_exp
                    self.sync_overall_level()
                    self.save()
                    self.update_bottleneck_status()
                    return True
                threshold = self.EXP_THRESHOLDS[idx + 1]  # 下一境界所需经验
            except (ValueError, IndexError):
                # 异常情况，按无瓶颈处理
                target_sk["exp"] = new_exp
                self.sync_overall_level()
                self.save()
                self.update_bottleneck_status()
                return True

            if new_exp >= threshold:
                # 计算溢出量
                overflow = new_exp - threshold
                # 累积瓶颈进度
                self.bottleneck_progress += overflow
                # 截断武功经验到阈值
                target_sk["exp"] = threshold

                # 检查瓶颈是否可突破
                bottleneck_threshold = self.get_bottleneck_threshold()
                if self.bottleneck_progress >= bottleneck_threshold:
                    # 突破！
                    self._breakthrough(skill_name)
                    # _breakthrough 内部会重置瓶颈并升级武功（经验设置为下一境界阈值）
                else:
                    print(f"【瓶颈积累】{skill_name} 溢出 {overflow} 点，瓶颈进度 {self.bottleneck_progress}/{bottleneck_threshold}")
                    self.save()
                    self.update_bottleneck_status()
                return True
            else:
                # 未达到阈值，正常加经验
                target_sk["exp"] = new_exp
                self.save()
                self.update_bottleneck_status()
                return True
        else:
            # 无瓶颈，正常加经验
            target_sk["exp"] = new_exp
            # 检查是否升级（提升感悟）
            old_realm = self.get_realm(old_exp)
            new_realm = self.get_realm(new_exp)
            if old_realm != new_realm:
                if not target_sk.get("exp_text"):
                    target_sk["exp_text"] = f"{new_realm}，武学境界再上一层。"
                else:
                    target_sk["exp_text"] = target_sk.get("exp_text", "") + f"  终至{new_realm}。"
            self.sync_overall_level()
            self.save()
            self.update_bottleneck_status()
            return True
    
    
    def update_bottleneck_status(self):
        # 根据当前 overall_realm 更新瓶颈状态
        # 如果处于瓶颈区间，设置 bottleneck_level 和进度；
        # 如果超出瓶颈区间，仅在瓶颈已满时重置瓶颈
        # 新版：每层末境为瓶颈（2/4/6/8/10/12档）
        BOTTLENECK_MAP = {
            "初窥门径": 1,   # 2档：入门→小成
            "略有所成": 2,   # 4档：小成→中坚
            "融会贯通": 3,   # 6档：中坚→一流
            "炉火纯青": 4,   # 8档：一流→绝顶（核心瓶颈）
            "登峰造极": 5,   # 10档：绝顶→宗师（天赋瓶颈）
            "返璞归真": 6    # 12档：宗师→传说（机缘瓶颈）
        }

        main_realm = self.overall_realm

        if main_realm in BOTTLENECK_MAP:
            needed = BOTTLENECK_MAP[main_realm]
            if self.bottleneck_level == 0:
                # 首次进入瓶颈
                self.bottleneck_level = needed
                self.bottleneck_progress = 0
                self.bottleneck_ready = False
                print(f"⚠️ 玩家进入第 {needed} 重瓶颈！")
            elif self.bottleneck_level < needed:
                # 瓶颈重数升级
                self.bottleneck_level = needed
                new_threshold = self.get_bottleneck_threshold()
                if self.bottleneck_progress > new_threshold:
                    self.bottleneck_progress = new_threshold
                    self.bottleneck_ready = True
                    print(f"⚠️ 瓶颈已升级至第 {needed} 重，且进度已满，等待突破契机！")
                else:
                    print(f"⚠️ 瓶颈已升级至第 {needed} 重，保留原有进度 {self.bottleneck_progress}/{new_threshold}")
        else:
            # 境界不在瓶颈映射中
            if self.bottleneck_level > 0 and self.bottleneck_ready:
                # 瓶颈已满，境界却不在映射中 -> 说明已经突破，清除瓶颈
                self.bottleneck_level = 0
                self.bottleneck_progress = 0
                self.bottleneck_ready = False
                print("✅ 玩家已突破瓶颈！")
            elif self.bottleneck_level > 0 and not self.bottleneck_ready:
                # 瓶颈未满，境界不在映射中 -> 保留瓶颈状态，继续积累
                pass  # 不做任何操作，保留原瓶颈等级和进度

        self.save()
        
    def _breakthrough(self, skill_name):
        # 瓶颈突破：武功经验跳到下一境界，瓶颈重置
        # skill_name: 突破的武功名称
        current_realm = self.overall_realm
        try:
            current_idx = self.REALM_LIST.index(current_realm)
            if current_idx < len(self.REALM_LIST) - 1:
                next_realm = self.REALM_LIST[current_idx + 1]
                next_exp = self.EXP_THRESHOLDS[current_idx + 1]
                for sk in self.martial_skill_list:
                    if sk["skill_name"] == skill_name:
                        sk["exp"] = next_exp
                        sk["exp_text"] = sk.get("exp_text", "") + f"  突破至{next_realm}。"
                        break
                print(f"【突破成功】{skill_name} 突破至 {next_realm}（经验 {next_exp}）")
            else:
                print(f"【已达巅峰】{skill_name} 已至最高境界")
                return
        except (ValueError, IndexError):
            return

        self.bottleneck_level = 0
        self.bottleneck_progress = 0
        self.bottleneck_ready = False
        self.sync_overall_level()
        self.save()

    # ---------- 辅助方法 ----------
    def add_skill(self, skill_name, initial_exp=0, initial_text=""):
        # 新增武功（如已存在则忽略）
        # skill_name: 武功名称
        # initial_exp: 初始经验
        # initial_text: 初始感悟文字
        # 返回: 成功新增返回True
        # 新增时自动查武功书填充 bonus/grade
        for sk in self.martial_skill_list:
            if sk["skill_name"] == skill_name:
                return False
        _book_info = lookup_skill_in_book(skill_name)
        self.martial_skill_list.append({
            "skill_name": skill_name,
            "exp": max(0, initial_exp),
            "exp_text": initial_text or "",
            "grade": _book_info["grade"],
            "bonus": _book_info["bonus"],
            "from_book": _book_info["from_book"],
        })
        return True

    def remove_skill(self, skill_name):
        # 移除武功
        # skill_name: 武功名称
        self.martial_skill_list = [sk for sk in self.martial_skill_list if sk["skill_name"] != skill_name]

    def update_exp_text(self, skill_name, new_text):
        # 更新武功的感悟文字
        # skill_name: 武功名称
        # new_text: 新的感悟文字
        if not new_text or not skill_name:
            return
        for sk in self.martial_skill_list:
            if sk["skill_name"] == skill_name:
                sk["exp_text"] = new_text
                return

    def sync_overall_level(self):
        # 根据武功列表重新计算 overall_realm 和 overall_martial_level
        if not self.martial_skill_list:
            self.overall_realm = "初学入门"
            self.overall_martial_level = "初学入门"
            return

        max_exp = 0
        display_parts = []
        for sk in self.martial_skill_list:
            exp = sk.get("exp", 0)
            name = sk.get("skill_name", "")
            if name:
                realm = self.get_realm(exp)
                display_parts.append(f"{name} {realm}")
                if exp > max_exp:
                    max_exp = exp

        true_realm = self.get_realm(max_exp)

        # ---- 瓶颈期锁定：瓶颈未满时，境界锁定为瓶颈对应的境界
        if self.bottleneck_level > 0 and not self.bottleneck_ready:
            # 通过 bottleneck_level 反查对应的境界名称
            locked_realm = None
            for realm, level in self.get_bottleneck_map().items():
                if level == self.bottleneck_level:
                    locked_realm = realm
                    break
            if locked_realm:
                self.overall_realm = locked_realm
                # 同时修正显示字符串中的境界名称，保持一致
                corrected_parts = []
                for sk in self.martial_skill_list:
                    name = sk.get("skill_name", "")
                    exp = sk.get("exp", 0)
                    # 如果是最高武功，使用锁定境界显示
                    if exp >= max_exp:
                        corrected_parts.append(f"{name} {locked_realm}")
                    else:
                        corrected_parts.append(f"{name} {self.get_realm(exp)}")
                self.overall_martial_level = " / ".join(corrected_parts) if corrected_parts else "初学入门"
                return
            else:
                # 找不到对应的境界（异常情况），使用真实境界
                self.overall_realm = true_realm
        else:
            self.overall_realm = true_realm

        self.overall_martial_level = " / ".join(display_parts) if display_parts else "初学入门"

    # ---------- 物品、传闻 ----------
    def add_item(self, item_name):
        # 添加物品（重复物品不重复添加）
        # item_name: 物品名称
        if item_name and item_name.strip() and item_name.strip() != "无":
            if item_name not in self.item_list:
                self.item_list.append(item_name)

    def remove_item(self, item_name):
        # 移除物品
        # item_name: 物品名称
        if item_name in self.item_list:
            self.item_list.remove(item_name)

    def add_rumor(self, rumor_text):
        # 添加传闻，自动去重并限制最近20条
        rumor_text = (rumor_text or "").strip()
        if not rumor_text or rumor_text == "无":
            return
        if rumor_text not in self.rumor_list:
            self.rumor_list.append(rumor_text)
        if len(self.rumor_list) > 20:
            self._data["rumor_list"] = self.rumor_list[-20:]

    def to_dict(self):
        # 转换为字典
        # 返回: 玩家数据字典
        return self._data.copy()

    def save(self, path=PLAYER_FILE):
        # 保存到文件
        # path: 保存路径
        save_json(path, self._data)

    @classmethod
    def load(cls, path=PLAYER_FILE):
        # 从文件加载
        # path: 文件路径
        # 返回: Player对象，失败返回None
        data = load_json(path)
        if data:
            return cls(data)
        return None

    @classmethod
    def create_new(cls, name, origin, ability, age=0, year=0):
        # 创建新玩家
        # name: 玩家姓名
        # origin: 出身背景
        # ability: 核心功法
        # age: 玩家年龄（0=未知，AI从origin推断）
        # year: 出生年份（0=未知，AI从origin推断）
        # 返回: 新的Player对象
        player = cls()
        player.name = name
        player.age = age
        player.year = year
        player.origin = origin
        player.core_ability = ability
        player.self_state = "状态平稳"
        player.item_list = []
        player.martial_skill_list = [{
            "skill_name": ability,
            "exp": 0,
            "exp_text": "初学入门，尚需时日打磨。"
        }]
        player.rumor_list = []
        player.bottleneck_level = 0
        player.bottleneck_progress = 0
        player.bottleneck_ready = False
        player.sync_overall_level()
        player.save()
        return player


# ---------- 全局单例 ----------
_player_instance = None


def get_player():
    # 获取全局玩家单例
    # 返回: Player对象
    global _player_instance
    if _player_instance is None:
        _player_instance = Player.load()
        if _player_instance is None:
            _player_instance = Player()
    return _player_instance


def reload_player():
    """强制从文件重新加载Player单例（文件被外部修改后调用）"""
    global _player_instance
    _player_instance = Player.load()
    if _player_instance is None:
        _player_instance = Player()
    return _player_instance


def set_player(player_obj):
    # 设置全局玩家单例
    # player_obj: Player对象
    global _player_instance
    _player_instance = player_obj


def sync_age_from_novel_node(player=None):
    """从 novel_node 提取年份自动更新 age（只涨不减）。
    匹配 novel_node 中的 1~9999 年份数字（如"1754年春"），age = 年份 - year。
    遍历所有匹配取第一个推算出合理年龄的；year=0（未知）、
    无合理匹配、或推算结果倒退时不动。"""
    if player is None:
        player = get_player()
    if not player:
        return None
    year = player._data.get("year", 0)
    if not year:
        return None
    for m in re.finditer(r"(\d{1,4})年", player.novel_node or ""):
        new_age = int(m.group(1)) - int(year)
        if 0 <= new_age <= 120 and new_age >= player.age:
            if new_age != player.age:
                player.age = new_age
                player.save()
                print(f"[年龄同步] novel_node 年份推算：{m.group(1)} - {year} = {new_age} 岁")
            return new_age
    return None


# ---------- 外挂级玩家属性编辑器 ----------
def edit_player_raw():
    # 外挂级玩家属性编辑器：返回完整玩家字典
    # 强制从文件重新加载，确保获取main.py等其他进程写入的最新数据
    # 返回: (success: bool, player_dict: dict, msg: str)
    player = Player.load()
    if not player:
        return False, {}, "未找到玩家存档，请先创建角色。"
    set_player(player)
    return True, player.to_dict(), "读取成功"


def save_player_raw(new_dict):
    # 直接用字典覆盖保存玩家数据（兼容封装类属性）
    # 强制从文件重新加载最新数据，防止内存缓存覆盖其他进程写入
    # new_dict: 新的玩家数据字典
    # 返回: (success: bool, msg: str)
    try:
        player = Player.load()
        if not player:
            return False, "未找到玩家存档"
        
        # 必填字段基础校验
        required = ["name", "origin", "core_ability", "martial_skill_list", "item_list"]
        for k in required:
            if k not in new_dict:
                return False, f"缺少必填字段：{k}"
        
        type_checks = {
            "rumor_list": list,
            "martial_skill_list": list,
            "item_list": list,
            "bottleneck_level": (int,),
            "bottleneck_progress": (int,),
            "bottleneck_ready": (bool,)
        }
        for field, expected_type in type_checks.items():
            if field in new_dict and not isinstance(new_dict[field], expected_type):
                expected_name = getattr(expected_type, '__name__', str(expected_type))
                return False, f"字段 {field} 类型错误，期望 {expected_name}，实际 {type(new_dict[field]).__name__}"
        
        # 直接操作 _data 字典，绕过 @property 机制（兼容游戏运行时动态添加的字段）
        modified_count = 0
        for key, value in new_dict.items():
            player._data[key] = value
            modified_count += 1
        
        # 修改武功/属性后强制同步整体境界
        if hasattr(player, 'sync_overall_level'):
            player.sync_overall_level()
        
        # 持久化保存 + 刷新全局玩家缓存
        player.save()
        set_player(player)
        
        return True, f"保存成功，共更新 {modified_count} 个字段"
    except Exception as e:
        # 控制台打印详细错误栈，便于排查
        print(f"[ERROR] 保存玩家数据失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False, f"保存失败：{str(e)}"


def set_player_field(field_path, value):
    # 快捷修改单个字段，支持点语法，兼容对象属性、列表、字典嵌套
    # field_path: 字段路径，如 "martial_skill_list.0.exp"
    # value: 新的值
    # 返回: (success: bool, msg: str)
    try:
        player = get_player()
        if not player:
            return False, "未找到玩家存档"
        
        keys = field_path.split(".")
        if not keys:
            return False, "字段路径为空"

        # 逐层定位到倒数第二层
        current = player
        for key in keys[:-1]:
            if isinstance(current, dict):
                # 字典类型：数字键自动转整数
                k = int(key) if key.isdigit() else key
                if k not in current:
                    return False, f"字典中不存在字段：{key}"
                current = current[k]
            elif isinstance(current, list):
                # 列表类型：必须是数字索引
                if not key.isdigit():
                    return False, f"列表索引必须为数字，收到：{key}"
                idx = int(key)
                if idx < 0 or idx >= len(current):
                    return False, f"列表索引越界：{idx}，总长度：{len(current)}"
                current = current[idx]
            else:
                # 对象类型：用 getattr 访问属性
                if not hasattr(current, key):
                    return False, f"对象不存在属性：{key}"
                current = getattr(current, key)

        # 自动转换值类型
        val = value
        try:
            if str(val).isdigit():
                val = int(val)
            elif str(val).lower() in ["true", "false"]:
                val = str(val).lower() == "true"
        except Exception:
            pass

        # 给最后一层赋值
        last_key = keys[-1]
        if isinstance(current, dict):
            k = int(last_key) if last_key.isdigit() else last_key
            current[k] = val
        elif isinstance(current, list):
            if not last_key.isdigit():
                return False, f"列表索引必须为数字，收到：{last_key}"
            idx = int(last_key)
            if idx < 0 or idx >= len(current):
                return False, f"列表索引越界：{idx}，总长度：{len(current)}"
            current[idx] = val
        else:
            # 对象属性赋值
            if not hasattr(current, last_key):
                return False, f"对象不存在属性：{last_key}"
            setattr(current, last_key, val)

        # 保存并刷新全局玩家对象
        player.save()
        set_player(player)
        return True, f"字段 {field_path} 已更新为 {val}"
    except Exception as e:
        return False, f"修改失败：{str(e)}"
