# Core lint：lowering 之后的 well-formedness 校验与阶段间 ABI 静态对账

> 状态：**current**。2026-10-04，分支 `feat/core-lint`。
> 依据：bug 率调研报告 §7.1（Core/ABI 校验器两刀）与同日裁决；语料是该报告的 110 条 bug 表。
> 本文记要校验的不变量、放在哪、怎么开关、误报策略、实测成本，以及不做的。

## 问题

调研语料里最大的一族产品 bug 是「阶段间 ABI」（14 条）：checker 接受了程序，lowering 或某个后端
兑现不了，症状推迟到运行期（`NoSuchMethodError`、`IllegalAccessError`、`effect evidence missing`、
`NoClassDefFoundError: dawn/rt/Fn10`）或 codegen panic，而且往往只在一个后端炸。仓里唯一的 IR 级
校验器是 C 侧 RC 消费检查（`c/rc.dawn` 的 `chk_*`），它管辖的 bug（#68、#444）都以编译期 panic
的形式出现并定位到行；它不管的那几条都是静默错值或运行期崩溃。这是本仓内「校验器把晚期症状提前成
早期报错」的证据，本文把同一做法往前挪一个阶段，两个后端共用。

外部对照：GHC 的 `-dcore-lint`、rustc 的 `-Zvalidate-mir`、Lean 4 的 `IR.Checker` 都是
「调试/测试时开，发布时关」（报告 §6 [9][10][11]）。本文照此办。

## 两刀

### 刀 1：静态对账（不需要输入程序，进已有内联测试与 parity 脚本）

| 不变量 | 落点 | 对应缺陷 |
|---|---|---|
| intrinsic 在 JVM、C、comptime 三处恰好归一组 | `lower.dawn` 的五组划分测试（已有）；`interp.dawn` 的三组划分测试，本刀把 `staged_intrinsics` 并进「lowering 已移除」一组；`scripts/intrinsic-parity.py` 新增第三节：读 `interp.call_builtin` 的臂与 `interp_arms()` 双向对账 | #185、#283 |
| JVM 侧 emit 引用的每个 `dawn/rt` 方法（名 + 描述符）在 rtclasses 生成集里 | `emit.dawn` 的测试与 parity 脚本第四节（#205 已落地，本刀只补变异证据） | #205 |
| C 侧运行时符号在 `dawn_rt.h` 里 | `emitc.dawn` 的测试（69691c36 已落地，本刀只补变异证据） | 69691c36 |
| 函数值的参数上限从 FnN 生成表派生 | `types.fn_interface_arities()` 是表，`main.dawn` 照表生成 `Fn0..Fn9`；`fn_max_params()` = 表中最宽 − `fn_arity` 给每个函数值加的证据槽数，`ctl_max_op_params()` 再减续延；新测试断言表无洞、每种行上最宽的合法函数值都有接口、再宽一个就没有、控制臂最宽恰为表中最宽 | #87 |
| checker 与 lowering 的函数列表一一配对 | `emit.dawn` 的三个配对测试（#182 已落地） | #182 |

#87 原来的写法是 `fn_max_params() = 8` 与生成循环 `while n <= fn_max_params() + 1` 并列，两处各写一遍
「证据槽占一个」。现在只有表是手写的，上限读表；表加宽语言就加宽，表收窄 checker 同一提交收窄。

### 刀 2：`DAWN_CORE_LINT=1` 时 lowering 之后的 well-formedness（`selfhost/src/ir/lint.dawn`）

位置：两条驱动在所有模块 lower 完、任何后端读 Core 之前跑一次。JVM 在 `main.dawn` 的
`collect_program_roots`（读 `emitted_core`，即带测试块的那份），native 在 `cdriver.build_units`
（RC 改写之前，读 `pre`）。配对规则在模块粒度跑（那里 checker 的 `TModule` 还在手边），其余规则在
全程序粒度跑（字典 key 与被调函数可以在任何模块里）。`__lower`（覆盖率/Core diff 工具）不开。

规则（违例时 panic，列出每一条，前缀 `core lint:`，每条带规则名）：

