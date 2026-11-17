# mtbot 稳定性与识别能力提升方案（对齐 OAS 实践 + adb 实时感知实测）

> 路径约定（下文引用简写）
> - `OAS/` = `c:\Users\123\Desktop\game\OnmyojiAutoScript-easy-install`
> - `mtbot/` = `E:\Reverse\auto_script\mtbot`
> - 本文为只读研究结论，**未修改任何业务代码**，未提交任何 commit。

---

## 0. 结论（先看这 8 条）

1. **mtbot 的"稳"缺的不是 try/except，而是三件套：卡死计时器、点击去重、全局任务 deadline。** 现有 `scheduler.run` 只有单任务 `try/except` + 单张现场截图（`mtbot/scheduler.py:87-97`），异常能记录，但"卡住不动"和"同一按钮连点"完全无感知——这是 OAS 与 mtbot 最大的结构性差距。
2. **`task_retries` / `auto_recover` 是死配置。** 在 `mtbot/config.py:50-51` 声明、GUI 里可改（`mtbot/gui.py:531`），但全项目无任何读取点（grep 无命中）。真正的失败重试在 OAS 是"3 次失败 → 重启游戏 → 仍失败 → 停模拟器退出"（`OAS/script.py:696-717`）。
3. **`max_task_minutes` 只在 4 处生效**（`combat.py:86`、`dungeon.py:119`、`events.py:106,159`），其余任务全靠 `for _ in range(N)` 计数兜底（如 `daily.py:552`、`reward.py:759`、`assist.py:328`）。这类循环每一次都要一次截图（约 0.9~1.3s），最坏情形是几十秒到数分钟没有"超时出口"，且没有全局兜底。
4. **"准"的短板是单帧、单模板、单阈值。** mtbot 已有可用的底层（`template.find` 支持 mask/多尺度/ROI，`titles.identify` 用 ROI 标题模板），但调用侧几乎都是"截一帧 → 判一次 → 立刻点"，没有 OAS 的"两帧确认 + 作用域→全量 的页面识别回退 + 未知页统一关闭器"。
5. **误点的根因是坐标来源。** OAS 的点击目标必须由模板命中框算出（`module/atom/image.py` 的 `coord`，432-439），mtbot 有大量直接写死的屏幕坐标（`mtbot/layout.py` 全常量、`ui.py:237-238`、`ui.py:338-340`），页面结构一变就是"点在别处"。登录兜底甚至用 `L.POPUP_BLANKS` 盲点（`ui.py:331-341`），这是事故高发点。
6. **「dbs」是 adb 的笔误，已按 adb 重做并实测。uiautomator 是硬失败**：`adb shell uiautomator dump /sdcard/wd.xml` 成功产出 2134 字节，但整棵树只有 6 个节点，最内层是 `<node resource-id="com.wjmtjq.ma.android:id/unitySurfaceView" class="android.view.View" content-desc="Game view" bounds="[28,0][691,1280]"/>` —— **无 text、无 clickable、无业务控件**。Unity 只暴露一个 SurfaceView，控件树方案在本游戏上不可用。
7. **adb 真正能给的运行时信息只有"存活/前台/帧率"以及"截图本身"**：`dumpsys activity activities | grep topResumedActivity` 可靠返回 `UnityPlayerActivity`；`logcat` 只有 `I Unity : [FrameRate] measured fps=72.0`（NvnLog 31969 行也全是帧率）；没有业务日志。**奖励是否已领、钻石余额、抽卡记录都不在 adb 元数据里，只在画面里**（见 3.6 的实拍证据：顶部钻石 254、签到页"已签到次数 22/31"）。
8. **root 可开且已实测成功，但读不到业务状态**：`root_permission=true` + 重启 + `adb root` → `uid=0(root)`，能读 `/data/data/com.wjmtjq.ma.android/`；可读字段只有 SDK 账号与客户端 UI 标志（`playerprefs` 的 `user_store`=区服 4561/138 级/昵称、`ArenaSimpleView_TodayEntered`、`ThousandLotteryAction` 等），**3 个 sqlite 全是空库（只有 `android_metadata`），无钻石余额/抽卡记录/服务端领取状态**。抓包侧：主连接是 **11019 端口的 TLS**（57 字节 / 3 秒心跳，载荷头 `17 03 03 00 34`），本机无 mitmproxy/Charles/burp，且 `global http_proxy` **不被游戏采纳（45 秒 0 命中）**。→ root 与抓包只适合人工诊断，不适合当生产数据源。

因此批 3 从"离线表驱动"改为**"在线证据链 + adb 健康探针"**：状态判断一律以"本帧截图 + adb 查询 + 日志"三者之一为证据；Luban `bytes` 表降级为**可选静态参考**（只提供关卡/商品等不变知识），root 读取与 tcpdump 只作为排查手段。

---

## 1. OAS 相对 mtbot 的具体做法（可迁移清单）

### 1.1 任务状态机与任务隔离

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 每个任务**单独模块、每次运行重新导入**，任务对象无跨轮状态 | `OAS/script.py:561-567`（`load_module` 后实例化 `ScriptTask`） | 迁移：mtbot 现在是"一整轮里顺序调用 `task.run(ctx)`"（`mtbot/scheduler.py:62-88`），对象是新建的（`tasks.make`），这点已等价；**但 mtbot 的任务内部状态（计数器/重试标记）没有落盘，跨轮无记忆**，需要补 `state.json` 的失败计数。 |
| 任务内是"截图 → 判定 → 动作"的显式循环，正常结束用异常信号 `TaskEnd` 退出 | `OAS/tasks/Restart/script_task.py:18-25`；典型任务 `while 1: self.screenshot(); ... raise TaskEnd` | 迁移：mtbot 用 `return TaskResult.ok`（`mtbot/tasks/base.py:11-23`）。**建议保留 mtbot 返回值风格**，只补一个 `TaskAbort(reason)` 异常用于"必须中断全局"的场景，避免大改。 |
| 页面定义与运行状态分离：静态 `Page` 注册表 + 运行期 navigator | `OAS/tasks/GameUi/registry.py:13-24, 69-91`；`OAS/tasks/GameUi/page_definition.py`（`Page/Transition`） | 迁移价值最高的一项：mtbot 的页面知识散在 `pages.py` 类里、坐标散在 `layout.py`。可先把"页面 key + 锚点模板 + 出入口"抽成一张表（详见批 2）。 |
| 页面识别"两帧连续一致"才算到达 | `OAS/tasks/GameUi/navigator.py:159-174`（`confirm_page`） | 直接可迁移：`titles.identify` 连续两次命中同一 key 才返回，可消灭"动画中间帧误判"。 |

