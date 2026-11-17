# adb 数据探测实测记录（《我叫MT：崛起》/ MuMu 12 / 127.0.0.1:16384）

> 时间：2026-11-03 13:0x~13:2x（本地 Asia/Shanghai）
> 目的：按用户澄清，「dbs」= **adb** 的笔误；实测 adb 到底能拿到哪些运行时信息，以及 root / 抓包的边界。
> 约束：未改业务代码；未 `adb kill-server`（与 OAS/MT 共用 5037 server）；所有设备侧改动均已还原。
> 敏感信息（手机号、token、uid 可识别部分）在本文件中已脱敏。

工具路径（本机 PATH 里没有 adb）：

```powershell
$adb = "D:\Program Files\Netease\MuMu Player 12\shell\adb.exe"
$mm  = "D:\Program Files\Netease\MuMu Player 12\nx_main\MuMuManager.exe"
```

---

## 1. uiautomator 控件树（硬结论：不可用）

```powershell
& $adb -s 127.0.0.1:16384 shell uiautomator dump /sdcard/wd.xml
# UI hierchary dumped to: /sdcard/wd.xml
& $adb -s 127.0.0.1:16384 pull /sdcard/wd.xml
# 2134 bytes
```

`wd.xml` 全文只有 6 个节点，最内层：

```xml
<node index="0" text="" resource-id="com.wjmtjq.ma.android:id/unitySurfaceView"
      class="android.view.View" package="com.wjmtjq.ma.android"
      content-desc="Game view" checkable="false" checked="false"
      clickable="false" enabled="true" focusable="true"
      bounds="[28,0][691,1280]" />
```

结论：

- **没有任何 `text`**；**没有除 `unitySurfaceView` 之外的 `resource-id`**；**没有 `clickable=true`**。
- Unity 把 UI 全部画进 SurfaceView 的像素里，Accessibility/uiautomator 看不到。
- 因此「按控件 id 点击 / 读控件文字」在本游戏上不可行，不是"还没试"。

---

## 2. dumpsys / logcat（只能证明存活与前台）

```powershell
& $adb -s 127.0.0.1:16384 shell "dumpsys activity activities | grep topResumedActivity"
# topResumedActivity=ActivityRecord{... u0 com.wjmtjq.ma.android/com.unity3d.player.UnityPlayerActivity t417}

& $adb -s 127.0.0.1:16384 shell "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'"
# 输出为空（Android 12 该字段未命中），但窗口列表里 isVisible=true

& $adb -s 127.0.0.1:16384 shell "logcat -d | grep Unity | tail -5"
# I Unity : [FrameRate] measured fps=72.0 ...
```

外置日志 `/sdcard/Android/data/com.wjmtjq.ma.android/NvnCache/Log/NvnLog_2026-11-03_10-08-17.txt`：
31969 行 / 4.18 MB，尾部仍全是 `[FrameRate]`。

结论：

- **可用**：前台判定（`topResumedActivity`）、存活、帧率；
- **不可用**：业务状态（奖励、余额、抽卡、任务进度）——一条都没有。

---

## 3. root 实测（成功，但业务状态不存在于本地文件）

### 3.1 开 root

```powershell
& $mm info -v 0
# is_android_started:true / player_state:start_finished / adb_port:16384 / pid:34032（开 root 前）

& $mm setting -v 0 --all_writable | Select-String root
# "root_permission": "false"

& $mm setting -v 0 -k root_permission -val true
# {"root_permission":"true"}

& $mm control -v 0 restart
# {"errcode":0,"errmsg":""}

# 注意：仅重启实例后 `adb shell id` 仍是 uid=2000(shell)，必须再执行 adb root
& $adb -s 127.0.0.1:16384 root
& $adb -s 127.0.0.1:16384 shell id
# uid=0(root) gid=0(root) ... context=u:r:su:s0
```

设备侧自查（root 后 `su` / `tcpdump` / `ss` 都出现）：

```powershell
& $adb -s 127.0.0.1:16384 shell "ls /system/xbin/su /system/bin/su; which ss netstat tcpdump"
# /system/bin/su
# /system/xbin/su
# /system/bin/ss
# /system/bin/netstat
# /system/bin/tcpdump
```

### 3.2 `/data/data/com.wjmtjq.ma.android/` 内容

```powershell
& $adb -s 127.0.0.1:16384 shell "ls -la /data/data/com.wjmtjq.ma.android/"
```

