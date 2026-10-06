# native 迭代协议的 RC 往返

> 状态：**current**。native 性能线刀 2：`for x in xs` 与 `xs[i]` / `get` 的 dup/drop 往返去掉一半以上，两处根因各一个提交，已落地。2026-10-07。
> 依据：`agent-handoff/research-value-repr-report-20261006.md`（listf mode1 每次元素访问 17 次 dup + 17 次 drop、0 分配，nbody 每步 297 dup + 385 drop）；
> [native-inline-design.md](native-inline-design.md)（刀 1，RC 快路径内联不默认开，所以少做 dup/drop 比让它们更便宜更值）；
> [perceus-design.md](perceus-design.md) §6.4（借用约定与保守推断）。

## 一、结论

1. 往返不在 `for` 的 lowering 里，在**借用推断的两处盲区**：
   - 列表原语（`len`、`xs[i]`、`get`）被 emitc 拼成对 `std/pvec` 函数的直接调用，而这些函数整个钉成全 owned
     （调用点不读表，emitc 对每个借用操作数补一个 dup，被调方再 drop）；
   - impl 方法（`Iter[List]` 的 `start/done/get/next`，各是一行对 `std/pvec` 的转发）不进推断，
     `CImpl` 调用点不读表，所以 `for` 的每次循环体迭代对列表 dup 四次、被调方 drop 四次。
2. 两处各修一次，都是**让调用点读被调方的表行**，没有为 List 开特例：
   - 第一个提交：emitc 对列表原语读目标函数的行，infer 只钉 intrinsic 自己消耗的位置（`list_push` 的列表）与三个边界拼写（`from_array`/`to_array`/`concat`）。
   - 第二个提交：impl 方法有了自己的表键（`core.impl_mode_name`，即 emitc 一直用来 mangle 的拼写），`CImpl` 调用点、推断、`mode_mismatch`、`arg_flags` 都经 `core.mode_key`/`core.callee_mode_key` 读写。
3. 实测（本机，clang 18.1.3，`-O2 -fwrapv -fexceptions -fno-strict-aliasing`，`dawn_rt.c` 的临时副本里挂 dup/drop 计数器，listf n=1000）：

| 每次元素访问 | 改前 | 提交 1 后 | 提交 2 后 |
|---|---|---|---|
| `for x in xs` 求和（mode1），dup / drop | 10.97 / 12.96 | 8.97 / 10.96 | **5.97 / 7.95** |
| `xs.get(i)` 点积（mode2，每轮两次 get），dup / drop | 13.94 / 16.90 | 11.94 / 14.90 | 11.94 / 14.90 |
| nbody 每步，dup / drop | 297 / 385 | 226 / 314 | **124 / 212** |

   研究报告里的 17 是 100 万元素（trie 三层）下的读数，n=1000 只有一层；每多一层 `leaf_for` 多 3 次 dup，所以 11 对 17 是同一件事。

4. 墙钟（5 次中位数，`/proc/loadavg` 在每格后读，本机同时有别的工作在跑，3.9 到 4.6；差别在 ±5% 噪声之上才读）：

| 基准 | 改前 | 改后 | 负载 |
|---|---|---|---|
| listf mode0（只建表） | 0.358 | 0.311 | 4.3 / 4.6 |
| listf mode1（`for` 求和，100 万 × 20） | 1.289 | **1.043**（−19%） | 4.4 / 4.2 |
| listf mode2（`get` 点积） | 2.413 | 2.265（−6%） | 4.1 / 3.9 |
| nbody 300 万步 | 6.217 | **4.819**（−22%） | 4.1 / 4.3 |
| 自举负载 `dawnc emitc selfhost/src/nmain.dawn`，user 秒（5 次交错） | 12.36 | **11.56**（−6.5%） | 2.9 / 2.8 |

   mode0 的差别是噪声（建表路径没有改）。mode1 每次访问约 46 ns 到约 37 ns，剩下的主体在 `std/pvec.leaf_for` 里（见 §四）。

5. 编译代价：nmain 闭包的 C 396,583 行 / 24.05 MB 变 396,874 行 / 23.86 MB；`cc-units.sh` 同一行 flag，clang 18，16 核墙钟 6.12 → 5.89 s，user 79.2 → 75.8 s（负载 3.6 与 5.0）。无回退。

## 二、根因的定位

`for x in xs` 对 List 的 Core 是对 `Iter[List]` 四个方法的 `CImpl` 调用。改前的 C：

```
if (iter_done(dup(xs), i)) goto end;
x = iter_get(dup(xs), i);
...
i = iter_next(dup(xs), i);
```

每个方法体又是 `pvec.count(dup(xs))`、`pvec.index(dup(xs), i)`。逐个数一次循环迭代（n=1000，一层 trie）的 11 次 dup：
`done` 2（调用点 1，`count` 1）、`get` 2（调用点 1，`index` 1）加 `at` 里取元素 1、`leaf_for` 里每层 3 加根与叶各 1、`next` 1。

为什么没被借用推断救起来，两条都是 pin 的字面效果：

- `infer.pinned` 把 `reach.list_roots()` 十个函数整个钉 owned，理由是「emitc 直呼其名，调用点不读表」。这对三个边界拼写是真的
  （literal/host 的 buffer 是 emitc 自己的规则），对五个列表原语不是：rc 把原语当 intrinsic，操作数本来是借用的，
  是 emitc 的 `own_args` 为了迁就被调方的 owned 约定而补 dup。pin 把一个**调用点的实现细节**固化成了被调方的约定。
