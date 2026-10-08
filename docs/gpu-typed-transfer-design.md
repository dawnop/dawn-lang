# GPU 宿主传输类型化：`upload`/`download` 的编码、线格式与刀序（U3a）

> 状态：**proposed**。2026-10-08 写成。基线 `origin/main` = c7c81203，种子 v0.85.0，`packages/tileir` 0.12.0。
> 这是 `dtype-unify-design.md`（PR #634，分支 `gpu/dtype-u0`，尚未合入 main，所以这里不做链接）§6 的 U3a：把那篇留下的 U3 开放问题 1、2、4 答完，并给出 U3b 起的刀序。
> 调研报告：维护者工作区 `research-gpu-typed-transfer-20261008.md`（含网页出处）；格式统一的前置调研是
> `research-format-types-unify-report-20261006`。本文引的外部事实以报告为准，本文只留结论与链接。
> 已有裁决（协调者，不在此重裁）：只存储格式（TF32、F8\*）按位型传输；§12.6 的规则句随 U3 进 spec（英文原文在前，中文在后）；`Tensor[U32]` 仍可写成类型。
> 本文所有计数都在基线上用 `git grep` 数出，不含 `selfhost/src/embed`；没量过的写「未量」并写明由哪一刀去量。

## 0. 先说三个与 U0 §6.2 假设不同的事实

U0 的 §6.2 把 U3 写成「加一个 `Pod[T]` 类的 trait，编码走 `Bytes`，`HasDtype` 只给名字」。核对基线后有三处要改：

1. **`Bytes` 通道已经存在，只缺 f64 与类型化。** `std/gpu.dawn` 的真设备 handler 今天已经对除 `f64` 以外的 11 个缓冲格式走 `pack_to(dt, List[Float])` / `unpack_from(dt, Bytes)`，
   再经 `gpu_upload_bytes_host` / `gpu_download_bytes_host`（运行时只拷字节、不认格式）；只有 `f64` 走 `Array[Float]` 的 `gpu_upload_host` / `gpu_download_host`。
   所以 U3 在线上是「把 f64 也收进已有的字节通道，并删掉那条 `Array[Float]` 旁路」，不是新开一条通道。
2. **模块顺序决定了编码只能在位一级，不能在字节一级。** `std/modules.txt` 的顺序是 `dtype`、`narrow`、`int/*`、……、`bytes`、……、`gpu`。
   `std/bytes`（`Buf`、`put`）排在 `narrow` 与 `int/*` 之后，所以这些模块里写不出「把一个值编成字节」；而只存储格式（TF32、F8\*）在 `std/gpu` 里
   根本取不出 `Float`（它们是 opaque、没有 `to_f64`，见 dtype-unify §3），能把它们变成位型的地方只有它们自己的声明模块。
   结论：编码契约必须是**每个元素一个位型 `Int`**，字节装配只在 `std/gpu` 里做一次。
3. **孤儿规则卡住了 `Float` 的 impl。** 实测（v0.85.0）`impl HasDtype[String]` 写在用户模块里报
   `orphan impl: HasDtype[String] may not live here`，提示「impl 属于声明 trait 的模块或声明该类型的模块」。`Float`、`Int` 是内建类型，没有声明模块，
   所以它们的 impl 只能在 trait 所在的模块里写。若 trait 在 `std/dtype`（见 §2），`Float` 的位型编码就得在 `std/dtype` 里写，
   而今天唯一的实现 `narrow.f64_bits` 在 `narrow`（后于 `dtype`）里，且是算术实现：不保 NaN 载荷、也慢。这直接推出 §4 的一条前置刀（原始位型 intrinsic）。

## 1. 现状（基线实测）

| 项 | 事实 |
|---|---|
| 效果操作 | `gpu_upload(handle: Int, data: List[Float])`、`gpu_download(handle: Int) -> Result[List[Float], ForeignError]`（`std/gpu.dawn` 608 行起） |
| 类型化函数 | `upload[D](t: Tensor[D], data: List[Float])`、`download[D](t: Tensor[D]) -> Result[List[Float], _]`；`D` 是幻影类型，函数里不读它 |
| `Tensor[D]` | `opaque` 的 `(handle, len)`，**不带格式名**；格式名只在 handler 的缓冲表里 |
| 真设备 | f64：`gpu_upload_host(p, Array[Float])` 在 C 里拷成 `double[]` 再 `cuMemcpyHtoD`；其余 11 格式：`pack_to` 后 `gpu_upload_bytes_host(p, Bytes)` |
| 假设备 | 缓冲表存 `(格式名, List[Float])`，`upload` 时按名 `round_to`，launch 时把 `List[Float]` 直接交给 `WideRefFn` |
| native intrinsic | `selfhost/src/check/types.dawn` 3871 到 3886 行四条 `bsig`；`selfhost/builtins.dawn` 412 到 421 行镜像；`runtime/c/dawn_rt.c` 4964 到 5143 行（真实现与 wasi 拒绝桩各四个）与 `dawn_rt.h` 808 到 811 行；JVM 侧 `selfhost/src/jvm/rtclasses.dawn` 1487 到 1490 行四个 `gen_gpu_refusal` |
| 精度债 | `Float` 只在 ±2^53 内装得下 `i64`；`dtype_diff.dawn` 把 i64 语料限制在 ±2^52（`i64_a`/`i64_b` 的注释） |
| 已有的位型函数 | `narrow.{bf16,f16,f32,f64,tf32,f8e5m2,f8e4m3fn,f4e2m1,f8e8m0}_bits` 与对应 `_of_bits`，入参出参都是 `Float` 与 `Int`；整数模块有 `wrap`/`to_int` |