| 目录 | 文件数 / 内容 |
|---|---|
| `shared_prefs` | 16 个 xml（Bugly、RMonitor、TapSDK、YouYi、`cl_jm_file.xml`、`yjsdk.xml.xml`、`playerprefs` 等） |
| `databases` | `bugly_db_`(69632)、`cl_jm_database.db`(28672)、`rmonitor_db`(36864) + 3 个空 journal |
| `files` | `TapEvent_persistedData`(49)、`tapsdk/events.db`(6120)、`bugly_last_us_up_tm`(13)、`native_record_lock`(0) |

### 3.3 关键字段（具体文件 + 字段名）

`shared_prefs/com.wjmtjq.ma.android.v2.playerprefs.xml`：

```text
10tjlbi8o1i00user_store = {"4561":{"server_id":"4561","level":138,"avatar":"2002","actorname":"火球呼脸"}}
db6vj1g013k8p7atArenaSimpleView_TodayEntered = 1793630690
db6vj1g013k8p7atThousandLotteryAction = 1
db6vj1g013k8p7atFuncLimitGiftIconBtn =（空/时间戳类）
db6vj1g013k8p7atSunkenTreasurePopUpView = 13
db6vj1g013k8p7atPopupScheduler_FuncOpenShown = 2031,2029
db6vj1g013k8p7at_10tjlbi8o1i00_4561CROSS_GUILD_PRECHECK_KEY = {"Setting":1,"Day":"2026.10.25"}
unity.player_session_count = 66
unity.player_sessionid = 1116487234667188705
```

`shared_prefs/cl_jm_file.xml`：

```text
cl_jm_b1 = gdapi.a5b.cc          # API 域名
cl_jm_a5 = 2.3.7.4               # SDK 版本
cl_jm_a9 = 300013296490
cl_jm_a2 = 29abc93...755690      # token/hash 类
cl_jm_c4 = cbc6c08...147143
cl_jm_f5 = b49be3d...755690
cl_jm_c9 = wROJbq6rhgvIVGSwWKuAkUq6j5slAWdt
cl_jm_c3 = fAWN7eLX
cl_jm_c7 = E76CDE8804907C453369033CCF8F8124
```

`shared_prefs/yjsdk.xml.xml`：

```text
yl_user_bean = {... "uid":"10tjlbi8o1i00", "username":"156****8830", "token":"ZXlKaGJHY2lPaUpJVXpJMU5pSXNJblI1Y0NJNklrcFhWQ0o5..." ...}
# token 为 base64(JWT)，头 {"alg":"HS256","typ":"JWT"}
```

`shared_prefs/YouYiData.xml`：`loginMethod=mobile`、`androidId`、`devid`，登录数据是 Java 序列化（`rO0AB...`）。

`databases/*.db`（用 Python sqlite3 解析，3 个库完全一样）：

```text
sqlite_master 只有 1 张表：
  android_metadata(locale TEXT) rows=1 → ('zh_CN',)
业务表数量 = 0
```

### 3.4 结论

- **root 本身可行**：`root_permission=true` + 重启 + `adb root` → `uid=0`。
- **能读到**：账号/区服/等级/昵称、SDK 域名与身份、客户端"弹窗是否已弹过/玩法今天是否进过"的 UI 去重标志。
- **读不到**（明确不存在）：钻石余额、抽卡记录、奖励领取状态。3 个 sqlite 全是空库；`files` 只有埋点/崩溃数据。
- 因此 root 只适合**人工排障取证**，不能作为脚本的生产数据源。

---

## 4. 抓包实测（能看到"有流量"，看不到明文）

### 4.1 本机抓包工具盘点

```powershell
foreach ($t in @('mitmproxy','mitmdump','charles','burp','fiddler','wireshark','tshark')) {
  if (Get-Command $t -ErrorAction SilentlyContinue) { "FOUND $t" } else { "MISSING $t" }
}
python -m pip list | Select-String -Pattern 'mitm|proxy|scapy|dpkt'
```

结果：**全部 MISSING**（未安装任何工具，也未擅自安装）。

### 4.2 设备连接与流量形态

```powershell
& $adb -s 127.0.0.1:16384 shell "ss -tunp | head -40"
# 游戏进程 pid 2733：
# ESTAB 10.0.2.15:56114 -> 118.145.248.220:11019   （长连接，非 443）
# CLOSE-WAIT/ESTAB -> 180.188.25.47:443、114.117.136.36:443、101.200.62.185:443 等
```

```powershell
& $adb -s 127.0.0.1:16384 shell "tcpdump -i wlan0 -nn -c 40 -s 200 'tcp and host 118.145.248.220' 2>/dev/null"
# 13:12:15.370 10.0.2.15.56114 > 118.145.248.220.11019: Flags [P.], length 57
# 13:12:15.400 118.145.248.220.11019 > 10.0.2.15.56114: Flags [P.], length 57
# ...每 3.00 秒一对，收发对称...
```

