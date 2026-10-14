# 平铺数值缓冲与 `Mem` 效果（可变数组线 K1）

> 状态：**proposed**；K2（两后端运行时）已落地，见 §9.1。2026-10-09 写成。基线 `origin/main` = 3cafc848（初稿写在 8025df1e 上，已 rebase）。
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
| K4 迁移后 bcrypt cost 12 `checkpw`，JVM：0.162 s；同机 jBCrypt 0.160 s（5 次稳态）；迁移前旧 List 版约 1.9 s | K4 报告（2026-10-14，dawnop-site 迁移分支），同机、稳态、三次启动取尾部中位；临时 bench（8 次连续 `checkpw` 取后段），未入库 |
| 同上：native 0.142 s | K4 报告（2026-10-14，dawnop-site 迁移分支），方法同上；dawnc 取 v0.89.0 release 资产并校验 sha256 |
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
impl Len[I64Buf]                                           # len(b): pure, the length never changes
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
  **结果类型里出现任何类型变量也拒**（在上面的判定放行之后再查）：变量是调用者以后才挑的类型，调用者可以把它挑成缓冲，
  而那时被检查的调用是泛型包装而不是 `with_mem`，规则看不到。所以 `fn scope[T](f: fn() -> T !Mem) -> T = with_mem(f)`、
  效果多态的 `scope2[T, !e]`、`Option[T]` 与 `(Int, T)` 的包装都在 `with_mem` 那一行被拒；结果类型具体的包装（`-> Int`）照常通过。
  把 `with_mem` 当值用（`let w: fn(fn() -> I64Buf !Mem) -> I64Buf = mem.with_mem`）同样受此规则，因为之后的 `w(...)` 是动态调用，调用点不叫 `with_mem`。
  误杀无害的泛型包装是有意的代价：Haskell、Koka、Rust 都靠把作用域写进类型（rank-2 或生命周期）才允许泛型包装，
  Dawn 没有 rank-N（§11 第 1 条），在不靠枚举入口的前提下，保守拒是唯一正确的答案；通用解见 §11 第 13 条。
- **R2，用户不能安装 `Mem` 的 handler。** `with handle Mem { ... }` 只在 `std/mem` 里合法。
  原因是：`Mem` 标签是「这次读写不是纯的」的唯一凭据，而 `with handle` 是语言里除 `with_mem` 之外唯一能把一个标签从行里减掉的节点。
  用户若自己装一个 `Mem` handler（臂写成 `mem_alloc(n) => b`，返回手头已有的缓冲），其下的 `at`/`set` 的行就被减成纯，
  于是 `fn peek(b: I64Buf) -> Int` 这类读写可变缓冲的函数会被检成纯函数，规范 §6.2 第 4 条的折叠与消重许可会作用在它们的调用上
  （K3 后实测：关掉 R2，这样的 `peek`/`poke` 能通过检查，运行得到 `(0, 5)`，与 §3.1 矛盾）。
  所以 `Mem` 只能由 `with_mem` 减去，而 R1 只管 `with_mem` 的结果，两条规则合起来才闭合。
  **旧稿的理由已过时**：它说闭包的行在创建点结算，用户 handler 会让带缓冲的闭包变成纯、绕过 R1。
  V1′ 之后函数值保留完整的行，只有调用点的 `with handle` 减标签（[effects-design.md](effects-design.md) 开头 2026-08-24 补记）；
  实测（`mem_n06_user_handler` 的第二个函数，以及关闭 R2 后的探针）用户 handler 之下创建的闭包行里仍有 `Mem`，R1 自己就会拒。
  那个洞不存在了，R2 现在保的是另一件事，见上。
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
| `copy_from(dst, dst_at, src, src_at, n)`，`n < 0` 或任一区间越界（`copy_within` 同，它是 `copy_from` 的一行包装，文案里写的仍是 `copy_from`） | `I64Buf.copy_from: range out of bounds (dst_at D, src_at S, n N) for dst length DL and src length SL`（K2 定死，进合约） |

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

`I64Buf` 的 JVM 描述符是 `[J`，与 `Bytes` 是 `[B` 同构。原语是 `dawn/rt/Mem`（K2 定名）上的静态方法：
`at ([JJ)J`、`set ([JJJ)Ldawn/rt/Unit;`（`Unit` 在 JVM 上是单例对象，不是 `V`），句柄在局部变量里，C2 内联后基址可以提升出循环（**未量**，K0 是静态字段形态）。
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
  `push_own` 的分配，一次预分配填满只要 8.4 ms。缓冲端点天然是「一次分配、一次填满」，预期拆包落在 memcpy 量级；**缓冲端点的实测数在 K5 补记，见 §9.3**。
- 这不依赖批量线先落地：`to_bytes`/`from_bytes` 在 K5 才做，K5 排在批量线 K3/K4 之后或与其合并。在此之前，`from_list`/`to_list` 用 Dawn 循环实现，
  对 bcrypt（1042 个字，一次）不是瓶颈，其余场景**未量**。
- `F64Buf`（`double[]` / `double*`）同形，位保真，K5 已做（§9.3）。缓冲端点对 `F64Buf` 是 `f64_to_bytes(b, width, order)` / `f64_from_bytes(bs, width, order)`，宽度取 4 或 8，没有 `signed`。落在同一模块 `std/mem`，函数名带 `f64_` 前缀（待裁问题 3，已裁）：`f64_new`、`f64_at`、`f64_set`、`f64_fill`、`f64_copy_from`、`f64_copy_within`、`f64_clone`、`f64_from_list`、`f64_to_list`；长度不另起 `f64_len`，`F64Buf` 与 `I64Buf` 各给一个 `impl Len`（Len 裁决 K5，修订上面待裁问题 3 的命名）；`Mem` 效果与 `with_mem` 共用。

