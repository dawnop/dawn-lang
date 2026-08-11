# Dawn 代码库审查 v2：标准库与 packages

> 状态：**current** —— std、inflate、JSON、SHA-2 与 Web API/实现的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- JSON 旧有大整数、非有限输出与控制字符问题已经修复，不应重复；inflate 的三项 P1 与 Web
  tempfile ownership 也已关闭。当前剩余风险集中在 Web 公开 invariant、协议边界，以及
  `LIB-18` 尚未验证的 streaming clean-truncation 候选。
- packages 的共同问题是 public record/Map/String 过早丢掉 invariant：Digest 可伪造、Response 可构造非法状态、query/form 丢重复值、JSON error 只有人类字符串。其中 query/form 与 JSON error 已由后续两个 major 关闭，Digest 与 Response 仍在册。
- early language/package 允许 breaking change，应优先把无效状态从公开类型中移除，而不是在 write boundary 继续 sanitizer/默认值补丁。
- **本篇按目录写 `packages/web/src/…`、`packages/json/src/…`，但目录名不是包名**：包管理器的 v2 换名规则要求 major ≥ 2 的包名带上 major，所以这两个包的 `name` 分别是 `web3` 与 `json2`（各自的 `dawn.toml`），消费者靠别名保住 `use web/...` 的拼写。版本随 major 走，读 manifest 不读本文。

## LIB-01 — P1 — 解压上限在完整 materialize 之后才检查（已修）

> **后续处置：已修。** `packages/inflate/src/deflate.dawn` 的 bounded 入口在 stored write、literal
> append 与 back-reference copy **之前**检查剩余预算；`gzip.gunzip_bounded` 按多 member 聚合输出
> 扣减同一预算。ZIP 拆成只读 metadata 的 `headers` 与逐 entry 的 `read_bounded`，Planner 的
> `compiler-plan/src/pkgfetch.dawn` 先检查 entry count/declared size，再把单项与总量剩余额度交给
> bounded decoder。

- **修复前证据：K/S。** DEFLATE API 没有 output limit，back-reference copy 持续扩 buffer；ZIP
  一次性解压全部 entries，package manager 与 tar.gz 路径都在完整 materialize 后才检查 64/256 MB
  上限。
- **修复前影响：** compression bomb 在 guard 生效前即可 OOM；事后长度检查不是 peak-memory
  上限。
- **门禁：** `scripts/inflate-contract/run.sh` 用独立 Java compressor 固定 exact-cap 与 one-byte-under
  边界；另在 256 MB heap 内展开 512 MB bomb，要求 bounded decoder 在 1024 bytes 处正常拒绝而
  不是 OOM。`deflate.dawn` 的 inline tests 还覆盖 stored block、zero 与 negative cap。
- **结论：已修。** archive ceiling 已移动到每次 output growth 之前，原 materialize-first 边界关闭。

## LIB-02 — P1 — ZIP central directory 损坏被当作正常结束（已修）

> **后续处置：已修。** `packages/inflate/src/zip.dawn` 从 EOCD/ZIP64 取得 disk、entry count、
> directory start 与 byte size，精确读取声明数量；遇到坏 signature、提前结束、跨出声明区间，
> 或最终 consumed bytes 与 directory size 不一致都返回 corrupt archive，而不是已有 entry 的部分成功。

- **修复前证据：S。** parser 只取 central directory start，不使用 size/count；loop 遇到第一个非
  central-directory signature 就返回已经收集的 entries。
- **修复前边界：** 两 entry ZIP 破坏第二个 central directory signature，会返回只含第一项的
  `Ok`，不是 corrupt archive。
- **门禁：** `scripts/inflate-contract/probe.dawn` 用 Java 生成两 entry ZIP，再翻转第二条 central
  record 的 signature；`scripts/inflate-contract/run.sh` 要求该输入以 central-directory 错误拒绝，
  不能降成一条 entry 的成功。
- **结论：已修。** archive completeness 由 EOCD 声明边界定义，损坏不再静默表现为文件缺失。