### 1.1 调用点计数

口径：`git grep`，只数 `*.dawn` 与两篇教程，不含 `selfhost/src/embed`（生成物，随 `gen-stdsrc` 重生）、不含 `std/gpu.dawn` 自己。`compiler-plan/src` 里有 3 处 `download(` 是包下载，与 GPU 无关，不计。

| 位置 | 原始 `gpu_upload`/`gpu_download` | 类型化 `upload`/`download` |
|---|---|---|
| `scripts/tile-gpu-diff/*.dawn`（27 个文件，其中 26 个驱动动 upload/download） | 45 | 16 |
| `examples/projects/gpu_fake` | 2 | 4 |
| `packages/tileir/src/prog.dawn`（测试） | 0 | 5 |
| `scripts/scalar-bench/bench.dawn` | 0 | 4 |
| `docs/tutorial.md` / `docs/tutorial.zh-CN.md` | 0 | 12 / 12 |
| `std/gpu.dawn` 自己（含 35 个 test 里的用法与文档注释） | 47 处合计 | |
| `site/src/gen/*.dawn` | 0（`gpu.dawn` 页无 upload/download 字样；`home.dawn` 两处是安装文案里的 download，与 GPU 无关） | 0 |
| `packages/tileref` | 0（通道是 `List[Float]`，不调 upload/download，只在注释里提） | 0 |

两点后果。其一，**tile-gpu-diff 的驱动不能直接改成类型化调用**：它们的缓冲是异构的 `List[(String, List[Float])]`（格式名是字符串、内容是 `List[Float]`），
一个循环里每个缓冲的 `T` 不同，类型化的 `upload[T]` 写不出来。这 45 处要走一个**保留的名字分派层**（§3.4），不是 `upload`。
其二，真正按 `upload`/`download` 迁移的是 16 + 4 + 5 + 4 + 24（教程，中英各 12）= 53 处加 `std/gpu.dawn` 自己的测试。

## 2. Q1：编码放在哪里

### 2.1 三个选项

- **A. `Dtype[T]` 自己带编解码**（铸造处给齐闭包，`Dtype` 不再是 `String` 的薄包装）。
- **B. 与 `HasDtype` 并列的单独 trait。**
- **C. 给 `HasDtype` 加方法。**

### 2.2 调研结论摘要（详见调研报告 §1）

- **cutile-rs 的 `DType`**（NVIDIA，2026）是一个 `unsafe trait`，`const DTYPE: DTypeId`，同一个 trait 既标「可作 `Tensor<T>` 的元素」又标「可作标量 kernel 参数」，
  host 读回靠 `to_host_vec` 直接把设备字节当 `T` 读；它不需要「编码」方法，因为 Rust 类型的内存布局就是线格式，安全条件写成 unsafe 契约（任何设备可产生的字节序列都是合法的 `Self`），
  `bool` 是唯一例外，靠设备侧保证只写 0/1。（出处：https://github.com/NVlabs/cutile-rs 的 `cuda-core/src/dtype.rs`。）
- **Rust `bytemuck::Pod`**：类型自己声明「全部位型合法、无填充、`repr(C)`」，字节转换是 `cast_slice`/`bytes_of` 这类**与类型绑定的函数**，不是格式描述对象带的闭包；
  文档明写字节转换依赖字节序。（出处：https://docs.rs/bytemuck/latest/bytemuck/trait.Pod.html。）
- **NumPy/PEP 3118**：dtype 是一个**对象**，带 `byteorder`（`<` `>` `=` `|`），缓冲区协议用格式串描述元素；这条路是「描述符对象带编码信息」，也就是选项 A 的形态。
  代价是描述符在运行期，类型检查不进来：`ndarray.set`/`get` 在 CuPy 文档里没写 dtype 不符时怎么办。（出处：https://numpy.org/doc/stable/reference/generated/numpy.dtype.byteorder.html、https://peps.python.org/pep-3118/、https://docs.cupy.dev/en/stable/reference/generated/cupy.ndarray.html。）