### 1.2 异常分类、超时、重试

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 异常分谱系：`TaskEnd`（正常结束）/`RequestHumanTakeover`/`GameStuckError`/`GameTooManyClickError`/`ScriptError`/`EmulatorNotRunningError` 等 | `OAS/module/exception.py:21-62` | 迁移：mtbot 现在只有 `DeviceError`（`mtbot/device.py:15`）。建议新增 `mtbot/errors.py`，至少区分 `Stuck / TooManyClick / UnknownScreen / DeviceLost / TaskTimeout`。 |
| 顶层按异常类型分派：UI 类错误 → 重启游戏；环境类错误 → 要求人工；其余记日志继续 | `OAS/script.py:540-621` | 迁移：对应 `mtbot/scheduler.py:89-97` 的 catch-all，只需按异常类型分支。 |
| 重试装饰器：可配置次数、间隔、失败回调，成功一次即止 | `OAS/module/base/retry.py:32-98` | 迁移：给"页面进入/按钮点击"这类幂等动作套装饰器，比"整任务重试"粒度更细、更安全。 |
| 动作级超时：`ui_click(..., timeout=...)` 到点返回失败而不是死等 | `OAS/tasks/base_task.py:760-782` | 迁移：mtbot `ui.press`/`titles` 全无超时概念（`mtbot/ui.py:34-37`）。 |
| 调度层自带重试节奏：成功/失败间隔分别设定 | `OAS/module/config/config.py:177-216`（`success_interval`/`failure_interval`） | 迁移：mtbot 是"跑完这一轮就结束"（`run.py:148-162` 轮次循环），没有"失败后退避 X 分钟再跑该任务"的概念。 |

### 1.3 卡死检测与自动重启（这是"稳"的核心）

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| **全局卡死计时器**：短 60s / 长 300s 两档，超时抛 `GameStuckError` | `OAS/module/device/device.py:29-30`（`stuck_timer` / `stuck_timer_long`）、141-163（判定） | 迁移：`mtbot` 完全没有等价物。建议在 `UI.screen()` 与 `UI.press()` 里统一 `stuck_record('WAIT_XXX')`，配合 `guard.py` 的定时器。 |
| 任务主动登记"我在等什么"，等太久即判卡死 | `OAS/module/device/device.py:126-163`（`stuck_record_add`，按名字累积） | 迁移：mtbot 里大量 `for _ in range(N)` 等动画（`reward.py:759`、`daily.py:552`），应改成 `wait_until(cond, timeout=...)`，内部即等价于 `stuck_record`。 |
| 失败后**重启游戏**而不是继续硬跑 | `OAS/tasks/Restart/script_task.py:37-44`（`app_stop` → `app_start` → login → `TaskEnd`） | 迁移：mtbot 有 `device.stop()`/`launch()`（`mtbot/device.py:126-131`）和 `ui.start_app`/`login`（`ui.py:345`、`ui.py:271`），**零件齐全，缺的是"什么条件下自动重启"的策略**。 |
| 连续 3 次任务失败 → 停模拟器 + 退出 + 通知 | `OAS/script.py:696-717`、`OAS/script.py:645-728` | 迁移：mtbot 的 `state.json` 只存 `last_run`（`mtbot/scheduler.py:103-110`），加 `fail_streak` 即可实现，且 GUI 已有日志面板可显示（`gui.py:623` 行读取线程）。 |
| 每任务开始清空异常记录，避免"上一个任务的卡死算到下一个头上" | `OAS/script.py:685-686` | 迁移：1 行级改动。 |

### 1.4 识别失败回退与未知画面处理

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 模板匹配必须带 ROI + 阈值，且 ROI 分"前景/背景"两套 | `OAS/module/atom/image.py:17-41`（`RuleImage.roi_front/roi_back/threshold`） | mtbot 的 `template.find(screen, name, threshold, scales, roi)` 参数已有（`mtbot/template.py:144`），**但调用方几乎不传 roi**；应把 roi 定义落到资源侧（类似 sidecar JSON），而不是散在代码里。 |
| 页面识别**两级回退**：先按"当前场景允许的页面类别"识别，未命中再退到"全量页面"；仍失败则记 warning，交给上层关闭器/重启策略 | `OAS/tasks/GameUi/navigator.py:195-231`（`_detect_current_page_with_fallback`） | 这是 mtbot 最该抄的结构：mtbot `vision.classify` 是单帧硬阈值，低于阈值直接 `State.UNKNOWN`（`mtbot/vision.py:457-498`），没有"缩小搜索范围"这一层。 |
| 未知画面**统一关闭器**清单（广告/公告/弹窗/断线重连…） | `OAS/tasks/GameUi/navigator.py:39-54`（`DEFAULT_UNKNOWN_CLOSERS`） | mtbot 已有 `close_popup` / `close_promo`（`ui.py:49-105`、`ui.py:106-135`），但策略分散在 `ensure_main_city` 内部（`ui.py:182-261`），任务里又各写一份"unknown 计数"（如 `combat.py:136-141`）。应收敛为一个 `recover_unknown()`。 |
| "同一跳转连续失败 3 次"即判定导航失败，换路径 | `OAS/tasks/GameUi/navigator.py:39`（`REPEATED_TRANSITION_FAILURE_THRESHOLD = 3`）、`790-890`（progress timer + 路径签名判断"有没有进展"） | 迁移：给 mtbot 的 `goto_tab`（`ui.py:263-270`）/各页 `enter()` 加"进展签名 + 3 次失败升级"。 |

### 1.5 模板 ROI 与多模板交叉验证

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 多尺度匹配（分辨率/UI 缩放漂移的兜底） | `OAS/module/atom/image.py:267-350`（`match_multi_scale`） | mtbot 已有 `_scales`/`sidecar_scales`（`template.py:113-136`、`144-163`），属于**已具备但未全面启用**，成本最低的提准手段。 |
| 多目标匹配，用"数量/位置关系"做交叉验证（如"奖励列表第 2 行存在"） | `OAS/module/atom/image.py:351-390`（`match_all`） | mtbot 有 `find_all`（`template.py:165-190`）但仅少数地方用；建议用于列表类界面（奖励、商店、关卡）。 |
| 组合匹配器：`all_of / any_of / not_` 表达"主城 = 有X且无Y" | `OAS/tasks/GameUi/page.py:58`（导出 `AllMatcher/AnyMatcher/NotMatcher`） | 迁移：mtbot 的 `vision.py` 已有大量 `is_gold/is_green/button_badge` 原子判据（`vision.py:28-72`），**只需要一个 20 行的组合器**就能写出稳健的复合页面判据。 |
| 识别复用同一帧（`self.device.image`），减少截图次数 | `OAS/tasks/base_task.py:184-211`（`appear` 用缓存帧） | mtbot 的 `ui.screen(name, fresh=False)` 已支持（`ui.py:27-33`），但多数任务每个判断都 `fresh=True`，浪费 1s/次。 |

