import random
import requests
import re
import base64
import os
import time
import io
from PIL import Image
from colorama import init

# 独立 LLM 配置（不依赖 main 的 DEEPSEEK 通道，换渠道只改 config.py 的 IMG_GEN_*）
from config import IMG_GEN_API_KEY, IMG_GEN_BASE_URL, IMG_GEN_MODEL, IMG_GEN_TIMEOUT
# Kolors 图片生成 API（web 配图 + NPC头像）
from config import KOLORS_IMG_API_URL, KOLORS_IMG_API_KEY, KOLORS_IMG_MODEL, KOLORS_IMG_SIZE, KOLORS_PLOT_WIDTH, PLOT_IMG_CACHE_DIR

# 初始化控制台颜色
init(convert=True, autoreset=True)
class Color:
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    END = "\033[0m"

# 内置兜底ASCII模板（图文融合版本）
BACKUP_ASCII = {
    "restaurant": f"""{Color.YELLOW}
    ┌────────────┐
    │   【醉仙楼】 │
    │   ┌──────┐  │
    │   │  靠窗  │  │
    │   │  温酒  │  │
    │   └──────┘  │
    └────────────┘
{Color.END}""",
    "mountain": f"""{Color.GREEN}
        ▲        ▲
    ▲▲▲      ▲▲▲
 ▲▲▲▲▲    ▲▲▲▲▲
  ┌──────┐
  │ 剑 客 │
  └──────┘
{Color.END}""",
    "river": f"""{Color.CYAN}
 ~ ~  [ 渡 口 ]  ~ ~
 ~  ~~~~~~~~~~~  ~
 ~  一叶扁舟    ~
 ~ ~ ~ ~ ~ ~ ~ ~ ~
{Color.END}""",
    "temple": f"""{Color.RED}
   ┌────┐
   │ 古刹 │
┌──┴────┴──┐
│ 残 烛     │
└──────────┘
{Color.END}""",
    "fight": f"""{Color.RED}
    ╱|、        /|
  (˚ˎ 。7      / |
  |、˜〵      /  |
  じしˍ,)ノ  /___|
  ┌──────────┐
  │  杀 意    │
  └──────────┘
{Color.END}"""
}

def get_fallback_by_plot(plot: str):
    """根据剧情自动匹配兜底画面"""
    txt = plot.lower()
    if "打" in txt or "对战" in txt or "交手" in txt or "刀剑" in txt or "招式" in txt:
        return BACKUP_ASCII["fight"]
    elif "酒楼" in txt or "酒" in txt or "店小二" in txt:
        return BACKUP_ASCII["restaurant"]
    elif "山" in txt or "林" in txt or "剑" in txt:
        return BACKUP_ASCII["mountain"]
    elif "江" in txt or "渡口" in txt or "舟" in txt:
        return BACKUP_ASCII["river"]
    elif "庙" in txt or "古刹" in txt:
        return BACKUP_ASCII["temple"]
    return random.choice(list(BACKUP_ASCII.values()))

