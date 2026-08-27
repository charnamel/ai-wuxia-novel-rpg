# 语义向量检索部署文档

## 一、概述

本文档指导将世界书向量检索功能从本地开发环境部署到Ubuntu轻量云服务器，使用 **Xshell + SSH** 进行远程操作。

**功能简介**：在世界书现有的L1-L4关键词检索基础上，叠加L5语义向量检索层，使玩家能用自然语言（如"医书"、"会医术的人"）检索到相关条目，而不仅限于精确名称匹配。

**测试覆盖**：103个用例覆盖6大类JSON的各种组合（单类/双类/三类/四类+/长文本场景），物品类从0%提升到100%，平均检索约40ms。

---

## 二、服务器环境要求

| 项目 | 最低要求 | 推荐配置 |
|------|---------|---------|
| OS | Ubuntu 20.04+ | Ubuntu 22.04 LTS |
| Python | 3.10+ | 3.10 / 3.12（不要用3.13） |
| CPU | 2核 | 2核+ |
| 内存 | 2GB | 2GB+ |
| 磁盘 | 可用1GB | 2GB+ |

> **注意**：Python 3.13 与 torch 不兼容（C API 变更），务必使用 3.10 或 3.12。

---

## 三、部署前准备（本地）

### 3.1 确认本地代码已开发完成

本地需确认以下文件已就绪：

| 文件 | 说明 | 状态 |
|------|------|------|
| `semantic_index.py` | 语义向量检索模块（新增） | ✅ 已创建 |
| `worldbook.py` | 世界书主模块（修改3处：构建/L5检索/状态） | ✅ 已修改 |
| `data/*.json` | 6个数据源文件 | ✅ 已有 |

### 3.2 Xshell 连接配置

1. 打开 Xshell → 文件 → 新建会话
2. 填写连接信息：
   - **名称**：AI小说服务器（自定义）
   - **主机**：你的服务器公网IP
   - **端口**：22
   - **协议**：SSH
3. 用户身份验证：
   - **方法**：Password 或 Public Key
   - **用户名**：root（或你的用户名）
   - **密码**：你的服务器密码
4. 点击"连接"测试

### 3.3 确认服务器项目路径

SSH登录后确认项目路径（假设为 `/opt/ai_novel/`）：

```bash
ls /opt/ai_novel/
# 应能看到 main.py web_server.py worldbook.py data/ 等
```

如果路径不同，后续命令中替换 `/opt/ai_novel/` 为你的实际路径。

---

## 四、部署步骤（SSH操作）

### 4.1 上传代码到服务器

#### 方法A：Xshell + rz/sz（推荐，简单）

```bash
# SSH登录服务器后，安装lrzsz（如果未安装）
sudo apt install lrzsz -y

# 进入项目目录
cd /opt/ai_novel

# 上传文件（在Xshell终端输入rz，会弹出文件选择窗口）
rz
# 在弹窗中选择本地的 semantic_index.py、worldbook.py
```

#### 方法B：scp命令（在本地PowerShell执行）

```powershell
# 在本地 Windows PowerShell 中执行
scp "D:\code\AI_novel_simulatorNEW V4.0\semantic_index.py" root@服务器IP:/opt/ai_novel/
scp "D:\code\AI_novel_simulatorNEW V4.0\worldbook.py" root@服务器IP:/opt/ai_novel/
```

#### 方法C：Xftp拖拽（图形界面）

1. Xshell菜单 → 右键会话 → 用Xftp传输
2. 左侧本地选文件，右侧服务器拖拽上传

#### 方法D：git同步（如果项目在git仓库）

```bash
ssh root@服务器IP
cd /opt/ai_novel
git pull origin main
```

### 4.2 安装Python依赖

SSH登录服务器后执行：

```bash
# 确认Python版本（需3.10+，不要用3.13）
python3 --version

# 安装venv（如果之前没装）
sudo apt update
sudo apt install python3.10-venv -y

# 进入项目目录
cd /opt/ai_novel

# 激活虚拟环境（如果使用venv）
# source venv/bin/activate

# 安装torch（CPU版，体积小约200MB）和sentence-transformers
pip3 install torch --index-url https://download.pytorch.org/whl/cpu
pip3 install sentence-transformers numpy

# 验证安装
python3 -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('BAAI/bge-small-zh-v1.5')
vec = model.encode(['测试'])
print(f'安装成功，向量维度: {vec.shape}')
"
```