### 1.6 坐标容错与点击方式

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 点击点由模板命中框中心计算，而非写死坐标 | `OAS/module/atom/image.py:219-265`（`match` 返回 box，`coord()` 取中心）、`OAS/tasks/base_task.py:213-243`（`appear_then_click`） | 迁移：mtbot `layout.py` 全常量坐标；建议"先用模板定锚点，再用相对偏移点击"，锚点失败则放弃点击（宁可不点，不要点错）。 |
| 点击前校验设备状态（`control_check`），无效状态不盲点 | `OAS/module/device/control.py:63-82` | 迁移：mtbot `device.press` 直接 `adb shell input tap`（`device.py:66-69`），无"最近一帧是否可交互"的判断。 |
| 长按/点击时长统一走配置（本游戏 50ms 不触发，需要长按） | mtbot 已有：`config.py:46 tap_ms=220`，OAS 对应 `control.py` 的 click duration | mtbot 这点是对的，应保留并统一到所有点击路径。 |

### 1.7 日志与失败截图

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 每天一个日志文件 + 保留天数清理 | `OAS/module/logger.py:132-165`、`19-51` | mtbot 已有按天文件（`log.py:55-64`）但**无清理**；`logs/screens` 只按数量裁剪 300 张（`config.py:47`、`device.py:104-119`）。 |
| **失败现场打包**：最近 60 帧 + 自最近一次分隔线起的日志（`log.txt`）→ `./log/error/<毫秒时间戳>/` | `OAS/script.py:101-132`；环形缓冲在 `OAS/module/device/screenshot.py:73`（`screenshot_deque`） | 这是最划算的可观测性改造：mtbot 现在只有一张 `error_{name}.png`（`scheduler.py:92-96`），复现"点错那一刻"几乎不可能。 |
| 日志带"任务/页面"上下文分段打印 | `OAS/script.py:687`（`logger.hr(task, level=0)` 任务横幅）、`563-567`（打印任务模块路径/名称） | mtbot `log.task()` 已有（`log.py:96`），补"进入/离开页面 + 耗时"即可（`log.goto/arrived` 已存在，`log.py:88-95`）。 |

### 1.8 配置热更新

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 配置按 mtime 自动重载 | `OAS/module/config/config_watcher.py:10-41` | 迁移：mtbot `run.py:85` 启动时读一次配置，GUI 保存后对已运行进程无效（`gui.py:531` 改的是内存对象，`gui.py:58` 才写盘）。 |
| 调度等待循环里检查"是否该重载"，边等边生效 | `OAS/script.py:296-321`（`wait_until` + `should_reload`） | 迁移：mtbot 的轮次间等待（`run.py:148-162`）同样可以插检查点。 |
| 每次取任务/延时前先 `reload()` | `OAS/module/config/config.py:292-383`（`task_delay`） | 迁移：把 `cfg` 变成"可重载句柄"，任务只持有句柄。 |

### 1.9 GUI 与执行分离

| 做法 | OAS 位置 | 说明 / 迁移要点 |
|---|---|---|
| 脚本跑在**独立进程**，服务端可 `terminate → join → kill` 三级停止 | `OAS/module/server/script_process.py:35-64` | mtbot 已经是 `subprocess.Popen`（`gui.py:617-621`），**起点很好**；差距是停止只有 `proc.terminate()`（`gui.py:714-718`），无"停后回主城/清理锁"。 |
| WebSocket `/ws/{name}` 提供启动/停止/状态 | `OAS/module/server/script_router.py:204-236` | mtbot 不需要 WebSocket（桌面 GUI 足够），但可借鉴"状态机 + 幂等启停 + 心跳"语义。 |
| GUI 只做展示，执行侧自包含（无 GUI 也能跑） | `OAS/script.py` 可直接 `python script.py` 运行 | mtbot `run.py:64` 已有 CLI，保留即可。 |

---

## 2. mtbot 当前薄弱点（逐条 + 文件/函数证据）

### 2.1 稳定性

| # | 薄弱点 | 证据（文件:行） | 后果 |
|---|---|---|---|
| S1 | 无全局任务 deadline，卡住的任务会一直占住整轮 | `mtbot/scheduler.py:54-120` 只 `task.run(ctx)`；`max_task_minutes` 仅 `combat.py:86`、`dungeon.py:119`、`events.py:106,159` 使用 | 一个任务挂住，后续任务全不跑；GUI 看不出"卡了多久" |
| S2 | 无卡死计时器（stuck timer） | 全项目无 `stuck_record` 等价物；等待靠 `for _ in range(N)`（`daily.py:552`、`reward.py:759`、`assist.py:328`） | 动画变慢/网络卡顿时，循环跑完仍判"未知"，反复空转 |
| S3 | 无点击去重，同一坐标可连点 | `mtbot/ui.py:34-37` → `device.py:66-69`（直接 `input tap`） | 误点/重复触发买钻、消耗次数（README 里已有"乱花钻石"类事故记录，故 `may_spend` 兜底，`tasks/base.py:56-74`） |
| S4 | 无失败重试/退避：`task_retries`、`auto_recover` 是死配置 | 声明 `mtbot/config.py:50-51`，GUI 可改 `gui.py:531`，**全项目无读取点** | 用户以为开了自动重试，实际不生效 |
| S5 | 跨轮无记忆：只存 `last_run` 结果 | `mtbot/scheduler.py:103-110`（`state.json` 结构） | 无法做"连续 3 次失败 → 重启游戏/停模拟器" |
| S6 | 设备层无重连；adb 失败即抛 | `mtbot/device.py:34-45`（`adb`/`shell` 抛 `DeviceError`）、`50-57`（只在启动连一次） | 模拟器抖动一次，整轮失败（虽然单实例锁 `run.py:40-61` 会阻止重复启动） |
| S7 | 截图每帧 `adb pull`，无 `exec-out` 直读、无帧缓存 | `mtbot/device.py:89-102` | 单帧约 0.9~1.3s，判断链变长即漏帧；也放大了 S1/S2 |
| S8 | 停止只 `terminate()`，无"停后回主城/清锁" | `mtbot/gui.py:714-718` | 下次启动可能停在战斗/弹窗中间态 |

