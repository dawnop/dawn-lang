# native 运行时小函数内联与 -flto 评估

> 状态：**current**。刀 1（native 性能线）：整数除模内联已落地，RC 快路径做成开关（默认关），`-flto` 默认开的评估结论是不开。2026-10-06。
> 依据：`agent-handoff/research-value-repr-report-20261006.md`（标量版 option_s 非 LTO 下慢 5 倍，根因是 `dawn_imod` 在 `dawn_rt.c` 里不能内联）；
> 裁决 ffi-llvm 4.a（RC 快路径进头文件，或 `-flto`；要报 CI 墙钟）；[c-tu-split-design.md](c-tu-split-design.md) §4.5、§九（LTO 留待 4.a 实测）。

## 一、结论

1. **`dawn_idiv`/`dawn_imod` 改成 `dawn_rt.h` 里的 `static inline`，无条件，零成本。** 标量循环（不分配）非 LTO 下追平 LTO：
   option_s 0.755 → 0.147 s（5.1 倍），update_s 0.227 → 0.084 s，pair_s 0.259 → 0.118 s。
   编出的 C 文本一字不变，只是运行时头多了内联定义；nmain 闭包的 cc 时间与产物大小实测无变化（产物 +8 字节，cc user 77.8 对 78.2 s）。
2. **RC 快路径（`dawn_dup`、递减型 `dawn_drop`）做成 `-DDAWN_RT_INLINE_RC` 开关，默认关。** 开了以后运行快，但 cc 代价很大：
   整个 native 编译器（nmain，4,460 个函数）cc CPU +83%，代码 +30%。收益与代价都在下面几节，是否对用户构建默认打开交给裁决（§七）。
3. **`-flto` 不做默认。** 完整 LTO 在 nmain 上 16 核墙钟 5.4 → 45.2 s，4 核 11.1 → 48.4 s；ThinLTO 4 核 11.1 → 29.1 s，而且产物字节随目标文件路径变。
   运行只快 11%，而 RC 快路径内联单独就快 21%。小程序上 LTO 多花 20% 到 40% 的 cc 时间。
4. **CI 墙钟：本刀合入的默认配置不改任何 CI 墙钟**（发射的 C 不变，nmain 的 cc 不变）。开关与 LTO 的预估见 §六。

## 二、现状与根因

`dawn_rt.h` 里除 `dawn_adt0`、`dawn_own_drop`、`dawn_take` 外，没有内联函数；`dawn_dup`、`dawn_drop`、`dawn_idiv`、`dawn_imod`、
`dawn_box_int`、`dawn_adt_new` 全是 `dawn_rt.c` 里的外部函数。生成的 C 只见声明，所以不开 LTO 时每次整数除模、每次 dup、
每次递减型 drop 都是一次真调用，且编译器看不见 `dawn_imod` 里的 `b == 0` 分支，循环里什么都提不出来。
c-tu-split-design 实测过：「RC 原语本体本来就在另一个 TU（`dawn_rt.c`），单 TU 也没内联到它们」。

## 三、做了什么

| 项 | 做法 | 理由 |
|---|---|---|
| `dawn_idiv`、`dawn_imod` | `dawn_rt.h` 里 `static inline`，除零走 `dawn_idiv_zero`/`dawn_imod_zero`（`dawn_rt.c`，`noreturn`），`INT64_MIN / -1` 分支保留 | 内联体只剩一个比较与一次除法；panic 文案仍在一处，退出码与 stderr 与改前逐字相同（本机对拍：除零、取模零、正常值） |
| `dawn_dup` | `-DDAWN_RT_INLINE_RC` 时 `static inline`，否则仍是外部函数 | 见 §五 |
| `dawn_drop` | 同上：内联的只有 `p != NULL`、`!dawn_rc_leak`、`rc > 1` 的递减；`rc <= 1` 走 `dawn_drop_slow`（原函数体，含误用诊断与释放） | 保持「一份语义」：慢路径就是原来的整个函数，直接调它的人行为不变 |
| 开关一致性 | `dawn_rt.c` 在开时定义 `dawn_drop_slow` 而不定义 `dawn_dup`，关时反之 | 开关必须到达程序的每个翻译单元，含 `dawn_rt.c`；混着编会链接失败，这是错得响的那一种 |
| rc-contract | 新增「inline rc fast paths」一段：`-O2 -DDAWN_RT_INLINE_RC` 编同一份 `rc_test.c` 并运行 | 默认构建从不编内联那一份，没有这一段它会腐烂 |
| 没做：分配器内联 | `dawn_box_int`、`dawn_adt_new`（slab 空闲链表弹出） | 见 §八 |

