# 平铺数值缓冲与 `Mem` 效果（可变数组线 K1）

> 状态：**proposed**。2026-10-09 写成。基线 `origin/main` = 3cafc848（初稿写在 8025df1e 上，已 rebase）。
> 调研报告：维护者工作区 `research-mutable-arrays-20261009.md`（含全部 `file:line` 与网页出处，本文只留结论）；
> 裁决：同目录 `ruling-mutable-arrays-20261009.md`；上游裁决 `ruling-bulk-array-bytes-20261008.md`。
> 触发：dawnop-site S5（纯 Dawn bcrypt）在 JVM 上比 jBCrypt 慢约 10 倍（cost 12：1.9 s 对 0.18 s）。
> 维护者指示（2026-10-08，逐字）：「既然做了，那就做个通用的呗，对于这种数组类型的，要有统一的解决方案，不要再走逐元素拷贝了」。
> 本文是裁决刀序里的 K1：句柄类型、`Mem` 效果、逃逸规则、拷入拷出，以及与批量打包线的接口。
> 没量过的数字写「未量」并写明由哪一刀去量；性能断言的出处都在 §1.3。
> 代码块都不标 `dawn run` / `dawn compile`，`doc-check.py` 不编译它们；本文落笔时没有任何一段在编译器上跑过，
> 因为它们依赖的类型与效果还不存在。

## 1. 问题、根因与 K0 实测

### 1.1 Dawn 今天没有 O(1) 且无装箱的可变数值序列

`List[T]` 是 pvec（持久向量），没有按下标更新的 API；`Array[T]` 只有 std 能命名，`array_with` 在 JVM 上永远复制，
在 native 上只有 rc==1 时才就地写，而且元素是装箱的。bcrypt 是第一个必须按位置随机写的算法：Blowfish 的 S 盒
（1042 个 32 位字）在 8192 趟 rewrite 里被自己写、自己读，每趟 521 个块、每块约 82 次读状态字（调研报告 §0、§1）。

根因比「写是追加」更深：1.9 s 里「读」（pvec 的 `leaf_for` 与分支）和「追加写」都有份。调研报告的 Java 微基准
（同一个密钥调度，`Object[]` 装 `Long` 就地写）约 0.47 s，即**装箱数组即使就地写也只有约 2.6 倍**，过不了 1.5 倍线。
所以光让写变成 O(1)（路线 (a)，Perceus 式唯一性就地更新）不够，必须平铺无装箱存储。

### 1.2 方案一句话

`std/mem` 提供一个**不可逃逸的平铺 `i64` 缓冲**（`I64Buf`，JVM 是 `long[]`，native 是 `int64_t[]`）和一个 `Mem` 效果；
缓冲只能在 `with_mem { ... }` 的作用域里创建和访问，`with_mem` 在内部消解 `Mem`，所以**对外仍是纯函数**。
不改 `Array[T]`、pvec 与值表示，不要求唯一性分析；值语义靠边界拷入拷出成立，两后端同构。
这就是调研报告里的选项 (b)+(c) 合并，裁决第 1、2 条。

### 1.3 测量出处（性能断言只引这些）

| 数字 | 出处 |
|---|---|
| bcrypt cost 12 `checkpw`，load 12 到 30：jBCrypt 0.4 为 0.188 到 0.191 s | K0 实测（分支 `proto/mem-k0`，提交 96631562，仅本地，从未推送；记在 2026-10-09 协调者交接） |
| 同上：JVM 平铺 i64 缓冲 0.198 到 0.206 s（约 1.05 倍 jBCrypt） | K0 实测，同上 |
| 同上：JVM 当前的纯 Dawn 追加式实现约 2.4 s（约 12 倍） | K0 实测，同上 |
| 同上：native 平铺缓冲，clang-20 -O2、无 LTO：0.317 到 0.32 s（约 1.7 倍）；同一份代码加 `-flto`：0.19 到 0.20 s（约 1.0 倍） | K0 实测，同上 |
| K0 JVM 形态：`Int` 是 `long`，`get`/`set` 是 `(J)J` 静态方法，C2 全内联，无装箱 | K0 实测，同上 |
| K0 native 慢的原因：`get`/`set` 住在 `dawn_rt.c`，每次访问是一次跨翻译单元调用加双重界检查 | K0 实测，同上 |
| Core IR 没有死码消除未使用的 `set`、没有对 `get` 做公共子表达式消除，测试通过 | K0 实测，同上 |
| 手写 Java 微基准：`long[]` 就地写 cost 12 为 0.22 到 0.29 s（机器负载 14）；`Object[]`+`Long` 就地写 0.47 s；jBCrypt 同机 0.18 s | 调研报告 §0、§4（scratchpad `bf/B.java`） |
| 1M f64 打包/拆包：native 读箱与字节序不是成本，拆包的大头是每元素 `push_own` 的头分配 | `docs/bulk-array-bytes-design.md` §1.3（分支 `docs/bulk-array-bytes`，PR #644） |

### 1.4 K0 没有覆盖什么（这些是 K2 与 K3 要补量的）

K0 是**丢弃式原型**，形态与本文的设计有五处不同，所以 1.05 倍与 1.0 倍是「方向对」的证据，不是验收数字：

