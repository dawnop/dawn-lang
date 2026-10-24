# std/math：一份源码、三端同位的宿主数学

> 状态：**current**。2026-10-24 的 K1 设计契约，依据 2026-10-21 的 std/math 裁决；
> K0 已随 [#873](https://github.com/dawnop/dawn-lang/pull/873) 合并，K1 随
> [#874](https://github.com/dawnop/dawn-lang/pull/874) 合并。K2 已在 `04ffe868` 实现；
> K3 的函数表已实现；K4 与 K3 同 PR 分提交交付。K5/K6 仍为后续要求。
> K2 的落地与验证见第四节末尾，K3 的修正分析见第五节末尾。

## 一、问题、依据与边界

基线是 `90f97aa2cdf0ab7ce2f6b93daf8be56da1f5e5b5`。此时 `std/float` 只有
`INFINITY`、`NAN`，没有 `std/math`。宿主数学散落在
`packages/tileinterp/src/math.dawn`、`packages/tileref/src/ref.dawn` 和
`std/narrow.dawn`；前两者服务的是 GPU 容差对拍，不能直接成为标准库的精度契约。

本设计采纳混合路线：六个精确运算做 internal intrinsic；位级函数用 Dawn 写在
`float_to_bits` / `float_of_bits` 上；超越函数移植 fdlibm，只留一份 Dawn 实现。
JVM、native C、wasm 以及 comptime 对同一输入产生相同结果，NaN 只比分类。
binary64 超越函数的误差上限是 **1 ulp**，不是现在就承诺正确舍入。

写者已完整阅读交接材料 `ruling-std-math-20261021.md`、
`research-std-math-20261021.md`、`std-math-k0-report-20261024.md`。
裁决优先于研究建议：研究稿给 `tanh` 留出的 2 ulp 例外不进入本契约。
研究稿的「逐位等于 StrictMath」也必须服从 1 ulp 上限，具体处理见第五节。
本文不沿用研究稿的单次耗时来承诺性能；K3/K4 要实测自身成本。

K0 已把 native、wasm 及 emitted C 测试配方的编译参数收为
`-ffp-contract=off`，并把 Float 的每次运算分别舍入写入规范。
其 aarch64 汇编契约检查真实发射结果，删除旗标的负控必须产生融合指令。
后续移植不得重排多项式、偷偷改成融合求值或打开 fast-math。
显式 `math.fma` 的单次舍入与普通 `a*b+c` 的两次舍入是两个各自明确的操作。

## 二、K1 的固定语料实测

### 方法与可复核材料

测量日为 2026-10-24，源码为上述基线，x86-64；JVM 是 GraalVM CE OpenJDK
21.0.2，native 用 clang 18.1.3、`-O2 -ffp-contract=off`，wasm 用 wasi-sdk 34
的 clang、同样关闭融合，以 Node 26.8.2 的 WASI preview1 执行。编译器由本树
`bin/dawn` 自举，显式 `--std` 指本树 std。native/wasm 编译的是同一份真实 emitted C，
连本树 runtime；这不是对完整 native driver 的额外验收，driver 由外部门禁验证。

探针直接调用包里的原函数，没有复制、改写算法。每轮先更新
`state = state * 16807 % 2147483647`，初值 `20261024`；
`u = to_float(state) / 2147483647.0`。按分别舍入的运算顺序生成
`exp` 的 `u*1400-700`、`sin` 的 `u*20-10`、`tanh` 的 `u*40-20`。
再更新一次取 `e = state % 2046 + 1`，再更新一次取尾数，
`log` 的输入位为 `(e << 52) | (state << 21)`。各组 20000 个，共 80000 行；
这不是全域证明，也未覆盖次正规结果、NaN、无穷或溢出。

每行输出函数名、输入位、tileinterp 结果位、tileref 结果位，位以有符号十进制 Int
打印。Java 对同一输入分别算 `Math`、`StrictMath`。MPFR 4.2.1 在 256 位精度下
向下、向上计算真值区间；两端转 binary64 最近偶数必须同位，才接受为正确舍入参考。
误差也用该区间向外界定，不把「距正确舍入结果的整数位距」冒充真实误差。

一次性脚本及所有原始输出留在本地证据目录
`~/workspace/gx-out/std-math-k1-measure-20261024/`：`prepare.py`、`run.sh`、
`analyze.py`、`Oracle.java`、`corpus.txt`、三端输出、`oracle.txt`、`summary.json`。
复跑命令为 `bash <证据目录>/run.sh`，再 `python3 <证据目录>/analyze.py`。
它们不进入仓库，K4 的永久门禁另按第六节建设。

输入语料（`函数名 空格 输入位 换行`，UTF-8）的 SHA-256 为
`10a18ab76571b6f334057df1cbc91797645966335102ce260146dd379becc9f1`。
三端完整输出逐字节相同，SHA-256 都为
`2f2c10f8498b4a153328892d27df7587799091f6f98d801269a37fcd4f0dee4a`。

### 结果与限制

下表每格是「与正确舍入结果的最大整数位距 / 真实误差上界（ulp，向上略取整）」；
单位依第五节定义。tileinterp/tileref 两列分别适用于三端，不能解读成 std/math 已通过。

| 输入组 | tileinterp，三端相同 | tileref，三端相同 | Java Math | Java StrictMath |
|---|---:|---:|---:|---:|
| exp，[-700,700] | 45356 / 45355.560 | 707 / 706.513 | 1 / 0.509 | 1 / 0.823 |
| sin，[-10,10] | 3 / 2.914 | 3 / 2.914 | 1 / 0.509 | 1 / 0.838 |
| log，正正规数，指数分层 | 19646 / 19645.765 | 2 / 2.178 | 0 / 0.500 | 1 / 0.596 |
| tanh，[-20,20] | 155643 / 155642.709 | 5 / 4.504 | 2 / 1.999 | 2 / 1.999 |

`exp` 的 tileinterp 正确舍入数为 7/20000，StrictMath 为 18018/20000。
tileinterp 最坏输入 `-0x1.5d09847e8e131p+9`，输出位 `71405552942727215`，
正确舍入位 `71405552942681859`。研究稿 §2.2 的 **44795 ulp** 是旧基线、
旧随机语料的历史最大值；原探针已删，不能声称精确复跑了那批输入。
本次得到 45356，两个数都表明不能把现有级数直接提升为 1 ulp 的标准库。
K5 必须保留本次见证，并用新实现重新量误差，不能只要求「低于 44795」。

本次 `sin` 两包同位为 19997/20000；研究稿报告旧语料 20000/20000。
新测量纠正了「今天总是完全相同」的说法，仍不能把高度同源的约化与级数当成独立参考。
K5 要保留 tileref 的独立算法，而不是追求两包逐位相等。

StrictMath 的 `tanh` 有 117/20000 个输入超过 1 ulp；最坏见证
`-0x1.da5766c3b4b00p-3`，返回位 `-4626005395199644422`，正确舍入位
`13820738678509907196`（后者为无符号打印），真实误差上界为 1.998162714 ulp。
这是 K3 必须解决的已知反例，不是可豁免的 gate 噪声。

研究稿 §2.1 的多库比较只能作为历史采样证据；本次也在 `exp` 上看到 Math 与
StrictMath 的正确舍入数不同。样本无法证明任何一库全域准确，单独一组全同也无法
证明跨平台契约。本文没有 aarch64 真机精度或吞吐测量，不声称已验证那些平台。

## 三、公开模块面与命名

全部函数纯、无效果；K2 必须同时支持运行期和 comptime。`Float` 是 binary64，
不增加新语法、重载或方法语法。以下 K2/K3 表面均已实现。

| 模块 | K2/K3 的公开成员与签名族 |
|---|---|
| `std/float`，K2 | 保留 `INFINITY NAN`；增加 `MAX MIN_POSITIVE EPSILON: Float`（`MIN_POSITIVE` 是最小正正规数）；`is_nan is_infinite is_finite is_subnormal sign_bit(Float) -> Bool`；`next_up next_down(Float) -> Float` |
| `std/math`，K2 | 常量 `PI E TAU LN_2 LN_10 LOG2_E LOG10_E SQRT_2: Float`；单参 `sqrt floor ceil trunc round round_even abs(Float) -> Float`；`fma(Float, Float, Float) -> Float`；`copysign min max next_after(Float, Float) -> Float`；`frexp(Float) -> (Float, Int)`；`ldexp(Float, Int) -> Float`；`ilogb(Float) -> Option[Int]` |
| `std/math`，K3 | 单参 `exp exp2 expm1 log log2 log10 log1p sin cos tan asin acos atan sinh cosh tanh cbrt(Float) -> Float`；双参 `pow hypot(Float, Float) -> Float`；`atan2(y: Float, x: Float) -> Float` |
| `std/math/f32`，K6 | 以 `narrow.F32` 为输入和输出的独立子模块，准入范围见第八节 |

`log` 为自然对数；`round_even` 是中点取偶数，`round` 是中点远离零；输出都是 Float，
不附带 Int 的饱和转换。`round` 先 `trunc(x)`，再用小数部分判断半值，并保留零的符号；
不能写成 `floor(x+0.5)`。非有限值原样按分类返回。

`min/max` 传播 NaN，零按 `-0 < +0` 选择，不等同于忽略 NaN 的 C `fmin/fmax`。
Float 没有 `Ord`，prelude 的泛型 `min/max` 不会替代这组模块限定函数。
`copysign(x,y)` 仅复制符号位；对 NaN 不增加 payload 保证。
`next_after(x,y)` 在数值相等时返回 y（含异号零），否则向 y 移一个可表示值；任一 NaN
返回 NaN。`next_up(-0)` 为最小正次正规数，`next_down(+0)` 为最小负次正规数，
向无穷继续走停在该无穷，向有限数走则离开无穷到最大有限数。

`frexp` 对非零有限数返回 `x=m*2^e` 且 `0.5 <= abs(m) < 1`，含次正规数；
零返回 `(x,0)`，无穷/NaN 返回 `(x,0)`。`ldexp` 对精确的 `x*2^e` 作一次最近偶数舍入，
含渐进下溢及带符号零；先按指数范围判定，不能令 `Int` 加法溢出，也不能分多次缩放造成双舍入。
`ilogb` 对非零有限数返回 `Some(floor(log2(abs(x))))`，零、无穷、NaN 返回 `None`，
不用 C 的平台相关哨兵整数。常量的位值由 MPFR 生成并固化，不能靠宿主字符串转换猜常量。

## 四、K2 intrinsic 与运行时模块所有权

共享声明的权威是 `selfhost/src/check/types.dawn` 的 `Rt`、`Intr`、`builtins()`、
`intrinsics()`，不是某个后端的 Java 类名表。背景见
[runtime-intrinsics-design.md](runtime-intrinsics-design.md)。六个新名字如下：

| internal 名字 | 参数 → 返回 | `rt` / `erased` / `internal` | JVM 后端本地实现 | native C / wasm 后端本地实现 |
|---|---|---|---|---|
| `float_sqrt` | Float → Float | `None / false / true` | `java.lang.Math.sqrt` | `sqrt` / `f64.sqrt` |
| `float_fma` | Float, Float, Float → Float | 同上 | `java.lang.Math.fma` | C `fma`；wasm 链 wasi-libc 软件 `fma` |
| `float_floor` | Float → Float | 同上 | `Math.floor` | `floor` / `f64.floor` |
| `float_ceil` | Float → Float | 同上 | `Math.ceil` | `ceil` / `f64.ceil` |
| `float_trunc` | Float → Float | 同上 | 按符号选 floor/ceil，保留 -0 | `trunc` / `f64.trunc` |
| `float_round_even` | Float → Float | 同上 | `Math.rint` | 最近偶数 `rint` / `f64.nearest` |

不增加 `RtMath`，不让 `Intr` 携带 `(class, method)` 或 C 符号。`rt=None` 表示后端自行
发射实现，不要求每端一定只有一条机器指令。C 头 `<math.h>` 与 `-lm` 已为 Float `%`
存在；wasm 没有核心标量 fma 指令，不能把 relaxed SIMD 的乘加或 `a*b+c` 当替身。
这些指令的定义见 [WebAssembly 数值语义](https://webassembly.github.io/spec/core/exec/numerics.html)。
C 的 `rint` 依赖最近偶数的宿主环境；Dawn 不提供切换舍入模式的 API，不承诺被外部 FFI
修改环境后的结果。若后端不能保证此环境，应发射固定最近偶数实现。

现有 `float_to_bits(Float)->Int`、`float_of_bits(Int)->Float` **继续由 `RtBytes` 所有**，
`erased=false, internal=true`；K2 只增加其 comptime 能力，不借数学线改所有权。
分类、相邻值、绝对值、拆指数不再各加 intrinsic。

K2 落点是 `check/types.dawn` 的签名和属性、JVM `jvm/emit.dawn` 的发射、
`c/emitc.dawn` 的 C 发射、`ir/interp.dawn` 的八个求值分支（六个新操作加位转换对），
以及现有 lower/函数值路径的覆盖。`intrinsics()` 由 `builtins()` 生成表，不能只添加一边。
std-only 拒绝、直接调用、取作函数值、运行期和 comptime 都要测试。

### 种子与 comptime 的闭环

当前解释器明确拒绝位转换对，注释说编译期尚不需要；K2 必须移除拒绝并实现，不能让
fdlibm 的 comptime 退回宿主 Math。解释器也不能调用同名 intrinsic 再递归到自己。
旧种子不认识六个新名字，因此 selfhost 源码不能在种子推进前直接调用它们。

K2 为解释器提供种子可编译的纯 Dawn 求值辅助：位转换用现有 `narrow.f64_bits` /
`f64_of_bits`；floor/ceil/trunc/nearest 走位拆解；sqrt 用整数有效数开方及余数判定；
fma 将乘积与加数对齐到显式 Int 分肢的精确累加器，再一次舍入，覆盖相消、次正规和溢出。
不得用 tileinterp 的 `fma_f64` 充当正确舍入兜底，它有已知极端指数双舍入缺口。
这部分是 K2 的验收工作，不能留下「先近似，推进种子后再修」的窗口。
推进种子后可以改为调用已支持的精确原语，但仍须验证相同语料与自举固定点。

同一组 raw-bit 输入要在 JVM 编译器、native 编译器各求 comptime 常量，再与三端运行期
比较。必须验实际常量产物；只让同一解释器算两次无法发现宿主依赖。

### K2 落地与验收（2026-10-24）

实现提交 `04ffe868ee15b243e69fc0f34baeef9d5d6d6be6`，只交付本节及第三节的 K2 表面。
`std/math` 已登记、内嵌；没有 fdlibm 源码、永久 `scripts/math-contract/`、tileinterp
迁移或 f32 入口。六个新原语的共享属性为 `None / false / true`，位转换对仍归 `RtBytes`。

`ir/float_eval.dawn` 是上一种子可编译的解释器辅助，不依赖新名字，也不调用 tile 包：

- sqrt 把正规化有效数扩成至多 106 位的整数被开方数，逐位恢复 53 位根和余数。
  半整数根的平方是 `q*q+q+1/4`，所以整数余数 `r>q` 恰好决定向上舍入，不存在漏判的中点。
  每轮的根、试减数和余数均在有符号 Int 范围内；次正规输入先正规化，输出不会次正规。
- fma 的整数累加器以 `2^-2148` 为二进制点、以 `2^26` 为分肢基数。163 肢覆盖有限
  binary64 乘积的全部 4196 位，乘积、加数均精确对齐，先比较绝对值再加减；分肢乘积
  与进位不会溢出 Int。相消后才定位最高位，按 53 位正规精度或 `2^-1074` 次正规单位
  用 guard/sticky 与奇偶位作一次舍入。零符号、无穷与非法乘加在入口单独处理。
- floor/ceil/trunc/nearest 先拆位清除小数，再决定是否增减一，保留负零。位转换用已获
  种子支持的 narrow 原语，不经字符串往返。

固定种子 20261024 的一次性验收探针共 21251 行，含每个指数层、边界值和 5147 组三参
fma。JVM 编译器与 native 编译器各自发射的 C 常量产物逐字节相同；实际 JVM、native、
wasm 执行与 Java 21 精确运算参考的完整输出摘要均为
`1433e19b7280c4e81408a0ec832b84b9b75b1588a30137eaaca15d23f3aeefd1`。
MPFR 4.2.1 的 256 位定向区间另独立决定全部 2684 个 sqrt 与 5147 个 fma 的 binary64 位；
八个公开数学常量也由定向区间两端舍入核对。NaN 统一按分类比较，不主张 payload。
这批有限语料是实现的验收证据，不是浮点全域的穷举证明。

可复跑材料在 `~/workspace/gx-out/std-math-k2-local-20261024/`，包括 `prepare.py`、
`Oracle.java`、原始语料、两种编译器的 C、三端输出及 `mpfr-probe.py`、`mpfr-constants.py`。
永久回归放在 std 内联测试、checker 属性/可见性测试及现有 native/wasm 语料中，覆盖
原语直接调用、函数值及其 comptime 求值；不提前建设 K4 的超越函数门。

三个独立副本负控均成功编译、执行退出 0，再由同一冻结位 oracle 判红：关闭 comptime
sqrt 的余数进位只改坏常量；把 emitted C 的 fma 换成乘后加，分别暴露相消、下溢和中间
溢出；把 round 换成 `floor(x+0.5)`，半值符号与相邻半值均失败。不能把前置编译失败算作负控。

## 五、K3 移植、许可证与精度契约

### 来源、移植顺序和许可保留

算法基线固定为 [Netlib fdlibm 5.3](https://netlib.org/fdlibm/readme)，
选择 IEEE core 的 `e_*`，不移植 errno、动态舍入、异常标志和平台 wrapper。
每个输入源文件在 K3 的来源清单中记 URL、版本注记、SHA-256、落地 Dawn 文件与修改理由。
K1 的 26 份 Netlib 原文快照保存在证据目录 `fdlibm-source/`，其 `manifest.json` 的
SHA-256 为 `d78c6cceb132528a60aef1a45cf9ba71dbdf9e7a8df17d7ff79262fc5494893c`；
不把远端可变 URL 当永久内容标识；
K3 提交源码时要把实际使用的逐文件摘要与来源清单一同入库。

| 顺序 | 源文件与依赖 | Dawn 移植要求 |
|---|---|---|
| 1 | `e_exp.c s_expm1.c e_log.c s_log1p.c e_log10.c` | 保留拆分常量、分支与求值次序，先建立 exp/log 族的 oracle 对拍 |
| 2 | `e_rem_pio2.c k_rem_pio2.c k_sin.c k_cos.c k_tan.c s_sin.c s_cos.c s_tan.c` | 连同 2/pi 表完整移植 Payne-Hanek 大参数约化，不能只保留 Cody-Waite 小参数路径 |
| 3 | `e_asin.c e_acos.c s_atan.c e_atan2.c` | 固化象限、端点和带符号零语义 |
| 4 | `e_sinh.c e_cosh.c s_tanh.c e_pow.c e_hypot.c s_cbrt.c` | 指数缩放、整数幂分类、避免中间溢出，并解决本节精度冲突 |
| 5 | exp2/log2 | fdlibm 5.3 无直接对应入口；用其约化内核与拆分的 log2(e)/ln(2) 补偿计算，逐函数独立 MPFR 验收 |

`exp2(x)=exp(x*LN_2)`、`log2(x)=log(x)/LN_2` 不能未经测量就入库。
exp2 在可表示的整数幂上必须精确，log2 在二的幂上必须精确，覆盖次正规幂。
具体补偿系数与误差分析随 K3 源码入库；达不到 1 ulp 就不能完成该入口。

fdlibm 的高低 32 位读写改成 64 位 raw-bit 操作；显式 `& 0xffffffff`、符号扩展与
逻辑移位重现原 32 位语义，不能让 Dawn 的 64 位 Int 溢出规则悄悄改变算法。
常量以原十六进制位为准；每个十进制拼写都由位断言核对。内部辅助源码留在
`std/math.dawn` 的私有函数，确需拆分时用 checker 已登记的 internal std 模块；不公开
Payne-Hanek 表或 kernel API。新增模块加入 `std/modules.txt`、内嵌生成配方及 API 差分。

许可证处理采用源文件随附的 Sun 许可通知，而不是把移植文件统称仓库原有许可证。
[e_exp.c](https://netlib.org/fdlibm/e_exp.c) 与
[s_tanh.c](https://netlib.org/fdlibm/s_tanh.c) 的通知年份和措辞不同，K3 必须逐文件保留
原 copyright 与 permission notice，在 Dawn 文件头用英文注释原样载入，并标出翻译和修改。
合并多个源文件时保留所有不同通知；来源清单列出映射。发布 std 源码和种子内嵌 std 时
也要核查这些通知随源码保留。K1 未复制算法，不提前加入空许可证文件。
OpenJDK 只充当可执行参考和规范来源，不复制 `FdLibm.java` 的源码或注释；若以后选择
其他来源，须先登记其具体许可证与来源，不能把 Netlib 通知套在别人的源码上。

### 结果的两层约束

第一层是同一 std 版本下的**同位约束**：每个非 NaN 结果在 JVM、native C、wasm 和
comptime 上 raw bits 相同，包含零的符号及无穷。NaN 不承诺符号、payload 或 signaling
状态，只要求分类一致。不能用绝对/相对容差掩盖后端位差。

第二层是**数学精度约束**：sqrt、fma、整数舍入、ldexp 正确舍入；位级函数精确；
所有列出的 binary64 超越函数及 hypot/cbrt/pow 误差不超过 1 ulp。
对非零有限真值 t，定义 `U(t)=2^(max(floor(log2(abs(t))), -1022)-52)`，
要求 `abs(result-t)/U(t) <= 1`；次正规区单位固定为 `2^-1074`。
真值恰为零时必须返回规定的带符号零；精确特殊值、溢出、定义域错误先按规则分类，
不能在 inf/NaN 上计算 ulp。表中的整数位距只是附加诊断，不能独立证明该上限。

MPFR 离线检查按 [MPFR 的定向舍入接口](https://www.mpfr.org/mpfr-current/mpfr.html#Rounding)
从 256 位递增精度构造真值区间；区间必须能决定 binary64 舍入、所在 binade 和误差是否越线。
不能确定时继续加精度，不能算通过。下溢区验证渐进舍入，必要时用 binary64 指数边界和
`mpfr_subnormalize`，不能只把精度设成 53 就当 binary64。

[Java 21 StrictMath 规范](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/StrictMath.html)
指定 fdlibm 5.3 的函数包括 `log10`；研究稿把它列为无对应/另实现的疑点不沿用。
未修改的 fdlibm 移植以 StrictMath 为逐位参考，MPFR 仍独立管精度。
`exp2/log2` 没有直接 StrictMath 入口，参考位由 MPFR 和选定 Dawn 算法的固定语料给出。

`tanh` 的已知越线使「所有函数严格等于 StrictMath」与本裁决无法同时满足。
K3 必须改进这一函数的补偿求值（例如 expm1 内核及最终除法的误差补偿），并提交
误差分析、困难点与 MPFR 证据；不能只给这 117 个抽样输入打补丁就宣布全域保证。
修改函数列入显式 oracle 差异清单：记录算法修正原因、StrictMath 原位、Dawn 目标位、
MPFR 区间证明；该函数用冻结的 Dawn 位语料验跨端，用 MPFR 验预算。
新发现其他函数越线也按同一流程修正，不能扩大 ulp 预算或静默跳过 StrictMath 对拍。
如果修正尚未完成，K3/K4 不满足完成条件。StrictMath 是参考预言机，不覆盖裁决。

### K3 落地、修正分析与证据（2026-10-24）

`std/math.dawn` 实现第三节的 20 个 K3 入口，内核全部私有，没有新增公开模块。
`scripts/math-contract/fdlibm/` 保留实际采用的 23 份 Netlib 文件和 5.3 readme；
`manifest.json` 逐文件记录 URL、版本、SHA-256、Dawn 落点及修改理由。
原文件中的约化、逼近误差分析仍可逐行审查。四种不同通知（含空行差异）全部保留在
Dawn 文件头；原始快照保留原字节。`provenance.py` 同时检查磁盘 std 与内嵌 std 中的通知。
所有非精确系数直接写 raw bits，不依赖十进制拼写。32 位有符号运算显式截断并符号扩展，
无符号运算显式掩码；高低字写入只改对应半字。Payne-Hanek 包含全部 66 个 24 位 2/pi
分肢和重算路径；工作区采用短的值列表，因此运行期与 comptime 执行同一份代码。

`oracle-differences.json` 是显式参考登记表：exp2/log2 没有 StrictMath 入口；
tanh、sinh、cosh、atan2 使用修正算法与 MPFR 冻结位。其他 14 个入口仍逐位对拍
Java 21.0.2 StrictMath。修正函数的原 StrictMath 位、Dawn 目标位、定向 MPFR 区间和
两者真实误差界都在该表中，没有跳过比较或逐输入的修补表。
扩展搜索发现原 sinh、cosh、atan2 也越过 1 ulp，故一起修正，未扩大预算。

**补偿运算的范围与舍入账。** 令 `u=2^-53`。two-sum 保留加法残差，Dekker 的
`2^27+1` 拆分保留乘法残差；双分量乘法加上两项交叉乘积和低分量乘积，除法用乘积
残差修正第一商。每个局部误差可保守界为 `32*u*u` 乘相应绝对操作数尺度。
各约化区间内最多 1024 个这样的操作，约化整数的绝对值最多 1026；下面的分支分别
使用其更紧的尺度。没有中间溢出；这些补偿路径最小非零主要操作数远大于正规下界。
低分量即使因精确相消变为零也不改变界。最终加回低分量才舍入为 binary64。
这些界用于 1 ulp 契约，没有声称所有结果正确舍入。

- **exp2**：先取最近整数 k，精确残差 `x-k` 再乘 MPFR 拆分的 ln(2)。在
  `|r|<=ln(2)/2` 上用 26 次 Taylor 多项式，余项
  `exp(|r|)*|r|^27/27! < 2^-132`；每个 `1/n!` 都按精确有理数拆成两分量。
  约化和 Horner 的保守相对误差小于 `2^-85`，远小于最终半 ulp 的余量。
  缩放到正规区精确；缩放到次正规区前的一次正常舍入最多贡献 1/4 个次正规单位，
  缩放的最后舍入最多 1/2 单位，总界小于 `0.75+2^-30` ulp。整数残差零时结果是
  精确的二次幂，包括全部次正规幂；-1075 的中点显式取零。
- **log2**：沿用 fdlibm 的正规化，使尾数落在 `[sqrt(1/2),sqrt(2)]` 附近。
  以补偿除法计算 `z=(m-1)/(m+1)`，`|z|<0.1716`；奇次 atanh 级数保留到
  `z^49/49`，余项小于 `2*|z|^51/(51*(1-z*z)) < 2^-133`。
  系数 `1/(2j+1)` 由精确有理数拆分，最后乘拆分的 log2(e)，再加整数指数。
  指数非零时没有严重相消；指数为零时误差随 `m-1` 缩放，相对误差小于 `2^-85`。
  所有二次幂在级数前返回精确整数。
- **tanh**：`|x|<2^-28` 直接返回 x，`|x-tanh(x)|<|x|^3/3`，小于 1/12 ulp；
  `|x|>=22` 返回带符号 1，遗漏量小于 `2*exp(-44)`，小于 1 的向下半间距。
  中间整段用补偿 exp(-2|x|) 和补偿的 `(1-e)/(1+e)`；k 的绝对值不超过 64。
  把上述局部误差及约化误差按绝对尺度累加，商的误差小于 `2^-85`；该段最小真值
  binade 的单位为 `2^-81`，因此最终舍入后的界小于 `0.5+1/16` ulp。
  困难点不是某 117 个采样输入，而是接近零的分子相消、expm1 误差被商放大，以及
  饱和边界附近向 1 舍入。全区间补偿同时处理这些条件，未对输入位查表。
- **sinh/cosh**：小值分支分别由 `sinh(x)-x` 的三次项和 `cosh(x)-1` 的二次项界定。
  中间段使用补偿的 `(exp(a) +/- 1/exp(a))/2`；靠近零的相消保留低分量，最小
  单位为 `2^-80`，补偿误差小于 `2^-85` 的对应绝对尺度。a>=22 时只算半 exp，
  在指数缩放之前除二，避免原先平方半 exp 的溢出和误差累积；被略去的项相对
  小于 `exp(-44)`，小于 0.001 ulp 的余量。连同最终舍入仍小于 1 ulp。
- **atan2**：保留 fdlibm 的零、无穷和 NaN 象限；有限非零输入先精确拆指数，以
  补偿除法求不大于 1 的幅值比。比值大于 1/2 时用 pi/4 恒等式，剩下的参数
  绝对值不超过 1/2。atan 奇次 Taylor 保留到 `z^121/121`，交错余项小于
  `|z|^123/123 < 2^-129`；补偿象限常数由 MPFR 的 pi 拆分。
  小角的误差随角缩放，其余角的绝对误差小于 `2^-85`，最终舍入后小于 1 ulp。
  指数差超过 60 时，忽略角量小于 `2^-59`，与 pi 的舍入误差之和仍小于 1 ulp；
  趋零的角使用一次普通除法保留渐进下溢。

**离线测量不是全域穷举。** 永久 `audit.py` 从 256 位开始递增精度，必须决定
binary64 舍入、真值 binade（或次正规共同单位）及误差预算；误差跨过 1 的区间继续加精度。
极小 exp 的 MPFR 自身下溢也使用向外的二进制有理界，不能把 MPFR 的指数范围当成真零。
`accuracy-audit.json` 固化每函数最坏见证、最大位距、向外误差界、工具版本、源码和
输入/输出摘要。扩展输入由 `gen.py --inputs-only INPUT --extra 12000` 重建，含 K1 的
20000 个 tanh 输入、失败输入的相邻 256 个位、每个 exp2 约化格、近 1 的巨大整数幂和
极端 hypot/atan2 比值。执行该输入后运行 `audit.py --inputs INPUT --actual OUTPUT --out REPORT`。
搜索规模、实测最大误差以该 JSON 为准；没有把抽样零失败写成全域证明。

### 特殊值必须成为语料

默认采用 fdlibm/StrictMath 的 IEEE core 特殊值规则；每个入口的 doc comment 和测试要
列齐自己的定义域、无穷、NaN 与零行为，不依赖宿主 errno。尤其固定：

| 情况 | 要求 |
|---|---|
| `sqrt(-0)`、`fma` 的精确零 | 保留 sqrt 的 -0；fma 按最近偶数的精确和定零符号，相消通常为 +0 |
| `sqrt(x<0)`、`log(x<0)`、`log(±0)` | 前两者 NaN；最后为 -inf |
| `exp(±0)`、`exp(-inf)`、`exp(+inf)` | 1、+0、+inf |
| `sin/tan(-0)`、`sinh/tanh(-0)` | -0；sin/cos/tan 的无穷输入为 NaN |
| `pow(x,±0)`、`pow(NaN,0)` | 1；但 `pow(±1,±inf)` 遵循 StrictMath 为 NaN，不笼统宣称全部等于 C Annex F |
| `pow(-0,y)`、负底数非整数幂 | 奇整数指数保留结果符号，负指数转对应无穷；负底数非整数幂为 NaN |
| `atan2(±0,+0)`、`atan2(±0,-0)` | ±0、±PI；四种无穷象限也逐位固定 |
| `hypot(inf,NaN)`、`cbrt(-0)` | +inf、-0 |
| `fma(0,inf,z)`、相反无穷相加 | NaN；中间乘积溢出而精确和有限的情况仍须单次舍入 |

版本内结果稳定；以后逐函数换成正确舍入算法允许改变具体位，但不得破坏精度和跨端契约。
变化记录 CHANGELOG；若移动仓库既有差分输出，实跑后按 CONTRIBUTING 的精确 label
写 `Emit-Change`，不预先加通配豁免。

## 六、K4 永久门禁：与 K3 同 PR、分提交

永久工具放 **`scripts/math-contract/`**，沿用
`scripts/narrow-contract/` 的生成检查、真实运行、变异负控三段结构。
K3 算法提交与 K4 门禁提交同 PR 交付，不能让新数学面在没有三端门的状态下合并。

1. **可重建语料**：`gen.py --check` 调用固定版本 Java 的 StrictMath 生成参考位，
   对照已提交的输入与输出摘要，禁止手改 expect。exp2/log2 和精度修正函数的 MPFR 语料
   单列来源，不伪装成 StrictMath 输出。固定 PRNG、种子、输入 raw bits、生成器版本与
   oracle 版本；语料按函数及边界命名，包含第二节的见证。
2. **三端真实执行**：同一 Dawn corpus 分别编译为 JVM、native C、wasm，比较 raw bits
   与参考；native 另跑 ASan 变体。wasm 实际链接并执行软件 fma，不以 native 结果代跑。
   覆盖 direct-call 和 function-value。K0 的无融合契约继续由原门禁守住。
3. **编译期执行**：由 JVM/native 两种编译器生成同一组 comptime 常量，在三端程序中
   输出并对拍；含位转换、六原语和 fdlibm 族，不能只测成功编译。
4. **MPFR 精度审计**：离线脚本常驻该目录，输出逐函数最大误差、最大位距、输入及输出位、
   最坏见证和工具版本。发布新算法前必须运行并归档，CI 无 MPFR 时消费已提交的冻结见证，
   不能宣称有限 CI corpus 证明全域 1 ulp。移植还要保留源误差分析；新修正附分析与扩展搜索。
5. **负控**：独立副本删除 exp 多项式一项，必须让 exp 段红；改 rem_pio2 拆分常数，必须
   让三角大参数段红；将 round 改为 floor(x+0.5)，必须让舍入边界段红。变异体须能编译且
   执行到指定比较，不能以编译失败、超时或无关崩溃计作成功杀死。

语料至少覆盖：两种零、NaN/无穷、最小/最大次正规数与相邻正规数、最大有限数；
半整数和 `0.49999999999999994`；sqrt 中点、fma 的精确相消及宽指数差；
exp 溢出/下溢边界、log 在 1 附近和所有指数层；三角在 k*pi/2 邻域及巨大有限参数；
pow 在 -1/0/1 邻域、巨大奇偶整数指数与定义域外；hypot 极端尺度差。
固定随机样本补充这些构造边界，不能替代它们。

K4 接入现有 native-diff/wasm 对应门片，复用已有工具链与 ASan runtime，不新造一条未覆盖
的旁路。CI wiring、`scripts/gates-external/steps.lock.json` 与 gate coverage map 一同更新。
先测冷运行及新增墙钟，再按 Gate-Budget 规则容纳，本文不预报秒数或承诺预算不变。
新增公开 std 面同时跑 `scripts/api-diff.py` 与 run-diff；自举固定点、prev-diff、
native CLI、wasm 和完整外部门禁仍需通过。不能只跑新 math gate 就声明 K3/K4 完成。

## 七、K5：tileinterp 迁移与参考独立性

K5 以前置 **K3/K4 全部通过** 为准。按职责迁移，不按旧研究稿的行数机械删除：

| 当前内容 | K5 去向 |
|---|---|
| INF/NAN、分类、相邻值、拆指数和缩放 | 改用 std/float 与 std/math；调用者不再维护副本 |
| `sqrt_rn`、`fma_f64`、floor/ceil | 用 math.sqrt/fma/floor/ceil；rem 用已有 Float `%` |
| exp/exp2/log/log2、三角/反三角、双曲、pow | 用 std/math；rsqrt 在包内组合 `1/math.sqrt`，不新增近似宿主入口 |
| split/two_prod | 普通乘积误差可用 fma，但须保留/重审极端范围保护，不能假定下溢时残差一定可表示 |
| `Dir`、directed/add_dir/mul_dir/div_dir | 留在 tileinterp，内部可复用精确 math.fma |
| flush、signed_zero、round-to-odd、窄格式舍入适配 | 留在 tileinterp；ftz 和定向舍入不是 std/math 的参数 |

第二节的新 exp 见证与研究的 44795 ulp 缺口必须在迁移报告中对照新 std/math 结果：
三端同位且真误差 <=1 ulp。迁移既要删掉旧宿主算法，也要重跑 GPU 容差语料；
不能把「误差改善」当作设备答案不变的证据。重新录制 tileinterp-diff 判词并解释每项变化，
重跑 leetgpu-diff、受影响的 tile-golden/device 台账和变异负控，按现有台账流程记录。

tileref 保留 `ref_exp/ref_log/ref_sin/...` 的独立级数，不能导入 std/math 的超越函数，
也不能让共享辅助函数间接调用它们。可把 `ref_sqrt`、`ref_remf` 换成精确原语与 `%`，
因为精确运算只有一个数学答案。`scripts/leetgpu-diff/check.py` 在既有不依赖 tileir 检查旁
增加依赖检查：识别模块别名、选择性导入和本地转发，不能只 grep `math.sin`；
带「别名导入并转发 exp」的负控必须红。算法独立性还需源码审查，不能声称一次文本扫描
能证明整个依赖闭包没有抄算法。

`std/narrow` 的 `sqrt_binary` 可在 K5 改用正确舍入 sqrt 再作目标格式舍入；先用现有
narrow-contract 的全语料和困难边界证明位不变，补齐双舍入条件，达不到就保留整数开方。
这不是把任意超越函数「先 Float 后舍入」当成设备语义的许可。

## 八、K6：f32 按需，正确舍入另行验收

K6 不阻塞 K2 至 K5；目标路径 `std/math/f32`，输入输出为 `narrow.F32`，同名靠模块区分。
先做单参函数，目标是 binary32 最近偶数**正确舍入**，不是把 binary64 的 1 ulp
误差口头换算为 f32 正确舍入。调用 binary64 fdlibm 再 `round_f32` 仅是候选算法，
会有双舍入困难点，只有验证后才可发布。

每个获准的单参函数离线遍历全部 `2^32` 输入位模式；对非 NaN 输入以 MPFR 自适应区间
决定正确的 binary32 舍入位，对 NaN 只比分类。记录覆盖区间、计数、分片摘要、oracle 与
编译工具版本、最坏/困难输入及例外处理；证明分片无缺口无重叠，保留可重跑脚本于
`scripts/math-contract/` 的 f32 子目录。修正困难点后再全量验证，三端运行验证同一算法，
抽样 CI 与困难点回归不能替代穷举。此处没有穷举耗时测量，不承诺完成天数。

第一批可以从 `sqrt exp exp2 expm1 log log2 log10 log1p sin cos tan asin acos atan
sinh cosh tanh cbrt` 按需求逐个准入；没有对应证据的函数不公开。
双参 `pow atan2 hypot` 和三参 `fma` 不能靠单参穷举证据过关，K6 首批不纳入；
以后另立多参正确舍入证明和门禁，不静默降成 1 ulp。
bf16/f16/f8/f4 的设备超越函数、ftz、approx、定向舍入仍归 tileir 一侧。

## 九、交付次序与完成判据

| 刀 | 前置 | 可审查的完成结果 |
|---|---|---|
| K0，已合并 | 无 | #873：禁融合、aarch64 汇编契约及删除旗标的负控 |
| K1，已合并 | 裁决、K0 报告 | #874：本文、固定语料证据、文档索引；无行为变化 |
| K2，已实现 | K1 | `04ffe868`：六 intrinsic、位转换 comptime、std/float 扩充、std/math 精确面；种子可编译、两种编译器的常量及运行期同位 |
| K3 + K4 | K0、K2 | fdlibm 全表与许可来源；tanh/exp2/log2 等逐函数精度证据；同 PR 的永久三端契约与变异负控全部通过 |
| K5 | K3/K4 | tileinterp 迁移、tileref 独立性检查、narrow sqrt 的等价证据、容差判词与受影响设备台账重验 |
| K6 | K3/K4，按需求排 | 逐函数 f32 正确舍入、完整穷举及困难点证据，不夹带设备语义 |

K2 至 K6 实现时回填本文状态与落地提交，不能让完成表只存在于交接目录。
如精度反例推翻移植方案，先修正算法与证据再合并，不把实现缺口写成已履行的契约。

## 不做的（理由）

- **超越函数委托各端 libm/Math**：第二节的采样已经显示参考位会因实现变化；
  comptime 还会把编译器宿主差异固化为常量。三端必须执行同一份 Dawn 源码。
- **JVM 调 StrictMath、C 再带另一份 fdlibm**：重复维护不能保证同步；StrictMath 也有本次
  实测的 tanh 越线。它是 oracle，不是可绕开精度审计的运行时归属。
- **现在承诺 binary64 全部正确舍入**：裁决把它排在后续，需要分肢/宽乘和逐函数证明；
  K3 的 1 ulp 与跨端契约先独立兑现，不能提前宣称 CORE-MATH 等级。
- **原样提升 tileinterp/tileref 级数**：历史 exp 44795 ulp 与本次 45356 位距都不满足目标；
  sin 的同源性还削弱独立对拍的判别力。
- **给 tanh 放宽到 2 ulp**：与裁决冲突；发现反例要求修实现，不是改预算或删除样本。
- **GPU 的 ftz、approx、定向舍入和窄格式超越函数进 std/math**：它们描述设备/方言的答案，
  归 tileir、tileinterp、tileref，不能混入宿主纯函数契约。
- **动态舍入模式、异常标志、fast-math**：引入隐藏状态或改变普通运算舍入，破坏纯函数与同位约束。
- **重载、Float trait、方法语法**：模块限定名已能区分 f32/f64，不改语言命名和调用规则。
- **gamma、bessel、erf 等特殊函数首批入库**：裁决未列入第一批，有宿主需求再立精度与来源契约。
- **NaN payload 承诺**：沿用 std/float 的现有边界；NaN 比分类，零和无穷仍必须逐位比较。
- **K1 修改运行时或提前接入半成品 gate**：本刀先固定可执行的设计；一次性实测留证据目录，
  永久 `scripts/math-contract/` 随 K3/K4 的实际算法一起交付。
