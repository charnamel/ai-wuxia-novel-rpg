#!/usr/bin/env python3
"""
批量NPC头像生成 - 硅基流动 Kolors
读取 batch_npc_avatars.json，跳过已有头像和别名(含括号)
限速：1张/分钟 (1 IPM)

用法 (在项目根目录运行):
  python tools/batch_generate_npc_kolors.py

支持中断后重新运行：已生成的会自动跳过。
"""

import json
import os
import sys
import time
import requests
from PIL import Image
import io

# ============ 配置区 ============
API_URL = "https://api.siliconflow.cn/v1/images/generations"
API_KEY = "sk-zekeikrcfndocdkaickayrjwghwldvvtwnpmmcbwapmuccir"
MODEL = "Kwai-Kolors/Kolors"
IMAGE_SIZE = "1024x1024"
OUTPUT_SIZE = 180

# 路径（相对于项目根目录）
JSON_FILE = "tools/batch_npc_avatars.json"
OUTPUT_DIR = "static/images/npcs"

# 限速
INTERVAL = 60  # 每张间隔秒数（1 IPM）
MAX_RETRY = 2  # 单张最大重试次数
# ================================


def call_api(prompt):
    """调用硅基流动 Kolors API，返回图片二进制数据"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "image_size": IMAGE_SIZE,
        "batch_size": 1,
        "num_inference_steps": 20,
        "guidance_scale": 7.5,
    }
    resp = requests.post(API_URL, json=payload, headers=headers, timeout=120)
    if not resp.ok:
        raise Exception(f"API {resp.status_code}: {resp.text[:300]}")
    result = resp.json()
    images = result.get("images", [])
    if not images or not images[0].get("url"):
        raise Exception(f"无图片数据: {str(result)[:200]}")
    img_resp = requests.get(images[0]["url"], timeout=60)
    img_resp.raise_for_status()
    return img_resp.content


def process_image(image_data, output_path):
    """缩放至180x180，白色背景转透明，保存PNG"""
    img = Image.open(io.BytesIO(image_data))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    img = img.resize((OUTPUT_SIZE, OUTPUT_SIZE), Image.LANCZOS)
    data = list(img.getdata())
    new_data = []
    for r, g, b, a in data:
        if r > 230 and g > 230 and b > 230:
            new_data.append((r, g, b, 0))
        else:
            new_data.append((r, g, b, a))
    img.putdata(new_data)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path, "PNG")


def main():
    # 切换到项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)

    # 加载 NPC 列表
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        npc_list = json.load(f)

    # 已有头像集合
    existing = set()
    if os.path.exists(OUTPUT_DIR):
        existing = set(os.path.splitext(f)[0]
                       for f in os.listdir(OUTPUT_DIR) if f.endswith(".png"))

    # 过滤：跳过已有、跳过含括号的别名
    to_generate = []
    skipped_alias = 0
    for item in npc_list:
        name = item["name"]
        if "(" in name or "（" in name:
            skipped_alias += 1
            continue
        if name in existing:
            continue
        to_generate.append(item)

    total = len(to_generate)
    print("=" * 60)
    print(f"批量NPC头像生成 - 硅基流动 Kolors")
    print(f"JSON总数: {len(npc_list)} | 已有头像: {len(existing)} | 别名跳过: {skipped_alias}")
    print(f"待生成: {total} | 限速: {INTERVAL}秒/张")
    print(f"预计耗时: {total * INTERVAL // 60} 分钟 ({total * INTERVAL / 3600:.1f} 小时)")
    print("=" * 60)
    print()

    if total == 0:
        print("所有NPC头像已生成完毕！")
        return

    success = 0
    failed = 0
    failed_names = []

    for i, item in enumerate(to_generate, 1):
        name = item["name"]
        prompt = item.get("prompt", f"Chinese ink wash painting portrait of {name}")
        output_path = os.path.join(OUTPUT_DIR, f"{name}.png")

        print(f"[{i}/{total}] {name}")
        print(f"  提示词: {prompt[:80]}...")

        ok = False
        for attempt in range(1, MAX_RETRY + 1):
            try:
                print(f"  调用API中{'(重试%d)' % attempt if attempt > 1 else ''}...", end="", flush=True)
                image_data = call_api(prompt)
                process_image(image_data, output_path)
                print(" 完成")
                ok = True
                break
            except Exception as e:
                print(f" 失败: {e}")
                if attempt < MAX_RETRY:
                    time.sleep(10)

        if ok:
            success += 1
        else:
            failed += 1
            failed_names.append(name)

        # 限速：等待 INTERVAL 秒（最后一张不等）
        if i < total:
            print(f"  等待 {INTERVAL} 秒...")
            time.sleep(INTERVAL)

    print()
    print("=" * 60)
    print(f"完成: 成功 {success}, 失败 {failed}, 总计 {total}")
    if failed_names:
        print(f"失败名单: {', '.join(failed_names)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