- **Halide `Buffer<T>`**：元素类型进 C++ 类型参数，`halide_type_of<T>()` 把类型映到运行期描述符；`Buffer<void>` 是类型擦除形态。（出处：https://halide-lang.org/docs/class_halide_1_1_buffer.html 的搜索摘要，原页未逐字核对。）
- **JAX**：`jax_enable_x64` 默认关，64 位值默认建不出来（把精度问题推成「根本不允许」）。（出处：https://docs.jax.dev/en/latest/default_dtypes.html。）

Dawn 与它们的差别：没有内存布局可以直接借（opaque 类型就是它的目标类型，`BF16` 的表示是 `Float`），没有调用点类型实参（spec §2.5），trait 方法只能靠参数或期望类型选 impl，
并且有孤儿规则。所以 cutile-rs 的「类型即布局」不可照搬；bytemuck 的「类型声明、函数绑定」的分工可以借。

### 2.3 逐项判

**C（扩 `HasDtype`）出局。** `HasDtype` 覆盖的是 16 个**tile 格式**，缓冲格式是其中 11 个（`element_bytes` 认的）。`I1`（Bool）、`I4`、`F4E2M1FN` 有 `HasDtype`、没有缓冲格式、也没有可传输的宿主值。
给 `HasDtype` 加编码方法，这三个就得写一个 `panic` 的假实现，类型错误退化成运行期失败。这是 tileir-011 §9 Q4 把 `FloatDtype` 与 `HasDtype` 分开保留时用过的同一条理由，这里再用一次。

**A（`Dtype[T]` 带闭包）出局。** 三个原因：(1) `Dtype[Bool]`、`Dtype[I4]` 同样存在而不可传输，与 C 同病；(2) `Dtype` 今天是 `opaque ... = String`，继承 `Eq/Hash/Ord`，
tileir 记录期、`alloc` 的表键、`assert dtype_name(a) == ...` 的测试都依赖它可比较；带闭包后不再可比较，要么手写 `Eq` 比名字（等于闭包是附加物），要么破坏现有用法；
(3) `upload(t, xs)` 手里没有 `Dtype` 值，要用就得让 `Tensor[T]` 多带一个字段，`Tensor` 的 `(handle, len)` 表示、`size`、`handle_of`、`buffer` 全要动。收益只有「少一个 trait 约束」。

**B（单独 trait）**，且契约是位型而不是字节（§0 第 2、3 条）：

```dawn
## 一个值作为设备缓冲元素时的位型。
pub trait DeviceBits[T] {
  ## 位型：低 `width` 位是格式的位模式（无符号读法）；8 字节格式占满整个 Int。
  fn bits_of(v: T) -> Int
  ## 逆：高于 `width` 的位被忽略。
  fn from_bits(bits: Int) -> T
}
```

- 声明在 `std/dtype`（与 `HasDtype` 并列）。理由是孤儿规则：`Float`、`Int` 的 impl 只能放在 trait 所在模块；其余类型（`BF16 F16 F32 TF32 F8E4M3FN F8E5M2 F8E8M0FNU I8 I16 I32 U8`）的 impl 放在**各自的声明模块**，
  与见证、`impl HasDtype` 并排，即 dtype-unify §1 的「三行并排」变成四行。
- 宽度不进 trait：`bits_of` 的参数含 `T`、`from_bits` 的返回含 `T`，选 impl 没问题，但「宽度」这种不含 `T` 的方法选不出 impl。
  宽度取自 `element_bytes(dtype_name(dtype_of()))`，所以类型化函数写 `T: HasDtype + DeviceBits`（`+` 约束在 spec 里已有，`assert_eq[T: Eq + Show]`）。
- `I1`（Bool）、`I4`、`F4E2M1FN` **不 impl** `DeviceBits`：`upload` 一个 `Tensor[Bool]` 是**编译错误**（requires `DeviceBits[Bool]`），不是运行期拒绝。这正是 `HasDtype` 与可传输集合分开的收益。
  （当前 `alloc(I1, n)` 到 handler 才被 `gpu.unsupported_dtype` 拒绝；类型化传输把传输这一步的拒绝前移到了类型检查。`alloc` 本身不动，不在本文范围。）
- `U16 U32 U64` 不 impl `HasDtype`，所以也不 impl `DeviceBits`；`Tensor[U32]` 仍可写成类型（已有裁决），`upload` 它同样是编译错误。
- 只存储格式的 `DeviceBits`：`bits_of` 在它们的声明模块里取自 `narrow.tf32_bits` 等现成函数（那里 opaque 即 `Float`），`from_bits` 取 `*_of_bits`。**不需要 `to_f64`**，U0 §8 开放问题 2 就此关闭：一律走位型，不为它们另起 `value_of` 之类的名字。

