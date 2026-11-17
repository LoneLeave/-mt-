# 安装包逆向关注点（交接文档）

来源：`E--Reverse\2f73d9b2-9d16-4875-bf96-1a49317f8d7f.jsonl`（静态分析全过程）、`E--Reverse\d89e8cea-7b94-4b9f-8036-5b582976472c.jsonl`（资源导出）。
旁证（本地既有产物，非本次对话生成但内容一致）：`E:\Reverse\逆向发现.md`、`E:\Reverse\抽卡概率.md`、`E:\Reverse\tools\INDEX.md`、`E:\Reverse\tools\lbix.py`。
标注「对话中未提及」= 会话里没有做/没有说，别当成结论。

---

## 1. 样本与产物

| 项 | 值 |
|---|---|
| 样本 | `E:\Reverse\com.wjmtjq1.ma.android_3867.apk`，351,204,386 字节（335 MB） |
| 应用 | 《我叫MT：崛起》 |
| 包名 / 版本 | `com.wjmtjq1.ma.android` / 1.1.6（versionCode 6）；**注意模拟器里装的是 `com.wjmtjq.ma.android` v1.0.5.186（另一个渠道包）**，两者不是同一包 |
| minSdk / targetSdk | 21 / 30 |
| 引擎 | Unity 2022.3.62f3，IL2CPP + XLua（脚本 Lua）+ YooAsset（资源） |
| 热更 | HybridCLR 风格热更 DLL（`HotfixLogic` / `AOTRefData`） |
| 渠道 | `pfid/channelid = 9699`，域名 `5151app.com` |
| 签名 | 广州 XINGJIA 自签证书（渠道重签名，非原厂） |

产物目录：
```
E:\Reverse\
├─ export\Art\            美术/音频/模型（对话中为 7,903 文件 / 523.8 MB；tools\INDEX.md 后续复核为 11,241 文件 / 622 MB）
├─ export\GameData\       配置表 / Lua / DLL / 协议 schema
├─ export\Catalog.csv     资源清单（路径 → bundle → 类型）
├─ export\Catalog_summary.json
├─ tools\                 扫描/导出/裁剪/模板脚本（见 §4）
├─ auto_script\           游戏脚本（另见 game-script.md）
├─ apk_meta\              包体元数据
├─ 逆向发现.md / 抽卡概率.md / pool_summary.txt / gacha_rates_summary.txt
```

---

## 2. 结论先行：这个包的防护强度基本为零

| 检查项 | 结果 |
|---|---|
| DEX 加壳（StubApp/梆梆/360/网易易盾/阿里加固） | **未命中任何壳特征** |
| 反外挂 so（ACE/易盾类） | `lib/` 下只有 il2cpp、unity、xlua、Bugly、RMonitor 等常规库 |
| `global-metadata.dat` | 14 MB，magic `AF1BB1FA` 标准，143,861 条可读字符串，Il2CppDumper 可直接用 |
| AssetBundle | 405 个全为明文 `UnityFS`，LZ4HC，无自定义加密/偏移 |
| Lua | 1,552 个 `.txt`，17 MB，**全明文** |
| 热更 DLL | `GameData/HotfixDlls/HotfixLogic/` 18 个（26.5 MB），标准 `MZ`/`BSJB`，dnSpy/ILSpy 可直接反编译 |
| 客户端配置 | 1,697 张 `LBIX` 二进制表 + 47 张服务端 Lua 表（5.1 MB），全部明文 |
| 协议 | `Data/Config/ProtoConfig/proto_schema.bytes`（`PSB1` 头）+ `luaresource/config/protoMap.txt` |
| 调试残留 | `IngameDebugConsole.Runtime.dll`、`LuaPanda.txt`（连 `127.0.0.1:8818`）、`main_debugMode.txt`、GM 字符串 |
| 网络信任 | `res/xml/network_security_config.xml` **显式信任用户 CA**（`<certificates src="user"/>`）→ 抓包可行 |

> 这意味着：**静态分析几乎无门槛**；难点在「表结构与数值含义」，不在「破保护」。反过来做防护评估时，这几项若命中任何一个（壳、加密 bundle、加密 Lua、非标准 DLL），后续路线要整体换。

---

## 3. 关键技术细节