## LIB-03 — P1 — DEFLATE bit reader 在 EOF 后伪造零位（已修）

> **后续处置：已修。** bit reader 仍可返回占位值以保持内部形状，但会永久记录越界；final
> block/EOB 成功前检查该状态。低层 `inflate_from`/`inflate_end` 同时返回真实 consumed offset，
> gzip 用它定位 member trailer，ZIP 要求该 offset 与 central directory 的 compressed size 一致。

- **修复前证据：S。** `take` 越界后把 byte 当 0，EOB branch 又可在统一 truncation check 前成功；
  container 也拿不到 consumed offset。
- **修复前边界：** 截短的 fixed block 可由补零恰好拼出七个零位的 EOB，返回看似完整的 output。
- **门禁：** `scripts/inflate-contract/probe.dawn` 对 Java level 1/6/9 的真实 raw DEFLATE 分别删除
  最后一个 byte，三者都必须拒绝；`deflate.dawn` 的 inline test 另固定最小 truncated fixed block。
- **结论：已修。** 人工补零不能再构成合法结束，container 也能验证精确消费边界。

## LIB-04 — P2 — GZIP header 与 member 边界不完整（已修）

> **后续处置（2026-08-09）：已修。** `gunzip`/`gunzip_bounded` 的公开签名不变，内部改为
> 迭代读取 RFC 1952 member 序列。每个 member 从真实 DEFLATE consumed offset 定位自己的
> trailer，分别验证 CRC32/ISIZE，再把 payload 追加到同一个 `bytes.Buf`；trailer 后若还有
> bytes，它们必须构成下一个完整 member，故合法 concatenated gzip 被接受、尾随垃圾被拒绝：
> `packages/inflate/src/gzip.dawn:95`、`:136`。同一 `deflate` 模块非破坏性新增公开低层 cursor
> API `inflate_from(src, from, cap)`：它直接从原始 `Bytes` 的绝对 offset 解码、返回绝对 end
> offset，并严格拒绝负数或超过输入长度的 `from`，因而不为每个 member 复制一次剩余 suffix：
> `packages/inflate/src/deflate.dawn:246`。原有 `inflate`/`inflate_bounded`/`inflate_end` 的签名
> 与从 byte 0 解码的语义不变，但不能声称整个 DEFLATE 公开 API 未变。Dawn 只有 module-private、
> 没有通用 package-private；把 cursor 放进另一个带 `pub` seam 的 “internal” 模块仍是用户可达
> API，所以实现保持单一 `deflate.dawn` 并诚实记录这个公开新增。
>
> 版本纪律同步落地：`inflate` 从 1.0.0 升至 1.1.0，因为新增公开函数属于 backward-compatible
> minor，而非可留在原 patch version 下的实现修正：`packages/inflate/dawn.toml:3`。版本提升与
> API 变更同批完成，避免 MVS 在同一 name/version 下观察到不同内容；README 也明确旧三个入口
> 兼容及 1.1.0 的新增范围：`packages/inflate/README.md:6`。
>
> header parser 现在拒绝 `FLG & 0xE0 != 0`，逐项证明 FEXTRA 长度与内容存在、FNAME/FCOMMENT
> 含 NUL terminator，并在 FHCRC 存在时对 checksum 字段之前的完整 header 计算 CRC32 低 16 位：
> `packages/inflate/src/gzip.dawn:61`、`:88`。这里订正旧审计的合规措辞：reserved bits 非零是 RFC
> 明确要求 compliant decompressor 报错的条件；RFC 的最低合规条款只要求能跳过 optional
> fields，并不强制验证 FHCRC。因此旧实现的 FHCRC 行为是完整性缺口，不宜单独称为最低合规
> 违规；本次仍选择验证，因为字段既然存在就不应静默接受已检测出的 header corruption。
>
> bounded 语义按聚合输出扣减剩余预算，不在 member 间重置；member 自身仍在 DEFLATE 写入前
> 拒绝超限：`packages/inflate/src/gzip.dawn:126`。循环与 `bytes.Buf` 使大量小 member 不依赖
> 递归，也不反复拼接累计结果；每个 payload 仅在 trailer 验证后线性追加一次。
>
> `inflate-contract` 覆盖空 member、2/3 members、多个空 member、完整 optional header、第二
> member 的合法 FHCRC 及坏 CRC/ISIZE/magic/FHCRC/reserved bit、FEXTRA 截断、FNAME/FCOMMENT
> 缺 NUL、尾随垃圾、聚合 cap 与 512 个 tiny members，并以同一纯 Dawn 语料对拍 JVM/native：
> `scripts/inflate-contract/gzip_cases.dawn:125`、`:156`、`:194`。六个持久行为负控分别删除
> member loop、恢复“文件最后 8 bytes 是 trailer”、按 member 重置 cap、跳过 reserved/FHCRC 验证，以及把
> FHCRC checksum 起点从当前 member 错改成 archive 0；每个 mutant 都必须成功编译运行并由
> 对应 case 把合同打红：`scripts/inflate-contract/run.sh:90`。

