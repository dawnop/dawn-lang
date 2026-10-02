# 标准库默认参数收敛：设计（K0–K19）

> 状态：current。本线的总纲：分组裁决、刀序与每刀的回填位置。K0（签名渲染默认表达式、
> LSP `textDocument/signatureHelp`）与 K1（`std/narrow` 的 `Rounding`）已落地；其余各刀落地时回填 §7「状态」并在这里改写被
> 事实推翻的前提。调研依据是 2026-10-02 的只读调研报告（仓外协作档，结论摘在 §2），
> 默认参数本身的语义见 [spec.md](spec.md) 3.1 节与 [named-args-design.md](named-args-design.md)。

---

## 1. 问题

#207 之前 Dawn 没有默认参数。那段时间长出来的 API 只能用「后缀一个名字」表达「差一个值」：

```dawn
narrow.round_f32_toward(x, "negative_inf")      # 舍入模式是字符串，非法值靠运行时 panic
gpu.launch3(k, gx, gy, gz, args)                 # 多两个轴就多一个名字
inflate.gunzip_bounded(src, Some(limit))         # 天花板是 None 的那个版本叫 gunzip
web.query_int_bounded_with(fastapi_errors(), req, "page", 1, 1, -1)
dev.addf_down(F32, s, a, b)                      # 「向下舍入且 ftz」根本拼不出来
```

默认参数落地以后，这些族里有一部分可以收成一个函数，有一部分不该收。本线的任务是分清
哪些是哪些、按什么顺序收，并先补齐一个工具链缺口：签名渲染里看不见默认值是什么。

## 2. 调研结论摘要

1. **前提修正一半。** `std/` 的 232 个 `pub fn` 里，真正「同一动词靠后缀区分、差一个纯值」的
   只有 narrow 的 `*_toward`、gpu 的 `launch3` / `with_gpu_fake_globals`、bytes 的 base64 两套
   字母表。`str` 的公开面已经接近 Kotlin / Rust 的分法（`trim_start`、`split_once`、
   `last_index_of` 在那两门语言里也是独立函数）。啰嗦主要在 packages：tileir 的 Dev 面、
   inflate 的 `*_bounded`、web 的 `*_with`。
2. **三条硬限制决定能合什么：** (a) 默认值看不见同一函数的其他形参（spec 3.1 节，「以后放宽
   不是破坏性变更」）；(b) builtin 签名不带默认（`Sig.param_defaults` 对非顶层 fn 恒空）；
   (c) 尾块填最后一个声明的形参，所以「body 放最后、默认值放 body 前」会逼所有
   `f(a, () => ...)` 调用改写。(a)(b) 挡住了 `cursor.find`、`parse_int_radix` 与 Dev 的
   load/store 族，归 B 组；(c) 决定 A 组把默认形参放在 body 之后。
3. **值用次数为 0。** 所有候选家族成员作为函数值出现的次数是 0（只在 `use` 列表里出现），
   所以「`let g = f` 后默认值丢失」不构成任何候选的否决理由，也不需要 Kotlin 1.4 式的
   「函数值保留默认」。
4. **先决缺口：** `sig_render` 把默认形参渲染成 `name: T = ...`；`dawn doc --builtins` /
   `--stdlib`、站点 stdlib 页、LSP hover 与 completion 走的都是它；LSP 没有
   `signatureHelp`。合并以后读者看得见「可以省」，看不见「省了是什么」。`cap: Option[Int] = ...`
   无伤大雅，`mode: Rounding = ...` 是实打实的信息损失。所以 K0 先补渲染。

## 3. 分组裁决

排序标准：语言纯洁与架构优雅优先，破坏性变更不计成本，只计刀数。

### A 组：直接合

