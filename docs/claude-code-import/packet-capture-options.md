# 抓包 / 协议取数：三个外部方案的评估（《我叫MT：崛起》脚本）

> 评估时间：2026-11-03
> 评估基准（现场实测，不再推翻）：Unity 2022.3.62f3 + IL2CPP + XLua + YooAsset；主连接 `118.145.248.220:11019`，3.00 s 一对 57 B，载荷 `17 03 03`（TLS app data）；系统代理 + `adb reverse` 45 s 零命中；可开 root（`uid=0`），有 `tcpdump`/`ss`；`uiautomator` 只有 `unitySurfaceView`；OAS 与 MT 共用 5037 adb server（禁止 `kill-server`）。
> 包名注：设备实测 `pm list packages | grep wjmtjq` 返回 `com.wjmtjq.ma.android`（无 `1`）；下文命令按设备实际包名。
> 静态结论注：`network_security_config.xml` 信任用户 CA 是**静态分析结论**，本次未安装证书、**未验证**能否解密。

## 0. 总结论

| 来源 | 方法 | 判定 | 一句话原因 |
|---|---|---|---|
| cnblogs《WinDivert + Python 全流量嗅探》 | Windows NDIS 层拦截 + TCP/WebSocket 重组 + protobuf 解码 | **部分有用（仅旁证）** | 能证明流量与端口，但作者明确"不能解密 TLS"，而本案主连接正是 TLS |
| GitHub `huomiaocode/SocketPacket` | WinPcap 抓 TCP + 按端口用 proto 解析成 Message | **部分有用（仅旁证，且更旧）** | 同样不解密 TLS；依赖 WinPcap/PySide2/pywin32 + 预编译 proto，维护成本高 |
| CSDN《利用 adb 实现游戏脚本》 | `screencap` + `input tap` + `cv2.matchTemplate` | **没用（已是现状）** | 这就是 mtbot 现有做法，没有新增能力 |

**三条都解决不了本案的核心阻塞：TLS 明文。** 真正有增量的是"透明重定向 + TLS 中间人"（第 4 节 P0/P1），与这三篇无关。

## 1. 三篇原文讲了什么（均已实际抓取成功）

### 1.1 cnblogs：WinDivert + Python 全流量嗅探

- 作者做的是一个**零侵入**的游戏协议抓包工具：不改游戏、不注入进程、不要求先开工具再开游戏，运行中可随时开始/停止。
- 选型上比较了 WebSocket 代理、DLL 注入 Hook、TUN 虚拟网卡、**WinDivert**，最终用 WinDivert：工作在 Windows NDIS 层，可拦截任意进程的 TCP（新建/已建立都行），不用 hook、不用自己维护 TCP 状态机。
- 链路：网络层拦截 → 传输层解析（WebSocket / TCP）→ 应用层解码（protobuf / JSON / 自定义）；换项目只替换"应用层解码"。
- 明确边界：**仅 Windows、需管理员权限、不能解密 TLS、HTTP/3（QUIC）拿不到明文**。

### 1.2 GitHub `huomiaocode/SocketPacket`

- 一个 Windows GUI 抓包/解析工具：把 proto 文件放进 `protobuf/protos/Proto/`，跑 `gen-protos.py` 生成 py，再改 `ProtobufData.py` 配 **ip/port/headlen/endian**，即可抓该端口 TCP 并把二进制按 `protobuf.pbs.*_pb2` 解析成 Message。
- 依赖：PySide2、pywin32、**WinPcap**（需预装，仓库 `_files` 里带了一份）。
- 本质是"**WinPcap 抓包 + proto 反序列化 + Qt 展示**"，没有 TLS 解密能力，也没有 WebSocket 重组；头部长度/字节序要手工配。

### 1.3 CSDN：利用 adb 实现游戏脚本

- 作者写《阴阳师》脚本：`adb shell screencap -p` 截图 → `adb pull` 回电脑 → `cv2.matchTemplate(..., TM_CCOEFF_NORMED)`，`maxres > 0.9` 认为命中 → `adb shell input tap` 点击；用 `os.system` 调 adb。
- 就是"**截图 + 模板匹配 + 模拟点击**"的最小闭环，代码在 `IFrestart/YYS`。
- 没有任何网络/协议内容。

## 2. 逐条适用性