- **修复前证据：S。** flags 高三位未拒绝；FHCRC 只前移 cursor；代码把整个文件最后 8 bytes
  当作唯一 trailer，因而拒绝合法 concatenated members。
- **修复前影响：** 非法 reserved flags 与 header corruption 被接受；合法多 member gzip 被拒，
  且 container framing 依赖“最后 trailer”而不是真实 DEFLATE end。
- **处置：** 已以严格、迭代、aggregate-bounded 的 member parser 替换，并由双后端行为合同与
  六项 mutation 常驻守门。

## LIB-05 — P2 — `bytes.index_of` 的范围判断可 Int overflow（已修）

> **后续处置（2026-08-09）：已修。** 空 needle 把 `last_start` 设为 `hlen`；非空
> needle 先拒绝 `start >= hlen`，再以 `remaining = hlen - start` 验证长度，只有验证
> 通过才计算 `last_start = hlen - nlen`：`std/bytes.dawn:111`。外层先匹配当前起点，
> 再判断是否已到最后合法起点，故 `i + 1` 只在 `i < last_start` 时发生：
> `std/bytes.dawn:126`；内层 matcher 也改为显式迭代：`std/bytes.dawn:137`。现行语义已
> 在规范钉死：负 `from` 钳到 0；空 needle 可命中
> `[0, len]`，但 `from > len` 返回 `None`：`docs/spec.md:1534`。
>
> std tests 与自动发现的 JVM/native fixture 覆盖 Int.MIN/MAX、空 haystack/needle、
> 最后合法起点命中/不命中、needle 更长，以及 std 的 131072-byte needle 与 fixture
> 的 100000-byte needle：`std/bytes.dawn:461`、`scripts/spike-native/bytes_index_of.dawn:19`。
> 关闭 LIB-05 所依赖的两项行为负控实测：恢复 `i + nlen` 后 fixture 在 Int.MAX 超时；
> 漏掉 last-start 后 JVM/native 都把两个末端命中误报为 `None`。
>
> production `std/bytes` 没有为测试新增 `std/str` 依赖；长 Bytes 复用测试原有变量按
> 长度倍增。隔离 Core 实测中，HEAD 与“仅新增测试”均保持 `calc` 的 `Adt1463`，只有
> production 实现及完整变更移到 `Adt1467`；因此仅测试引入的 nominal-ID 噪声为 0，
> 剩余 `+4` 来自实际控制流，并由 Core 的既有 ID normalization 识别为非指令变化。
>
> **订正旧结论：** 修复前 `bytes_at` 越界返回 `-1` sentinel，并不会经 `bytes.at`
> panic；真实症状是 `i + nlen` 与随后 `i + 1` 回绕后重扫巨大 Int 区间，表现为不终止。
> 同时，旧 matcher 是自尾递归，按 spec §12.4 本来就保证降成循环；100000-byte
> 行为负控恢复旧写法仍通过，因此没有“旧 matcher 会爆栈”的实证。显式循环保留为局部
> 可读性与不依赖该优化形状的实现选择，不把这部分冒充成已复现的栈缺陷。Core golden
> 会抓到恢复递归写法，但那只是结构守卫，不是行为负控，也不是关闭本项的依据。

