# 游戏脚本开发交接文档

来源：`E--Reverse\2f73d9b2-9d16-4875-bf96-1a49317f8d7f.jsonl`（mtbot）、`E--Reverse\d89e8cea-7b94-4b9f-8036-5b582976472c.jsonl`（模板匹配框架）、`E--DailyIdea\9c74a3b8-fbc6-4f03-9571-18dfb5c2e7c3.jsonl`（OAS 运维与巡检）。
标注「对话中未提及」= 会话里没有可靠信息，不要当成事实。

---

## 0. 先看全局：本机同时有三套脚本

| 线 | 目标游戏 | 路径 | 状态 |
|---|---|---|---|
| OAS（开源成品） | 阴阳师 `com.netease.onmyoji.wyzymnqsd_cps` | `c:\Users\123\Desktop\game\OnmyojiAutoScript-easy-install` | 长期在用，任务调度正常，有已知 bug |
| mtbot（自研） | 《我叫MT：崛起》`com.wjmtjq.ma.android` | `E:\Reverse\auto_script` | 26 任务 + GUI，绝大部分真机跑通 |
| 模板匹配框架 | 同上 | `E:\DailyIdea\游戏脚本框架` | 21 任务跑通，后被 mtbot 参考/迁移 |

共享的物理资源是**同一个 MuMu Player 12 实例**（`127.0.0.1:16384`）。三套脚本不能同时抢前台——这是踩过很多次的坑。

---

## 1. 运行环境（已验证）

### 1.1 模拟器 / ADB
```
MuMu 12 主程序：D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuNxMain.exe
MuMuManager  ：D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe
adb          ：D:\Program Files\Netease\MuMu Player 12\shell\adb.exe
连接地址     ：127.0.0.1:16384
```
- 启停模拟器（对话中验证可用）：
  ```powershell
  MuMuManager.exe control -v 0 launch
  MuMuManager.exe control -v 0 shutdown
  MuMuManager.exe info -v 0
  ```
- 也可以 `MuMuManager.exe control --app launch --package-name <包名>`（对话中出现过 `app launch / clone / delete / setting` 子命令；`setting` 键包含 `mini_disk`、`system_disk_readonly`）。
- 模拟器重启后需要重新 `adb connect 127.0.0.1:16384`。

### 1.2 分辨率与截图
- 《我叫MT：崛起》分辨率 **720×1280**，density 240，游戏画面横向范围 x∈[28,691]。
- 阴阳师在前台时模拟器会转成 **1280×720 横屏**——这是为什么脚本必须做「前台/朝向守卫」。
- 截图方式：`adb exec-out screencap -p`（对话中使用的是 exec-out，避免 pull 的半包问题）。

### 1.3 Python 环境
- OAS：Python 3.10（README 标注）。
- mtbot / 逆向工具：`D:\anaconda\python.exe`；逆向另有一个 conda 环境 `C:/Users/123/.conda/envs/Reas/python.exe`（装了 UnityPy）。
- 入口统一用 `python -I` 运行，避免当前目录污染 sys.path。

---

## 2. OAS（阴阳师）线

### 2.1 关键路径
```
项目根   c:\Users\123\Desktop\game\OnmyojiAutoScript-easy-install
配置     config\oas1.json            （实例名 oas1）
日志     log\YYYY-MM-DD_oas1.txt     （如 log\2026-10-19_oas1.txt）
任务模块 tasks\<TaskName>\script_task.py （约 50 个：WantedQuests、RyouToppa、Orochi、Secret、Hunt、AbyssShadows、GuildBanquet、DemonRetreat、TalismanPass、RealmRaid、DemonEncounter、AreaBoss、GuildActivityMonitor …）
启动     server.py / oas-backend.bat / console.bat / oas.exe
```

