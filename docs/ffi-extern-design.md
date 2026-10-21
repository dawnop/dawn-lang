# C extern：`fn f(..) = extern c "sym" else ..` 与公开头 `dawn_ffi.h`

> 状态：**current**（F0：设计稿与头文件已落地；F1 的语法、检查、Core 与后端已实现；F2 的清单和构建链路、F3 的 sqlite 包与目标明确的契约已实现，完整语法门禁扩展待 F4，
> 每刀落地后在末尾「落地记录」补哈希）。2026-10-21。依据：维护者工作区的
> `ruling-ffi-extern-surface-20261020.md`（14 条裁决与刀序）、`research-ffi-extern-surface-20261020.md`（三种语法对照、
> sqlite 桩的 ASan 实测、§8 待裁点）、`ruling-ffi-llvm-concurrency-20261004.md` 第 1 条、
> `ruling-full-native-20261020.md` 第 3 条。本文把 14 条裁决落成可实现的规格，不重裁。

## 要解决什么

native 后端已经自举，dawnop-site 要从 JVM 迁到 native，它的后端有一个绕不开的 C 库：SQLite（外加 libsimple 分词扩展）。
今天 Dawn 与 C 之间只有两条路，都不够：

- `use java`：只在 JVM 上有意义，native 与 wasm 在 checker 前置拒绝（`selfhost/src/c/emitc.dawn` 的 `CForeign` 分支）。
- 运行时 intrinsic（`RtGpu` 那十一项宿主函数是先例）：名字表是**编译器契约**，每加一个要改 `types.dawn`、
  两个后端与对账门禁。把 sqlite 的二十几个函数放进去，等于让编译器认识 sqlite。

要的是第三条路：**包自带一份 C 桩，语言里用一种最小的声明绑定它**，编译器不认识 sqlite，只认识「这个函数的实现是
包里某个符号」。

## 总览

```dawn
## a prepared statement for `sql`, or the engine's refusal
fn sq_prepare(db: Int, sql: String) -> Result[Int, ForeignError] !io =
  extern c "sq_prepare" else Err(no_native("sq_prepare"))
```

```c
#include "dawn_ffi.h"
DAWN_FFI_REQUIRE(1);

dawn_adt *DAWN_EXTERN(sq_prepare)(int64_t db, dawn_str *sql) { ... }
```

```toml
[native]
sources = ["src/sqlite_stub.c"]
```

三件东西各管一件事：Dawn 里的 `extern` 说**这个函数由 C 实现**；`dawn_ffi.h` 说**桩能用运行时的哪一小部分**；
清单里的 `[native]` 说**桩源文件是哪些**。裁决的 14 条分别落在下面各节，节首标注条号。

## 一、语法（裁决 1）

### 文法

普通 `fn` 声明的函数体换成 extern 体：

```
fn_decl     = [vis] "fn" NAME [tparams] "(" params ")" ["->" type] [effects] "=" body
body        = expr | extern_body
extern_body = "extern" "c" STRING [ "else" expr ]
```

- `extern`、`c` 是**上下文词**，只在函数体开头（`=` 之后、换行跳过之后）的这个位置特殊：下一个词是 `extern` 且再下一个词是
  `c` 且其后是字符串字面量，才走 extern 分支。其余位置它们仍是普通标识符（全仓 `.dawn` 里 `extern` 作为标识符出现 0 次，
  仍不做成硬关键字，免得夺走将来的名字）。判法与 `opaque`/`ctl` 一样由 `is_word` 做有界前瞻（`parser.dawn` 的 `is_word`）。
- 签名、效果行、可见性、文档注释全部沿用 `FnDecl`，**`FnDecl` 一个字段不加**。函数体位置多一种表达式节点
  `EExtern(sym, fallback: Option[Expr])`。
- `else` 后是一个表达式，与 `if ... else` 的排版同形；没有 `else` 即没有回退体。
- `extern` 体只合法于**顶层 `fn` 的整个函数体**。出现在 impl 方法、trait 方法、嵌套 `fn`、闭包、`let` 右侧，
  checker 一律报「`extern` can only be the whole body of a top-level function」。

不选 A（`extern fn { c "sym" } else { }`）：多出一种声明形式，`else` 跟在 `}` 后面还要给 formatter 学一条新衔接规则。
不选 C（`@extern(c, "sym")`）：Dawn 没有 `@` token，也没有任何标注机制，加了它 `__lex` 对现有 reject 语料的输出会变，
而且一旦有了通用标注语法就会有人要 `@inline`、`@deprecated`，为一个特性开这扇门不值。

### fmt

- 沿用 formatter 保留作者换行的规则，不引入通用行宽折行。一行形式为 `fn f(..) -> T !io = extern c "sym" else expr`。
- 多行形式在 `=` 后换行，缩进一级写 `extern c "sym"`，`else expr` 另起一行与之同缩进；`else` 后的表达式照表达式的缩进规则。
- `fmt --check` 的幂等性与「本仓全过 --check 只证自洽」的局限同其他语法一样，由 F1 的 fmt 语料钉住（`dawn-fmt-indent-model`
  是词法级启发式，新语法要在语料里各形状都有一例，而不是指望启发式碰巧对）。

