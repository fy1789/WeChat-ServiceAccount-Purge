# PC 微信 (4.1.15.51) “服务号”一键清空逆向工程详解

本文档详细记录针对 Windows PC 微信 `4.1.15.51` (x64) 中“服务号”（`brandservicesessionholder`）右键删除仅隐藏入口、不清空子会话与聊天记录问题的逆向分析过程、核心函数符号/地址表及补丁机器码实现。

---

## 1. 核心数据结构与会话标识

在微信 4.x (`Weixin.dll`, 默认 `ImageBase = 0x180000000`) 中，会话管理由 `kernel::service::SessionService` 负责，列表项视图模型为 `ChatSessionCellViewModel`。

### 1.1 `ChatSessionCellViewModel` 与 `kernel::Session` 内存布局
- `ChatSessionCellViewModel + 0x160` (`352` 字节)：内嵌的 `kernel::Session` 对象。
- `kernel::Session` 结构体大小：`0x290` (`656` 字节)。
- `kernel::Session + 0x00`：`std::string username`（MSVC `std::string` 布局：`+0x00` 为 16 字节 SSO 缓冲区或堆指针，`+0x10` 为 `size`，`+0x18` 为 `capacity`）。
- `kernel::Session + 0x185` (`389` 字节)：会话标志位（`bit 3 = 0x08` 表示聚合盒子自身）。
- `kernel::Session + 0x190` (`400` 字节)：`uint32_t brand_sub_type`：
  - `0`：订阅号盒子 (`brandsessionholder`) 的子会话
  - `1`：服务号盒子 (`brandservicesessionholder`) 的子会话

### 1.2 关键函数地址表（基于 `Weixin.dll` `4.1.15.51`，`ImageBase = 0x180000000`）

| 函数语义 | VA | RVA | 说明 |
| :--- | :--- | :--- | :--- |
| `Session::GetUserName` | `0x180083820` | `0x0083820` | `mov rax, rcx; ret`（返回 `&session->username`） |
| `IsBrandServiceContact` | `0x180BC45C0` | `0x0BC45C0` | 排除 `"weixin"`，检查 `"gh_"` 前缀或服务号联系人属性 |
| `IsBrandSessionHolder` | `0x180BC4CF0` | `0x0BC4CF0` | 判断 `username == "brandsessionholder"`（订阅号盒子） |
| `IsBrandServiceSessionHolder` | `0x180BC4F20` | `0x0BC4F20` | 判断 `username == "brandservicesessionholder"`（服务号盒子） |
| `IsConversationBox` | `0x180BC5610` | `0x0BC5610` | 判断 `username == "conversationboxservice"`（折叠群聊盒子） |
| `IsOpenIMKefuHolder` | `0x180BC5860` | `0x0BC5860` | 判断 `username == "opencustomerservicemsg"`（微信客服盒子） |
| `IsWaAppKefuHolder` | `0x180BC6F80` | `0x0BC6F80` | 判断 `username == "appbrandcustomerservicemsg"`（小程序客服盒子） |
| `IsMsgBoxSubSession` | `0x182557C90` | `0x2557C90` | 判断 `Session*` 是否为折叠群聊子会话 |
| `IsOpenIMKefuSubSession` | `0x182557CE0` | `0x2557CE0` | 判断 `Session*` 是否为微信客服子会话 |
| `IsWaAppKefuSubSession` | `0x182557D10` | `0x2557D10` | 判断 `Session*` 是否为小程序客服子会话 |
| `IsBrandServiceSubSession` | `0x182557D20` | `0x2557D20` | 判断 `Session*` 是否非盒子、非内置特殊号且 `*(uint32_t*)(s + 400) == 1` |
| `VM::IsBrandSessionHolder` | `0x181C59110` | `0x1C59110` | 传入 `ChatSessionCellViewModel*`，判断是否为订阅号盒子 |
| `VM::IsBrandServiceSessionHolder` | `0x181C59130` | `0x1C59130` | 传入 `ChatSessionCellViewModel*`，判断是否为服务号盒子 |
| `ChatSessionCellViewModel::Hide` | `0x181C5C660` | `0x1C5C660` | 右键“不显示”视线隐藏逻辑 |
| `ChatSessionCellViewModel::Delete` | `0x181C5CE10` | `0x1C5CE10` | 右键“删除”核心执行函数 |
| `SessionService::DeleteSession` | `0x18197A070` | `0x197A070` | 删除单个会话（异步任务入口 `0x181956010`） |
| `DeleteAllMsgBoxSession` | `0x18197C100` | `0x197C100` | 批量清空折叠群聊所有子会话及消息（入口 `0x1819563F0`） |
| `DeleteAllOpenIMKefuSession` | `0x18197CDC0` | `0x197CDC0` | 批量清空微信客服所有子会话及消息（入口 `0x181956530`） |
| `DeleteAllWaAppKefuSession` | `0x18197DA80` | `0x197DA80` | 批量清空小程序客服所有子会话及消息（入口 `0x181956670`） |
| `Delete_MenuHandler` | `0x185FF68E0` | `0x5FF68E0` | 会话右键菜单“删除”（ID `1009`）点击处理器 |
| `Delete_ConfirmCallback` | `0x185FF6D50` | `0x5FF6D50` | 删除确认弹窗点击确认后的回调函数 |