## 8. bcrypt 迁移草图（K4，已落地，下为原示意稿）

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

**K4 落地结果**（出处：K4 报告，2026-10-14；dawnop-site PR #5，已合并为该仓 main 的 31f185de，哈希稳定）：

- 做法照本节：`hash_raw` 内 `with_mem(...)`，辅助函数显式收句柄并带 `!Mem`，`rewrite` 内联 16 轮。
- 性能（同机、稳态、三次启动取尾部中位，cost 12 `checkpw`）：JVM 0.162 s，同机 jBCrypt 0.160 s，native 0.142 s；均在 K4 门限内（JVM 0.27 s，native 0.23 s）。
- 41 个 hash 与 6 个原测试逐字节一致，native 给出同样的 hash。
- emit 转储（`dawnc emitc`）：`feistel`/`encipher`/`rewrite` 对句柄只有借用，16 轮热循环里没有 `dawn_dup`/`dawn_drop`。
- 变异体负控：把 `from_list(INIT)` 提出 `with_mem` 外共享，R1 拒绝（`the result of with_mem cannot mention a buffer`）。
- sha2 只评估、未改：现状没有 W 表（消息调度用 16 个局部变量滑窗），H 状态是 8 元素 `List`；实测（16 MB，1 MB 一次 update，稳态）JVM 约 59 MB/s，native 约 128 MB/s，已高于 25 到 30 MB/s 的目标，故不动。

## 9. 刀序与验收

每刀一个 PR、一个主题、每刀一个提交。门禁覆盖用 `scripts/gate-map/gatemap.py` 查，不推导。

| 刀 | 内容 | 验收 | 负控 |
|---|---|---|---|
| K2 | 两后端运行时：`RtMem` 六个原语；`I64Buf` 内置类型；`static inline` 头文件版 `at`/`set`；契约门 `scripts/mem-contract`；`std/mem` 里**只含**原语的薄包装（暂无 `Mem` 效果，辅助函数先不带标签） | 合约 `.expect` 两后端逐字一致（§5 全表加 `2^32+5` 别名）；ASan 门三用例绿；`intrinsic-parity`、`builtin-type-contract` 绿；**重量 K0 的 bcrypt（句柄参数版、显式长整比较）：JVM <= 1.5 倍 jBCrypt（<= 0.27 s），native <= 1.2 倍（<= 0.23 s）**，同机、稳态、三次取中位；`Array`/pvec 与 emit 语料零差异（新增 `RtMem` 若令 emit 产物字节变化，按 `scripts/emit-labels.txt` 逐字 label 声明） | 越界比较写成 `>` 而非 `>=`；JVM 漏掉先比后截断（`2^32+5` 用例红）；`copy_from` 同缓冲重叠按正向逐元素拷贝（重叠用例红）；native `new` 不清零（零值用例红） |
| K3 | 检查器：`Mem` 效果、`with_mem`、R1 到 R4、`Mem` 在 `const`/comptime 的拒绝；`std/mem` 带上 `!Mem`；Core 保序测试 | **句柄逃逸的变异体负控全红**（下一行）；正例（§4.3）全绿；bcrypt 再量一次，这次**含 `Mem` 证据参数**，JVM <= 1.5 倍、native <= 1.2 倍；**同机同轮对比 K2（无证据）：慢出 10% 以上就触发零操作标记效果备用方案（§10 问题 2）**，两后端各判一次；Core 保序：夹在两次 `at` 之间的 `set` 不被消除，两次 `at` 不被合并（golden）；`Array`/pvec/emit 语料零差异 | R1：关掉规则后，下表 N1 到 N5 各自**必须**编过，开着必须红；R2：N6；R3：N7、N8；R4：N9；加 N10 作用域外调 `at`（「没人应答」，内置规则） |
| K4 | dawnop-site 迁移 bcrypt（须先发 release、bump `.dawn-version`）；评估 sha2 的 W 表与 H 状态 | 41 个 hash 与 6 个测试逐字节一致；native 同 hash；JVM cost 12 <= 0.27 s（<= 1.5 倍），native <= 0.23 s（<= 1.2 倍）；sha2 只评估不承诺（目标越过 25 到 30 MB/s，现状出处在调研报告 §1）；**已达成**：JVM 0.162 s、native 0.142 s，41 个 hash 与 6 个测试一致，sha2 实测 JVM 约 59 MB/s、native 约 128 MB/s 故不改（§8，K4 报告 2026-10-14） | 把 `from_list(INIT)` 改成共享同一个缓冲跨调用（须被 R1 拒绝，或被测试发现两次调用互相污染） |
| K5 | `F64Buf`；`to_bytes`/`from_bytes` 与批量线原语的缓冲端点 | 1M 元素缓冲与 `Bytes` 往返：位保真（`0x7FF8000000000001`、`-0.0` 往返，两后端逐字节一致）；端到端耗时 <= 批量线同尺寸 `List` 路径（批量线通过线 1.5 倍 `List` 拷贝），实测数在本刀补记；**已达成**（PR #737，§9.3） | 字节序写反；宽度错一档；符号扩展写成零扩展（**已验：JVM 与 native 各三个，全红**，§9.3） |
| K6 | 可选：JVM 静态唯一性分析（裁决第 5 条） | 仅在出现按位置更新 `List` 的实测需求时再评 | |