```powershell
& $adb -s 127.0.0.1:16384 shell "tcpdump -i wlan0 -nn -c 6 -s 260 -X 'tcp and host 118.145.248.220 and port 11019' 2>/dev/null"
# 0x0020: 5018 ffff 7bd0 0000 1703 0300 342c 9f8d
#                            ^^^^^^^^^^^^ = TLS record: type=0x17(app data), ver=0x0303, len=0x0034(52)
```

- **主连接是跑在 11019 端口上的 TLS**（不是明文自定义协议），3 秒一次 57 字节心跳。
- 交互（点击关闭签到弹窗）后同一连接出现 **233 B + 249 B** 服务端下推（13:15:28），说明交互 → 实时服务端数据，但全是密文。
- 内层帧格式（TLS 之内）未知，需要中间人 + 再逆向才有机会。

### 4.3 HTTP 代理实验（游戏不采纳）

```powershell
# 本机监听 127.0.0.1:8888（仅记录请求首行，不做 MITM）
Start-Process python -ArgumentList "...\probe\proxy_logger.py"

& $adb -s 127.0.0.1:16384 reverse tcp:8888 tcp:8888
& $adb -s 127.0.0.1:16384 shell "settings put global http_proxy 127.0.0.1:8888"
& $adb -s 127.0.0.1:16384 shell "settings get global http_proxy"
# 127.0.0.1:8888
```

结论（45 秒后检查）：

```text
proxy 日志：只有 listener up，无任何连接
adb shell "ss -tnp | grep 8888"：No matches
```

→ 游戏**不读取 Android 全局代理**（Unity/BestHTTP 自建连接）。
→ 「HTTP 代理 + 安装用户 CA」这条常规解密路径在本游戏上**不成立**；CA **未安装**，因此无需移除。

---

## 5. 在线证据链（状态从画面读，实拍）

同一次会话：

| 时刻 | 画面 | 关键读数 |
|---|---|---|
| 13:13 | 每日签到「获得奖励」弹窗 | 顶部金币 `262233`、钻石 **`254`**、奖励`阵营核心` |
| 13:15（点击空白处后） | 签到页 | `已签到次数：22/31`、第 22 天 `再领一次 充值5`、钻石仍 `254` |

结论：钻石余额、签到进度、弹窗内容**都在画面像素里**，可用固定 ROI + 数字模板/OCR 读取；这是唯一可行的"在线实时验证"数据源。

---

## 6. 还原（全部已执行并校验）

| 步骤 | 命令 | 校验结果 |
|---|---|---|
| 关 root 开关 | `& $mm setting -v 0 -k root_permission -val false` | `--all_writable` → `"root_permission": "false"` |
| 重启实例 | `& $mm control -v 0 restart` | `{"errcode":0}` |
| 重新 connect | `& $adb connect 127.0.0.1:16384` | already connected；`sys.boot_completed=1` |
| 验证非 root | `& $adb shell id` | `uid=2000(shell) ... context=u:r:adbd:s0` |
| 清代理 | `settings put global http_proxy :0` | 读回 `:0` |
| 清 reverse | `& $adb reverse --remove-all` | `reverse --list` 为空 |
| 清设备临时文件 | `rm -f /sdcard/wd.xml /sdcard/cap1.txt /sdcard/shot*.png` | 已删除（其它 png 属另一会话，未动） |
| 恢复游戏前台 | `am start -n com.wjmtjq.ma.android/com.unity3d.player.UnityPlayerActivity` | 进程存在，`topResumedActivity` = UnityPlayerActivity |

中断说明：开 root 与关 root 各触发一次实例重启（共 2 次），游戏期间退出，已重新拉起。

---

## 7. 尚未验证 / 不要当成结论的点

1. 11019 端口 TLS **内层**的帧格式与是否二次加密——未验证。
2. `uiautomator` 的结论只覆盖当前版本/当前 Activity；若游戏未来改成原生 UI 控件，结论会变。
3. 抓包只证明"TLS 心跳 + 交互有下推"，未证明具体业务消息内容。
4. root 读取到的 `ThousandLotteryAction`、`ArenaSimpleView_TodayEntered` 等是否**等价于**"今天已抽/已进"，只按命名推断，未做行为对照实验。
5. 长期开 root 对账号的影响、以及被反作弊识别的风险，未验证。
6. 数字 OCR 的精度/延迟未实测（只做了人工读图）。
