# mtbot 文档索引（docs/README.md）

本目录只放「怎么用 / 怎么验证 / 改过什么」的说明；业务代码全在 `E:\Reverse\auto_script\mtbot\`。

## 1. 目录结构

| 路径 | 用途 |
| --- | --- |
| `E:\Reverse\auto_script\mt.py` | CLI 入口（`--task` / `--profile` / `--gui`） |
| `E:\Reverse\auto_script\mtbot\` | 任务与页面逻辑（device/ui/vision/pages/tasks/scheduler/layout） |
| `E:\Reverse\auto_script\tools\verify_ui.py` | 实机验证工具：抓图、模板/金色带识别、可选点击、改前改后对比 |
| `E:\Reverse\auto_script\tools\watch_run.py` | 整轮盯梢：启动全量跑 + 每 2.5s 抓帧判页面 + 自动落证 |
| `E:\Reverse\auto_script\artifacts\verify\<问题编号>\` | 每个问题的改前/改后截图 + `report.txt`（识别得分、命中坐标、像素差） |
| `E:\Reverse\auto_script\artifacts\run\<时间戳>\` | 整轮实跑：`run.log`、`issues\<序号>_<类型>\`（截图 + `context.log`）、`watch.json` |
| `E:\Reverse\auto_script\templates\` | 模板匹配图（模板名必须带 `.png`） |
| `E:\Reverse\auto_script\config.json` | 设备与任务配置（`device.adb`、`device.serial`、`runtime.*`） |

历史交接文档在 `E:\Reverse\auto_script\docs\claude-code-import\`（Claude Code 会话整理，只读参考）。

## 2. 跑单个任务

```powershell
python -I E:\Reverse\auto_script\mt.py --list
python -I E:\Reverse\auto_script\mt.py --task daily,weekly --config E:\Reverse\auto_script\config.json
python -I E:\Reverse\auto_script\mt.py --profile daily --dry-run
python -I E:\Reverse\auto_script\mt.py --gui
```

任务名见 `mtbot/tasks/__init__.py` 的 `TASK_CLASSES`。

## 3. 实机验证工具

```powershell
# 抓当前画面 + 识别状态
python E:\Reverse\auto_script\tools\verify_ui.py --issue 07 --name now --state

# 模板识别（--tpl 可重复，模板名要带 .png）
python E:\Reverse\auto_script\tools\verify_ui.py --issue 07 --name tpl --tpl 标题_日常任务.png

# 金色按钮带（x0,y0,x1,y1）
python E:\Reverse\auto_script\tools\verify_ui.py --issue 07 --name band --bands 180,990,640,1180

# 真点一下（220ms 长按，规避短按 input tap 被忽略），并对比像素差
python E:\Reverse\auto_script\tools\verify_ui.py --issue 07 --name tap --press 431,1099 --prev 07/now.png

# 离线分析已有截图（不连设备）
python E:\Reverse\auto_script\tools\verify_ui.py --issue 07 --name off --image 07/now.png --bands 180,990,640,1180

# 找右上角红色关闭钮（输出中心点与建议命中点 cx-20, cy+10）
python E:\Reverse\auto_script\tools\verify_ui.py --issue 00 --name x --closex
```

adb 解析顺序：`config.json` 的 `device.adb` → `D:\Program Files\Netease\MuMu Player 12\shell\adb.exe` → `D:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe` → PATH 里的 `adb`。

> 注意：OAS 与本脚本共用同一个 adb server（5037）。**不要执行 `adb kill-server`**；掉线时用
> `adb disconnect 127.0.0.1:16384` + `adb connect 127.0.0.1:16384`。

## 4. artifacts/verify 组织

- 目录名用问题编号（`01`、`02`、`05`、`07`、`09`、`12`、`13`…）。
- 每张图命名 `<步骤>.png` / `<步骤>_after.png`；`report.txt` 由工具追加，含：
  `[shot]` 路径与分辨率、`[tpl]` 最佳分数、`[bands]` 金色带中心、`[press]` 坐标、`[diff]` 像素变化、`[state]`。
- 分辨率统一为 720×1280（MuMu 竖屏）；坐标均按该分辨率实测。

## 5. 整轮实跑 + 视觉盯梢（watch_run.py）

```powershell
# 一条命令：启动 36 任务全量（用副本配置）+ 本地盯梢
python E:\Reverse\auto_script\tools\watch_run.py --config E:\Reverse\auto_script\config.fullrun.json --interval 2.5 --task-timeout 240

# 只盯已有日志（不启动新进程）
python E:\Reverse\auto_script\tools\watch_run.py --ts 20261103_160000 --no-run
```

- `config.fullrun.json` 是 `config.json` 的副本（只改 `enabled`，原 `config.json` 不动）；
  不用时可以删掉，脚本默认仍读 `config.json`。
- 盯梢项：unknown 连续 ≥6 帧、同页 ≥120s、弹窗 ≥30s、金币/钻石数字变化、
  同坐标 30s 内重复点击 ≥3 次、任务报 OK 但画面没变。
- 证据：`artifacts\run\<ts>\issues\<序号>_<类型>\shot.png` + `shot_prev1~3.png` + `context.log`
  （含前后 15s 日志、当前任务、判定页面、资源裁图）。

## 6. 2026-11-03 修复速查

- 消费保护：`runtime.allow_diamonds`（默认 `false`）+ `BaseTask.may_spend()`；`task_retries`、`auto_recover` 同批加入。
- 稳定性：`scheduler._run_once()` 单任务超时（`max_task_minutes`）+ 重试 + 失败回主城。
- 领奖：日常/周常「一键领取 + 自动置顶」，不再下滑；签到用固定 5×3 网格 + 红飘带识别。

## 7. 2026-11-04 点击量化（不许「点了就算」）

- `runtime.click_verify`（默认 `true`）：每次点击后等 `click_verify_wait`（默认 1.2s）抓一帧，
  比较点击点 ±120px 区域的灰度变化，变化像素占比 < 2% 判「空点」。
- 空点会自动按 `(0,-8) (0,+8) (0,-16) (0,+16)` 重试，最多 `click_retry`（默认 2）轮；
  命中后把该 `(页面|按钮)` 的偏移写进 `artifacts\run\<ts>\calib_learned.json`。
  导航类点击（点空白/返回/关弹窗）传 `expect="none"`，不参与校验。
- 流水：`artifacts\run\<ts>\clicks.jsonl`，每行含 `task/page/btn/raw/used/hit/diff/attempt`。
- 空点证据：`artifacts\run\<ts>\issues\click_<n>_<页面>_<按钮>\{before.png,after.png,info.txt}`。
- 静态补偿表：`mtbot\layout.py` 的 `CLICK_CALIB`（key 为 `"页面名|按钮名"`，value 为 `(dx,dy)`）。
- 跳过点：切页/识别/前置页失败一律 `log.warning` 写明任务/页面/坐标/判定值；
  日常页签按 `tab[1], -25, -50, -75` 四个候选 y 逐个试，仍失败就回退主城重进再判一次。

## 8. 战斗态纪律（2026-11-04 定）

**战斗进行中一律不点任何 UI，只等结算出现**；识别与点击只在非战斗态做。
原因：战斗画面持续动画，`click_verify` 会把「动画变化」当成命中，坐标补偿因此一路漂移
（实测 tower 的 `(655,900)` 从 900 漂到 860，撞上「暂停」→ 弹「退出战斗」→ 被计成失败）。
若战斗/结算中偶发确认弹窗，只点左侧「取消」，绝不点右侧确定。

