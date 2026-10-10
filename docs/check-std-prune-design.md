# check / emitc / build / run / test 只加载程序到得了的 std 模块

> 状态：**proposed**。重开 [std-pruning-design.md](std-pruning-design.md) §6 否决过的「check 端也裁」。
> 触发条件是该节自己写的重开门槛：check 时间本身成了瓶颈（[check-cold-start-design.md](check-cold-start-design.md)
> 两刀之后，空程序 `dawnc check` 仍约 0.41 s，其中 std 加载约 0.35 s）。
> 调研与裁决是内部文档（`~/workspace/agent-handoff/research-check-std-prune-reopen-20261011.md`、
> `ruling-check-std-prune-reopen-20261011.md`，未入库），下面只引其中的测量。

## 1. 病

`load_chosen_std` 对 `modules.txt` 的 27 个模块逐个 lex、parse、check、跑 comptime，不论程序用不用。
std 共 645,979 字节，其中 `gpu`、`narrow`、`int/*`、`memfs`、`mem`、`float`、`dtype`、`reactor` 这些
可选模块占 54%。典型程序（Playground 样例 11 个、`examples/` 42 个）里，39 个 example 与 10 至 12 个
样例的可达模块数恰好是基座那 10 个（调研 `reach.py` 的统计），所以几乎每一次 `check` 都在为没人用的
模块付钱。

## 2. 原先否决的四条，逐条复核

| 否决理由（2026-09-06） | 今天 | 依据 |
|---|---|---|
| ADT id 是顺序计数器，模块集合一变 id 就漂 | 失效 | `a0b80c0d` 之后 id 由声明派生（`check/identity.dawn` `derive`），是「属主 + 声明路径」的纯函数。调研对 5 个程序用裁掉 14 个模块的 std 跑 `emitc`，C 与全量逐字节相同 |
| Core golden 断言三程序 std 同 dump | 失效 | `selfhost-core-diff.sh` 自 2026-09-25 起是按需的两 revision 对照，不再是门 |
| `no bundled std module` 的候选清单要稳定 | 靠回退解决 | 清单取自已加载模块的导出表。导入了嵌入 std 里不存在的模块时，本设计回退全量加载（§4），清单不变 |
| impl 一致性是全程序的 | 成立，由孤儿规则承担 | §5 |

## 3. 什么被加载

**基座**：下面四类，再取闭包。不是一张人写的名单，每一类都从声明它的地方读：

| 来源 | 读哪里 | 得到 |
|---|---|---|
| 没有声明点的内建类型的属主 | `types.builtin_type_inventory()` 里 `BtLeaf(TyOpaque(.., owner, ..))` | `std/char`、`std/loc` |
| 为孤儿规则认领内建头的模块 | `passes.head_owner` 对各 `Head` | `std/list`、`std/map`、`std/set`、`std/str`、`std/bytes` |
| prelude 名字的属主 | `stdlib.prelude_owner` 对 `prelude_names()` | `std/io`、`std/list`、`std/fmt` |
| lowering 不论程序导入什么都会调进去的表示模块 | `types.internal_std_modules()` | `std/hamt`、`std/pvec`（`lower` 的 `hamt_sig` 找不到会 panic，`emitc` 的 list 原语同理） |

闭包：这些模块自己的 `use std/..`（`str`→`cursor`、`bytes`→`char`、`loc`/`fmt`→..）。结果是 12 个模块：
`bytes char cursor fmt hamt io list loc map pvec set str`。`stdlib.std_base_modules` 取前四类，
一个内联测试把结果与上面这行钉在一起，改了「编译器无条件需要什么」就必须改这里。

**其余模块**：当且仅当模块图导入它（传递地）。模块图指加载器已经读进来的全部模块的 `use std/..`，
包括 `[deps]` 路径依赖包里的（调研用文本扫目录时漏了 `packages/tea-dom` 的 `std/reactor` 与
`packages/tileir` 的 `std/float`，7 个单元因此报缺模块；这正是不能扫文本的原因）。传递部分取自
std 模块自己的 `use`：`modules.txt` 按依赖序排，所以从后往前走一遍，每个入选模块 parse 一次并把它的
`use std/..` 并入需要集合，随后的检查直接用这次 parse。