| 编号 | 合并 | 改前 → 改后 |
|---|---|---|
| A1 | narrow：`Rounding = NearestEven \| NearestAway \| TowardZero \| Down \| Up` 成为 `round_binary` / `round_f32` / `round_tf32` 的 `mode` 默认参数，删两个 `*_toward`、两个 `*_away` 与字符串校验（`NearestAway` 来自 T17 的 `round_binary_away` / `round_tf32_away`，调研时还没有） | `round_f32_toward(x, "negative_inf")` → `round_f32(x, mode: Down)`；`round_tf32_away(x)` → `round_tf32(x, mode: NearestAway)` |
| A2 | inflate：天花板 `cap: Option[Int] = None`，`inflate_end` 并入 `inflate_from(src, from = 0, cap = None)`，`gunzip` / `zip.read` 同理 | `gunzip_bounded(src, Some(n))` → `gunzip(src, cap: Some(n))` |
| A3 | web：`fmt: ErrorFormat = default_errors()` 挪到尾部，`streaming` 收 `length: Option[Int] = None` | `query_int_bounded_with(f, req, ..)` → `query_int_bounded(req, .., fmt: f)` |
| A4 | gpu 宿主面：`launch(kernel, grid, args, gy = 1, gz = 1)`，`with_gpu_fake(kernels, body, globals = map.empty())` | `launch3(k, gx, gy, gz, hs)` → `launch(k, gx, hs, gy: gy, gz: gz)` |
| A5 | tileir：`trace_kernel(name, params, body, hints: Hints = [])` | `trace_kernel_hinted("k", ps, hs, f)` → `trace_kernel("k", ps, f, hints: hs)` |
| A6 | tileir Dev 属性族：`rounding` / `ftz` / `propagate_nan` / `overflow` / `align` / `visibility` / `constant` / `shared` / `unsigned_cmp` 成为默认参数；**明文推翻** `dev.dawn` 刀 T4 那段「属性是名字的一部分」注释 | `addf_down(F32, s, a, b)` → `addf(F32, s, a, b, rounding: Down)` |
| A7 | bytes：`Base64 = Standard \| StandardRaw \| Url \| UrlRaw` 成为 `to_base64` / `from_base64` 的 `enc` 默认参数 | `to_base64_url(sig)` → `to_base64(sig, enc: UrlRaw)` |
| A8 | 只加默认、不删函数：`str.pad_start` / `pad_end` 的 `pad = " "`，`bytes.index_of` 的 `from = 0` | 零调用改动 |

A4、A5、A6 把默认形参放在 body / args **之后**，是为了让现存的位置调用零改动；代价是这些
函数从此不能用尾块写（尾块会去填最后一个形参）。今天没有一处用尾块调它们。

### B 组：合，但先补语言能力

| 编号 | 能力 | 用它的候选 |
|---|---|---|
| B1 | 默认值可以引用**前面**的形参（Kotlin、JavaScript 允许；Scala 只允许前面的参数列表；Swift、Python 不允许）。`f$default$k` 从零元变成接收前 k 个形参 | `cursor.find(s, sub, from = start(s))`；Dev 的 `load` / `store` 五连合成 `strides = row_major(shape)`、`mask = None`、`hints = []` |
| B2 | `parse_int` 迁进 `std/fmt` 成为普通顶层函数，吞掉 `parse_int_radix`（`radix = 10`）。不让 builtin 表支持默认 | `parse_int_radix` 12 处 |
| B3 | 尾块前向匹配（Swift SE-0286）：尾块填第一个未被填、类型是函数的形参 | 让 A4/A5/A6 的 body 可以回到默认参数之前；独立设计文档，不在本刀序 |
| B4 | 工具：签名渲染默认表达式、LSP signatureHelp | 即 K0，A 组的前置 |

不需要的能力：函数值保留默认（值用次数为 0，见 §2.3）。

### C 组：不合

| 家族 | 理由 |
|---|---|
| `get` / `unwrap_or` / `expect` | 返回类型不同；「拿不到怎么办」放在 Option 组合子上（Kotlin `getOrElse`、Rust `unwrap_or`、Swift `??`），Dawn 已有 |
| `split` / `split_once` / `rsplit_once`；`decode_utf8_lossy` / `_checked` | 返回类型不同 |
| `trim` / `trim_start` / `trim_end`；`index_of` / `last_index_of` | 方向是动词的一部分，Kotlin、Rust、Python 无一合并 |
| `read_file` / `read_bytes`、`put` / `put_bytes`、`row` / `row_do` 等 | 实参类型不同，Dawn 没有重载 |
| `print` / `println` / `eprint` / `eprintln` | Rust、Kotlin 都保留四个；一千多处调用换来少三个名字 |
| `max` / `max_by`、`sort` / `sort_by` | bound 不同（`T: Ord` 对 `K: Ord`），`key = identity` 需要类型参数默认值 |
| `json_ok` / `json_response` | 默认值在首位（status）；`json_ok` 在 dawnop-site 有 59 处，是一个有名字的常用形状 |
| `serve_app` / `serve_app_with` | `cfg` 的默认要用 `port` 构造，`port` 与 `cfg.port` 会成两个真相 |
| narrow 按格式的 `round_bf16` 等、gpu `pack_*` | 格式就是函数的身份，已有按 dtype 分发的总入口 |
| `sqrt_approx`、`shr_i` / `shr_u`、`eq_u` 族 | 精度契约或符号性，换个值就是换一个函数 |