| 来源 | 能解决什么 | 前提条件 | 在本环境成立吗 | 风险 / 成本 |
|---|---|---|---|---|
| cnblogs WinDivert | 看"哪些进程/端口在通信、报文多大、频率多少"；若应用层是**明文** protobuf/WebSocket 可直接解 | Windows + 管理员 + WinDivert 驱动 + 协议/schema 映射 | **半成立**：抓得到包（模拟器流量走宿主 NDIS），但 11019 是 TLS，**只能看到密文**；与设备端 `tcpdump` 能力重叠 | 驱动安装/管理员权限；对 TLS 无解；维护"应用层解码"成本高 |
| SocketPacket | 同上的"按端口解析 proto" | Windows + WinPcap + PySide2/pywin32 + 预编译 proto + 手配 headlen/endian | **半成立**：能抓到 TCP，但 TLS 密文解不出；工具老、依赖重 | WinPcap 在新 Windows 上兼容性差；无维护；GUI 工具不适合自动化 |
| CSDN adb 截图 | 页面识别、点击 | adb + cv2 | **完全成立，但已实现**：mtbot `device.screenshot` + `template.find` 就是它 | 无新增风险；继续用它即可 |

共同硬约束（必须写清）：

1. **TLS 是不可绕过的一层**：三篇里只有第一篇明确说"不能解密 TLS"，另两篇同样没有 MITM 能力。
2. **代理路线已被实测否决**：`global http_proxy` + `adb reverse` 45 s 0 命中（见 `adb-data-probe.md` 4.3），所以"开个 HTTP 代理让游戏走代理"在本作不成立。
3. **设备端已有更便宜的替代**：root 后 `tcpdump`/`ss` 直接抓，不需要在 Windows 装 WinDivert/WinPcap。
4. **uiautomator 不可用**：任何"读控件"的方案都不成立，只能读像素。

## 3. "已试过 / 未试过"判定（带证据）

| 事项 | 判定 | 证据 |
|---|---|---|
| 系统代理（`http_proxy`）+ `adb reverse` | **这次试过，失败** | `docs/claude-code-import/adb-data-probe.md:208-228`：45 s 0 命中、`ss` 无 8888 连接 |
| 设备端 `tcpdump` 抓 11019 | **这次试过，成功但只到密文** | `adb-data-probe.md:169-204`；`stability-plan.md:238-247`（57 B/3 s、`17 03 03 00 34`） |
| `network_security_config` 信任用户 CA → "抓包可行" | **之前讨论过、只做了静态判断，没做** | `reverse-notes.md:50`、`184-186`、`206-209`；会话原句见 `C:\Users\123\.claude\projects\E--Reverse\2f73d9b2-9d16-4875-bf96-1a49317f8d7f.jsonl:297`："配合未发现证书固定，抓包分析可行" |
| 安装 CA / TLS 中间人解密 | **未做**（本次明确未装证书） | `adb-data-probe.md:174-179`（工具全缺）；`stability-plan.md:240` |
| `mitmproxy` / Charles / burp / Wireshark | **从未安装、从未使用** | 同上；本次 `Get-Command` + `pip list` 全 MISSING |
| WinDivert / SocketPacket / VPNService | **完全没碰过** | 全库 jsonl 检索无真实命中（`SocketPacket/WinDivert/VPNService` 在 E--Reverse 会话 0 条） |
| `iptables` 透明重定向 | **完全没碰过** | 同上 0 条 |
| Frida / Xposed / LSPosed | **没碰过**（提过"是否有 libfrida"的排查项，没做） | `reverse-notes.md:153`；jsonl 里 `FRIDA/XPOSED` 命中均在 base64 随机串中，属误命中 |
| 截图 + 模板匹配 | **已实现、正在用** | mtbot `device.py` + `template.py`；CSDN 文章只是同款 |
| 现在是否在跑抓包 | **没有**（无 `tcpdump`、无 8888/8080 监听；仅 MT GUI `mt.py --gui` 空闲） | 本次 `ps -A | grep tcpdump` 为空；`Get-NetTCPConnection` 无 8888/8080 |

## 4. 值得做的最小实验（按 收益/风险/工作量 排序）

> 前提：以下都**不改业务代码**；需要 root 的操作不重启实例；若 MT 脚本在前台跑，先停。

### P0（推荐）：证明 `iptables` 透明重定向可行（5 分钟，低风险）

收益：这是所有"绕开代理限制"方案的前置条件；只证明"能改道"，不解密、不装证书。
风险：游戏当前连接会被劫持 → 掉线重连一次（不需要重启实例）。
工作量：3 条命令 + 还原。