### 2.2 识别准确度

| # | 薄弱点 | 证据 | 后果 |
|---|---|---|---|
| R1 | 主判读是**像素采样阈值**，单帧单次 | `mtbot/vision.py:14-72`（`avg/is_gold/is_green/...`）、`457-498`（`classify`） | 光照/战斗特效/半透明遮罩一变就判 `UNKNOWN` |
| R2 | 页面标题模板只有一处 ROI，单帧判定 | `mtbot/titles.py:16-17`（ROI `(0,0,340,95)`、`THRESHOLD=0.90`）、`50-55`（`identify`） | 过渡动画中误判页面 |
| R3 | `template.find` 单帧单模板，无两帧确认、无"命不中再放宽一次"的二次匹配 | `mtbot/template.py:144-163`（默认 `threshold=0.85`，`template.py:34`） | 一次低分命中就点击 |
| R4 | ROI 参数存在但调用侧基本不传 | `mtbot/template.py` 已支持 `roi/scales`；`titles.py` 是唯一常规使用者 | 全屏匹配 → 误命中率上升 |
| R5 | 页面知识用类 + 硬编码坐标，非注册表/图 | `mtbot/pages.py` 各类 `enter()/is_open()`；`mtbot/layout.py` 全常量；`ui.py:237-238`、`ui.py:338-340` 散落坐标 | 坐标随 UI 改版失效，且没有"锚点失败就不点"的保护 |
| R6 | `unknown` 处理策略在每个任务里各写一份 | `combat.py:136-141`、`daily.py` 等多处本地计数器 | 行为不一致，难统一调参 |
| R7 | 无"动作前置校验"（点击前是否处于可交互态）；登录兜底还会**盲点猜测坐标** | `ui.py:34-37`；`ui.py:331-341`（`for pos in L.POPUP_BLANKS[:2]` 轮流点） | 动画中点击被吞后重复点；兜底盲点可能正好点在"购买/消耗"上 → 与 S3 叠加 |

### 2.3 mtbot 已有的优点（改造时要保留，别顺手改坏）

- 单实例锁 + 残留 PID 检测：`mtbot/run.py:31-61`
- 前台被其它脚本占用时整轮中止：`mtbot/scheduler.py:74-85`
- 任务间强制回主城：`mtbot/scheduler.py:112-115`
- 任务对象与 GUI 分离（子进程 + 日志线程）：`gui.py:617-621`、`623-660`
- 模板支持 mask / 多尺度 / sidecar：`template.py:43-97`、`113-163`
- 付费闸门（默认拒钻）：`tasks/base.py:56-74`、`config.py:49`
- 日志带源文件行号：`log.py:34-53`、`55-64`

### 2.4 最小改造路径（不做大重构，按"新增文件 + 少量钩子"推进）

| 步骤 | 新增/改动 | 范围（估） | 说明 |
|---|---|---|---|
| M1 | 新增 `mtbot/guard.py`：`Deadline`、`StuckTimer`、`ClickGuard` | +约 150 行 | 纯新增，零侵入 |
| M2 | `ui.py` 挂 2 个钩子：`screen()` 记录"等待开始"、`press()` 过 `ClickGuard`（含 `tap_ms` 统一） | 改 `ui.py` 约 8 行 | 一处改，全任务受益 |
| M3 | `scheduler.py`：任务级 deadline（`max_task_minutes` 全局强制）+ `fail_streak` 落盘 + 3 次失败升级（重启游戏/停模拟器） | 改约 30 行 | 让 `task_retries/auto_recover` 真正生效 |
| M4 | 新增 `mtbot/incident.py`：保留最近 N 帧（内存环形）+ 失败时打包 png/日志尾 | +约 60 行；`log.py` 加 1 个 sink | 取代"单张 error_*.png" |
| M5 | 新增 `mtbot/errors.py`：`Stuck/TooManyClick/UnknownScreen/DeviceLost/TaskTimeout` | +约 40 行 | 上层按类型分支 |
| M6 | `device.py`：截图改 `exec-out screencap -p`（Windows 下用二进制重定向）+ 短缓存 + 失败重连 1 次 | 改约 40 行 | 直接压缩 S7/S6，减少卡死概率 |
| M7 | 新增 `mtbot/actions.py`：`appear()/appear_then_click()/wait_until()`（ROI + 阈值 + interval + timeout + 两帧确认） | +约 120 行 | 批 2 的主力；任务渐进替换，不必一次全改 |
| M8 | 新增 `mtbot/nav.py`：页面 key 注册表 + 未知页关闭器链 + 跳转失败 3 次升级 | +约 150 行 | 与 `titles.py`/`pages.py` 并存，先 shadow 运行，再切换 |

---

## 3. 「dbs」可行性结论

### 3.1 能力 → 实测结果 → 结论（总表）

| 能力 | 实测命令 | 实测结果 | 结论 / 限制 |
|---|---|---|---|
| uiautomator 控件树 | `adb shell uiautomator dump /sdcard/wd.xml` + `adb pull` | 2134 B、6 个节点，最内层 `unitySurfaceView`（`android.view.View`，content-desc="Game view"），无 text / 无 clickable | ❌ 不可用：Unity 只暴露一个 SurfaceView，没有可读控件 |
| dumpsys / logcat | `dumpsys activity activities`、`dumpsys window windows`、`logcat -d` | 前台=`UnityPlayerActivity`，`isVisible=true`；logcat 只有 `I Unity : [FrameRate] measured fps=72.0` | ✅ 可做存活/前台/卡死探针；❌ 无任何业务字段 |
| root 读取 | `root_permission=true` + `control restart` + `adb root` → `uid=0(root)`，读 `/data/data/com.wjmtjq.ma.android/` | 16 个 shared_prefs / 3 个 sqlite（全空）/ 4 个 SDK 文件；只有账号与 UI 标志 | ⚠️ 仅调试取证；读不到余额/抽卡/领取状态 |
| 抓包 | 设备端 `tcpdump`（root 后可用）、`ss -tunp`；`global http_proxy` + `adb reverse` | 主连接 **11019 端口 TLS**（57 B / 3 s 对称心跳，载荷头 `17 03 03 00 34`）；HTTP 代理 45 s **0 命中** | ✅ tcpdump 能证明"有流量"；❌ 无明文（TLS + 代理不被采纳） |