## 四、基准（本机，clang 18.1.3，`-O2 -fwrapv -fexceptions -fno-strict-aliasing`）

来源：`agent-handoff/bench-repr-artifacts/dawn/*.dawn`（research-value-repr 的同一批源码，同一份 `__emitc --split` 输出，只换运行时头）。
每格 5 次取中位数，墙钟秒，AMD Ryzen 7 9700X。**负载**：这台机器同时有别的写者在跑，1 分钟负载读数在 3.4 到 5.8 之间，
所以单格有 ±5% 的噪声；标量版（pair_s、option_s、update_s）的差距远大于噪声，分配型的小差异（pair、tree 的 ±5%）不要读成结论。

列：base = 改前；def = 本刀默认（只内联除模）；inl = 另加 `-DDAWN_RT_INLINE_RC`；右半边同样三列带 `-flto -fuse-ld=lld`。

| 基准 | base | def | inl | base+lto | def+lto | inl+lto |
|---|---|---|---|---|---|---|
| option_s（标量） | 0.755 | **0.147** | 0.160 | 0.154 | 0.147 | 0.150 |
| update_s（标量） | 0.227 | **0.084** | 0.089 | 0.091 | 0.093 | 0.090 |
| pair_s（标量） | 0.259 | **0.118** | 0.122 | 0.119 | 0.121 | 0.120 |
| nbody | 6.144 | 6.102 | 5.668 | 5.644 | 5.526 | 5.140 |
| listf | 3.276 | 3.070 | **2.064** | 2.830 | 2.675 | 1.853 |
| update | 2.481 | 2.559 | 2.155 | 2.258 | 2.211 | 2.089 |
| option | 2.117 | 1.697 | 1.774 | 1.786 | 1.588 | 1.682 |
| pair | 3.400 | 3.478 | 3.800 | 3.249 | 3.438 | 3.607 |
| tree | 0.593 | 0.630 | 0.696 | 0.635 | 0.681 | 0.669 |

读法：

- **标量版**：除模内联一刀就追平 LTO（base+lto 与 def 同量级），这是本刀要修的缺口。
- **inl 是双刃的。** 递减型 drop 与 dup 占多数的负载受益（对 base：listf −37%、update −13%、nbody −8%），
  而每次 drop 都是 `rc == 1` 释放的负载（pair、tree，对象即生即死）内联的那一次检查白付，不快：第一轮 pair +1%、tree +6%，第三轮 pair +12%、tree +17%（对 base，含噪声）。
  这也是为什么它不能无条件打开。
- LTO 在 def 之上再给 3% 到 15%（nbody 9.4%、listf 12.9%、update 13.6%、pair 1%、tree −8%）；在 inl 之上再给 3% 到 10%。
- 数据文件与脚本：`agent-handoff/native-inline-report-20261006.md` 里列了位置；本节数字取自第三轮（base、def、inl 交错），
  早两轮（base、new）方向一致：listf 3.096 → 2.286，nbody 6.167 → 5.553，标量版同前。

### 自举负载（nmain 的 `dawnc emitc selfhost/src/nmain.dawn`）

产物是整个 native 编译器，在它自己的 bootstrap 负载上跑（user 秒，5 次中位数，负载 2.5 到 3.2）：

