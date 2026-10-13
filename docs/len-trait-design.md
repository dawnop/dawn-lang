# prelude `Len` trait：std 范围统一的 `len`（K1，设计稿）

> 改名说明（2026-10-12）：文中的 `Tensor[D]`（`std/gpu` 的宿主缓冲类型）今天叫 `DeviceBuffer[D]`；本文按当时的名字写成，不逐处改动。

> 状态：**proposed**。K2 已实现（本地分支 `std/len-k2`，未推送）；§7 记实施与实测。2026-10-10 写成。基线 `origin/main` = a8c53f6e。
> 动码前的**调研与方案**，不是设计定稿。
> 调研报告与裁决（维护者工作区）：`research-std-len-20261009.md`、`ruling-std-len-20261009.md`，含全部 `file:line` 与外部出处，本文只留结论。裁决：采方案 (b)，prelude 加 `Len` trait。
> K0 原型：本地分支 `proto/len-k0`（提交 05d2dc15，从未推送）。本文引它 2026-10-09 的实测，出处写作「K0 原型 05d2dc15，2026-10-09」（§5）；K0 没有测到的项写「未量」并写明由 K2 去量。

## 1. 问题

prelude 的 `len` 今天是只认 `List` 的 builtin（`selfhost/src/check/types.dawn` 的 `builtins()` 里 `bsig("len", [TyList(t)], ...)`）。别的类型各自在模块里再起一个：`str.len`、`bytes.len`、`map.len`、`set.len`，以及 `Buf` 的 `bytes.size`。三个后果：

1. **遮蔽。** 一个模块一旦自己声明了 `len`（比如 `std/gpu` 想给 `Tensor` 写 `len`），本模块里所有裸 `len(xs)` 与点写法 `xs.len()` 都被遮蔽成它（spec §10.3、§10.6）。没有限定形可以绕开（`prelude-namespace-design.md` D5 明确不给），`std/str` 里的 `slice_cps` / `pad_fill` / `rev_cps` 三个绕行函数就是这个病的化石。
2. **同模块撞名。** `Bytes` 占了 `bytes.len`，`Buf` 只好叫 `bytes.size`，这是 CONTRIBUTING §7 里那条命名例外的来历。`std/mem` 设计里的 `f64_len` 同理。
3. **一个概念多个名字。** 与 §7 的「一个概念一个名字」相违。

trait 方法的名字不是模块顶层声明，`impl` 体内的 `fn len` 不遮蔽 prelude，遮蔽规则也不影响 trait 查找（spec §10.6 末段）。所以 `Len` 同时消掉三件事，且**不新增语法、不改名字解析**。

## 2. 方案

`prelude_traits()` 加一个注入的单参数 trait：

```dawn
trait Len[C] { fn len(x: C) -> Int }
```

- `injects: true`，所以 `len(x)` 与 `x.len()` 都走现有 trait 方法路径（UFCS 第 5 步已包含 trait 方法）。
- 各类型写 impl：`impl[T] Len[List[T]]`（`std/list`）、`impl Len[String]`、`impl Len[Bytes]`、`impl[K, V] Len[Map[K, V]]`、`impl[T] Len[Set[T]]`，以及之后的 `Buf`、`Tensor`、`I64Buf`、`F64Buf`。`List` 的 impl 与 `Iter[List[T]]`（`std/list.dawn`）同一形状，v1 不涉及条件 impl。
- `len` 退出公开 builtin 表，换成内部名 `list_len`（仍是 intrinsic，只是用户拼不出来）。
- 单参数、不带关联类型、不带默认方法（`is_empty` 以后可以作默认方法，现在没有调用点要求）。

## 3. K0 观察到的四件事，各自的对策

K0 把 `Len` 与五个 impl 原样加进去并编译 selfhost，发现的问题全部落在 K2。每一条这里写对策与验收，数字由 K2 量。

### 3.1 List 点位必须发同样的字节

K0 现象：对 `len(xs)`（`xs: List[T]`）的调用点，发射的是 `invokestatic std/list.dawn$impl$Len$List$len`，而不是今天的 `std/pvec.count`。也就是 `Len[List]` 被当成普通 impl 方法 devirtualise 成了一次包装调用。

后果：JVM 上多一层调用；native 上 TU 切分（`docs/c-tu-split-design.md`）会挡住跨 TU 内联；emit 语料、Core golden 全部移动。而 `len(` 在仓内有约 4200 个调用点，绝大多数是 `List`。