### LSP 与编辑器

`EExtern` 住在 `FnDecl.body` 里，所以大纲、符号、引用、重命名、悬停的函数签名、文档注释、`dawn doc` 天然把它当普通函数。
额外的只有三处：

- 悬停：函数签名下多一行 `extern c "sym"`，有回退体时再注明「fallback on the JVM backend」。
- 词法着色：TextMate 的上下文规则给 `extern`、`c` 关键字色，字符串保留字符串色。LSP 继续只发送已解析的名字，回退体内参数、调用等走既有语义 token 与引用路径，不扩大协议载荷。
- 不提供「跳到 C 定义」：checker 不读 C 文件（见第四节「边界」）。

`editors/vscode` 的 TextMate 语法加上下文词；`scope-contract.js` 从 `parser.dawn` 的 `is_word(...)` 判定点读词表，
漏了会红；spec §1.4 的两份清单由 `doc-check.py` 对账，新上下文词同时进 spec 表。这些随 F1 做。

## 二、类型与检查（裁决 4、9）

一个 extern 函数的检查结果与后端无关：同一个模块在 JVM 和 native 上检查结果相同。

**边界类型**：参数与返回只许下表的类型，其余编译期拒绝（「type X cannot cross a C extern」）。

| Dawn | C 参数 | C 返回 |
|---|---|---|
| `Int` | `int64_t` | `int64_t` |
| `Float` | `double` | `double` |
| `Bool` | `bool` | `bool` |
| `Unit` | 不出现在参数 | `dawn_unit` |
| `String` | `dawn_str *` | `dawn_str *` |
| `Bytes` | `dawn_bytes *` | `dawn_bytes *` |
| `Option[T]`、`Result[T, ForeignError]` | `dawn_adt *` | `dawn_adt *`（桩构造，见头文件） |

`T` 取上表里的类型（`Result[Int, ForeignError]`、`Result[Bytes, ForeignError]`、`Option[String]`）。
**不跨**：用户 ADT、元组、记录（tag 是声明序号、字段掩码由编译器排，跨了就把布局冻成 ABI）、闭包（C 调 Dawn 要把
证据向量和着陆点交给第三方栈帧）、`List`/`Map`/`Set`、`Array`（头文件 ABI 2 的第一个候选，等第一个消费者）。
外部句柄一律编成 `Int`，Dawn 侧用 `opaque type` 包住，生命期交给 `bracket` 或 handler；GPU 宿主十一项已用这个办法，
LSan 零漏。

**效果行**：必须显式写出，且恰为 `!io`。不许纯（等于复活已删的 `unsafe_pure`），不许具名效果（C 侧没有证据向量），
不许效果变量。

**可见性（裁决 4）**：extern 函数只许私有或 `pub(pkg)`。`pub` 报「an extern function cannot be `pub`: wrap it in a
Dawn function」。包对外必须用 Dawn 包一层安全 API（做参数校验、把借用的约定藏起来、把 `Int` 句柄包成 `opaque type`），
这条由编译器强制，不靠评审。

**符号名形状**：`[a-z][a-z0-9]*(_[a-z0-9]+)*`，即小写、数字、单下划线分隔，不含 `__`，不以 `_` 结尾。
理由：编译器自己的 `mangle`（`emitc.dawn`，`dawn_<owner>__<name>`）含 `__`，两个名字空间因此不相交。

**回退体（裁决 9）**：按普通可移植 Dawn 检查，与外层函数同签名。回退体里不许 `use java`（native 与 wasm 加载这个模块时
会在 checker 前置拒绝，等于这个包在 native 上编不过；Dawn 没有条件编译，不为这一个口子造）。**回退体的形状只写成规则，
不加机器约束**：要么返回「这个后端没有」的错误值（`Err(ForeignError { kind: "<pkg>.unsupported_backend", .. })`、`None`），
要么给出与 C 实现等价的实现；不允许悄悄给出一个和 C 实现不同的「成功」结果，否则就成了两份语义。这一条靠评审和包测试守，
机器查不了，也不为它限制表达式语言。

## 三、借用语义与符号隔离（裁决 3、5、6）

### 借用（裁决 3）

沿用运行时的约定原文：「arguments are BORROWED, and anything a primitive keeps it dups for itself」（`dawn_rt.h`）。

- **参数一律借用**。桩不得 drop，调用期间值一定活着（rc 遍历在调用返回后才释放）。桩**不得把借来的指针存过调用**；要保留
  就拷进 C 内存。首版没有任何桩需要持有 Dawn 值，所以头文件干脆不导出 `dawn_dup`/`dawn_drop`。