### 2.2 配置要点（`config/oas1.json`，实际读取核对）
- 设备：`serial=127.0.0.1:16384`、`handle=MuMu安卓设备`、`package_name=com.netease.onmyoji.wyzymnqsd_cps`
- 截屏 `uiautomator2`，控制 `minitouch`，模拟器类型 `MuMuPlayer12`
- 调度：`restart.scheduler` 每天 `server_update=09:05:00`；各任务有 `enable / next_run / priority / success_interval / failure_interval`
- 日志里实际跑过的任务（`log\2026-10-19_oas1.txt` 可查）：Orochi、TalismanPass、WantedQuests、Restart、GuildActivityMonitor、Secret、WeeklyTrifles 等；完整启用情况以 `config\oas1.json` 各任务的 `enable / next_run / priority` 为准。
- 仓库现有日志行是老格式：`2026-10-19 00:01:12.289 | logger.py:0320 | INFO | [Task] Orochi (Enable, 5, ...)`。
- 会话中确立的目标日志格式（自研脚本直接照抄这套）：
  ```
  INFO     2026-10-29 09:11:59.677 │ [Task] WantedQuests (Enable, 5, 2026-10-29 11:40:47)
  INFO     2026-10-29 09:12:00.624 │ module_path: ...\tasks\GotoMain\script_task.py, module_name: script_task
  INFO     2026-10-29 09:12:00.672 │ <<< UI GOTO PAGE_MAIN >>>
  INFO     2026-10-29 09:12:01.614 │ [UI] page_main
  INFO     2026-10-29 09:12:04.606 │ [3.9s] Page arrived page_main
  ```

### 2.3 Web 服务与端口（有冲突，务必实机确认）
- `server.py` 用 uvicorn 起 `module.server.app:fastapi_app`，端口优先级：命令行 `--port` > `deploy` 配置 > 默认。
- 代码默认值：`deploy/config.py`、`deploy/template` 中 `WebuiPort = 22267`，`server.py` 兜底 22270。
- **对话中记录为 `http://127.0.0.1:22288`**（当时运行的实际端口）。→ 结论：以 `deploy/config` 或启动参数为准，文档里的三个数字都出现过。

### 2.4 已定位的 OAS bug 与绕过（已在仓库留备份文件）