### 9.1 K2 落地记录（2026-10-09）

实现提交：`5113c698`（内置类型与六个原语，两后端）、`aaff683a`（`std/mem` 与契约门）。基线 `origin/main` = e027347b。

**做了什么。** 新增内置类型 `I64Buf`（`Ty` 的叶子变体 `TyI64Buf`，访问级别 `BtPublic`，不是 std-only：§3.1 说用户模块也可以拼写它，
辅助函数要把缓冲当参数收；它没有 `Eq`、`Hash`、`Ord`、`Show`，与 `Array` 同，按身份持有）；运行时模块 `RtMem` 与六个 std-only 原语
`i64buf_new/len/at/set/fill/copy_from`（comptime 一律拒绝）；JVM 类 `dawn/rt/Mem`（`I64Buf` 是裸 `long[]`，描述符 `[J`）；
native 的 `dawn_i64buf`（头、`len`、柔性数组成员，一次 `calloc`，叶子对象，`DAWN_K_I64BUF`）与头文件里 `static inline` 的 `len`/`at`/`set`，
越界走 `cold`、`noreturn`、`noinline` 的 `dawn_i64buf_oob`；`std/mem` 里是原语的薄包装加 `copy_within`、`clone`、`from_list`、`to_list`，
暂无 `Mem` 效果，函数不带标签（K3 加）。`F64Buf` 仍是 K5。

**契约门 `scripts/mem-contract`。** 一份用户程序 `probe.dawn`，三次对着手写的 `expected.txt` 逐字节比较：JVM、native（-O2）、native 加 ASan/LeakSanitizer/UBSan；
第四步不比输出，检查探针的汇编里没有 `dawn_i64buf_at/set/len` 的符号（`static inline` 退回外联时输出仍然对，只有这一步红）。
`expected.txt` 覆盖 §5 全表，加 `2^32 + 5`、`-(2^32 - 5)`、`INT64_MAX` 的别名与溢出探针，以及一个 `at + n` 会回绕的 `copy_from`。
`std/mem` 的 test 块（`dawn test --stdlib`；`scripts/native-asan-tests.sh` 在 ASan 下原生再跑一遍）另有 §6.2 要求的三个释放用例：
panic 被接住时缓冲活着；闭包捕获了缓冲后被丢弃。第三个（挂起的续延持有缓冲后被丢弃）需要 `ctl` 效果，而 std 的这个模块不引入也不声明效果（引入 `std/io` 的 `Exit` 会让 checker-corpus 与 identity 的 `mint-imported-effect` 变异体多红一批 std 测试），所以放在 `scripts/mem-contract/probe.dawn` 里，同样在 ASan 下跑。门禁接进 `gates.yml` 的 `contracts-1`（本机约 6 s，不改任何 budget 行）。

**变异体负控**（每个都先让门变红，再还原）：

| 变异 | 哪一步红 |
|---|---|
| native 的界检查 `>=` 写成 `>` | native 腿，`index` 行 `I64Buf index 8 ...` 变成 `no panic` |
| JVM 先截断成 `int` 再比较（K0 的形态） | JVM 腿，`2^32 + 5` 与 `-(2^32 - 5)` 两行变成 `no panic (0)` |
| native `copy_from` 按正向逐元素拷贝 | native 腿，`up`、`same` 两行 |
| native `new` 用 `malloc` 而不是 `calloc` | native 腿（以及 ASan 腿），`zero`、`plain` 两行 |
| `dawn_i64buf_at` 加 `noinline` | 内联检查，汇编里 19 行符号 |
| `dawn_i64buf_new` 每次多泄漏一块 | ASan/LeakSanitizer 腿 |
| `copy_from` 多拿一个对 `dst` 的引用不还 | `rc-contract` 的 `i64buf` 断言（登记为 `counted`，所有者 `i64buf`） |

另外 `scripts/rc-contract` 加了 `i64buf` 断言：新缓冲 rc 为 1 且清零，任何原语和任何由原语抛出的 panic 都不动引用计数，`dawn_immortal` 能处理这个种类。
核对 §6.2 的「热循环没有逐次 dup/drop」：bcrypt 的 emit 转储里 `feistel`、`encipher`、`rewrite` 对句柄只有借用，没有 `dawn_dup`/`dawn_drop`。

**实测：重量 K0 的 bcrypt（句柄参数版、显式长整比较），cost 12 `checkpw`，同机同轮，每轮 12 次取后 8 次的中位数，三轮：**

| | 秒 | 对 jBCrypt 0.4 |
|---|---|---|
| jBCrypt 0.4 | 0.158、0.158、0.158 | 1.00 |
| Dawn JVM，`Long.compareUnsigned(i, len) >= 0` | 0.159、0.159、0.160 | 约 1.01，验收线 1.5 |
| Dawn JVM，两次有符号比较（`i < 0`，`i >= len`） | 0.160、0.160、0.159 | 约 1.01，与上一行无差别 |
| Dawn native，clang-20 -O2，无 LTO | 0.150、0.149、0.148 | 约 0.94，验收线 1.2 |
| Dawn native，gcc 13 -O2，无 LTO | 0.143、0.142、0.142 | 约 0.90 |