| 规则 | 内容 | 对应缺陷 |
|---|---|---|
| `dict-shape` | 同一 key 的所有 `CDictDef`（跨模块）trait、`nargs`、槽数一致 | #144/#146 |
| `dict-arity` | `CDictRef` 指向 `nargs == 0` 的 def；`CDictApply` 指向 `nargs == len(args) > 0` 的 def；`CDictArg` 的下标小于 `nargs` | #13、#144 |
| `dict-undefined` | 被引用的 key 在程序某模块里有 def | （同族） |
| `evidence-row` | 提升出来的闭包从自己的 pack 里 `ev_get` 一个 label，则它的每个创建点的行都含这个 label；每个创建点的行都不含证据原子（纯或只有 io）时，闭包不得把自己的 pack 当证据交给被调者（命名调用的证据槽或函数值调用的 pack 位） | #43、#54 |
| `evidence-slot` | 命名调用的证据实参与被调者的槽形状一致：精确 label 槽收到该 label 的记录；擦除槽（效果变量、投影）不收裸记录；函数值调用的 pack 位不收裸记录 | 5f91c188、abab133a 同族 |
| `call-arity` | 对程序内已知的 `CDirect` 被调者，实参个数 = 捕获 + 参数 + 字典 + 证据槽 | 阶段间 ABI 总则 |
| `lowered-intrinsic` | Core 里不出现 `lowered_intrinsics`/`staged_intrinsics` 的名字，也不出现任何表都没声明的名字 | #283 |
| `fn-pairing` | 每个模块 checker 声明的函数与 lowering 产出的函数按位置同名、等长 | #182 |
| `unbound-read` | 每个被读、被赋值、被 drop 的符号在该路径上由函数参数或外层块里更早的 `let` 绑定；不可落空的语句之后不再检查（Never 规则） | #93 的形状 |

关于 Never（#93）：Core 保留了不可落空调用之后的代码（`let y: Int = stop(); println(y)`），后端不发射
它。所以「Never 之后不可达的读」在 Core 层不是违例，lint 的做法是在第一个不可落空的语句处停止检查
该块剩余部分，`unbound-read` 只对可达代码断言绑定。这条规则在本刀的语料里没有对应的复原缺陷：
#93 是 JVM 后端自己丢了落空信息，修在 `emit.dawn`，Core 本身没错。它在这里的作用是让「可达的读必
有绑定」成为可检查的事实，后端据此跳过不可达代码才是安全的。

## 开关与报错

`DAWN_CORE_LINT` 非空且不为 `0` 即开（`lint.enabled()`，`!Env`）。默认关，任何用户构建都不付成本。
违例是编译器 bug，不是用户诊断，所以是 panic 而不是带源码位置的 `error:`；消息形如

```
panic: core lint: 1 violation(s) of the lowered-Core invariants (DAWN_CORE_LINT=1)
  [dict-arity] nested_list_eq.main: dictionary `dict$1$List_Int` applied to 1 argument(s), but its def is a constant singleton (nargs 0); a backend would construct it through the singleton's private constructor (#13, #144)
```

最多列 40 条，其余计数。

## 误报策略

误报是让 lint 被关掉的原因，所以每条规则在需要猜的地方**跳过**而不是猜，跳过写在规则旁边：

- `evidence-row`：创建点的行含效果变量或投影时不判 label 读（pack 里装什么由调用方的实例化决定，
  Core 自己枚举不出来）；「空 pack 被转交」只认命名调用的证据槽和函数值调用的 pack 位两处。第一版
  认的是「body 里任何地方提到自己的 pack」，在 selfhost 上报了 6 处误报：控制效果的包装闭包把自己的槽
  交给 `ctl_yield`，那个槽装的是 handler 的 pack，不是它自己的行描述的（`lower.lower_ctl`）。收窄后为 0。
- `evidence-slot`、`call-arity`：只判程序里按 `(owner, name)` 唯一找到的非 impl、非 default 函数；
  `CImpl`/`CMethod`/`CDefault` 不判。
- `unbound-read`：`let` 在 init 之后才进作用域；循环体与 step 用循环外的作用域；`CSLoop` 视为可落空
  （无限循环之后的代码会被检查，只可能多报不会少报，实测 0）。

实测误报（全部 0）：

| 输入 | 编译次数 | 违例 |
|---|---:|---:|
| `scripts/spike-native` 全部 146 个条目，JVM `__emit` + native `__emitc`（std 加 `stdext/raw`，3 个 `.jvm-only` 只编 JVM） | 289 | 0 |
| selfhost：JVM `__emit selfhost`、native `__emitc selfhost/src/nmain.dawn` | 2 | 0 |
| `DAWN_CORE_LINT=1 ./bin/dawn test selfhost`（带测试块的整程序，911 项通过） | 1 | 0 |
| `DAWN_CORE_LINT=1 ./bin/dawn test compiler-plan`（90 项通过） | 1 | 0 |

前两行是 `scripts/core-lint-contract/corpus.sh`，本机 16 核 `--jobs 4` 墙钟 260 s。

## 变异证据（判据）

`scripts/core-lint-contract/mutate.py` 是变异补丁登记表（已登记进 `mutation-anchor-preflight.py`
的 ADAPTERS 与 REGISTRY_READERS、`scripts/anchor-readers.txt`），`run.py` 逐个复原，要求对应检查
用它自己的话变红；先跑正控（未变异副本上各检查全绿、各复现程序开 lint 无违例）。本机 127 s 全绿：

