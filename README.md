# AI 武侠小说交互 RPG GAME

一个用大语言模型驱动的武侠互动小说。你扮演一名穿越到金庸世界的现代人，接下来想干什么都行——练功、行侠、报仇、寻宝，剧情全由 AI 实时生成，没有固定剧本。

开源免费，仅供学习交流。

## 能玩到什么

- 自由剧情生成：你说一句话，AI 接一段故事，怎么走由你
- 骰子检定：出招会掷 d20，好坏直接影响剧情走向，AI 不能自说自话
- 武功修炼：从初学入门一路练到破碎虚空，共 14 个境界
- 回合制战斗，可以跟 NPC 单挑
- 276 个 NPC，各有身份、性格、秘密和好感度，会记住你做过的事
- 世界书检索：两千多条世界设定按需注入，AI 不会瞎编设定
- 主线按原著桥段推进，也可以跳着玩
- 网页界面游玩，带地图、任务、装备等管理面板

## 跑起来需要什么

- Python 3.10 以上
- 一个 LLM API Key（DeepSeek 或任意 OpenAI 兼容接口都行）

可选：阿里云百炼 Key（云端长期记忆）、SiliconFlow Key（NPC 头像和剧情配图）。

## 部署

**1. 获取代码，装依赖**

```bash
git clone https://github.com/charnamel/ai-wuxia-novel-rpg.git
cd ai-wuxia-novel-rpg
python -m venv venv
venv\Scripts\activate        # Linux/macOS 用 source venv/bin/activate
pip install -r requirements.txt
```

核心依赖不大；语义检索那组（sentence-transformers，带 torch）体积较大，不装也能玩，游戏自动降级为纯关键词检索。

**2. 配置 API Key**

复制 `.env.example` 为 `.env`，填上密钥。最小配置只要两行：

```ini
MAIN_LOOP_A_API_KEY=sk-xxx
AUX_A_API_KEY=sk-xxx
```

主循环模型管剧情生成，辅助模型管状态提取和骰子判定，都是必填，可以用同一家。`.env.example` 里写了 DeepSeek 官方和 OpenCode Go 两套示例（后者一个密钥能调 deepseek-v4-flash、gpt-5.6-luna、grok-4.5 等多种模型），照着改就行。配图、云记忆之类的配置都是可选，不填照常跑。

**3. 预构建语义向量索引（可选，推荐）**

```bash
pip install sentence-transformers numpy
python build_semantic_index.py
```

首次联网下载中文 embedding 模型（约 95MB，已配国内镜像），全量编码 1~3 分钟，之后走缓存完全离线。跳过这步游戏也能玩，只是第一次触发语义检索会卡 30 秒到 2 分钟。

**4. 启动**

```bash
python run.py
```

浏览器打开 http://localhost:5000，创建角色就能玩了。手机连同一局域网也能访问。

**5. 服务器部署（可选）**

```bash
pip install gunicorn
gunicorn -w 1 -b 0.0.0.0:5000 --timeout 300 run:app
```

worker 只能开 1 个（游戏状态存在本地 JSON 里，多 worker 会互相覆盖）；timeout 给足 300 秒，AI 生成剧情慢。挂 Nginx 的话超时同样调上去。更详细的说明和常见问题见[部署指南](docs/01-部署指南.md)。

## 玩法

创建角色后，用一句话描述行动就行，比如"我在客栈里环顾四周"。

几个要点：

- 输入里提到武功（指名道姓，或者"运起内力"这种说法），会弹出骰子检定面板，确认后掷骰
- 检定优先用你点名的武功，其次是装备的内功轻功
- 跟 NPC 的互动会累积好感，好感影响态度和剧情走向
- 「回归主线」触发原著主线，玩完一段点「主线完成」再继续下一段
- 地图上选地点就可以出门游历

## 目录结构

核心代码 20 个 py 文件，主要的几个：

- `main.py` 主循环，剧情生成和状态更新都在这
- `web_server.py` Web 服务
- `dice_system.py` 骰子检定
- `battle_system.py` 战斗
- `worldbook.py` 世界书检索
- `player_manager.py` 玩家数据
- `data/` 静态游戏数据（NPC、武功、地图、主线等）

想深入了解，看 docs 目录：

- [部署指南](docs/01-部署指南.md)
- [世界书引擎](docs/02-世界书引擎.md)
- [本地语义向量检索](docs/03-本地语义向量检索.md)
- [游戏模块详解](docs/04-游戏模块详解.md)

## 致谢

本项目的骰子检定与 AI 跑团玩法设计，灵感来自 [DiceFrame](https://github.com/diceframe/diceframe) 项目，感谢它的启发。

## 版权说明

代码开源免费（MIT），仅供学习交流，不得商用。世界观和人物基于金庸小说的二次创作，相关版权归金庸先生及版权方所有。AI 生成内容仅供娱乐。