1. **没有句柄参数。** K0 用一个全局缓冲（JVM 是静态字段 `k0buf`，native 是文件级静态指针），`get(i)` 不带缓冲实参。
   本设计的 `at(b, i)` 把句柄作为参数；JVM 上基址能否在循环外提升、native 上长度在每次 `set` 后是否被重载
   （运行时用 `-fno-strict-aliasing`，`int64_t` 的写入可能与同结构体的 `len` 别名），都**未量**。K2 去量。
2. **没有 `Mem` 证据参数。** K0 的原语是纯类型的，没有任何带标签的函数。带 `!Mem` 的函数会多一个隐藏证据参数
   （[effects-design.md](effects-design.md) §5.2），未使用的参数通常被内联吃掉，但**未量**。K3 去量，这是第一个含证据参数的 bcrypt 数字。
3. **JVM 下标是 `L2I` 截断。** K0 靠 `LALOAD` 抛 `ArrayIndexOutOfBounds`，而 `(int)(2^32 + 5)` 等于 5，会静默别名。
   本设计要求先对 `long` 下标做显式范围比较再截断，多出来的这一次比较的成本**未量**。K2 去量。
4. **native 越界是 `abort()`**，不是 panic。本设计要求两后端同文案 panic（§5）。
5. **只有 bcrypt 一个负载**，访问模式是「字节索引的 S 盒读 + 顺序写」。sha2 的 W 表是另一种模式，K4 顺带评估。

## 2. 先例（出处见调研报告 §2，网页出处在该节）

| 语言 | 机制 | 本设计取什么、不取什么 |
|---|---|---|
| Haskell | `ST` + `STUArray`（平铺无装箱、块内可变），`runSTUArray` 在边界冻结；`runST` 靠 rank-2 类型保证状态不逃逸 | **取**：可变性关进作用域、边界处纯、平铺存储。**不取**其机制：Dawn 没有 rank-N 类型，品牌类型参数做不了，逃逸只能用 §4 的检查规则 |
| Lean 4 | `Array.set!` 在 rc==1 时破坏性更新，`ByteArray`/`FloatArray` 平铺 | **取**平铺原语的形状；**不取**唯一性：JVM 没有 RC，路线 (a) 的天花板是装箱读（§1.1） |
| Clean / Rust | 唯一性类型 / 所有权保证无别名才就地写 | 不取：要给语言加线性或所有权系统，范围远超一个原语 |
| OCaml | `Array`/`Bytes`/`Bigarray` 直接可变，float array 平铺 | 取平铺；**不取无值语义**：Dawn 不接受可变别名 |
| Koka | `st<h>` 效果加堆品牌 `h` 的 `runST`（凭记忆，本次未抓取）；Perceus/FBIP 只做检查 | 效果加作用域消解的形状与本设计同构；品牌靠 rank-2，同上不取 |
| Dawn 自己 | handler 域 `var`（[handler-state-design.md](handler-state-design.md) §8）：格子不是值，闭包捕获与传出词法域都是编译错误 | 取「可变物不能离开它的作用域」这条原则；**机制不能直接复用**，见 §4.1 |

读法（调研报告 §2）：O(1) set 加值语义只有三条路，RC 唯一性、类型强制线性、把可变性关进作用域。JVM 没有 RC，所以只剩第三条。

## 3. 表面（`std/mem`）

### 3.1 类型、效果与作用域

```dawn
## A flat, mutable buffer of 64-bit integers. Exists only under `Mem`.
pub type I64Buf   # compiler-owned; std names it, user modules may spell it too (see 4.2)

pub effect Mem {
  fn mem_alloc(n: Int) -> I64Buf
}

## Runs `body` with a fresh memory scope. Every buffer made inside is private to
## this call; the result cannot mention one (section 4). Pure when `!e` is empty.
pub fn with_mem[T, !e](body: fn() -> T !Mem !e) -> T !e = {
  with handle Mem { mem_alloc(n) => i64buf_new(n) }
  body()
}
```

- **`Mem` 是一个带操作的具名效果，不是标记**：解析器拒绝零操作的效果（`an effect must declare at least one operation`，
  本文落笔时在 `selfhost/src/front/parser.dawn:1535` 实测），`with handle` 也要求至少一臂（同文件 `:3361`）。所以唯一的操作是分配，
  `new` 经它走。读写不是操作：它们是带 `!Mem` 标签的普通函数，直接落到原语，**不经证据分派**，热路径上没有闭包调用。
- **`with_mem` 的形状照抄 `io.with_clock_real`**（`std/io.dawn:874`），区别是生产 handler 不碰宿主，所以返回行是 `!e` 而不是 `!io`：
  `body` 若是纯的，`with_mem` 调用就是纯的，规范 §6.2 第 4 条（纯函数可折叠、可消重、可 comptime）因此对 `with_mem(...)` 成立。
  这条成立的前提是 §4 的逃逸规则，没有它，`with_mem` 返回一个别名过的缓冲，纯度就是假的。
- 带 `!Mem` 的函数不是纯的，所以规范 §6.2 第 4 条给编译器的折叠与消重许可**对读写调用不成立**。这是 `Mem` 必须是效果而不能只靠类型的第二个理由
  （第一个是让 `new` 在作用域外编不过）。Core IR 今天不做 DCE 与 CSE（K0 实测），K3 要把这一点钉成测试（§9）。

### 3.2 函数