```powershell
$adb = "D:\Program Files\Netease\MuMu Player 12\shell\adb.exe"

# 0) 需要 root（本次实测 root 已复原为 false，需先 adb root；若失败再开 root_permission）
& $adb -s 127.0.0.1:16384 root
& $adb -s 127.0.0.1:16384 shell id          # 期望 uid=0(root)

# 1) 设备上开一个监听，记录"是否有连接被改道进来"
& $adb -s 127.0.0.1:16384 shell "rm -f /data/local/tmp/redir.log; (nc -l -p 9999 > /data/local/tmp/redir.log 2>&1 &)"

# 2) 把出站 11019 改写到本机 9999
& $adb -s 127.0.0.1:16384 shell "iptables -t nat -A OUTPUT -p tcp --dport 11019 -j REDIRECT --to-ports 9999"
& $adb -s 127.0.0.1:16384 shell "iptables -t nat -L OUTPUT -n | grep 11019"

# 3) 等一个心跳周期（≤5 s），看是否被改道
& $adb -s 127.0.0.1:16384 shell "ss -tnp | grep 9999; ls -l /data/local/tmp/redir.log"
```

判定：`ss` 出现 `127.0.0.1:9999` 的连接、且原 `118.145.248.220:11019` 长连接断开 → 改道成立。
还原（必须执行）：

```powershell
& $adb -s 127.0.0.1:16384 shell "iptables -t nat -D OUTPUT -p tcp --dport 11019 -j REDIRECT --to-ports 9999"
& $adb -s 127.0.0.1:16384 shell "pkill nc; rm -f /data/local/tmp/redir.log"
& $adb -s 127.0.0.1:16384 shell "iptables -t nat -L OUTPUT -n | grep 11019"   # 期望：空
# 若 root 是临时开的：MuMuManager setting -v 0 -k root_permission -val false + control restart
```

### P1（可选，成本高）：`mitmproxy` reverse 模式解 TLS

只有 P0 成立、且接受封号风险才做。收益是**唯一可能看到 11019 内层 protobuf** 的路径（包里已有 `proto_schema.bytes`）。
前提：宿主装 **一个** `mitmproxy`（`pip install mitmproxy`，不装其它）、生成 CA、把 CA 装进设备信任库、`adb reverse` + `iptables` 改写 11019 → 本机 8080、`mitmproxy --mode reverse:https://118.145.248.220:11019 --listen-port 8080`。
风险：证书安装通常需重启实例（游戏掉线）；若存在 pinning/双向认证会直接握手失败；反作弊可能识别；**未验证**。
工作量：30–60 分钟，且 CA 清理需要再重启一次。

```text
# 概要（未执行，仅方案）
pip install mitmproxy
mitmproxy --mode reverse:https://118.145.248.220:11019 --listen-port 8080
adb reverse tcp:8080 tcp:8080
adb shell "iptables -t nat -A OUTPUT -p tcp --dport 11019 -j REDIRECT --to-ports 8080"
# CA 安装（root）：push 到 /system/etc/security/cacerts/<hash>.0 或用户 CA 目录 → 重启
# 还原：删 CA 文件 + iptables -D + adb reverse --remove-all + 重启实例
```

### 明确不建议

- **WinDivert / SocketPacket**：在"已能 root + tcpdump"的本案里属于重复建设；且二者都不解密 TLS，拿不到业务字段。除非要做"Windows 侧长期旁路审计"，否则不值得。
- **CSDN 的截图+模板**：已是 mtbot 现状，没有增量；真正该做的是"两帧确认 / ROI 收敛 / 数字 OCR"，见 `stability-plan.md` 批 2。
- **VPNService / Xposed / Frida**：需要额外框架/改包/注入，维护与封号成本远高于收益；本案连控件树都没有，hook 也拿不到稳定业务字段（且会触碰反作弊）。

## 5. 还原清单（若执行 P0/P1）

| 改动 | 还原 | 校验 |
|---|---|---|
| `iptables` OUTPUT REDIRECT | `iptables -t nat -D OUTPUT ...` | `iptables -t nat -L OUTPUT -n` 无 11019 |
| 设备监听 `nc` | `pkill nc` | `ps -A | grep nc` 为空 |
| `adb reverse` | `adb reverse --remove-all` | `reverse --list` 为空 |
| 用户 CA | 删除对应 `<hash>.0` | 信任库列表无新增 |
| root 开关 | `root_permission=false` + `control restart` | `adb shell id` = `uid=2000(shell)` |

## 6. 还没验证的事

1. 11019 的 TLS 是否能被用户 CA 中间人成功解密（静态只说"信任用户 CA"，未见 pinning，但**未实测**）。
2. TLS 之内是 protobuf 还是二次加密（`proto_schema.bytes` 只是线索）。
3. 游戏是否检测代理/证书/root（反作弊强度未知）。
4. P0 改道是否会被游戏立刻识别为断线并触发风控。
5. WinDivert/SocketPacket 在 MuMu 12（Hyper-V 网络）下能否稳定抓到宿主侧流量（未测）。