**推荐 Q1：B，位型契约，`DeviceBits` 与 `HasDtype` 并列在 `std/dtype`。** 判据是语言纯洁（`Dtype` 保持「一个名字」，不被塞进它不负责的事；可传输集合是 tile 格式集合的真子集，由 trait 是否 impl 表达）与架构（impl 在类型自己的模块、字节装配只一处）。

## 3. Q3：线格式

### 3.1 推荐

**效果操作两端都是 `Bytes`，对每个缓冲格式一视同仁，包括 `f64` 与 `i64`。**

```dawn
pub effect Gpu {
  fn gpu_upload(handle: Int, data: Bytes) -> Result[Unit, ForeignError]
  fn gpu_download(handle: Int) -> Result[Bytes, ForeignError]
  ...
}
```

- **字节序：小端，规定而不是探测。** 设备侧（CUDA 的 x86-64 与 aarch64 Linux 主机）是小端，运行时按字节拷贝，不转换。NumPy 的 `<` 显式字节序与 PEP 3118 的前缀是同一思路：线格式写明字节序，而不是「本机」。
  native 运行时在 `dawn_rt.c` 加一条 `_Static_assert`（`__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__`，仅在 GPU 代码段），大端主机编不过，不静默出错。未实测：没有大端主机可跑。
- **元素宽度**：`element_bytes` 的 12 个格式（`f64 i64 i32 tf32 bf16 f16 i16 i8 u8 f8E4M3FN f8E5M2 f8E8M0FNU`），元素 `i` 占 `[i*w, (i+1)*w)`，位型低字节在前。
- **对齐**：`Bytes` 无对齐要求；设备缓冲由 `cuMemAlloc` 分配（驱动保证至少 256 字节对齐，出处是 CUDA 驱动文档对 `cuMemAlloc` 的说明，本文未逐页核对），元素在缓冲内按自然宽度偏移，不会错位。
  `cuMemcpyHtoD` 的主机源指针是否要求对齐：未核对，今天 11 个格式已经直接把 `Bytes` 的内部指针交给它（`dawn_gpu_upload_bytes_host`），tile-gpu-diff 在 sm_86 上逐位相等，是间接证据，不是证明。
- **NaN 载荷**：今天 f64 经 `double[]` 拷贝，载荷保留。若 U3 用 `narrow.f64_bits`（算术实现，NaN 一律答 `0x7FF8000000000000`），载荷丢失，是回退。
  所以 §4 的 U3b1 加一对**原始位型 intrinsic**（`Float`↔`Int`，Java 的 `Double.doubleToRawLongBits`/`longBitsToDouble`，Rust 的 `f64::to_bits`/`from_bits`，Go 的 `math.Float64bits` 同形），
  `narrow.f64_bits`/`f64_of_bits` 改为它们的薄封装。Float 的 `DeviceBits` impl 因孤儿规则必须写在 `std/dtype`，而 `std/dtype` 是 narrow 的下层，这对 intrinsic 也是**前置**，不是优化。

### 3.2 删什么

`gpu_upload_host(Int, Array[Float])` 与 `gpu_download_host(Int, Int) -> Result[Array[Float], _]` 两条 intrinsic 整条删除：`types.dawn` 2 条 `bsig`、`builtins.dawn` 2 条镜像、`dawn_rt.c` 4 个函数（真实现 2、wasi 桩 2）、`dawn_rt.h` 2 行、`rtclasses.dawn` 2 个桩。
保留的 `gpu_upload_bytes_host`/`gpu_download_bytes_host` 名字不改，避免无谓的 Emit-Change；去掉 `_bytes_` 只是美观，不值得多一轮 golden 变动。

### 3.3 假设备与参考实现通道（tileref）

- `packages/tileref` 的参考实现仍是 `fn(n, dtypes: List[String], ins: List[List[Float]]) -> List[Float]`（`WideRefFn`），**不动**（U0 §9 第 9 条）。它是宿主参考，不是设备。
- 假设备的缓冲表由 `(格式名, List[Float])` 改为 `(格式名, Bytes)`：`gpu_upload` 原样存字节，`gpu_download` 原样答字节，所以 **upload 后立即 download 的往返对任意格式、任意值逐位精确**（包括 2^53+1 的 i64）。
  launch 时才把每个输入按格式名 `unpack_from` 成 `List[Float]` 交给 `WideRefFn`，写回再 `pack_to`。