- **返回值一律 owned**。头文件里的每个构造函数都交出一个新计数，并且**拷贝**它的 C 输入，桩手里没有需要释放的东西。
- **`owned` 参数首版不开放**，也不预留拼写：两个已知消费者（sqlite、GPU 宿主十一项）都用不到。将来第一个需要「把大 Bytes
  原地交给 C」的消费者出现时，再定拼写，并上 `DAWN_CONSUMES` 的对账契约（`scripts/builtin-decl-contract` 是同形先例）。
- sqlite 的具体后果：`sqlite3_bind_text` 必须用 `SQLITE_TRANSIENT`（调用返回前拷贝）。用 `SQLITE_STATIC` 是悬垂指针，
  因为 Dawn 字符串可能在下一条语句就被释放。这写进 `packages/sqlite` 的桩注释，F3 的负控也覆盖。

### NUL 结尾是 ABI 保证（裁决 5）

`dawn_str` 的 `len` 为准，可含内嵌 NUL，但 `p[len]` 永远是 NUL：所有构造函数都写一个（`dawn_str_new`），字面量指向
C 字符串字面量。这原本只是「给 C 库接缝的方便」，现在升格为保证，`dawn_rt.h` 里 `dawn_str` 的注释与 `dawn_str_new` 的
注释已改成这个措辞。`dawn_ffi_cstr` 依赖它：

- 无内嵌 NUL：返回 `p`，可以直接交给要 `const char *` 的库，零拷贝。
- 有内嵌 NUL：返回 `NULL`，**不截断**。截断会让 `open("a\0b")` 打开 "a"，那是另一个文件，调用方看不见。桩把 `NULL`
  回成自己的 `Err`（`"<pkg>.embedded_nul"`）。
- 空串是合法 C 串（长度 0），不是错误。

契约 `scripts/ffi-header-contract` 里 `str_nul_terminated` 一例对 `dawn_str_copy`、`dawn_str_concat`、`dawn_cursor_slice`、
空串、`dawn_str_new(0)` 各检查一次 `p[len] == 0`；将来新增产串的原语若漏写，这里是第一个红。

### 符号隔离（裁决 6）

若发射端把 `c "sym"` 直接写成对 `sym` 的调用，一个 extern 就能绑上 libc 的 `system`、`dlopen`、`execve`，参数按 Dawn ABI
传过去（`dawn_str *` 被当作 `char *` 读，第一个字段是 RC 头）。这不只是 UB，还绕过「C 只能来自包自带桩」这条供应链约束。

规则：发射端把 `extern c "sq_prepare"` 写成对 **`dawn_x_sq_prepare`** 的调用，桩用 `DAWN_EXTERN(sq_prepare)` 定义，
宏展开成同一个名字（`dawn_rt.h` 定义、`dawn_ffi.h` 包含，前缀与展开只有这一处定义，发射器与桩不会各写一遍）。libc 里没有 `dawn_x_*`，
所以**只能绑定包自带桩里的符号，不能绑定任意 libc 符号**。

同一个程序里两个包定义同名符号，驱动在调 cc 之前就能按声明查重给出 Dawn 层面的错误（见 F2），而不是让链接器报
`multiple definition`。两个 Dawn 声明绑同一个符号是允许的，只要 C 签名逐字一致，否则报错。

## 四、Core 与后端（裁决 7、10）

### `CExtern` 节点

Core 新增 `CExtern(sym: String, args: List[CExpr], fallback: Option[CExpr], ty: Ty, site: CSite)`，与 `CForeign` 对称：
`core.dawn` 里 `CForeign` 的注释早就预告「if it ever is [scheduled], it gets its own node for the JVM backend to refuse
in turn」。**不复用 `CIntrinsic`**：intrinsic 的名字表（`types.dawn` 的 `Rt`/`Intr`）是编译器契约，由
`intrinsic-parity.py` 与 `builtin-decl-contract` 逐项对账；把包桩的符号塞进去，名字表的语义就被稀释成「也许是某个包的」，
那两道门也就守不住任何东西。

函数体是 `EExtern` 的 `fn`，lowering 把它降成 `CExtern(sym, <形参按序的 CVar>, fallback, ret_ty, site)`，作为该函数的整个体。
一个 backend 无关的小 pass **选臂**在各后端驱动里最先运行：

| 后端 | 选臂的结果 |
|---|---|
| native、wasm | 丢掉 `fallback`（置 `None`），保留 `CExtern`；rc、infer、reach、lint 之后都看不到回退体，只被回退体引用的函数因此不被发射 |
| JVM | 有回退体：用 `fallback` 替换 `CExtern`，之后与普通函数无异；没有：编译期拒绝 |

JVM 的拒绝文案：「extern function `f` has no fallback body and the JVM backend has no C」。**不加 `jvm` 子句**（裁决 10）：
两条通往 Java 的路规则要写两遍，而回退体里用 `use java` 又会让 native 加载该模块时前置拒绝，等于这个包在 native 上编不过。
也不用 Panama 或 JNI：桩是按 `dawn_rt.h` 写的，JVM 上没有这些结构；FFM 在钉住的 JDK 21 上是预览；JNI 违反 spec §12.3。
两后端对称是 **intrinsic 契约层**的义务，不是 FFI 的：`runtime-intrinsics-design.md` 的分层里 FFI 在最外层，
spec §9 原话「FFI 本质不可移植」。extern 只守两条更弱的性质：类型检查结果与后端无关；不对称只以两种显式形式出现
（编译期拒绝、运行时 `Err`）。

