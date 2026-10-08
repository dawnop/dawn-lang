# 数组/列表与 Bytes 的批量转换：一族契约原语（U3d 通用化，K1）

> 状态：**proposed**。2026-10-08 写成。基线 `origin/main` = a3d45a59。
> 调研报告：维护者工作区 `research-bulk-array-bytes-20261008.md`（含全部 `file:line` 与网页出处，本文只留结论）；裁决：同目录 `ruling-bulk-array-bytes-20261008.md`。
> 维护者指示（逐字）：「既然做了，那就做个通用的呗，对于这种数组类型的，要有统一的解决方案，不要再走逐元素拷贝了」。
> 本文取代 `gpu-typed-transfer-design.md` 里 U3d 的原范围（该文 §3.5、§7、§8 开放问题 4 已指向本文）。
> 没量过的数字写「未量」并写明由哪一刀去量；所有性能断言的出处都在 §1.3。

## 1. 问题与现状

### 1.1 用户面是 `List[T]`，原语层是 `Array[T]`

`List` 是 `std/pvec` 的 32 叉 trie，叶子是 `Array`；`Array[T]` 只有 std 能命名。所以统一方案必须同时管两层：`List` 到 `Array` 今天就是逐元素（`std/pvec.dawn` 的 `to_array`/`from_array`/`arr_slice`），`Array` 到 `Bytes` 又是逐元素。

### 1.2 两个后端的 `Array[Int]`/`Array[Float]` 都是装箱的

JVM 是 `Object[]` 里放 `Long`/`Double`；native 是 `void*` 槽指向 `dawn_box`。所以「一次 memcpy」在今天的表示下不存在：任何 `Array[Float]` 到 `Bytes` 的转换都至少读一遍每个元素的箱。

**本方案（A+）在运行时循环里仍然遍历装箱元素。** 它能消除的是 Dawn 源码里每字节一次 `Buf.put`、每元素一次闭包、每元素一次 RC 往返和中间分配；它不能消除「读箱」这一遍。只有平铺（无装箱）存储才能消除，那是选项 B，现在不做（§7）。

### 1.3 逐元素转换点与已有测量

完整清单（16 处批量类、6 处标量类、算法类说明）见调研报告 §2，这里只列要改的主要位置：`std/gpu.dawn` 的 11 对 `pack_*`/`unpack_*` 及 `to_array`/`of_array`；`dawn_gpu_upload_host`/`dawn_gpu_download_host`（`runtime/c/dawn_rt.c`）；`bytes_from_array`（JVM `rtclasses.dawn`，C `dawn_rt.c`）；`std/bytes.dawn` 的 `settle`/`freeze`/`put_bytes`；`std/pvec.dawn` 的 `to_array`/`from_array`/`arr_slice`。

测量出处（性能断言只引这些）：

| 数字 | 出处 |
|---|---|
| 1M f64：Dawn 侧 `Buf.put` 逐字节编码 JVM 123 ms、native 279 ms；`List` 拷贝基线 JVM 36 ms、native 64 ms | 维护者实测，记在调研报告 §5.2 |
| JVM 上 `pack_i64` 187 ms，`unpack_i64` 300+ ms，`pack_i32` 87 ms | `gpu-typed-transfer-design.md` §3.5 |
| JVM 装箱数组的运行时紧循环（读箱 + `ByteBuffer.putLong`）1M 元素：第 1 轮 11.1 ms，第 5 轮 1.8 ms；原生 `double[]` 批量 6.0 / 1.0 ms；噪声大，只当量级 | 调研报告 §2.4 |
| native C 紧循环（K0，链接真实 `runtime/c/dawn_rt.c`，clang-20 -O2 同 `native-selfhost-tests.sh`，1M 元素，5 取最好；机器负载 3.5 到 6，抖动 20% 到 30%，只当量级；bench 源在临时目录，未入库）：memcpy 8 MB 0.2 到 0.3 ms；`dawn_array` 经 `push_own`+`dup` 拷贝 21 到 30 ms（`List` 拷贝下界）；pack f64 小端/大端 1.5 / 1.0 ms（乱序箱 1.6 ms，故读箱缓存未命中不是瓶颈，bswap 免费），i64 1.5 / 1.3 ms，i32 1.0 / 1.0 ms；unpack 逐元素 `push_own`：f64 29 到 31 ms，i64 37 ms，i32 29 到 30 ms；unpack 写入预分配缓冲一次填满：8.4 ms；单独分配 1M 个 `dawn_box_float` 6.2 ms；Dawn 侧逐字节 `Buf.put` 编码复测 292 到 341 ms | 本次 K0 实测 |
| 真实 pvec `list.map` 一遍（Dawn 程序内） | 58 到 90 ms，本次 K0 实测 |
| 真实 pvec `List` 与 `Array` 互转的占比（报告 §4.5） | **未量** |
| JVM 紧循环 | **未量** |