> **首次验证会下载模型（约95MB）**，如果网络慢请先设置镜像（见4.3）。

### 4.3 设置HuggingFace镜像（国内服务器必做）

```bash
# 设置环境变量（永久生效）
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
source ~/.bashrc

# 验证
echo $HF_ENDPOINT
# 应输出: https://hf-mirror.com
```

### 4.4 配置 .env 文件

在项目根目录的 `.env` 文件中添加语义检索配置：

```bash
cd /opt/ai_novel

# 追加配置到.env（如果文件不存在会自动创建）
cat >> .env << 'EOF'

# === 语义检索配置 ===
ENABLE_SEMANTIC_SEARCH=true
SEMANTIC_MODEL=BAAI/bge-small-zh-v1.5
SEMANTIC_MIN_SIMILARITY=0.45
SEMANTIC_SCORE_WEIGHT=2.0
EOF

# 验证配置
grep SEMANTIC .env
```

### 4.5 预构建向量缓存（重要！）

**首次运行需要编码2179条目，约30秒。** 建议部署时预构建，避免运行时卡顿：

```bash
cd /opt/ai_novel

python3 -c "
import worldbook
worldbook.init()
# 触发首次构建（含向量编码）
result = worldbook.search('测试')
print('向量索引预构建完成')
print(f'检索结果长度: {len(result) if result else 0} 字符')
"
```

看到以下输出表示成功：

```
[语义检索] ✅ 模型加载完成: BAAI/bge-small-zh-v1.5 (3.2s)
[语义检索] 编码 2179 条目...
[语义检索] ✅ 向量索引构建: 2179条, 30.5s, 4.2MB
[语义检索] ✅ 加载缓存向量: 2179条, 512维
```

预构建后会在 `data/` 目录生成两个缓存文件：

```bash
ls -la /opt/ai_novel/data/semantic_*
# semantic_vectors.npy  (4.2MB)
# semantic_ids.json     (0.03MB)
```

后续启动直接加载缓存（0.1秒），无需重新编码。

### 4.6 重启Web服务

```bash
cd /opt/ai_novel

# 如果用nohup运行
pkill -f web_server.py
nohup python3 web_server.py > server.log 2>&1 &

# 如果用systemd
sudo systemctl restart ai-novel

# 验证服务启动
sleep 2
tail -20 server.log
```

### 4.7 验证部署成功

```bash
# 方法1：检查Web API状态
curl http://localhost:5000/worldbook/status | python3 -m json.tool

# 期望输出包含：
# "semantic": {
#   "enabled": true,
#   "available": true,
#   "model": "BAAI/bge-small-zh-v1.5",
#   "vector_count": 2179,
#   "vector_dim": 512
# }
```

---

## 五、验证检索效果

部署完成后，在游戏网页顶栏查看「世界书检索」状态：`语义✅ N条向量` 即为正常。

开发期内部测试结论（供参考）：103个用例覆盖6大类JSON的单类/双类/三类/四类+/长文本组合，通过率约90%，平均检索约40ms。

---

## 六、配置参数说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ENABLE_SEMANTIC_SEARCH` | false | 语义检索总开关（true/false） |
| `SEMANTIC_MODEL` | BAAI/bge-small-zh-v1.5 | embedding模型名称 |
| `SEMANTIC_MIN_SIMILARITY` | 0.45 | 相似度门槛（0~1，越高越严格） |
| `SEMANTIC_SCORE_WEIGHT` | 2.0 | L5打分系数（越高语义权重越大） |

### 参数调优建议

| 场景 | MIN_SIMILARITY | SCORE_WEIGHT | 效果 |
|------|---------------|-------------|------|
| 默认（推荐） | 0.45 | 2.0 | 平衡召回率和精度 |
| 召回更多 | 0.35 | 2.5 | 更多结果，但可能有噪声 |
| 更精准 | 0.55 | 1.5 | 减少误召回，但可能漏掉 |
| 关闭语义 | — | — | 设ENABLE=false，纯L1-L4检索 |

---

## 七、安全降级机制

