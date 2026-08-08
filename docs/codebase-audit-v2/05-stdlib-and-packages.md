# Dawn 代码库审查 v2：标准库与 packages

> 状态：**current** —— std、inflate、JSON、SHA-2 与 Web API/实现的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- JSON 旧有大整数、非有限输出与控制字符问题已经修复，不应重复；当前最高风险转到纯 Dawn inflate 的边界与 Web tempfile lifecycle。
- packages 的共同问题是 public record/Map/String 过早丢掉 invariant：Digest 可伪造、Response 可构造非法状态、query/form 丢重复值、JSON error 只有人类字符串。
- early language/package 允许 breaking change，应优先把无效状态从公开类型中移除，而不是在 write boundary 继续 sanitizer/默认值补丁。

## LIB-01 — P1 — 解压上限在完整 materialize 之后才检查

- **证据：K/S。** DEFLATE API 无 output limit：`packages/inflate/src/deflate.dawn:170`，back-reference copy 持续扩 buffer：`:356`；ZIP 一次性解压全部 entries：`packages/inflate/src/zip.dawn:203`。package manager 事后才检查：`selfhost/src/pkg/pkgfetch.dawn:278`；tar.gz 也先完整 gunzip：`:380`，注释承认检查太晚：`:386`。
- **影响：** 声称的 64/256 MB 上限不能限制 peak memory；compression bomb 在 guard 生效前 OOM。旧审查“archive limit 已修”不适用于现在的纯 Dawn inflate 路径。
- **建议：** `inflate_bounded/gunzip_bounded` 在每次 output growth 前检查；ZIP 提供 metadata iterator或逐 entry callback，单项/总量/数量上限都在 materialize 前执行。

## LIB-02 — P1 — ZIP central directory 损坏被当作正常结束

- **证据：S。** EOCD 只取 central directory start，未使用 directory size/count：`packages/inflate/src/zip.dawn:69`；loop 遇到第一个非 `CD_SIG` 就返回已收集 entries 的成功：`:203`。
- **边界：** 两 entry ZIP 破坏第二个 central directory signature，会返回只含第一项的 `Ok`，不是 corrupt archive。
- **影响：** archive completeness/integrity 失效，表现为静默文件缺失；package tree hash只看到被接受的残缺结果。
- **建议：** 验证 EOCD/ZIP64 disk、entry count 与 directory byte size；精确读取声明数量并要求结束位置吻合。

## LIB-03 — P1 — DEFLATE bit reader 在 EOF 后伪造零位

- **证据：S。** `take` 越界后把 byte 当 0：`packages/inflate/src/deflate.dawn:27`；EOB branch 在统一 truncation check 前可成功返回：`:322`。
- **边界：** 截短的 fixed block 可由补零恰好拼出 EOB；`inflate` 又不返回 consumed offset，container 无法严格拒绝 trailing garbage。
- **影响：** truncated stream 可能被接受，破坏 archive validator 的“完整读取”前提。
- **建议：** bit read 返回 `Result`/exhausted flag；EOB 也必须证明实际 bits 足够；container mode 要求 compressed slice 精确消费。

## LIB-04 — P2 — GZIP 忽略 reserved flags 与 header CRC

- **证据：S。** 读取 flags 后不拒绝高三位：`packages/inflate/src/gzip.dawn:43`；`FHCRC` 只跳两 bytes：`:51`。
- **影响：** 格式明确标记的非法 reserved bits 与 header corruption 都被接受。
- **建议：** `flags & 0xE0 != 0` hard error；存在 FHCRC 时验证 header CRC16。

## LIB-05 — P2 — `bytes.index_of` 的范围判断可 Int overflow

- **证据：S。** boundary 使用 `i + nlen > hlen`：`std/bytes.dawn:110`，没有先拒绝远大于 length 的 `from`。
- **边界：** nonempty needle 且 `from = Int.MAX` 时加法 wrap，可绕过 stop condition，继而越界或异常扫描。
- **影响：** 一个应为 total query 的 API 对合法 Int input panic。
- **建议：** 先处理 `from > hlen`，再用 `nlen > hlen || i > hlen - nlen` 的无溢出比较；补 MIN/MAX tests。

## LIB-06 — P2 — UTF-8 API 默认有损且没有 strict 对应项