## 4. 范围与回退

与 #685 的 lean 加载同一条边界：内嵌 std，用于 `check`、`emitc`、`build`、`run`、程序的 `test`，
native 与 JVM 的 `check`。以下一律全量，行为不变：`--std <dir>`、`DAWN_STD`、`test --stdlib`、`doc`、
LSP、JVM 的 `run/build/emitc`（它们本来就没用 lean）。

内嵌 std 上，下列情形也回退全量：

- 某个模块没有 parse 成功（它的导入未知）；
- 导入了嵌入 std 里没有的 `std/X`（`no bundled std module` 的候选清单列的是已加载模块，必须是全部）。

多目标的 `check` 先把全部目标加载完，取导入的并集，std 只加载一次。

**`StdCtx.moved`**（未定义的裸名字的 `use std/X, then X.f(...)` 提示）本来由已加载模块的导出构建，
裁掉的模块里的提示会消失，那是可观测的文案差。所以生成器 `gen-stdsrc.py` 同时写出所有模块的导出函数
表（`stdsrc.moved_rows`），裁剪加载直接用它。表的识别规则是行级的（顶层 `pub fn`，以及 `pub trait` /
`pub effect` 块里缩进两格的方法），不是 parser；它由内联测试对着全量加载逐键比较，误读即红。

## 5. 两道门

**孤儿守卫**（`stdlib.orphan_violations`，内联测试）。一个基座之外的模块被裁掉后，只有在它的 impl
不导入就看不见时才是无声的。impl 靠 trait 或靠 subject 类型被遇到，所以要求：基座之外每个模块里的每个
impl，trait 或 subject 类型至少一个由该模块声明。孤儿规则（`passes.pass_register_impls`）本来就强制
二选一，但它允许认领了内建头的模块拿一个没人声明的内建 subject 过关，所以守卫里内建 subject 不算「声明在
本模块」，认领者必须在基座里。判定读已经建好的表：`StdCtx.impls` 的 `owner`、`identities` 的属主、
`TyOpaque` 自带的属主。负控写在同一个测试里：把 `std/list` 或 `std/str` 从基座拿掉，守卫必须报告
违例；拿掉没有这类认领的 `std/loc`，必须不报。

**全量/裁剪差分门**（`scripts/std-prune-diff.sh`）。对检查器语料、`examples/`、Playground 样例，
内嵌 std 的裁剪加载与 `--std std`（全量；`std/` 与内嵌副本逐字相同由既有测试保证）比较
`check` 的退出码、stdout、stderr，以及 `emitc` 的 C 输出，逐字节相同。任何静默差异即红。

## 6. 取消资格条件

差分门有任何静默差异，或出现不导入即可见的基座之外的 impl。

## 7. 实测

（实现后补。）

## 8. 不做的（理由）

- **惰性函数体**：裁剪之后 check 体只剩约 23 ms，要字节层配括号并认字符串与注释，等于第二个迷你词法器，
  与「lexer 是单一事实」冲突。
- **AST 序列化缓存**：AST 有 43 个类型、91 个变体，无 derive，要手写序列化，约省 50 ms，
  且多一代自举（快照必须由同一代编译器生成）。
- **C0（暖编译 worker）**：期望空程序 `check` 降到 0.3 s 以下，线以下就关闭不做。
- **LSP、`doc`、`test --stdlib`、`--std` 目录**：它们读 `StdCtx.mods` / `srcs`，或者目录的主人可能正在改
  std。这一刀不扩大范围。
- **把 `moved` 表改成运行期惰性求值**：要让加载器在报错路径上回头加载被裁的模块，把纯函数变成有状态的；
  生成一张表更小。
- **新的 parse-only 相位**：被留下的模块照旧完整走原流程，只是 `names` 少几项。
