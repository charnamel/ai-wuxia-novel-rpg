# AI互动武侠小说游戏

一款基于大语言模型（LLM）驱动的中文武侠互动小说游戏。你将扮演一名熟读小说的现代大学生，穿越到金庸武侠世界，自由行走江湖——练功、闯荡、结交豪杰、卷入恩怨情仇。所有剧情由 AI 实时生成，每一次选择都会改变你的江湖命运。

本项目为**开源免费游戏**，仅供学习交流使用。

## 核心特性

- **AI 实时剧情生成**：主循环剧情由 LLM 驱动，无固定剧本，自由度极高
- **D&D 风格骰子检定**：武功出招触发 d20 检定，DC 由 AI 根据场景动态判定，8 档结果分级（大成功→大失败）
- **武功修炼体系**：14 个修为境界（初学入门→破碎虚空），武功品阶加成，瓶颈突破机制
- **内功/轻功增幅检定**：出招时自动匹配套路（名词匹配 → 装备槽 → 最强武功），内功轻功催动攻击加成
- **回合制战斗系统**：与 NPC 对战，逐回合出招，AI 承接打斗叙事，战局智能分析
- **276 个 NPC 智能体**：每个 NPC 拥有独立身份、性格、秘密、好感度与记忆，会记住与你的每次互动
- **多层记忆系统**：50 轮细节累加窗口（缓存友好设计，命中厂商 Prompt Cache 省钱）+ 最新 2 章概要（每 50 轮一章）+ 全局剧情脉络（每 100 轮融合更新）+ 云端向量记忆按需检索，长剧情不遗忘也不爆上下文
- **世界书检索引擎**：六大数据源（NPC/武功/地图/门派/物品/主线）关键词倒排索引，按需注入上下文
- **主线动态演化**：江湖大势、势力格局随剧情推进实时变化
- **Web 可视化界面**：浏览器中游玩，含角色属性编辑器、地图系统、任务面板、战斗弹窗

## 环境要求

- Python 3.10+
- 一个 LLM API Key（支持 DeepSeek / MiMo 等任意 OpenAI 兼容接口）
- （可选）阿里云百炼 API Key —— 开启云端长期记忆
- （可选）SiliconFlow API Key —— 开启 NPC 头像与剧情配图生成

## 快速部署

### 1. 获取项目

```bash
git clone https://github.com/charnamel/ai-wuxia-interactive-novel.git
cd ai-wuxia-interactive-novel
```

### 2. 安装依赖

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

> 语义检索依赖（sentence-transformers）体积较大，缺失时程序自动降级，不影响游玩。

### 3. 配置 API Key

```bash
copy .env.example .env    # Linux/macOS 用 cp
```

编辑 `.env`，至少填写一处 LLM 配置：

```ini
# 主循环模型（剧情生成，必填其一）
MAIN_LOOP_A_API_KEY=你的API密钥
MAIN_LOOP_A_BASE_URL=https://api.deepseek.com
MAIN_LOOP_A_MODEL=deepseek-chat

# 辅助模型（状态提取，可用同一家）
AUX_A_API_KEY=你的API密钥
AUX_A_BASE_URL=https://api.deepseek.com
AUX_A_MODEL=deepseek-chat
```

`.env.example` 内置两组方案示例：**DeepSeek 官方** 与 **OpenCode Go 聚合网关**（一个密钥调用 deepseek-v4-flash / gpt-5.6-luna / grok-4.5 等多种模型）。任意 OpenAI 兼容端点均可（数眼科技、OpenRouter、本地 Ollama 等），改 `BASE_URL` 和 `MODEL` 即可。

### 4. 预构建语义向量索引（可选，推荐）

启用本地语义检索（世界书 L5 层）可获得更好的检索效果：

```bash
pip install sentence-transformers numpy
python build_semantic_index.py
```

首次运行联网下载中文 embedding 模型（约 95MB，已配置国内镜像），全量编码约 1~3 分钟。跳过本步游戏也可正常游玩（自动降级为纯关键词检索）。

### 5. 启动游戏

```bash
python run.py
```

浏览器访问 **http://localhost:5000**

### 6. 服务器部署（可选）

```bash
pip install gunicorn
gunicorn -w 1 -b 0.0.0.0:5000 --timeout 300 run:app
```

> 建议 worker 数为 1（游戏状态存于本地 JSON 文件，多 worker 会冲突）。

## 开始游戏

1. 打开网页后，点击**创建角色**，填写姓名、出身、初始能力
2. 用一句话描述你的行动（如"我在客栈里环顾四周"、"我运起内力一掌拍向山贼"）
3. AI 生成剧情后继续输入行动，自由推进故事