def draw_ascii(api_key: str = None, base_url: str = None, latest_plot: str = ""):
    """
    主函数：发送最新剧情，获取并打印“图文融为一体”的ASCII意境画
    独立通道：不传 api_key/base_url 时自动使用 config.img_gen_* 专属配置
    （原有位置传参调用方式完全兼容）
    """
    api_key = api_key or IMG_GEN_API_KEY
    base_url = base_url or IMG_GEN_BASE_URL
    plot_sub = latest_plot[:800] if len(latest_plot) > 800 else latest_plot

    # 【核心修改】彻底重写构图提示词，强制图文融合！
    prompt = f"""
根据以下武侠剧情，创作一幅【纯 ASCII 字符构成的世界】。

构图核心规则（非常重要）：
1. **文字必须作为图形的一部分融入画面中，严禁悬浮在顶部或底部！**
2. 示例引导：
   - 若场景在酒楼，用框线(+-|)组成画中的招牌、对联或牌匾，并在招牌框内写上“客栈”、“酒”或店名。
   - 若场景在打斗，将招式名称或“刀”、“剑”二字直接作为武器轮廓的一部分，或用飘动的横幅表现“杀意”。
   - 若场景在江边，用字符拼出渡口的石碑或船帆，并在其上刻下文字。
3. 画面主体使用 `@`, `#`, `%`, `*`, `+`, `=`, `.`, `:` 等字符表现明暗和轮廓。
4. 行数 15~20 行，宽度不超过 60 字符，严禁输出 markdown 代码块 ` ``` `。
5. 必须准确还原剧情的场景氛围，文字直接为场景服务。

剧情文本：
{plot_sub}
"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": IMG_GEN_MODEL,
        "messages": [
            {"role": "system", "content": "你是一位极其擅长“图文一体”的ASCII艺术画师，文字本身就是画面建筑的材质，你绝不单独在画外写注释。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.4,
        "max_tokens": 800,
        "stream": False  # <--- 【关键修复】加上这一行，保证返回完整的 JSON，不出错
    }
    art = get_fallback_by_plot(latest_plot)
    try:
        print(f"{Color.CYAN}正在 AI 生成剧情 ASCII 意境画面（图文一体）...{Color.END}")
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=IMG_GEN_TIMEOUT
        )
        resp.raise_for_status()
        res_json = resp.json()
        choices = res_json.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "").strip()
            if content:
                clean = content
                if "```" in clean:
                    clean = re.sub(r"```[a-zA-Z]*\n?([\s\S]*?)```", r"\1", clean).strip()
                if clean:
                    art = clean
                    
    except requests.exceptions.ReadTimeout:
        print(f"{Color.RED}AI 响应超时（25s），使用匹配剧情的兜底画面{Color.END}")
    except Exception as e:
        print(f"{Color.RED}API 生成失败：{str(e)}，使用内置画面{Color.END}")

    # 统一打印画面
    print(f"\n{Color.YELLOW}==================== 剧情 ASCII 画面 ===================={Color.END}")
    print(art)
    print(f"{Color.YELLOW}==========================================================\n{Color.END}")


def _build_plot_prompt(latest_plot: str) -> str:
    """根据剧情文字构建图片生成提示词（零 LLM 成本，纯模板拼装）"""
    plot_sub = latest_plot[:500] if len(latest_plot) > 500 else latest_plot
    txt = latest_plot
    # 场景判定（复用 get_fallback_by_plot 的关键词逻辑）
    if "打" in txt or "对战" in txt or "交手" in txt or "刀剑" in txt or "招式" in txt:
        scene = "刀光剑影的激烈武打交锋，飞沙走石，剑气纵横"
    elif "酒楼" in txt or "酒" in txt or "店小二" in txt:
        scene = "古色古香的武侠酒楼内景，木质桌椅，酒旗招展"
    elif "江" in txt or "渡口" in txt or "舟" in txt:
        scene = "烟波浩渺的江面渡口，一叶扁舟，远山如黛"
    elif "庙" in txt or "古刹" in txt:
        scene = "幽静深山的古刹禅院，残烛青烟，古木参天"
    elif "山" in txt or "林" in txt or "崖" in txt:
        scene = "崇山峻岭间的江湖行旅，云雾缭绕，险峰峭壁"
    elif "夜" in txt or "月" in txt:
        scene = "月色下的江湖夜行场景，清冷幽静"
    else:
        scene = "江湖行走的写意场景，古道西风"
    return (f"金庸武侠彩色水墨画风格插画，{scene}。"
            f"画面氛围参考以下剧情：{plot_sub}。"
            f"要求：彩色水墨晕染，意境深远，古典武侠美学，构图精美，无文字水印。")


def _generate_prompt_via_llm(latest_plot: str) -> str:
    """用 LLM（IMG_GEN_* 通道）把剧情提炼成英文画面提示词；失败返回 None，由调用方回退模板"""
    if not latest_plot or not latest_plot.strip():
        return None
    plot_sub = latest_plot[:500] if len(latest_plot) > 500 else latest_plot
    system_prompt = (
        "你是一位武侠题材插画导演。请根据提供的剧情文本，输出一段用于 AI 绘图工具的英文画面提示词。"
        "要求：1) 只输出提示词本身，不要任何解释、前缀或 markdown 代码块；"
        "2) 2-3 句英文，包含场景、人物动作、氛围、光线、色调；"
        "3) 主题为彩色水墨风格武侠插画（Chinese traditional colorful ink wash painting, wuxia style）；"
        "4) 输出控制在 80 个英文单词以内。"
    )
    user_prompt = f"剧情文本：\n{plot_sub}"
    headers = {
        "Authorization": f"Bearer {IMG_GEN_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": IMG_GEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 200,
        "stream": False,
    }
    try:
        print(f"{Color.CYAN}正在用 LLM 提炼画面提示词...{Color.END}")
        resp = requests.post(
            f"{IMG_GEN_BASE_URL}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=IMG_GEN_TIMEOUT,
        )
        resp.raise_for_status()
        res_json = resp.json()
        choices = res_json.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "").strip()
        if not content:
            return None
        # 清洗：去掉可能的 markdown 代码块包装和首尾引号
        if "```" in content:
            content = re.sub(r"```[a-zA-Z]*\n?([\s\S]*?)```", r"\1", content).strip()
        content = content.strip('"\'')
        return content
    except Exception as e:
        print(f"{Color.RED}LLM 提示词生成失败: {e}，回退模板{Color.END}")
        return None


def generate_plot_image(latest_plot: str):
    """
    调用硅基流动 Kolors 图片生成 API，根据剧情文字生成配图。
    成功返回 web 相对路径（如 /static/images/plot_cache/xxx.png），失败返回 None。
    提示词优先由 LLM 提炼剧情生成，LLM 失败时回退模板拼装（零 LLM 成本）。
    图片缩放至 KOLORS_PLOT_WIDTH 宽度以适配手机端显示。
    """
    if not latest_plot or not latest_plot.strip():
        print(f"{Color.RED}配图失败：剧情文本为空{Color.END}")
        return None

    prompt = _generate_prompt_via_llm(latest_plot) or _build_plot_prompt(latest_plot)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KOLORS_IMG_API_KEY}",
    }
    payload = {
        "model": KOLORS_IMG_MODEL,
        "prompt": prompt,
        "image_size": KOLORS_IMG_SIZE,
        "batch_size": 1,
        "num_inference_steps": 20,
        "guidance_scale": 7.5,
    }

    image_data = None
    for attempt in range(1, 4):  # 最多3次
        try:
            print(f"{Color.CYAN}正在调用 Kolors 生成剧情配图{'(第%d次)' % attempt if attempt > 1 else ''}...{Color.END}")
            resp = requests.post(KOLORS_IMG_API_URL, json=payload, headers=headers, timeout=300)
            resp.raise_for_status()
            result = resp.json()
            images = result.get("images", [])
            if not images or not images[0].get("url"):
                raise ValueError(f"API返回异常: {str(result)[:200]}")
            img_url = images[0]["url"]
            img_resp = requests.get(img_url, timeout=120)
            img_resp.raise_for_status()
            image_data = img_resp.content
            break
        except Exception as e:
            print(f"{Color.RED}Kolors 调用失败: {e}{Color.END}")
            if attempt < 3:
                time.sleep(3)
            else:
                return None

    if not image_data:
        return None

    # 缩放至适配手机的宽度后保存
    try:
        img = Image.open(io.BytesIO(image_data))
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        new_h = int(h * KOLORS_PLOT_WIDTH / w)
        img = img.resize((KOLORS_PLOT_WIDTH, new_h), Image.LANCZOS)

        os.makedirs(PLOT_IMG_CACHE_DIR, exist_ok=True)
        filename = f"{int(time.time() * 1000)}.png"
        output_path = os.path.join(PLOT_IMG_CACHE_DIR, filename)
        img.save(output_path, "PNG")
        web_path = f"/{PLOT_IMG_CACHE_DIR}/{filename}"
        print(f"{Color.GREEN}配图已生成({KOLORS_PLOT_WIDTH}x{new_h}): {web_path}{Color.END}")
        return web_path
    except Exception as e:
        print(f"{Color.RED}配图保存失败: {e}{Color.END}")
        return None