两处结论。一，**§5 留的二选一：两种 JVM 写法在噪声内相同，取单次无符号比较**（代码短一半，字节码里一个分支）；新增的显式长整比较没有可测的成本。
二，**`static inline` 本身追平了 LTO**：native 不开 LTO 就比 jBCrypt 快，§6.1 的升级梯子一步都没用上，§11 第 14 条（不开 LTO）保持。
这台机器上的 jBCrypt 是 0.158 s，比 K0 记的 0.19 s 快，所以验收线按比例（同机同轮）判：JVM 约 1.01 倍对 1.5 倍，native 约 0.9 倍对 1.2 倍；
绝对数 0.27 s 和 0.23 s 是参考机上的，这里更宽。bcrypt 的源码是 K0 的 `k0/bcrypt_buf.dawn` 把全局缓冲换成句柄实参，不入库（K4 会带真正的迁移），
六个已知 hash 向量在 JVM 上全过，native 输出 `true`。

**K2 没覆盖、留给后面的。**

- **整程序拆分后的跨翻译单元调用。** `std/mem` 的 `at`/`set` 是普通 Dawn 函数，包着内联的原语；bcrypt 这样的小程序是一个翻译单元，包装函数被 `cc` 一起内联。
  程序的函数体超过 `TU_BYTES`（1.5 MB，`emitc.dawn`）后会切成多个翻译单元，调用方与 `std/mem` 的包装不在同一个单元时，包装函数本身是一次外联调用，
  `static inline` 的好处在那一跳上丢掉。这一点**未量**；要不要让 emitc 把「只包一个原语」的 std 函数当内联形式，是 K3/K4 在 dawnop-site 规模上量过再裁的事。
- 含 `Mem` 证据参数的 bcrypt（K3 的 10% 线），`Mem` 效果与逃逸规则（K3），`to_bytes`/`from_bytes` 与 `F64Buf`（K5）。

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
| N11 | 泛型包装 `fn scope[T](f: fn() -> T !Mem) -> T = with_mem(f)` | R1（结果含类型变量） |
| N12 | 效果多态包装 `scope2[T, !e]` | R1（同上；行是否封闭无关） |
| N13 | `let w: fn(fn() -> I64Buf !Mem) -> I64Buf = mem.with_mem`，函数值路径 | R1（挂在函数名被当值用的地方） |
| N14 | `Option[T]` 与 `(Int, T)` 的泛型包装 | R1（变量藏在类型实参与元组里） |

### 9.2 K3 落地记录（2026-10-12）

基线 `origin/main` = 64298c6b 之上，分支 `lang/mem-k3`，三个提交：先效果（`std/mem` 声明 `Mem` 与 `with_mem`，十一个夹具在**没有任何规则**时录成黄金），
再规则（R1 到 R4，同一批夹具的黄金按预期变红），最后 Core 保序门与本记录。

**做了什么。**

- `std/mem`：`pub effect Mem { fn mem_alloc(n: Int) -> I64Buf }`；`with_mem` 的 handler 臂是 `i64buf_new(n)`；`new` 经 `mem_alloc` 走，`clone`/`from_list` 经 `new`；
  `at`/`set`/`fill`/`copy_from`/`copy_within`/`clone`/`from_list`/`to_list` 带 `!Mem`，`len` 纯。测试与 `scripts/mem-contract/probe.dawn` 全部包进 `with_mem`，
  探针输出对 K2 逐字节不变（JVM、native、ASan 三腿）。
- 规则落点（`check/types.dawn` 里 `is_mem_effect`/`eff_names_mem`/`buffer_reach`，调用点在 `checker.dawn` 与 `passes.dawn`）：按效果身份认，即 `std/mem` 里名为 `Mem` 的那一个，不看名字本身。
  R1 在 `check_call` 里 `ret` 算定之后（`s.name == "with_mem"` 且 `s.owner == Some("std/mem")`）；`buffer_reach` 穿过元组、列表/集合/映射/数组、不透明类型、
  用户 ADT 字段（带类型实参代换、带环保护）与函数类型的参数和结果，函数类型的行里有 `Mem` 也算。R2 在 `check_handle`，装 `Mem` 的 handler 的模块必须就是声明它的模块。
  R3 两处：`passes.dawn` 的效果操作签名（参数和结果；`std/mem` 自己的 `mem_alloc` 豁免，它就是分配的应答）与 `declare_cells` 的 `var` 类型。
  R4 在 `sam_snapshot`：带 `Mem` 标签的函数值过 SAM 转换点时拒绝；缓冲作 Java 实参本来就过不了重载解析（`I64Buf` 不是可编组类型），N9 的第二个函数把这一半钉住。
- `Mem` 在 `const` 与 comptime：已被既有机制拒绝（`i64buf_new` 是 comptime 拒绝名单上的原语），`mem_comptime` 夹具钉住两条路径的措辞。
- Core 保序：`scripts/mem-contract/order.dawn` 加 `run.sh` 第五步，`__lower --dump` 之后检查 `order` 函数里 `std/mem.at/set/at/at` 四次调用按序都在，再运行得 7。
  Core 仍无 DCE/CSE，所以这一步今天是对「现状」的钉子，将来有人加这两个 pass 时它先红。

