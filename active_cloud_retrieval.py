"""
云向量主动检索模块（独立运行，与DC检定并行）

功能：
1. 调用独立小模型（deepseek-v4-flash）生成检索关键词
2. 并行查云向量库（CHAPTER+RUMOR / NPC_MEMORY / TASK）
3. 去重合并
4. 失败时返回空文本，主循环自动降级到被动检索

不动现有 cloud_memory_v2.py 任何代码，仅调用其 get_relevant_history 接口。
"""

import os
import json
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
load_dotenv()

from cloud_memory_v2 import get_relevant_history, MemoryCategory

# ========== 配置（优先用 ACTIVE_RETRIEVAL_* 独立配置，未设则降级到主循环DEEPSEEK配置） ==========
try:
    from config import DEEPSEEK_API_KEY as _FALLBACK_KEY
    from config import DEEPSEEK_BASE_URL as _FALLBACK_URL
    from config import DEEPSEEK_MODEL as _FALLBACK_MODEL
except ImportError:
    _FALLBACK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    _FALLBACK_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    _FALLBACK_MODEL = "deepseek-v4-flash"

_API_KEY = os.getenv("ACTIVE_RETRIEVAL_API_KEY", "") or _FALLBACK_KEY
_BASE_URL = os.getenv("ACTIVE_RETRIEVAL_BASE_URL", "") or _FALLBACK_URL
_MODEL = os.getenv("ACTIVE_RETRIEVAL_MODEL", "") or "deepseek-v4-flash"

_MAX_GROUPS = 3
_L4_TOP_K = 2
_NPC_TOP_K = 2
_QUEST_TOP_K = 2
_MIN_SCORE = 0.40
_THINKING_TIMEOUT = 15
_MAX_NPC_LINES = 4  # 注入L4-1的主动NPC记忆条数上限
_MAX_L4_LINES = 5   # 注入L4-2的主动剧情/任务条数上限

# 条目前缀（[维度] 或 "1." 序号，可任意组合），去重key计算时剥离
_PREFIX_RE = re.compile(r'^(?:(?:\[[^\]]+\]|\d+\.|[📜📋📰])\s*)+')
# 行首序号前缀，如 "1. "
_NUM_PREFIX_RE = re.compile(r'^\d+\.\s*')

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=_API_KEY, base_url=_BASE_URL)
    return _client


# ========== 小模型 tool 定义 ==========
_RETRIEVE_TOOL = {
    "type": "function",
    "function": {
        "name": "retrieve_cloud_memory",
        "description": "检索云向量记忆库。根据当前局面生成2-3组关键词。",
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "检索关键词，多个用空格分隔"
                            },
                            "dimension": {
                                "type": "string",
                                "description": "检索维度",
                                "enum": ["人物记忆", "剧情回忆", "任务线索", "武功经历", "地点回忆"]
                            }
                        },
                        "required": ["query", "dimension"]
                    },
                    "description": "2-3组检索关键词，每组聚焦一个维度"
                }
            },
            "required": ["queries"]
        }
    }
}

_THINKING_PROMPT = """你是一个游戏记忆检索助手。根据当前局面，从云向量记忆库中检索历史信息。

记忆库包含：玩家过往剧情摘要、NPC记忆、任务记录。

【近3轮剧情】
{recent_context}

【玩家本轮行动】
{player_input}

【活跃NPC】
{active_npcs}

请调用 retrieve_cloud_memory 工具生成检索关键词。要求：
1. 给出2-3组关键词，每组聚焦一个维度
2. 主动联想：玩家没提到但可能需要的记忆（如NPC上次见面的情景、某武功习得经历、某地点探索历史）
3. 不要超过3组
4. 关键词要具体（人名+事件，而非单独的"刀法"）
5. 你必须调用 retrieve_cloud_memory 工具，不要用文字回答
"""


def _build_thinking_prompt(recent_context, player_input, active_npcs):
    """单遍正则替换占位符（str.format 遇到玩家输入含花括号会抛 KeyError）"""
    mapping = {
        "recent_context": (recent_context or "无")[:300],
        "player_input": (player_input or "")[:200],
        "active_npcs": ", ".join(active_npcs) if active_npcs else "无",
    }
    return re.sub(
        r"\{(recent_context|player_input|active_npcs)\}",
        lambda m: mapping[m.group(1)],
        _THINKING_PROMPT,
    )