comptime 解释器（`interp`）见到 `CExtern` 一律拒绝，同 std-only 的 intrinsic。

### 发射

emitc 对每个被调用的符号发一次原型 `extern <ret> DAWN_EXTERN(<sym>)(<args>);`，调用点是一次普通 C 调用，参数借用，返回值当作 owned
交给 rc 遍历（与 intrinsic 的约定一致，没有 owned 参数位）。native 后端拒绝 `use java` 的老规矩不变。
F2 的 `dawnc emitc` 只出 `.c`，要把包的 C 源列出来一并提示，否则手动 cc 的用户会遇到未定义符号。

### 边界

checker 不打开任何 `.c` 文件，不解析 C。`[native] sources` 的内容只在**驱动**阶段读：符号查重与「缺桩」诊断用一次词法扫描
（识别 `DAWN_EXTERN ( <ident> )` 的定义，跳过注释与字符串），并对能辨认的公开 ABI 签名做一致性检查。
它不展开预处理器、宏或 typedef，不是 C 安全验证；复杂声明可能漏报，条件编译中的定义可能被计入，最终由 cc/link 兜底。

## 五、C 源声明与构建（裁决 2、14）

### `[native] sources`

```toml
[native]
sources = ["src/sqlite_stub.c"]
```

- 只有一个键 `sources`，字符串数组，顺序即编译顺序；未知键报错。旧编译器对未知表本来就报错
  （`manifestv.dawn` 的 `unknown table`），天然带最低版本门槛，不另设版本字段。
- 路径相对包根，必须在 `src/` 下、以 `.c` 结尾、无 `..`、非绝对、不重复，文件必须存在（Dawn 层面的错误，不是 cc 的）。
  放在 `src/` 下是因为 `s1:` 源码摘要覆盖 `src_root` 下所有普通文件、`d1:` 树哈希覆盖整棵树：C 文件改一个字节，
  url 依赖的锁与 build-info 不用改任何东西就会变。native/wasm 驱动在读取桩之前，对实际加载的 URL 归档
  各重验一次 `d1:`，也覆盖已存在的热缓存；否则 resolver 的热命中捷径会漏掉缓存中的 C/头文件修改。模块加载只认 `.dawn`，`.c` 混在 `src/` 里不影响模块图。
- 依赖包的 `[native]` 同样生效（path、url、传递依赖一视同仁）。没有 `[native]` 的包里写了 extern，native 构建在驱动阶段报
  「extern needs the package to list its C sources under [native]」；单文件程序没有清单，同理。JVM 构建不关心。
- 不支持 `-l`、编译旗标、构建脚本：链接行要能从清单静态读出（供应链判据）。外部库一律在桩里 `dlopen`。
  glibc 2.34 起 `dlopen` 在 libc 里，不需要 `-ldl`；更老的 glibc 与静态链接下 `dlopen` 不可靠，写进 spec 的限制。
- wasm：同一份桩会被 wasi 的 clang 再编一遍，桩必须自己 `#ifdef __wasi__` 答 `Err("<pkg>.unsupported_backend", ..)`，
  F2 的契约把每个带 C 源的包的桩也编一遍 wasm。

### `dawn_ffi.h` 怎么安装

头文件放在 `runtime/c/dawn_ffi.h`，**在运行时头旁边**，是 header-only（`static inline`，包含 `dawn_rt.h`），所以安装路径与
`dawn_rt.h` 完全相同，不新增机制：

1. `scripts/gen-rtsrc.py` 的 `FILES` 加 `"dawn_ffi.h"`，生成物 `selfhost/src/embed/rtsrc.dawn` 带上它；
2. `cdriver.dawn` 的嵌入新鲜度检查与 `nmain.dawn` 的暂存循环（现在是 `["dawn_rt.c", "dawn_rt.h", ...]`）各加一项，
   于是构建时它与 `dawn_rt.h` 一起被写进暂存目录，`-I $work` 已在 cc 命令行上；
3. 每个实际加载的包将自己的 `src/` 树独立暂存到 `native/<序号>/src/`，保留本地头文件和子目录，
   不扁平化；只把清单列出的 `.c` 追加到 native 与 wasm 两条 cc 命令。包内 include 以各自的源目录解析，
   不把不同包的头放进共享搜索路径。`src/` 和其下的符号链接均拒绝，与 `s1:`/`d1:` 的输入约束一致。包根的规范路径用于去重，`src/` 自身不允许是链接。
   根包先收集，依赖按已加载模块的依赖顺序收集，同一包根只取一次；只声明但未加载的依赖不编译。
   `build`、`run`、`test` 使用同一份计划；`emitc` 在 stderr 提示各包源文件和头目录，供手动编译使用。
   两个 Dawn 声明若使用同一个符号，须有相同的 C ABI 签名；声明还须在自己的包找到桩。