**负控（先红后绿）。** 夹具 N1 到 N10 在第一个提交时录黄金：N1 到 N9 全部**编过**（N9 的 Java 参数那半本来就被重载解析拒绝，N10 报既有的未处理效果诊断），
即「规则关掉时夹具必须编过」；第二个提交后 N1 到 N5 各出 R1，N6 出 R2，N7 与 N8 出 R3，N9 的线程那半出 R4。`mem_ok_scopes` 在两个提交里黄金都是空的，钉住 §4.3 的允许形态。
N7 与 N8 与设计稿的表有一点不同：设计稿把「操作签名」与「`var` 存句柄」写在同一个夹具里，这里拆成两个文件，这样每条诊断只有一个出处。

**与设计稿的偏差和发现。**

1. **R2 的理由已过时，规则本身照写。** 已改写，见 §4.2：旧稿说闭包的行在创建点结算，但那是 effects-design §4.6 的旧语义，V1′ 之后用户 handler 之下的闭包行里仍有 `Mem`，R1 自己就会拒。
   R2 真正保的是另一件事：用户 handler 会剥掉读写上的 `Mem` 标记，让 `peek`/`poke` 以纯函数通过检查。
2. **R1 只看 `with_mem` 的调用点，用户包一层泛型就看不见。已堵（92c257d5，2026-10-13）。** `fn scope[T](f: fn() -> T !Mem) -> T = with_mem(f)` 的结果是类型变量 `T`，R1 在那里放行；
   调用 `scope(() => mem.new(4))` 时调用点不是 `with_mem`，缓冲就出来了。调研还发现同一缺口的另外两个入口：`Option[T]`/`(Int, T)` 这类变量藏在类型实参里的包装，
   以及把 `with_mem` 当函数值用（之后的调用是动态调用）。裁决取方案 A（保守拒）：`with_mem` 的结果类型含任何类型变量即拒，调用点与函数值路径各挂一处，夹具 N11 到 N14 见 §9.1。
   误杀面是不能写泛型的 `with_mem` 包装；仓内（std、packages、site、playground、examples）核过，没有这样的包装。
   通用解（方案 C）等第二个客户，见 §11 第 13 条。
3. **bcrypt 带 `Mem` 证据参数：native 越过 10% 线，JVM 没有。** 把 K0 的 bcrypt 改成句柄参数版（K2 版无标签，K3 版每个辅助函数 `!Mem`、`with_mem` 包住一次 `hash_with_salt`），
   同机同轮交错三轮，每轮 12 次取后 8 次中位数，cost 12 `checkpw`，秒：

   | | K2（无证据） | K3（`Mem` 证据） | 比值 |
   |---|---|---|---|
   | JVM | 0.1777、0.1788、0.1786 | 0.1777、0.1778、0.1786 | 1.00 |
   | native，cc -O2 | 0.1428、0.1426、0.1422 | 1.1159、1.1173、1.1247 | 约 7.8 |

   native 的原因看生成的 C 就清楚：证据是 owned 参数（Core 里 `ev v1 : ev$Mem owned`），每次 `at`/`set`/`get` 调用前 `dawn_dup(dawn_own[1])`，每个带证据的函数都开一个 `DAWN_OWN_FRAME`，
   热循环里每次访问多一次引用计数和一次帧登记，`static inline` 的 `at`/`set` 省下的东西被这一层吃回去还多。按 §10 问题 2 的明文，这就是触发「零操作标记效果」备用方案的情形
   （任一后端越线即触发）；K3 不实现它（要改解析器与新增一类消解形式，比 R1 到 R4 大），也没有借此改动 Core 或降级。`std` 里没有任何使用者，所以这个回退今天没有受害者；
   K4 迁移 bcrypt 之前必须先把这条解决。备选里还有一条设计稿没写的更小的路：让证据形参在 C 后端按借用传递（`c/infer` 的借用推断今天不覆盖 `ev` 形参），那只治 dup/drop，
   帧登记是否一并消失**未量**。

**没覆盖的。** `Mem` 与 `ctl` 效果的相互作用（挂起的续延持有句柄）只由 mem-contract 的 `dropped_line` 在运行时覆盖，没有对应的检查器夹具；
`F64Buf` 仍是 K5。

### 9.3 K5 落地记录（2026-10-14，PR #737）

两刀两个提交，一个 PR。基线 `origin/main` = 6376f3c8。

1. **刀 1：`F64Buf`。** 内置类型 `F64Buf`（`TyF64Buf`、头 `HF64Buf`、JVM `double[]`、native `dawn_f64buf *`），六个 std-only 原语
   `f64buf_new/len/at/set/fill/copy_from`（经 `RtMem`，comptime 一律拒绝），`std/mem` 的 `f64_new`、`f64_at`、`f64_set`、`f64_fill`、`f64_copy_from`、`f64_copy_within`、
   `f64_clone`、`f64_from_list`、`f64_to_list` 与 `impl Len[F64Buf]`。元素按 `double` 存取，不经算术，NaN 载荷与 `-0.0` 的位原样保留。
   panic 措辞是 I64Buf 的、类型名换成 `F64Buf`，两后端逐字一致。
2. **与 §7 的偏差：`Mem` 效果多了第二个操作 `mem_alloc_f64`。** 设计稿把 `mem_alloc` 写成 `Mem` 唯一的操作。`F64Buf` 若不走 `with_mem` 的 handler，
   就绕过了 R1 到 R4 全部规则，所以 `with_mem` 的 handler 现在答两个操作，用户 handler 因此必须也答两个（`mem_n06_user_handler` 用例随之改写）。