- **修复前证据：S。** boundary 使用 `i + nlen > hlen`，没有先拒绝远大于 length 的 `from`。
- **修复前影响：** 一个应为 total query 的 API 对合法 Int input 可能不终止。
- **处置：** 已以 remaining-length/last-start 算法替换，并由 std、Core 与双后端语料守护。

## LIB-06 — P2 — UTF-8 API 默认有损且没有 strict 对应项

<!-- audit-anchor: absent std/bytes.dawn | decode_utf8_checked -->

- **证据：S。** `bytes.decode_utf8` 明确用 U+FFFD 替换 malformed input：`std/bytes.dawn:79`；Web 无条件用它构造 text body：`packages/web/src/server.dawn:77`。
- **影响：** invalid UTF-8 JSON/签名输入会在应用看到前被改写；`Request.body` 无法表示 decode failure，raw bytes 也容易丢失。
- **建议：** 现函数改名 `decode_utf8_lossy`，新增 `decode_utf8_checked -> Result`；Web 对 text media type strict decode，同时始终保留 raw Bytes。

- **订正（#196 分诊，2026-08-11 写回）。** 上面「raw bytes 也容易丢失」不准确：
  `read_body` 返回 `(String, Bytes)`，`Request.raw` 始终保留原始字节
  （`packages/web/src/types.dawn`），建议里「始终保留 raw Bytes」那半**已经实现**。
  仍成立的是另外两半：`decode_utf8` 无条件有损、没有 strict 对应项，且 `Request.body`
  无法表示 decode failure。
- **搭车去向：** 本项是 RD-06「函数名即定义域」的延续而非冲突，但同一函数在 20 个版本内
  已改名两次（`decode` → `decode_utf8`），编译器还有核心路径调用点，
  **不要为它单开一轮种子三期**；并进 RD-06 命名族统一的破坏窗口一起走。

## LIB-07 — P2 — `io.delete` 把不存在与操作失败都压成 false（已修）

- **证据：S。** 修复前 API 返回 Bool，文档把不存在和 nonempty directory 等都写成 false：`std/io.dawn:90`；JVM/C runtime 丢掉具体 host error：`selfhost/src/jvm/rtclasses.dawn:1370`、`runtime/c/dawn_rt.c:1910`。
- **影响：** permission、busy、nonempty 与 not-found 无法区分；resource cleanup 不知道是否真的释放，直接加剧 Web tempfile 问题。
- **建议：** `Result[DeleteOutcome, ForeignError]`；至少保证 `Ok(false)` 仅表示 not found。
- **处置：** 公开 API 已改为 `Result[DeleteOutcome, ForeignError]`，只把不存在映射为
  `Ok(NotFound)`；JVM `Files.deleteIfExists` 与 C `remove` 的其余失败都穿过 `catch_fault`
  成为 `Err`。std 在后端前以稳定 `ForeignError` 拒绝空串与尾 `/`，native 路径桥拒绝内嵌
  NUL，避免 JVM 规范化或 C 截断后删到另一对象。三个 Bool 路径查询在 NUL 上统一直接回
  `false`，`getenv` 作为同一 C-string bridge 上唯一的 Option 查询统一回 `None`，不会从 native
  fault 或查询 NUL 前缀；双后端合同与七组可运行 mutant 固定删除结果、查询结果、路径解释及
  目标不变边界。

## LIB-08 — P2 — JSON parse error 只有不稳定的 String（已修）

