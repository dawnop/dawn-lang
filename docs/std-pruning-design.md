# 按程序裁剪 std：emit 边界上的可达性

> 状态：**current / 已落地**。刀 1（模块级 + 函数级，两个后端的 emit 边界）已落地，
> 尾款「pvec 的十个根改成有条件加」也已落地（§5 第二张表）。
> 立项调研见 `~/workspace/agent-handoff/research/std-prune-prestudy.md`（内部，未入库），
> 它的核心测量在下面 §5 复现。check 端的裁剪（调研里的方案 b）**不做**，理由在 §6。

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
* `c/emitc.emitter_named_pvec_fns()` 的十个名字，配上 `std/pvec`，**但只在这份程序里
  可能出现一个 List 时才加**（下面「List 的判据」）。列表字面量、`++`、七个 list 原语与
  Array 宿主边界都是**发射器自己拼出来的调用**，Core 里没有对应的节点，走图到不了。
  两个后端拼的是同一批十个名字（JVM 侧在 `gen_list_intrinsic` 的 `target` 表与 `PVEC_MOD`
  的四处直呼），`emitc.dawn` 里 `emitter_named_pvec_fns` 旁边的测试把这份名单钉在发射器的
  实际拼法上。

**List 的判据**（`reach.mentions_list`）：走图读到的每一个类型（表达式的、签名的、
发射器无条件保留的描述符的），只要里面有一个 `TyList`，这十个根就进队列，`Live.lists`
记下这个答案，两个后端读的是同一份，不各判一次。判据落在类型上而不是节点形状上：那十个
发射点每一个都收或吐一个 vector，所以产生它的 Core 节点自己的类型、或它某个实参的类型里
必有 `TyList`；而节点形状是发射器的事，会随发射器改，「这份程序里有没有 List」不会。

`TyAdt` 不往构造子的字段里递归，是有意的：`List[T]` 字段只是一个描述符，真要造出一个
List 得靠某个活函数体里的字面量或原语，而那里自带 `TyList`；读回来也是在读处交出
`TyList`。记录唯一藏得住 List 的地方是**折叠常量**：`CConstRef` / `CComptime` 指的是一个
Core 里根本没有的 `CValue`，`const P: Point = Point { xs: [1] }` 在引用处只有一个 `TyAdt`，
而发射器会像展开字面量一样把那个字段拼成 `std/pvec.from_array`。所以标量类型的折叠常量
放行，其余一律按「可能藏了一个 List」算（`reach.folded_may_hold_list`）。判错的代价是
C 侧的链接错误、JVM 侧的 `NoSuchMethodError`，所以每一条证不出「没有 List」的臂都答 true。

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

同机成对测量，基线 `fffe98f8`，头 = 刀 1。

| 判据 | 之前 | 之后 |
|---|---|---|
| `hello.dawn` 的 C 行数 | 24,140 | 1,205 |
| `apply_postfix.dawn` | 23,923 | 933 |
| `scripts/spike-native/` 119 条可编译语料合计 | 2,915,086 | 262,005 |
| `scripts/spike-native/run.sh` 全量墙钟（16 核，4 路） | 457.5 s | 238.3 s |
| `__emit examples/projects/calc.dawn` | 268 class / 358,758 B | 105 class / 83,097 B |
| `__emit selfhost` | 1,785 class / 5,406,006 B | 1,661 class / 5,256,477 B |

编译器自己省得少是意料之中：它用得起 std 的大半。

### pvec 的那一档，后来买了

刀 1 里十个根是无条件加的，所以一个只有 `println` 与算术的程序仍然带走 pvec 的闭包。当时
写着「要更准就得在走图时判断这份 Core 里还会不会出现一个 List，而判错的代价是链接错误」，
判为不值。后来做了，判据在 §3，代价确实是链接错误、也确实按「证不出没有就当有」写。

同机成对测量，基线 `9659a93d`（刀 1 之后），头 = 这一档。语料合计比的是两边都有的 126 条
（这一档自己新加的 `const_record_list` 不在内）。