3. **JVM 实现：一份生成器两个家族。** `gen_mem_class` 里的六个原语改为 `gen_buf_ops(cw, kind)`，`BufKind` 只记名字、数组描述符与搬一个元素的操作码；
   检查逻辑只写一遍，`I64Buf` 与 `F64Buf` 不会各自漂移。
4. **刀 2：缓冲端点。** `to_bytes(b, width, order = Little)` / `from_bytes(bs, width, signed, order = Little)`（`I64Buf`），
   `f64_to_bytes(b, width, order = Little)` / `f64_from_bytes(bs, width, order = Little)`（`F64Buf`），四个 std-only 原语 `i64buf_pack`、`i64buf_unpack`、
   `f64buf_pack`、`f64buf_unpack`。**字节序依据：** 设计稿 §7 写明语义原样沿用批量线 §3，所以沿用 `Endian`，原语层与 `bytes_pack_int` 一样以 `little: Bool` 收
   （builtin 签名不能名用户类型），`Endian` 到 `Bool` 在 `std/mem` 里一处转换。宽度、环绕、符号扩展与两种 panic 措辞（`bytes.pack: width W is not ...`、
   `bytes.unpack: length L is not a multiple of W`）与批量线逐字相同，没有另造一套。JVM 沿用 `ByteBuffer` 设好字节序再逐元素读写，复用批量线的
   `int_width`、`float_width`、`unpack_count`；native 在宽度 8 且字节序等于本机时是一次 `memcpy`，其余走批量线的 `dawn_put_int`/`dawn_get_int`。
   结果一次分配、一次填满。
5. **验证。** `scripts/mem-contract` 扩到 `F64Buf`（值、位、panic、重叠拷贝）与端点：整数样本（宽度与符号边缘共 14 个值）在四种宽度、两种字节序下的
   24 行（`to_bytes` 十六进制与 `from_bytes` 数值）由独立的 Python 模型逐行核对，不是录自任何后端；`1M` 元素往返用 64 位线性同余生成的位型（`F64Buf` 侧含各种 NaN 载荷、次正规数、无穷），
   宽度 8 往返零差，宽度 4 的有符号与无符号和也由 Python 复算一致。同一份 `expected.txt` 由 JVM、native、ASan/LSan/UBSan 三路逐字节通过。
   `0x7FF8000000000001` 与 `-0.0` 的往返在 `expected.txt` 里按位核对。`scripts/rc-contract` 新增 `f64buf` 断言。
   **负控（各一个，手工施加，均已还原）：**

   | 变异体 | JVM 运行时 | C 运行时 |
   |---|---|---|
   | 字节序写反（打包时翻转 `little`，C 另翻转 `memcpy` 快路径条件） | 红，探针与 `expected.txt` 不符 | 红，同上 |
   | 宽度错一档（4 字节分支只写 2 字节） | 红 | 红 |
   | 符号扩展写成零扩展 | 红 | 红 |

6. **实测（1M 元素，七轮取中位，三个进程再取中位，参考机有其它任务；基准程序在临时目录，未入库）。**
   基线是同程序里 `list.map` 恒等拷贝一遍（批量线的口径）。

   | 项 | JVM | native（`cc` 13.3 `-O2`） | 通过线（1.5 倍 `List` 拷贝） |
   |---|---|---|---|
   | `List` 拷贝基线，Int | 33.2 ms | 56.2 ms | |
   | `List` 拷贝基线，Float | 26.5 ms | 41.7 ms | |
   | `pack_ints` + `unpack_ints`（`List` 路径） | 10.7 ms | 55.3 ms | |
   | `pack_floats` + `unpack_floats`（`List` 路径） | 6.5 ms | 37.0 ms | |
   | `to_bytes` + `from_bytes`（`I64Buf`，缓冲到缓冲） | 1.3 ms | 0.84 ms | <= 50 / 84 ms，过 |
   | `f64_to_bytes` + `f64_from_bytes`（`F64Buf`） | 1.3 ms | 3.3 ms | <= 40 / 63 ms，过 |
   | `List` 到缓冲到 `Bytes` 到缓冲到 `List`，Int（含 `from_list`/`to_list`） | 25.5 ms | 69.6 ms | <= 50 / 84 ms，过 |
   | 同上，Float | 14.2 ms | 53.6 ms | <= 40 / 63 ms，过 |

   缓冲到缓冲的往返比 `List` 路径快一个数量级以上（native 约 66 倍，JVM 约 8 倍），与 §7 的预期一致：预期「拆包落在 memcpy 量级」成立。
   **含 `List` 转换的端到端**在 native 上反而比纯 `List` 路径慢（69.6 对 55.3 ms，约 1.26 倍）：多出来的是 `from_list`/`to_list` 两个 Dawn 循环（见第 7 条）。
   JVM 各轮抖动大（`List` 路径吃 GC，单轮可差数倍），只当量级；native 三次之间差不到 3%。
   `f64` 的 native 往返（3.3 ms）比 `i64`（0.84 ms）慢约四倍：**已查（Q7 跟进，Q7 跟进），与类型无关。** 把两个往返的先后顺序对调，慢的跟着位置走（同一组里排第二的操作约 2 到 4 倍慢，不论 `I64Buf` 还是 `F64Buf`；`f64_from_bytes` 与 `from_bytes` 的 C 代码逐行同形，`f64buf_new` 与 `i64buf_new` 同为 `calloc`）。把 `calloc` 换成 `malloc`、调 `MALLOC_TOP_PAD_`/`MALLOC_TRIM_THRESHOLD_`/`MALLOC_MMAP_THRESHOLD_` 都不改变这个差，缺页总数也不变，所以不是 glibc 的归还策略。没有 `F64Buf` 特有的缺陷，也没有小修法，不改实现。