## 4. K0：签名携带默认表达式

### 4.1 `Sig` 的新形状

`Sig.param_defaults` 从 `List[Bool]` 换成 `List[Option[String]]`：`None` 是没有默认，
`Some(text)` 是默认值的源码原文。空列表的含义不变（非顶层 fn 的签名一律为空）。

任务单给了两条路：(a) 签名带源文本；(b) 渲染时按名找 `f$default$k` 的函数体再反渲染。
选 (a)，且选「换类型」而不是「加一个平行字段」：

- 平行的 `List[Bool]` 加 `List[Option[String]]` 是同一个事实的两份，必有一天不一致。换类型以后
  「有没有默认」就是 `is_some`，`checker.param_has_default` 是唯一读法。
- (b) 的代价不在序列化：`gatemap.py selfhost/src/check/types.dawn` 列出的 export-surface、
  incremental memo 都只在内存里传 `Sig` 值，**没有一处把 `Sig` 序列化**，(a) 的改动面是
  构造点（全仓 21 处，其中 17 处是 `param_defaults: []`）。(b) 的真实代价是反渲染丢作者写法：
  `map.empty()` 会变成 Core 里的调用形状，字符串字面量的转义要重新拼。
- 源文本由 **parser** 记，不由 passes 切。passes 手里只有 `Cx`，`Cx` 不存模块源文本
  （named-args-design 6.3 节当年卡在这里）；parser 手里有 token 流与码点数组，`assert` 记自己
  原文用的就是同一个数组（`SAssert` 的 `Option[String]`）。于是 `Param` 加
  `default_src: Option[String]`，passes 在建 `Sig` 时照抄。

`Param.default_src` 的写法：取默认表达式占用的每个 token，从源码按 span 切出原文；两个
token 之间只要隔着任何东西（空格、换行、注释）就补一个空格，紧挨着就什么都不补。效果是
多行默认折成一行、注释自然消失（注释不是 token），字面量保留原样的引号与转义
（`"\u{2007}"` 渲染出来仍是 `"\u{2007}"`）。`a  +  b` 会折成 `a + b`：签名是给人读的，
多余空白不算作者的意图。唯一会带换行的是 `"""` 字面量，渲染时折成空格。

构造器、trait 方法、effect operation、impl 方法与 builtin 的 `Sig` 都没有默认，仍为空或
`None`。`MethodSig.has_default` 是 trait 方法有没有默认**实现**，与本节无关。

### 4.2 渲染规则与 40 的理由

`sig_render` 把有默认的形参渲染成 `name: T = <expr>`，`<expr>` 由 `types.default_display`
给出：

1. 换行、回车、制表符换成空格，去首尾空白；
2. 不超过 `DEFAULT_SHOWN = 40` 个码点就原样输出；
3. 超过就截：保留前缀（去尾部空白），接 `…`，再把前缀里**没闭合的**字符串、括号与插值
   按由内到外补上闭合符；补完仍超宽就把前缀再缩一个码点，直到不超过 40。

例：`"a default far wider than any signature shows"` 渲染为
`"a default far wider than any signatur…"`；`f(` 加 35 个 `a` 再加 `, bbbb)`（44 个码点）
渲染为 `f(aaa…a,…)`，结尾的 `)` 是补上的。

**为什么是 40。** 本线计划要出现在签名里的默认值，最宽的是 `default_errors()` 与
`row_major(shape)`，16 个码点；其余是 `NearestEven`（11）、`map.empty()`（11）、
`NoAssumption`（12）、`None`、`[]`、`" "`。40 是最宽计划值的两倍半，计划内的默认值永远
不会被截。截断是为「默认值其实是一段计算」这种情况准备的：它会把后面的形参挤出 hover
的可见宽度。一个带三个默认形参的签名，最坏多出 3 × (40 + 3) 个码点，仍在一屏之内。

