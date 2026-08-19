# LSP framing 边界与失同步处理（TOOL-07）

> 状态：**current —— 已定稿并落地**。本文只负责 stdio frame；workspace snapshot、
> project/classpath 与 initialize/shutdown lifecycle 不在本项范围。权威用户契约见
> [`spec.md` §12.1](spec.md)，原审计见
> [`codebase-audit-v2/04-cli-lsp-build-and-release.md`](codebase-audit-v2/04-cli-lsp-build-and-release.md)。

## 1. 问题不是两个 runtime，而是共享层没有先验证

旧 `read_message` 把未设上限的 `Int` 直接传给 `io.read_stdin`。JVM 随后以 `L2I`
缩成 host `int`，native 则按声明值分配；同一坏帧因而会分别崩溃、挂起、静默退出或 OOM。
无终止符的 header 还会逐 byte 无限扩张。

修复点必须位于两后端共用的 `selfhost/src/lsp/server.dawn`，并且发生在
`io.read_stdin(content_length)` 之前。JVM/native 的 read primitive 不改：它们只应看见
已经证明能进入各自长度/分配边界的值。

## 2. 定稿契约

| 边界 | 契约 |
|---|---|
| header | 从首 byte 到 `CRLF CRLF` 共最多 8192 bytes；第 8192 byte 恰好完成可收，到达 8192 仍未完成立即 fatal |
| body | 最大 67108864 bytes；先验证，再调用 stdin read |
| header 行 | 每个非空行必须是 `1*tchar ":" field-value`；未知但语法正确的字段忽略，无冒号、空/非 token 字段名 fatal |
| 字段名 | `Content-Length` 仅 ASCII 大小写不敏感；不做 Unicode folding |
| 字段值 | 两端只可有 SP/HTAB，中间须为 `1*ASCII DIGIT`；`0` 合法 |
| 非法值 | 空、正负号、小数、指数、下划线、Unicode digit、`Int` 溢出、body 超限均 fatal |
| 重复字段 | 每个值独立完整解析；数值相同可收（含前导零/大小写差异），冲突或任一非法均 fatal |
| clean EOF | 尚未读到任何 header byte 时静默退出 |
| partial input | 已读到 header byte 后 EOF，或 body 短读，均 fatal |
| body 编码 | 完整 body 必须是严格 UTF-8；非法编码与 JSON 语法错同属可恢复 `-32700` |

固定 fatal 响应的 JSON 语义为：

```json
{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}
```

响应一次后关闭 read loop。失败后的任何 byte 都不得尝试解释成下一帧。

## 3. 为什么 JSON 错可恢复、framing 错不可恢复

完整、有界且按声明长度读完的 body 若 UTF-8 或 JSON 解析失败，下一 byte 仍是可信的 frame
边界；它属于 `Malformed(-32700, detail)`，可以回复后继续。公开 `bytes.decode_utf8_lossy`
（本设计成文时名叫 `decode_utf8`）的契约是替换非法序列，不能直接充当 wire validator：
例如 bytes `22 80 22` 会被修成合法 JSON 字符串 `"�"`。LSP 因此在 decoding 处严格验证。

framing 错误没有这个性质。缺失、非法或冲突的长度意味着不知道 body 有多长；partial body
也无法知道当前 EOF 前的 byte 是否完整消息。继续扫描只能猜边界，并可能把攻击者拼在坏帧后的
合法 `initialize` 当成新请求。因此 `Frame` 显式区分：

```dawn
type Frame = Eof | Message(value: Json) | Malformed(code: Int, why: String) | Fatal
```

`Malformed` 只表示“完整 frame 内的 JSON 错”，`Fatal` 才表示 transport 已失同步。fatal
分支不 flush pending document update，以免固定错误前多发一条与坏帧无关的 diagnostics。

## 4. 纯解析器与读取顺序

`parse_content_length_value` 不复用通用 `parse_int`。通用 parser 接受符号并按语言 whitespace
trim，不是 wire grammar；本处用负数累计，在任何 host conversion 前检测十进制 `Int`
溢出。字段名比较同样只折叠 ASCII `A..Z`。

`parse_content_length` 接收一个已经完成的 header block，依次完成：

1. 二次确认总长与 `CRLF CRLF`；
2. 验证每个非空行都有冒号，且字段名是非空 ASCII `tchar`；
3. 找出每个 ASCII case-insensitive 的 `Content-Length`；
4. 独立验证每个值的完整 wire grammar 与 `Int` range；
5. 验证 body cap；
6. 验证重复字段数值一致；
7. 只在全部通过后把长度交给 `io.read_stdin`。

header reader 在追加每个 byte 后更新终止符状态。检查顺序固定为“先认完成，再认超限”，
所以恰好 8192 bytes 的完成态可收；未完成态在 8192 当场 fatal，根本不读第 8193 byte。

