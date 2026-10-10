# native 栈帧瘦身：返回时解除清理、不会 raise 的函数不挂清理

> 状态：**current**。R1a（native 性能线，Koka 差距报告的第一项）：两刀已落地，第三刀（槽着色）经实测不做。2026-10-11。
> 依据：`agent-handoff/research-koka-gap-20261011.md` §3.1、§4.1（rbtree 上 `DAWN_OWN_FRAME` 的清理扫描占 27.7% 指令，去掉得 30% 到 35% 墙钟，是上界，
> 消融版在 panic 时泄漏）；[perceus-design.md](perceus-design.md) §5.3（清理的存在理由）、[oneshot-design.md](oneshot-design.md) §11.10（强制展开逐帧跑 `dawn_own_drop`）、
> [rc-operand-unwind-design.md](rc-operand-unwind-design.md)（#467 的槽）。

## 一、结论

1. **返回时把槽数清零（`DAWN_RETURN`），清理的扫描在普通出口上就是死代码。** 普通返回时 RC 已经逐个释放或转移了每个槽，扫描只会读到 NULL；
   只有 raise 展开会丢掉一个还持有槽的帧，那条路径不经过 `DAWN_RETURN`，仍读完整计数。rbtree 3.951 → 3.046 s（−23%）。
2. **不可能被 raise 穿过的函数，整个清理属性都不挂。** 判定在 Core 上做（`selfhost/src/c/quiet.dawn`），是全程序调用图上的最大不动点。
   槽数组还在（槽要存储），但没有清理、没有注册、编译器可以把槽放进寄存器。在第一刀之上再省：rbtree 3.046 → 2.879 s，cfold 0.595 → 0.343 s（−42%）。
3. **槽着色（共用互斥生命周期的槽）不做。** 第一刀之后，普通路径上已经没有按槽数计费的东西；着色只能缩短 raise 函数的初始化，上界见 §六。
4. 正确性没有让步：panic、`catch_fault`、一次性续延丢弃三条路径都由 LeakSanitizer 守着，并且有**会变红的负控**（§四）。

## 二、根因

`dawn_rt.h` 的 `DAWN_OWN_FRAME(n)` 声明一个 `void *dawn_own[n+1]`，挂 `cleanup(dawn_own_drop)`。清理在**每一次**离开作用域时都跑，
循环 `1..n` 查 NULL。为了 raise 展开时恰好释放一次，这是必要的；对每天走几十亿次的普通出口，它是纯开销。
`n` 是整函数的槽数而不是活跃槽数：`ins` 是 24，`balance` 是 29。报告用 callgrind 量出 rbtree 2 万次插入里这个循环占 27.7% 指令（外加初始化约 2.5%）。

清理依赖的不变量是「普通出口上每个槽都是 NULL」（`dawn_rt.h` 的 unwind cleanup 一节早就写了这句话：每个 RC 放置的释放或转移都清槽）。
这条不变量以前只是约定。本刀把它变成可查的：`-DDAWN_OWN_CHECK` 的构建在 `DAWN_RETURN` 里扫一遍，发现残留槽就 `abort`。
用这个开关编出的 native 编译器本体（`nmain`）跑完 native selfhost 测试，834 项全过，所以不变量在整个编译器及其测试上成立。

## 三、做了什么

### 刀 1：`DAWN_RETURN`

```c
#define DAWN_RETURN(e) do { __auto_type dawn_ret_ = (e); DAWN_OWN_ASSERT_CLEAR(); dawn_own[0] = 0; return dawn_ret_; } while (0)
```

先算返回值再清计数：返回表达式里的调用可以 raise，那时帧必须还是满的。（实测 RC 总是先把返回值绑成原子再释放，所以这个顺序目前是「由构造保证」，
这个变异体是等价变异体，见 §四。顺序仍按防御写。）发射端 `emitc.ret_stmt`：帧里已经有第一个槽才用 `DAWN_RETURN`，否则是普通 `return`。
`nslots` 在函数体发射期间只增不减，所以更早的 `return` 只是没有享受到优化，不会错。wasm 上清理还负责注销影子栈，`DAWN_RETURN` 不动这件事。

### 刀 2：`quiet` 判定

一个帧被丢弃，只有两种方式：从它下面起的 raise 穿过它；或者它停在一次调用里、持有它的续延被回收。两者都要求这个函数在调用会 raise 或挂起的东西。
所以函数 `f` 是 **quiet** 当且仅当它的函数体和它能直接调用到的所有函数里**没有**：