**为什么截了还要补闭合符。** 签名不只给人读：`scripts/param-change.py` 与
`scripts/api-diff.py` 按顶层逗号切形参表，一个被截在 `(` 或 `"` 里面的默认值会让后面所有
形参读不出来。补齐以后渲染永远是括号与引号平衡的，两个脚本只需要跳过字面量内部
（`mask_literals`），不需要知道截断规则。

### 4.3 LSP

hover 与 completion 的 detail 走同一个 `sig_render`，自动带上默认值。新增
`textDocument/signatureHelp`，能力声明 `signatureHelpProvider: { triggerCharacters: ["(", ","] }`：

- **找调用处**：从 token 流倒推（`lspc.call_at`），不看 AST。客户端在 `f(1, ` 这种半截状态
  发请求，这时缓冲区不解析，上一次分析又是别的文本。规则：光标前最内层未闭合的 `(`，可以
  穿过列表字面量的 `[`（`f([1, |` 仍是 `f` 的第一个实参），遇到 `{` 就停（块、lambda 体、
  记录字面量都不是这次调用的形参）；`(` 前必须是小写名字，`fn name(` 是声明不是调用；光标在
  字符串或注释里不给。
- **找签名**：先问分析结果（与 hover 同一个 `find_target`，目标的 span 必须正好是那个名字
  token），分析过期时按名字解析：`alias.f(` 查该模块别名的导出，否则依次本模块、std、
  builtin，最后是 `use m.{f}` 行（缓冲区不解析时 checker 不跑，本模块的名字表为空，但 `use`
  行通常已解析、被导入的模块是单独检查的）。**不解析时本模块自己的函数找不到**，这是已知
  局限。
- **当前形参**：数本次调用自己的顶层逗号；`recv.m(` 的接收者（限定词不是模块别名）与
  `x |> f(` 的左侧占第一个形参，所以下标加一；`name: ` 形式的具名实参按名字定位，名字不存在
  时给一个越界下标（客户端显示为不高亮）。
- **范围**：顶层函数、方法、trait 方法、effect operation 与 builtin（后两者没有默认，照样给
  签名）。Java 成员不做：它们的调用解析不到 `Sig`，也没有默认。构造器不做（`(` 前是大写名字）。
- 形参 label 用签名 label 里的 `[start, end)` UTF-16 偏移，不用子串：客户端按子串定位时，
  `a: Int` 会先在 `aa: Int` 里被找到。偏移来自 `types.sig_render_parts`，它把渲染拆成
  「`(` 之前、各形参、`)` 之后」三段，`sig_render` 本身就是三段拼回去，所以两者不可能不一致。

`scripts/selfhost-lsp-diff.sh` 的会话加了一个带两个默认参数的 `pad_to`（一个短、一个超宽）、
一次 hover 与六次 signatureHelp（按位置两次、具名一次、管道右侧一次、声明自身的形参表一次、
半截缓冲区一次），从此有 N−1 对拍。

### 4.4 机器读者

| 读者 | 改动 |
|---|---|
| `scripts/param-change.py` | 切形参表前先 `mask_literals`（字符串与字符字面量内部换成占位符，下标不变），默认值里的逗号与括号不再被当成结构；自测加三例 |
| `scripts/api-diff.py` | `split_defaults` 把默认值从签名上拿掉再比效果原子与形状（K0 前的 `= ...` 与 K0 后的 `= expr` 不再报成「signature changed」，默认值里的 `!x` 不再被当成效果）；默认值按形参名单独比：消失或变值算 Breaking，新增算 Additions，`...` 是「值未知的默认」不算变化；自测加四例。K1 补一条：形参表**末尾**新增、且每个都带默认的形参算 Additions（旧调用全部照编），插在已有形参之前或不带默认仍算 Breaking；自测再加四例 |
| `scripts/builtin-decl-contract` | builtin 没有默认，镜像不变（验证见提交说明） |
| `scripts/checker-corpus` | `default_params` 的「缺实参」诊断附带签名，`b: Int = ...` 变 `b: Int = 1`，已重录 |

### 4.5 落点

