# -*- coding: utf-8 -*-
"""DC检定开关（ENABLE_DICE_SYSTEM）验证测试
验证：
1. dice_enabled() 三种取值解析（true/false/缺失）
2. .env 原子写入逻辑（无该行时自动追加）
运行：python tool/test_dice_toggle.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dice_system

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")


print("=== 1. dice_enabled() 取值解析 ===")

# 缺失 → 默认开启
os.environ.pop("ENABLE_DICE_SYSTEM", None)
check("缺失时默认开启", dice_system.dice_enabled() is True)

# 显式 true
for v in ("true", "TRUE", "True", "1"):
    os.environ["ENABLE_DICE_SYSTEM"] = v
    check(f"'{v}' → 开启", dice_system.dice_enabled() is True)

# 显式 false
for v in ("false", "FALSE", "False", "0", "off"):
    os.environ["ENABLE_DICE_SYSTEM"] = v
    check(f"'{v}' → 关闭", dice_system.dice_enabled() is False)

# 带空格
os.environ["ENABLE_DICE_SYSTEM"] = "  false  "
check("带空格 '  false  ' → 关闭", dice_system.dice_enabled() is False)

os.environ.pop("ENABLE_DICE_SYSTEM", None)

print("\n=== 2. .env 写入逻辑模拟（无该行自动追加） ===")

# 复现 web_server.py 的写入逻辑
def write_env_flag(env_path, new_val):
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("ENABLE_DICE_SYSTEM=") and not stripped.startswith("#"):
            lines[i] = f"ENABLE_DICE_SYSTEM={new_val}\n"
            found = True
            break
    if not found:
        lines.append(f"\n# ====== DC骰子检定开关 ======\nENABLE_DICE_SYSTEM={new_val}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


with tempfile.TemporaryDirectory() as td:
    env_path = os.path.join(td, ".env")

    # 场景A：env 无该行 → 追加
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("MAIN_LOOP_A_MODEL=test\n")
    write_env_flag(env_path, "false")
    content = open(env_path, encoding="utf-8").read()
    check("无该行时追加", "ENABLE_DICE_SYSTEM=false" in content)
    check("追加不影响原内容", "MAIN_LOOP_A_MODEL=test" in content)

    # 场景B：已有该行 → 替换
    write_env_flag(env_path, "true")
    content = open(env_path, encoding="utf-8").read()
    check("已有该行时替换为true", "ENABLE_DICE_SYSTEM=true" in content)
    check("替换后无重复行", content.count("ENABLE_DICE_SYSTEM=") == 1)

    # 场景C：注释行不算
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# ENABLE_DICE_SYSTEM=false\nOTHER=1\n")
    write_env_flag(env_path, "true")
    content = open(env_path, encoding="utf-8").read()
    check("跳过注释行（新增有效行）",
          "# ENABLE_DICE_SYSTEM=false" in content and "\nENABLE_DICE_SYSTEM=true" in content)

print(f"\n{'='*40}\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