- `i64` 越过 ±2^53 的值，在**交给 `WideRefFn` 的那一步**无法表示成 `Float`。假设备在那里**拒绝**（`gpu.fake_inexact`，消息写明是哪个缓冲、哪个下标），而不是静默舍入。这与 `round_to` 的「静默舍入」不同，故意如此：
  `upload` 不再舍入（值在 `T` 里已经是格式的值），而参考实现的 `Float` 通道装不下的值是一个应当被看见的限制。代价：假设备上 `i64` 语料仍限于 ±2^53 才能过 launch。
- **`dtype_diff` 的 i64 越界语料因此只在真设备上跑，参考值由 tileref 里的一个 `Int` 孪生函数 `dtype_i64_ref_int(n, a: List[Int], b: List[Int]) -> List[Int]` 给出**（`Int` 的乘加在 Dawn 里是 64 位回绕，与设备 `addi/muli` 同；
  这一点是依据，未在本文实测，U3c 的第一个测试要证它）。`WideRefFn` 通道不变，孪生函数是 `dtype_i64_ref` 旁边的新函数，不是对通道的改动。

### 3.4 保留的名字分派层

`pack_to(dtype: String, xs: List[Float]) -> Bytes` 与 `unpack_from(dtype: String, b: Bytes) -> List[Float]` **保留并公开**，补上 `f64` 一臂；它们是「按字符串名的 `Float` 视图」，服务两类调用方：
tile-gpu-diff 的异构缓冲驱动（45 处原始调用改成 `gpu.gpu_upload(h, pack_to(dt, data))`，机械替换），和假设备的 launch 边界。它们不是兼容层：旧的 `List[Float]` 效果签名消失，这是名字分派的**新**角色。
内部实现收为一个宽度通用的装配函数（位型 `Int` 列表按宽度小端打包 / 拆包），`pack_bf16` 等 11 对函数删除（它们今天各自重复一遍循环）。

### 3.5 性能：测了什么，没测什么

问题是「f64 也走 `Bytes` 之后，宿主侧编码成本涨多少」。量法：`./bin/dawn run`（JVM 后端，v0.85.0），1,000,000 个元素的 `List[Float]`，同一进程内依次计时，单次、三次进程重复；
`pack_f64` 是脚本里按设想的 U3 写的版本（`narrow.f64_bits` 加逐字节 `bytes.put`），不是仓库代码。草稿在本机 scratchpad，不进仓库。

| 步骤 | 毫秒（三次重复） |
|---|---|
| 遍历并复制 `List[Float]`（今天 f64 路的宿主半段的下界） | 49、46、48 |
| `pack_i32`（今天 11 格式路的 4 字节） | 87、86、88 |
| `unpack_i32` | 73、70、76 |
| `pack_i64`（8 字节） | 187、186、188 |
| `unpack_i64` | 317、303、298 |
| `pack_f64`（U3 的设想，8 字节） | 185、184、185 |

读法：这是 JVM 后端、冷启动、含 JIT，**不是 native**；而 `gpu_*_host` 只在 native 运行时存在，真正的宿主成本在 native 上，本文**未量**。
JVM 上的趋势：每多一个字节约 20 ns，字节数决定成本；f64 从「遍历 + C 里一次 memcpy 级拷贝」（量不到，C 半段未量）变成约 185 ms，**可能慢到 4 倍**，量级是毫秒到百毫秒，
对照一个 8 MB 缓冲的 PCIe 拷贝（估计，未量，约 0.3 到 0.7 ms），宿主编码已经是主导项；今天 11 个窄格式路本来就是这样，U3 只是让 f64 也如此。
**因此 U3b/U3c 之外留一条条件刀 U3d：宽度通用的批量 intrinsic**（`Array[Int]` 位型按宽度打包成 `Bytes` / 拆回，RtBytes 一个模块），入场判据是 U3b 里先在 native 上量出 1M 元素 f64 编码的墙钟；
没有数字不做，数字好看再做，数字难看也许不值得做（用户态的 8 MB 拷贝一年也难得跑几次）。

## 4. Q2：K4 的 `ScalarDtype` 与 `DeviceBits` 合并吗

### 4.1 今天的 `ScalarDtype`

`std/gpu.dawn` 530 到 560 行：`trait ScalarDtype[A] { fn scalar_dtype() -> Dtype[A]  fn scalar_word(v: A) -> LaunchArg }`，四个 impl：`Float`（`Word("f64", f64_bits)`）、`Int`（`Word("i64", v)`）、
`I32`（`Word("i32", to_int & 0xFFFFFFFF)`）、`F32`（`Word("f32", f32_bits(to_f64))`）。`Word(dtype, bits)` 的 `bits` 是「`i32`/`f32` 在低 32 位，`i64`/`f64` 占满 64 位」，即**与上面的 `bits_of` 约定逐字相同**。

### 4.2 比较