- **证据：S。** `bytes.decode_utf8` 明确用 U+FFFD 替换 malformed input：`std/bytes.dawn:79`；Web 无条件用它构造 text body：`packages/web/src/server.dawn:77`。
- **影响：** invalid UTF-8 JSON/签名输入会在应用看到前被改写；`Request.body` 无法表示 decode failure，raw bytes 也容易丢失。
- **建议：** 现函数改名 `decode_utf8_lossy`，新增 `decode_utf8_checked -> Result`；Web 对 text media type strict decode，同时始终保留 raw Bytes。

## LIB-07 — P2 — `io.delete` 把不存在与操作失败都压成 false

- **证据：S。** API 返回 Bool，文档把不存在和 nonempty directory 等都写成 false：`std/io.dawn:90`；JVM/C runtime 丢掉具体 host error：`selfhost/src/jvm/rtclasses.dawn:1370`、`runtime/c/dawn_rt.c:1910`。
- **影响：** permission、busy、nonempty 与 not-found 无法区分；resource cleanup 不知道是否真的释放，直接加剧 Web tempfile 问题。
- **建议：** `Result[DeleteOutcome, ForeignError]`；至少保证 `Ok(false)` 仅表示 not found。

## LIB-08 — P2 — JSON parse error 只有不稳定的 String

- **证据：S。** public API 是 `Result[Json, String]`：`packages/json/src/parser.dawn:172`；offset 直接拼进 message：`packages/json/src/lexer.dawn:46`。
- **影响：** Web/LSP/config tooling 要取 error kind/offset 只能解析人类文本，文案调整会破坏调用方。
- **建议：** breaking change 为 `JsonError { kind, offset, message }`；若需过渡，另留 `parse_message` wrapper。

## LIB-09 — P3 — JSON number 注释与真实 IEEE 策略相反

- **证据：S。** value comment 声称不能精确表示的 decimal 会被拒：`packages/json/src/value.dawn:8`；parser/test 明确接受 `1e-400` 并 underflow 为 `0.0`：`packages/json/src/parser.dawn:203`。
- **影响：** caller 会误以为 Json number 保证 decimal exactness。
- **建议：** 写清“integer overflow 和 non-finite overflow 被拒；fraction/exponent 按 IEEE rounding，可 underflow”。行为本身是已裁决策略，不在此要求改 parser。

## LIB-10 — P1 — CORS headers 不覆盖 error response

- **证据：S。** allowed-origin path 通过 `next(req)?` 提前传播 error：`packages/web/src/middleware.dawn:68`；404/405 是 `Err`：`packages/web/src/server.dawn:391`；error 在 middleware chain 外 render：`:449`。
- **影响：** 浏览器能发跨域请求，却无法读取合法 origin 收到的 4xx/5xx body/header；生产 debugging 与 API client behavior 分叉。
- **建议：** CORS 同时 transform `Ok(Response)` 和 `Err(HttpError)`，把 headers 写入 error；更整齐的 architecture 是 middleware 包装最终 Response，而非半途 Result。

## LIB-11 — P1 — request-body tempfile 有确定泄漏路径

- **证据：S。** temp file 先创建，之后才对 output stream 建 bracket：`packages/web/src/server.dawn:355`；request-level cleanup 只有 Request 构造成功后才安装：`:448`；`File.delete()` false 仍当成功：`:365`。
- **边界：** open output stream、transfer 或 Request construction failure 时，path 没有任何 owner；反复 interrupted upload 可积累 temp files。
- **影响：** 长期 server 可耗尽 temp directory/disk。
- **建议：** temp path 是最外层 bracket resource；只有 Request 成功接管 ownership 才 disarm cleanup；delete failure 必须 log/return structured error。

## LIB-12 — P2 — query/form 重复字段被静默折叠

- **证据：S。** `Request` 使用 `Map[String, String]`：`packages/web/src/types.dawn:36`；parser 先有 pair list，随后 `map.from`：`packages/web/src/server.dawn:283`、`:319`；form 同样：`:295`。
- **边界：** `?tag=a&tag=b`、checkbox、多选表单只留下一个值。
- **影响：** 常见 HTTP 数据无法忠实表示，丢失不带诊断。
- **建议：** breaking change 为 multimap 或 ordered pair list；提供 `query_first/query_all` convenience API。