| 判据 | 之前 | 之后 |
|---|---|---|
| `hello.dawn` 的 C 行数 | 1,205 | 438 |
| `apply_postfix.dawn` | 933 | 166 |
| `scripts/spike-native/` 126 条可编译语料合计 | 284,249 | 237,462 |
| 其中被裁到的条目 | 无 | 61 条，每条整齐 767 行 |
| `__emit` 一个只 `println` 的程序 | 106 class / 63,391 B | 104 class / 55,972 B |

61 条各减 767 行，是同一个 pvec 闭包在 61 个没有集合的程序里各出现一次。`__emit selfhost`
与 §7 里那十个差分语料一字节没动：它们全都用得起 List。

**墙钟没有那一行**。刀 1 砍掉的是语料 C 的 91%，`spike-native` 全量墙钟因此对半；这一档
砍掉的是 16%，且集中在 61 个本来就小的条目上。相邻三次实测 304.2 / 304.6（基线）/ 309.6 秒，
差在噪声里，所以这里不写一个数。省下来的是 C 的字节，不是这条流水线的时间。

剩下的 std 是走图能到达的真调用，没有第三个「发射器自己拼出来、Core 里没有节点」的族。

## 6. 不做的：check 端也裁

调研里的方案 b（只加载可达的 std 模块）省 check 的约 35%，但要新加一个 parse-only 相位、
会改 `no bundled std module std/X` 的候选清单（`scripts/checker-corpus/cases/imports.expected`
逐字记着今天的十四个名字），并且让 `std.*.core` 不再由任一程序完整产生，Core golden 的
语义会变。收益与风险不成比例。

2026-09-06 结账：**不立项**。emit 边界这条线上还剩的量（§5 第二张表）已经取完，check 端
那 35% 要换的是三样东西的语义，其中 Core golden 那一样正是这整份设计「裁剪停在 emit 一侧」
的立足点。重开的门槛是 check 时间自己变成瓶颈，而今天不是。

## 7. 守卫

| 说的话 | 谁在看 |
|---|---|
| 走图交出的答案本身 | `ir/reach.dawn` 的内联测试。List 判据是其中四条：正控（hello 的形状，十根不加）、负控（List 只出现在某个可达 std 函数的返回类型里，十根照加）、判据本身逐个类型构造子、折叠常量按类型判 |
| 可达时表在、不可达时表不在 | `scripts/table-freight/run.sh`（两侧模板，本刀沿用） |
| 裁掉的是死码，不是活码 | `bin/dawn` 的自举（编译器用裁过的 std 编译自己）、`dawn test selfhost`、`scripts/selfhost-fixpoint.sh`、`scripts/native-fixpoint.sh`、`scripts/spike-native/run.sh` 的语料七道检查、`scripts/package-tests.sh`、`scripts/example-tests.sh`、`site/build.sh` |
| 折叠常量里的 List 也算数 | `scripts/spike-native/const_record_list.dawn`，唯一的 List 在一个折叠记录常量的字段里，从不读出来。判据漏掉它就是 `undefined reference to dawn_std_2pvec__from_1array`，那条语料的 `cc` 检查 |
| lowering 那一侧没被碰 | `scripts/selfhost-core-diff.sh` 的 17 份 `*.core` |
| `--stdlib` 全留 | `dawn test --stdlib` 的 137 条 |
| 字典归属与 `modules.txt` 的排法无关 | `scripts/dict-owner-contract/run.sh`（把 `gpu` 挪到 `map` 之后重新 emit，字典表须逐字节不动、非空、且不由任何 std 模块填），与 `ir/reach.dawn` 的 "which module's copy of a dictionary is kept does not depend on load order" |

JVM 上裁错一个活方法是运行期的 NoSuchMethodError，不是构建失败——这是 JVM 惰性解析常量池
的性质，不是这把刀引入的。补的是**跑**：上表第三行里每一项都执行发射出来的字节，
最早的一处就是工具链自举本身，所以裁错在第一次 `bin/dawn` 就红。实测过：把 List 判据改成
「永远答不」，`./bin/dawn --version` 直接抛
`java.lang.NoSuchMethodError: 'std.pvec$Vec std.pvec.from_array(dawn.rt.Array)'`，
编译器连自己都建不起来。改成「永远答是」则回到刀 1 的行数（hello 1,205、apply_postfix 933），
所以上面那张表的差全部来自判据，没有别的来源。