- `infer.plain` 排除 `impl_of`。理由写在 `rc.mode_mismatch` 的注释里：表按 `CDirect` 能拼出的名字键入，两个 impl 的 `show` 同名。
  这是键的问题，不是语义问题：impl 方法只经 `CImpl` 到达（字典槽名的是 `lower.make_bridge` 造的普通桥函数，桥函数再 all-owned 地调 impl），
  所以给它一个不撞的键，两侧读同一张表就够了。

## 三、做了什么

| 项 | 做法 | 理由 |
|---|---|---|
| `emitc.list_call_args` | 列表原语的操作数按目标函数的表行：行里借用则裸传，行里 owned 则取 intrinsic 自己的转移（`list_push`）或补 dup | 与 `CDirect` 同一规则，`arg_flags` 同一张表 |
| `infer.list_owned_positions`、`reach.list_boundary_roots` | 整函数 pin 只剩三个边界拼写；原语目标只钉 `intr_owned_args` 列出的位置 | pin 的粒度回到「调用点真正的约定」 |
| `core.impl_mode_name`、`mode_key`、`callee_mode_key` | impl 方法的键 `(owner, "impl$<tid>$<subject_key>$<method>")`，与 emitc mangle 的拼写同一个函数 | 一处定义，`CImpl` 与 `CFun` 不各自重算 |
| `infer`/`rc`/`emitc` | `plain` 换成 `mode_key`；`dm_expr` 的调用臂、`owned_positions`、`mode_mismatch`、`stamp_modes`、`arg_flags` 都经两个键函数 | 契约的两个读者（被调方的 `CParam.mode`，调用点的表）保持逐函数一致 |

默认方法（`CDefault`）与带捕获的 lambda 仍不进表（调用点不读）。

## 四、不做的（理由）

- **`leaf_for` 的每层 3 次 dup**（mode1 剩余 5.97 里的大头，100 万元素下占 12 里的 10）。三次是：match 的 scrutinee 别名 dup、`VBranch(kids)` 绑定的 dup、`array_get` 结果的 dup。
  - 只改 `std/pvec` 的一行（让 `VLeaf(_)` 臂 panic 而不是返回 `node`，scrutinee 就不再需要别名）实测 5.97 → 4.98 dup，
    但它改变 JVM 的 `emit` 字节，要给每个 `emit *` 标签声明 Emit-Change，收益是每层一对而已，不值得为它扰动全部差分。没做。
  - 真正的解是 rc 的两件事：模式绑定按借用投影（`kids` 只被读，scrutinee 活到它的最后一次使用），或者「dup 后同一路径上 drop 同一值」的融合。
    前者推迟 scrutinee 的释放，与 Perceus 的早 drop（唯一性/复用的前提）直接冲突，要单独的设计与 `array_with` 就地率门禁（`array-contract`、`map-reuse-contract`）的实测；
    后者是一个 Core 级数据流 pass。两者都是整个编译器的 match 都受影响的改动，不是本刀的范围。留作下一刀。
- **Core 级内联 `Iter` 方法**：没有 Core 内联器，加一个是新 pass，且本刀的借用约定已经把调用点的 dup/drop 拿掉，剩下的只是调用开销。
- **`get` 返回借用元素**：`for` 每次元素一对 dup/drop（元素是装箱 Float）。要让 `get` 返回借用是语言层的签名改动（Iter trait 的返回约定），不是推断能给的。
- **`xs.get(i)` 的 `Some` 与元组分配**（mode2 每次 3 次分配）：是值表示问题，归 research-value-repr 的刀序（小值按值展开），不在 RC 往返这条线。
- **mode-contract 的 impl 翻转**：`DAWN_RC_MODE_FLIPS` 按 `(owner, name)` 指名，impl 方法没有可写的名字，所以没把 impl 加进 roster。
  负控是手工做的：让 `callee_mode_key` 对 `CImpl` 返回 `None`（调用点不读表，被调方仍盖 borrowed），listf 探针在 ASan 构建下立刻是 LSan direct leak。
  harness 学会指名 impl 键之前，这条保护靠 spike-native 的 ASan+LSan 语料与 `rc_check`。
- **让 `from_array`/`to_array`/`concat` 也借用**：它们是 emitc 自己写的边界拼写（`concat` 对两侧各 dup），读表要改三处拼写，没有测得的收益。

## 五、门禁

native-fixpoint（B == C）、`dawn test selfhost`（1005）、`native-selfhost-tests`（780）、spike-native（174 项，ASan+LSan）、
rc-mode-contract（`std/pvec:index` 的 known-red 已 FIXED，按文件里的预言删除；`std/pvec:push` 进 roster 作为剩下的 pin 的探针，编译期拒绝）、
rc-contract、array-contract、map-reuse-contract、pvec-contract、builtin-decl-contract、c-map（check 与 7 个变异体）、
`native-asan-tests`（10 个单元在 ASan+UBSan 下原生跑）。`native-cli-diff` 在 `test, the report is flushed as it goes` 一项红，
**改前同红**（`spin(10^15)` 在本机 clang 18 下被折叠，原生不挂住），与本刀无关。
输出层面：改动只影响 C 路径，JVM 的 `emit` 字节不变，无需 Emit-Change 声明。

## 六、落地记录

见提交 `Read the callee's mode row at list primitive call sites` 与 `Let devirtualised impl calls read the parameter-mode table`。
数据与脚本：`agent-handoff/native-iter-report-20261007.md`。