def _call_thinking_model(recent_context, player_input, active_npcs):
    """调用小模型生成检索关键词"""
    client = _get_client()
    prompt = _build_thinking_prompt(recent_context, player_input, active_npcs)

    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": "你是游戏记忆检索助手。请调用 retrieve_cloud_memory 工具。只调用工具，不要输出其他内容。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=800,
        top_p=1.0,
        stream=False,
        timeout=_THINKING_TIMEOUT,
        tools=[_RETRIEVE_TOOL],
        tool_choice="auto",
        extra_body={"thinking": {"type": "disabled"}},
    )
    msg = resp.choices[0].message
    content = msg.content or ""
    if not content and hasattr(msg, 'reasoning_content'):
        content = msg.reasoning_content or ""
    result = {"content": content}
    if msg.tool_calls:
        result["tool_calls"] = msg.tool_calls
    return result


def _search_one_group(query, slot_id=None, known_npcs=None, cancel_event=None):
    """执行单组关键词的云向量检索（3个分类查询，支持取消）"""
    results = {"l4": "", "npc": "", "quest": "", "l4_count": 0, "npc_count": 0, "quest_count": 0}
    uid = slot_id or os.environ.get("CLOUD_MEM_SLOT_ID", "default_player_XSFH6")

    def _cancelled():
        return cancel_event is not None and cancel_event.is_set()

    if _cancelled():
        return results

    try:
        l4_result = get_relevant_history(
            user_id=uid,
            query=query[:100],
            top_k=_L4_TOP_K,
            min_score=_MIN_SCORE,
            category_filter=[MemoryCategory.CHAPTER, MemoryCategory.RUMOR],
        )
        results["l4"] = l4_result or ""
        results["l4_count"] = len([l for l in (l4_result or "").split("\n") if re.match(r'^\d+\.', l.strip())])
    except Exception:
        pass

    if _cancelled():
        return results

    # NPC记忆检索：只查白名单内的已知NPC名，避免把普通词（如"剑法""华山派"）当人名浪费配额
    try:
        tokens = [n.strip() for n in query.split() if len(n.strip()) >= 2]
        known_set = set(known_npcs or [])
        npc_names = [t for t in tokens if t in known_set][:2]
        npc_texts = []
        for name in npc_names:
            if _cancelled():
                break
            mem = get_relevant_history(
                user_id=uid,
                query=f"{name} {query}",
                top_k=_NPC_TOP_K,
                min_score=_MIN_SCORE,
                category_filter=[MemoryCategory.NPC_MEMORY],
            )
            if mem and "暂无" not in mem:
                npc_texts.append(mem)
        results["npc"] = "\n".join(npc_texts) if npc_texts else ""
        results["npc_count"] = len(npc_texts)
    except Exception:
        pass

    if _cancelled():
        return results

    try:
        quest_result = get_relevant_history(
            user_id=uid,
            query=query[:100],
            top_k=_QUEST_TOP_K,
            min_score=_MIN_SCORE,
            category_filter=[MemoryCategory.TASK],
        )
        results["quest"] = quest_result or ""
        results["quest_count"] = len([l for l in (quest_result or "").split("\n") if re.match(r'^\d+\.', l.strip())])
    except Exception:
        pass

    return results


def _deduplicate(texts):
    """按前30字去重（key先剥离 [维度]/序号 前缀，避免同内容不同维度被判为不同条目）"""
    if not texts:
        return ""
    seen = set()
    deduped = []
    for text in texts:
        key = _PREFIX_RE.sub('', text.strip())[:30]
        if key and key not in seen:
            seen.add(key)
            deduped.append(text)
    return "\n---\n".join(deduped)


def _try_parse_closed(s):
    """尝试闭合未闭合括号并解析；无法安全闭合时返回 None"""
    s = s.strip()
    if not s:
        return None
    stack = []
    in_str = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif ch == ']' and stack and stack[-1] == '[':
            stack.pop()
    if in_str:
        return None
    while s and s[-1] in ',: \t\r\n':
        s = s[:-1].rstrip()
    if not s:
        return None
    for ch in reversed(stack):
        s += '}' if ch == '{' else ']'
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_truncated_json(raw):
    """修复被 max_tokens 截断的 JSON：逐字符回退 + 栈式闭合，可挽救前面已完成的条目"""
    fixed = (raw or "").strip()
    for _ in range(len(fixed)):
        parsed = _try_parse_closed(fixed)
        if parsed is not None:
            return parsed
        fixed = fixed[:-1]
    return None


def _parse_tool_call(resp):
    """解析小模型返回的tool call，提取检索关键词组"""
    if not resp or not resp.get("tool_calls"):
        return None

    tc = resp["tool_calls"][0]
    if hasattr(tc, 'function'):
        raw_args = tc.function.arguments
    else:
        raw_args = tc.get("function", {}).get("arguments", {})

    if isinstance(raw_args, str):
        try:
            tool_args = json.loads(raw_args)
        except json.JSONDecodeError:
            tool_args = _repair_truncated_json(raw_args)
            if tool_args is None:
                return None
    else:
        tool_args = raw_args

    if not isinstance(tool_args, dict):
        return None

    queries = tool_args.get("queries", [])
    if not queries:
        single = tool_args.get("query", "")
        if single:
            queries = [{"query": single, "dimension": "综合"}]

    valid = [
        q for q in queries
        if isinstance(q, dict) and isinstance(q.get("query"), str) and q.get("query")
    ][:_MAX_GROUPS]
    return valid if valid else None