对策：在 `ir/lower.dawn` 的 `lower_trait_call` 里，witness 是 `WConcrete`（及 `WApply`）且 `tid` 是 `Len`、主语是 `TyList` 时，**直接发 `CIntrinsic("len", ...)`**，不经 `CImpl`。这与该函数头部已有的「prelude witness 塌缩成原语」是同一个设计线（`primitive_witness` / `prim_relation`：塌缩不是优化，是定义），所以放在同一个门里，而不是在 emit 或 C 后端各补一份。字典槽（泛型 `[C: Len]` 经 `WForward` 走字典）仍然需要一个真方法体，那个体是 `list_len(xs)`，经下一节。

验收（K2）：对已有 `List` `len` 调用点，`selfhost-prev-diff` 的 emit 语料 **0 字节差异**，Core golden 对 `List` 点位 0 变化，并给出一个 `javap` 级的对照（同一个小程序在 main 与候选上的 `len` 调用指令逐字节相同）。**任何 emit label 只因 impl 包装而移动，是 bug，要修，不是要声明。**

### 3.2 impl 体必须调内部名，不能调自己

K0 现象：`impl[T] Len[List[T]] { fn len(xs) = len(xs) }` 里的 `len(xs)` 经 UFCS 解析回这个 impl 自己，无限递归（K0 为此用了 `list_len`；复现样例见维护者工作区）。

对策：所有 `Len` impl 体只调内部名（`list_len`、`bytes_len`、`map_size`、`set_size`）。`list_len` 是 builtin 表里的一个条目，lowering 把它改回 `len` intrinsic（K0 在 `lower_expr` 的 `XCallBuiltin` 臂里做了，K2 可沿用，但要与 3.1 的 `lower_trait_call` 改写共用同一个 `list_len` 到 intrinsic 的映射，不要两处各写一份）。

另外：#659（已合入 main）现在拒绝无条件自递归，`checker.dawn` 里已有三条测试固定 `impl Len[...]` 体里 `len(xs)` 与 `b.len()` 的诊断。所以一个写成自调用的 impl **编译不过**，这是第二道网。K2 不得靠放宽那条检查通过。`std/list.dawn` 里 `Iter[List[T]]` impl 体当前用的裸 `len(xs)` 同样改成 `list_len(xs)`（裁决已定；K0 的 `Iter` impl 体同样会解析到 `Len` 方法，用内部名不依赖 3.1 的改写）。

### 3.3 comptime 解释器的燃料

`ir/interp.dawn` 把 `len` 当内建名求值（`name == "len"` 一臂），`xs ++ xs` 另按自己的规则记燃料。若 `len(xs ++ xs)` 经 `Len[List]` 的 impl 包装，就多出一次用户函数调用与一次体求值，**可能改变 `--comptime-fuel` 下恰好用尽的边界**，也占用 `depth`（调用深度）。具体差多少未量，见 §5。

对策：解释器看到的是 Core，3.1 的改写发生在 lowering，所以 `List` 点位在 Core 里本来就是 `len` intrinsic，燃料记账与今天相同；`list_len` 同样映射到 `len` 的解释器臂。解释器里的内建名清单（`interp.dawn` 的 builtin 名表）、`lower.dawn` 的同名清单、`checker.dawn` 的同名清单都要加 `list_len`，并且在三处对账。

验收（K2）：加一条 comptime 测试：`len(xs ++ xs)` 在 `ct_fuel(n)` 下，用尽的最小 n 在 main 与候选上相同（二分取得，两侧各记一个数）。**这个数现在未量。**

### 3.4 K0 时 selfhost 测试的 18 处失败

K0 重新生成 stdsrc 之后，`dawn test selfhost` 是 1050 项里 18 项失败（重新生成之前是 61 项）。分类（K0 原型 05d2dc15，2026-10-09）：未登记的 `list_len` 别名 4 项（intrinsic 属性断言、builtin 数 114 的断言、lower / interp 的分组表、`Len` 缺文档文本），无 std 的检查器夹具 6 项，`prelude_method_names` 计数 8 的 1 项，interp_test 里 `len(xs ++ xs)` 的 comptime 燃料断言 5 项，另 2 项当时未逐项记录。K2 重现时逐条对账：

