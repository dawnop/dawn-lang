# builtin 函数值走同一条 lowering，数值解析原语改为声明

> 状态：**current**。2026-09-30，issue #283、#185、#186（分支 `fix/builtin-fn-value-lowering`）。
> 调研是 `research-code-debts-20260930` 的 #185、#186 两节与「builtin 函数值绕过 lowering 改写」一节；
> 本文记规则、取舍与门禁。

## 问题

三件事，根是同一个：「一个 intrinsic 名字由谁实现」在 lowering 里是三分的，在别处不是。

1. **#283，builtin 函数值绕过改写。** `lower.lift_fn_value` 给 builtin 造包装 lambda 时，体直接写
   `CIntrinsic(name, ...)`，不经 `lower_expr` 对 `XCallBuiltin` 做的那串特例（`parser_impl`、
   `char_unchecked`、`to_string`、`hamt_fn`、cell/ctl）。于是：
   - `let f = parse_int`、`let f = parse_int_radix` 过 `dawn check`，JVM 上
     `panic: codegen: Core intrinsic without a JVM mapping: parse_int`，native 上
     `panic: emitc: intrinsic not implemented for native: parse_int`；
   - `let f = parse_float` 不 panic，但绕过 std/fmt 的 §11 文法校验直接调宿主：
     `f("1.5d") = Some(1.5)`、`f("0x1p3") = Some(8.0)`，直接调用 `parse_float` 对两者都答 `None`。
2. **#185，comptime 解释器是二分的。** `interp_arms`（有臂）与 `comptime_rejects`（按名拒绝）划分
   intrinsic 全集，没有「lowering 已改写、解释器永远见不到」这一类。结果：
   - `parse_int` 在 `interp_arms` 里有一条死臂（注释说解释 std Core，体调的是宿主 `parse_int`）；
   - `parse_int_radix`、`char_unchecked`、`map_*`/`set_*` 被塞进 `comptime_rejects`，镜像
     `selfhost/builtins.dawn` 的 P5 标记于是对用户宣称 `parse_int_radix` 在 `const` 里被拒；实测
     `const Z: Option[Int] = parse_int_radix("ff", 16)` 折叠成 `Some(255)`。
3. **#186，parse_float 的原语是按模块路径认出来的。** std/fmt.atod 校验后要调宿主做十进制到二进制的
   转换，这一次调用必须留作 intrinsic；lowering 靠 `st.owner != "std/fmt"` 这条字符串比较认它。
   `std/fmt` 改名或 atod 挪模块，这条就不再匹配。

## 规则

### lowering 侧：一个名字恰属一组

`ir/lower.dawn` 已有的划分不变，本文只把它当作其余各处对齐的标准：

| 组 | 含义 | 谁欠一条臂 |
|---|---|---|
| `Intr.rt` 有值 | 运行时模块拥有，各后端按约定名调用 | 各后端的运行时（不是发射器） |
| `inline_intrinsics` | 各后端自己写指令 | JVM 与 native 发射器 |
| `jvm_only_intrinsics` | 只有 `use java` 产生的值会到 | JVM 发射器 |
| `lowered_intrinsics` | lowering 改写成别的东西，后端永远见不到 | 没有人；有臂即死代码 |
| `staged_intrinsics` | 实现它的阶段还没落地，lowering 按名拒绝 | 没有人（今天为空） |

新增的约束是 **`lowered_intrinsics` 里任何名字都不能以 `CIntrinsic` 出现在 lowering 的输出里**，
不论它出现在直接调用还是函数值里。

### 函数值：包装体是一次 builtin 调用，交给 `lower_expr`

`lift_fn_value` 对 builtin 不再自己写 `CIntrinsic`，而是造一个 `XCallBuiltin(name, 参数, [], 证据, ty)`，
在包装函数自己的帧里交给 `lower_expr`。于是直接调用的所有特例对函数值自动成立，特例只在一处：

- 参数是包装参数的 `XLocal`；擦除类型的跨越（`lower_args_to` / `adapt_out`）由 `XCallBuiltin` 臂按
  `erased_builtin_sig` 做，与原来手写的 `adapt_in` / `adapt_out` 是同一对变换。
- 证据：包装对外是函数值，只收一个证据包；对内是具名调用，按 builtin 自己的 ABI 行每个原子一个槽。
  原来手写 `ev_from_pack`；现在对行里每个原子写一个 `XEvRead(key, role, ...)`，并以
  `ev_env = []`、`ev_own = 包参数` 进入 `lower_expr`——和 `lift_lambda` 降 lambda 体用的是同一个帧形状，
  `ev_slot` 于是给出同一个 `ev_from_pack(pack, key)`。只有 `sort_by` 与 `bracket` 的行非空。
- 见证：函数值路径上 `wits` 为空。带约束的 builtin 被检查器的 `eta_bounded_fn_value` 展开成 lambda，
  本来就不走 `lift_fn_value`。

不在 `lift_fn_value` 里再抄一份 `parser_impl` 判断：那正是函数值与直接调用分叉的方式。

### 解释器侧：三组，两两不交

`ir/interp.dawn` 的划分从二分改为三分，全集仍是 `types.intrinsics()` 加 `lower.internal_intrinsics()`：