| 来源 | 为什么算 | 例外 |
|---|---|---|
| 调用目标不静态已知（函数值、字典方法、默认方法） | 可以是任何东西，效果操作和 `resume` 都在里面 | 无 |
| `CIntrinsic` | 表里没有「哪些会 panic」的信息 | `null_ref`（就是字面 NULL）；`lower` 在已证穷尽的 match 末尾写的 `panic("unreachable match")`，且 `site` 是 `CNoSite`（用户写的 panic 带源码位置，永远算） |
| Int 的 `/` `%` | 除零 panic | Float 的不算 |
| 操作数不是 Int/Float/Bool/Unit 的算术与比较，`++` | 窄类型可能查范围，字符串与记录比较进运行时，`++` 是 pvec 调用 | 无 |
| 列表字面量、`CForeign`、非标量常量 | 发射成 `std/pvec` 调用 | 标量常量不算 |
| 直接调用一个不 quiet 的函数，或不在程序里的函数 | 传递 | 无 |

用工作表求**最大**不动点，而不是最小：自递归、没有任何 raiser 的函数是 quiet，这正是 rbtree 的 `ins`，一遍「没有任何调用」的检查会漏掉它。
同名同 owner 的多个函数（trait 实现的方法）要全部 quiet，调用点只写 `(owner, name)`。栈溢出不算 raise：没有 handler（`dawn_rt.h` 的程序栈一节），进程直接死，清理本来也不会跑。

quiet 函数的帧用 `DAWN_QUIET_FRAME(n)`：同样的数组与初始化，没有 `cleanup`、没有 wasm 影子栈注册。

## 四、正确性怎么守

- **LeakSanitizer 是裁判**，已有的 `spike-native` 语料（`ordered_owned_raise`、`alloc_raise`、`catch_kinds`、`ctl_discard_fault`、`handler_arm_catch`……）全量跑过，`ctl-live-contract` 与 `rc-contract` 全过。
- **`scripts/frame-contract/run.sh`**：一个程序（`frame_raise.dawn`），每个函数在一个槽里持有一个 `Box(String)` 越过一个 raise 来源。
  干净编译输出等于记录、无报告（普通与 `DAWN_OWN_CHECK` 两种构建）；`engaged` 查 `calm` 拿到无清理帧、会 raise 的函数都保留清理，
  免得「编译器什么都没判 quiet」的版本白拿全绿；然后五个变异体（`DAWN_FRAME_QUIET_MUTANT`，`cdriver.dawn`）逐个让分析不再计某一来源，
  对应函数必须被判 quiet、C 必须与干净版不同、ASan 必须报泄漏，**并且报告里点名了那个函数**。实测：

  | 变异体 | 该判 quiet 的函数 | 实测 |
  |---|---|---|
  | `intrinsics`（panic 算 quiet） | `hold` | 泄漏 166 字节 / 6 次分配 |
  | `dynamic`（函数值调用算 quiet） | `via` | 泄漏 262 字节 / 8 次分配 |
  | `callees`（直接调用 raiser 不传递） | `nest` | 泄漏 59 字节 / 2 次分配 |
  | `division`（Int `/` 算 quiet） | `quot` | 泄漏 59 字节 / 2 次分配 |
  | `dynamic`（效果操作，续延被丢弃） | `asker` | 同一次运行里点名 |

- **等价变异体**：把 `DAWN_RETURN` 里「先算值再清计数」颠倒，没有程序能红。RC 在返回前总是把值绑成原子再释放，所以返回表达式里从来没有「带着活槽的调用」。
  这是诚实的等价，不是漏测；防御顺序保留，harness 里不留一个永远绿的变异体。
- **`adt-reuse-contract` 的一处反向变化**：变异体 `reset-keeps-the-slot`（发射器读槽而不 take）以前靠退出扫描把残留的槽**二次释放**才让 `update_zero_alloc` 等四条断言变红。
  二次释放随扫描一起消失，这四条红从 `matrix.txt` 删掉；该变异体仍红在 `finished` 与 `answers`，并且被 `DAWN_OWN_CHECK` 直接抓住。
  这是诚实地承认：退出扫描曾经顺手兜住过一类发射器 bug，现在由一个显式的检查开关承担。

## 五、实测

机器负载 5 到 17（其他写者在跑），WSL2，clang-20 `-O2`，同一份发射的 Dawn 程序，base 是 `a27bfac5`，**交错**取 5 次最短墙钟，三栏是 base、刀 1、刀 1+2（秒）：