### 玩法提示

- **出招触发检定**：输入中提到武功名（如"独孤九剑"）或类型词（"一剑刺出"、"运起内力"、"施展轻功"）会触发骰子检定面板，确认后掷骰，结果影响剧情走向
- **检定加成**：主动点名武功 > 装备的内功/轻功 > 你修炼最深的武功；内功轻功会为攻击提供增幅
- **好感度**：与 NPC 互动（施恩/冒犯）会累积好感，影响 NPC 对你的态度与剧情分支
- **修炼**：战斗与历练中获得武功经验，境界从"初学入门"一路升至"破碎虚空"
- **探索**：通过地图系统前往不同地域，触发各地主线剧情与随机事件

## 项目结构

```
├── run.py                  # 启动入口
├── build_semantic_index.py # 语义向量索引预构建工具（可选）
├── web_server.py           # Flask Web 服务（API + 路由）
├── main.py                 # 主循环（剧情生成、工具调用解析）
├── dice_system.py          # 骰子检定系统（DC判定、增幅、约束文本）
├── battle_system.py        # 回合制战斗系统
├── player_manager.py       # 玩家数据（境界、武功、经验）
├── worldbook.py            # 世界书检索引擎（六大数据源关键词索引）
├── mainline_dynamic.py     # 主线动态演化
├── cloud_memory_v2.py      # 云端向量记忆（阿里云百炼）
├── task_manager.py         # 任务系统
├── semantic_index.py       # 本地语义向量检索（可选）
├── image_generator.py      # AI 配图生成
├── equipment_manager.py    # 装备管理
├── practice_system.py      # 修炼系统
├── save_manager.py         # 存档管理
├── file_utils.py           # 文件读写工具
├── location_time.py        # 地点/时辰管理
├── llm_utils.py            # LLM 返回值解析
├── config.py               # 配置中心（从 .env 读取密钥）
├── data/                   # 静态游戏数据
│   ├── npc_agents.json     # NPC 档案（276人）
│   ├── mainline_catalog.json   # 主线剧情目录
│   ├── map_data.json       # 世界地图
│   ├── martial_arts_bonus.json# 武功品阶表
│   ├── items_catalog.json  # 物品目录（870+）
│   └── ...
├── docs/                   # 详细文档
│   ├── 01-部署指南.md
│   ├── 02-世界书引擎.md
│   ├── 03-本地语义向量检索.md
│   ├── 04-游戏模块详解.md
│   └── 05-网页界面与指令指南.md
├── static/                 # 前端资源（含276张NPC头像）
└── templates/              # 页面模板
```

## 详细文档

想深入了解系统设计，请阅读 [docs/](docs/) 目录：

- [网页界面与指令指南](docs/05-网页界面与指令指南.md) —— 玩家操作手册：按钮功能、对战/存档/调试指令写法、骰子检定触发
- [部署指南](docs/01-部署指南.md) —— 环境准备、依赖安装、服务器部署、常见问题
- [世界书引擎](docs/02-世界书引擎.md) —— 六大数据源、L1~L5 五层检索打分、字数配额机制
- [本地语义向量检索](docs/03-本地语义向量检索.md) —— embedding 原理、向量缓存、增量更新、降级链
- [游戏模块详解](docs/04-游戏模块详解.md) —— 19 个模块逐一解析（主循环/记忆/骰子/战斗/成长/任务）
- [本地向量存储与检索总览](docs/07-本地向量存储与检索总览.md) —— 两套向量系统（世界书语义层 + 长期记忆库）的设计思路、部署步骤、维护注意事项

## 配置说明

所有密钥通过 `.env` 配置，详见 `.env.example`：

| 配置项 | 用途 | 必填 |
|--------|------|------|
| `MAIN_LOOP_*` | 主循环剧情生成模型 | 是 |
| `AUX_*` | 辅助状态提取模型 | 是 |
| `IMG_GEN_*` | 剧情配图生成模型 | 否 |
| `DASHSCOPE_API_KEY` | 阿里云百炼（云端记忆） | 否 |
| `KOLORS_IMG_API_KEY` | SiliconFlow（NPC头像） | 否 |
| `ENABLE_SEMANTIC_SEARCH` | 本地语义检索 | 否（默认开） |

## 版权与免责声明

- 本项目为**开源免费游戏**，代码仅供学习交流，不得用于商业用途
- 游戏世界观与人物基于金庸武侠小说的二次创作，相关版权归金庸先生及版权方所有
- AI 生成内容仅供娱乐，不构成任何事实陈述
- 使用本项目产生的任何后果由使用者自行承担

## License

MIT