```dawn
pub fn new(n: Int) -> I64Buf !Mem                          # zero-filled, n >= 0
pub fn len(b: I64Buf) -> Int                               # pure: the length never changes
pub fn at(b: I64Buf, i: Int) -> Int !Mem                   # position assertion, panics out of range
pub fn set(b: I64Buf, i: Int, v: Int) -> Unit !Mem         # position assertion, panics out of range
pub fn fill(b: I64Buf, from: Int, to: Int, v: Int) -> Unit !Mem   # writes: out-of-range panics, never clamps
pub fn copy_from(dst: I64Buf, dst_at: Int, src: I64Buf, src_at: Int, n: Int) -> Unit !Mem
pub fn copy_within(b: I64Buf, from: Int, to_at: Int, n: Int) -> Unit !Mem
pub fn clone(b: I64Buf) -> I64Buf !Mem                     # fresh buffer, same contents
pub fn from_list(xs: List[Int]) -> I64Buf !Mem
pub fn to_list(b: I64Buf) -> List[Int] !Mem
```

命名逐条过 CONTRIBUTING §7 的准入测试：

- **长度叫 `len`**，纯函数：长度创建后不变，所以不带 `!Mem`，在作用域外也能问。
- **读叫 `at`，不叫 `get`。** 判据一（断言，越界 panic）拼作 `at` 与 `[]`，判据二（问询，返回 `Option`）才拼 `get`；
  `bytes.get(b: Buf, i)` 就是反例，那是「panic 却占着判据二的名字」的缺陷。裁决文本里写的 `get`/`set` 是原语层的名字（`i64buf_get`），
  公开面按准入测试改成 `at`。`set` 与 `at` 同属判据一，文档注释里写明。
- **转换叫 `to_X` / `from_X`**：`to_list`/`from_list`，以及 §7 的 `to_bytes`/`from_bytes`。`clone` 与 `copy_from` 是动词：它们回答的不是「转成什么」。
- **`fill` 与 `copy_from` 的范围参数越界一律 panic，绝不夹取**（待裁问题 4，已裁）。判据三（`slice`/`take`/`drop`）夹取的理由是
  「参数是范围或落点，问的是这一段里存在的部分」；而一个**写**操作静默夹取会把越界 bug 变成少写了几个字，这与判据三的出发点相反。
  这条已作为一句话补进 CONTRIBUTING §7（英文正本与中文译本同提交）。
- **复制的命名**（已裁，不用图形学行话 `blit`）：区间拷贝取 Rust 的 `copy_from_slice` / `copy_within` 先例，写成 `copy_from(dst, dst_at, src, src_at, n)`（目的在前，与 `memcpy`、Rust 同序，也与 `System.arraycopy` 的源在前**相反**，所以实参位置名写进签名而不靠次序记忆），
  和同一缓冲内的 `copy_within(b, from, to_at, n)`。两者语义都是 memmove（重叠安全；`System.arraycopy` 与 C `memmove` 同语义，Rust 的 `copy_within` 也如此）。
  `copy_within` 是 `copy_from(b, to_at, b, from, n)` 的一行包装，不另立原语。
  **整份复制叫 `clone`**（Rust `Clone`、Java `Object.clone`），不叫 `copy`：于是 `copy_*` 簇只表示「把一段写进已有缓冲」，`clone` 只表示「产出新缓冲」，二者不会被混淆。
- 没有 `get(b, i) -> Option[Int]`、没有 `push`/`pop`/`resize`：长度固定是语义的一部分（§8）。需要时 K5 之后再按真实调用点补。

### 3.3 零值与长度上限

`new(n)` 清零。`n < 0` 或 `n > MAX_LEN` 一律 panic，`MAX_LEN = 2^31 - 9`（JVM 数组长度的实际上限，native 取同值使两后端行为一致）。
文案进合约（§5）。

## 4. 逃逸规则

### 4.1 为什么不能直接复用 handler 域 `var` 的机制

handler 域 `var` 的格子**不是值**：它没有可拼写的类型，用户拼不出它，`resolve_local` 把对它的读写在穿过闭包边界时改写成
`cell_get`/`cell_set`，闭包捕获它是编译错误（[handler-state-design.md](handler-state-design.md) §4.1、§8 问题一与问题五）。
逃逸禁令在那里便宜，是因为格子从一开始就不是能传来传去的东西。

`I64Buf` **必须是值**：bcrypt 的 `feistel(s, x)`、`rewrite(s, salt)` 这样的辅助函数要把缓冲当参数收，否则每个辅助函数都得内联进同一个块，
库（sha2、inflate 的窗口）无法组合。所以格子那条路（缓冲是不可拼写的名字）走不通，要换一套规则。共享的只有原则与方法：
「可变物不能离开它的作用域」加「每条规则配一个变异体负控」。

### 4.2 规则（K3 在检查器里实现）

底线先说清：**内存安全不依赖这些规则**。JVM 上句柄是 GC 管理的 `long[]`，native 上句柄是带引用计数的普通堆对象（§6.2），
一个逃出来的句柄只会让旧缓冲活得更久，不会悬空。这些规则保的是 `with_mem` 的**纯度**：缓冲的内容不能在 `with_mem` 返回之后还被人读写，
否则「对外纯」的承诺就破了。

- **R1，结果类型不得提及缓冲。** 在每个 `with_mem` 调用点，推断完成后，`T` 不得出现 `I64Buf`，
  也不得出现行里带 `Mem` 标签的函数类型。出现的判定要穿过元组、类型实参与用户 ADT/记录的字段（带代换、带环保护）。
  `Option[I64Buf]`、`(Int, I64Buf)`、`type Box = { b: I64Buf }`、`fn() -> Int !Mem` 都被拒。诊断指向 `with_mem` 调用并点名出现的位置。