| 组 | 来源 |
|---|---|
| `interp_arms()` | 解释器有臂 |
| lowered | `lower.lowered_intrinsics()` 原样引用，不抄 |
| `comptime_rejects()` | 解释器按名拒绝 |

- `parse_int` 离开 `interp_arms`，臂删除；`parse_int_radix`、`char_unchecked`、`map_*`/`set_*`、
  以及 #186 之后的 `parse_float` 离开 `comptime_rejects`，归 lowered 组。
- 分区测试断言三组两两不交、并为全集，并单独断言 `interp_arms ∩ lowered = ∅`（#185 验收第一条的「或」分支）。
- **`map_*`/`set_*` 在 `const` 里仍然不折叠**，只是理由不在 intrinsic 层：lowering 把它们改写成
  `std/hamt` 调用，`call_named` 拒绝 `std/hamt` 的 Core。这组名字单列为
  `comptime_refused_after_lowering()`，测试从两个方向对 `lower.hamt_fn` 对账，并实际探一次
  `std/hamt` 的拒绝，所以镜像上这 18 个名字的 `# comptime: rejected` 保留，是真的。
- 镜像的 P5 于是是：标记 ⇔ 名字在 `comptime_rejects` 或 `comptime_refused_after_lowering` 里。
  `parse_int_radix` 的标记去掉；`char_unchecked` 的标记同理去掉（它在 `const` 里就是恒等）。

### 数值解析原语：声明，而不是路径

- 新增 intrinsic `float_of_decimal(s: String) -> Option[Float]`，`internal`（只有 std 能写），
  `rt = RtStrings`。它就是原来 `parse_float` 的运行时方法：对已校验、已修剪的串做 IEEE 754
  最近偶数的十进制到二进制转换。
- `std/fmt.atod` 校验后调 `float_of_decimal`。
- `parse_float` 进 `lowered_intrinsics`，失去 `rt`；lowering 对它无条件改写成 `std/fmt.atod`，
  `st.owner != "std/fmt"` 删除。
- 后端：JVM `dawn/rt/Strings.parse_float` 改名 `float_of_decimal`，C `dawn_parse_float` 改名
  `dawn_float_of_decimal`；两个发射器按约定从 intrinsic 名派生符号，不需要改。解释器的臂同样改名。
- 自举：种子阶段用种子自己的 std（`bin/dawn`、`build-release-jar.sh` 都给种子传种子 std），
  第二阶段才用工作树 std，所以 std 在同一刀里改调新 intrinsic 可行；以本地
  `scripts/selfhost-fixpoint.sh` 为准。

## 兼容性：这是修 bug，不是语言变更

`let f = parse_float; f(s)` 的接受集变窄：`f("1.5d")`、`f("0x1p3")` 从 `Some` 变 `None`。
spec §11 定义的接受语言从来就是那段 EBNF，直接调用一直照它办；函数值给出别的答案是实现缺陷，
所以按 bug 修，不走破坏性变更流程。spec §11 加一句写明「经函数值调用与直接调用是同一个函数」。
仓库没有 CHANGELOG 文件，版本说明在发版时写，这一句由发版人带上。

`let f = parse_int` / `parse_int_radix` 从编译期 panic 变成能跑，不影响任何能编过的程序。

## 门禁与负控

- `lower.dawn` 测试：对 `lowered_intrinsics()` 里每个有公开签名的名字构造函数值并 lower，断言输出里
  没有同名 `CIntrinsic`；`parse_float` 在 std/fmt 外降成 `std/fmt.atod` 调用，atod 内层降成
  `CIntrinsic("float_of_decimal")`。
- 端到端回归：`scripts/spike-native/` 语料加 `let f = parse_int`、`let f = parse_float` 与 `"1.5d"`，
  JVM 与 native 两个后端对同一份 `.expect`。
- 解释器三分测试；`builtin-decl-contract` 的 M1 接受三组，P5 按上面的定义。
- 负控：`parse_int` 加回 `interp_arms` → 三分测试红；撤掉 `lift_fn_value` 的改动 → 回归测试红；
  atod 改回调 `parse_float` → 编 std 时检查器报 parse_float 不可在 std/fmt 内作原语（见实测）。

## 不做的（理由）

- **intrinsic-parity 不读解释器。** 它读的是发射器的 `name == "..."` 链，那是测试够不到的一半；
  解释器的自测已经比它强：它不只对名单，还实际调用每个名字，确认「有臂」「拒绝」与表一致。
  在 intrinsic-parity 里再读一次解释器源码，只是多一个从源码文本解析的读者。
- **不在 `atod` 上加声明级标记**（#186 验收给的另一选项）。标记要 lowering 去读一个函数的属性，
  是一个新的语言面；一个 internal intrinsic 是已有机制（`char_unchecked`、`str_lower` 先例），
  调用点本身就写明了它是原语。
- **不改 `driver/builtin_mirror.dawn` 的 dump 去输出 lowered 组。** `check.py` 已经从源码文本读解释器的
  两个名单；lowered 组按同一读法从 `lower.dawn` 读，由 M1 的全集等式审计。这样不扩编译器的导出面。
- **不给 `parse_int_radix` 加解释器臂。** 它在 `const` 里本来就能折叠（经 std/fmt 的 Core），
  加臂就是 #185 要删的那种死臂。