7. **待裁问题 7 的数字（`from_list`/`to_list` 的 Dawn 循环对批量线，不改实现，待协调者裁）。** 「批量线实现」指
   `to_list(b) = bytes.unpack_ints(to_bytes(b, 8), 8, true)`、`from_list(xs) = from_bytes(bytes.pack_ints(xs, 8), 8, true)`，即用现成的批量原语绕一圈：

   | 项 | JVM 循环 | JVM 批量 | native 循环 | native 批量 |
   |---|---|---|---|---|
   | `from_list`（1M Int） | 3.3 ms | 3.8 ms | 31.2 ms | 24.7 ms |
   | `to_list`（1M Int） | 20.2 ms | 7.1 ms | 38.2 ms | 27.1 ms |

   建议：`to_list` 改走批量路径（JVM 约 2.9 倍，native 约 1.4 倍，实现是一行）；`from_list` 不改（JVM 持平略慢，native 快 21% 但多一份 8 MB 中间 `Bytes`，
   且批量线的 `List` 到 `Array` 那一步本身就是逐元素的）。更彻底的做法是直接加 `i64buf_from_array`/`i64buf_to_array` 两个原语（预分配、一遍填满，
   K0 量到的 8.4 ms 对 29 ms 就是这个差），但那是新原语，不在 K5 范围，要不要做请裁。bcrypt 的 `from_list` 只调一次、1042 个字，这些都不影响它。
8. **输出变化。** 每个程序的 jar 都带 `dawn/rt/Mem`，它多了方法，所以 prev-diff 的 10 个 `emit *` 标签全变；另有 `doc --builtins` 与 `lsp`；
   fmt 零差。两个提交的信息里逐标签声明了 `Emit-Change(...)`。

## 10. 待裁问题与裁决

2026-10-09 协调者对本文七个待裁问题逐条裁决如下。已裁的写进正文，延后的写明重开条件。

1. **R1 到 R4 的落地：已裁，检查器专用特判，按 `Mem` 效果身份认。** `with_mem` 调用点做 R1，`with handle Mem` 的限制做 R2，R3、R4 同。
   **通用化的触发条件**（明文）：当出现**第二个**需要「作用域内、不可逃逸的句柄」的客户，预期是 `Gpu` 设备句柄，就把特判提升为通用机制
   （sealed 效果加局部类型标注），并**另写一篇设计文档**，那一篇才定语法与 spec 条文。现在不做：只有一个客户，抽象的形状没有第二个例子可对。
2. **证据参数备用方案的触发线：已裁，取紧线。** K3（含 `Mem` 证据参数）在同机同轮的 bcrypt cost 12 上比 K2（无证据）慢出 **10% 以上**，
   就打开「零操作标记效果」备用方案：允许零操作的效果，`with_mem` 成为检查器已知的消解形式，`Mem` 不产生证据参数，也不需要 `mem_alloc` 这个凑数的操作。
   这要改解析器（今天拒绝零操作效果）并新增一类消解形式，是比 R1 到 R4 更大的特性，所以只在这条线被越过时才开。JVM 与 native 各判一次，任一越线即触发。
   **回填（2026-10-13，提交 3a5ecf75）：触发线在 native 上被越过，但备用方案没有开，改走更小的修法。** 同机同轮测得 K3 形态（带证据）比 K2 形态（无证据）慢 6.3 倍，
   原因是 C 后端把效果证据形参一律当 owned：每次 `mem.at` 多一次 dup、一个 own-frame、一次 drop，三处都是出到运行时的调用，内联不掉。
   修法是让借用推断把证据形参和普通引用形参一样对待（表行为「形参、字典、证据」的次序），只动 C 后端的调用约定，不碰解析器、检查器、JVM 和证据 ABI。
   实测（Blowfish 型内核，3,000,000 次块加密，`cc -O2`，五次取中位数）：

   | 版本 | 改前 | 改后 |
   |---|---|---|
   | 无证据（K2 形态） | 0.112 s | 0.112 s（不受影响） |
   | 带证据（K3 形态） | 0.707 s（6.3 倍） | **0.112 s（1.00 倍）** |
   | 带证据，开 `-DDAWN_RT_INLINE_RC` | 0.380 s（3.4 倍） | 0.114 s（1.01 倍） |

   JVM 无差异（调研时测得，带证据 0.172 s，无证据 0.171 s，含 JVM 启动），所以两后端各判一次的结论是：JVM 未越线，native 越线且已被修法拉回 10% 线内。
   native 编译器自举编译自身的墙钟（三次）：不内联 RC 8.6 s 对 8.8 s，内联 RC 8.27 s 对 8.18 s，在噪声内。
   零操作标记效果因此降为二线备用方案；它动整个证据 ABI（`types.nev`、49 处 `eff_labels`、JVM 描述符），而这条线只需要 C 后端的借用。
   这个数字是 Blowfish 型内核上的，不是真 bcrypt cost 12；K4 迁移 bcrypt 后要在真实负载上复量，仍以 10% 线为准。
   钉住它的测试：`scripts/mem-contract/run.sh` 读生成的 C，要求缓冲访问函数里没有 dup、drop、own-frame，且带变异负控；
   `scripts/rc-mode-contract` 的 `ev_scan` 三个站点覆盖借用与必须保持 owned 的逃逸情形。