K0 的结论（native）：

- pack 在 native 上有约 20 倍余量（1.0 到 1.5 ms 对 30 ms 目标）。读箱、字节序都不是成本。
- unpack 的 29 ms 里约 70% 是 `push_own` 每元素新分配数组头并释放旧头，分配 1M 个浮点箱本身只要 6.2 ms。逐元素 `push_own` 恰好压在 30 ms 目标线上，没有余量。
- 因此 unpack 的实现**必须**经运行时内部的预分配入口（形如 `dawn_array_from_boxes(n)` 的内部辅助；`dawn_array_buf_new` 现在在 `dawn_rt.c` 里是 `static`，需要对内开放），一次分配、一次填满，实测 8.4 ms；**不得**写成 `push_own` 循环。
- 逐字节 `Buf.put` 编码在 native 上复测 292 到 341 ms，与 §1.3 第一行的 279 ms 同量级，pack 的收益约两个数量级。

## 2. 方案：一族契约原语

契约增量共 6 条，全部 std-only（`internal`）。契约层不引入 ADT：字节序用 `little: Bool`，符号性用 `signed: Bool`。

| 原语 | 签名 | Rt |
|---|---|---|
| `bytes_pack_int` | `(a: Array[Int], width: Int, little: Bool) -> Bytes` | RtBytes |
| `bytes_unpack_int` | `(b: Bytes, width: Int, signed: Bool, little: Bool) -> Array[Int]` | RtBytes |
| `bytes_pack_float` | `(a: Array[Float], width: Int, little: Bool) -> Bytes` | RtBytes |
| `bytes_unpack_float` | `(b: Bytes, width: Int, little: Bool) -> Array[Float]` | RtBytes |
| `array_extend` | `(a: Array[T], b: Array[T]) -> Array[T]`，批量追加 `b` 的全部元素（erased） | RtArray |
| `array_slice` | `(a: Array[T], from: Int, to: Int) -> Array[T]`，区间拷贝（erased，夹取规则同 `bytes_slice`） | RtArray |

- `Int` 与 `Float` 分两族：元素箱类型不同（`Long` 与 `Double`；`dawn_box.val.i` 与 `.val.f`），拆成两个原语比运行时再分派更快、更好验证。不用 `kind` 枚举参数（§8）。
- **`bytes_from_array` 并入**：`bytes_from_array(a)` 等于 `bytes_pack_int(a, 1, true)`，删除旧原语（类型表、镜像、JVM、C、头文件、6 处调用点）。
- **`array_extend`/`array_slice`** 是所有 `Array` 逐元素拷贝的统一替代：`pvec.to_array` 改为逐叶子 `array_extend`，`pvec.arr_slice` 直接 `array_slice`。JVM 是 `System.arraycopy`；native 是一遍 dup 引用的循环（RC 仍逐元素 dup，但没有分配、没有闭包）。
- **GPU**：`gpu_upload_host`/`gpu_download_host` 连同 C、wasi 桩、JVM 桩、头文件、镜像一并删除。真设备 handler 不再有 f64 分支，f64/i64 直走 `bytes.pack_floats`/`bytes.pack_ints`；11 对 `pack_*`/`unpack_*` 收成「舍入后位型 `List[Int]` + `pack_ints(bits, width)`」，非舍入格式整格式批量。
- **std/bytes 公开面**（名字待命名评审）：`type Endian = Little | Big`；`pack_ints(xs: List[Int], width: Int, order: Endian = Little) -> Bytes`、`unpack_ints(b, width, signed, order = Little) -> List[Int]`、`pack_floats(xs: List[Float], width, order = Little)`、`unpack_floats(b, width, order = Little)`。内部是 `pvec.to_array` + 原语 + `pvec.from_array`。

## 3. 语义（合约，两后端逐字一致）