> 原始 Luban 静态表（1697 张 `*.bytes`）仍可离线解码，但已降级为**可选静态参考**，见 3.5；它提供"关卡/商品/奖励池"这类不变知识，不提供"当时状态"。

### 3.2 uiautomator 控件树：硬结论（实测，非推断）

实测命令与产物：

```powershell
adb -s 127.0.0.1:16384 shell uiautomator dump /sdcard/wd.xml
# UI hierchary dumped to: /sdcard/wd.xml
adb -s 127.0.0.1:16384 pull /sdcard/wd.xml
# 2134 bytes
```

整棵 XML 只有 6 个节点，最内层（也是唯一有内容的节点）为：

```xml
<node index="0" text="" resource-id="com.wjmtjq.ma.android:id/unitySurfaceView"
      class="android.view.View" package="com.wjmtjq.ma.android"
      content-desc="Game view" checkable="false" checked="false"
      clickable="false" enabled="true" focusable="true"
      bounds="[28,0][691,1280]" />
```

硬结论：

1. **没有任何 `text`**，**没有除 `unitySurfaceView` 之外的 `resource-id`**，**没有 `clickable=true` 的节点**。
2. Unity 的 UI 全部画在 SurfaceView 的像素里，不是 Android View，`uiautomator`/Accessibility 读不到。
3. 因此"按控件 id 点击 / 读控件文字"这条路在本游戏上**直接作废**，不是"还没试"的问题。

反过来说：mtbot 走"截图 + 模板匹配"不是落后，而是**这个游戏唯一可行的手段**；可优化的是"何时截、截哪块、如何复核数字"，而不是换控件树。

### 3.3 dumpsys / logcat / root：能读到什么、读不到什么

**dumpsys / logcat（无需 root）**

| 命令 | 实测输出 | 可用性 |
|---|---|---|
| `dumpsys activity activities \| grep topResumedActivity` | `topResumedActivity=...com.wjmtjq.ma.android/com.unity3d.player.UnityPlayerActivity` | ✅ 判断"游戏是否在前台"，零成本 |
| `dumpsys window windows` | `...UnityPlayerActivity ... isVisible=true`，另有 `Panel:com.wjmtjq.ma.android/...UnityPlayerActivity` | ✅ 判断是否被系统层/半透明层遮挡 |
| `logcat -d \| grep Unity` | 只有 `I Unity : [FrameRate] measured fps=72.0` | ⚠️ 只能看帧率，无业务日志 |
| 外置 NvnLog（`NvnCache/Log`） | 31969 行 / 4.18 MB，尾部全为 FrameRate | ⚠️ 同上 |

> 这三项正好支撑批 1 的"存活/前台/卡死"探针（P0-5），但**一条业务字段都没有**。

**root 读取（已实测：可开、可读、可关）**

```powershell
MuMuManager.exe setting -v 0 -k root_permission -val true
MuMuManager.exe control -v 0 restart
adb -s 127.0.0.1:16384 root
adb -s 127.0.0.1:16384 shell id
# uid=0(root) gid=0(root) ... context=u:r:su:s0
```

读 `/data/data/com.wjmtjq.ma.android/` 的实际内容：

| 文件 | 实测字段（举例） | 用途 / 限制 |
|---|---|---|
| `shared_prefs/com.wjmtjq.ma.android.v2.playerprefs.xml` | `10tjlbi8o1i00user_store` = `{"4561":{"server_id":"4561","level":138,"avatar":"2002","actorname":"火球呼脸"}}`；`db6vj1g013k8p7atArenaSimpleView_TodayEntered=1793630690`；`...ThousandLotteryAction=1`；`...SunkenTreasurePopUpView`；`...PopupScheduler_FuncOpenShown=2031,2029`；`unity.player_session_count=66` | 能确认账号/区服/等级；能看到"某弹窗/玩法今天是否已进入"的**客户端去重标志**。⚠️ 这是 UI 标志，**不是奖励领取状态** |
| `shared_prefs/cl_jm_file.xml` | `cl_jm_b1=gdapi.a5b.cc`（API 域名）、`cl_jm_a5=2.3.7.4`（SDK 版本）、`cl_jm_a9=300013296490`、`cl_jm_a2/c4/f5/c9/c3`（token/hash 类） | 定位服务端域名与 SDK 身份；**敏感，勿外传** |
| `shared_prefs/yjsdk.xml.xml` | `yl_user_bean` 明文 JSON：`uid`、`username`（手机号）、`token`（JWT/HS256） | 账号凭证；**敏感** |
| `shared_prefs/YouYiData.xml` | `loginMethod=mobile`、`androidId`、`devid`；登录数据为 Java 序列化 `rO0AB...` | 账号登录缓存；非业务 |
| `databases/cl_jm_database.db` / `bugly_db_` / `rmonitor_db` | **每个库只有 `android_metadata(locale='zh_CN')`，0 行业务数据** | 空库，无价值 |
| `files/` | `tapsdk/events.db`（6120 B 埋点）、`TapEvent_persistedData`（空列表）、`bugly_last_us_up_tm` | SDK 埋点/崩溃；无业务 |

**明确没有的东西**：钻石余额、抽卡记录、奖励领取状态——在以上**所有文件里都不存在**。它们只在服务端消息与画面里。

### 3.4 抓包：能看到什么、为什么看不到明文

1. **本机工具盘点**：`mitmproxy / mitmdump / charles / burp / fiddler / wireshark / tshark` **全部缺失**（`Get-Command` + 常见安装路径 + `pip list` 均无）。
2. **root 后设备自带 `tcpdump` / `ss` / `netstat`**（`/system/bin/`），不需要安装任何东西就能证明"有流量"。
3. `ss -tunp` 实测：游戏进程同时持有 `118.145.248.220:11019`（ESTAB 长连接）与多条 `:443`（SDK/登录）。
4. `tcpdump -i wlan0 -nn -c 40 -s 200 'tcp and host 118.145.248.220'`：**每 3.00 秒一对 57 字节报文，收发对称**；`-X` 显示载荷开头 `17 03 03 00 34`，即 TLS 1.2 application data（记录长 52 的密文）。
   → 不是"自定义明文协议"，而是**跑在非标准端口 11019 上的 TLS**（外层 TLS，内层帧格式未知）。