- 不带 std 的夹具（6 项）：一些检查器测试直接构造最小环境，没有 `std/list`，于是 `len(xs)` 找不到 `Len[List]` 的 impl。K2 的方式待定：候选是让这些夹具的预置 impl 环境带上一条 `Len[List]` 记录，而不是让测试各自加 std；实施时看哪种改动面小。
- `prelude_method_names` 的计数断言（1 项；`checker.dawn` 里 `len(prelude_method_names()) == 8`）：prelude 多一个注入方法，数加一，这是**预期的**数字变化，不是漏洞。
- builtin 计数与清单（4 项连同下一条文档文本）：`len` 退出公开清单、`list_len` 进内部清单；`Intr` 的 `internal` 集合要登记。**Bulk 线（`std/bytes` 的批量原语）同样会动 builtin 计数；谁后落地谁 rebase，这是对账不是冲突。**
- 文档文本：spec §3.5 的预置 trait 表、§10.6 的 builtin 清单（由 `doc-check: builtin-inventory` 对账）、标准库参考的「预置 trait」一节。

- comptime 燃料（5 项）：interp_test 里 `len(xs ++ xs)` 的燃料断言，见 3.3，这 5 项在 3.3 的二分测试之外也要逐条对账，不靠放宽期望通过。

K2 的目标：这 18 条在同一次提交里全绿，且没有任何一条靠删断言或放宽期望通过。

## 4. 落点（K2 才动）

| 文件 | 变动 |
|---|---|
| `selfhost/src/check/types.dawn` | `LEN_ID`、`prelude_traits()` 一项、`prelude_trait_ids()`、`builtins()` 去掉公开 `len` 加内部 `list_len`、`intrinsics()` 的 `internal` 登记 |
| `selfhost/src/ir/lower.dawn` | `lower_trait_call` 对 `Len[List]` 直接发 intrinsic；`list_len` 到 `len` 的映射；builtin 名清单 |
| `selfhost/src/ir/interp.dawn` | 内建名清单加 `list_len`，求值臂与 `len` 共用 |
| `selfhost/src/check/checker.dawn` | 名清单、夹具环境、测试计数 |
| `std/list.dawn` | `impl[T] Len[List[T]]`；`Iter` impl 体改用 `list_len` |
| `docs/spec.md`、`docs/spec.en.md`、标准库参考 | 预置 trait 表、builtin 清单；先中后英（译本摘要由 `doc-check` 对账） |

`str/bytes/map/set` 的 impl 与 341 处限定调用、14 处 `bytes.size` 的迁移是 K3；`Tensor` 是 K4；`std/mem` 是 K5。本设计稿对应 K1，不含任何编译器或 std 改动。每一刀独立提交；改变输出的刀按 `scripts/emit-labels.txt` 逐字写 `Emit-Change(<label>)`。

## 5. 数字的出处（性能断言只引这里）

