# 包内可见档 `pub(pkg)`

> 状态：**current** —— 裁决 1（2026-09-24）的落地设计。动码前写成，实现后回填（§十）。
> 他语言调研原文在 `agent-handoff/research-package-visibility-20260924.md`（本仓外），结论摘在 §二。

## 一、问题

Dawn 的可见性今天只有两档：模块私有（默认）与 `pub`（spec §10.4）。一个跨模块、但只在
本包内部消费的名字，作者只有两条路：公开它（它就进了包的公开面，删它是 semver major），
或者复制一份。调研（`debt-survey-2026-09-07`）里三条架构债都卡在这一个缺口上：

- **ARCH-N05**：`ir/lower.dawn` 的 `subst_subject`/`trait_method_sig` 不是 `pub`，
  `jvm/emit.dawn` 于是各写一份，注释自认「a drift between the two is a VerifyError」。
- **ARCH-N12**：`Cx`（`check/cx.dawn`）47 字段被 9 个模块直读，只能 `pub type`。
- **LIB-13 残差**：`packages/web` 的 `dispatch_segs`/`validate_routes`/`route_meta`/`Dispatch`
  是 `server.dawn` 跨模块消费的 seam，web4 major 窗口里想收而收不了
  （`docs/codebase-audit-v2/05-stdlib-and-packages.md` LIB-13「处置」段）。

## 二、先例对照（摘要）

| 语言 | 形式 | 边界 | 对 Dawn 的取舍 |
|---|---|---|---|
| Rust | `pub(crate)` / `pub(super)` / `pub(in path)`（RFC 1422） | crate / 模块树 | 取**拼写形状**：复用 `pub`，不加硬关键字；private-in-public 规则同 SEM-07 |
| Swift | `package`（SE-0386） | `-package-name` 相同的模块 | 取**语义**：包内跨模块可见；「public 函数不能用 package 类型」 |
| Kotlin | `internal` | 构建工具的「模块」 | 反例：test 要 `-Xfriend-paths` 打洞；Dawn 的 test 块在模块内，天然同包 |
| Go | 大小写 + `internal/` 目录 | Go package / 目录树 | 大小写与 Dawn 冲突；目录是模块粒度 |
| Java 9 / Cabal / dune / Roc / Gleam `internal_modules` | 描述文件列导出模块 | 模块粒度 | 解不了 ARCH-N05（要藏的是一个函数） |
| Gleam `@internal` | 声明级标注，**不强制** | 包 | 反例：不强制就复现 LIB-13（公开面挂着零调用者的名字） |

## 三、语法

```dawn
pub(pkg) fn subst_subject(...) -> Sig = ...
pub(pkg) type Dispatch = ...
pub(pkg) opaque type Handle = Rep
pub(pkg) alias Row = ...
pub(pkg) const LIMIT: Int = 8
pub(pkg) trait Walk[T] { ... }
pub(pkg) effect Trace { ... }
pub(pkg) ctl effect Abort { ... }
```

- `pub(pkg)` 只出现在 `pub` 能出现的位置（顶层 fn/type/opaque type/alias/const/trait/effect）。
  `impl`/`test`/`use` 仍不许带可见性，报错文案与 `pub` 相同。
- `pkg` 是**上下文关键字**：只在 `pub(` 之后特殊，`let pkg = 1`、`fn pkg()` 照常合法
  （与 `opaque`/`ctl`/`as` 同一先例）。
- `pub(` 后面若不是 `pkg)`，报 ``visibility can only be restricted to the package: write `pub(pkg)` ``，
  hint 说明 Dawn 没有 `pub(super)`/`pub(in ...)`。
- AST：`is_pub: Bool` 换成三值 `vis: Vis = VisPrivate | VisPkg | VisPub`（`front/ast.dawn`）。
  两个布尔（`is_pub` + `is_pkg`）会多出一个非法状态，不要。