| 文件 | 内容 |
|---|---|
| `front/ast.dawn`、`front/parser.dawn` | `Param.default_src`，`tokens_source` |
| `check/types.dawn` | `Sig.param_defaults: List[Option[String]]`，`DEFAULT_SHOWN`、`default_display`、`closers_of`、`sig_render_parts` |
| `check/passes.dawn`、`check/checker.dawn`、`jvm/emit.dawn` | 构造点与 `param_has_default` |
| `lsp/lspq.dawn` | `Target.sig`、`offer_sig` |
| `lsp/lspc.dawn`、`lsp/server.dawn` | `call_at`、`signature_at`、`handle_signature_help`、能力声明 |

测试：`types` 的渲染与截断（含闭合符、插值、转义、恰好 40 与 41）、`checker` 的解析到渲染
全程（多行加注释的默认值折成 `[ 1, 2 ]`、字面量保留引号、无默认不变）、`lspc` 的调用处
扫描（嵌套、列表、具名、管道、声明、元组、字符串、块）。

## 5. 刀序

每刀一个 PR，仓内调用改动不超过 40 处。Emit-Change 一列是**预计**会动的检查 label，以
门禁实测为准；std 刀都要重生成 `selfhost/src/embed/stdsrc.dawn`，`std/modules.txt` 不动。

| 刀 | 内容 | 依赖 | Emit-Change |
|---|---|---|---|
| K0 | B4：默认表达式进 `Sig` 与 `sig_render`，LSP signatureHelp | 无 | `lsp`（实测；std 今天没有默认参数，`doc --builtins` 等不动） |
| K1 | A1：`std/narrow` 的 `Rounding` 与两族合并 | K0 | `doc --builtins`（实测见 §7）；narrow 契约判据不变 |
| K2 | A6 + A5：tileir Dev 属性族、`d_global`、alloca、`d_for` 的 unsigned、`trace_kernel` | K1（复用 `Rounding`） | 无 std 输出；tile-golden 185 个逐字节不动 |
| K3 | A2：inflate 四族 | 无 | 无（packages 不进 `doc --builtins`）；inflate major |
| K4 | A3：web 三族 | 无 | 无；web 6.0，dawnop-site 下次升钉改 8 处 |
| K5 | A4 + A7 + A8：gpu `launch` / `with_gpu_fake`、bytes base64、`pad_*` / `bytes.index_of` 加默认 | K0 | `doc --builtins`，可能 `doc site`；改 std 公开面必跑 run-diff |
| K6 | B1 语言能力（spec 3.1 节改写、checker、两个后端、interp），同刀只落 `cursor.find` | 无 | `doc --builtins`；`spike-native` 加默认引用形参的用例 |
| K7–K18 | B1 之后的 Dev load/store 五连合并，按 `scripts/tile-golden/kernels.dawn` 的段落与其它文件切 | K6 | 无；golden 逐字节不动 |
| K19 | B2：`parse_int` 迁 `std/fmt` 并吞 `parse_int_radix` | 无 | `doc --builtins`；builtin-decl-contract 镜像少一项 |

T17（`ftoi` saturating、`ftof` nearest_away）排在 K2 之后，直接写成
`float_to_int(.., saturating: Bool = false)` 与 `float_to_float(.., rounding: Rounding = NearestEven)`，
不再新增后缀名。B3 尾块前向匹配另立设计文档，不在本刀序。

## 6. 不做的（理由）

- **反渲染 `f$default$k` 的函数体。** 会丢作者写法（注释、转义、`map.empty()` 的拼法），而
  (a) 的代价只是 20 个构造点（§4.1）。
- **在 `Cx` 里存模块源文本，让 passes 切。** parser 已经有码点数组，`assert` 也是这么做的；
  把整份源文本塞进 `Cx` 会让每个持有 `Cx` 的地方（包括增量记忆）多背一份大字符串。
- **原样输出不截断。** 默认值是任意纯表达式（named-args 裁决 3），可以是一段计算；不截就会
  把后面的形参挤出 hover。
- **截断不补闭合符。** 两个按逗号切签名的脚本会读错，见 §4.2。
- **signatureHelp 用 AST 找调用处。** 客户端发请求时缓冲区常常不解析（`f(1, ` 正是典型），
  而不解析的模块根本不进 checker（`analyze.dawn` 的 `parse_failed`）。
