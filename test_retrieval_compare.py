"""
主动检索 vs 被动检索 质量对比测试程序 v4

核心策略：
- 世界书：始终被动检索（本地关键词匹配，快且精准）
- 云向量库(XSFH6)：对比被动 vs 主动检索质量
  - 被动：直接用玩家输入查向量库
  - 主动：小模型生成关键词 → 并行查向量库 → 去重 → 校验

优化清单：
1. 移除 novel_node 污染
2. 并行执行3组检索
3. 结果去重
4. 控制检索总数
5. 二次校验（json_mode）
6. 加入近期剧情摘要
"""

import json, os, sys, time, re
from dotenv import load_dotenv
load_dotenv()

os.environ["CLOUD_MEM_SLOT_ID"] = "default_player_XSFH6"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import CLOUD_MEM_SLOT_ID, COMMON_TIMEOUT
CLOUD_MEM_SLOT_ID = os.environ["CLOUD_MEM_SLOT_ID"]

LLM_API_KEY = os.getenv("MAIN_LOOP_A_API_KEY", "")
LLM_BASE_URL = os.getenv("MAIN_LOOP_A_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("MAIN_LOOP_A_MODEL", "deepseek-v4-flash")

from worldbook import search as wb_search, get_status as wb_status
from cloud_memory_v2 import get_relevant_history, MemoryCategory
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

_client = None

# ========== 全局控制 ==========
MAX_GROUPS = 3
WB_TOP_K = 8
WB_MAX_CHARS = 1000
L4_TOP_K = 3
NPC_TOP_K = 2
QUEST_TOP_K = 2

# 云向量检索的数据源（主动检索专用）
CLOUD_SOURCES = ["l4_memory", "npc_memory", "quests"]
# 被动检索的全部数据源
ALL_SOURCES = ["worldbook"] + CLOUD_SOURCES


def call_llm(sys_prompt, user_prompt, temp=0.2, tools=None, max_tokens=500, timeout=30, json_mode=False):
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    kwargs = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temp,
        "max_tokens": max_tokens,
        "top_p": 1.0,
        "stream": False,
        "timeout": timeout,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = _client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    content = msg.content or ""
    if not content and hasattr(msg, 'reasoning_content'):
        content = msg.reasoning_content or ""
    result = {"content": content}
    if msg.tool_calls:
        result["tool_calls"] = msg.tool_calls
    return result


# ========== 主动检索 tool（仅云向量库）==========
RETRIEVE_TOOL = {
    "type": "function",
    "function": {
        "name": "retrieve_cloud_memory",
        "description": "检索云向量记忆库（玩家历史剧情、NPC记忆、任务记录）。根据当前局面生成2-3组关键词，聚焦不同维度。",
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
                                "description": "检索关键词，多个用空格分隔，聚焦一个维度"
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

THINKING_PROMPT_TEMPLATE = """你是一个游戏记忆检索助手。根据当前局面，判断需要从云向量记忆库中检索哪些历史信息。

记忆库包含：玩家过往剧情摘要、NPC记忆（NPC对玩家的印象）、任务记录。

【近期剧情摘要】
{recent_summary}

【上一轮剧情（L1）】
{l1_scene}

【玩家本轮行动】
{player_input}

【活跃NPC】
{active_npcs}

请调用 retrieve_cloud_memory 工具生成检索关键词。要求：
1. 给出2-3组关键词，每组聚焦一个维度
2. 主动联想：玩家没提到但可能需要的记忆（如某NPC上次见面的情景、某武功的习得经历、某地点的探索历史）
3. 不要超过3组
4. 关键词要具体（人名+事件，而非单独的"刀法"）
5. 你必须调用 retrieve_cloud_memory 工具，不要用文字回答
"""


def call_thinking_model(scenario):
    prompt = THINKING_PROMPT_TEMPLATE.format(
        recent_summary=scenario.get("recent_summary", "无")[:200],
        l1_scene=scenario.get("l1_scene", "无")[:300],
        player_input=scenario["player_input"],
        active_npcs=", ".join(scenario.get("active_npcs", [])) or "无",
    )
    try:
        response = call_llm(
            sys_prompt="你是游戏记忆检索助手。请调用 retrieve_cloud_memory 工具。只调用工具，不要输出其他内容。",
            user_prompt=prompt,
            temp=0.2,
            tools=[RETRIEVE_TOOL],
            max_tokens=800,
            timeout=30,
        )
        return response
    except Exception as e:
        print(f"  [ERROR] 小模型调用失败: {e}")
        return None


# ========== 检索执行 ==========
def search_worldbook(query):
    """世界书检索（被动专用）"""
    wb_result = wb_search(query, top_k=WB_TOP_K, max_chars=WB_MAX_CHARS)
    count = len([
        l for l in (wb_result or "").split("\n")
        if l.strip() and l.strip().startswith("【")
        and not re.match(r'^【[①②③④⑤⑥⑦⑧⑨⑩]', l.strip())
    ])
    return wb_result or "", count


def search_cloud(query, top_k_l4=L4_TOP_K, top_k_npc=NPC_TOP_K, top_k_quest=QUEST_TOP_K):
    """云向量库检索（被动/主动共用）"""
    results = {}

    # L4：章节摘要 + 江湖见闻
    try:
        l4_result = get_relevant_history(
            user_id=CLOUD_MEM_SLOT_ID,
            query=query,
            top_k=top_k_l4,
            min_score=0.40,
            category_filter=[MemoryCategory.CHAPTER, MemoryCategory.RUMOR],
        )
        results["l4"] = l4_result or ""
        results["l4_count"] = len([l for l in (l4_result or "").split("\n") if re.match(r'^\d+\.', l.strip())])
    except Exception as e:
        results["l4"] = ""
        results["l4_count"] = 0

    # NPC记忆
    try:
        npc_names = [n.strip() for n in query.split() if len(n.strip()) >= 2]
        npc_results = []
        for name in npc_names[:3]:
            mem = get_relevant_history(
                user_id=CLOUD_MEM_SLOT_ID,
                query=f"{name} {query}",
                top_k=top_k_npc,
                min_score=0.40,
                category_filter=[MemoryCategory.NPC_MEMORY],
            )
            if mem and "暂无" not in mem:
                npc_results.append(mem)
        results["npc"] = "\n".join(npc_results) if npc_results else ""
        results["npc_count"] = len(npc_results)
    except Exception as e:
        results["npc"] = ""
        results["npc_count"] = 0

    # 任务
    try:
        quest_result = get_relevant_history(
            user_id=CLOUD_MEM_SLOT_ID,
            query=query,
            top_k=top_k_quest,
            min_score=0.40,
            category_filter=[MemoryCategory.TASK],
        )
        results["quest"] = quest_result or ""
        results["quest_count"] = len([l for l in (quest_result or "").split("\n") if re.match(r'^\d+\.', l.strip())])
    except Exception as e:
        results["quest"] = ""
        results["quest_count"] = 0

    return results


def deduplicate_cloud(texts):
    """云向量结果去重：按前30字去重"""
    if not texts:
        return ""
    seen = set()
    deduped = []
    for text in texts:
        key = text.strip()[:30]
        if key and key not in seen:
            seen.add(key)
            deduped.append(text)
    return "\n---\n".join(deduped)


# ========== 被动检索 ==========
def passive_retrieve(scenario):
    """被动检索：世界书+云向量库，全用玩家输入"""
    print(f"\n  [被动检索] 使用玩家输入: '{scenario['player_input'][:40]}'")
    t0 = time.time()

    # 世界书（被动）
    wb_text, wb_count = search_worldbook(scenario["player_input"])

    # 云向量库（被动）
    cloud = search_cloud(scenario["player_input"])

    t1 = time.time()
    cloud_total = cloud["l4_count"] + cloud["npc_count"] + cloud["quest_count"]

    return {
        "worldbook": wb_text,
        "worldbook_count": wb_count,
        "l4_memory": cloud["l4"],
        "l4_count": cloud["l4_count"],
        "npc_memory": cloud["npc"],
        "npc_count": cloud["npc_count"],
        "quests": cloud["quest"],
        "quest_count": cloud["quest_count"],
        "cloud_total": cloud_total,
        "time": t1 - t0,
        "group_details": [],
    }


# ========== 主动检索（仅云向量库）==========
def active_retrieve_cloud(scenario):
    """主动检索：小模型生成关键词 → 并行查云向量库 → 去重 → 校验"""
    print(f"\n  [主动检索] 调用小模型生成检索关键词...")

    # Step 1: 小模型生成关键词
    t0 = time.time()
    resp = call_thinking_model(scenario)
    t1 = time.time()
    print(f"  [主动检索] 小模型耗时: {t1-t0:.2f}s")

    if not resp:
        return None, "小模型调用失败", [], 0

    tool_calls = resp.get("tool_calls")
    if not tool_calls:
        content = resp.get("content", "")
        print(f"  [主动检索] 小模型未使用tool call: {content[:200]}")
        return None, "小模型未使用tool call", [], 0

    # 解析 tool call
    tc = tool_calls[0]
    if hasattr(tc, 'function'):
        func = tc.function
        tool_name = func.name
        raw_args = func.arguments
        if isinstance(raw_args, str):
            try:
                tool_args = json.loads(raw_args)
            except json.JSONDecodeError:
                print(f"  [主动检索] JSON解析失败，尝试修复...")
                fixed = raw_args.strip()
                open_braces = fixed.count('{') - fixed.count('}')
                open_brackets = fixed.count('[') - fixed.count(']')
                fixed += ']' * open_brackets + '}' * open_braces
                try:
                    tool_args = json.loads(fixed)
                    print(f"  [主动检索] JSON修复成功")
                except:
                    return None, "JSON解析失败", [], 0
        else:
            tool_args = raw_args
    else:
        tool_name = tc.get("function", {}).get("name", "")
        tool_args = tc.get("function", {}).get("arguments", {})
        if isinstance(tool_args, str):
            try:
                tool_args = json.loads(tool_args)
            except:
                return None, "JSON解析失败", [], 0

    if tool_name != "retrieve_cloud_memory":
        return None, f"错误的tool: {tool_name}", [], 0

    query_groups = tool_args.get("queries", [])
    if not query_groups:
        single_query = tool_args.get("query", "")
        if single_query:
            query_groups = [{"query": single_query, "dimension": "综合"}]

    if not query_groups:
        return None, "参数为空", [], 0

    query_groups = query_groups[:MAX_GROUPS]
    for g in query_groups:
        print(f"    [{g.get('dimension', '?')}] {g.get('query', '')}")

    # Step 2: 并行检索云向量库
    t2 = time.time()
    all_l4_texts = []
    all_npc_texts = []
    all_quest_texts = []
    all_counts = {"l4": 0, "npc": 0, "quest": 0}
    group_details = []

    with ThreadPoolExecutor(max_workers=MAX_GROUPS) as executor:
        future_map = {}
        for group in query_groups:
            query = group.get("query", "")
            dimension = group.get("dimension", "未知")
            if not query:
                continue
            future = executor.submit(search_cloud, query)
            future_map[future] = {"query": query, "dimension": dimension}

        for future in as_completed(future_map):
            info = future_map[future]
            try:
                cloud = future.result()
            except Exception as e:
                group_details.append({
                    "dimension": info["dimension"], "query": info["query"],
                    "l4_count": 0, "npc_count": 0, "quest_count": 0, "error": str(e)
                })
                continue

            l4_text = cloud.get("l4", "")
            l4_count = cloud.get("l4_count", 0)
            npc_text = cloud.get("npc", "")
            npc_count = cloud.get("npc_count", 0)
            quest_text = cloud.get("quest", "")
            quest_count = cloud.get("quest_count", 0)

            all_counts["l4"] += l4_count
            all_counts["npc"] += npc_count
            all_counts["quest"] += quest_count

            if l4_text:
                all_l4_texts.append(f"[{info['dimension']}] {l4_text}")
            if npc_text:
                all_npc_texts.append(npc_text)
            if quest_text:
                all_quest_texts.append(quest_text)

            group_details.append({
                "dimension": info["dimension"], "query": info["query"],
                "l4_count": l4_count, "npc_count": npc_count, "quest_count": quest_count,
            })

    t3 = time.time()
    print(f"  [主动检索] 并行检索耗时: {t3-t2:.2f}s")

    # 去重
    merged_l4 = deduplicate_cloud(all_l4_texts)
    merged_npc = deduplicate_cloud(all_npc_texts)
    merged_quest = deduplicate_cloud(all_quest_texts)

    # 去重后重新计数
    final_l4_count = len([l for l in merged_l4.split("\n") if re.match(r'^\d+\.', l.strip())]) if merged_l4 else 0
    final_npc_count = len([l for l in merged_npc.split("\n") if "【" in l[:5]]) if merged_npc else 0
    final_quest_count = len([l for l in merged_quest.split("\n") if re.match(r'^\d+\.', l.strip())]) if merged_quest else 0

    cloud_total = final_l4_count + final_npc_count + final_quest_count
    print(f"  [主动检索] 去重后 {cloud_total} 条云向量结果")

    # Step 3: 二次校验
    cloud_preview = (merged_l4[:200] + "\n" + merged_npc[:200])[:400]
    verify_prompt = f"""请评估以下云向量记忆检索结果质量。返回JSON。

【当前局面】
玩家: {scenario['player_input'][:150]}
NPC: {', '.join(scenario.get('active_npcs', [])) or '无'}

【检索分组与命中】
{json.dumps(group_details, ensure_ascii=False)}

【记忆结果预览】
{cloud_preview}

只返回JSON：
{{"score": 1-10, "noise": ["无关维度名"], "reason": "简短分析"}}
"""
    print(f"  [主动检索] 二次校验...")
    t4 = time.time()
    verify_info = {"score": 0, "noise": [], "reason": "未校验"}
    try:
        verify_resp = call_llm(
            sys_prompt="你是检索质量评估器。直接输出JSON，不要输出任何分析或推理。第一个字符必须是{。",
            user_prompt=verify_prompt,
            temp=0.1,
            tools=None,
            max_tokens=400,
            timeout=15,
            json_mode=True,
        )
        t5 = time.time()
        print(f"  [主动检索] 校验耗时: {t5-t4:.2f}s")

        verify_text = verify_resp.get("content", "")
        verify_clean = re.sub(r'```(?:json)?\s*', '', verify_text).replace('```', '').strip()
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', verify_clean, re.DOTALL)
        if not json_match:
            first_brace = verify_clean.find('{')
            last_brace = verify_clean.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                json_str = verify_clean[first_brace:last_brace+1]
                try:
                    verify_info = json.loads(json_str)
                except:
                    pass
        else:
            try:
                verify_info = json.loads(json_match.group())
            except:
                pass
        print(f"  [主动检索] 校验: score={verify_info.get('score')}, noise={verify_info.get('noise', [])}")
    except Exception as e:
        print(f"  [主动检索] 校验失败: {e}")

    t_total = time.time() - t0
    status = f"score={verify_info.get('score', 0)}/10, {verify_info.get('reason', '')}"

    results = {
        "l4_memory": merged_l4,
        "l4_count": final_l4_count,
        "npc_memory": merged_npc,
        "npc_count": final_npc_count,
        "quests": merged_quest,
        "quest_count": final_quest_count,
        "cloud_total": cloud_total,
        "time": t_total,
        "group_details": group_details,
    }
    return results, status, group_details, cloud_total


# ========== 输出 ==========
def print_separator(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_cloud_results(results, label):
    """只打印云向量库结果"""
    if not results:
        print(f"  {label}: 无结果")
        return 0
    total = results.get("cloud_total", 0)
    print(f"  {label} - L4记忆: {results.get('l4_count', 0)} 条")
    print(f"  {label} - NPC记忆: {results.get('npc_count', 0)} 条")
    print(f"  {label} - 任务: {results.get('quest_count', 0)} 条")
    print(f"  {label} - 云向量总计: {total} 条")
    # 预览
    for key in ["l4_memory", "npc_memory", "quests"]:
        text = results.get(key, "")
        if text:
            preview = text[:150].replace("\n", " | ")
            print(f"  {label} - {key} 预览: {preview}...")
    return total


def print_wb_results(results, label):
    """只打印世界书结果"""
    count = results.get("worldbook_count", 0)
    text = results.get("worldbook", "")
    print(f"  {label} - 世界书: {count} 条")
    if text:
        preview = text[:150].replace("\n", " | ")
        print(f"  {label} - 世界书预览: {preview}...")
    return count


# ========== 数据加载 ==========
def load_recent_summary():
    cache_path = os.path.join(os.path.dirname(__file__), "data", "context_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        summary = cache.get("compressed_global_summary", "") or cache.get("last_plot_summary", "")
        return summary[:300] if summary else ""
    return ""


def load_scenarios():
    scenario_path = os.path.join(os.path.dirname(__file__), "data", "test_scenarios.json")
    if os.path.exists(scenario_path):
        with open(scenario_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        scenarios = []
        for item in raw:
            scenarios.append({
                "name": f"Round {item['round']}: {item['player_input'][:30]}",
                "player_input": item["player_input"],
                "l1_scene": item.get("l1_scene", ""),
                "active_npcs": item.get("active_npcs", []),
                "round": item["round"],
                "recent_summary": "",
            })
        return scenarios
    return []


def main():
    print_separator("云向量主动检索 vs 被动检索 v4")
    print(f"  小模型: {LLM_MODEL}")
    print(f"  云记忆ID: {CLOUD_MEM_SLOT_ID}")
    print(f"  策略: 世界书=被动 | 云向量=被动 vs 主动")
    print(f"  参数: L4 top_k={L4_TOP_K} | NPC top_k={NPC_TOP_K} | 最多{MAX_GROUPS}组并行")

    status = wb_status()
    print(f"  Worldbook: ready={status.get('ready')}, entries={status.get('entries_count')}")

    scenarios = load_scenarios()
    recent_summary = load_recent_summary()
    print(f"  近期摘要: {recent_summary[:80]}...")
    for s in scenarios:
        s["recent_summary"] = recent_summary
    print(f"  测试场景数: {len(scenarios)}")
    if not scenarios:
        return

    all_stats = []

    for i, scenario in enumerate(scenarios):
        print_separator(f"场景{i+1}/{len(scenarios)}: {scenario['name']}")
        print(f"  玩家输入: {scenario['player_input'][:100]}")
        print(f"  活跃NPC: {', '.join(scenario['active_npcs']) or '无'}")

        # === 被动检索（世界书 + 云向量）===
        print(f"\n  --- 被动检索（全部）---")
        t_start = time.time()
        passive_results = passive_retrieve(scenario)
        t_passive = passive_results["time"]
        wb_count = print_wb_results(passive_results, "被动")
        passive_cloud = print_cloud_results(passive_results, "被动")

        # === 主动检索（仅云向量）===
        print(f"\n  --- 主动检索（仅云向量）---")
        active_results, status_msg, group_details, active_cloud = active_retrieve_cloud(scenario)
        t_active = active_results["time"] if active_results else 0
        if active_results:
            print_cloud_results(active_results, "主动")
        else:
            print(f"  主动: 失败 ({status_msg})")

        # 分组详情
        if group_details:
            print(f"\n  主动检索分组详情:")
            for g in group_details:
                print(f"    [{g['dimension']}] '{g['query']}' → L4:{g.get('l4_count',0)} NPC:{g.get('npc_count',0)} Q:{g.get('quest_count',0)}")

        # 对比
        print_separator(f"场景{i+1} 对比")
        print(f"  世界书（被动）: {wb_count} 条")
        print(f"  云向量-被动: {passive_cloud} 条, {t_passive:.2f}s")
        print(f"  云向量-主动: {active_cloud} 条, {t_active:.2f}s")
        print(f"  主动评估: {status_msg}")
        print(f"  云向量差异: {active_cloud - passive_cloud:+d} 条")

        all_stats.append({
            "scenario": scenario["name"][:42],
            "round": scenario.get("round", 0),
            "wb_count": wb_count,
            "passive_cloud": passive_cloud,
            "active_cloud": active_cloud,
            "passive_time": round(t_passive, 2),
            "active_time": round(t_active, 2),
            "status": status_msg[:30],
            "group_count": len(group_details),
        })

    # 总结
    print_separator("总结报告")
    print(f"{'场景':<44} {'轮次':>5} {'WB':>4} {'云被动':>5} {'云主动':>5} {'被动s':>6} {'主动s':>6} {'分组':>4} {'评估':<30}")
    print("-" * 120)
    for s in all_stats:
        print(f"{s['scenario']:<44} {s['round']:>5} {s['wb_count']:>4} {s['passive_cloud']:>5} {s['active_cloud']:>5} {s['passive_time']:>5.2f}s {s['active_time']:>5.2f}s {s['group_count']:>4} {s['status']:<30}")

    # 统计
    pc_avg = sum(s["passive_cloud"] for s in all_stats) / len(all_stats)
    ac_avg = sum(s["active_cloud"] for s in all_stats) / len(all_stats)
    pt_avg = sum(s["passive_time"] for s in all_stats) / len(all_stats)
    at_avg = sum(s["active_time"] for s in all_stats) / len(all_stats)

    print(f"\n  云向量-被动平均: {pc_avg:.1f} 条/场景, {pt_avg:.2f}s/场景")
    print(f"  云向量-主动平均: {ac_avg:.1f} 条/场景, {at_avg:.2f}s/场景")
    if pc_avg > 0:
        print(f"  主动/被动条数比: {ac_avg/pc_avg:.2f}x")
    if pt_avg > 0:
        print(f"  主动/被动耗时比: {at_avg/pt_avg:.2f}x")


if __name__ == "__main__":
    main()