- **R2，用户不能安装 `Mem` 的 handler。** `with handle Mem { ... }` 只在 `std/mem` 里合法。原因是闭包的行在**创建点结算**
  （[effects-design.md](effects-design.md) §4.6）：用户若在作用域里自己装一个 `Mem` handler，其内创建的、用到缓冲的闭包的行会被结算成纯，
  于是带着缓冲的「纯」闭包可以合法地作为 `with_mem` 的结果传出而不被 R1 看见。没有 handler 的用户代码里，
  任何用到 `at`/`set` 的闭包的行里永远留着 `Mem`（供给证据的只有 `with_mem` 自己对 `body` 形参的那一份），R1 的「带 `Mem` 的函数类型」那条才兜得住。
- **R3，缓冲类型不得出现在 effect 操作的签名里，也不得作为 handler 域 `var` 的类型。** 否则一个声明在 `with_mem` 外面的 handler
  可以在臂里把句柄存进它的格子，块剩余再读出来（臂在装 handler 的地方运行，不在发出操作的地方）。
- **R4，带 `Mem` 标签的函数值不得越过 `use java` 边界；缓冲不得作为 Java 互操作的实参或返回。** Java 可以在任意线程、任意时刻调用回调
  （[spec.md](spec.md) §9 的回调边界条款，「调用时机仍不受追踪」一条），缓冲会在 `with_mem` 返回之后被写。`I64Buf` 本来也不是可编组类型。
- `Mem` 在 `const` 初始化与 comptime 里一律拒绝：具名效果在那里本来就拒（[effects-design.md](effects-design.md) §4.5 的 comptime 条），
  解释器没有缓冲，原语进 `comptime_rejects()` 的名单，与 `Array` 同状态（解释器没有 `Array`，见 [spec.md](spec.md) 的 comptime 一节）。
- 没有语言级的线程原语，所以句柄不需要「不可发送」标注；若将来加了 `spawn`，`I64Buf` 与带 `Mem` 的闭包默认不可发送，那一刀要重开本节。

### 4.3 允许的东西（正例，同样进测试）

缓冲作为参数传给辅助函数；辅助函数声明 `!Mem`；`List[I64Buf]` 与用户记录在 `with_mem` **内部**持有缓冲；
嵌套 `with_mem`，内层 body 读写外层的缓冲（外层作用域仍然活着）；`to_list(b)`、`at(b, i)` 的结果（`List[Int]`、`Int`）作为 `T`。
内层缓冲不能传给外层（R1 作用于内层调用点的 `T`）。

### 4.4 否掉的做法

见 §8：品牌类型参数（没有 rank-N）、无句柄的隐式单缓冲、运行时作用域代号检查、native 区域释放。

## 5. 越界与错误语义（两后端同文案）

规范要求 panic 消息两后端逐字节相同（[spec.md](spec.md) §4.8 之后的 panic 条款：`panic(m)`、下标越界、`expect` 等，消息是 `catch_panic` 交回纯代码的值）。
现有的先例是 `array index N out of bounds for length M`（JVM `rtclasses.dawn` 的 `array_bounds_panic`，native `dawn_array_bounds_panic`）。

| 情形 | 文案 |
|---|---|
| `at`/`set` 越界（含负数） | `I64Buf index N out of bounds for length M` |
| `new(n)`，`n < 0` | `I64Buf.new: negative length N` |
| `new(n)`，`n > MAX_LEN` | `I64Buf.new: length N is too large` |
| `fill(b, from, to, v)`，不满足 `0 <= from <= to <= len` | `I64Buf.fill: range [F, T) out of bounds for length M` |
| `copy_from(dst, dst_at, src, src_at, n)`，`n < 0` 或任一区间越界（`copy_within` 同） | `I64Buf.copy_from: range out of bounds` 加两段长度，K2 定死后进合约 |

- **下标是 `Int`（64 位）。** JVM 实现必须在截断成 `int` **之前**对 `long` 做范围比较（K0 的原型没做，见 §1.4 第 3 点）。
  候选写法是单次无符号比较 `Long.compareUnsigned(i, len) >= 0`（一次比较同时覆盖负数）；它与 C2 的范围检查消除如何相互作用**未量**，K2 在两种写法间量一次，选快的。
- **native** 的 `at`/`set` 是 `static inline`（§6.1），越界分支调用一个 `noinline`、`cold` 的 `dawn_i64buf_oob(i, len)`，它构造文案并 `dawn_fault`。
  热路径上只剩一次比较和一个预测为假的分支。
- 合约测试 `scripts/mem-contract`（仿 `bytes-pack-contract`）两后端跑同一份 `.expect`，覆盖上表每一行，另加 `i = 2^32 + 5` 的别名负控（长度 ≥ 6 的缓冲上必须 panic，不得读到下标 5）。

## 6. 实现

### 6.1 native：`static inline` 进头文件，不开 LTO

K0 的 native 数字（§1.3）：无 LTO 约 1.7 倍，加 `-flto` 约 1.0 倍。差距的来源已知：`get`/`set` 在 `dawn_rt.c`，每次访问一次跨翻译单元调用。
修法有两条：给整个链接开 LTO，或把热路径函数挪进 `dawn_rt.h` 变成 `static inline`（头文件里已有大量先例，如 `dawn_idiv`、`dawn_dup`、`dawn_drop`）。