1. **字节序**：显式参数，默认 `Little`。没有「原生序」选项（两后端原生序可能不同，而语言要求逐字节一致）。
2. **整数宽度** `width in {1, 2, 4, 8}`。打包取每个元素的低 `8*width` 位，环绕截断，没有范围错误。拆包由 `signed` 决定符号扩展或零扩展；`width = 8` 时两者相同。
3. **浮点宽度** `4 | 8`。f64 位保真：NaN 载荷与符号、`-0.0` 原样进出（JVM `Double.doubleToRawLongBits`/`longBitsToDouble`，C `memcpy` 到 `uint64_t`）。f32 是 `double` 到 `float` 的 IEEE 就近偶数舍入，NaN 载荷不承诺保留；f32 拆包是精确的 `float` 到 `double`。
4. **长度**：打包结果长度 `n * width`。拆包时 `len(bytes) % width != 0` 一律 panic，消息逐字进合约（如 `bytes.unpack: length 7 is not a multiple of 4`）。今天 `unpack_i32` 等静默 `/ 4` 丢尾巴，那是 bug 级行为，直接改。
5. **非法宽度**：panic，文案进合约。
6. **空输入**：空数组得空 `Bytes`，空 `Bytes` 得空数组。
7. **所有权/RC**：打包只借用元素，不 dup；拆包产生新箱，由结果数组拥有。`array_extend` 对每个元素 dup，是新的 RC 站点。

## 4. 实现要点

- **JVM**：`rtclasses.dawn` 里手写 ASM。六个原语各写一份约 400 行，不可接受；先写**一个循环骨架生成函数**（参数是读箱指令序列与按宽度写字节的指令序列），把量压到约 200 行；K3 先做骨架，K4 复用。字节侧用 ByteBuffer/VarHandle。退路：宽度当循环内 `switch`，换约 15% 吞吐。
- **native**：`runtime/c/dawn_rt.c` 六个函数，约 150 行，纯 C（wasi 也可用，无需桩）。存储允许处用 memcpy 与字节交换；读箱用借用指针。
- **契约表**：`types.dawn` 声明、`rt_of`/`internal` 循环、`erased` 集合加入 `array_extend`/`array_slice`（K2 要确认），`builtins.dawn` 镜像，`dawn doc --builtins` 对账。
- **与 U3b1 的关系**：U3b1（`Float`↔`Int` 原始位型 intrinsic）与 `bytes_pack_float(width=8)` 有重叠但独立：前者给逐元素位型（`std/dtype` 里要，标量与常量仍有价值），后者是批量字节装配。

## 5. 边界（诚实声明）

- bf16/f16/tf32/f8 的舍入是逐元素算术（`narrow.round_*`），仍在 Dawn 里逐元素算位型，之后的「位型到字节」一步批量。
- `DeviceBits` 路径上 `List[I32]`/`List[BF16]` 等不透明元素到 `List[Int]`/`List[Float]`：**裁决取 (a)**，接受一次 `list.map`，不做恒等表示转换；K0 已量：native 真实 pvec `list.map` 58 到 90 ms，大约是 pack 原语（约 1.5 ms）的数十倍，换言之该路径的成本主要在 `list.map` 与 `List` 互转，不在原语；真实 `List` 与 `Array` 互转占比和 JVM 紧循环尚未量，量完再决定是否重评恒等表示转换。`Float`/`Int`（f64/i64）路径不经此。
- `Buf.put_bytes` 的非对齐路径靠 K6 解决；`bytes_from_array` 在 `freeze` 中仍读一遍不超过 4096 个的尾部箱，但走同一原语。

## 6. 验收与刀序

验收（参考机；基线是 §1.3 的 `List` 拷贝）：

| 指标 | 通过线 | 目标 |
|---|---|---|
| 1M f64 `pack_floats`/`unpack_floats`，端到端含 `List` 到 `Array` | 各后端 <= 1.5 倍该后端 `List` 拷贝基线（JVM <= 54 ms，native <= 96 ms） | JVM <= 15 ms，native <= 30 ms |
| `Array[Float]` 层（原语本身） | 与 `array_extend` 同一量级 | JVM、native 各 <= 10 ms |
| `pack_i64`/`unpack_i64` | 比今天的 187 / 300+ ms（JVM）低一个数量级 | |
| 位保真 | `0x7FF8000000000001`、`-0.0`、NaN 符号位往返，两后端逐字节一致 | |

刀序（每刀一个 PR、一个主题、每刀一个提交）：