- `pub(pkg) fn` 与 `pub fn` 一样必须写返回类型：它也是跨模块的契约，推断出来的签名会让
  同包的另一个模块随被调者的函数体漂移。
- `dawn fmt` 把 `pub (pkg)`、`pub( pkg )` 归一成 `pub(pkg)`。

## 四、语义

### 4.1 什么是「包」

**包 = 装载器眼中的一个源码单元**，也就是一个 `dawn.toml`：

| 模块来自 | 包身份 `PackageId` |
|---|---|
| 被检查的工程自身（目录模式、文件模式、LSP 单文档；有无 `dawn.toml` 都算一个） | `PkgRoot` |
| `[deps]` 源码包 | `PkgDep(name)`，`name` 是该包 manifest 里的真名（MVS 保证全程序一名一份，别名在装载时已规范化成真名） |
| 捆绑标准库 | `PkgStd`：整个 std 是一个包 |

所以 selfhost 是一个包（`selfhost/dawn.toml`），compiler-plan 是另一个；selfhost 用不到
compiler-plan 的 `pub(pkg)`。`scripts/incremental-semantics-contract/` 等以 `[deps]`
引用 selfhost 的工程是第三方，同样看不到 selfhost 的 `pub(pkg)`。

身份由 driver 在建 `Cx` 时决定：`analyze.module_step_with_recording` 已经持有
`LoadedModule.pkg`（`[deps]` 包）与 `std_identity` 的判定（std），把 `[deps]` 包名写进
`Cx.dep_package`；`cx.package_of(cx)` 由 `is_std_module` 与 `dep_package` 推出
`PackageId`，不另存一份会与 `is_std_module` 不一致的副本。

### 4.2 名字可见性：判定只在一处

`pub(pkg)` 声明像 `pub` 一样进入 `ModExports` 的各张名字表，外加两条：

- `ModExports.package`：导出模块的包身份；
- `ModExports.pkg_only`：本模块以 `pub(pkg)` 导出的名字（含 `pub(pkg) type` 的构造器、
  `pub(pkg) effect` 的操作、`pub(pkg) trait` 注入的方法）。

**唯一判定点**是 `check/passes.pass_imports` 取到被引入模块的 `ModExports` 之后、嫁接之前：
`exports_seen_by(exp, viewer)` 在 `exp.package != viewer` 时把 `pkg_only` 的名字从
`fns`/`types_by_name`/`aliases`/`alias_resolved`/`ctors`/`consts`/`traits_by_name`/`effects`
里删掉。之后所有路径——选择性引入、限定访问 `m.f`/`m.T`/`m.C`/`m.NAME`、限定效果 `!m.E`、
补全——读的都是这份已过滤的表，不再各自判断。body 检查读的 `cx.module_exports` 也是过滤后的，
所以**不新增 body 路径上的 Cx 读**，journal-reads 账本不动。

身份元数据（`adt_infos`/`trait_infos`/`effect_infos`/`impls`）**不过滤**：public-surface-design
§7.1 的原则不变，import、求解与后端仍需要完整身份表。

名字被滤掉之后，「找不到」诊断先问 `pkg_only`：命中就说

```text
`dispatch_segs` is package-private to package `web`
hint: only modules of package `web` may name it
```

而不是 `is private to module` 或 `has no exported ...`。四处缺名诊断（选择性引入、限定函数、
限定值/构造器/类型、限定效果）共用一个 `pkg_private_diagnostic(exp, name)`。
包名显示：`PkgDep(n)` 显示 `n`，`PkgStd` 显示 `std`；`PkgRoot` 不会出现在这条诊断里——
根工程不被任何别的包依赖，没有谁能从包外引用它。

### 4.3 公开面（SEM-07 audience 表扩一档）

`Audience` 加一个值 `APackage(pkg)`，`AModule` 带上声明模块的包：

```text
World | StdOnly | Package(pkg) | Module(owner, pkg)
```