| 断言 | 状态 | 出处 / 由谁量 |
|---|---|---|
| 未改写的 `Len[List]` 调用发 `invokestatic std/list.dawn$impl$Len$List$len` 而不是 `std/pvec.count`（循环与泛型 `len` 探针里都如此，JVM 后端；native 后端未量） | **已测** | K0 原型 05d2dc15，2026-10-09 |
| 改写后 List 点位 emit 与 main 逐字节相同 | **已测**：prev-diff 范围模式 10 个 emit 标签全 0 字节（含 `emit selfhost`，约 2500 处 `len`）；探针的整个 jar 目录逐文件 `diff -r` 相同，`javap -c -p` 相同；native 探针的 C（单文件与 `--split` 各单元）`cmp` 相同 | K2，2026-10-10 |
| 推断失败的调用点：`dawn check` selfhost 全图 0 错误（约 2500 处裸 `len`）；site、compiler-plan、playground、packages 的 json / web / fspath / sha2 / inflate 均通过；tea 不在 `packages/` 下，未检查。未标注形参的 lambda `let f = xs => len(xs)` 报 "cannot infer the type of xs"，种子 v0.85.0 同样报，不是回退 | **已测**（裁决门槛约 20 处，实测 0） | K0 原型 05d2dc15，2026-10-09 |
| 遮蔽：模块里有 `impl Len[Tensor]` 时 `len(xs) + len(t)` 两者都解析，输出 7；模块级 `pub fn len(t: Tensor)` 仍遮蔽 List 的 `len`（现状） | **已测** | K0 原型 05d2dc15，2026-10-09 |
| 泛型：`fn gen[T](xs: List[T]) = len(xs)` 与 `fn gen_len[C: Len](c: C)` 对 List 与用户类型 `Box` 都正确；fold 累加与 `xss.map(x => len(x))` 正常 | **已测** | K0 原型 05d2dc15，2026-10-09 |
| 自编译墙钟：基线 9.19 / 9.92 / 9.09 s，候选 9.92 / 9.03 / 9.32 s，噪声之内 | **已测**（3 次） | K0 原型 05d2dc15，2026-10-09 |
| 自递归 impl 体 `fn len(xs) = len(xs)`：在 `-Xss512m` 下 StackOverflow，堆外约 19 GB；当时 `check` 放行，#659 现已拒绝 | **已测**（事故） | K0 原型 05d2dc15，2026-10-09 |
| selfhost 测试 18 / 1050 失败（见 3.4） | **已测** | K0 原型 05d2dc15，2026-10-09 |
| comptime 燃料边界不变（二分） | **已测**：`len(xs ++ xs)`，xs 16 个元素：main 与候选都是 39 用尽、40 够；xs 1024 个元素：都是 2055 用尽、2056 够 | K2，2026-10-10，`--comptime-fuel` 二分，两侧各一份 jar |
| 自编译墙钟（K2 后） | **已测**（3 次，`check selfhost` 与 `build selfhost`）：check 基线 4.66 / 4.57 / 4.65 s，候选 4.70 / 4.74 / 4.63 s；build 基线 8.19 / 7.77 / 7.72 s，候选 7.75 / 7.83 / 7.91 s，噪声之内 | K2，2026-10-10 |
| 约 4200 处裸 `len(`、377 处点写法 `.len(`、341 处限定 `str/bytes/map/set.len(`、14 处 `bytes.size(`、7 处 Tensor `size` | 调研报告 §2 计数 | 调研报告，`std packages selfhost/src site playground examples` 的 grep |

## 6. 不做的（理由）

- **不做 (a-full)**（prelude 名不可遮蔽，或加 `prelude.x` 限定入口）：与 `prelude-namespace-design.md` D5「不给限定形」相反，并让「prelude 追加是兼容的」失效；`impl` 方法名本来就不遮蔽，用不着。
- **不做 (c)**（检查器内建多态 `len`）：Tensor、I64Buf 住在 std，检查器要么依赖 std 类型（层次倒置，违背 `Rt` / `Intr` 只说模块的设计线），要么每加一个类型改一次编译器；用户类型进不去；与缩小 builtin 的方向相反。
- **不做 (d)**（保留 `size`、`f64_len`）：违反 CONTRIBUTING §7「一个概念一个名字」，且 GPU 命名裁决已裁 Tensor 改 `len`。
- **只有 K0 失败才做的 (a-min)**（`std/list` 加 `pub fn len`、gpu 内 74 处改 `list.len`）：K0 实测推断失败 0 处、墙钟在噪声内；字节问题有 3.1 的对策，所以不做。(b) 落地时它也会整体作废。
- **不引入 Koka 式重载**：改名字解析与 §10.3，影响全部 UFCS 与具名实参规则，只为一个 `len`；trait 已经是同样的能力。
- **不为 `at`、`get`、`is_empty` 一并 trait 化**：`Index` 已覆盖 `[]`；`is_empty` 以后可以做 `Len` 的默认方法，现在没有调用点要求；`buf_at` 与长度无关，例外保留。
- **不给 `Len` 加关联类型或第二个参数**：长度只是 `Int`。
- **不把 `Hamt.count`、`pvec.count` 并进**：`pub(pkg)` 的表示层内部名，不出 std。
- **不让 `Len[List]` 的 impl 方法体承担热路径**：热路径是 3.1 的 intrinsic 改写；impl 体只服务字典槽（泛型 `[C: Len]`）。
- **不做兼容层**：`str.len` 等限定拼写在 K3 直接删并迁调用方（仓内外部消费者为 0）。
- **不在 K2 前改 `CONTRIBUTING` §7**：它描述的是今天的 std；两条例外在 K3 / K5 落地时才删，先英后中。

## 7. K2 实施记录（2026-10-10）

提交（本地，未推送）：`fix` 先行一刀，再是编译器与 std，再是 spec。