| 构建 | user 秒 | 对 base |
|---|---|---|
| base（-O2） | 12.55 | |
| base + 完整 `-flto` | 11.13 | −11% |
| base + `-flto=thin` | 11.13 | −11% |
| inl（-O2） | 9.91 | **−21%** |
| inl + 完整 `-flto` | 9.37 | −25% |
| inl + `-flto=thin` | 9.27 | −26% |

默认配置（def）对 nmain 与 base 的 C 完全一致（nmain 里几乎没有 `idiv`/`imod` 调用，产物只差 8 字节），所以第一行也是它。
只内联 dup、不内联 drop 的变体（A）：11.49 对 11.82（同一轮 base），−3%，cc CPU +19%，不值。
内联 drop 后再把 `dawn_own_drop` 标 `noinline`（B）：cc user 127 s 对 76 s，没有救回编译时间。
把内联体写得更短（E，`uint32_t` 区间比较折成一次）：产物反而 13.6 MB，cc user 140 s，更差。
另试过在 `dawn_drop_slow` 里给 `BOX` 与全标量 ADT 加叶子快路径（实验，未入库）：update −32%、nbody −10%，
但 tree +33%、pair 持平，且那一轮机器负载 7 到 10，数字不可信，**没有保留**。

## 五、编译时间（nmain 闭包，379k 行 C，16 段，clang 18.1.3，`scripts/cc-units.sh` 同一行 flag）

| 配置 | 16 核墙钟 | 16 核 user | 4 核墙钟 | 4 核 user | 产物大小 |
|---|---|---|---|---|---|
| base / def（-O2） | 5.4 s | 74 s | 11.1 s | 40 s | 9.41 MB |
| inl（-O2） | 10.0 s | 134 s | 20.1 s | 74 s | 12.22 MB |
| base + `-flto=thin` | 11.4 s | 99 s | 29.1 s | 66 s | 10.46 MB |
| inl + `-flto=thin` | 22.4 s | 168 s | 49.1 s | 112 s | 12.78 MB |
| base + 完整 `-flto` | 45.2 s | 81 s | 48.4 s | 64 s | 9.84 MB |
| inl + 完整 `-flto` | 74.0 s | 139 s | | | 12.23 MB |

4 核行用 `taskset -c 0-3` 加 `CC_JOBS=4` 近似 CI 的 4 核 runner。4 核两轮对拍：base 11.13 与 11.11 s，inl 20.25 与 20.01 s（负载 1 到 3），
16 核一轮（负载 2 到 6）。更早两批在负载 8 到 13 下测的数字方向相同但绝对值偏高，不引用。

**inl 的 cc 代价是内联点的数量，不是内联体的大小**：nmain 的 C 文本里有 65,462 处 `dawn_drop(` 与 46,408 处 `dawn_dup(`，产物多 2.8 MB，折合每点约 25 字节。
所以代价随程序大小线性涨，对小程序便宜：

| 程序（单次 cc，含 `dawn_rt.c`） | 行数 | -O2 | inl | -flto | `-flto=thin` |
|---|---|---|---|---|---|
| shapes | 7.7k | 1.16 s | 1.32 s | 1.29 s（bfd）/ 1.18 s（lld） | 1.23 s |
| json | 12.7k | 1.72 s | 2.26 s | 2.21 s | 2.20 s |
| site | 69.7k | 9.41 s | 12.42 s | 13.37 s（bfd）/ 10.65 s（lld） | 12.13 s |

（`dawn_rt.c` 自己约 0.4 s，不随开关变。）

## 六、对 CI 与用户构建的含义

**本刀合入的默认配置：不改 CI 墙钟。** 发射的 C 文本逐字不变，nmain 的 cc 与产物不变，只多了 rc-contract 里一段约 2 s 的 `-O2` 编译。