<!-- audit-anchor: absent packages/json/src/value.dawn | pub type JsonError -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `ce9cd15` 把 `parse` 的失败类型从
> `String` 换成 `packages/json/src/value.dawn` 的 `JsonError { kind, offset, message }`，
> `JsonErrorKind` 按调用方**能据以分支**的区别分档而不是一档一句话；`error_text` 保留旧的
> 单行渲染供迁移。这是包破坏性变更，随 `96a378a` 的 major 一起发为 `json2 / 2.0.0`。
> 立项时要显式推翻的 `re-audit-2026-07-30.md:547`「包错误类型统一 String 已由 ERR-02 覆盖」
> 归因确实不成立：ERR-02 的范围是 `java_try`/`catch_panic` 的 `Result[T, String]`，从未碰过
> JSON 自己的 parse error。

- **证据：S。** public API 是 `Result[Json, String]`：`packages/json/src/parser.dawn:172`；offset 直接拼进 message：`packages/json/src/lexer.dawn:46`。
- **影响：** Web/LSP/config tooling 要取 error kind/offset 只能解析人类文本，文案调整会破坏调用方。
- **建议：** breaking change 为 `JsonError { kind, offset, message }`；若需过渡，另留 `parse_message` wrapper。

## LIB-09 — P3 — JSON number 注释与真实 IEEE 策略相反（已修）

> **后续处置（2026-08-09）：已修。** `Json` 与 parser 文档现明确区分两条路径：
> `Int` 范围内的整数词素精确保留为 `JInt`；fraction/exponent 按 IEEE-754 binary64
> ties-to-even 舍入为 `JNum`，有限下溢接受为有符号零，只有非有限溢出被拒。
> `json_lib` 跨后端语料使用 Python `struct.pack` 派生的位标签，并由规范化 value/exact
> 与 ±0 reciprocal 间接验证 2^53+1、两侧 tie-even、正负下溢零和最大有限值；同时固定
> `1e400` 拒绝与大整数的逐位保真。

- **证据：S。** value comment 声称不能精确表示的 decimal 会被拒：`packages/json/src/value.dawn:8`；parser/test 明确接受 `1e-400` 并 underflow 为 `0.0`：`packages/json/src/parser.dawn:203`。
- **影响：** caller 会误以为 Json number 保证 decimal exactness。
- **建议：** 写清“integer overflow 和 non-finite overflow 被拒；fraction/exponent 按 IEEE rounding，可 underflow”。行为本身是已裁决策略，不在此要求改 parser。

## LIB-10 — P1 — CORS headers 不覆盖 error response

<!-- audit-anchor: absent packages/web/src/server.dawn | bodyless_request -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `79448da` 让 dot-segment 400 与
> body-limit 413 这两条早退拒绝也走 middleware 链：`bodyless_request` 从请求行与 header
> 造出一个 body 为空的 Request（这两条路径的全部意义就是不读 body），核心函数直接返回该
> 错误，于是它们与其他 error response 一样拿到 CORS 头与访问日志行。dot-segment 检查移到
> dispatch 之后，因此拒绝还带上匹配路由的 tags。middleware 在这两条路径上看到的是
> **诚实但不完整**的 Request（method/path/headers/query/tags 为真，body 与 raw 为空），
> 这一点写在调用点。本项的 partial 边界至此关闭。

> **后续处置（2026-08-09）：partial。** `with_cors` 已不再用 `?` 提前传播，handler 的
> `Ok(Response)` 与 `Err(HttpError)` 都会写入 CORS headers：`packages/web/src/middleware.dawn:81`。
> 但 dot-segment 400 与 body-limit 413 在 Request/middleware 之前生成：
> `packages/web/src/server.dawn:458`、`:484`，仍无 CORS。只有让 CORS 包住最终 Response 或把
> early error 也交给同一 response transform，才能关闭原发现。

- **证据：S。** allowed-origin path 通过 `next(req)?` 提前传播 error：`packages/web/src/middleware.dawn:68`；404/405 是 `Err`：`packages/web/src/server.dawn:391`；error 在 middleware chain 外 render：`:449`。
- **影响：** 浏览器能发跨域请求，却无法读取合法 origin 收到的 4xx/5xx body/header；生产 debugging 与 API client behavior 分叉。
- **建议：** CORS 同时 transform `Ok(Response)` 和 `Err(HttpError)`，把 headers 写入 error；更整齐的 architecture 是 middleware 包装最终 Response，而非半途 Result。