**这三步放在 F2，不在 F0**：F0 的头只被契约直接以 `-I runtime/c` 使用，没有任何桩能进到 native 构建，提前嵌入只会让每个
native 二进制多带一份没人读的头，并且让 F0 碰编译器源码。F0 因此是纯增量（新增一个头、一个契约，外加把两条掩码宏从
`dawn_rt.c` 挪进 `dawn_rt.h`）。

`-DDAWN_RT_INLINE_RC` 必须到达程序的每个翻译单元（`dawn_rt.h` 的注释：混着编会链接失败，那是大声出错的方式）。
驱动从主编译行提取共同的目标、优化与 RC 选项，逐个编译桩并只给该包加入自己的 `src/` include 目录，然后把对象一起链接。
契约用 plain、inline RC、ASan/UBSan/LSan 与 wasm 的真实编译行证明这些选项都到达每个桩。

## 六、`dawn_ffi.h` 的 API（裁决 5、8）

头文件版本 **`DAWN_FFI_ABI` = 1**。名字的增加不动版本号；名字改义或删除才动。桩在 include 之后写 `DAWN_FFI_REQUIRE(1);`，
版本不符时编译在那一行停下并说一句人话，而不是表现成一个错的答案。

| 名字 | 作用 |
|---|---|
| `DAWN_FFI_ABI`、`DAWN_FFI_REQUIRE(n)` | 版本号与编译期检查 |
| `DAWN_EXTERN(sym)` | 桩的链接名，展开为 `dawn_x_<sym>` |
| `dawn_ffi_str_len(s)`、`dawn_ffi_str_data(s)` | 字符串的长度与字节（不一定是 C 串） |
| `dawn_ffi_cstr(s)` | 取 NUL 结尾 C 串；内嵌 NUL 返回 `NULL`，不截断 |
| `dawn_ffi_bytes_len(b)`、`dawn_ffi_bytes_data(b)` | Bytes 的长度与字节 |
| `dawn_ffi_str_copy(p, n)`、`dawn_ffi_str_from_cstr(c)`、`dawn_ffi_bytes_copy(p, n)` | 构造新的 String、Bytes（拷贝输入） |
| `dawn_ffi_box_int/bool/float(v)`、`dawn_ffi_box_unit()` | 造 `ok`/`some` 的擦除载荷 |
| `dawn_ffi_ok(payload)`、`dawn_ffi_err(kind, message)` | 构造 `Ok(..)`、`Err(ForeignError{kind, message, None})`；`err` 拷贝两个串 |
| `dawn_ffi_some(payload)`、`dawn_ffi_none()` | 构造 `Some(..)`、`None` |
| `dawn_ffi_is_ok(r)`、`dawn_ffi_is_some(o)`、`dawn_ffi_payload(a)` | 读 Result、Option 的分支与载荷（借用） |
| `dawn_ffi_err_kind(r)`、`dawn_ffi_err_message(r)` | 读 `Err` 的 `ForeignError`（借用的字符串） |
| `dawn_ffi_peek_int/bool/float(payload)` | 读擦除载荷里的标量 |
| `dawn_ffi_panic(message)` | 唯一的「拒绝继续」，仅限调用方违约，`_Noreturn` |

Int、Float、Bool 是普通 C 标量，不需要任何名字。

**围栏**：头文件末尾 `#pragma GCC poison` 掉 `dawn_fault`、`dawn_panic`、`dawn_dup`、`dawn_drop`、`dawn_drop_slow`、
`dawn_adt_new`、`dawn_adt_new_wide`、`dawn_str_new`、`dawn_str_copy`、`dawn_some`、`dawn_none`、`dawn_box_*`、
`dawn_peek_int/bool`、`dawn_bytes_utf8`。一个 include 了 `dawn_ffi.h` 的桩翻译单元，要碰这些名字就是编译错误，
想要就得回来在这里加一个名字并写明为什么（这也是「不导出 `dawn_fault` 与 RC 内部」由机器守住的方式）。发射出的代码和运行时自己
只 include `dawn_rt.h`，不受影响。

**`dawn_panic` 的唯一用途（裁决 8）**：**调用方违约**，例如桩文档里写明「下标须在 `[0, n)`」而传来了 `-1`，与运行时自己
对越界下标 panic 的判据一致（spec §9.8：外部世界造成的失败不是 panic）。外部世界的失败（文件不存在、库被锁、缺共享库）
一律回 `Result`，可恢复。panic 的强制展开会穿过桩的栈帧而不运行桩自己的任何清理，所以要在桩持有 C 资源**之前**调，不要之后。
`dawn_fault` 不导出：它同样是强制展开，桩里已拿到的 C 资源（没 finalize 的语句、malloc 的缓冲）会全部泄漏，第三方库的帧若在栈上，
库内部状态也被跳过；错误模型里它只给 io 原语失败用。