| identity \ root | `World` | `StdOnly` | `Package(q)` | `Module(m, q)` |
|---|---:|---:|---:|---:|
| `World` | 是 | 是 | 是 | 是 |
| `StdOnly` | 否 | 是 | 仅当 `q` 是 std | 仅当 `m` 是 std 模块 |
| `Package(p)` | 否 | 仅当 `p` 是 std | 仅当 `p == q` | 仅当 `p == q` |
| `Module(o, p)` | 否 | 否 | 否 | 仅当 `m == o` |

- `pub(pkg)` 声明的 audience 是 `Package(本包)`；它作为 surface root 按 `Package(本包)` 验证：
  可以提同包的 `pub(pkg)` 身份，不能提模块私有身份。
- `pub` 声明的签名提到 `pub(pkg)` 身份即泄漏：
  ``public function `f` exposes package-private type `Dispatch` ``，hint
  ``make `Dispatch` public or remove it from this public surface``。
- observable impl：先按模块的公开 root 问；不可观察时再按 `Package(本包)` 问——
  一个 `pub(pkg) trait` 对公开类型的 impl 在包内可观察，它的 bound 与关联类型就要按包验证。
  `dawn doc` 读的 `observable_impls` 仍只按公开 root 算，所以这类 impl 不进文档。
- `TraitI` 原来存 `is_pub` 再由 `trait_audience` 推导 audience；推导需要包身份，而导入方
  没有声明方的包，于是 `TraitI` 改成与 `AdtI`/`EffectI`/`AliasE` 一样直接存 `audience`。
  这顺带让 public-surface-design §15.1 记的「四种身份记录里唯一靠推导的那个」不再特殊。
- `StdOnly` 与 `Package(std)` 不合并：`StdOnly` 是 `std/hamt`/`std/pvec` 的 `pub` 被模块边界
  截住后的 audience，今天 std 源码还不能写 `pub(pkg)`（std 与 selfhost 一起由种子编译）。
  下一个种子之后，这两个模块的 `pub` 可以改写成 `pub(pkg)`，`internal_std_modules` 与 `StdOnly`
  那时再议是否删除（§九）。

### 4.4 `dawn doc`

`doc.dawn` 七处 `is_pub` 判断改成 `vis == VisPub`：`pub(pkg)` 项不出现在 JSON 的任何数组里。
`observable_impls` 如上只按公开 root 算。

### 4.5 LSP

- `use m.{` 与 `m.` 的补全读 `exports_seen_by(exp, 本文档的包)`，与 checker 同一个函数，
  不另写规则。
- 尚未加载的模块走 `declared_items`（只解析源码），那里不知道候选模块属于哪个包，
  **只列 `pub`**：宁可少给一个同包名字，也不给一个下一个按键就被 checker 拒绝的名字。
  目录模式下同包模块都已加载，所以这一支只在单文件场景触发。
- `may_name_module` 的 `AModule(mod_path)` 带上文档自己的包。

### 4.6 Core 与后端

不需要知道。可见性是检查期概念：lowering 之后所有声明一律可见，JVM 类的 access flag、
C 符号的链接性都不随之变化。这也是为什么 Core golden 不变。

### 4.7 `export-surface` 门禁

`scripts/export-surface-contract/` 加：`pub fn` 泄漏 `pub(pkg)` 类型被拒、`pub(pkg) fn` 提同包
`pub(pkg)` 类型通过、`pub(pkg) fn` 提私有类型被拒、`dawn doc` 不列 `pub(pkg)` 项；变异体
`doc-publishes-pkg`（doc 把 `VisPkg` 当 `VisPub`）必须让 doc 断言变红，`pkg-always-visible`
（`exports_seen_by` 永不过滤）必须让跨包工程夹具变红。

### 4.8 spec

§10.4 改写成三档，钉一句契约（doc-check `SPEC_CONTRACTS`，中英各一）：
「`pub(pkg)` 声明对同一个包（一个 `dawn.toml` 单元）内的所有模块可见，对包外不可见」。