**推荐 `static inline`，不开 LTO**，理由：

- LTO 是全链接的编译器开关，波及每个产物的编译与链接时间，且 `scripts/cc-units.sh` 头注明确写着「没有 LTO 时目标文件与二进制不依赖编译顺序与作业数」，
  这是可复现构建（release-native 比较两次链接）靠的性质，LTO 会碰它（该脚本 `:27`）。为一个原语付这笔账不划算。
- `static inline` 只影响用到缓冲的翻译单元，其余程序零差异。
- 目标：native 上 bcrypt cost 12 **<= 1.2 倍 jBCrypt（即 <= 0.23 s，按 K0 同机 0.19 s）**。K0 的 LTO 数字（0.19 到 0.20 s）说明「内联掉调用」这件事本身够用，
  但 `static inline` 是否也追平 LTO（尤其是句柄参数、长度重载、越界分支布局）**未量**，K2 去量。
- 若 K2 未达标，升级梯子依次是：(1) 越界路径挪成 `cold noinline` 并加 `__builtin_expect`；(2) 在 `at`/`set` 内用局部拷贝避免长度重载；
  (3) 仅对运行时那一个翻译单元之外的产物局部开 LTO，且必须附墙钟影响声明（CI 墙钟纪律）。走到 (3) 要回来重开本节。

结构体：`typedef struct { dawn_hdr h; int64_t len; int64_t data[]; } dawn_i64buf;`，柔性数组成员让数据与头在同一次分配里，
热路径少一次指针解引用（`dawn_bytes` 是 `p` 指针，为了和字符串共享布局；这里没有那个约束）。

### 6.2 native：引用计数对象，不做区域释放

调研报告 §5 第 3 条担心「区域结束释放的缓冲遇到 panic 与控制帧的安全性」。本设计**绕开这个问题**：缓冲是普通的 RC 对象，
最后一个引用 drop 时释放（叶子对象，无子引用，掩码为空），与 `Bytes` 同类。panic 展开、控制臂的续延、`catch_panic` 都只是普通的 drop 路径，
没有「作用域结束时统一释放」这一个新的释放点，所以没有悬空读的可能，也不依赖 §4 的规则保内存安全。

- `at`/`set`/`len`/`fill`/`copy_from` 的缓冲形参是**借用**（不在 `types.dawn` 的 owned 实参表里，`:4205` 起那张表只列要拿走所有权的位置），
  所以热循环里没有逐次的 dup/drop。K2 用 `rc-contract` 与 emit 转储核对这一点；`new` 的结果是 owned，`copy`/`from_list` 同。
- ASan 门（`scripts/native-asan-tests.sh`）加三个用例：`with_mem` 内 panic 被 `catch_panic` 接住后零泄漏；控制臂挂起时持有句柄的续延被丢弃；句柄被闭包捕获后闭包被丢弃。

### 6.3 JVM

`I64Buf` 的 JVM 描述符是 `[J`，与 `Bytes` 是 `[B` 同构。原语是 `dawn/rt/Mem`（暂名，K2 定）上的静态方法：
`at ([JJ)J`、`set ([JJJ)V`，句柄在局部变量里，C2 内联后基址可以提升出循环（**未量**，K0 是静态字段形态）。
越界走 §5 的显式比较，抛 `dawn/rt/PanicError`，与 `array_bounds_panic` 同路径。`fill` 用 `Arrays.fill`，`copy_from` 用 `System.arraycopy`（后者自带 memmove 语义，注意它的实参次序是源在前，包装时对调）。

### 6.4 契约表登记

照 `docs/runtime-intrinsics-design.md` 的契约：语言只说一个原语归哪个**运行时模块**，各后端自己映射类名或翻译单元。
新增运行时模块 `RtMem`（不挤进 `RtArray`，后者的契约是 `Array[T]` 的窗口语义，二者没有共同点）。六个原语：

| 原语 | 签名 | 备注 |
|---|---|---|
| `i64buf_new` | `(n: Int) -> I64Buf` | 清零，§5 的两条 panic |
| `i64buf_len` | `(b: I64Buf) -> Int` | |
| `i64buf_at` | `(b: I64Buf, i: Int) -> Int` | |
| `i64buf_set` | `(b: I64Buf, i: Int, v: Int) -> Unit` | |
| `i64buf_fill` | `(b: I64Buf, from: Int, to: Int, v: Int) -> Unit` | |
| `i64buf_copy_from` | `(dst: I64Buf, dst_at: Int, src: I64Buf, src_at: Int, n: Int) -> Unit` | memmove 语义 |

全部 std-only（`internal`），comptime 拒绝；新内置类型 `I64Buf` 进 `types.builtins()` 的类型表并受 `scripts/builtin-type-contract` 与
`scripts/intrinsic-parity.py`（双向核对两后端 arm）约束。`clone`、`copy_within`、`from_list`、`to_list` 是 `std/mem` 里的 Dawn 代码，建在这六个之上，不单独加原语。

## 7. 与批量打包线的接口

批量线（[bulk-array-bytes-design.md](bulk-array-bytes-design.md)）的 A+ 方案是 `Array[Int|Float]` 与 `Bytes` 之间的一族原语，
它自己承认：运行时循环里仍然遍历装箱元素，只有平铺存储才能消掉那一遍。`I64Buf` 就是那个平铺端点（裁决第 3 条）：