- cutile-rs 把「张量元素」与「标量参数」放进**同一个** `DType`，没有子集。Triton 与 cuTile Python 的标量参数规则这次没有取到一手页面（调研报告 §0 记了缺口），不据此下判断。
- Dawn 这边的子集关系是 K4 **有意**留的：`scalar_dtype` 的注释写明「只给 I32 I64 F32 F64，因为这四个在参数区的布局就是 4 或 8 字节」，且 K4 的裁决把 `bf16`/`i8` 之类标量参数排除（Tile IR 13.4 规范对 rank-0 入口参数的类型没有一手引文，tileir-k4-design §1.4）。

### 4.3 推荐 Q2：**不合并成一个 trait，但合并位型的来源**

- 保留 `ScalarDtype`：它表达的不是「怎么编码」而是「哪些格式允许按值传」，是 `DeviceBits` 的真子集（4 个对 11 个）。合并会把 `scalar(x: BF16)` 放进类型检查通过的集合，而 Tile IR 是否接受这样的入口参数**没有一手证据**；
  放宽应当是单独一刀、先量（K4 的做法），不是 U3 顺手带的。
- 去重复：`ScalarDtype` 的四个 impl 里的位型算式（`f64_bits`、`& 0xFFFFFFFF`、`f32_bits(to_f64(v))`）全部改成对 `bits_of` 的调用：`scalar_word(v) = Word("i32", bits_of(v))`。
  `scalar_dtype()` 与 `HasDtype::dtype_of()` 今天是同一个答案写了两遍，一并改成调 `dtype_of()`。结果：位模式只有一个来源，K4 的 `Word` 与 U3 的传输逐位一致由构造保证，而不是由测试保证。
- 门禁：K4 现有的 `erase(scalar(..)) == Word(..)` 五条断言（`std/gpu.dawn` 2670 到 2675 行）原样保留，是这次重构的回归网；`scripts/scalar-bench` 与 `scripts/tile-gpu-diff/scalar_diff.dawn`（真设备）要仍绿。
- 负控：把 `I32` 的 `bits_of` 改成不掩码（负数得到负 `Int`），`scalar(i32.wrap(0 - 2))` 的断言必红。

## 5. Q4：迁移与门禁

### 5.1 范围

计数见 §1.1。受影响的面：

| 面 | 动什么 | 破坏 |
|---|---|---|
| `std/dtype`、`std/narrow`、`std/int/{i8,i16,i32,u8}` | 加 `DeviceBits` trait 与 impl（11 个格式加 `Float`、`Int`） | 否（增量） |
| `std/gpu` | `Gpu` 效果 `gpu_upload`/`gpu_download` 改 `Bytes`；`upload`/`download` 改 `List[T]`；假设备缓冲存 `Bytes`；`ScalarDtype` 瘦身；11 对 `pack_*`/`unpack_*` 收为一个宽度通用函数；`pack_to`/`unpack_from` 补 `f64` | 是 |
| 编译器与运行时 | 删 2 条 `Array[Float]` intrinsic（类型表、镜像、C、wasi 桩、JVM 桩）；加一对原始位型 intrinsic | 是（intrinsic 表） |
| `packages/tileref` | 加 `dtype_i64_ref_int`；通道不变 | 否 |
| 调用方 | tile-gpu-diff 45 处原始调用加 `pack_to`/`unpack_from`；16 + 4 + 5 + 4 处类型化调用把 `List[Float]` 字面量改成 `List[T]`；教程中英各 12 处 | 是 |
| spec | §12.6（中文 `spec.md` 与 `spec.en.md`）改写 | 文档 |

类型化调用点的改法要看 `T`：`Tensor[Float]` 的调用（`upload(a, [1.0, 2.0])`）不变，因为 `Float` 字面量本来就是 `List[Float]`；
`Tensor[BF16]` 的调用把 `Float` 列表改成 `BF16` 列表，经 `FromFloat`（`let w: BF16 = 0.1` 在构造点舍入，dtype-unify §7 提过）。具体多少处要换类型，要等 U3b 里逐个文件对一遍才有数，**未量**。

### 5.2 门禁

- **`dtype_diff` 的 i64 越界语料**：`i64_a`/`i64_b` 加一组越过 2^53 的值（建议 `2^53 + 1`、`-2^62`、`Int` 最大与最小值各一），真设备 vs `dtype_i64_ref_int` 逐位相等。原语料的 ±2^52 段保持。这是本刀的主判词。
- **tile golden 逐字节不变**：U3 不碰 `packages/tileir` 与 `tileiras` 输入，`kernels.dawn` 产物不变。但 `std/gpu.dawn` 与 `std/narrow.dawn` 在 tile-gpu-diff 的 `TILE_PATHS` 里（`scripts/tile-gpu-diff/run.sh` 575 行），所以台账的 `inputs=` 摘要会变，verdict 不变；sm_86 本机重录，sm_90、sm_100 由所有者重录（同 dtype-unify §6.4）。
- **Emit-Change**：标签必须逐字取自 `scripts/emit-labels.txt`，不接受通配。预计被动到的候选：`doc --builtins`（intrinsic 表变）、`emit selfhost`（`stdsrc` 内嵌的 std 变）；
  `doc`、`run` 类标签是否被动，**要等 U3b 跑 `selfhost-prev-diff.sh` 与 `selfhost-run-diff.sh` 才知道**，本文不预报。