| 变异 | 复原的缺陷 | 变红的检查 |
|---|---|---|
| `static-69691c36` | `scalar_rt` 的 Float 臂指向不存在的运行时符号 | emitc 测试 every scalar relation the emitter names is one the runtime defines |
| `static-87` | 上限不减证据槽 | types 测试 every function value the checker admits has an interface to be called through |
| `static-182` | 配对检查丢掉长度半边 | emit 测试 a lowered list longer than the declared one is reported, not dropped |
| `static-185-arm` | interp 链里有一条 `interp_arms()` 未列的臂（死臂） | `intrinsic-parity.py` 新增的第三节 |
| `static-185-listed` | 给 lowering 必移除的名字列了臂（`parse_int` 的原形） | interp 测试 the comptime interpreter covers every intrinsic, removes it in lowering, or refuses it |
| `static-205` | emitter 调用的运行时方法描述符与生成集不符 | emit 测试 every runtime method the JVM emitter can call is one rtclasses generates |
| `static-283` | builtin 函数值包装体直接写 `CIntrinsic` | lower 测试 a builtin taken as a value lowers as the call it wraps |
| `lint-13` | 零目标条件 impl 走 `CDictApply` | `cond_impl_module`，两后端 `[dict-arity]` |
| `lint-43` | 局部 fn 的 label 拒绝被关掉 | `local_label.dawn`（issue 原复现），两后端 `[evidence-row]` |
| `lint-54` | 局部 fn 的效果变量拒绝被关掉 | `local_variable.dawn`（issue 原形加 main），两后端 `[evidence-row]` |
| `lint-144` | 字典 key 不含 arity | `nested_list_eq.dawn`，两后端 `[dict-arity]` |
| `lint-5f91c188` | 投影槽交裸记录 | `effect_assoc_row.dawn`，两后端 `[evidence-slot]` |

每个 `lint-*` 还要求：同一个变异编译器**不开** lint 时接受该程序（`lint-144` 不开 lint 时 JVM 运行即
`NoSuchMethodError: ...dict$1$List_Int.<init>(java.lang.Object)`，`lint-43`/`lint-54` 运行即
`effect evidence missing`），即 lint 把运行期症状挪到了编译期。

`lint-144` 的复现：先试的几个单模块形状（只比较嵌套列表；再加一次泛型调用；Option、元组）在今天的树上
都不触发，`Eq[List[Int]]` 的每次请求都走 `CDictApply`；开 lint 编译 selfhost 时才发现今天的触发形状：记录的合成相等性经常量拿
`Eq[List[Int]]`（`check/passes` 的 `Sig` 字段），嵌套列表直接比较经应用拿（`check/cx` 的测试）。
`nested_list_eq.dawn` 把这两者放进一个模块。

## 性能（实测）

本机 16 核，同一个 jar，`__emit selfhost` 与 `__emitc selfhost/src/nmain.dawn` 各五轮交替开关：

| | lint 关（中位数） | lint 开（中位数） | 增量 |
|---|---:|---:|---:|
| JVM `__emit selfhost` | 5.69 s | 5.74 s | +0.9% |
| native `__emitc nmain` | 5.70 s | 5.86 s | +2.8% |

轮间波动约 ±1 s（5.4 至 7.1 s），增量在噪声以内；报告 §7.1 预估的 2% 到 5% 是上界。lint 是对 Core 的
几次线性遍历，没有不动点。

## CI 与墙钟

- 刀 1：`types.dawn`、`interp.dawn` 的测试随 `dawn test selfhost` 走，parity 脚本已在 push 的
  job 里；新增的只是一个内联测试和脚本里的一节，墙钟约 0。
- 刀 2：**不进 push**（push-total 余量 0）。nightly.yml 新增 `core-lint` job：`run.py`（本机 127 s）、
  `corpus.sh --jobs 4`（本机 260 s）、`DAWN_CORE_LINT=1 ./bin/dawn test selfhost`（本机 37 s），
  timeout 45 分钟作失控止损。nightly 不计 push-total。是否进 push 等 nightly 攒够观测再按
  Gate-Budget 决定。

## 不做的（理由）

- **不进 push 门禁。** push-total 余量 0，裁决要求新动态检查先 nightly 实测。
- **不在 `__lower`（Core diff 工具）上开。** 它服务于两版本比较，已经逐模块 catch panic，混进 lint
  会把「哪个模块 lower 失败」和「哪条不变量破了」搅在一起。
- **不判 `CImpl`/`CMethod`/`CDefault` 调用的证据形状与个数。** 被调者要按 `(trait, subject)` 结构匹配
  找，subject 的实例化与 impl 声明的 subject 不同形，猜错就是误报；等有复原缺陷要它再做。
- **不追 Never 之后的读。** 见上文：那是后端的事，Core 合法。
- **不把违例做成用户诊断。** 违例是编译器 bug，用户改不了源码去绕；panic 加规则名给维护者用。
- **不在 RC 之后再跑一遍。** RC 之后的不变量由 `c/rc.dawn` 的消费检查管，两者不重叠。
- **不用 LLM 或随机程序扩大误报语料。** 那是报告 §7.3 的生成器，另立一刀；本刀的零误报断言只对
  树里现有的输入成立。