系统设计有3层降级保护，任何情况下不影响L1-L4检索：

```
第1层：ENABLE_SEMANTIC_SEARCH=false
  → 跳过L5，纯L1-L4检索

第2层：sentence-transformers未安装
  → ImportError，跳过L5

第3层：向量检索运行时异常
  → 返回空列表，L5不加任何分
```

**验证降级**：临时关闭语义检索

```bash
# 修改.env
sed -i 's/ENABLE_SEMANTIC_SEARCH=true/ENABLE_SEMANTIC_SEARCH=false/' .env

# 重启服务
pkill -f web_server.py
nohup python3 web_server.py > server.log 2>&1 &

# 验证L1-L4正常工作
python3 -c "
import worldbook
worldbook.init()
result = worldbook.search('屠龙刀')
print('L1-L4检索正常' if result else '异常')
"
```

---

## 八、内存与性能监控

### 8.1 检查内存占用

```bash
# 查看Python进程内存
ps aux | grep python | grep -v grep

# 或用top
top -p $(pgrep -f web_server.py)
```

预期内存占用：

| 组件 | 内存 |
|------|------|
| OS + Python运行时 | ~330MB |
| web_server + 应用 | ~100MB |
| BGE-small模型 | ~120MB |
| torch运行时 | ~150MB |
| 向量矩阵 | ~5MB |
| **总计** | **~705MB** |

2GB服务器剩余约1.3GB，安全。

### 8.2 检查检索延迟

```bash
# 计时测试
time python3 -c "
import worldbook
worldbook.init()
worldbook.search('医书')
"
```

预期：首次约30秒（编码），后续每次20-50ms。

### 8.3 检查磁盘占用

```bash
ls -lh /opt/ai_novel/data/semantic_*
du -sh ~/.cache/huggingface/
```

预期：
- semantic_vectors.npy: 4.2MB
- semantic_ids.json: 0.03MB
- HuggingFace模型缓存: ~95MB

---

## 九、常见问题排查

### Q1: 模型下载失败

```bash
# 确认镜像设置
echo $HF_ENDPOINT
# 应为: https://hf-mirror.com

# 如果未设置
export HF_ENDPOINT=https://hf-mirror.com
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"
```

### Q2: 内存不足（OOM）

```bash
# 检查可用内存
free -h

# 如果available < 500MB：
# 1. 确认没有其他大内存进程
ps aux --sort=-%mem | head -10
# 2. 考虑关闭其他不必要的服务
# 3. 或添加swap
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Q3: 向量缓存损坏

```bash
# 删除缓存，重新构建
rm /opt/ai_novel/data/semantic_vectors.npy
rm /opt/ai_novel/data/semantic_ids.json

# 重新预构建
cd /opt/ai_novel
python3 -c "import worldbook; worldbook.init(); worldbook.search('重建')"
```

### Q4: 检索结果为空

```bash
# 检查语义检索状态
python3 -c "
import worldbook
worldbook.init()
s = worldbook.get_status()
print('语义检索状态:', s.get('semantic'))
"

# 确认 enabled=true, available=true, vector_count>0
```

### Q5: Web端状态不显示语义检索

```bash
# 检查API返回
curl http://localhost:5000/worldbook/status

# 如果没有semantic字段：
# 1. 确认worldbook.py已更新
# 2. 确认semantic_index.py在项目根目录
# 3. 重启web_server
pkill -f web_server.py
nohup python3 web_server.py > server.log 2>&1 &
```

### Q6: Xshell连接断开导致进程退出

```bash
# 使用nohup或screen/tmux保持后台运行
# 方法1：nohup（推荐）
nohup python3 web_server.py > server.log 2>&1 &

# 方法2：screen
screen -S ai_novel
python3 web_server.py
# Ctrl+A 然后按D 脱离会话
# screen -r ai_novel 重新连接

# 方法3：tmux
tmux new -s ai_novel
python3 web_server.py
# Ctrl+B 然后按D 脱离会话
# tmux attach -t ai_novel 重新连接
```

---

## 十、升级与回滚

### 升级模型

```bash
# 修改.env
sed -i 's/SEMANTIC_MODEL=BAAI\/bge-small-zh-v1.5/SEMANTIC_MODEL=BAAI\/bge-base-zh-v1.5/' .env