## LIB-11 — P1 — request-body tempfile 有确定泄漏路径

- **证据：S。** temp file 先创建，之后才对 output stream 建 bracket：`packages/web/src/server.dawn:355`；request-level cleanup 只有 Request 构造成功后才安装：`:448`。删除结果已由 LIB-07 改为结构化并会记录失败，但它没有补上 ownership 空窗。
- **边界：** open output stream、transfer 或 Request construction failure 时，path 没有任何 owner；反复 interrupted upload 可积累 temp files。
- **影响：** 长期 server 可耗尽 temp directory/disk。
- **建议：** temp path 是最外层 bracket resource；只有 Request 成功接管 ownership 才 disarm cleanup；delete failure 必须 log/return structured error。

## LIB-12 — P2 — query/form 重复字段被静默折叠（已修）

<!-- audit-anchor: absent packages/web/src/types.dawn | query: Map[String, List[String]] -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `05db7f2` 把 `Request.query` 与
> `parse_form` 的结果都改成 `Map[String, List[String]]`，按 wire order 保留同名的每个值，
> 与 WEB-04 早已落地的 `headers` 同形；`query`/`form_value` 取第一个，`query_all`/`form_all`
> 取全部。包破坏性变更，随 `96a378a` 的 major 发为 `web3 / 3.0.0`。

- **证据：S。** `Request` 使用 `Map[String, String]`：`packages/web/src/types.dawn:36`；parser 先有 pair list，随后 `map.from`：`packages/web/src/server.dawn:283`、`:319`；form 同样：`:295`。
- **边界：** `?tag=a&tag=b`、checkbox、多选表单只留下一个值。
- **影响：** 常见 HTTP 数据无法忠实表示，丢失不带诊断。
- **建议：** breaking change 为 multimap 或 ordered pair list；提供 `query_first/query_all` convenience API。

## LIB-13 — P2 — public router 与真实 server 的重复斜杠语义不同