def active_retrieve_cloud(recent_context, player_input, active_npcs, slot_id=None, known_npcs=None, cancel_event=None):
    """
    主动检索云向量库（入口函数）

    参数：
      recent_context: 近3轮剧情文本（str）
      player_input: 本轮玩家输入（str）
      active_npcs: 活跃NPC名列表（list[str]，用于小模型提示词）
      slot_id: 云向量库slot_id（str，可选，默认读环境变量）
      known_npcs: 已知NPC全名列表（list[str]，NPC记忆检索白名单，None则跳过NPC检索）
      cancel_event: threading.Event（可选，置位后在检查点中止；已发出的HTTP请求无法中断）

    返回：
      {
        "text": "合并后的检索结果文本（可直接注入prompt）",
        "count": 总条数,
        "groups": [{"dimension":..., "query":..., "count":...}],
        "error": None 或 错误信息
      }
    失败时 text="" count=0，主循环自动降级。
    """
    t0 = time.time()
    print(f"[主动检索] 启动，模型={_MODEL}")

    def _cancelled():
        return cancel_event is not None and cancel_event.is_set()

    # Step 1: 小模型生成关键词
    try:
        resp = _call_thinking_model(recent_context, player_input, active_npcs)
    except Exception as e:
        print(f"[主动检索] 小模型调用失败，降级: {e}")
        return {"text": "", "count": 0, "groups": [], "error": str(e)}

    if _cancelled():
        print("[主动检索] 已取消（小模型返回后），降级")
        return {"text": "", "count": 0, "groups": [], "error": "cancelled"}

    query_groups = _parse_tool_call(resp)
    if not query_groups:
        print(f"[主动检索] 小模型未生成有效关键词，降级")
        return {"text": "", "count": 0, "groups": [], "error": "no_keywords"}

    t1 = time.time()
    print(f"[主动检索] 小模型耗时: {t1-t0:.2f}s, 生成{len(query_groups)}组关键词")
    for g in query_groups:
        print(f"  [{g.get('dimension', '?')}] {g.get('query', '')}")

    # Step 2: 并行检索
    t2 = time.time()
    all_l4 = []
    all_npc = []
    all_quest = []
    raw_l4_lines = []
    raw_npc_lines = []
    raw_quest_lines = []
    group_details = []

    with ThreadPoolExecutor(max_workers=_MAX_GROUPS) as executor:
        future_map = {}
        for g in query_groups:
            q = g.get("query", "")
            if not q:
                continue
            future = executor.submit(_search_one_group, q, slot_id, known_npcs, cancel_event)
            future_map[future] = g

        for future in as_completed(future_map):
            g = future_map[future]
            try:
                r = future.result()
            except Exception as e:
                group_details.append({"dimension": g.get("dimension", "?"), "query": g.get("query", ""), "count": 0, "error": str(e)})
                continue

            if r["l4"]:
                all_l4.append(f"[{g.get('dimension', '?')}] {r['l4']}")
                raw_l4_lines.extend(r["l4"].split("\n"))
            if r["npc"]:
                all_npc.append(r["npc"])
                raw_npc_lines.extend(r["npc"].split("\n"))
            if r["quest"]:
                all_quest.append(r["quest"])
                raw_quest_lines.extend(r["quest"].split("\n"))
            group_details.append({
                "dimension": g.get("dimension", "?"),
                "query": g.get("query", ""),
                "count": r["l4_count"] + r["npc_count"] + r["quest_count"],
            })

    t3 = time.time()
    print(f"[主动检索] 并行检索耗时: {t3-t2:.2f}s")

    # Step 3: 去重合并
    merged_l4 = _deduplicate(all_l4)
    merged_npc = _deduplicate(all_npc)
    merged_quest = _deduplicate(all_quest)

    # Step 3.5: 结构化解析（NPC记忆 → L4-1；剧情/传闻/任务 → L4-2）
    npc_lines = _parse_npc_lines(raw_npc_lines)
    l4_lines = _parse_l4_lines(raw_l4_lines, raw_quest_lines)

    # 组装最终文本
    parts = []
    if merged_l4:
        parts.append(f"【主动检索·剧情线索】\n{merged_l4}")
    if merged_npc:
        parts.append(f"【主动检索·NPC记忆】\n{merged_npc}")
    if merged_quest:
        parts.append(f"【主动检索·任务线索】\n{merged_quest}")

    final_text = "\n\n".join(parts)
    final_count = sum(g.get("count", 0) for g in group_details)

    t_total = time.time() - t0
    print(f"[主动检索] 完成，共{final_count}条（NPC记忆{len(npc_lines)}条→L4-1，其余{len(l4_lines)}条→L4-2），总耗时{t_total:.2f}s")

    return {
        "text": final_text,
        "count": final_count,
        "npc_lines": npc_lines,
        "l4_lines": l4_lines,
        "groups": group_details,
        "error": None,
    }