```dawn
pub fn to_bytes(b: I64Buf, width: Int, order: Endian = Little) -> Bytes !Mem
pub fn from_bytes(bs: Bytes, width: Int, signed: Bool, order: Endian = Little) -> I64Buf !Mem
```

- **语义原样沿用批量线 §3**，不另立一套：打包取低 `8*width` 位环绕截断；拆包由 `signed` 决定符号扩展；`width in {1, 2, 4, 8}`；
  拆包时 `len(bytes) % width != 0` 一律 panic；`Endian` 是批量线 K4 给 `std/bytes` 加的类型，`mem` 用它而不重复声明。
- **实现**：`width = 8` 时 JVM 用 `ByteBuffer.asLongBuffer`，native 小端用 `memcpy`（端序不同用逐字交换）；其余宽度是一个运行时循环。
  与批量线的循环骨架生成函数共用一份骨架（批量线 §4），不另写。
- **相对批量线 A+ 的收益是预期，不是实测**：批量线 K0 量到 native 打包本身只要约 1.5 ms（读箱不是瓶颈），拆包的 29 ms 里约七成是每元素
  `push_own` 的分配，一次预分配填满只要 8.4 ms。缓冲端点天然是「一次分配、一次填满」，预期拆包落在 memcpy 量级；**缓冲端点的实测数未量，K5 去量**。
- 这不依赖批量线先落地：`to_bytes`/`from_bytes` 在 K5 才做，K5 排在批量线 K3/K4 之后或与其合并。在此之前，`from_list`/`to_list` 用 Dawn 循环实现，
  对 bcrypt（1042 个字，一次）不是瓶颈，其余场景**未量**。
- `F64Buf`（`double[]` / `double*`）同形，位保真，K5 做。落在同一模块 `std/mem`，函数名带 `f64_` 前缀（待裁问题 3，已裁）：`f64_new`、`f64_len`、`f64_at`、`f64_set`、`f64_fill`、`f64_copy_from`、`f64_copy_within`、`f64_clone`、`f64_from_list`、`f64_to_list`；`Mem` 效果与 `with_mem` 共用。

## 8. bcrypt 迁移草图（K4，只示意）

```dawn
use std/mem
use std/mem.{I64Buf, Mem}

const S0: Int = 18        # P at 0..17, S-boxes after it, as in the K0 prototype
const S1: Int = 274
const S2: Int = 530
const S3: Int = 786

fn feistel(s: I64Buf, x: Int) -> Int !Mem = {
  let a = mem.at(s, S0 + ((x >>> 24) & 0xFF))
  let b = mem.at(s, S1 + ((x >>> 16) & 0xFF))
  let c = mem.at(s, S2 + ((x >>> 8) & 0xFF))
  let d = mem.at(s, S3 + (x & 0xFF))
  (((a + b) ^ c) + d) & 0xFFFFFFFF
}

fn rewrite(s: I64Buf, salt: List[Int]) -> Unit !Mem = {
  # ... the K0 loop, with `mem.at(s, i)` / `mem.set(s, n, v)` in place of get/put
}

## Pure from the outside: the state buffer is born and dies inside this call.
pub fn hash_raw(password: Bytes, salt: Bytes, cost: Int) -> List[Int] =
  mem.with_mem(|| {
    let s = mem.from_list(INIT)
    eks_setup(s, password, salt, cost)
    digest(s)                       # List[Int]: the result mentions no buffer
  })
```

要点：辅助函数全部显式收 `s`（句柄是参数，所以同一份代码可组合）；`INIT` 仍是模块级 `const List[Int]`，每次调用 `from_list` 拷入一份（边界拷贝，值语义的来源）；
`digest` 在作用域内 `to_list`，出口只有 `List[Int]`；`hash_raw` 对外是纯函数，可折叠可消重。迁移改的是 dawnop-site 一个文件，
现有 41 个 hash 与 6 个测试不变。**迁移须先发 dawn-lang release 并 bump `.dawn-version`**（裁决 K4 备注）。

## 9. 刀序与验收

每刀一个 PR、一个主题、每刀一个提交。门禁覆盖用 `scripts/gate-map/gatemap.py` 查，不推导。

