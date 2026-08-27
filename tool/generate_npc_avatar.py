#!/usr/bin/env python3
"""
Agnes Image 2.0 Flash API NPC头像生成脚本
当前免费 ($0/张)，OpenAI兼容格式

用法 (在项目根目录运行):
  python tools/generate_npc_avatar.py <NPC姓名> "<提示词>"

示例:
  python tools/generate_npc_avatar.py 张三 "Chinese traditional colorful ink wash painting portrait of a young warrior"

也可以批量生成:
  python tools/generate_npc_avatar.py --batch npc_list.json

npc_list.json 格式:
  [
    {"name": "张三", "prompt": "portrait description..."},
    {"name": "李四", "prompt": "portrait description..."}
  ]
"""

import sys
import json
import base64
import os
import time
import requests
from PIL import Image
import io

# ============ 配置区 ============
API_URL = "https://apihub.agnes-ai.com/v1/images/generations"
API_KEY = "sk-GGKsc6sd21r1KN5IkAyCL9lIfXBU9yZ9Zhc5felpP7x5ToEG"
MODEL = "agnes-image-2.1-flash"
IMAGE_SIZE = "1024x1024"  # API生成尺寸
OUTPUT_SIZE = 180          # 最终输出尺寸 (后端会缩放为28x28)
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "images", "npcs")
MAX_RETRY = 3              # 最大重试次数（含首次）
RETRY_DELAY = 3            # 每次重试间隔秒数
# ================================


def call_api(prompt):
    """调用Agnes图片生成API，返回图片二进制数据（失败自动重试）"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "size": IMAGE_SIZE,
        "return_base64": True,
    }

    for attempt in range(1, MAX_RETRY + 1):
        try:
            print(f"  调用API中{'(第%d次)' % attempt if attempt > 1 else ''}...", end="", flush=True)
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=120)
            if not resp.ok:
                print(f"  API错误 {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
            result = resp.json()
            print(" 完成")
            break
        except Exception as e:
            if attempt < MAX_RETRY:
                print(f"  失败: {e}，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
            else:
                raise

    if not result.get("data"):
        raise ValueError(f"API返回异常: {result}")

    item = result["data"][0]

    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])

    if item.get("url"):
        print(f"  从URL下载...", end="", flush=True)
        img_resp = requests.get(item["url"], timeout=60)
        img_resp.raise_for_status()
        print(" 完成")
        return img_resp.content

    raise ValueError(f"未找到图片数据: {result}")


def process_image(image_data, output_path):
    """处理图片：缩放至180x180，白色背景转透明，保存为PNG"""
    img = Image.open(io.BytesIO(image_data))

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    img = img.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)

    # 白色背景转透明
    data = list(img.getdata())
    new_data = []
    for item in data:
        r, g, b, a = item
        if r > 230 and g > 230 and b > 230:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, a))
    img.putdata(new_data)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG")


def generate_one(name, prompt):
    """生成单个NPC头像"""
    output_path = os.path.join(OUTPUT_DIR, f"{name}.png")
    print(f"[{name}]")

    try:
        image_data = call_api(prompt)
        process_image(image_data, output_path)
        print(f"  已保存: {output_path}")
        return True
    except Exception as e:
        print(f"  失败: {e}")
        return False


def batch_generate(json_path):
    """批量生成"""
    with open(json_path, "r", encoding="utf-8") as f:
        npc_list = json.load(f)

    success = 0
    failed = 0
    for npc in npc_list:
        name = npc["name"]
        prompt = npc["prompt"]
        ok = generate_one(name, prompt)
        if ok:
            success += 1
        else:
            failed += 1

    print(f"\n批量完成: 成功 {success}, 失败 {failed}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            print("用法: python generate_npc_avatar.py --batch <json文件路径>")
            sys.exit(1)
        batch_generate(sys.argv[2])
    else:
        if len(sys.argv) < 3:
            print("用法: python generate_npc_avatar.py <NPC姓名> <提示词>")
            sys.exit(1)
        name = sys.argv[1]
        prompt = sys.argv[2]
        generate_one(name, prompt)


if __name__ == "__main__":
    main()