---

## 2. 原版代码缺陷定位

### 2.1 服务号子会话是如何被归类到 `"brandservicesessionholder"` 的？
在聚合盒子初始化函数 (`VA 0x18195D580..0x18195D5FC`) 中，微信遍历所有 `kernel::Session`：
```asm
; 检查是否为服务号子会话 (0x18195D5C0)
18195d5c0: movq  %rsi, %rcx
18195d5c3: callq 0x180bc45c0       ; IsBrandServiceContact(session->username)
18195d5c8: testb %al, %al
18195d5ca: je    0x18195d5fc
18195d5cc: movq  %rsi, %rcx
18195d5cf: callq 0x182557d60       ; *(uint32_t*)(session + 400) == 1
18195d5d4: testb %al, %al
18195d5d6: je    0x18195d5fc
; 归入 "brandservicesessionholder" (0x180bc5050)
```

### 2.2 为什么右键“服务号 -> 删除”弹窗不提示“删除聊天后，聊天记录也将被清空。”？
在 `Delete_MenuHandler` (`VA 0x185FF68E0`) 的 `0x185FF6A39..0x185FF6A6B` 处：
```asm
185ff6a39: 48 8b 4e 10                 movq  16(%rsi), %rcx
185ff6a3d: e8 ce 26 c6 fb              callq 0x181c59110       ; VM::IsBrandSessionHolder
185ff6a42: 84 c0                       testb %al, %al
185ff6a44: 75 0f                       jne   0x185ff6a55       ; 订阅号盒子 -> 副标题置空 ""
185ff6a46: 48 8b 4e 10                 movq  16(%rsi), %rcx
185ff6a4a: e8 e0 26 c6 fb              callq 0x181c59130       ; VM::IsBrandServiceSessionHolder
185ff6a4f: 90                          nop
185ff6a50: 84 c0                       testb %al, %al
185ff6a52: 74 16                       je    0x185ff6a6b       ; 若不是服务号盒子 -> 跳到 0x185ff6a6b 加载“删除聊天后，聊天记录也将被清空。”
185ff6a54: 48 8d 15 9d c1 8f 02        leaq  0x188ef2bf8(%rip), %rdx ; "" (空字符串)
```
注意 `0x185FF6A53`（指令 `74 16`）故意将服务号盒子的弹窗副标题设为了空字符串 `""`。

### 2.3 为什么点击确认后子会话没有被删除？
在 `ChatSessionCellViewModel::Delete` (`VA 0x181C5CE10`) 中：
1. `0x181C5D04F` 调用 `SessionService::DeleteSession("brandservicesessionholder")` 仅删除了父级盒子入口。
2. 随后在 `0x181C5D3EE..0x181C5D64C` 进行级联删除检查：
   - `0x181C5D3F1`：若 `IsOpenIMKefuHolder(session)` 为真 -> 调用 `0x181956530` (`DeleteAllOpenIMKefuSession`)
   - `0x181C5D4A3`：若 `IsWaAppKefuHolder(session)` 为真 -> 调用 `0x181956670` (`DeleteAllWaAppKefuSession`)
   - `0x181C5D555`：若 `IsConversationBox(session)` 为真 -> 调用 `0x1819563F0` (`DeleteAllMsgBoxSession`)
   - **唯独没有对 `IsBrandServiceSessionHolder(session)` (`0x180BC4F20`) 做级联清理！**

---

## 3. 补丁设计详解

利用 `Weixin.dll` 的 `.text` 节末尾对齐填充区（`RVA 0x76F9F50..0x76FA000`，共 176 字节 `0xCC`，属性为 `PAGE_EXECUTE_READ`）作为 Code Cave，并使用 `.data` 节 BSS 尾部未使用的 1 字节（`RVA 0xBBD8FF0`，属性为 `PAGE_READWRITE`）作为模式标志 `g_delete_mode`：