# 删除旧缓存
rm data/semantic_vectors.npy data/semantic_ids.json

# 重新预构建
python3 -c "import worldbook; worldbook.init(); worldbook.search('升级')"
```

> **注意**：bge-base-zh-v1.5 模型约400MB，内存占用翻倍，2GB服务器慎用。

### 回滚（关闭语义检索）

```bash
# 修改.env
sed -i 's/ENABLE_SEMANTIC_SEARCH=true/ENABLE_SEMANTIC_SEARCH=false/' .env

# 重启服务
pkill -f web_server.py
nohup python3 web_server.py > server.log 2>&1 &

# 系统自动回退到纯L1-L4检索，无需删代码
```

---

## 十一、文件清单

| 文件 | 说明 | 操作 |
|------|------|------|
| `semantic_index.py` | 语义向量检索模块（新增） | 上传到服务器 |
| `worldbook.py` | 世界书主模块（修改3处） | 替换服务器上的 |
| `.env` | 环境配置（新增4行） | 追加配置 |
| `data/semantic_vectors.npy` | 向量缓存（自动生成） | 预构建时生成 |
| `data/semantic_ids.json` | ID缓存（自动生成） | 预构建时生成 |

---

## 十二、部署检查清单

在Xshell中逐项执行验证：

```bash
# 1. Python版本（需3.10+，非3.13）
python3 --version

# 2. 依赖安装
python3 -c "import torch; print('torch:', torch.__version__)"
python3 -c "import sentence_transformers; print('sentence-transformers: OK')"

# 3. 镜像配置
echo $HF_ENDPOINT  # 应为 https://hf-mirror.com

# 4. .env配置
grep ENABLE_SEMANTIC_SEARCH .env  # 应为 true

# 5. 代码文件
ls -la semantic_index.py worldbook.py

# 6. 向量缓存
ls -la data/semantic_vectors.npy  # 应为 4.2MB
ls -la data/semantic_ids.json

# 7. Web服务运行
curl -s http://localhost:5000/worldbook/status | grep -o '"available": [a-z]*'
```

---

## 十三、快速部署命令汇总（一键复制）

以下命令可在Xshell中依次执行：

```bash
# ====== 1. 进入项目目录 ======
cd /opt/ai_novel

# ====== 2. 上传代码（用rz，或用scp从本地传） ======
# rz  # 弹窗选择 semantic_index.py worldbook.py

# ====== 3. 安装依赖 ======
pip3 install torch --index-url https://download.pytorch.org/whl/cpu
pip3 install sentence-transformers numpy

# ====== 4. 设置镜像 ======
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
source ~/.bashrc

# ====== 5. 配置.env ======
cat >> .env << 'EOF'

# === 语义检索配置 ===
ENABLE_SEMANTIC_SEARCH=true
SEMANTIC_MODEL=BAAI/bge-small-zh-v1.5
SEMANTIC_MIN_SIMILARITY=0.45
SEMANTIC_SCORE_WEIGHT=2.0
EOF

# ====== 6. 预构建向量缓存 ======
python3 -c "import worldbook; worldbook.init(); worldbook.search('预热'); print('预构建完成')"

# ====== 7. 重启服务 ======
pkill -f web_server.py
nohup python3 web_server.py > server.log 2>&1 &
sleep 3

# ====== 8. 验证 ======
curl -s http://localhost:5000/worldbook/status | python3 -m json.tool | grep -A5 semantic
```

---

## 十四、Xshell常用快捷操作

| 操作 | 快捷键/命令 | 说明 |
|------|------------|------|
| 复制 | 鼠标选中即复制 | Xshell默认选中即复制 |
| 粘贴 | 鼠标右键 | 粘贴剪贴板内容 |
| 上传文件 | `rz` | 弹出文件选择窗口 |
| 下载文件 | `sz 文件名` | 下载到本地 |
| 新建标签 | Ctrl+T | 多标签页操作 |
| 切换标签 | Ctrl+Tab | 切换标签页 |
| 全屏 | Alt+Enter | 切换全屏模式 |
| 查找 | Ctrl+F | 在终端输出中查找 |

---

*文档版本：v2.0 | 更新日期：2026-08-10 | 测试用例：103个*