| 刀 | 内容 | 破坏 | 负控 |
|---|---|---|---|
| K0 | 只量：native 1M f64 的 C 紧循环、`List` 拷贝、`list.map` 一遍（native 已量，见 §1.3；真实 pvec 互转占比与 JVM 紧循环待量）；填 `gpu-typed-transfer-design.md` 开放问题 4 | 否 | 无 |
| K1 | 本文 | 否 | 无 |
| K2 | `array_extend`/`array_slice` + `pvec` 三处改用 + `scripts/array-contract` 两条断言 | 否 | 区间右端开闭错一位，合约红；native `array_extend` 漏一次 dup，ASan 门红 |
| K3 | 整数族 + 骨架生成函数 + 删 `bytes_from_array`（6 处）+ 合约 `scripts/bytes-pack-contract`（两后端同一 `.expect`） | 是 | 字节序写反（非对称值）；宽度错一档；符号扩展写成零扩展（`0x80`）；截断改饱和（`300`） |
| K4 | 浮点族 + std/bytes `Endian` 与公开面 | 否 | JVM 换 `doubleToLongBits`（规范化 NaN），载荷用例红；native 经 `double` 算术而非 `memcpy`，同样红 |
| K5 | GPU 重写（与 U3c 合并或紧随）：删 `gpu_*_host` 与桩、镜像，11 对收成位型 + `pack_ints` | 是 | `unpack_i32` 符号扩展改零扩展，`dtype_diff` 红；f64 改规范化 NaN，红 |
| K6 | `Buf.put_bytes` 非对齐路径用 `bytes_unpack_int(width=1)` 批量进尾部 | 否 | 非对齐拷贝错位一字节，合约红 |
| K7（条件） | 标量 `bytes_get_int`/`bytes_get_float`，改 sha256 `word`、tileir `put_le`、binfo | 否 | 大端写成小端，sha2 红 |

K2 与 K3 可并行。破坏性刀（K3、K5）用 `Emit-Change(<label>)` 声明，label 逐字取自 `scripts/emit-labels.txt`。门禁覆盖用 `scripts/gate-map/gatemap.py` 查。本方案不改 workflows；`bytes-pack-contract` 若挂进 CI 须按 Gate-Budget 声明。

## 7. 选项 B 与 C 的处置

- **B（平铺无装箱数值数组）现在不做。** 重开条件：迭代协议 K1（RC 往返）落地后，若 GPU 上传或 `listf` 在实测中仍是体感瓶颈，或出现第二个 `Array[Float]`/`Array[Int]` 真实热路径。重开时 A+ 的签名与 std 公开面不变，实现从读箱换成 memcpy（JVM `asDoubleBuffer().put(double[])`，native memcpy）。所以 A+ 对 B 无后悔。
- **C 只取标量读写一半**，即条件刀 K7；完整的零拷贝 `ByteView[T]` 不做。

## 8. 不做的（理由）

1. **B1：让 `Array[Float]`/`Array[Int]` 本身平铺（单态化）。** `Array[T]` 是擦除原语，运行期不知元素类型；推翻 D3/D9，与 `docs/seq6-research.md` 的结论相反。
2. **B2：新增 `F64Array`/`I64Array` 平铺类型，现在。** 在迭代协议 K1 之前，native 上 `listf` 缺口大头是 RC 而非表示；不做 pvec 叶子特化则用户的 `List[Float]` 仍装箱，做了就是「大、高风险」的 value-repr K5。重开条件见 §7。
3. **完整 `ByteView[T]` 零拷贝视图。** JVM 上 `byte[]` 不能重解释为 `double[]`，视图只能是逐元素标量访问；GPU/sha2/inflate 的消费方式是批量或顺序；下载到 `List[Float]` 仍要物化。
4. **「原生字节序」选项。** 两后端原生序可能不同，语言要求逐字节一致。
5. **按 `kind` 枚举参数的单一原语。** 契约层要后端无需认识 ADT；`Int`/`Float` 箱类型不同，拆成两族更快、更好验证。
6. **把舍入也放进运行时原语（bf16/f16/tf32/f8）。** native 要自写软件舍入，且 `narrow.round_*` 语义已由 Dawn 源码与 `dtype_diff` 钉着，放进运行时会出现两份舍入定义。若 K0 实测舍入算术才是剩余大头再重评。
7. **`unpack` 对长度不整除静默丢尾巴。** 改为 panic；静默丢数据是隐藏错误，且没有外部消费者要兼容。
8. **为 `bytes_from_array`、`gpu_upload_host`、`gpu_download_host` 留别名或迁移提示。** 无外部消费者，不做兼容层。
9. **`DeviceBits` 路径上的恒等表示转换（报告 §4.5 的 (b)）。** 需要 checker 规则设计，收益只在窄整数格式；取 (a)，K0 量完再说。
10. **把 `Buf` 换成真字节缓冲类型（`ByteBuf`）。** 已被 `docs/inflate-default-cap-design.md` §5.6 判为不做，本文不重裁。