**掩码单一来源**：`Some`、`Ok`、`Err` 的「一个擦除字段」掩码与 `ForeignError` 的「三个引用字段」掩码原来写在
`dawn_rt.c`（`DAWN_MASK_ONE_BOXED`、`DAWN_MASK_THREE_BOXED`）。头文件要构造这些值，于是两条 `#define` 挪进 `dawn_rt.h`，
运行时与头文件读同一个定义，而不是各抄一份。

## 七、自测：`scripts/ffi-header-contract`

F1 之前语言里还没有 extern，所以头文件靠一个不经 Dawn 语法的 C 程序来守：

- `stub.c` 只 include `dawn_ffi.h`，像包的桩一样写十三个 `dawn_x_t_*` 函数，读每种参数、造每种答案、读一个传进来的 `Result`、
  触发那个 panic；
- `host.c` 扮演发射代码：借用传参、答案恰好 drop 一次，并且用 `dawn_rt.h` 自己的视角检查每个值的 tag、字段数、掩码和
  装箱（所以头文件里一个与运行时不一致的构造函数在这里红，而不是首先红在某个包的程序里）；
- 与真实 `dawn_rt.c` 链接，三种构建（plain `-O1`、`-O2 -DDAWN_RT_INLINE_RC`、ASan 加 UBSan 加泄漏检测），输出须与手写的
  `expected.txt` 相等；panic 单独驱动：`--panic` 须退出码 1 且 stderr 恰为 `panic: t.checked: index below zero`。

负控（`mutate.py` 持有锚点，由 `mutation-anchor-preflight` 在构建前证明各自恰好出现一次）：

| 负控 | 破坏 | 必须看到 |
|---|---|---|
| `abi-mismatch` | 头里的 ABI 号改成 2，桩仍要 1 | 桩编译失败，且失败原因是 ABI 检查那一句 |
| `cstr-truncates` | `dawn_ffi_cstr` 对内嵌 NUL 改为截断 | 契约红（`cstr_embedded_nul`） |
| `err-mask-short` | `ForeignError` 的掩码只覆盖一个字段 | ASan/LSan 泄漏加掩码断言红 |
| `bytes-cut-at-nul` | `dawn_ffi_bytes_copy` 在第一个零字节处截断 | 契约红（`bytes`） |
| `fence-open` | 把 `dawn_fault` 移出 poison 列表 | `fault_stub.c`（真头下必须编不过）此时必须编过，证明前面那次红是围栏而不是别的错误 |

墙钟：本机 11 秒（三次构建加五个负控，纯 cc，没有 JVM）；已用 gcc 与 clang 20 各跑一遍。接入 CI 的 `contracts-3`，
按 30 秒记，规划值 375 秒到 405 秒，超时 21 分钟，`push-total` 由 22523 秒到 22553 秒（`Gate-Budget` 写在提交里）。

### 性能断言的出处

本文对性能只有一处断言：**错误与借用用 RC 契约守得住，不需要桩做任何计数**。出处是调研里的本机实测：一个只依赖 `dawn_rt.h`
的 sqlite 桩（约 110 行，dlopen `libsqlite3.so.0`）加一个模仿发射代码的主程序，在 ASan/LSan 下跑通 open、prepare、bind、step、
column、错误路径、`load_extension`，零泄漏；负控（循环里少一个 `dawn_drop`）报 31 字节泄漏
（`research-ffi-extern-surface-20261020.md` §2.2）。头文件是 `static inline` 的薄封装，没有性能主张，也不需要：F0 不进任何热路径。
头文件的「零成本」不作断言；F3 的 `packages/sqlite` 有了真实调用量再量。

## 八、种子策略（裁决 14）

**编译器零轮种子，一次发布即可**。selfhost、compiler-plan、std 都不用 extern，所以种子编译器不需要认识它
（与 `named-args-design.md` 同型的判断）：

- `selfhost/src`、`compiler-plan/src`、`std/`：不用 extern，不受种子窗口约束。
- `packages/sqlite`、`scripts/grammar-corpus/accept/*extern*`：由 HEAD 工具链编，同一 PR 或下一 PR 即可用。
- `selfhost-fmt-diff.sh` 的语料是 HEAD 与上一 tag 的路径交集，新文件晚一个 release 才进对拍，那时上一个 tag 已认识 extern。
- `selfhost-prev-diff.sh` 的语料是写死的列表：**不要在 extern 发布之前把 `packages/sqlite` 加进去**。
- dawnop-site 按 `.dawn-version` 钉某个 release：extern 发布后 bump 一次，再引入 `[deps.sqlite]`。

「三期两发布」只在将来 **std 自己用 extern**（例如 GPU 宿主面不迁出 std）时才付。能守住零轮的前提只有一个：std 不用 extern。

## 九、刀序、验收与负控

F0 是本文与头文件（已完成，见第七节）。