| 刀 | 内容 | 验收 | 负控 |
|---|---|---|---|
| K2 | 两后端运行时：`RtMem` 六个原语；`I64Buf` 内置类型；`static inline` 头文件版 `at`/`set`；契约门 `scripts/mem-contract`；`std/mem` 里**只含**原语的薄包装（暂无 `Mem` 效果，辅助函数先不带标签） | 合约 `.expect` 两后端逐字一致（§5 全表加 `2^32+5` 别名）；ASan 门三用例绿；`intrinsic-parity`、`builtin-type-contract` 绿；**重量 K0 的 bcrypt（句柄参数版、显式长整比较）：JVM <= 1.5 倍 jBCrypt（<= 0.27 s），native <= 1.2 倍（<= 0.23 s）**，同机、稳态、三次取中位；`Array`/pvec 与 emit 语料零差异（新增 `RtMem` 若令 emit 产物字节变化，按 `scripts/emit-labels.txt` 逐字 label 声明） | 越界比较写成 `>` 而非 `>=`；JVM 漏掉先比后截断（`2^32+5` 用例红）；`copy_from` 同缓冲重叠按正向逐元素拷贝（重叠用例红）；native `new` 不清零（零值用例红） |
| K3 | 检查器：`Mem` 效果、`with_mem`、R1 到 R4、`Mem` 在 `const`/comptime 的拒绝；`std/mem` 带上 `!Mem`；Core 保序测试 | **句柄逃逸的变异体负控全红**（下一行）；正例（§4.3）全绿；bcrypt 再量一次，这次**含 `Mem` 证据参数**，JVM <= 1.5 倍、native <= 1.2 倍；**同机同轮对比 K2（无证据）：慢出 10% 以上就触发零操作标记效果备用方案（§10 问题 2）**，两后端各判一次；Core 保序：夹在两次 `at` 之间的 `set` 不被消除，两次 `at` 不被合并（golden）；`Array`/pvec/emit 语料零差异 | R1：关掉规则后，下表 N1 到 N5 各自**必须**编过，开着必须红；R2：N6；R3：N7、N8；R4：N9；加 N10 作用域外调 `at`（「没人应答」，内置规则） |
| K4 | dawnop-site 迁移 bcrypt（须先发 release、bump `.dawn-version`）；评估 sha2 的 W 表与 H 状态 | 41 个 hash 与 6 个测试逐字节一致；native 同 hash；JVM cost 12 <= 0.27 s（<= 1.5 倍），native <= 0.23 s（<= 1.2 倍）；sha2 只评估不承诺（目标越过 25 到 30 MB/s，现状出处在调研报告 §1） | 把 `from_list(INIT)` 改成共享同一个缓冲跨调用（须被 R1 拒绝，或被测试发现两次调用互相污染） |
| K5 | `F64Buf`；`to_bytes`/`from_bytes` 与批量线原语的缓冲端点 | 1M 元素缓冲与 `Bytes` 往返：位保真（`0x7FF8000000000001`、`-0.0` 往返，两后端逐字节一致）；端到端耗时 <= 批量线同尺寸 `List` 路径（批量线通过线 1.5 倍 `List` 拷贝），实测数在本刀补记 | 字节序写反；宽度错一档；符号扩展写成零扩展 |
| K6 | 可选：JVM 静态唯一性分析（裁决第 5 条） | 仅在出现按位置更新 `List` 的实测需求时再评 | |

**K3 的变异体负控清单**（每条先证明会红：关掉对应规则，夹具必须编过；再证明规则开着时夹具被拒。门禁的绿没有信息量，只有变异体分得清「没漏」和「没看」）：

| 编号 | 夹具 | 由哪条规则拒 |
|---|---|---|
| N1 | `with_mem(\|\| new(4))`，`T = I64Buf` | R1 |
| N2 | `T = (Int, I64Buf)` 与 `T = Option[I64Buf]` | R1（穿过元组与类型实参） |
| N3 | `type Box = { b: I64Buf }`，`T = Box` | R1（穿过用户 ADT 字段） |
| N4 | 返回 `\|\| at(b, 0)`，`T = fn() -> Int !Mem` | R1（函数类型行里的 `Mem`） |
| N5 | 内层 `with_mem` 的结果带着内层缓冲传给外层 | R1（作用于内层调用点） |
| N6 | 作用域里写 `with handle Mem { mem_alloc(n) => ... }`，再让「纯」闭包带缓冲传出 | R2 |
| N7 | 用户 `effect Stash { fn stash(b: I64Buf) -> Unit }`，handler 装在 `with_mem` 外面并把句柄存进臂的 `var` | R3（操作签名） |
| N8 | handler 域 `var h: List[I64Buf] = []` | R3（`var` 类型） |
| N9 | `use java` 的 `Thread.new(\|\| at(b, 0))` | R4 |
| N10 | 作用域外直接 `new(4)` | 「没人应答」的既有诊断 |

## 10. 待裁问题与裁决

2026-10-09 协调者对本文七个待裁问题逐条裁决如下。已裁的写进正文，延后的写明重开条件。

1. **R1 到 R4 的落地：已裁，检查器专用特判，按 `Mem` 效果身份认。** `with_mem` 调用点做 R1，`with handle Mem` 的限制做 R2，R3、R4 同。
   **通用化的触发条件**（明文）：当出现**第二个**需要「作用域内、不可逃逸的句柄」的客户，预期是 `Gpu` 设备句柄，就把特判提升为通用机制
   （sealed 效果加局部类型标注），并**另写一篇设计文档**，那一篇才定语法与 spec 条文。现在不做：只有一个客户，抽象的形状没有第二个例子可对。
2. **证据参数备用方案的触发线：已裁，取紧线。** K3（含 `Mem` 证据参数）在同机同轮的 bcrypt cost 12 上比 K2（无证据）慢出 **10% 以上**，
   就打开「零操作标记效果」备用方案：允许零操作的效果，`with_mem` 成为检查器已知的消解形式，`Mem` 不产生证据参数，也不需要 `mem_alloc` 这个凑数的操作。
   这要改解析器（今天拒绝零操作效果）并新增一类消解形式，是比 R1 到 R4 更大的特性，所以只在这条线被越过时才开。JVM 与 native 各判一次，任一越线即触发。
