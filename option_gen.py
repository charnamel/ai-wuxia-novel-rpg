"""行动选项清洗与 AI 兜底生成。

- clean_action_options: 把 AI 输出的 "A / B、C / 无 / / D" 清洗成 ["A", "B、C", "D"]
- generate_options: 当主循环未输出选项时，用辅助模型补 3 个候选行动

设计要点：
- 清洗只此一处，main.py 主循环解析和兜底生成都复用，避免逻辑重复。
- generate_options 内部懒导入 main.llm_call_common，避免与 main.py 循环导入。
"""
import re

# 纯标点/空白判定（不含中文顿号、字符、字母数字）
_PURE_PUNCT_RE = re.compile(r'^[\s\W_]+$', re.UNICODE)

# 选项分隔符（中文丨、半角| 与 / 等价）
_SEP_RE = re.compile(r'[/|丨]')
# 序号标记（非锚定，用于在字符串任意位置找出所有序号来切分多选项）
# 覆盖：1. 1、1) (1) ①   A. 一、 等（圈号 ① 允许裸用不带后缀标点）
_NUM_TOKEN_RE = re.compile(
    r'(?:\(\s*(?:\d+|[一二三四五六七八九十]|[①-⑳])\s*\)'
    r'|（\s*(?:\d+|[一二三四五六七八九十]|[①-⑳])\s*）'
    r'|(?:\d+|[①-⑳]|[一二三四五六七八九十])\s*[\.、)）]'
    r'|[①-⑳]'           # 裸圈号：①去药铺 ②问掌柜 等
    r'|[A-Za-z]\s*[\.、)）]'
    r')'
)
# 专用于"行首序号前缀"的剥离（单条去前缀用，锚定开头）
_NUM_PREFIX_RE = re.compile(
    r'^(?:\(\s*(?:\d+|[一二三四五六七八九十]|[①-⑳])\s*\)'
    r'|（\s*(?:\d+|[一二三四五六七八九十]|[①-⑳])\s*）'
    r'|(?:\d+|[①-⑳]|[一二三四五六七八九十])\s*[\.、)）]'
    r'|[①-⑳]'            # 裸圈号
    r'|[A-Za-z]\s*[\.、)）]'
    r')\s*'
)
# 中文句内标点（顿号/逗号，仅当整段无其他分隔符时兜底切分）
_INNER_PUNCT_RE = re.compile(r'[、，,]')


def _strip_opt(s: str) -> str:
    """单条选项清洗：去【】标签、去行首序号、去首尾空白。"""
    if "【" in s:
        s = s.split("【", 1)[0].strip()
    s = s.strip()
    s = _NUM_PREFIX_RE.sub("", s)
    s = s.strip()
    return s


def _split_by_number(raw: str) -> list:
    """用序号 token 切分多选项，返回切分后的原始段（每条仍带自己的序号前缀）。"""
    mids = list(_NUM_TOKEN_RE.finditer(raw))
    if len(mids) < 2:
        return []
    cuts = [m.start() for m in mids]
    segs = []
    segs.append(raw[:cuts[0]])  # 首个序号前的导语（通常为空）
    for i, c in enumerate(cuts):
        segs.append(raw[c:cuts[i + 1] if i + 1 < len(cuts) else len(raw)])
    # 丢弃只含空白的片段（如纯导语空段）
    return [s for s in segs if s.strip()]


def clean_action_options(raw: str) -> list:
    """把选项原始字符串清洗为选项数组。

    规则（按优先级，命中首个即用该规则切分）：
    1. 含 / 丨 | -> 按这些分节符切；
    2. 含多个换行（≥2 非空行）-> 按行切；
    3. 出现≥2 个序号标记（1. 1、① A. 等）且首段即是序号 -> 按序号切；
    4. 无以上且含顿号/逗号，且切出的每段都较短（≤12字）-> 按顿号/逗号切
       （避免误伤"继续拆招、询问养吾剑要诀"这类长句单选项）；
    5. 兜底返回单元素。
    每条再做单条清洗（去【】、去序号、去纯标点）。
    """
    if not raw:
        return []
    raw = raw.strip()
    parts = None

    # 规则1：显式分隔符
    if _SEP_RE.search(raw):
        parts = [p.strip() for p in _SEP_RE.split(raw)]
    # 规则2：多行
    elif raw.count("\n") >= 1 and sum(1 for ln in raw.split("\n") if ln.strip()) >= 2:
        parts = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    # 规则3：序号切分（开头即为序号，且至少2个）
    else:
        m0 = _NUM_TOKEN_RE.match(raw)
        if m0:
            segs = _split_by_number(raw)
            if len(segs) >= 2:
                parts = segs
        # 规则4：顿号/逗号兜底（每段都很短才切）
        if parts is None and _INNER_PUNCT_RE.search(raw):
            cands = [p.strip() for p in _INNER_PUNCT_RE.split(raw) if p.strip()]
            if len(cands) >= 2 and all(len(c) <= 12 for c in cands):
                parts = cands

    if parts is None:
        parts = [raw]

    result = []
    for p in parts:
        opt = _strip_opt(p)
        if not opt or opt == "无" or _PURE_PUNCT_RE.match(opt):
            continue
        result.append(opt)
    return result


def generate_options(l1_anchor: str, player_action: str, current_goal: str) -> list:
    """用辅助模型生成 3 个行动选项，返回清洗后的数组（失败返回空数组）。"""
    # 懒导入，避免与 main.py 循环导入
    from main import llm_call_common

    l1 = (l1_anchor or "")[-200:]
    goal = current_goal or "暂无明确目标"
    action = (player_action or "")[:100]

    sys_prompt = (
        "你是武侠RPG的行动选项生成器。根据上文剧情、玩家刚做的事、当前目标，"
        "给出 3 个玩家接下来可以做的行动候选。"
        "只输出一行，格式为：选项A / 选项B / 选项C，"
        "每个选项须贴合当前剧情、方向各异、可直接执行，避免空泛重复；"
        "禁止序号、解释、换行、冒号。"
    )
    user_prompt = (
        f"【上文剧情】{l1}\n"
        f"【玩家本轮行动】{action}\n"
        f"【当前目标】{goal}\n"
        f"请输出 3 个贴合当前剧情、方向各异、可直接执行的行动选项，用 / 分隔："
    )

    try:
        reply = llm_call_common(
            sys_prompt, user_prompt, temp=0.5, retry_times=1,
            max_tokens=80, stream=False,
        )
    except Exception as e:
        print(f"[option_gen] 兜底生成失败: {e}")
        return []

    # llm_call_common 返回 dict {'content':..., 'tool_calls':...}，取 content
    if isinstance(reply, dict):
        text = (reply.get("content") or "").strip()
    else:
        text = str(reply or "").strip()
    if not text:
        return []
    # 容错：剥序号、取首行、取首个句号前
    text = re.sub(r'^\s*\d+[\.、]\s*', '', text, flags=re.MULTILINE)
    text = text.split("\n")[0]
    text = text.split("。")[0]
    opts = clean_action_options(text)
    if len(opts) < 2:
        return []
    return opts[:3]