## 五、落点

| 文件 | 改动 |
|---|---|
| `front/ast.dawn` | `Vis` 三值；`FnDecl`/`TypeDeclR`/`EffectDeclR`/`DConst`/`DTrait`/`ConstView`/`TraitView` 的 `is_pub` → `vis` |
| `front/parser.dawn` | `classify_top_decl` 解析 `pub(pkg)`；各声明函数的参数改名 |
| `front/astdump.dawn` | `pub=true/false` 不变，`VisPkg` 打 `pub=pkg`（旧程序 dump 逐字不变） |
| `front/fmt.dawn` | 若 `pub(` 之间插空格则修 |
| `check/types.dawn` | `PackageId`、`APackage`、`AModule(owner, pkg)`、`TraitI.audience` |
| `check/cx.dawn` | `Cx.dep_package`、`package_of`、`ModExports.package`/`pkg_only`、`exports_seen_by`、`pkg_private_diagnostic` |
| `check/passes.dawn` | audience 取值、import 过滤、surface root 按档验证 |
| `check/checker.dawn` | `exports_of` 收 `pub(pkg)`、缺名诊断 |
| `driver/analyze.dawn` | 设 `dep_package` |
| `doc.dawn`、`lsp/lspc.dawn` | 只发 `VisPub`；补全过滤 |
| `docs/spec.md`、`docs/spec.en.md` | §10.4 |
| `scripts/checker-corpus/cases/` | 跨包正反例 |
| `scripts/export-surface-contract/` | 夹具与两个变异体 |

`selfhost/src` 自身在本刀**不使用** `pub(pkg)`：种子 v0.77.0 的 parser 不认它（种子约束）。
种子推进到 v0.78.0 之后，第一批用上它的是 `ir/interp` 只为兄弟测试模块开的四项
（`program_sigs`、`eval_module`、`CtRun`、`LowerCache`，见 unused-imports-design §4）。

## 六、错误文案

| 情形 | 消息 |
|---|---|
| 包外引入/限定访问 | `` `x` is package-private to package `web` `` |
| `pub` 签名提到 `pub(pkg)` 身份 | `` public function `f` exposes package-private type `T` `` |
| `pub(pkg)` 签名提到私有身份 | `` package-private function `f` exposes private type `S` `` |
| `pub(crate)` 等 | `` visibility can only be restricted to the package: write `pub(pkg)` `` |
| `pub(pkg) impl` / `test` / `use` | 与 `pub` 同文案 |

## 七、为什么这些没顺手做

- 没把 `std/hamt`/`std/pvec` 改成 `pub(pkg)`：std 由种子编译，种子不认新语法。
- 没改 ARCH-N05/N12/LIB-13 的代码：同上，selfhost 与 packages 也由种子编译（packages 另受
  semver 窗口约束，见 §九）。

## 八、不做的（理由）

- **`pub(super)`、`pub(in path)`**：Dawn 的模块路径只是文件路径，没有「父模块」这个语义对象；
  RFC 1422 支持任意路径的理由（把一个 crate 内联进另一个）在 Dawn 不存在。
- **re-export（`pub use`）**：与可见档正交，裁决 1 写明另议；它会引入「一个名字两条路径」。
- **字段级 `pub(pkg) f: T`**：本刀不做，**也不列为将来项**（协调方 09-24 裁定）。`opaque type`
  已是隐藏表示的唯一写法；字段级要在字段读取、记录字面量、记录模式、`{..x, f: v}`、
  derive Show 五处各加一条规则，是新特例。三条目标债也没有一条需要它。
- **不强制的标注（Gleam `@internal`）**：不强制就复现 LIB-13。
- **在 manifest 里列导出模块（JPMS/Cabal/Roc）**：模块粒度，解不了 ARCH-N05；把可见性从
  声明处挪进另一个文件。