5. 关闭签到弹窗时（13:15:28），同一连接出现 **233 B + 249 B** 服务端下推 → 交互确实实时产生服务端数据，但**全是密文**。
6. **HTTP 代理实验**：`settings put global http_proxy 127.0.0.1:8888` + `adb reverse tcp:8888 tcp:8888` + 本机监听 → **45 秒 0 命中**，`ss` 也没有任何进程连 8888 → 游戏**不读取 Android 全局代理**（Unity/BestHTTP 自建连接）。
7. 因此"HTTP 代理 + 用户 CA 解密"这条常规路径在本游戏上**不成立**；要拿明文只能做 iptables 透明重定向 + TLS 中间人 + 再破内层加密，成本与风险都高，**不建议作为脚本数据源**。

### 3.5 Luban 静态表：降级为可选静态参考（不排期）

`bytes` 表只提供"关卡/商品/奖励池"这类**不变知识**，不能提供任何"当时状态"；且 1697 张里只有 1298 张能被现有启发式解析、399 张失败、没有字段名 schema。因此它**不再作为批 3 主线**，只在确实需要静态知识时启用。

若将来启用，仍走"离线导出 → 运行时只读 JSON → 哈希校验失败即回退"的链路；下面保留参考实现（当前**不排期、不落地**）：

**选表**：`campaign_tbgoblintreasuremine`、`shop_tbshopdata`、`club_bounty_tbclubbountyboss`。

**第 1 步（离线）** `tools/export_gamedata.py`（一次性，人在环）：

```python
# tools/export_gamedata.py  —— 离线导出，不参与运行时
import json, hashlib, sys
from pathlib import Path
sys.path.insert(0, r"E:\Reverse\tools")
import lbix

FIELD_SCHEMA = {}   # name -> 人工确认后的字段名列表
TABLES = ["campaign_tbgoblintreasuremine", "shop_tbshopdata", "club_bounty_tbclubbountyboss"]
SRC = r"E:\Reverse\export\GameData\Data\Data\bytes"

def export(name: str, fields: list[str]):
    raw = open(fr"{SRC}\{name}.bytes", "rb").read()
    mode, nfields, idx, data_start = lbix.choose_mode(raw)
    if not mode:
        raise SystemExit(f"{name}: 头部解析失败，需人工处理")
    if len(fields) != nfields:
        raise SystemExit(f"{name}: 字段数 {nfields} 与 schema {len(fields)} 不符")
    rows = {}
    offs = [o for _, o in idx]
    for i, (k, o) in enumerate(idx):
        end = offs[i + 1] if i + 1 < len(offs) else len(raw) - data_start
        toks = lbix.tokens(raw, data_start + o, data_start + end)
        values = [v for _, v, _, _ in toks]
        rows[str(k)] = dict(zip(fields, values))     # 字段名由人工核对得到
    return {
        "table": name,
        "schema_version": "0.1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rows": rows,
    }

for name in TABLES:
    # 先跑一遍 lbix 打印 token 序列，人工对照得到字段名（必要时用 IL2CPP 字段顺序）
    fields = FIELD_SCHEMA[name]   # 由人工核对维护的 dict[str, list[str]]
    payload = export(name, fields)
    out = Path(f"data/gamedata/{name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{name}: {len(payload['rows'])} 行 → {out}")
```

**第 2 步（运行时只读）** `mtbot/gamedata.py`：

```python
"""只读加载离线导出的配置表；校验失败一律回退，绝不用可疑数据做决策。"""
import json, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "gamedata"
_cache = {}

class GameDataUnavailable(Exception):
    pass

def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(table: str, expected_sha: str | None = None) -> dict:
    if table in _cache:
        return _cache[table]
    p = ROOT / f"{table}.json"
    if not p.exists():
        raise GameDataUnavailable(f"缺少 {table}（未导出或已禁用）")
    payload = json.loads(p.read_text(encoding="utf-8"))
    if expected_sha and payload.get("source_sha256") != expected_sha:
        raise GameDataUnavailable(f"{table} 版本不匹配，拒绝使用")
    _cache[table] = payload["rows"]
    return payload["rows"]

def try_load(table: str) -> dict | None:
    try:
        return load(table)
    except GameDataUnavailable:
        return None
```

**第 3 步（决策接入，示例 diff 思路）**

```python
# mtbot/tasks/goblin.py 里把"层数/守卫战力"这类常量改为表驱动
rows = gamedata.try_load("campaign_tbgoblintreasuremine")
if rows:
    max_floor = max(int(r["floor"]) for r in rows.values())   # 字段名以 schema 为准
    log.info(f"地精宝藏共 {max_floor} 层（来自 dbs）")
else:
    max_floor = 6          # 回退：原硬编码
    log.warn("dbs 不可用，沿用内置常量")
```

**第 4 步（验收口径）**
1. 同一段录像/同一状态，接表与不接表的决策输出**完全一致**（差异必须先解释清楚）；
2. 删除 `data/gamedata/` 目录 → 脚本行为与今天**完全等价**（回退通路有效）；
3. 人为改坏一个字段值 → 值域断言报警，且不触发购买动作。

### 3.6 在线证据链：状态到底从哪里读（实测样板）

关掉签到弹窗前后的两张实拍（同一次会话，13:13 / 13:15）：

| 观察点 | 实拍读数 | 说明 |
|---|---|---|
| 顶部资源栏 | 金币 `262233`、钻石 **`254`** | 钻石余额**就在画面里**，固定 ROI，可直接读 |
| 签到弹窗 | `获得奖励` + `阵营核心` 图标 | "刚领了什么"可从弹窗标题/道具图标判断 |
| 关闭后签到页 | `已签到次数：22/31`，第 22 天标 `再领一次 充值5` | **领取进度/是否还能领**在页面上，不在 prefs |
| 弹窗提示 | `点击空白处关闭` | 关闭动作的锚点文本，可作为"弹窗存在"的判据 |

因此"在线实时验证"的落地形态是**截图证据链**，规则如下：

1. 任何"已领取 / 是否可领"的判断，必须绑定**本帧截图 + 命中区域坐标 + 时间戳**，三者一起进日志；
2. 数值类（钻石/次数/进度）用**固定 ROI + 数字模板或 OCR**，**两帧一致**才采信（对齐批 2 的 P1-1 两帧确认）；
3. `dumpsys`/`logcat` 只作旁证（前台/存活/帧率/卡死），**不充当业务状态来源**；
4. 判断失败必须留帧（批 1 P0-4），否则"为什么这么点"无法回溯；
5. 离线表（Luban）允许存在，但**不得单独作为决策依据**——必须有在线证据兜底。