1. **自递归检查对真实模块是瞎的。** #659 的 `selfrec.is_self` 拿调用的 owner 与 impl 所在模块比较；trait 方法调用的 owner 是 *声明 trait 的模块*（预置 trait 为无），只有 `cx_new(None, None)` 的夹具里两者才相等，所以 `impl Len[Box] { fn len(b) = len(b) }` 在任何有模块名的文件里都通过 `dawn check`（本节写下前用探针复现）。改成 trait 方法只按 trait 与主语认「自己」，owner 仍只比较普通函数；这是 K2 之前就要补的第二道网，独立一刀。
2. **3.1 的塌缩**：`lower_trait_call` 在 witness 是 `List` 时发 `len` intrinsic（`is_len_primitive`，不剥 opaque：opaque 包 List 且自写 `Len` 的类型有自己的长度）；`list_len` 内建与这条走同一个 `list_len_call`。`len` 退出 builtins 表，进 `internal_intrinsics`（lowering 的内部原语）；`list_len` 进 `lowered_intrinsics`。
3. **额外发现一**：`std/list` 的 impl 只对排在它之后的 std 模块可见，`narrow` 等模块在 `list` 之前就用到 `len(List)`，`dawn check std` 报 no impl of `Len` for `List[Int]`。解法是把 `list` 挪到 `modules.txt` 里 `str` 之后（它只依赖 `str`）；没有 std 模块因此需要改。
4. **额外发现二**：条件 impl 扫描让每个程序多出一个 `dawn/tr/Len.class` 接口，十个 emit 标签全动，这正是 3.1 说的「只因 impl 包装而移动」。`Len` 在 List 上无界、且被塌缩，它的字典只会为带 `[C: Len]` 界的函数而造，而界扫描本来就会要接口；`main.dawn` 对这种 impl 不再无条件要接口。带 `[C: Len]` 的探针（List 与用户类型 `Box` 都过字典）输出 28，与预期相同。
5. **LSP 行号**：impl 放在 `std/list` 文件头部会让文件里所有定义整体下移（hover、definition 都动）。放到文件末尾后，lsp 差分只剩补全列表：少了 `fn len[T](xs: List[T]) -> Int`，多了 `trait Len[T]` 与 `fn len[T: Len](x: T) -> Int`。已按 `Emit-Change(lsp)` 声明；`doc --builtins` 同样声明。
6. **3.4 的失败**：重现为 19 项（多出 `ir/lower` 的「内建当值」一项，对 `list_len` 的期望改成 lower 到 `len` 原语）。无 std 夹具用 `with_list_len(cx)` 把 `Len[List]` 记录放进 impl 表（impl 是预置 trait 在 List 上的，孤儿规则只许写在 `std/list`，所以夹具不能写源码；记录带 `provided: ["len"]`，不会被当成原语关系）。`prelude_method_names` 计数改 9；燃料断言一条没放宽，另加 `a List's len spends the fuel the builtin did` 钉住 39 / 40。
7. **镜像**：`selfhost/builtins.dawn`（`len` 改为 std 内部的 `list_len`）、builtin-decl-contract 的一个变异体不再用公开 `len`（改用 `get`，名字 `p9-drop-get-s-flag`）、doc-check 的清单自检改用 `range`、checker-corpus 的 `self_recursion` 用例去掉本地 `trait Len` 与孤儿 List impl 并重录三份 golden（`calls`/`pipe` 的签名行变成 `fn len[T: Len](x: T) -> Int`）。
8. **与 Bulk K4 的对账**：main 已到 b262fbd7（builtin 计数 125），`lower` 的分组计数断言的唯一冲突按 125 + `lowered` 23 / `internal` 23 合并。

仍未做（K3 起）：见下文第 8 节，K3a / K3b 已把它们做完。

## 8. K3a / K3b 实施记录（2026-10-13）

K3 分两刀，因为种子（上一个 release）自带的 std 没有 String / Bytes / Buf / Map / Set 的 `Len` impl，工具链用种子编译，所以第一刀只能加 impl、迁种子编不到的调用方，旧函数原样留着。