- **在 importer 的每个使用点各自判断**：判定点只有 `exports_seen_by` 一个，否则就是 SEM-07
  §7.1 反对的「第二份规则」。

## 九、应用前置报告：下一个种子之后要收的三处

以下都**不在本刀**（种子约束）。v0.78.0 发布、种子推进之后，selfhost/src 与 packages 才能写
`pub(pkg)`。行号取自 `b2e19e06`。

### 9.1 ARCH-N05：`subst_subject` / `trait_method_sig` 双份

- 现状：`ir/lower.dawn:1359` `fn subst_subject`、`:1392` `fn trait_method_sig`（私有）；
  `jvm/emit.dawn:564` `fn trait_method_sig`、`:578` `fn subst_subject`、`:608` `fn subst_tvar`
  （`check/types.subst` 单变量情形的子集重写）。emit 侧调用点 `:2157`、`:2189`、`:2201`。
- 改法：lower 的两个函数改 `pub(pkg)`；`jvm/emit.dawn` 删自己的三个函数（约 75 行），
  `use ir/lower.{subst_subject, trait_method_sig}`；emit 已依赖 `ir/lower`（调研 `emit.dawn:74`），
  不新增边。panic 前缀从 `codegen:` 统一成 `lower:`。
- 预计：−75 行、+2 行；验收 = 五语料 class 输出逐字节不变（`selfhost-prev-diff.sh`）。
  注意 lower 用 `types.subst`、emit 用 `subst_tvar`，行为若有差（例如 `TyOpaque` 臂）会在
  prev-diff 里现形，那正是这份重复要消灭的东西。

### 9.2 ARCH-N12：`Cx` 直读

- 诚实的边界：`Cx` 的直读者（`check/checker` 312 次、`check/passes` 100、`lsp/lspq` 43、
  `lsp/lspc` 33、`doc` 23、`main` 16、`c/cdriver` 11、`driver/analyze` 10、`ir/interp` 8）
  **全在 selfhost 这一个包里**，`pub(pkg)` 不减少这 9 个模块的耦合。它能做的是把 `Cx` 从
  selfhost 的**公开面**拿掉。
- selfhost 的公开面今天真有包外消费者：`scripts/incremental-semantics-contract`（`use compiler/check/cx.{Cx, ModExports, cx_new}`、`check/checker.{check_module, exports_of}` 等）、
  `scripts/builtin-decl-contract/dump`（`check/cx.{Cx, cx_new}`、`check/passes.{pass_fn_signatures, seed_prelude}`）、
  `scripts/slab-bench/workloads/*`、`scripts/project-plan-contract/captured-probe`。
- 改法：`check/cx.dawn` 的 `pub type Cx`、`pub type Frame`、`pub type LambdaCx` 改 `pub(pkg)`；
  两个包外消费者要么改走 `driver/analyze` 的公开入口，要么这两个契约脚本随之调整。
  LSP 侧 13 个字段（`adts` `traits` `fns` `module_aliases` `imported_names` `ctors_by_name`
  `consts` `adts_by_name` `traits_by_name` `java_classes` `is_std_module` `aliases`，
  `lsp/lspq.dawn:46`、`lsp/lspc.dawn:27`）的查询面仍是调研里的选项 2，与 `pub(pkg)` 无关，另立。
- 预计：3 行可见性改动 + 两个契约脚本各数行；不动任何读点。

### 9.3 LIB-13 残差：web 包 seam

- 符号：`packages/web/src/router.dawn` 的 `dispatch_segs`、`validate_routes`、`route_meta`
  与类型 `Dispatch`（`server.dawn` 跨模块消费）。
- 改法：四处 `pub` → `pub(pkg)`。收窄公开面是 semver major：`packages/web` 要开 `web5`
  （包名随 v2 换名规则改），dawnop-site 要提 bump；这与 LIB-16（`Response` 可公开构造非法
  状态）应搭同一个 major 窗口，一次迁移而不是两次。