- 其他：`./bin/dawn test selfhost`、`./bin/dawn test` 对 std 的 stdlib 测试、`scripts/gen-stdsrc` 重生后 embed 无漂移、`dawn doc --stdlib` 与 LSP 同名语料、`native-fixpoint.sh` B==C。

## 6. spec §12.6 要写的句子

规则句（协调者已裁进 spec；英文原文在前）：

> In type position write the value type; in value position write the format's name. For `std/narrow` and the fixed-width integers the two are spelled alike (`Tile[BF16]`, `alloc(BF16, n)`); for the three builtins they are `Float`/`F64`, `Int`/`I64`, `Bool`/`I1`.

> 类型位置写值类型，值位置写格式名。对 `std/narrow` 与定宽整数两者同名（`Tile[BF16]`、`alloc(BF16, n)`）；对三个内建类型分别是 `Float`/`F64`、`Int`/`I64`、`Bool`/`I1`。

随 U3c 改写的句子（见 dtype-unify §6.3，这里补上本文新增的两条）：

- 「值以 `List[Float]` 进出」改为「值以 `List[T]` 进出，`T` 是张量的元素类型；`upload` 把每个值编码成格式的位型（小端），宽整数不再经 `Float`，`download` 精确答出」，i64 精确性债关闭。
- 「`upload` 按缓冲格式舍入」改为「值在 `T` 里已经是格式的值，`upload` 不舍入」。
- 新增一句：只有同时有 `HasDtype` 与 `DeviceBits` 的 `T` 才能 `upload`/`download`；`Bool`、`I4`、`F4E2M1FN` 有格式无缓冲，传输是类型错误。
- 假设备一节新增：往返任意值逐位精确；越出 `Float` 通道精度的 `i64` 在 launch 边界被拒（`gpu.fake_inexact`），不舍入。
- 英文 `spec.en.md` 同步，译本摘要重登记（`doc-check.py` 的 transl 检查）。

## 7. Q5：刀序

| 刀 | 内容 | 破坏 | 判词 | 负控 |
|---|---|---|---|---|
| U3a | 本文 | 否 | 裁决（§8 的开放问题） | 无 |
| U3b1 | 原始位型 intrinsic 一对（`Float`↔`Int`，JVM、C、wasi 桩、类型表、镜像、`narrow.f64_bits`/`f64_of_bits` 改封装）；先在 native 上量 1M 元素 f64 编码墙钟，决定 U3d | 否（加 intrinsic，旧函数行为只在 NaN 载荷上更保真） | 现有 narrow 测试全绿；新增 `0x7FF8000000000001` 往返保载荷；`native-fixpoint.sh` B==C；Emit-Change 声明 | 把 JVM 侧换成 `doubleToLongBits`（规范化 NaN），载荷测试必红 |
| U3b2 | std 增量：`DeviceBits` trait 与 12 个 impl（含 `Float`、`Int`）；宽度通用的位型装配函数；`upload_typed`/`download_typed` 以新名并存（只活到 U3c，同提交内收回，不留别名）；`ScalarDtype` 改调 `bits_of` | 否 | std 测试；每个格式在边界值上的往返；`ScalarDtype` 五条断言原样；`dawn doc`/LSP 同名语料不受影响 | ①`I32` 的 `from_bits` 少一个字节宽，往返测试红；②字节序写反，往返测试在非对称值上红；③`upload_typed` 一个 `Tensor[Bool]` 必须是编译错误（负控是检查它**确实**报错，而不是用 `U32` 之类顺带过去） |
| U3c | 切换：效果操作 `Bytes`；删 `Array[Float]` 两条 intrinsic；`upload`/`download` 收 `List[T]`；假设备存 `Bytes`、launch 边界 `fake_inexact`；`pack_to`/`unpack_from` 补 `f64`；tileref 加 `dtype_i64_ref_int`；迁移 §1.1 的全部调用点；教程中英；spec §12.6 中英；`dtype_diff` 越界语料 | 是 | §5.2 全部 | ①`download` 解码改回经 `Float`，i64 语料在 2^53+1 红；②`upload` 位型字节序写反，`dtype_diff` 红；③假设备往返 2^53+1 的 i64 必须逐位相等（把假设备改回存 `List[Float]`，此测试红） |
| U3d（条件） | 宽度通用批量 intrinsic（RtBytes） | 否 | U3b1 的 native 数字出来后立项 | 打包宽度写错一档，往返红 |