- **K3a**（`9328e225`）：五个 impl，std 测试与脚本里的 165 处限定调用迁移；`Emit-Change(lsp)`。
- **K3b**（种子推进到 v0.88.0 之后；提交 `6d92e055`、`58cfd3b2`、`71d0b8fa`）：
  1. **迁移**：80 个 `.dawn` 文件里 329 处限定调用（`str.len` / `bytes.len` / `bytes.size` / `map.len` / `set.len`）改成 `len(x)`。按目录：`selfhost/src` 139（35 个文件）、`packages` 72（18）、`playground` 33（7）、`site` 26（8）、`compiler-plan` 23（5）、`examples` 16（2）、`std` 16（3）、两份 ownership 合约 4（`rc-view-contract` 3、`rc-mode-contract` 1）。只被这些调用用到的整模块 `use std/str`、`use std/bytes` 随之因 unused import 报错而删（4 处，另有 `site/play-ui/samples/chars.dawn` 与一个文档测试里的内嵌程序）。内嵌 Dawn 程序与按源码文本锚定的脚本一并改：`fuzz3/gen.py`、四个 `mutate.py`、`mutation-anchor-preflight-test.py`、`native-cli-diff.sh`、`selfhost-lsp-diff.sh`、`playground/test/contract.sh`。四个 LSP 脚本拿 `str.len` 当「限定的 std 调用」样例，改用 `str.trim`（hover 期望 `fn trim(s: String) -> String`）。
  2. **删除**：`str.len`、`bytes.len`、`bytes.size`、`map.len`、`set.len` 五个模块级函数；`Buf` 的 `size` 体并进 impl，`bytes.dawn` 里 8 处 `size(` 测试调用改 `len(`。`bytes.buf_at` 的文档注释改成「唯一的具名例外」。
  3. **`std/str` 绕行函数**：`pad_fill` 与 `rev_cps` **仍在**。它们不是因为 `len` 被 `str.len` 遮蔽才存在，而是因为 `std/str` 在 `modules.txt` 里排在 `std/list` 之前：模块里既没有 `Len[List]`，也没有 `map`。试过改成 `map(range(0, n), …)`，先报 `undefined function: map`，改掉后报 `no impl of Len for List[Char]`。保留递归版，在函数上方写明原因。
  4. **文档**：CONTRIBUTING §7 先英后中，两条例外只剩 `bytes.buf_at`，并说明 `len` 是预置 trait；spec（中、英）、教程（英、中）里的 `str.len` / `bytes.len` / `bytes.size` 同步。
  5. **声明的输出变化**：`emit selfhost`、`emit site`、`emit playground`、`emit packages/web`、`emit packages/json`（调用点从模块函数改走 impl），`doc --builtins`（std 文档面少了 `str.len`），`lsp`（`std/str` 的定义行上移 5 行，补全不再列模块级 `len`）。其余 prev-diff 标签（`examples/*` 五项）逐字节相同。
  6. **门禁样例跟着动**（集群全套第一轮的四个红，原因都在这一刀里）：`lsp-semantic-tokens` 的期望 token 序列（`len(str.trim(n))` 里 `len` 是 trait 调用，没有 token，只剩 `str`、`trim`）；`lsp-rename` 的「std 函数」样例换成 `str.index_of`（再加一处裸 `len` 调用会改变「builtin 遮蔽」那条的报错）；`builtin-decl-contract` 的 P9 变异体原先拿 `std/bytes.len` 当「与 builtin 同名的 std 函数」，该函数没了，改拿 `std/map.get`（变异体名 `p9-flag-std-map-get`）；`rc-mode-contract` 的站点 `std/str:len:1:0` 随之消失，且 impl 方法在 Core 里名为 `len`、调用点却按 `impl$17$String$len` 查表，两侧对不上，所以站点改到 `std/str:count:3:0`（`len` 的 impl 把参数交给它，借用翻转同样被拒）。`docs` 门的 `site/build.sh` 在集群上停在 play-ui 的 npm 步骤，与本刀无关（本机 `site/build.sh` 通过）。
  7. **tile 台账**：`packages/tileir` 与 `std/gpu` 动了，本机 sm_86 台账按规矩重录，记录在 `71d0b8fa`。
  8. **本机门禁**：`dawn test selfhost` 1080 项全绿、`dawn test compiler-plan` 95 项全绿、`dawn test --stdlib` 241 项全绿；`fmt --check`、`doc-check.py`、`mutation-anchor-preflight`（656 处锚点）、`anchor-guard`、checker-corpus（202 例）、`selfhost-fmt-diff` 全过；prev-diff 约 69 s、run-diff 约 118 s。