每次 push 编 nmain 的位置（`cc-units.sh` 的调用点）：native-fixpoint（A、B 两次）、native-selfhost-tests、native-cli-diff、wasm-contract、
java-target-classpath-contract、wasm-target 的 C 驱动、prev-diff-native 的 release-native（两次静态链接），大约 8 到 10 次。
若把 `-DDAWN_RT_INLINE_RC` 加进 `cc-units.sh`：4 核每次 +9 s，合计约 +80 到 +90 s 的 cc 墙钟分散在这些 job 上，
push-total 按 3 倍计约 +250 s，**需要 `Gate-Budget(push-total)` 声明**。若加 `-flto=thin`：4 核每次 +18 s，约 +180 s 墙钟，3 倍约 +540 s，且 ThinLTO 产物字节随路径变，
`release-native.sh` 的两次逐字节对拍会红。完整 `-flto`：4 核每次 +37 s，约 +350 s 墙钟，字节可复现（绝对路径下实测相同），但慢到不可行。
这些是由 §五 的单次测量外推的估算，**没有 CI 观测**；真值要等第一次 CI 运行再按惯例重述。

结论：**CI 的编译器构建继续不开 LTO、不开 RC 内联。** 理由是运行收益（−21%）不抵每次构建 +80% 的 cc，而 CI 的瓶颈就是 cc（#239）。

## 七、待裁决

1. **用户构建（`dawn build`、`dawn run`）是否默认开 `-DDAWN_RT_INLINE_RC`。** 小程序 cc +14% 到 +30%（shapes、json、site），
   运行在 drop 递减型负载上快 7% 到 37%，在对象即生即死的负载上不快、最多慢约 17%。收益不是单向的，我的倾向是**先不默认**，
   等 Perceus reuse（ADT 复用）落地后再测一次：reuse 会把「即生即死」那一类负载改成就地更新，那时 inl 的拖累会消失。
   若裁决为开：改点是 `nmain.dawn` 的 cc 行加一个 `-D`，`dawn test` 与自举构建保持关（它们走另一条路径），需要同步改 nmain 里四处 argv 断言。
2. **`-flto` 默认**：不开（§一第 3 条）。如果以后要给发布产物单独开，条件是先把目标文件路径从 ThinLTO 的模块标识里拿掉，
   或者改用完整 `-flto`（字节可复现，nmain 上 +40 s 墙钟，只在 tag 发布时付）。当前 release-native 是 `--static` 两次对拍，
   完整 LTO 会让这一步从约 25 s 涨到约 200 s。

## 八、不做的（理由）

- **分配器内联**（`dawn_box_int`、`dawn_adt_new` 的 slab 弹出）：slab 的头指针与当前 slab 表是 `dawn_rt.c` 的文件静态，
  内联要把它们导出，并带上 ASan 毒化、wasm 无 slab、`DAWN_SLAB_FORCE` 三套条件编译，rc-contract 十四个变异体都盯着这一段。
  上界可以由 LTO 估：带 LTO 的 def 比不带的只快 1% 到 15%，LTO 已经跨 TU 内联了这些分配函数，而分配密集型基准（pair、tree）几乎不动。
  所以上界就是个位数百分比，不值得动 slab。真要拿回「每对象 5 ns」，要靠少分配（CPR、ADT reuse），不是内联。
- **`dawn_drop_slow` 的叶子快路径**：见 §四末，实验数字不稳，且 tree 变慢。
- **LTO 进 `cc-units.sh` 的环境开关**：用不上才加。评估用的是临时脚本，不进库。
- **在 `nmain.dawn` 的 cc 行加 `-flto` 并带「失败则重试」回退**：clang 的 `-flto` 要 LLVMgold 或 lld，Ubuntu 的 clang-18 默认可用，
  别处不一定；回退等于把构建时间翻倍的失败路径做成默认，没有收益支撑。

## 九、落地记录

见提交 `Inline the small integer division helpers of the C runtime` 与随后的评估记录提交。