| 基准 | base | 刀 1 | 刀 1+2 | 刀 1+2 / base |
|---|---|---|---|---|
| rbtree | 3.951 | 3.046 | 2.879 | 0.729 |
| rbtree-ck（cons 链） | 7.210 | 6.649 | 6.377 | 0.884 |
| deriv | 3.303 | 2.887 | 2.678 | 0.811 |
| binarytrees | 12.060 | 12.159 | 12.054 | 1.000 |
| cfold | 0.552 | 0.595 | 0.343 | 0.620 |
| nqueens（cons ADT） | 0.982 | 0.994 | 0.964 | 0.982 |

输出 md5 逐项相同。binarytrees 与 nqueens 的热路径不在带槽的递归函数里（对象即生即死，时间在分配与释放），所以不动；
cfold 的刀 1 略慢（0.552 → 0.595）在噪声内，刀 2 之后明显快（递归求值的函数全是 quiet）。

自举与启动（native `dawnc`，clang-20，交错取 5 次最短，同一份 `selfhost/src` 输入，负载 8）：

| 项 | base | 刀 1+2 | 变化 |
|---|---|---|---|
| `dawnc emitc selfhost/src/nmain.dawn`（native 编译器编译自己） | 14.23 s | 11.99 s | −16% |
| `dawnc check` 空程序 | 0.421 s | 0.411 s | −2.5%（启动路径几乎不碰带槽的递归） |

## 六、剩下多少（为什么不做槽着色）

把刀 1+2 的 C 再用一份把 `DAWN_CLEANUP(f)` 定义成空的运行时头编一遍（消融：**所有**函数都没有清理，panic 时会泄漏，只作上界），交错对比：

| 基准 | 刀 1+2 | 全去清理 | 比值 |
|---|---|---|---|
| rbtree | 3.341 / 3.337 | 3.499 / 3.469 | 1.048 / 1.040 |
| cfold | 0.410 | 0.414 | 1.011 |
| deriv | 2.812 | 2.792 | 0.993 |

（rbtree 两行是两轮。）报告的上界是 −30% 到 −35%，刀 1+2 已经拿到 −27%，而把剩下的清理也整个去掉**不再更快**（差在噪声里，rbtree 甚至慢 4%，
那是别的代码布局效应）。槽着色能做到的最多是缩短 raise 函数的槽数组初始化，这个量在上面的测量里是零。

## 七、不做的（理由）

- **槽着色（互斥分支共用槽）**：§六实测，刀 1+2 之后清理整个去掉都不再更快，着色的上界是零。而它需要证明「分支 A 的槽在分支 B 开始前一定是 NULL」，
  这是 #467 一类 bug 的新来源，没有收益支撑就不碰。
- **表驱动 landing（raise 时查表释放，帧上不挂任何东西）**：要改 oneshot-design §11.10 的「强制展开逐帧跑 `dawn_own_drop`」，且 wasm 靠影子栈。
  §六已经说明帧上剩下的成本是零，没有可买的东西。
- **把更多 intrinsic 列入 quiet**：表里没有「哪些会 panic」的信息，逐个人工认定每个都是一次 `unsafe` 的判断。只收了 `null_ref` 与 lowering 自己写的不可达 panic。
  benchmark 里的受益函数（rbtree 的 `ins`/`balance`、cfold 的求值）靠这两个就够了；要扩，先在 intrinsic 表上加「可 raise」一栏并让门禁对账，再谈列名单。
- **解析 `CImpl`/`CDefault` 到具体函数后继续传递**：现在一律算 loud。trait 方法的静态调用是常见写法，但 rbtree/cfold/deriv 里不在热点上；等有实测的受益者再做。
- **quiet 判定放进 Core 层（给 JVM 后端用）**：JVM 没有这个清理。
- **把 `DAWN_OWN_CHECK` 接进 CI**：已在 `scripts/frame-contract` 的干净运行里用上；整套 native selfhost 测试开着它跑过一次（834 项），
  但 CI 常开会让每次 cc 多一个扫描，推迟到有人想要时再按 Gate-Budget 流程接。
- **在 CI 里接 `scripts/frame-contract/run.sh`**：它约 2 分钟（6 次 `__emitc` 加 7 次 ASan 构建）。接入要改 `gates.yml`、重录 steps lock 并写 Gate-Budget 声明，
  是单独的、要报墙钟的一刀，没有跟这两刀混在一起。

## 八、落地记录

提交 `Disarm the owned-slot frame on ordinary returns`、`Give functions that cannot raise a frame with no cleanup`，随后是本文与 `scripts/frame-contract`。
`runtime/c` 在 tile 台账的输入里（`scripts/tile-gpu-diff/inputs.py`），合入时 GPU 台账需要所有者重录。
