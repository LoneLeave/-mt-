# Claude Code 历史对话交接文档（游戏脚本 / 安装包逆向）

本目录把 Claude Code（`~/.claude/projects/` 下的 JSONL 会话）里关于「游戏脚本开发」和「安装包逆向关注点」的内容，整理成可直接复用的中文交接文档。所有结论均来自会话原文与本地代码/配置的核对，未在对话中出现的内容会明确标注「对话中未提及」。

## 一、文档索引

| 文档 | 用途 | 主要面向 |
|---|---|---|
| [game-script.md](./game-script.md) | 游戏脚本开发全貌：OAS 阴阳师线、自研 mtbot 线、模板匹配线；环境、命令、坐标坑、踩坑修复、未完成项 | 继续写/修脚本 |
| [reverse-notes.md](./reverse-notes.md) | 安装包逆向：样本结构、Unity/YooAsset 解包、LBIX 配置表、数值机制、逆向重点检查清单 | 继续分析安装包 |

## 二、来源会话（已采用）

| 会话文件 | 大小 | 主题 | 采用章节 |
|---|---|---|---|
| `C:\Users\123\.claude\projects\E--Reverse\2f73d9b2-9d16-4875-bf96-1a49317f8d7f.jsonl` | 605 MB / 31501 行 | ①APK 逆向分析与数值挖掘 ②《我叫MT：崛起》mtbot 自动化脚本（E:\Reverse\auto_script） | reverse-notes 主体 + game-script 的 mtbot 章节 |
| `C:\Users\123\.claude\projects\E--Reverse\d89e8cea-7b94-4b9f-8036-5b582976472c.jsonl` | 59 MB / 3086 行 | ①Unity 美术资源导出 ②基于模板匹配的游戏脚本（E:\DailyIdea\游戏脚本框架） | reverse-notes 解包章节 + game-script 的模板匹配章节 |
| `C:\Users\123\.claude\projects\E--DailyIdea\9c74a3b8-fbc6-4f03-9571-18dfb5c2e7c3.jsonl` | 138 MB | OAS 巡检/自动重启/微信告警、Ollama+OpenClaw 本地模型、MT 脚本早期版本 | game-script 的「OAS 运维与巡检」章节 |

## 三、已查看但不采用（判定依据）

| 会话 | 判定 |
|---|---|
| `E--Reverse` 之外：`D--code-Buddy\*`（a647f529、e4a6409e、e676745c、0d8de19e、03067615、d854acc8 等） | 内容是因果学习/概念表示/CAW-CCL 论文项目，关键词命中属误报，与游戏脚本/逆向无关 |
| `D--AI-KnowledgeBase\d77ae31d…` | 知识库检索，无关 |
| `D--code-ResearchTow\2c2a006a…`、`D--RearchData-Article-Try-Fansy\ab454fa0…` | 论文/研究项目，无关 |
| `E--DSinfer\e2aeaea8…` | 仅询问 DeepInfer 项目用途，无关 |
| `E--DailyIdea\fc557559…` | 提取到的 user 文本为空（无有效对话内容），未采用 |
| `C--Users-123\bb8bce08…`、`C--Users-123\3b1eb283…` | 仅两条「Reply with exactly OK」的探针会话，无关 |

## 四、主题概览（30 秒版）

- **游戏脚本有两条独立产品线**：
  1. **OAS（阴阳师）**：成熟开源框架，已在本机长期运行（`c:\Users\123\Desktop\game\OnmyojiAutoScript-easy-install`），有既定调度、日志、任务模块；可用但存在若干已定位的 bug 与运维冲突点。
  2. **mtbot（《我叫MT：崛起》）**：从零自研，位于 `E:\Reverse\auto_script`，已重构为 OAS 式分层架构（26 个任务 + Tkinter GUI + OAS 风格日志），核心难点是「Unity 无 UI 树 → 像素判读 + 坐标长按」。
  3. **模板匹配版（《我叫MT：崛起》）**：位于 `E:\DailyIdea\游戏脚本框架`，用解包出来的原始 Sprite 做模板，是 mtbot 之外的另一条路线（也是 mtbot 的移植来源之一）。
- **逆向的核心对象**是《我叫MT：崛起》渠道包 `com.wjmtjq1.ma.android`（v1.1.6，Unity 2022.3.62f3 + IL2CPP + XLua + YooAsset），保护几乎为零：资源 bundle 明文、Lua 明文、DLL 标准 .NET、`global-metadata.dat` 未加密。
- **可复用的最大资产**是解包产物：`E:\Reverse\export\`（7,903 个美术/音频/模型文件、Catalog.csv、README）与 `E:\Reverse\export\GameData\`（3,338 个配置/脚本/DLL 文件），以及 `E:\Reverse\tools\` 里的扫描/导出脚本。

## 五、如何继续使用

1. 先看主题对应的单篇文档，再按其中的「关键路径」直接打开代码或产物。
2. 恢复工作前先确认模拟器占用：OAS 与 mtbot 共用同一个 MuMu 实例（`127.0.0.1:16384`），同一时刻只能有一个在前台跑目标游戏。
3. 逆向侧不要重复造轮子：解包已做完，直接从 `E:\Reverse\export\GameData` 读数值，从 `E:\Reverse\tools\` 复用脚本。
4. 文档中的「对话中未提及」项，是当时没有验证/没有讨论的部分，不要当作已知事实。

> 合规边界（对话中反复确认，沿用即可）：只操作自己的模拟器与账号；不买真钱商品；不做内存修改、协议伪造、GM 指令、检测对抗。