U3 不碰 `packages/tileir` 的代码，所以不需要 tileir 的次版本；U4 复用 `DeviceBits`（取回宿主 `Float` 的缺口就是这个 trait 补上的）。
U3c 与「改 CI 必报墙钟」：本文不改 workflows，不新增 gate；`std/gpu.dawn` 的变更会让 tile 台账摘要变，触发的重录成本由所有者的集群重录承担，不在 PR CI 里。

## 8. 开放问题（需要裁决）

1. **原始位型 intrinsic 加不加（U3b1）。** 推荐加：孤儿规则让 `Float` 的 `DeviceBits` 必须在 `std/dtype`，而 `std/dtype` 排在 `narrow` 之前，不加 intrinsic 就写不出；同时保 NaN 载荷。若不加，退路是把 trait 声明挪到 `std/narrow`（让整数模块多依赖 `narrow`），并接受载荷规范化。
2. **假设备存 `Bytes` 还是继续存 `List[Float]` 并在 `upload` 拒绝不精确的 i64。** 推荐前者（往返精确是一个可测的性质）；后者改动小，但 `Float` 存储下 `dtype_diff` 的假设备等价对照无法覆盖 2^53 以上。
3. **`dtype_i64_ref_int` 放在 tileref 还是只放在 `dtype_diff` 里。** 推荐 tileref（它是参考实现的家，其余 i64 参考也在那里）；放 `dtype_diff` 里更局部但把参考逻辑散到驱动。
4. **U3d 的入场线。** 本文不定数字；建议 U3b1 量出 native 上 1M 个 f64 的编码墙钟后，由量到的值相对 8 MB 拷贝（估计 0.3 到 0.7 ms，须在 B200 与 3080 上量）的比例定。
5. **`upload_typed` 并存期是否值得。** U0 的刀序里 U3b 与 U3c 之间有新旧并存。若 U3b2 与 U3c 能在同一个 PR 里分两个提交（每刀一个提交），并存名字就不会出现在 main 上，可省掉；取决于 PR 的体量（调用点 53 + 45 处），由写者在 U3b2 开工时报。

## 9. 不做的（理由）

1. **把编码做进 `Dtype[T]`（选项 A）**：`Dtype` 失去可比较性、`Tensor` 要多一个字段，且 `Dtype[Bool]` 等不可传输的格式仍要一个假编码（§2.3）。
2. **扩 `HasDtype`（选项 C）**：16 个 tile 格式里只有 11 个是缓冲格式，扩了就要给 `I1 I4 F4E2M1FN` 写 `panic` 的假实现，类型错误退成运行期失败（§2.3）。
3. **`ScalarDtype` 并入 `DeviceBits`**：会让 `scalar(x: BF16)` 类型检查通过，而 Tile IR 接受这样的入口参数没有一手证据；放宽是单独一刀（§4.3）。
4. **字节一级的编码契约（`encode(List[T]) -> Bytes`）**：`std/bytes` 在 `narrow`/`int/*` 之后，这些模块写不出；只存储格式在 `std/gpu` 里又取不出 `Float`（§0）。
5. **给只存储格式补 `to_f64`**：trait 方法共享函数命名空间，第二个同名方法编不过（dtype-unify §3），且位型已经够（§2.3）。
6. **改参考实现的 `List[Float]` 通道**：它是宿主参考，改了动 `packages/tileref` 全部参考实现且没有收益；i64 精确性靠一个 `Int` 孪生函数解决（§3.3）。
7. **假设备对不精确的 i64 静默舍入**：`upload` 不再舍入之后，静默地在 launch 边界舍入会让一个越界值看起来被正确处理；拒绝才让限制可见（§3.3）。
8. **为旧的 `List[Float]` 效果签名保留别名或迁移提示**：没有外部消费者，破坏性变更不做兼容层。保留的 `pack_to`/`unpack_from` 是新的「按名分派的 `Float` 视图」，不是旧签名的别名。
9. **主机端字节序可配置 / 大端支持**：没有大端 CUDA 主机；用静态断言让大端编不过，比做一个从未测过的转换路径诚实（§3.1）。
10. **在本文里决定 U3d**：没有 native 数字不立项（§3.5）。
11. **让 `upload` 接受 `U16 U32 U64`**：方言没有无符号整数 tile 类型，`HasDtype` 与 `DeviceBits` 都不 impl 它们才是诚实的（dtype-unify §9 第 5 条）。