- **为半截缓冲区里本模块自己的函数现场推签名。** 要类型解析，等于在 LSP 里再写一个 passes；
  客户端通常会自动补 `)`，那时缓冲区是解析的，走分析结果。
- **函数值保留默认（Kotlin 1.4 式适配）。** 值用次数为 0（§2.3）。
- **builtin 表支持默认值。** B2 的路是把 `parse_int` 搬进 std，不是让 builtin 表、
  `builtin-decl-contract` 的渲染与 P6 回读都学会默认值。

## 7. 状态

| 刀 | 状态 | 提交 |
|---|---|---|
| K0 | 已落地 | `8938471f`（PR #375 rebase 合入 main 后的哈希；分支上原为 `c53d7e85`） |
| K1 | 已落地 | `fd99b635`（分支哈希；合入 main 时若经 rebase，由协调者回填） |
| K2–K19 | 未开工 | |

### 7.1 K1 落地记录

- **面。** `pub type Rounding = NearestEven | NearestAway | TowardZero | Down | Up`，变体按 IEEE 754 §4.3
  的五个舍入方向属性起短名（`Down` / `Up` 是 roundTowardNegative / roundTowardPositive 的通行简称）。
  `round_binary(x, p, emin, emax, mode: Rounding = NearestEven)`、`round_f32(x, mode: ...)`、
  `round_tf32(x, mode: ...)`；删 `round_binary_away`、`round_binary_toward`、`round_f32_toward`、
  `round_tf32_away`。与 Tile IR 方言拼写（`nearest_even` / `nearest_away` / `zero` / `negative_inf` /
  `positive_inf`）的一一对应写在 `std/narrow.dawn` 文件头，**拼写函数不在 narrow**：它属于方言，K2 在
  `packages/tileir` 建。
- **实现。** 私有的 `round_nearest`（两种就近模式）与 `round_binary_toward`（三种定向模式）合成
  `round_binary` 里的两个 `match`：一个回答「量级要不要进一个 quantum」，一个回答「越过最大有限值时
  是无穷还是最大有限值」。非法模式的 `panic` 随字符串一起消失。
- **`round_bf16` / `round_fp16` 不加 `mode`。** 任务单允许加（只转调 `round_binary`）；没加的理由：格式是
  函数身份（§3 C 组），今天没有调用要 bf16/fp16 的定向舍入（tileref 的两处用 `round_binary(f, .., mode: TowardZero)`
  直接写），而 `round_bf16` 的签名是 narrow 契约 `emax-off-by-one` 变异体的锚点，没有需求就不动它。
- **调用方。** `packages/tileref` 8 处、`scripts/tile-gpu-diff/attr_diff.dawn` 1 处、
  `examples/projects/gpu_fake` 1 处，外加 narrow 自己的内联测试（五个模式各有断言，另加「显式写
  `NearestEven` 等于省略」两条）。f32 到 tf32 的 `zero` 原写作 `round_binary_toward(f, 11, -126, 127, "zero")`，
  现在写 `round_tf32(f, mode: TowardZero)`。
- **`std/moved.txt`。** `round_binary_toward` 与 `round_f32_toward` 在 v0.82.0 里是公开函数，
  `std-moved-check` 要求登记，补了两行带提示（since 0.83.0）；两个 `*_away` 是 v0.82.0 之后才加的，不登记。
- **narrow 契约。** 判据不变。`ties-away` 的锚点从 `let n = ...` 那一行改成 `match` 的
  `NearestEven -> ...` 臂；`no-subnormal-clamp` 的锚点仍带两行注释（定向函数并入后语句本身又唯一了，
  注释留在锚点里防下一个同构的舍入函数）。**负控发现：** 把 `Down` 臂改成 `Up` 的行为，契约照样全绿，
  因为 `narrow_round` 语料里**没有定向舍入的节**（27 节全是就近偶数）；抓住它的是 narrow 自己的内联测试
  `directed rounding takes the neighbour on the named side`，以及层 2 的 `attr_round` / `attr_ftof`（GPU）。
  给契约补定向节要改 `gen.py` 与 `.expect`，超出本刀「判据不变」的范围，留作后续。
- **api-diff。** K0 版把 `mode` 的新增报成三条「signature changed」（Breaking）；本刀教它认「末尾追加的
  带默认形参」（§4.4），实测报为 Additions，删掉的四个函数仍是 Breaking。