| 刀 | 内容 | 验收（全满足才过） | 先证明会红的负控 |
|---|---|---|---|
| F1 | 解析（`EExtern`）、fmt、astdump；checker（边界类型、效果行恰为 `!io`、可见性、符号名形状、回退体可移植、`extern` 只许整个顶层函数体）；`CExtern` 与选臂 pass；rc/infer/reach/lint/coredump 各臂；`interp` 拒绝；emitc 发 `dawn_x_` 原型与调用；JVM 发回退体或拒绝；`emitc.dawn` 里「there is none」的拒绝文案改为指向 extern | 树内一个测试桩（放 `scripts/` 语料，不经包）在 native 与 wasm 上跑、ASan/LSan 干净；同一程序 JVM 走回退体；三目标 stdout 符合预期；现有语料 `__lex`/`__parse` 输出不变；checker 不打开任何 `.c` | 效果行写纯、回退体含 `use java`、符号名带 `__`、`pub extern`、边界类型写 `List`，各自编译期被拒；桩里少一个 `dawn_drop` 的反例（若桩持有值）LSan 报漏 |
| F2 | 清单 `[native] sources` 与 Planner（`compiler-plan` inline tests）；`nmain` 的暂存与两条 cc 行；`dawn_ffi.h` 的嵌入与暂存（`gen-rtsrc.py`、`cdriver`、`nmain`）；符号查重与缺桩诊断；`dawnc emitc` 提示；JVM 侧的拒绝与回退在包路径上同样成立 | path 依赖包带一个 `.c`，native 与 wasm 都 build 并通过 F1 语料；改 C 文件一个字节，url 依赖的 `d1:` 校验报错；清单列出不存在的 `.c`，报 Dawn 层面的错；两包同名符号，cc 之前报错；`./bin/dawn test compiler-plan` 覆盖新表 | 同名符号、缺文件、`sources` 含 `..`、未知键，各自被拒；去掉暂存里的 `dawn_ffi.h` 则桩编译红 |
| F3 | `packages/sqlite`：桩约 400 行 C、约 25 个 extern、Dawn 侧 API、native/ASan/JVM 三组测试、README；加载 libsimple 走 C 接口 `sqlite3_load_extension`（裁决 13），SQL 函数 `load_extension()` 保持关闭 | 后端 `db/sql.dawn` 用到的全部能力有对位；libsimple 经 C 接口加载、FTS5 `simple` 分词可查；LSan 零漏；缺 `libsqlite3.so.0` 时答 `sqlite.no_library` 而不是崩；JVM 上每个操作答 `sqlite.unsupported_backend` | `bind_text` 改用 `SQLITE_STATIC` 须被测试抓到；故意漏一个 `finalize` 须 LSan 红；SQL 里调 `load_extension()` 须失败 |
| F4 | 门禁接线：ASan 变体、grammar-corpus（`accept/` 各形状、`reject/` 各错误且钉 `# expect:` 诊断序列）、fmt 语料、LSP（semantic tokens、悬停）、编辑器语法、doc-check（spec §1.4 的上下文词表）、gatemap 登记新门、CI 墙钟与 `Gate-Budget` | 全部新门在 CI 绿；`scripts/native-cli-diff.sh` 里注明 sqlite 包**不**进两后端对拍的原因（它的报告在两个后端上本来就不同） | 各门的变异体先证明会红；新门接线后 `steps_lock.py record` |

dawnop-site 过渡期（裁决 11，不属于这四刀）：引入 `effect Db`，配两个入口，JDBC handler 与 native handler，两条臂共享业务代码对拍；
`dawnc build main_native.dawn` 的模块图里没有 `db/jdbc.dawn`，不触发 `use java` 拒绝；切换完成后删 JDBC 入口。
`packages/sqlite` 放在树内（裁决 12），dawnop-site 用 url+subdir 消费，与 web 相同。

## 不做的（理由）

- **`owned` 参数**：两个已知消费者都用不到；拼写与 `DAWN_CONSUMES` 对账契约等第一个需要它的消费者出现再定。现在不预留名字，
  免得预留的拼写成为将来的包袱。
- **`jvm` 子句、Panama、JNI**：两条通往 Java 的路规则写两遍；回退体里用 `use java` 会让 native 编不过；桩按 `dawn_rt.h`
  写，JVM 上没有这些结构；FFM 在 JDK 21 上是预览；JNI 违反 spec §12.3。
- **任意 libc 符号**：`dawn_x_` 前缀就是为了让 extern 只能绑包自带桩里的符号。要用 libc 的函数，在桩里包一层，包一层的那份 C
  就是被评审与摘要覆盖的东西。
- **SQL 函数 `load_extension()`**：SQLite 文档的警告是，只应用 `SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION` 打开 C 接口，保持 SQL
  函数关闭，防止 SQL 注入拿到加载扩展的能力。包只用 `sqlite3_db_config` 加 `sqlite3_load_extension`，且只在显式调用 `load_extension` 的区间打开 C 入口，返回前关闭。