### 3.7 四个确认点的结论（已按你的回应重做）

| 确认点 | 你的回应 | 实测结论 |
|---|---|---|
| 1. "dbs" 是什么 | 是 **adb** 的笔误 | 已按 adb 重做。`uiautomator` 硬失败（只有 `unitySurfaceView`）；adb 能给的是存活/前台/帧率+截图，不含业务字段 |
| 2. 离线导出 | 可接受，但最终必须在线实时验证 | 接受。Luban 表**降级为可选静态参考**（3.5）；所有状态判断必须有在线证据（3.6） |
| 3. root | 可以做，自己去试 | **已实测成功**（`uid=0`），但只能读到账号与 UI 标志，**读不到奖励/钻石/抽卡**；默认关闭，仅排障时开 |
| 4. 抓包 | 要你尝试 | 已实测：**无 mitmproxy/Charles/burp**；主连接是 **11019 端口 TLS**；`global http_proxy` **不被采纳** → 常规代理解密不成立，抓包只作旁证 |

### 3.8 风险与还原（设备侧改动均已回退）

| 改动 | 还原动作 | 实测校验 |
|---|---|---|
| `root_permission` false→true | `setting -v 0 -k root_permission -val false` + `control -v 0 restart` | `--all_writable` 显示 `"root_permission": "false"`；`adb shell id` = `uid=2000(shell)` |
| `global http_proxy` → `127.0.0.1:8888` | `settings put global http_proxy :0` | 读回 `:0`（即未设置） |
| `adb reverse tcp:8888 tcp:8888` | `adb reverse --remove-all` | `reverse --list` 为空 |
| 临时文件（`/sdcard/wd.xml`、`cap1.txt`、本次截图） | `rm -f` | 已删除（`/sdcard` 其余 png 是另一会话的产物，未动） |
| CA 证书 | **未安装**（代理未被采纳，安装无意义） | 无新增用户证书，无需移除 |
| 实例重启导致游戏退出 | `am start ...UnityPlayerActivity` | 进程存在且 `topResumedActivity` 为 UnityPlayerActivity |

残余风险：开 root 会强制重启实例（本轮已发生 2 次中断）；读到的手机会话/token 属敏感信息，**未写入任何文档**；长期开 root 的账号风险未验证。

---

## 4. 排期建议（3 批）

### 批 1｜先止血：卡死与误点（最高优先，改动小、收益立竿见影）

| 任务 | 交付物 | 触碰文件 | 验收 |
|---|---|---|---|
| P0-1 全局任务 deadline + 看门狗 | `guard.py` 的 `Deadline`；`scheduler` 包裹 `task.run` | 新增 `guard.py`；改 `scheduler.py`（约 20 行） | 任一任务超过 `max_task_minutes` 必须被中断并记 `TaskTimeout` |
| P0-2 点击去重 | `ClickGuard`（同坐标 60s 内 >6 次 → 拒绝并抛 `TooManyClick`） | `ui.py` 挂 `press()`（约 8 行） | 日志中不再出现"同点连击"；误触关键按钮的轮次为 0 |
| P0-3 未知画面统一兜底 | `ui.recover_unknown()`（收敛 `close_popup/close_promo/回主城`） | `ui.py`（约 40 行）；任务内替换本地计数器（渐进） | 未知态自愈成功率可统计；任务内 `unknown` 分支显著减少 |
| P0-4 失败现场包 | `incident.py`：最近 10~20 帧 + 日志尾 → `logs/incidents/<时间>/` | 新增；`scheduler.py` 3 行 | 任一失败能在 1 分钟内定位"点错在哪一帧" |
| P0-5 设备层加固 | 截图 `exec-out` + 缓存 + 单次重连；`errors.py` 分类 | `device.py`（约 40 行）；新增 `errors.py` | 拔插/重启模拟器后能自愈一次，而不是整轮失败 |
| P0-6 让死配置复活 | `task_retries`/`auto_recover` + `fail_streak` + 连续 3 次失败升级 | `scheduler.py`（约 15 行） | GUI 上开关有效；连续失败会重启游戏而非无限重跑 |

### 批 2｜再提准：识别与坐标

| 任务 | 交付物 | 触碰文件 | 验收 |
|---|---|---|---|
| P1-1 页面识别升级 | `PageID` + 两帧确认 + 锚点"唯一性"约束 | `titles.py` 扩展（约 40 行） | 过渡动画不再误判；`UNKNOWN` 帧占比下降（可用日志统计） |
| P1-2 动作抽象 | `actions.py`：`appear/appear_then_click/wait_until`（ROI+阈值+interval+timeout+多模板 any/all） | 新增（约 120 行）；任务渐进替换 | 所有点击都由模板命中点推出，硬编码坐标清零（`layout.py` 只保留"无模板可用"的少量项） |
| P1-3 坐标容错 | 锚点失败 → 不点；相对偏移白名单；`tap_ms` 统一 | `layout.py`/`pages.py` 渐进；`ui.py` | 点错导致的"进了别的界面"事故下降 |
| P1-4 OCR 复核闸门 | 花钱/消耗次数前读余额或次数 | 视 OCR 选型（PaddleOCR/Tesseract 选一） | 余额不足时绝不点击 |
| P1-5 页面注册表 | `nav.py`：页面 → 锚点 → 入口/出口；未知页关闭器链 | 新增（约 150 行） | 任一页面可从任意页面到达（离线图校验） |

### 批 3｜后增强：adb 实时感知 + 在线证据链（原"离线表驱动"已作废）