def _parse_npc_lines(raw_lines):
    """
    把云向量NPC记忆原始行清洗为与被动L4-1一致的格式：
      "1. [npc_memory] 【胡一刀的记忆】xxx" → "【胡一刀的记忆】xxx"
    """
    seen = set()
    out = []
    for raw in raw_lines:
        clean = _NUM_PREFIX_RE.sub('', raw.strip())
        clean = re.sub(r'^\[[^\]]*\]\s*', '', clean)
        if not clean.startswith("【") or "的记忆】" not in clean:
            continue
        key = clean[:30]
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= _MAX_NPC_LINES:
            break
    return out


def _parse_l4_lines(raw_l4_lines, raw_quest_lines):
    """
    把剧情/传闻/任务原始行清洗为与被动L4-2一致的条目格式（保留[分类]标签）：
      "1. [chapter] xxx" → "[chapter] xxx"
    """
    seen = set()
    out = []
    for raw in list(raw_l4_lines) + list(raw_quest_lines):
        clean = _NUM_PREFIX_RE.sub('', raw.strip())
        if not clean:
            continue
        # 过滤检索输出的标题行/占位符（非真实条目）
        if clean.startswith("【相关历史线索】") or clean in ("暂无相关历史线索", "无相关历史线索"):
            continue
        key = _PREFIX_RE.sub('', clean)[:30]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(clean)
        if len(out) >= _MAX_L4_LINES:
            break
    return out


def merge_with_passive(passive_text, active_result, passive_npc_block=""):
    """
    将主动检索结果与被动检索结果分流合并：
      - NPC记忆 → 与被动L4-1去重后单独返回（格式：【XX的记忆】xxx，与被动一致）
      - 剧情/传闻/任务 → 与被动L4-2去重后，续接被动编号返回

    参数：
      passive_text: 被动L4-2检索结果文本（str）
      active_result: active_retrieve_cloud() 的返回值（dict）
      passive_npc_block: 被动L4-1的NPC记忆文本（str，用于去重，可省略）

    返回：
      {"l4": 合并后的L4-2文本, "npc": 追加到L4-1的NPC记忆文本（无则空串）}
      主动检索失败或无结果时，l4返回原被动文本，npc返回空串
    """
    if not active_result or active_result.get("error"):
        return {"l4": passive_text or "", "npc": ""}

    npc_lines = active_result.get("npc_lines") or []
    l4_lines = active_result.get("l4_lines") or []
    if not npc_lines and not l4_lines:
        return {"l4": passive_text or "", "npc": ""}

    # --- NPC记忆：与被动L4-1按前30字去重，格式不变 ---
    npc_keys = set()
    for line in (passive_npc_block or "").split("\n"):
        k = line.strip()[:30]
        if k:
            npc_keys.add(k)
    deduped_npc = []
    for line in npc_lines:
        k = line.strip()[:30]
        if k and k not in npc_keys:
            npc_keys.add(k)
            deduped_npc.append(line)

    # --- L4-2：去重 + 续接被动最大编号 ---
    passive_body = (passive_text or "").strip()
    if passive_body == "无相关历史线索":
        passive_body = ""

    l4_keys = set()
    max_num = 0
    for line in passive_body.split("\n"):
        s = line.strip()
        k = _PREFIX_RE.sub('', s)[:30]
        if k:
            l4_keys.add(k)
        m = _NUM_PREFIX_RE.match(s)
        if m:
            max_num = max(max_num, int(m.group(0).rstrip(". ")))

    new_entries = []
    for line in l4_lines:
        s = line.strip()
        k = _PREFIX_RE.sub('', s)[:30]
        if k and k not in l4_keys:
            l4_keys.add(k)
            new_entries.append(s)

    merged_l4 = passive_body
    if new_entries:
        numbered = "\n".join(f"{max_num + i + 1}. {l}" for i, l in enumerate(new_entries))
        merged_l4 = (passive_body + "\n" + numbered) if passive_body else numbered

    # 主动无新增时保持原被动文本（含"无相关历史线索"占位符）
    return {"l4": merged_l4 or (passive_text or ""), "npc": "\n".join(deduped_npc)}