3. **`F64Buf` 的位置与函数命名：已裁，同模块 `std/mem`，`F64Buf` 是自己的类型，函数带 `f64_` 前缀。** 依据现有先例：`std/bytes` 同时有 `Bytes` 与 `Buf` 两个类型，
   先到先得的 `Bytes` 占短名（`len`、`at`），`Buf` 的函数带类型名前缀（`buf_at`、`size`），CONTRIBUTING §7 把这两个例外逐条记了。
   Dawn 没有重载，同模块里别无他法。`I64Buf` 先到，占短名（`at`、`set`）；`F64Buf` 用 `f64_at`、`f64_set` 等（见 §7）。
   备选的同级模块 `std/memf` 被否：它会把 `Mem` 效果拆到两个模块的依赖里，而 `with_mem` 只应有一个。例外的理由写进 `std/mem` 的模块头注，免得被当成惯例抄。
4. **范围写入越界：已裁，panic，绝不夹取。** 夹取一个写操作会把越界 bug 悄悄变成少写了几个字。已作为一句话补进 CONTRIBUTING §7 与它的中文译本（同提交，更新了译文摘要）。
   **给 K2 的备注（本刀不实现）：** 若强制 §7 准入测试的脚本需要对应规则（例如「名字里带 `fill`/`copy_from` 的写入范围函数不得走夹取实现」），在 K2 里补，
   此刻只记下，不动脚本。
5. **名字：已裁。** `with_mem` 不变。图形学行话 `blit` 废弃，区间拷贝取 Rust/Java 先例：`copy_from(dst, dst_at, src, src_at, n)`（目的在前，Rust `copy_from_slice` 同序）与 `copy_within(b, from, to_at, n)`；
   整份复制叫 `clone`，不叫 `copy`，使「写进已有缓冲」（`copy_*`）与「产出新缓冲」（`clone`）两簇不会混淆。理由见 §3.2。
6. **`MAX_LEN = 2^31 - 9`：已裁，两后端取同值，通过。** 取同值换取行为一致，代价是 native 拿不到 2^31 以上的缓冲，没有调用点要它。
7. **`from_list`/`to_list` 是否在 K5 改走批量线的 `array_extend`/`pvec.to_array`：延后到 K5。** 现在 Dawn 循环够 bcrypt（1042 个字，一次）用，没有实测理由先动；K5 量完再定。

## 11. 不做的（理由）

1. **品牌类型参数（`I64Buf[s]` 加 rank-2 的 `with_mem`），照 Haskell `runST`。** Dawn 没有 rank-N 类型，效果行也不能给值打品牌；
   为此加高阶多态是比整条线都大的特性。取而代之的是 §4 的检查规则，代价是 R1 要穿过 ADT 字段的判定，这是一次性的实现成本。
2. **无句柄的隐式单缓冲（`with_mem(n, body)`，`mem.at(i)`，缓冲在证据里）。** 逃逸在构造上不可能，看上去最简单。否掉的三个理由：
   读写必须读证据里的基址，要么做成效果操作（每次访问一次闭包调用，native 上是间接调用，打掉内联，正是 K0 要避免的），要么新增「读证据」的内部原语，
   那是新的检查器与 lowering 机制；一个作用域只有一个缓冲，两个缓冲的算法（拷贝、转置、F64 加 I64）写不出来；辅助函数不能自带缓冲参数，库难以组合。
3. **运行时作用域代号检查（每个缓冲带 `with_mem` 的激活 id，每次访问核对）。** 热路径上多一次读取和比较，且需要「当前作用域」寄存器（线程局部），
   这是对 K0 已证明可以接近零开销的访问路径做相反的事。内存安全已由 GC/RC 保证（§4.2 首段），运行时检查只买纯度，而纯度靠编译期规则。
4. **native 区域/竞技场释放。** 见 §6.2：引用计数对象让 panic 与控制帧下的释放走普通 drop 路径，不引入新的释放点，调研报告 §5 第 3 条的风险因此消失。
5. **不改 `Array[T]`、pvec 与值表示**（裁决第 2 条）：缓冲是独立的非持久类型；装箱数组即使就地写也只有约 2.6 倍（§1.1）。
6. **JVM 加引用计数、Baker 重定根的持久数组**（裁决第 4 条）：范围过大只为一个原语；旧版本读退化、线程不安全、共享常量表会竞争。
7. **不为 bcrypt 加 `use java` 或专用 intrinsic**（裁决第 6 条）：违背 de-Java 方向，也不是统一方案。
8. **不暴露用户可写的 `Array[T]` 或 `xs[i] = v` 语法**：值语义会被可变别名打破；可变性只在 `Mem` 作用域内。
9. **不做 `fip` 标注**（沿用 `ruling-perceus-reuse-20261007` Q1）；不碰 `List[Float]` 平铺（value-repr K5，本缓冲只给它备原语）。
10. **缓冲不可变长：没有 `push`/`pop`/`resize`。** 追加式需求已有 `Buf`（追加）与 pvec；可变长缓冲要回答「重分配后旧句柄怎么办」，
    那是另一个别名问题，没有调用点要它。
11. **缓冲之间、缓冲与 `List` 之间不做零拷贝视图。** 视图要另一套逃逸与别名规则；值语义靠边界拷贝成立，这是本设计简单的来源。
12. **不做 `get(b, i) -> Option[Int]`**：没有调用点把越界当正常分支；判据二的名字留给将来真的需要时。
13. **不做 comptime 里的缓冲**：解释器没有 `Array`，缓冲同状态（§4.2）。
14. **不开 LTO**（§6.1）：除非 K2 梯子走到第 (3) 步并附墙钟声明。