### 3.1 补丁点 1：恢复弹窗副标题（`RVA 0x5FF6A53`）
- 原字节：`74 16` (`je 0x185ff6a6b`)
- 新字节：`EB 16` (`jmp 0x185ff6a6b`)

### 3.2 补丁点 2：级联触发异步清理任务（`RVA 0x1C5D555` -> `Stub_CheckBox` @ `RVA 0x76F9F50`）
将 `0x181C5D555` 处的 `call 0x182557CD0` 重定向到 `Stub_CheckBox` (`RVA 0x76F9F50`)：
```asm
; Stub_CheckBox @ RVA 0x76F9F50 (46 bytes)
sub  rsp, 0x28
call 0x180BC5610                        ; IsConversationBox(rcx)
test al, al
jz   .check_brand_service
mov  byte ptr [0x18BBD8FF0], 0          ; g_delete_mode = 0 (折叠群聊模式)
jmp  .done

.check_brand_service:
mov  rcx, rsi                           ; rsi = Session* (offset 0 = username)
call 0x180BC4F20                        ; IsBrandServiceSessionHolder(rcx)
test al, al
jz   .done
mov  byte ptr [0x18BBD8FF0], 1          ; g_delete_mode = 1 (服务号模式)

.done:
add  rsp, 0x28
ret
```
当删除的是“服务号”盒子时，`Stub_CheckBox` 置 `g_delete_mode = 1` 并返回 `al = 1`，直接复用 `ChatSessionCellViewModel::Delete` 原生后续代码（`0x181C5D562..0x181C5D64C`）获取 `SessionService` 并投递 `DeleteAllMsgBoxSession` 异步任务。

### 3.3 补丁点 3：子会话双重安全过滤（`RVA 0x197C2F3` -> `Stub_FilterSession` @ `RVA 0x76F9F80`）
在 `DeleteAllMsgBoxSession` (`0x18197C100`) 遍历所有会话的循环内，将 `0x18197C2F3` 处的 `call 0x182557C90` 重定向到 `Stub_FilterSession` (`RVA 0x76F9F80`)：
```asm
; Stub_FilterSession @ RVA 0x76F9F80 (40 bytes)
cmp  byte ptr [0x18BBD8FF0], 1          ; 检查是否为服务号清理模式
je   .filter_brand_service
jmp  0x182557C90                        ; g_delete_mode == 0: 走原版 IsMsgBoxSubSession

.filter_brand_service:
sub  rsp, 0x28
call 0x182557D20                        ; 1. IsBrandServiceSubSession(rcx): 非盒子、非内置、且 *(uint32_t*)(s+400) == 1
test al, al
jz   .ret
mov  rcx, r14                           ; r14 = 当前遍历的 Session*
call 0x180BC45C0                        ; 2. IsBrandServiceContact(rcx): 确保是 gh_ 服务号会话

.ret:
add  rsp, 0x28
ret
```
当子会话通过双重校验返回 `1` 时，`DeleteAllMsgBoxSession` 原生循环体自动执行：
1. `0x182AC38F0`：从 `session.db` 删除该子会话。
2. `0x1817DF5D0`：打印日志 `"delete all messages of session:"` 并清空该子会话在消息数据库中的所有历史记录。
3. `0x181959370`：通知 UI 层移除该会话。

---

## 4. 跨版本适配指南（特征码定位）

若微信升级至新版本，可通过以下字符串或特征直接定位上述地址：
1. **定位 `DeleteAllMsgBoxSession`**：在 `.rdata` 或加密字符串引用中搜索 `"kernel::service::SessionService::DeleteAllMsgBoxSession()::(lambda)::operator()"` 或 `"delete all messages of session:"`，循环头中遍历步长为 `add r14, 0x290` (`49 81 C6 90 02 00 00`) 后的第一个 `call` 即为 `SITE3_RVA`。
2. **定位 `ChatSessionCellViewModel::Delete`**：交叉引用 `DeleteAllMsgBoxSession` 的投递函数，在该函数末尾连续三个 `if-else` 分支中最后一个 `call IsConversationBox` 即为 `SITE2_RVA`。
3. **定位 `SITE1_RVA`**：交叉引用 `"brandservicesessionholder"` 的判定函数 `VM::IsBrandServiceSessionHolder`，在右键菜单模块中紧跟 `VM::IsBrandSessionHolder` 之后的 `test al, al; je <load_subtitle>` 即为 `SITE1_RVA`。
