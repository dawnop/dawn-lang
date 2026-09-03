# 按程序裁剪 std：emit 边界上的可达性

> 状态：**current / 已落地**。刀 1（模块级 + 函数级，两个后端的 emit 边界）已落地。
> 立项调研见 `~/workspace/agent-handoff/research/std-prune-prestudy.md`（内部，未入库），
> 它的核心测量在下面 §5 复现。check 端的裁剪（调研里的方案 b）**没有做**，理由在 §6。

## 1. 病

`std/modules.txt` 里的十四个模块，以前每一个都被整份 lower 并 emit，与程序用不用无关。
一个 `hello.dawn` 生成 24,140 行 C，其中 23,700 行是 std；`std/gpu` 一家占 8,190 行。
JVM 那边同理：一个只 `println` 的程序带走 268 个 class。

树里已经有一次可达性走图（`ir/reach.dawn`），走完之后只回答「Unicode 表带不带」，
把可达函数集合当场丢掉。这把刀就是把那个集合留下来。

## 2. 边界：只在 emit，不在 check

| 相位 | 变了吗 |
|---|---|
| `load_std` / `check_module` / `eval_comptime`（`driver/stdlib.dawn`） | 没变。十四个模块照样全部 parse + check + comptime |
| `lower`（`ir/lower.dawn`） | 没变。十四个模块照样整份 lower |
| `__lower --dump` | 没变。所以 `scripts/core-golden/` 的 17 份 `*.core`（含 `std.gpu.core`）逐字节未动 |
| emit（`c/emitc.dawn`、`jvm/emit.dawn`） | 只写走图到过的东西 |

把线画在这里的代价是 check 时间一秒不省；买到的是三件事：没人到达的 std 模块里的类型
错误照样会被发现，`no bundled std module std/X` 的候选清单不随程序变，Core golden 不动。

## 3. 走图

一次走图，三个答案（`ir/reach.Live`）：Unicode 表、活函数集、活字典集。
两个后端读同一份。

**根**：

* 用户程序每个模块的**每一个**函数（测试块在内，按后端跟随它嵌入的东西：JVM 传
  `lower.emitted_core`，native 传 `named_tests` 改过名的 Core）。所以**只有 std 会掉东西**；
* `c/emitc.emitter_named_pvec_fns()` 的十个名字，配上 `std/pvec`。列表字面量、`++`、
  七个 list 原语与 Array 宿主边界都是**发射器自己拼出来的调用**，Core 里没有对应的节点，
  走图到不了。两个后端拼的是同一批十个名字（JVM 侧在 `gen_list_intrinsic` 的 `target` 表
  与 `PVEC_MOD` 的四处直呼），`emitc.dawn:1505` 的测试把这份名单钉在发射器的实际拼法上。

函数的身份是 `ir/core.fn_key`：owner + 是 impl/default/test/普通 + 名字。用扁平列表里的
下标不行——两边得用同样的顺序建那张表，而那种耦合坏了没人看得见。

**全留的两条路**：`dawn test --stdlib` 与无 target 的 runtime-only jar。它们的程序里没有
用户模块，走图会说「什么都到不了」。这两条传 `None` 而不是一个「全活」的 `Live`：
「不裁」是**没有答案**，不是一个必须与走图保持一致的满答案。

## 4. 两个后端的不同，与字典的归属

C 是一个翻译单元，一个 key 一份字典；JVM 是每个模块一个字典 class，转发到**那个模块自己**
的槽桥。同一个 `Eq[String]`，每个需要它的模块都 lower 了一份一模一样（只差 owner）的桥。

以前 C 侧留「先遇到的那一份」，也就是 `std/modules.txt` 的排法说了算——而 std 里第一个
物化 `Eq[String]` 的是 `std/gpu`。于是用户程序的一个 `==` 就把 gpu 钉住（issue #69）。
整份 std 都在的时候没人看得见；裁剪之后它是 8,000 行。

现在 `reach.dict_owners` 按 **owner 名字最小**挑一份。任意，但每次一样，且重排
`modules.txt` 动不了它。走图标活**两份**：挑中的那份（C 要链的）和**引用方模块自己**的
那份（JVM 的 class 要转发的）。少标任何一份都是链接错误或 NoSuchMethodError；多标一个
小桥函数不值得省。

JVM 侧没有同一个缺陷：`dict_class(gx.class_name, key)` 本来就是每模块一份，谁也不会
借用别人的桥。

## 5. 量

同机成对测量，基线 `fffe98f8`，头 = 本刀。

| 判据 | 之前 | 之后 |
|---|---|---|
| `hello.dawn` 的 C 行数 | 24,140 | 1,205 |
| `apply_postfix.dawn` | 23,923 | 933 |
| `scripts/spike-native/` 119 条可编译语料合计 | 2,915,086 | 262,005 |
| `scripts/spike-native/run.sh` 全量墙钟（16 核，4 路） | 457.5 s | 238.3 s |
| `__emit examples/projects/calc.dawn` | 268 class / 358,758 B | 105 class / 83,097 B |
| `__emit selfhost` | 1,785 class / 5,406,006 B | 1,661 class / 5,256,477 B |

编译器自己省得少是意料之中：它用得起 std 的大半。

**std/pvec 是一个刻意的过量**。十个根是无条件加的，所以一个只有 `println` 与算术的程序
仍然带走 pvec 的闭包（823 行里有约 700 行）。要更准就得在走图时判断「这份 Core 里还会不会
出现一个 List」，而判错的代价是链接错误。裁剪之后 hello 已经比目标小一半，这一档没有买。

## 6. 没做的：check 端也裁

调研里的方案 b（只加载可达的 std 模块）省 check 的约 35%，但要新加一个 parse-only 相位、
会改 `no bundled std module std/X` 的候选清单（`scripts/checker-corpus/cases/imports.expected`
逐字记着今天的十四个名字），并且让 `std.*.core` 不再由任一程序完整产生——Core golden 的
语义会变。收益与风险不成比例，单独立项，排在后面。

## 7. 守卫

| 说的话 | 谁在看 |
|---|---|
| 走图交出的三个答案本身 | `ir/reach.dawn` 的内联测试（原有 7 条一字未改，新增 4 条） |
| 可达时表在、不可达时表不在 | `scripts/table-freight/run.sh`（两侧模板，本刀沿用） |
| 裁掉的是死码，不是活码 | `bin/dawn` 的自举（编译器用裁过的 std 编译自己）、`dawn test selfhost`、`scripts/selfhost-fixpoint.sh`、`scripts/native-fixpoint.sh`、`scripts/spike-native/run.sh` 的 119 条语料七道检查、`scripts/package-tests.sh`、`scripts/example-tests.sh`、`site/build.sh` |
| lowering 那一侧没被碰 | `scripts/selfhost-core-diff.sh` 的 17 份 `*.core` |
| `--stdlib` 全留 | `dawn test --stdlib` 的 137 条 |
| 字典归属与 `modules.txt` 的排法无关 | `scripts/dict-owner-contract/run.sh`（把 `gpu` 挪到 `map` 之后重新 emit，字典表须逐字节不动、非空、且不由任何 std 模块填），与 `ir/reach.dawn` 的 "which module's copy of a dictionary is kept does not depend on load order" |

JVM 上裁错一个活方法是运行期的 NoSuchMethodError，不是构建失败——这是 JVM 惰性解析常量池
的性质，不是这把刀引入的。补的是**跑**：上表第三行里每一项都执行发射出来的字节，
最早的一处就是工具链自举本身，所以裁错在第一次 `bin/dawn` 就红。