## LIB-13 — P2 — public router 与真实 server 的重复斜杠语义不同

- **证据：S。** public dispatch path splitter 丢所有 empty segment：`packages/web/src/router.dawn:67`、`:275`；server raw-path splitter 保留内部 empty segment：`packages/web/src/server.dawn:244`、`:427`。
- **边界：** direct `dispatch(..., "/a//b")` 可匹配 `/a/b`，真实 HTTP server 不匹配。
- **影响：** unit test 与 production routing 分叉；pattern 中 repeated slash 也会被 silently normalize。
- **建议：** 共享唯一 pure path parser；pattern/request 同时选择 reject repeated slash 或 preserve exact segments。

## LIB-14 — P2 — tail capture 抹掉 encoded slash 的 segment 边界

- **证据：S。** server 先按 raw slash 分段再 decode：`packages/web/src/server.dawn:244`，但 tail capture 最后用 `/` 拼成 String：`packages/web/src/router.dawn:96`。
- **边界：** `/dav/a%2Fb` 的单 segment `"a/b"` 与 `/dav/a/b` 的两个 segments 最终都得到 `rest = "a/b"`。
- **影响：** file/WebDAV/auth handler 无法区分两个 URI resource identity。
- **建议：** tail param 保留 `List[String]` 或带 raw encoding/segment boundaries 的专用类型。

## LIB-15 — P2 — `ServerHandle` 不拥有自己创建的 executor

- **证据：S。** handle 只保存 server/port/latch：`packages/web/src/server.dawn:489`；`start` 创建 virtual-thread executor 后不保存：`:511`；`stop` 不 shutdown：`:527`。
- **影响：** start/stop lifecycle 没有确定释放全部 resources；stop exception 时 latch 也可能不 release。
- **建议：** handle 持有 executor；`stop` 的 finally 顺序停止 server、shutdown executor、无条件 countDown。

## LIB-16 — P2 — `Response` 可公开构造非法 HTTP 状态

- **证据：S。** `Response` 是 public record literal：`packages/web/src/types.dawn:81`；header sanitizer 删除字符而非拒绝：`:214`；write boundary 不重新 validate：`packages/web/src/server.dawn:131`；no-body status 只覆盖 204/304：`:94`。
- **边界：** header name `":"` 可变 empty，`"X:A"` 与 `"XA"` collision；1xx/205 仍可带 entity。
- **影响：** safe constructor 的保证可被 record literal 绕过，最终是 host exception 或 protocol violation。
- **建议：** opaque `Response` 与 validated `HeaderName/HeaderValue`；write boundary defense-in-depth；统一 1xx、204、205、304、HEAD body semantics。

## LIB-17 — P2 — 两种 body limit 对 0/负数语义相反

- **证据：S。** middleware 直接 `len > limit`：`packages/web/src/middleware.dawn:53`；底层 reader 把 `limit <= 0` 当 unlimited：`packages/web/src/server.dawn:76`。
- **边界：** `-1` 在底层 unlimited、在 middleware 连 empty body 都拒；`0` 分别是 unlimited 与 empty-only。
- **影响：** config 迁移或组合 middleware 时可从 fail-closed 变 fail-open，且无 type/validation 提示。
- **建议：** 禁止 negative；用 `Option[Int]` 表示 unlimited；所有入口复用同一 validator。

## LIB-18 — P2 — streaming response 吞掉所有 fault 与 panic

- **证据：S。** transfer 被 `catch_panic` 包裹，返回 Result 立即丢弃：`packages/web/src/server.dawn:162`。
- **影响：** client disconnect、upstream IO failure 与 program invariant panic 都无 log/metric且不可区分；request 看似正常结束。
- **建议：** 只降级 expected disconnect；structured log IO fault；program panic 必须进入统一 server error path。

## LIB-19 — P2 — SHA-256 `Digest` public record 可伪造 invariant

- **证据：S。** digest state 是 public record：`packages/sha2/src/sha256.dawn:27`；`update/finish` 直接假定 `h` length、buffer length、total 相互一致：`:109`、`:127`。
- **影响：** caller 可构造 type-correct 但会 OOB 或输出错误 digest 的 state；API 把实现 invariant 变成用户责任。
- **建议：** `pub opaque type Digest`，只允许 `new/update/finish` 建立和推进状态。