本设计成文时仓库没有严格 UTF-8 的公开 API：当时的 `bytes.decode_utf8` 规范上就是
replacement decoder，为避免扩大 runtime/std API，本地 `valid_utf8` 在 LSP 边界按 bytes
检查 continuation、overlong、surrogate 与 `U+10FFFF` 上界，通过后才调用现有 decoder。
LIB-06 之后严格 API 有了公开形态 `bytes.decode_utf8_checked`，`valid_utf8` 这份本地副本
已删除，LSP 边界改由 `decode_body` 调 checked decoder 完成同一职责。

## 5. 门禁分工

`server.dawn` 的纯测试固定 8192/8193、`0`/`00042`、64 MiB/64 MiB+1、所有近似非法
拼写、`2^63`、`2^31`、重复同值/冲突/单个非法、畸形 header 行与严格 UTF-8。它直接证明
parser 的数值/编码边界，不需要真的分配 64 MiB body。

`scripts/lsp-framing.py` 驱动真实 stdin/stdout。凡是在 header 阶段即可判定的坏帧，都在其后
拼一个合法 `initialize`，并断言只收到一次固定错误；必须靠 EOF 才能确认的 partial
header/body 则单独断言一次固定错误。header/body cap 两例还要求进程在 stdin 仍打开时退出。
完整 frame 的坏 JSON 与“替换后原本可成为合法 JSON”的非法 UTF-8 都必须先回 `-32700`，
再成功回答后续 `initialize`。脚本使用独立 process group，超时会清理 launcher 与全部子进程。

普通 gates 直接跑 JVM；`scripts/native-cli-diff.sh` 用 release 形状的 native binary 跑独立
leg。Linux 上 body-cap 实验在 warm-up 后记录整个 process group 的 RSS，再向超限声明持续写
48 MiB；正确实现先拒绝，RSS 增量必须不超过 32 MiB。非 Linux 保留退出/响应断言，只合理
skip `/proc` RSS 读数。

八类负控全部实际见红并在恢复实现后复验：

1. 把 header cap 从 8192 放大到 16384 后，8193-byte 完整 header 被当成合法
   `initialize`，8192-byte 未完成 header 在 stdin 保持打开时不退出。
2. 把 body cap 从 64 MiB 放大到 128 MiB 后，超限声明不再立即退出；JVM RSS 增量达到
   39884 KiB，超过 32768 KiB oracle。
3. 把重复字段恢复为 last-wins 后，冲突长度后的请求被执行并产生两条
   `initialize` response。
4. 删除 `Fatal` 分支的 read-loop 关闭后，坏帧后的合法请求继续执行，并出现多余响应。
5. 删除严格 UTF-8 预检后，bytes `22 80 22` 被 replacement decoder 修成合法 JSON
   字符串，预期的首条 `-32700` 消失。
6. 恢复“忽略畸形 header 行”后，无冒号、空字段名和非法 token 字段名都被接受，并继续
   执行后续 `initialize`。
7. 把 cleanup 恢复为“launcher 活着才 `killpg`”后，确定性 self-test 中 launcher 先退出，
   同 process group 的 child 仍存活。
8. 把 response oracle 恢复为宽松 last-wins/有符号长度/16384-byte cap 后，self-test 分别
   在冲突重复值、`+2` 与 9000-byte header 三项见红。

## 6. 明确不做

- 不做 workspace/project snapshot，也不加载 `[java-deps]`；它们分别属于 TOOL-05/06/10。
- 不做 initialize/shutdown lifecycle 状态机；它属于 TOOL-08。
- 不修改 lexer、formatter 或 JSON parser。
- 不改变 `bytes.decode_utf8_lossy`（当时名 `decode_utf8`）的全语言 replacement 契约，
  也不为本项新增 runtime intrinsic。
- 不把 cap 下推进通用 `io.read_stdin`；这里是 LSP protocol policy，不是所有 stdin 调用的语义。
- 不把 framing error 伪装成可恢复 `Malformed`，也不尝试启发式重同步。

## 7. 收口测量

- Core 首次测量只报告 `lsp.server` 的 exact 与 normalized hash 同时变化；审阅为本项共享
  framing 实现的预期 Core 后，重录 14 份 dump / 77 个 module hash，再跑为 green。
- Emit 没有新增变化：`selfhost-prev-diff.sh` 与 `selfhost-run-diff.sh` 都通过，只有仓库既有且
  已声明的 SYN-10/CLI 差异提示。
- harness self-test 为 11/11；真实流为 JVM 28/28、native 28/28。最终 Linux RSS 增量分别为
  JVM 8/372 KiB、native 4/336 KiB（未完成 header / 超限 body，门槛均为 32768 KiB）。
- `dawn test selfhost` 为 366/366；LSP liveness 的 hangup/liveness/idle/debounce/freshness
  全部通过，JVM 与 previous release 的 52 条 LSP message 逐项一致。
- `doc-check.py` 通过 84 份文档、70 个 checked block 与 6 组翻译；
  `dawn fmt std site selfhost packages examples --check` 通过。
- native 独立 framing leg 使用 release 形状 binary 通过。完整 `native-cli-diff.sh` 在到达该
  leg 前，被既有 SYN-08 最小整数语料对 N-1 formatter 的不兼容阻断；本项没有把该跨任务
  失败伪装成 TOOL-07 通过，也没有扩大范围修改它。