| 问题 | 现象 | 根因（代码核对） | 处理 |
|---|---|---|---|
| Notifier 崩溃 | 任何错误触发通知时脚本直接死，`AttributeError: 'Notifier' object has no attribute 'required'` | `module/notify/notify.py` `__init__` 中 `provider_name is None` 时直接 `return`，后面的 `self.required = ...` 从未执行（第 34–42 行） | 配好 provider，或修复初始化顺序 |
| Task name mismatch | 从别的任务里调用「重启」被拒：`Task name mismatch: model=..., path=...` | `tasks/base_task.py` 校验 `model_task_name` 与 `path_task_name` 一致 | 现仓库已在 [base_task.py](file:///C:/Users/123/Desktop/game/OnmyojiAutoScript-easy-install/tasks/base_task.py#L83-L88) 加了豁免（`path_task_name != 'Restart'`），并留有 `base_task.py.bak_mismatch` 备份；另有 `script.py.bak_restart_skip` |
| 启停接口无效 | HTTP `GET` start/stop 调了没反应 | 路由里调用 async 方法没有 `await`（对话结论） | 改用 WebSocket `/ws/{name}` |
| 游戏掉登录 | OAS 退出，需人工点「进入游戏」 | 登录流程未被正确处理（对话结论） | 需在 `tasks/GlobalGame`/启动流程补「进入游戏」分支（对话中提到要修，仓库有 `script.py.bak_restart_skip`） |

其他用到的 OAS 接口（对话中出现）：
- `WebSocket /ws/{name}`（真正可用的启停）
- `/home/kill_server`
- `PUT /{script}/{task}/sync_next_run`

### 2.5 OAS 与其它脚本共存的硬规则（用户多次强调）
1. **阴阳师出问题，先在 OAS 内部重启阴阳师**，不要「关掉全部再重启全部」。
2. **任何重启阴阳师的动作都必须由 OAS 发起**，不要直接打开 MuMu 去点。
3. OAS 在跑时不要用别的脚本抢同一模拟器；mtbot 在启动时会检测前台包名，发现是阴阳师就直接中止（`ERROR：前台是 com.netease.onmyoji…`）。
4. 巡检工具的「自动重启」会把 MuMu 一起关掉——手工玩 MT 时必须临时关掉自动重启。

---

## 3. OAS 运维 / 巡检（微信告警）

路径（对话中实际建立）：
```
E:\DailyIdea\游戏脚本巡检\
├─ 每日巡检.cmd       # 计划任务入口
├─ 巡检一次.cmd       # 手动入口
├─ config.json        # 开关、Server酱³ key、重启策略
└─ 报告/归档（中文命名目录）
```

- **巡检频率**：高频巡检单次约 1.35 秒（不调模型）；计划任务每 10 分钟一次（面板可一键创建/删除）。
- **判定 → 修复链路**：检测 `script_inactive` / 任务长时间不推进 → 停 OAS → 关 OASX → 关 MuMu → 拉起模拟器 → 启动 OASX → 启动 `oas1` 任务 → 复检；完整链路实测 **54 秒**恢复 `ok`（早期版本约 70 秒）。
- **告警**：Server酱³，新接口格式
  ```
  https://<uid>.push.ft07.com/send/<sendkey>.send
  ```
  UID 可从 sendkey 前缀自动解析（当时为 `30056`）。免费额度有限；发送失败会在日志留 `sc3失败:...`，不会静默。
- **控制面板**：本地网页 `http://127.0.0.1:8765`（只监听本机），可开关自动重启/推送、立即巡检、生成日报、测试推送、打开最新报告，并显示最近 40 条动作记录。
- **本地模型（可选层）**：Ollama + OpenClaw；小模型（4b）用于文本播报，9b 与模拟器同跑会显存溢出，只适合夜间加载。模型只负责「读日志判状态、生成日报」，不做错误归因。
- **已知运维事故**：巡检自动重启撞上 MuMu 权限/残留进程，出现 `VERR_NEED_NO_ADMIN_ERROR`、多份 `MuMuNxDevice` 进程互相冲突 → 加了「进程堆积防护」；MuMu 主程序以管理员权限运行会加剧冲突。

---

## 4. mtbot（《我叫MT：崛起》自研脚本）

### 4.1 关键路径与命令
```
项目   E:\Reverse\auto_script
入口   E:\Reverse\auto_script\mt.py
包     E:\Reverse\auto_script\mtbot\
旧代码 legacy\      历史截图 archive\      导出产物/工具 E:\Reverse\export / E:\Reverse\tools
```

```powershell
python -I E:\Reverse\auto_script\mt.py --list
python -I E:\Reverse\auto_script\mt.py --task tower --boot
python -I E:\Reverse\auto_script\mt.py --profile daily
python -I E:\Reverse\auto_script\mt.py --profile full --boot --emulator
python -I E:\Reverse\auto_script\mt.py --profile full --rounds 3
python -I E:\Reverse\auto_script\mt.py --task mail --boot --cold
python -I E:\Reverse\auto_script\mt.py --gui
python -I E:\Reverse\auto_script\mt.py --dry-run --rounds 2
```
`--boot`=把游戏拉回前台并进主城；`--emulator`=允许拉起模拟器；`--cold`=冷启动（登录→公告→弹窗→主城）。

### 4.2 分层架构（重构后约 2731 行，思路对齐 OAS）

| 层 | 文件 | 职责 |
|---|---|---|
| 设备 | `device.py` `emulator.py` | adb 截图 / 长按点击 / 按键 / 前台检测；MuMuManager 启停。**不认识游戏** |
| 视觉 | `vision.py` `layout.py` | 像素判读 + `classify()` 画面状态枚举；**所有实测坐标集中在 layout** |
| UI | `ui.py` | 回主城、关弹窗（含红 X 偏移）、断线重连、登录流程 |
| 页面 | `pages.py` | MainCity / TrialsHub / Tower / Tree / Legend / Demon / Daily / Guild / Arena / Campaign… 每个有 `enter()` 和动作 |
| 任务 | `tasks/{combat,daily,reward}.py` | 26 个任务类，只调用页面与视觉 |
| 调度 | `scheduler.py` `config.py` `run.py` | 配置驱动、按优先级跑、逐任务隔离异常、状态记账 |

设计原则：**所有任务都是「看状态 → 做一个动作」的循环，可以从任意界面/任意进度开始，可重复运行（幂等）**。

### 4.3 画面状态机（vision）
枚举：`MAIN_CITY / MAIN_CITY_DIM / TITLE / TRIALS_HUB / DEPLOY / BATTLE / RESULT_TOWER / RESULT_TREE / RESULT_GENERIC / RESULT_LEGEND / RESULT_DEFEAT / QUIT_DIALOG / RECONNECT / RECONNECT_LOGIN / CONFIRM_DIALOG / DIALOG / UNKNOWN`

常用像素判据（对话中给出并实测）：
- 金币按钮：`R>=212, G>=150, R-B>=85`
- 红点角标：红色像素簇，`R>185, G<105, B<65, R-G>95`（与橙色按钮 ~(207,112,80) 区分）
- 共鸣等级（蓝字）：`B-R>40, B>150`，面积 ≥15px
- 主城天空：`B>210, 140<G<200, R<125`
- 标题页：`R>195, R-B>85 @ (360,1040)`
- 退出确认框：`(170,720)` 浅灰
- 战斗页：底部 5 张英雄卡至少 3 个亮 + 场地中部偏暗
- 胜利横幅：`(560,300)` 暖金 `R-B>80`；结算标题条 `(70,645)` 暖紫 + 暗色护栏 `(360,1050)`

### 4.4 坐标与输入（最容易翻车的地方）

| 现象 | 实测结论 |
|---|---|
| 点击「没反应」 | 游戏部分按钮**必须长按**：`adb shell input swipe x y x y 220ms`；50ms 的 `input tap` 常被忽略。统一用 **200–250ms** |
| 点偏 | 不是偏 30–50px，而是**底部按钮实际命中点比视觉中心低约 70px**：布阵页「一键上阵/战斗」视觉 y≈1160，真正可点 y≈1230 |
| 弹窗红 X | 红 X 实际命中点相对视觉中心偏移 **(-20, +10)** |
| 全屏促销/充值页 | **没有遮罩**，点空白无效，必须点左上/左下返回箭头（`(88,1215)` / `(88,1205)`） |
| Android BACK | 会弹「确认要退出游戏吗」——不要用 BACK 代替返回箭头 |
| 页签坐标改版 | 日常/周常/成就/历练四页签在改版后变窄为 `270 / 380 / 490 / 600`，旧代码点 `455 / 615 / 680` 等于没切页；勇士计划页签 y≈550（旧 y=505） |
| 地图被误判成战斗 | 主线地图底部整行金色「挑战NN-N」会被「底部亮像素」判据命中 → `BATTLE`，然后对着地图连点 12 分钟「跳过」。修法：底部 `(300,1055)(360,1055)(430,1055)` 三点全金 ⇒ 判定为地图，不是战斗 |

### 4.5 幂等/兜底（用户明确要求的兼容性）
- 所有「领取」类任务：已领过要能识别并跳过（按钮消失/变灰/红点消失）。
- 任何「未知画面」兜底：**连续 25 次认不出就停**（早期会空转 45 分钟看门狗）。
- 战斗中固定「跳过」：`press (655,900)`；结算页「保存」用「保存」模板而非固定坐标（不同玩法模板不同，公会试炼的保存按钮与公会圣兽不是同一张图）。
- 关闭弹窗只点「可确认」的：底部「点击空白处关闭」文字或右上角红叉，不要盲点聊天栏。
- 主线「等级不足」：当时是**推断**（进不了布阵就停），没有专门识别提示框（对话中未做模板）。

### 4.6 任务清单（26 个，已注册；含已删除项）
奖励/提升：邮件 `mail`、排行榜 `rank`、签到、商城免费礼包、千抽福利、战令、圣物（祝福 + 一键升级 + 升星 + 羁绊）、装备强化（一键50级 ↔ 一键升星循环，直到金币不足且无可升星）、英雄升级（**只升前 5 个实际出战英雄，且取等级最低者**，蓝字=共鸣等级不算）、助战升级（荣耀之书/天神传承/神器/战宠）、图鉴升级 `collection`、英雄羁绊 `hero_bond`
每日：日常/周常/成就/历练四页签 + 活跃度宝箱（25/50/75/100）、悬赏（接取至悬赏值 <1800）、公会捐献、商店、角斗场、公会试炼
战斗/历练：爬塔 `tower`、时光之树 `tree`、传奇试炼 `legend`、邪能神殿 `demon`、巨龙牢窟、地精宝藏 `goblin`、战役主线 `campaign`、公会圣兽 `beast`（12:00 后开放，每日 5 次）

**已删除**：达标返利（活动位置会变）、共鸣（用户要求删）。
**明确不做**：任何真钱商品（68 元/首充/累充/每日特惠）；需要人判断的付费项。

### 4.7 GUI（Tkinter，仿 OASX）
- 左栏：26 任务分组勾选（奖励/提升、每日、战斗历练），预设 `reward / daily / combat / full`，全选/全不选/反选，✓/✗ 显示上次结果
- 右上：双击任务按参数表生成表单（塔的「最多胜利层数/连续失败停止」、挂机「次数/钻石预算」、公会试炼「是否买次数/单价」），改完写回 `config.json`
- 右下：全局钻石预算、单任务超时
- 顶部：运行当前/运行选中/停止/打开日志目录 + 登录游戏/拉起模拟器/冷启动；「轮次」1–99（等价 `--rounds N`）
- 右侧状态卡：当前任务、当前界面（来自 `[UI] page_xxx`）、第 r/N 轮、队列进度条；「待执行队列」表格状态 等待→进行中→完成/失败（中断会收尾成「中断/未执行」）
- 美化素材直接用解包产物：`Art/.../UI2/bg/hero_details_back_3.jpg`、`Extra/Icon/ic_launcher_foreground.png`、`icon_zc_kfkh / icon_xsfl_ysz / icon_zc_kfgh`；预览图在 `docs/gui_preview.png`

### 4.8 日志格式（与 OAS 对齐，能定位到行）
```
INFO     2026-10-29 12:26:29.754 │ [Task] tower (Enable, 10, 2026-10-29 12:26:29)
INFO     2026-10-29 12:26:33.101 │ <<< UI GOTO PAGE_MAIN >>>
INFO     2026-10-29 12:26:35.402 │ [UI] main_city
DEBUG    2026-10-29 13:09:59.424 │ [mtbot/ui.py:31] press (200, 700) ms=220
WARN     2026-10-29 13:10:37.128 │ [mtbot/ui.py:205] 没能回到主城
INFO     2026-10-29 13:10:37.128 │ [mtbot/scheduler.py:104] 完成 1/1 个任务
```
GUI 有「显示点击调试」开关（默认关），默认不刷 DEBUG 点击行。

---

## 5. 模板匹配框架（E:\DailyIdea\游戏脚本框架）

这是一条与 mtbot 并行的路线：**用截图/原始素材做 OpenCV 模板匹配**，比纯像素判据更通用，但怕改版。

### 5.1 结构
```
E:\DailyIdea\游戏脚本框架\
├─ core\vision.py      # 模板匹配 + ROI + 多尺度 + alpha 蒙版
├─ tasks\_campaign.py  # 战役页公共逻辑（含 dismiss_popup）
├─ tasks\claim_gift_card.py / claim_level_reward.py / idle_reward.py / guild_beast.py / launch_game.py
├─ assets\             # 模板；旧模板备份 assets\_backup_20261027\
```

### 5.2 已验证的匹配经验
- 原始 Sprite 素材命中很准：主城图标 `icon_zjm_x_youjian`（邮件）、`icon_zjm_x_richang`（日常）、`icon_zjm_b_haoyou`（好友）、`icon_zhucheng_*` 在正确位置 **0.95–0.97**。
- **但同一素材在别的界面也会到 0.90+**（图标形状相似）→ 必须配 **ROI 限制区域**，否则误判。
- 识别层已支持**透明蒙版 + 多尺度**：`App` 增加 `roi` 参数且不改老调用行为；`find_all` 需透传 `max_results`（升级时漏过，已补）。
- **模板裁剪的坑（反复踩）**：
  - 把红点、数字、文字截进去 → 红点消失/数字变化就失效（实测 0.695 / 0.730 / 0.743）。
  - 把「免费」气泡截进去 → 气泡消失失效。
  - 用会变的按钮（「免费刷新」→「30 刷新」）当「面板已打开」的标志 → 标志失效；应改用**面板标题**。
  - 用场景碎片当弹窗提示条 → 干净战役页 0.96 但会误判。
- 做法：新模板必须**交叉验证**——只在对的界面命中（≈1.00），其他界面 ≤0.33；负样本自测 1.0 且不互串；裁完先在离线截图上跑一遍分数。

### 5.3 具体修复（可直接照抄）
- `_campaign.py` 新增 `dismiss_popup()`：进战役页后只关能确认的弹窗（底部「点击空白处关闭」文字 / 右上角红叉），不再误点聊天栏。
- `claim_gift_card.py`：入口改固定点 `(100,300)`，用「通关福利」标题确认面板打开（换英雄也不失效）。
- `claim_level_reward.py`：新增「通关主线」标题校验，面板没开不点格子；格子坐标下移到 `y=845`。
- `idle_reward.py`：按「领取收益」是否还在自适应关闭，不再盲点两次。
- `guild_beast.py`：改走底部「公会」→ 圣兽雕像，不依赖会轮换的主城入口。
- `launch_game.py`：补「公告」弹窗处理（公告→开始游戏→活动弹窗→主城，约 130 秒），否则空等 150 秒再重试。
- 战役锚点：`悬赏入口.png` 改成纯文字「悬赏」（带不带红点都 1.0）。

### 5.4 素材来源
- APK 内全部 UI Sprite 已导出为**带透明通道**素材库：**4,921 张，23 秒，0 错误**。
- 出现在任务里的：邮件/日常/好友/排行榜四个主城入口、悬赏锚点、通关福利/通关主线标题。

---

## 6. 汇总：踩过的坑与已验证解法（速查）

| # | 坑 | 解法 |
|---|---|---|
| 1 | adb 短按无效 | 改 `input swipe x y x y 200–250ms` |
| 2 | 底部按钮点不中 | 命中点比视觉低 ~70px |
| 3 | 红 X 点不中 | 偏移 (-20,+10)，再逐个猜测点，最后左下返回 |
| 4 | 全屏活动页无遮罩卡死 | `close_promo()`：红 X 聚类 + 返回箭头；登录/回主城每轮 unknown 都调用 |
| 5 | 促销页被判成 战斗/结算 | 战斗判据收紧（≥3 张亮卡 + 中部暗）+ 新增 `DIALOG` 状态 |
| 6 | 地图被判成战斗 → 空转 | 底部三点全金 ⇒ 地图；未知画面 25 次上限 |
| 7 | 页签坐标改版 | 四页签 270/380/490/600；勇士计划 y≈550 |
| 8 | 模板带红点/文字/气泡 → 失效 | 只裁稳定静态部分；用标题当面板标志 |
| 9 | 原素材误命中 0.90+ | 加 ROI + 多尺度 + alpha 蒙版 |
| 10 | 圣物只点了「祝福」 | 还要「一键升级」+ 升星页签 + 羁绊可升行；回主城用左下返回 |
| 11 | 装备强化只升一次 | 循环：一键50级 → 升星 → 一键升星 → 回强化 → 直到金币不足且无可升星 |
| 12 | 只升最高等级英雄 | 升**实际出战前 5 名里等级最低**的；蓝字（共鸣）不算 |
| 13 | 悬赏同一按钮连点 10 次 | 点一次没变化就停；用标题「悬赏任务」当面板标志 |
| 14 | 日常/周常奖励领不到 | 战斗类任务要先跑；活跃度宝箱必须点 |
| 15 | 日常副本/悬赏花钻石 | 行内金按钮左侧有青色钻石图标的**一律跳过**，扫描区间 y<980 |
| 16 | 补星补满后卡住 | 地图无「挑战」时点右侧黄箭头翻章 `(640,460)`；连翻三章无可打才停 |
| 17 | 与 OAS 抢模拟器 | 前台检测：包名是阴阳师就中止；手工玩 MT 时关巡检自动重启 |
| 18 | OAS provider 为空 → 崩 | 见 §2.4 |

---

## 7. 未完成 / 待验证（对话结尾状态）

- **荣耀竞技场**：入口已找到（点奖励图标区域，不是标题），但当时「匹配」按钮在非开放时段无响应 → **未完成完整流程**。
- **公会试炼** 已能打（约 90 秒真时间战斗，无跳过），但「保存」模板曾识别失败（0.69），已补模板；后续稳定性未长期验证。
- **邪能神殿（demon）**：玩法已按用户口述重写（一键扫荡 → 符文选择 → 双队伍战斗，每场点 2–3 次跳过，每 10 关再选符文），通过后仍需观察改版。
- **主线「等级不足」** 没有专门识别提示框，只靠「进不了布阵就停」推断。
- **地精宝藏**：入口在历练页偶发找不到（日志 `在历练页没找到地精宝藏入口`），需要兜底。
- **mtbot 最终实机重跑** 被 OAS 占用挡住（`--task campaign` 中止），只做了离线回归（91 测试 + 2 日志样本）。
- **OASX 重启步骤** 在巡检链路里未实测（被权限策略拦），首次真实故障才会验证。
- **本地模型分工**：9b 与模拟器同跑显存溢出 → 只能夜间按需加载（对话中未实现自动切换策略）。
- **逆向产物的协议层**：抓包、证书校验、服务端接口细节——**对话中未提及**（该会话只做静态分析）。

## 8. 复用建议

1. 新任务先写「状态判定」再写「动作」，保证任意界面可进入、可重复运行。
2. 所有坐标进 `layout.py`，不要在任务里散落硬编码。
3. 任何新模板必须过「交叉验证 + 负样本」两道关。
4. 需要点击前先截一帧确认状态；点击后再截 1–2 帧确认变化（用户明确建议「一次点击多次截图」）。
5. 与 OAS 共存时，把「是否阴阳师前台」作为第一道守卫。