- 预计：4 行 + manifest 版本/包名 + 下游一提交。
- **回填（2026-09-25，web5）：已落地。** 四处 `pub` → `pub(pkg)` 与 manifest 改名
  `web5 / 5.0.0` 同一提交（中间态若公开面已变而名未变，就是一个违反 semver 的 `web4`）。
  实测与预计一致：router.dawn 4 行，包内调用点（`server.dawn` 的 `dispatch_segs`/
  `validate_routes`/`route_meta`/`Dispatch`）与 router.dawn 自己的 test 零改动，
  `playground` 零改动。同一个 major 的其余改动与理由见 [web5-design.md](web5-design.md)。
  同一个 major 里 LIB-16 用上了 §4.3 表没有现成夹具的一格：`pub opaque type Response` 指向
  `pub(pkg) type ResponseRep`。实测放行（公开面只查 identity 不查 representation），包外
  引入表示报 `` `ResponseRep` is package-private to package `web5` ``，读字段报
  `` `.` field access needs a record value, got Response ``。

## 十、实现回填

落地于分支 `feat/package-visibility`（基线 `b2e19e06`），提交按顺序：设计稿、语言落地、spec、
checker-corpus、export-surface 契约，外加一个修 export-reads 锚点的小提交。

与上文不一致处，逐条：

- **缺名诊断的形状**。§4.2 写的是一个 `pkg_private_diagnostic` 返回 `Option`；实现改成
  `pkg_private`（判定）+ `pkg_private_export`（给要记账的读路径的记录）+ `pkg_private_err`
  （直接报错）。原因是 `scripts/checker-corpus/coverage.py` 只跨同文件 helper 解析措辞、
  不跟 match 里 `Some(d)` 的绑定，`Option` 形状让三个 `cerr` 点失去可证明的措辞、棘轮红。
  「no exported type/constructor」两处原有记录保留原字面，覆盖率不变（288/294）。
- **期望外的锚点**。`scripts/syntax-small-contract/run.sh` 的一个变异体锚在
  `fn type_decl(p: P, st: St, is_pub: Bool)` 上，`scripts/export-surface-contract/mutate.py` 的
  `lsp-ignores-audience` 锚在 `AModule(qc.entry.mod_path)` 上，都随改名更新；
  `incremental-semantics-contract/export-reads.py` 锚在记账值的名字 `Some(diagnostic)` 上，
  实现保留该名字。
- **fmt**：`pub (pkg)` 原被打成带空格的形式，`front/fmt.dawn` 加一条「`pub` 后的 `(` 贴紧」。
- **LSP**：`exports_seen_by` 在 `lsp/server.doc_qcx` 构造 `exports_env` 时一次性施加，
  lspc/lspq 所有读 `exports_env` 的地方因此都只见本包可见的名字。这一处没有专门的 LSP 契约，
  它与 checker 共用同一个函数，函数本身由 `pkg-always-visible` 变异体钉住。

Core golden 不变（可见性是检查期概念）；astdump 对不写 `pub(pkg)` 的程序逐字不变。

### 10.1 种子推进到 v0.78.0 之后的收尾（2026-09-25，分支 `fix/pkgvis-followups`）

§九 的三处，外加一处门禁基础设施，逐条：