- **`use c` 拼写**：撞编译器自己的 `c/` 目录模块，且形状是「声明函数」而不是「引入命名空间」。
- **纯 extern、具名效果的 extern**：前者复活已删的 `unsafe_pure`，后者 C 侧没有证据向量。
- **通用 C ABI（指针、结构体、可变参数）与头文件导入**：Perceus 下只有对着运行时写的桩守得住令牌纪律。
- **回调（C 调 Dawn）**：要把证据向量和着陆点交给第三方栈帧。
- **托管外部指针（带终结器）**：`Int` 句柄加 `bracket` 已够，GPU 已证明。
- **`-l`、编译旗标与构建脚本**：链接行要能从清单静态读出。
- **用户 ADT、元组跨边界**：会把编译器内部布局冻成 ABI。
- **桩里的 `dawn_fault`**：强制展开不清理 C 资源，见第六节。
- **按后端选模块的条件编译**：dawnop-site 的双入口已够过渡期用；为一个过渡期造一套 `cfg` 是长期语言面换短期便利。
- **把 sqlite 放进 `Rt` 契约表**：裁决已否，`intrinsic-parity.py` 一行不改。
- **在 `dawn_ffi.h` 里导出数组**：首版没有消费者；这是 ABI 2 的第一个候选，到时再加，加名字不动版本号。

## 落地记录

- F0：`runtime/c/dawn_ffi.h`、`scripts/ffi-header-contract/`、`DAWN_MASK_*` 挪进 `dawn_rt.h`、本文。提交哈希待 PR 合并后回填。

- F1（95fd4a96）：`EExtern`、边界检查、`XExtern`/`CExtern`、后端选臂、借用 RC、C 原型与调用、JVM 回退及拒绝、grammar/fmt/LSP 契约。`DAWN_EXTERN` 定义移至两种翻译单元共享的 `dawn_rt.h`，避免发射代码包含 FFI 的 poison 围栏；公开头的安装仍留 F2。

- F2（本提交）：`[native] sources` 的清单验证与 Planner 测试、按加载图收集、每包完整 `src/` 暂存、共享目标选项、
  `dawn_ffi.h` 嵌入及新鲜度检查、包符号归属与可识别 ABI 签名检查、`emitc` 提示、C/头文件摘要负控。
  契约为 `scripts/ffi-sources-contract/run.sh`，同一 F1 transcript 在 path、url+subdir、native、wasm、JVM 上验收。

- F3（本 PR）：`packages/sqlite` 的 Linux/glibc ≥2.34 loader、非复用 token、
  物化查询和 bracket 事务；SQLite 下限 3.35.5，当前夹具 3.54.1；固定 libsimple
  v0.7.1 的中文、拼音、排序及三个触发器；C 入口开启期间仍拒绝 SQL 加载。
  `scripts/sqlite-contract` 先运行逐条负控，再验收 plain/inline RC 与完整插桩引擎，
  JVM/WASI 每个入口实跑 unsupported；门禁分别接 contracts-3 和 wasm-target。
  panic 清理错误写 stderr 并保留原 panic，正常清理错误返回 Result。


### F3 包的具体约定

`sqlite/sqlite` 的公开面采用调研 §2.2：`Db`、`Value`、`Col`、`Rows`、`TxMode`，
以及 `with_db`、`query`、`execute`、`execute_changes`、`last_id`、`busy_timeout`、
`in_transaction`、`with_tx`、`load_extension`。`with_db` 默认普通路径，可显式允许 URI；
Stmt 不公开。仅支持 Linux/glibc ≥2.34 的动态链接 native，JVM 和 WASI 的每个入口返回
`sqlite.unsupported_backend`。生产桩只 dlopen 系统 `libsqlite3.so.0`，测试引擎不进入包。

句柄为不复用的正整数 token，表记录种类、父连接及语句状态；释放时删除节点，空表不保留
SQLite 资源的全局根。每次语句调用同时验证父连接，重复 finalize 与陈旧 token 返回
`sqlite.invalid_handle`。Dawn RC 只管理复制出的值，bracket 管 SQLite 生命周期；正常
返回检查 close/finalize，已有 Err 保留原 kind 并附清理错误，panic 由 bracket 收尾。
事务先读真实 autocommit，拒绝嵌套；body Err、panic 和 commit Err 都回滚，已经自动
回滚时不再发无效 rollback。没有保存点或自动重试。

参数按 1 起算、列按 0 起算，数量和 C int 范围先校验。query 在 step 前复制列名，
每行先判 NULL，再按 Col 转换并立即复制文本；非法 UTF-8 返回 `sqlite.invalid_utf8`。
prepare 拒绝空 SQL 和多条有效语句，允许末尾空白和注释。execute 消费单条语句；
execute_changes 仅供 DML，沿用 sqlite3_changes 的 int 范围及 DDL 保留前值的语义。

不做的沿用本设计及 F3 调研 §7.3：生产 vendor、C flags/链接库/构建脚本、静态 simple、
WASI 持久化、借用列视图、自动终结器、语句池、BLOB 流、回调及连接池均不增加。
