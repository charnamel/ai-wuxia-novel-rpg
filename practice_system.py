import os
import json
import re
import random
import time
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, COMMON_TIMEOUT
from player_manager import get_player

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def llm_call_common(sys_prompt: str, user_prompt: str, temp=0.7, retry_times=2):
    """通用LLM调用"""
    def clean_text_block(text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    clean_sys = clean_text_block(sys_prompt)
    clean_user = clean_text_block(user_prompt)

    for i in range(retry_times + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": clean_sys},
                    {"role": "user", "content": clean_user}
                ],
                temperature=temp,
                max_tokens=800,
                top_p=1.0,
                stream=False,
                timeout=COMMON_TIMEOUT,
                extra_body={"thinking": {"type": "disabled"}}
            )
            result = resp.choices[0].message.content.strip()
            if result:
                return result
            raise Exception("模型返回空文本")
        except Exception:
            if i < retry_times:
                time.sleep(1.2 * (2 ** i))
            else:
                return ""
    return ""


def do_practice(is_first_init: bool = False):
    """
    练功主函数（一键对所有武功整体修炼）

    流程：
    1. 检索：读取并校验所有武功数据完整性（印证）
    2. 感悟：为每门武功生成新的感悟文字（根据各自境界）
    3. 经验：每门武功随机获得 1~3 点经验
    4. 瓶颈：由 add_exp 自动转化，无需单独处理
    """
    player = get_player()
    if not player:
        return False, "【未读取到玩家存档，无法练功】"

    skill_list = player.martial_skill_list
    if not skill_list:
        return False, "【当前没有习得任何武功，无法练功。请先通过剧情获取功法。】"

    # ===== 1. 检索印证：校验所有武功数据完整性 =====
    need_fix = False
    for idx, sk in enumerate(skill_list):
        if not sk.get("skill_name"):
            print(f"【数据修复】第 {idx+1} 条武功缺少名称，已自动修复")
            sk["skill_name"] = f"未知武功_{idx+1}"
            need_fix = True

        exp = sk.get("exp", 0)
        if not isinstance(exp, int) or exp < 0:
            print(f"【数据修复】{sk['skill_name']} 经验值异常，已重置为 0")
            sk["exp"] = 0
            need_fix = True

        if not sk.get("exp_text"):
            sk["exp_text"] = f"{sk['skill_name']}，初学入门，尚需时日打磨。"
            need_fix = True

    if need_fix:
        player.save()
        print("【印证完成】武功列表数据已修复")

    # ===== 2. 遍历每门武功，生成感悟 + 加经验 =====
    results = []
    for sk in skill_list:
        skill_name = sk["skill_name"]
        current_exp = sk.get("exp", 0)
        current_realm = player.get_realm(current_exp)
        current_text = sk.get("exp_text", "")

        # ---- 2.1 AI生成该武功的新感悟 ----
        prompt = f"""
你是一位武侠修炼推演师，为武功「{skill_name}」生成修炼感悟。

【当前武功境界】{current_realm}
【当前感悟】{current_text}

【境界-感悟对应表】
- 初学入门：刚摸到门路，体会尚浅，感悟应体现“入门、基础、生涩”。
- 初窥门径：已能初步运用，感悟应体现“初窥、尝试、略有心得”。
- 略有小成：招式熟练，内力渐生，感悟应体现“圆融、流畅、小成”。
- 略有所成：功架扎实，已能实战，感悟应体现“沉稳、自信、有所成”。
- 渐入佳境：武学理解加深，感悟应体现“渐入、意境、质变”。
- 登堂入室：掌握核心精髓，感悟应体现“登堂、入室、贯通”。
- 融会贯通：武学融会贯通，感悟应体现“融合、自成体系”。
- 炉火纯青：修炼至纯熟极致，感悟应体现“纯熟、收发自如”。
- 出神入化：超越原功法限制，感悟应体现“变化莫测、神妙”。
- 登峰造极：达到最高境界，感悟应体现“宗师、化境”。
- 超凡入圣：超越凡俗，感悟应体现“超凡、通神”。
- 返璞归真：由繁入简，感悟应体现“返朴、归真、大巧不工”。
- 天人合一：人与天地合，感悟应体现“天人、自然、大道”。
- 破碎虚空：超越现有体系，感悟应体现“虚空、巅峰、超越”。

【任务】
根据「{skill_name}」当前境界「{current_realm}」，生成一段新的感悟文字（20~30字）。
要求：
1. 必须贴合「{current_realm}」的层次，不可跳跃
2. 感悟内容要体现当前境界的特点（参考上表）
3. 必须按照金庸武侠小说的风格生成相应的感悟
4. 不要重复已有的感悟文字
5. 只输出感悟文字，不要其他内容
"""
        raw_text = llm_call_common("", prompt, temp=0.7)
        if not raw_text or len(raw_text) < 5:
            # 兜底：根据境界生成默认感悟
            tips = {
                "初学入门": f"初习「{skill_name}」，尚需时日打磨根基。",
                "初窥门径": f"「{skill_name}」初窥门径，略有心得。",
                "略有小成": f"「{skill_name}」渐有圆融之感，小有所成。",
                "略有所成": f"「{skill_name}」已得要领，功架渐稳。",
                "渐入佳境": f"「{skill_name}」渐入佳境，武学理解日益精进。",
                "登堂入室": f"「{skill_name}」已登堂入室，得其神髓。",
                "融会贯通": f"「{skill_name}」融会贯通，自成体系。",
                "炉火纯青": f"「{skill_name}」已臻纯熟，收发由心。",
                "出神入化": f"「{skill_name}」出神入化，变化莫测。",
                "登峰造极": f"「{skill_name}」登峰造极，已达化境。",
                "超凡入圣": f"「{skill_name}」超凡入圣，通神入化。",
                "返璞归真": f"「{skill_name}」返璞归真，大巧不工。",
                "天人合一": f"「{skill_name}」天人合一，与道相合。",
                "破碎虚空": f"「{skill_name}」破碎虚空，达至巅峰。"
            }
            raw_text = tips.get(current_realm, f"「{skill_name}」修炼有所精进。")

        # ---- 2.2 更新感悟 ----
        player.update_exp_text(skill_name, raw_text)

        # ---- 2.3 随机获得 1~3 点经验（瓶颈进度由 add_exp 自动转化） ----
        exp_gain = random.randint(1, 3)
        player.add_exp(skill_name, exp_gain)

        new_exp = sk.get("exp", 0)
        new_realm = player.get_realm(new_exp)

        results.append(f"{skill_name}：{new_realm}（+{exp_gain}经验）\n  “{raw_text}”")

    # ===== 3. 同步并保存 =====
    player.sync_overall_level()
    player.update_bottleneck_status()
    player.save()

    # ===== 4. 返回结果 =====
    msg = "【练功完成】\n" + "\n".join(results)
    return True, msg