- **std/hamt、std/pvec 改 `pub(pkg)`**（`fae6a7e8`）。两个模块 30 处 `pub` 全改，
  `selfhost/src/embed/stdsrc.dawn` 随 `gen-stdsrc.py` 重生。`StdOnly` 与
  `internal_std_modules` **没有删**：删除的前提是它们只为「std 写不出 `pub(pkg)`」而存在，
  实查不成立。名单另外还承担三条 `pub(pkg)` 替代不了的规则：
  `passes.pass_imports` 在 std 外拒绝 `use std/hamt`/`use std/pvec` 并给出该用哪个容器的提示
  （spec §10.6）；`doc.dawn` 据它把两个模块整体排除出参考文档（两处实现、三处测试断言）；
  `scripts/lsp-use-completion.py` 读它决定 `use` 补全不提供这两个模块。`StdOnly` 本身还是
  内建类型 `Array`（`BtStdOnly`）的 audience，`export-surface` 契约钉着它的诊断措辞
  `standard-library-internal type` 和两个变异体。按裁决只做前半，删除另议。
  连带一处门禁修正：真 std 里不再有 `StdOnly` 根，`stdonly-collapses-to-world` 变异体
  在真 std 上存活（集群 export-surface 红，实测）。契约改为往 std 副本的 `pvec.dawn`
  追加一个只提 `Array` 的 `pub fn`，未变异时必须通过，变异体瞄准这份副本。
- **ARCH-N05**（`fa5ebea0`）。`ir/lower` 的 `subst_subject`、`trait_method_sig` 改
  `pub(pkg)`；`jvm/emit` 删掉自己的 `trait_method_sig`、`subst_subject`、`subst_tvar`
  （77 行），改 `use ir/lower.{LMod, subst_subject, trait_method_sig}`，顺带去掉因此不再用的
  四个 `check/types` 导入；panic 前缀统一为 `lower:`。两份替换并非同一个遍历：
  `types.subst` 在函数类型上还会对效果行跑 `subst_eff`（空映射下只经 `eff_union` 重新规范化），
  `subst_tvar` 原样保留效果。验收：集群 `prev-diff`（五语料 class 逐字节）、`prev-diff-native`、
  `native-diff-1/2`、`classfile-never-mutants` 全绿，没有差异可报。
- **ARCH-N12 未做**。把 `Cx`/`Frame`/`LambdaCx` 改 `pub(pkg)` 后 `dawn check selfhost` 报
  354 条泄漏诊断（第一层，14 个文件）：326 条 `public function ... exposes package-private type Cx`、
  22 条同类 `public type`，外加 `LambdaCx` 3 条、`Frame` 3 条。§九 9.2 的「3 行可见性改动」
  漏算了 §4.3 自己定的规则：`pub` 签名提到 `pub(pkg)` 身份即泄漏。连锁会一路传到
  `driver/analyze.CheckedMod` 与 `driver/stdlib.StdCtx`，也就是契约脚本本该改走的
  「`driver/analyze` 公开入口」本身就携带 `Cx`，给不了不含 `Cx` 的出口。
  包外直接 `use .../check/cx` 的有 13 个文件（`incremental-semantics-contract` 12 个、
  `builtin-decl-contract/dump` 1 个），其中多处读 `slots_of`、`mint_cursor`、`enter_decl_owner`
  等内部件。按裁决「脚本随之红就不改 `Cx`」，`Cx` 保持 `pub`。要收这一条，先要定
  selfhost 对包外暴露的检查器 API 是什么（契约探针要的是内部件，不是公开入口），
  那是另一个设计问题，不是可见性改写。
- **外部门禁输入包的种子**（`08e6c99c`）。种子推进后集群输入包仍只有 v0.77.0：
  `inputs.py verify` 只拿每一行对 MANIFEST 和锁文件，旧种子的包照样全绿，后端于是不重推，
  每个 toolchain 步骤转去 GitHub 拉 v0.78.0，而集群节点连不上，
  `test`、`checker-corpus`、`contracts-1`、`prev-diff` 开跑 40 s 内全红。
  `verify` 加 `--seed-tag`，MANIFEST 缺该 tag 的种子或 std 即红；crun 后端从被测提交的
  `scripts/seed-release.txt` 取 tag 传给远端与本地两次 verify；prefix 内的本地后端缺种子时
  直接报缺哪个，不再去碰网络。负控：对未重建的本地包 `verify --seed-tag v0.78.0` 报两项 FAIL。