### 3.1 UnityFS 版本伪装（YooAsset 常见坑）
- 405 个 bundle 都是 `UnityFS` + LZ4HC，但 **header 里的版本串被写成 5.x.x**，与引擎 2022.3 不符。
- UnityPy 遇到这种头会报「不支持的版本」或解出空对象。**解法：手动设置 `FALLBACK_UNITY_VERSION = "2022.3.62f3"`**，再 `Environment.load(path)` 遍历 `objects`。
- 资源清单用 `Catalog.csv` 建立「资源路径（如 `Assets/GameAssets/Prefabs/UI/UI2/main_icon/...`）→ bundle → 类别」映射，避免盲目遍历 405 个包。

### 3.2 配置表 LBIX（Luban 风格）格式
`tools\lbix.py` 已实现，结构：
```
[1 byte] idxCount
[4 bytes] "LBIX"
[varint] fieldCount
idxCount × ( key , offset )      // key 可能是 int 或 length-prefixed string
[data ...]                        // offset 相对 data 起点
```
- 变长整数编码（非标准 varint）：
  ```
  <0x80            → 1 字节，值 = b
  <0xC0            → 2 字节，(b&0x3F)<<8 | b[+1]
  <0xE0            → 3 字节，(b&0x1F)<<16 ...
  <0xF0            → 4 字节，(b&0x0F)<<24 ...
  <0xF8            → 5 字节，(b&0x07)<<32 ...
  ```
- 键类型需试两种模式（int / str），用「偏移递增且落在数据区内」做校验（`choose_mode`）。
- 字段值靠启发式区分字符串与整数（长度 ≤60 且可打印/含中文 → 字符串）。这是**够用但不完备**的解析，遇到嵌套结构需按表结构再精读。
- 可对照 `Data/Config/ProtoConfig/proto_schema.bytes` 与 Hotfix DLL 里的字段定义验证字段含义（抽卡概率就是这么核对的）。
- 地图数据例外：`SceneGridMap_100101.bytes` 等是 **JSON 明文**，不必走 LBIX。

### 3.3 数值结论（仅限本样本，1.1.6 客户端配置）
> 服务端可能覆盖，以游戏内公示为准。

- **抽卡（主卡池）**：普通召唤 SSR **12%** / SR **20%** / R **68%**；积分召唤 648 积分必出先天传奇；阵营抽卡文案「必出传奇」。
- **单英雄概率**：品质命中后按池内权重分配 —— R 池 6 人约 11.33%/人；SR 池 11 人 0.99%–2.67%；SSR 池 56 个有效权重，**0.003%–1.12%**，多数 0.2%–0.7%；UP 池最高约 **2.01%**/抽。
- **未启用的新池** `drawcard261`（GameLogic 只引用 `cfg.drawcard`）：普通召唤 1%/3%/96%，限时召唤 5%/20%/75%。→ 若线上切配置，体感会明显变差。
- **伤害公式**（Lua `BaseEntity:calcRealDamage` + `BuffComponent`）：
  - 暴击率 = `(Crit - Rcrit)/10000`，区间 [0,1]
  - 暴击伤害 = `1.5 + CriAdd * 0.00005`
  - 减伤 = `atk / (atk*1.25 + def*3)`
  - 除暴击外**没有随机浮动**
  - 阵营克制 ±10%（`FightConst.txt:522`）
- **战力压制**：战力差 >15% 触发；压制值 = `3 + floor((gap-15)/5)*3`，上限 30；`_suppressDrr = 1 - suppress*0.01`；只在特定玩法里启用。
- 其他抽奖：专武打造最高档 0.6%–2.4%；神器召唤 80/9.4/9/1/0.6；战宠唤灵 50/40/10；许愿池碎片传奇 55%。
- 表规模：英雄 89 条、怪物约 3,790、技能 511、Buff 1,786、被动特效 1,913、测试战报 140 份。

### 3.4 战斗内核可离线跑
- `SharedSource/Battle/` 是完整战斗模拟，入口清单 `OFFLINE_BATTLE_DOFILE`；`ClientSource/Lua/clientFightManager.txt` 负责战报序列化；`FightVerify.txt` 做客户端战报校验（输出上下限）；`fightRecordReport.txt` 生成逐帧战报。
- Lua 由 TS→Lua 转译（`Halliwood/ts2lua`），部分语法依赖 `_ts_*` 辅助函数；用 Lua 5.3/5.4 加载需补这些辅助。
- **意义**：可以脱离真机做「算伤害/算胜负」的离线沙盘，也能用来生成关卡目标与掉落期望。