3. **`F64Buf` 的位置与函数命名：已裁，同模块 `std/mem`，`F64Buf` 是自己的类型，函数带 `f64_` 前缀。** 依据现有先例：`std/bytes` 同时有 `Bytes` 与 `Buf` 两个类型，
   先到先得的 `Bytes` 占短名（`len`、`at`），`Buf` 的函数带类型名前缀（`buf_at`、`size`），CONTRIBUTING §7 把这两个例外逐条记了。
   Dawn 没有重载，同模块里别无他法。`I64Buf` 先到，占短名（`at`、`set`）；`F64Buf` 用 `f64_at`、`f64_set` 等（见 §7）。
   备选的同级模块 `std/memf` 被否：它会把 `Mem` 效果拆到两个模块的依赖里，而 `with_mem` 只应有一个。例外的理由写进 `std/mem` 的模块头注，免得被当成惯例抄。
4. **范围写入越界：已裁，panic，绝不夹取。** 夹取一个写操作会把越界 bug 悄悄变成少写了几个字。已作为一句话补进 CONTRIBUTING §7 与它的中文译本（同提交，更新了译文摘要）。
   **给 K2 的备注（本刀不实现）：** 若强制 §7 准入测试的脚本需要对应规则（例如「名字里带 `fill`/`copy_from` 的写入范围函数不得走夹取实现」），在 K2 里补，
   此刻只记下，不动脚本。**K2 结果：仓库里没有强制 §7 准入测试的脚本**（`scripts/` 下没有按函数名检查夹取或判据的检查），所以没有可补的规则；
   `fill`/`copy_from` 不夹取这条由 `scripts/mem-contract` 与 `std/mem` 的 test 块的越界用例钉住（见 §9.1）。
5. **名字：已裁。** `with_mem` 不变。图形学行话 `blit` 废弃，区间拷贝取 Rust/Java 先例：`copy_from(dst, dst_at, src, src_at, n)`（目的在前，Rust `copy_from_slice` 同序）与 `copy_within(b, from, to_at, n)`；
   整份复制叫 `clone`，不叫 `copy`，使「写进已有缓冲」（`copy_*`）与「产出新缓冲」（`clone`）两簇不会混淆。理由见 §3.2。
6. **`MAX_LEN = 2^31 - 9`：已裁，两后端取同值，通过。** 取同值换取行为一致，代价是 native 拿不到 2^31 以上的缓冲，没有调用点要它。
7. **`from_list`/`to_list` 是否在 K5 改走批量线的 `array_extend`/`pvec.to_array`：延后到 K5。** 现在 Dawn 循环够 bcrypt（1042 个字，一次）用，没有实测理由先动；K5 量完再定。**K5 已量（PR #737，§9.3 第 6 条），已裁（2026-10-14，PR #738）：`to_list` 与 `f64_to_list` 改走批量线，`from_list` 不改。** `to_list(b) = bytes.unpack_ints(to_bytes(b, 8), 8, true)`，`f64_to_list` 同形用 `unpack_floats`；两后端结果逐字节不变（`scripts/mem-contract` 的 `to_bits` 行含 `-0.0` 与 NaN 载荷，期望文件未动）。1M 元素复测（同一份 jar 或二进制里对着旧循环，JVM 五个进程的中位数，native 三个进程）：`to_list` JVM 约 21 对 6.3 ms，native 37.2 对 24.2 ms；`f64_to_list` JVM 约 19 对 4 到 12 ms（受 GC 抖动，安静时 3.7 ms），native 26.3 对 18.1 ms。`from_list` 的数字不支持改（JVM 批量反而更慢，native 只省 6 ms 且多一份 8 MB 中间 `Bytes`），保持循环。

8. **R1 的泛型缺口：已裁，方案 A（2026-10-13）。** 结果类型含类型变量即拒，不靠枚举入口。落地记录见 §9.2 第 2 条（92c257d5）。
   方案 C（自动 trait `Unscoped`）的触发条件同问题 1：第二个客户（预期 `Gpu` 设备句柄）出现时另写设计稿。

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
15. **暂不加专用的 `i64buf_from_array`/`i64buf_to_array`（及 f64 版）原语**（问题 7 的裁决）：它更干净（预分配、一遍填满），但超出 K5，且没有真实调用点的吞吐需求；等有了再做。
13. **现在不做自动 trait `Unscoped`（方案 C），也不做签名上的作用域标记（方案 B）。** C 让 `with_mem` 声明 `T: Unscoped`，具体的 `T` 由 `buffer_reach` 判定，
    刚性的 `T` 必须自己声明同一约束，泛型包装于是可写；它是新的语言特性，只有一个客户时抽象的形状没有第二个例子可对，所以等 `Gpu` 成为第二个客户再另写设计稿，
    届时取代 R1 的保守拒。B 是手写的 rank-2 近似，跨模块导出、LSP、文档都要认，面大且仍是特判。把规则挂到「行里消掉 `Mem` 的任何调用点」（D）也不做：
    它要区分 `with_mem` 的减法与 handler 的减法，实现比 A 大，且看不到函数值的动态调用点。
