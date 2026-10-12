# WeChat-ServiceAccount-Purge (PC 微信“服务号”一键彻底清空补丁)

> **让 PC 微信右键“服务号 -> 删除”真正清空所有服务号子会话与历史聊天记录，不再反复重现。**

![Platform](https://img.shields.io/badge/Platform-Windows_x64-0078D6)
![Weixin](https://img.shields.io/badge/Weixin-4.1.15.51-07C160)
![Python](https://img.shields.io/badge/Python-3.8%2B_Zero_Deps-F7DF1E)
![License](https://img.shields.io/badge/License-All_Rights_Reserved-red)

---

## 😫 原版痛点

在 PC 微信 4.x（Qt 架构，`Weixin.dll`）中，**“服务号”**（`brandservicesessionholder`）是一个折叠了众多服务号消息的聚合盒子：

1. 当你在主界面右键点击 **“服务号 -> 删除”** 时，微信仅弹窗提示 `删除与“服务号”的聊天？`（故意隐藏了副标题 `删除聊天后，聊天记录也将被清空。`）。
2. 点击确认后，微信底层仅删除了 `"brandservicesessionholder"` 这一行外层入口，**盒子里成百上千条服务号子会话及历史消息记录完全没有被删除**。
3. 一旦有任何一个服务号发来新消息，“服务号”盒子就会重新出现，点进去会发现**此前所有的历史服务号和旧消息全部原封不动地留在里面**，只能点进去逐条手动右键删除，极其繁琐。

---

## ✨ 补丁效果

本工具通过逆向分析 `Weixin.dll` 的会话管理与删除流水线，仅用 **3 处原生指令级微补丁（无需注入第三方 DLL，零外部依赖）** 实现最符合直觉的原生体验：

| 行为对比 | 原版 PC 微信 | 打补丁后 |
| :--- | :--- | :--- |
| **右键“服务号 -> 删除”弹窗文案** | `删除与“服务号”的聊天？`<br>*(副标题被置空)* | `删除与“服务号”的聊天？`<br>`删除聊天后，聊天记录也将被清空。` |
| **点击红色“删除”确认后** | 仅隐藏外层入口行，保留所有子会话与消息 | **移除外层入口 + 自动遍历清空所有服务号子会话及全部历史聊天记录** |
| **新服务号消息到达时** | 所有旧服务号和历史消息全部重新出现 | 仅显示新到达的那一条服务号，旧记录彻底清空 |
| **其他会话（个人/群聊等）** | 正常 | **100% 保持原样，双重校验绝不误伤** |

---

## 🚀 快速使用

本工具仅使用 Python 标准库（`ctypes`、`struct`），**无需安装任何第三方依赖**。支持 **进程内存热补丁（推荐，无需重启微信、不改磁盘文件、不破坏数字签名）** 和 **磁盘 DLL 持久化补丁** 两种模式。

### 方式一：进程内存热补丁（即开即用，零磁盘改动）

保持微信处于运行状态，直接双击运行 [`apply_live_patch.bat`](apply_live_patch.bat)，或在终端执行：

```powershell
# 查看当前运行进程与磁盘文件的补丁状态
python wx_service_delete_patch.py status

# 对当前运行中的 Weixin.exe 注入内存热补丁（立即生效，无需重启微信）
python wx_service_delete_patch.py apply

# 一键还原当前运行中的 Weixin.exe 为原版逻辑
python wx_service_delete_patch.py restore
```

### 方式二：磁盘文件持久化补丁（重启微信依然生效）

如需持久化写入 `Weixin.dll`（工具会自动在同一目录下创建 `Weixin.dll.bak` 备份），请先退出微信，并以**管理员权限**运行终端：

```powershell
# 备份 Weixin.dll.bak 并写入持久化补丁
python wx_service_delete_patch.py file-apply

# 将磁盘 Weixin.dll 还原为原版状态
python wx_service_delete_patch.py file-restore
```

---

## 🔍 逆向原理与执行流程

详细逆向过程与汇编级分析请参阅 [`docs/REVERSE_ANALYSIS.md`](docs/REVERSE_ANALYSIS.md)。

### 核心调用与补丁链路

```text
[用户操作] 右键点击“服务号” -> 选择“删除”
    │
    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. Delete_MenuHandler (VA 0x185FF68E0)                                   │
│    ├─ [补丁点 1] RVA 0x5FF6A53: 74 16 (je) ──> EB 16 (jmp)               │
│    └─ 解除副标题屏蔽，弹窗显示：“删除聊天后，聊天记录也将被清空。”       │
└──────────────────────────────────────────────────────────────────────────┘
    │ (用户点击红色“删除”按钮确认)
    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 2. ChatSessionCellViewModel::Delete (VA 0x181C5CE10)                     │
│    ├─ 调用 SessionService::DeleteSession 删除外层服务号盒子入口           │
│    ├─ [补丁点 2] RVA 0x1C5D555: call Stub_CheckBox (RVA 0x76F9F50)       │
│    └─ 识别 brandservicesessionholder，置 g_delete_mode = 1，              │
│       直接复用原生逻辑投递 DeleteAllMsgBoxSession 异步批量清理任务        │
└──────────────────────────────────────────────────────────────────────────┘
    │ (后台线程执行批量清理任务)
    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ 3. DeleteAllMsgBoxSession (VA 0x18197C100)                               │
│    ├─ [补丁点 3] RVA 0x197C2F3: call Stub_FilterSession (RVA 0x76F9F80)  │
│    ├─ 双重校验过滤服务号子会话：                                         │
│    │    ① IsBrandServiceSubSession (0x182557D20): *(uint32*)(s+400) == 1 │
│    │    ② IsBrandServiceContact    (0x180BC45C0): 校验 gh_ 服务号属性    │
│    └─ 逐一从 session.db 删除子会话 + 清空对应消息记录 + 通知 UI 刷新      │
└──────────────────────────────────────────────────────────────────────────┘
```

### 三大关键发现

1. **为什么原版弹窗没有“聊天记录也将被清空”提示？**
   在 `Delete_MenuHandler` (`VA 0x185FF68E0`) 中，`0x185FF6A4A` 调用了 `VM::IsBrandServiceSessionHolder` (`0x181C59130`)，当返回 `true` 时故意将弹窗副标题置为空字符串 `""`。将 `0x185FF6A53` 的 `74 16` (`je`) 改为 `EB 16` (`jmp`) 即可恢复原生确认文案。
2. **为什么原版确认删除后不删服务号子会话？**
   在 `ChatSessionCellViewModel::Delete` (`VA 0x181C5CE10`) 末尾（`0x181C5D3EE..0x181C5D64C`），微信依次检查被删会话是否为微信客服盒子（调 `DeleteAllOpenIMKefuSession`）、小程序客服盒子（调 `DeleteAllWaAppKefuSession`）、折叠群聊盒子（调 `DeleteAllMsgBoxSession`），**唯独漏掉了对服务号盒子 `"brandservicesessionholder"` 的级联清理调用**。
3. **如何安全、无副作用地级联清空所有服务号子会话？**
   利用 `.text` 节尾部的对齐填充空隙（`RVA 0x76F9F50..0x76FA000`）放入共 86 字节的两个微型转发跳板（`Stub_CheckBox` 与 `Stub_FilterSession`），在删除 `"brandservicesessionholder"` 时复用原生的 `DeleteAllMsgBoxSession` 异步清理任务，并使用微信初始化服务号盒子时的同源判定函数 `IsBrandServiceSubSession` (`*(uint32_t*)(session + 400) == 1`) + `IsBrandServiceContact` (`gh_` 属性校验) 进行双重过滤，逐一删除子会话及全部消息记录。

---

## 📁 目录结构

```text
.
├── README.md                    # 项目说明文档
├── LICENSE                      # 授权声明（源码公开 / 权利保留，非开源许可）
├── wx_service_delete_patch.py   # 核心补丁工具（支持热补丁与持久化补丁）
├── apply_live_patch.bat         # Windows 双击一键注入内存热补丁脚本
└── docs/
    └── REVERSE_ANALYSIS.md      # 完整逆向分析报告、RVA 地址表与机器码详解
```

---

## ⚠️ 免责声明与技术定位

> **本项目不是数据提取工具，也不是反规避（Anti-Circumvention）工具。**
> 为明确区分本项目与一批因「绕过加密提取聊天记录」而被投诉下架的导出/解密类项目，
> 现将本项目的实际行为边界声明如下。

### 本项目做了什么（行为边界）

| 常见指控项 | 本项目实际情况 |
| :--- | :--- |
| 绕过或破解加密 | **否。** 不涉及任何加密算法、密钥或数据库协议，不读取、不解密 `session.db` 或任何数据文件 |
| 读取 / 导出数据 | **否。** 不读取、不解析、不导出、不外传任何聊天记录、通讯录或用户数据 |
| 访问网络 | **否。** 仅使用 Python 标准库（`ctypes`/`struct`/`os`/`shutil`/`sys`），无网络请求、无遥测、无更新检查、无第三方依赖 |
| 注入第三方模块 | **否。** 不注入 DLL、不创建远程线程、不加载任何外部模块；仅通过 `WriteProcessMemory` 写入本机目标进程自身的指令区与其自带的 Code Cave |
| 伪造指令 / 新增功能 | **否。** 只调用客户端**自身已有的原生函数**（`IsBrandServiceSubSession`、`DeleteAllMsgBoxSession` 等），将原生删除流程扩展到原本遗漏的服务号盒子，不构造任何伪造指令或数据 |
| 修改他人数据 | **否。** 仅作用于本机、当前用户本人已登录的客户端，删除的是使用者自己的本地会话与消息 |

### 使用条款与风险提示

1. 本项目仅供**逆向工程技术研究、学习与个人客户端操作体验优化**使用，严禁用于任何非法用途。
2. 使用者须仅对**自己拥有合法访问权限的、本机的**客户端进程执行本补丁，不得用于任何他人设备、账号或数据。
3. 使用本补丁可能违反客户端软件服务条款中的相关约定（如「禁止逆向工程」「禁止修改软件功能」等），由此产生的**账号限制、封禁或其它后果由使用者自行承担**，作者不承担任何责任。
4. 请自行确认所在司法辖区的相关法律法规，并自行判断使用的合法性。
5. 执行清空操作后，服务号内的历史消息记录将被**真实清空且不可恢复**，请确认无需保留旧服务号通知后再执行删除。
6. 本项目与所涉第三方客户端软件的权利人之间不存在任何隶属、赞助、授权、认可或背书关系；相关软件名称与商标归其各自权利人所有。
7. 本项目采用「源码公开、权利保留」授权（详见 [LICENSE](LICENSE)），**不授予任何再分发、衍生发布或商业使用许可**。

> 本声明不构成法律意见。如对合法性存在疑问，请咨询专业律师。