| 任务 | 交付物 | 触碰文件 | 验收 |
|---|---|---|---|
| P2-1 adb 健康探针 | `probe.py`：`dumpsys activity` 前台判定 + `logcat` FrameRate/崩溃 + 进程存活 | 新增（约 60 行）；`scheduler.py` 挂钩 | 游戏被切后台/崩溃/卡死 3 s 内可判定，不再靠模板猜 |
| P2-2 数字 ROI 读数（在线证据） | `readers.py`：钻石/次数/进度固定 ROI + 数字模板或 OCR + **两帧一致**才采信 | 新增（约 100 行）；先接"签到/商店"各一处 | 读数与实拍一致；余额/次数不足时绝不点击 |
| P2-3 判断留痕（证据链） | 每次状态判断落 `logs/evidence/<时间>_<task>.png + .json`（ROI、读数、结论） | 新增小模块 + `scheduler.py` 3 行 | 任一"已领取/不够钱"结论都能回放截图自证 |
| P2-4 诊断工具（仅人工） | `tools/diag.ps1`：开 root → `ss`/`tcpdump` → 读 prefs 的一键取证脚本，**不进运行路径** | 新增工具脚本 | 排障时可取证；生产运行零依赖 |
| P2-5（可选，不排期） | Luban 静态表离线导出，仅作"关卡/商品"知识参考 | 见 3.5 | 删除数据目录后行为等价 |

**批间依赖**：批 2 的 `actions.py` 依赖批 1 的 `guard.py`（超时/去重是它的基础）；批 3 的 P2-1/P2-2 可直接复用批 1 的 `guard` 与批 2 的两帧确认，**不依赖 root、不依赖抓包、不依赖离线表**。

---

## 附录 A：OAS 引用索引（便于核对）

| 主题 | 文件 | 行区间 |
|---|---|---|
| 主循环 / 任务分派 | `OAS/script.py` | 645-728 |
| 连续失败 3 次升级 | `OAS/script.py` | 696-717 |
| 异常分派（UI/环境/其它） | `OAS/script.py` | 540-621 |
| 任务模块热导入 | `OAS/script.py` | 561-567 |
| 失败现场打包（60 帧 + 日志段） | `OAS/script.py` | 101-132 |
| 等待 + 配置重载检查 | `OAS/script.py` | 296-321 |
| 取下一个任务 | `OAS/script.py` | 323-346 |
| 异常谱系 | `OAS/module/exception.py` | 21-62 |
| 重试装饰器 | `OAS/module/base/retry.py` | 32-98 |
| 卡死计时器定义 | `OAS/module/device/device.py` | 29-30（`Timer(60)` / `Timer(300)`），126-163 |
| 卡死累积判定 | `OAS/module/device/device.py` | 126-163 |
| 点击去重判定 | `OAS/module/device/device.py` | 170-215 |
| 点击前控制校验 | `OAS/module/device/control.py` | 63-82 |
| 截图环形缓冲 | `OAS/module/device/screenshot.py` | 51-80, 109 |
| 调度队列（pending/waiting） | `OAS/module/config/config.py` | 177-216 |
| 取任务（按 next_run） | `OAS/module/config/config.py` | 218-242 |
| 延时/重载 | `OAS/module/config/config.py` | 292-383 |
| 成功/失败间隔 + `next_run` 计算 | `OAS/module/config/config_model.py` | 220-223, 450-470 |
| 配置 mtime 监听 | `OAS/module/config/config_watcher.py` | 10-41 |
| 日志文件/清理 | `OAS/module/logger.py` | 19-51, 132-165 |
| 进程级启停（terminate/join/kill） | `OAS/module/server/script_process.py` | 35-64 |
| WebSocket `/ws/{name}` | `OAS/module/server/script_router.py` | 204-236 |
| 模板匹配（ROI/阈值） | `OAS/module/atom/image.py` | 17-41, 219-265 |
| 多尺度匹配 | `OAS/module/atom/image.py` | 267-350 |
| 多目标匹配 | `OAS/module/atom/image.py` | 351-390 |
| 组合匹配器导出 | `OAS/tasks/GameUi/page.py` | 58 |
| 页面注册表 | `OAS/tasks/GameUi/registry.py` | 13-24, 69-91 |
| 页面识别回退 + 两帧确认 | `OAS/tasks/GameUi/navigator.py` | 159-174, 195-231 |
| 未知页关闭器 / 跳转失败阈值 | `OAS/tasks/GameUi/navigator.py` | 39-54, 790-890 |
| 重启游戏 + 登录 | `OAS/tasks/Restart/script_task.py` | 18-44 |
| `appear / appear_then_click / 多尺度点击` | `OAS/tasks/base_task.py` | 184-211, 213-243, 245-272 |
| `ui_get_reward / ui_click(超时)` | `OAS/tasks/base_task.py` | 718-758, 760-782 |

## 附录 B：本次只读验证做过的事（可复现）

1. `E:\Reverse` 递归搜索 `dbs|db|database` 目录、`*.db/*.sqlite` → 0 命中。
2. 用 `E:\Reverse\tools\lbix.py` 解码 `campaign_tbgoblintreasuremine.bytes`：36 行 / 104 字段 / UTF-8 中文可读。
3. 全量 1697 张表头部解析统计：1298 成功 / 399 失败（启发式解码器能力边界）。
4. 设备 `127.0.0.1:16384`：`/sdcard/Android/data/com.wjmtjq.ma.android/files/il2cpp/Metadata/global-metadata.dat` 可读；`/data/data/com.wjmtjq.ma.android/` 不可读（无 root）。
5. `Config/ProtoConfig/proto_schema.bytes`（PSB1）含 `C2s/S2c` 消息与字段名（如 `RewardStatus`），证实"领取状态"在服务端消息层。
6. `Config/WindowConfig/winConfig.json` 含 1002 个视图名 + prefab 路径（无坐标），可作"未知画面命名"的辅助，但不能替代模板坐标。

**第二轮（设备侧实测，全部可回退）**

7. `adb shell uiautomator dump /sdcard/wd.xml` → 2134 B / 6 节点，唯一业务节点是 `unitySurfaceView`（无 text/clickable）。
8. `MuMuManager setting -v 0 -k root_permission -val true` + `control -v 0 restart` + `adb root` → `uid=0(root)`；读 `/data/data/com.wjmtjq.ma.android/`：16 个 prefs、3 个空 sqlite、4 个 SDK 文件；**无钻石/抽卡/领取状态**。
9. root 后设备自带 `tcpdump`：`host 118.145.248.220` 每 3.00 s 一对 57 B；`-X` 首字节 `17 03 03 00 34` → 11019 端口上的 TLS；点击后出现 233 B + 249 B 服务端下推。
10. `settings put global http_proxy 127.0.0.1:8888` + `adb reverse tcp:8888 tcp:8888` + 本机监听 → 45 s **0 命中** → 游戏不读全局代理；因此未安装 CA。
11. 还原：`root_permission=false` + 重启 → `adb shell id`=`uid=2000(shell)`；`http_proxy=:0`；`reverse --list` 为空；游戏已重新启动到前台。