<!-- audit-anchor: present packages/web/src/router.dawn | pub fn dispatch( -->

- **证据：S。** public dispatch path splitter 丢所有 empty segment：`packages/web/src/router.dawn:67`、`:275`；server raw-path splitter 保留内部 empty segment：`packages/web/src/server.dawn:244`、`:427`。
- **边界：** direct `dispatch(..., "/a//b")` 可匹配 `/a/b`，真实 HTTP server 不匹配。
- **影响：** unit test 与 production routing 分叉；pattern 中 repeated slash 也会被 silently normalize。
- **建议：** 共享唯一 pure path parser；pattern/request 同时选择 reject repeated slash 或 preserve exact segments。

- **订正（#196 分诊，2026-08-11 写回）。** **性质要降级。** `packages/web/src/router.dawn`
  的 doc 已经逐字自称「the **legacy** empty-dropping rule……the server does not route
  through this any more」，`dispatch`/`match_path` 只留给直接调用者与测试。所以这不是
  路由分叉，是**没删干净的过期公开 API**：精确命中 RD-12 逐字点名的「web 的 `match_path`/
  `dispatch`/`parse_query` 都是 `serve_app` 内脏」。去向是 RD-12 的包 pub 收窄，不是
  「共享唯一 pure path parser」，那件事 `dispatch_segs` 已经做完了。

## LIB-14 — P2 — tail capture 抹掉 encoded slash 的 segment 边界（已修）

<!-- audit-anchor: absent packages/web/src/types.dawn | pub fn param_segs -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `4825c84` 让 `Request.params` 持有
> 每个 capture **匹配到的段**（`Map[String, List[String]]`）而不是拼回的 String：`{name}`
> 一段，`{name*}` 余下若干段。`param` 读单段 capture，`param_segs` 读 tail capture，
> `/dav/a%2Fb` 与 `/dav/a/b` 因而在 handler 侧仍然可分。包破坏性变更，随 `web3 / 3.0.0` 发。

- **证据：S。** server 先按 raw slash 分段再 decode：`packages/web/src/server.dawn:244`，但 tail capture 最后用 `/` 拼成 String：`packages/web/src/router.dawn:96`。
- **边界：** `/dav/a%2Fb` 的单 segment `"a/b"` 与 `/dav/a/b` 的两个 segments 最终都得到 `rest = "a/b"`。
- **影响：** file/WebDAV/auth handler 无法区分两个 URI resource identity。
- **建议：** tail param 保留 `List[String]` 或带 raw encoding/segment boundaries 的专用类型。

## LIB-15 — P2 — `ServerHandle` 不拥有自己创建的 executor（已修）

<!-- audit-anchor: absent packages/web/src/server.dawn | executor: ExecutorService -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `aed3107` 把 `start` 创建的
> virtual-thread executor 存进 `ServerHandle`，`stop` 经 `release_handle` 固定顺序释放：
> executor 先 shutdown、再停 JDK server、最后**无条件** countDown，每步各自 `catch_fault`，
> 所以任一步抛出都不会再让 `join` 永久阻塞。`server.dawn` 的单测直接钉住「JDK 的 stop 抛
> 异常时 executor 仍被关掉」。包破坏性变更（handle 多一个字段），随 `web3 / 3.0.0` 发。

- **证据：S。** handle 只保存 server/port/latch：`packages/web/src/server.dawn:489`；`start` 创建 virtual-thread executor 后不保存：`:511`；`stop` 不 shutdown：`:527`。
- **影响：** start/stop lifecycle 没有确定释放全部 resources；stop exception 时 latch 也可能不 release。
- **建议：** handle 持有 executor；`stop` 的 finally 顺序停止 server、shutdown executor、无条件 countDown。

## LIB-16 — P2 — `Response` 可公开构造非法 HTTP 状态（部分修复）

<!-- audit-anchor: present packages/web/src/types.dawn | pub type Response = { -->

> **后续处置（2026-08-11 登记，实现更早）：partial。** header sanitizer 那半已由
> `a2d9571` 关闭：`header_name`/`header_value` 的**逐字符删除**换成谓词
> `valid_header_name`/`valid_header_value`，发射端拒绝而不是改写：`with_header` panic
> （程序用自己的字符串造头，送不出去是调用方的 bug，逐请求隔离把它渲染成 500），
> `try_with_header`/`try_redirect` 是请求输入派生值的形式，答 400。删除法留下的静默改写
> （`/a\r\nX: 1` 变成 `/aX: 1` 这类）因此消失。
>
> **仍开放：** `Response` 仍是 public record，record literal 可绕过构造器；no-body 状态集
> 仍只有 204/304，1xx 与 205 仍可带 entity；write boundary 也仍不重新校验。opaque
> `Response` 那半在 `web-api-v2-design.md` §四已被裁「不做」（status 是三位数字的开放集合），
> 重开必须显式回应该节；受检 `HeaderName`/`HeaderValue` 与统一的 1xx/204/205/304/HEAD
> 语义没有被 §四覆盖，是本项余下的可做面。

- **证据：S。** `Response` 是 public record literal：`packages/web/src/types.dawn:81`；header sanitizer 删除字符而非拒绝：`:214`；write boundary 不重新 validate：`packages/web/src/server.dawn:131`；no-body status 只覆盖 204/304：`:94`。
- **边界：** header name `":"` 可变 empty，`"X:A"` 与 `"XA"` collision；1xx/205 仍可带 entity。
- **影响：** safe constructor 的保证可被 record literal 绕过，最终是 host exception 或 protocol violation。
- **建议：** opaque `Response` 与 validated `HeaderName/HeaderValue`；write boundary defense-in-depth；统一 1xx、204、205、304、HEAD body semantics。

## LIB-17 — P2 — 两种 body limit 对 0/负数语义相反（已修）

<!-- audit-anchor: absent packages/web/src/middleware.dawn | limit > 0 -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `3a21be8` 让 `with_body_limit` 与
> `read_body` 用同一条读法：`limit <= 0` 是 unbounded，正数才是上限。原来的
> `len > limit` 使 `0` 只放行空 body、`-1` 连空 body 都 413，与底层 reader 恰好相反；
> 现在两处对 0 与负数给同一个答案，`middleware.dawn` 的单测钉住这一条。建议里的
> `Option[Int]` 表示法没有采用：统一读法已经关闭本项指出的分歧边界，换类型是另一次
> 包破坏，留给下一个 major。

- **证据：S。** middleware 直接 `len > limit`：`packages/web/src/middleware.dawn:53`；底层 reader 把 `limit <= 0` 当 unlimited：`packages/web/src/server.dawn:76`。
- **边界：** `-1` 在底层 unlimited、在 middleware 连 empty body 都拒；`0` 分别是 unlimited 与 empty-only。
- **影响：** config 迁移或组合 middleware 时可从 fail-closed 变 fail-open，且无 type/validation 提示。
- **建议：** 禁止 negative；用 `Option[Int]` 表示 unlimited；所有入口复用同一 validator。

## LIB-18 — P2 — streaming response 吞掉所有 fault 与 panic

<!-- audit-anchor: present packages/web/src/server.dawn | let _ = catch_panic -->

> **当前静态候选（未验证，不改严重度）：** streaming 分支把 `transferTo` 放进
> `catch_panic` 后丢弃整个结果，且 `ResponseBody.Stream` 不携带 expected length：
> `packages/web/src/server.dawn:163`、`:171`。除异常 disconnect/fault 外，上游若以 clean EOF
> 提前结束，当前层也可能把截短 body 当正常完成。R-AUDIT 没有构造网络探针；这里只记录
> clean-truncation 可能性，不新增 P0/P1，也不冒称已确认。

- **证据：S。** transfer 被 `catch_panic` 包裹，返回 Result 立即丢弃：`packages/web/src/server.dawn:162`。
- **影响：** client disconnect、upstream IO failure 与 program invariant panic 都无 log/metric且不可区分；request 看似正常结束。
- **建议：** 只降级 expected disconnect；structured log IO fault；program panic 必须进入统一 server error path。

- **订正（#196 分诊，2026-08-11 写回）。** **证据等级 S → K。**
  [`streaming-response-design.md`](../streaming-response-design.md) 逐字把「`catch_panic`
  当 finally 兜住客户端中途断开」写成方案（§4.4 同款做法，落地清单也照抄），按方法说明 §3
  的定义这属于「仓库已承认」。缺陷仍成立：三者不可区分、无 log/metric、clean truncation
  可能被当成功。它因此是「细化一条已裁决的兜底」，零破坏、成本极低，可搭 tempfile 一类
  的小刀一起做。

## LIB-19 — P2 — SHA-256 `Digest` public record 可伪造 invariant

<!-- audit-anchor: absent packages/sha2/src/sha256.dawn | pub opaque type Digest -->

- **证据：S。** digest state 是 public record：`packages/sha2/src/sha256.dawn:27`；`update/finish` 直接假定 `h` length、buffer length、total 相互一致：`:109`、`:127`。
- **影响：** caller 可构造 type-correct 但会 OOB 或输出错误 digest 的 state；API 把实现 invariant 变成用户责任。
- **建议：** `pub opaque type Digest`，只允许 `new/update/finish` 建立和推进状态。

- **订正与去向（#196 分诊，2026-08-11 写回）。** 本条是 RD-12 的原句（「`Digest` 立刻
  opaque」），不是新账，去向是 RD-12 的包 pub 收窄。**全表 ROI 最高**：改一个关键字，
  编译器源码零改动（`selfhost/src/pkg/` 的两个消费点只经 `new`/`update`/`finish`/`hex`
  使用它，从不写字面量、不读字段），哈希输出逐字节不变。