### 3.5 美术导出的两个硬事实
1. **玩法页标题不是贴图**：标题是 TTF 文字 + 描边/渐变渲染（`NewArtFont` 里只有战斗数字位图字体）。扫 5,041 张 UI 图也找不到标题图块 → 标题模板只能用 720×1280 真机截图 1:1 裁切（已收录 `E:\Reverse\auto_script\mtbot\templates\标题_*.png`）。
2. **Sprite 导出必须保留 alpha**：用 UnityPy 导 `m_Sprite` 时按 `Texture2D` + `rect/offset` 裁切，4,921 张带透明通道，23 秒、0 错误；不带 alpha 的 UI 图做模板会大面积误命中。

---

## 4. 工具链（都是本地已成型、可直接复用）

| 脚本 | 作用 |
|---|---|
| `tools\scan.py` | 扫包/目录，统计 bundle 与类型分布（对话中扫出 410，报告写 405，差 5 个疑似非 UnityFS 或重复） |
| `tools\parse_manifest.py` | 解析 `Catalog` / `apk_meta` |
| `tools\export_assets.py` | 全量导出（贴图/文本/音频/字体/视频） |
| `tools\export_sprites.py` | 只导 Sprite（带 alpha），产模板素材 |
| `tools\export_meshes.py` | 导 663 个 OBJ 模型 |
| `tools\export_builtin.py` | 导 Unity 内置资源（默认字体/着色器等） |
| `tools\analyze_sprites.py` / `find_ui_sprites.py` / `find_more_sprites.py` | 从导出结果里筛 UI 图标/入口图标 |
| `tools\build_stage_templates.py` / `make_new_templates.py` | 生成/裁剪模板 + 缩放配置 json |
| `tools\make_catalog.py` / `preview_sheet.py` / `template_sheet.py` | 资源清单、预览图 |
| `tools\lbix.py` | LBIX 解码（`python tools/lbix.py <bytes> [key]`） |
| `tools\adb_mumu.py` | MuMu adb 封装（截图/点击） |
| `tools\pylibs\` | 打包的 dnfile / pefile 等依赖 |

环境：`C:/Users/123/.conda/envs/Reas/python.exe`（已装 UnityPy）；`dnfile` 用于读 .NET metadata 的 schema（Hotfix DLL 的字段名就是靠它读出来的）。

导出量（对话中）：
```
7,903 个文件 / 523.8 MB
├─ 图片 6,759 PNG   ├─ 模型 663 OBJ   ├─ 音频 114 WAV
├─ 字体 5 TTF       ├─ Spine 361      ├─ 视频 1
└─ GameData 3,338 个（含 1,552 个 Lua）
```

---

## 5. 逆向时的重点检查清单（可套用到其它安装包）

按顺序做，前面的结论决定后面值不值得做。

### 第一步：定位与身份（10 分钟）
- [ ] 包名、versionName/Code、minSdk/targetSdk
- [ ] 签名：是否渠道重签（本样本 XINGJIA 自签 ≠ 原厂）；多渠道包差异（本样本 `com.wjmtjq1` 与 `com.wjmtjq` 是不同渠道）
- [ ] `assets/AppConfig.json`、渠道号、上报/日志域名
- [ ] 权限与第三方 SDK 清单（判断数据面与风控面）

### 第二步：保护评估（决定后续路线）
- [ ] DEX 是否加壳（StubApp / 梆梆 / 360 / 易盾 / 阿里）
- [ ] `lib/` 是否有反外挂 so（ACE/易盾类）、是否有 `libfrida`/`ptrace`/反调试字符串
- [ ] `global-metadata.dat` 是否加密（magic 是否 `AF1BB1FA`，大小是否异常）
- [ ] AssetBundle 是否加密/偏移/自定义 UnityFS
- [ ] Lua 是否字节码/加密（本样本明文）
- [ ] 热更 DLL 是否标准 .NET（`MZ`/`BSJB`）
- [ ] 完整性校验 / 签名校验 / 模拟器检测（**本样本对话中未深入**，只判断了「客户端无专门反外挂模块」）

### 第三步：引擎与元数据
- [ ] 引擎版本（`globalgamemanagers` / `data.unity3d` 里的版本串）
- [ ] IL2CPP：`libil2cpp.so` + `global-metadata.dat` → Il2CppDumper → `dump.cs` / `il2cpp.h`
  ```bash
  Il2CppDumper.exe libil2cpp.so global-metadata.dat out/
  ```
  （本样本为「建议的下一步」，对话中未实际跑）
- [ ] Mono/XLua：先看 `assets/bin/Data/Managed` 与 Lua 目录
- [ ] 热更方案：HybridCLR / tolua / xlua / 自研；DLL 用 dnSpy 反编译

### 第四步：资源
- [ ] 走 `Catalog` 清单而不是盲扫；记录「bundle 数、类型分布、异常包」
- [ ] UnityPy 遇到版本头异常 → 设 `FALLBACK_UNITY_VERSION`
- [ ] Sprite 导出保留 alpha + `rect/offset` 裁切
- [ ] 记录：**文字标题不是贴图**，别浪费时间在美术资源里找标题

### 第五步：配置表
- [ ] 判断表格式：Luban（LBIX）/ protobuf / 自定义二进制 / JSON
- [ ] 先解 header（magic + 索引 + 字段数），再试键类型
- [ ] 用 DLL 里的字段定义或 proto schema 反证字段含义
- [ ] 关注「客户端有但未启用」的表（`drawcard261` 这种，往往是下一版/灰度配置）

### 第六步：协议与网络
- [ ] `proto_schema.bytes`（PSB1）+ `protoMap.txt` → 消息名与字段
- [ ] `network_security_config.xml` 是否信任 user CA（本样本信任 → 抓包可行）
- [ ] 是否有证书 pinning / 双向认证（**本样本对话中未提及**，需实测）
- [ ] 抓包与协议对齐（**本样本对话中未做**，只有 schema 静态材料）

### 第七步：服务端校验与风控面
- [ ] 客户端战报校验逻辑（本样本 `FightVerify.txt` 输出上下限）
- [ ] 是否存在 GM/调试入口（本样本：`GMView`、`@gmcall`、`@additem`、`LuaPanda` 8818、`IngameDebugConsole`）
- [ ] 高熵未知块（本样本 `assets/znslae.dat`，307,560 字节、熵 7.99、头 `01 06 03 00`，用途未明）
- [ ] 测试残留（内网地址 `10.10.5.223`、`127.0.0.1:32528`、`test.txt`、`reportm201.report.dev`）

### 第八步：合规判断（做之前先停一下）
- 只操作自有账号/自有设备；不做内存修改、协议伪造、GM 调用、反检测对抗、真钱商品套利。
- 用户协议明确禁止反向工程；本次会话的定位是「静态理解 + 本地自动化」，遇到上述红线不越界（对话中助手也拒绝过「外挂式自动化」）。

---

## 6. 未完成 / 未验证

| 项 | 状态 |
|---|---|
| Il2CppDumper 还原类型与方法 | 只作为「建议下一步」，**未执行** |
| dnSpy/ILSpy 反编译 `HotfixLogic/*.dll` 并导出 C# 工程 | **未执行**（只确认 DLL 头标准、可反编译） |
| 解析 `proto_schema.bytes` + 抓包对齐 | **未执行**；schema 与 protoMap 已在包内定位 |
| `znslae.dat` 用途 | **未定论**（高熵块，可能是加密资源/存档/反作弊数据） |
| 证书 pinning / 双向认证 | **对话中未提及**（仅知 network_security_config 信任 user CA） |
| 抓包实操、模拟器检测对抗、完整性校验绕过 | **对话中未提及**，不应假设可行 |
| `scan.py` 扫出 410 个 bundle 与报告的 405 有 5 个差异 | 未逐一定位（疑似非 UnityFS 或重复计入） |
| 美术文件数 | 对话中 7,903 / 523.8 MB，tools\INDEX.md 复核 11,241 / 622 MB（统计口径不同，unsure） |
| 1.1.6 与已安装 1.0.5.186 的差异 | **未对比** |

---

## 7. 如果换一个包，最短路径

1. `apktool d` / 直接解压看 `assets/`、`lib/`、`AndroidManifest.xml` → 判引擎与加固。
2. 有 `global-metadata.dat` → 先 `Il2CppDumper`；有 `lib/*.lua`/`.txt` → 先看脚本（往往比反编译更快拿到业务逻辑）。
3. 有 `*.bundle` / `data.unity3d` → UnityPy（版本头异常就设 `FALLBACK_UNITY_VERSION`）。
4. 有二进制表 → 先判 magic：`LBIX` 用 `tools\lbix.py`，`PSB1` 是 protobuf schema，JSON 直接读。
5. 能拿到 schema + 明文 Lua，基本可以不抓包就把业务跑通；抓包只用于校验服务端差异。
