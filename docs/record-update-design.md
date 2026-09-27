# 记录更新进 Core：宽记录在 JVM 上复制再赋值

> 状态：**current**。2026-09-27，issue #257（分支 `fix/wide-record-update`）。裁决见 issue #257 的裁决评论，
> 调研（阈值探针、拒编清单、原型与性能）是那条评论所引的调研报告；本文记做法、取舍与实测。

## 问题

`Cx`（`selfhost/src/check/cx.dawn`，58 个字段）的每次更新 `Cx { ..cx, f: v }` 都降成一次 58 参构造器调用。
JDK 21 的 C2 表示不了那么多栈传参（JDK-8325467，只修在 JDK 26 b17，21u、25u 均无回移），于是
`check.cx$Cx::<init>` 报 `unsupported incoming calling sequence`，每个调用它的方法、以及每个内联了这种调用的方法都报
`unsupported calling sequence`，退回 C1 跑完整个进程。OpenJDK 21.0.11 上一次 `check selfhost` 有 21 条这样的日志。

x86_64、JDK 21 的精确阈值是 **54 个 JVM 实参**（含接收者；构造器 53 个字段可编、54 个起拒编），long 与 double 不另算；
JDK-8342156 记录过 x86_64 在 APX 改动后一度只剩 38；JDK 26 发布说明写的是「greater than 30」。aarch64 没有实测数据。

影响面：CI 的门禁 job 跑 GraalVM CE 21（顶层 Graal JIT，不受影响），受影响的是集群基准（OpenJDK 21 C2）、
playground 生产（发行版 OpenJDK 21，长驻进程）、release 构建矩阵与任何用普通 JDK 21 的用户。
调研实测：一次性 `check selfhost` 的上界约为零（同一 jar 在 JDK 21 与 26 上 6.54 s 对 6.68 s），稳态（bench-replay）
原型对基线在 JDK 21 上 0.82 到 0.95、在 JDK 26 上 0.92 到 1.04。

## 裁决：记录更新是 Core 的一个节点

`{ ..r, f: v }` 以前降成「`CCtor` + 每个保留字段一个 `CField` 投影」，Core 里没有「更新」这件事。
可两个后端都在从这个形状里把它认回来：native 的 `c/rc.dawn` 靠 `spread_rebuild` 认出「spread base 的 `let` + 尾部同构造子重建」
来提前释放旧记录（#30、#40）；JVM 要对宽记录换一种构造方式，也得认同一个形状。再在 JVM 后端加一处形状识别，
就是同一个语义被降级丢掉、再被两个后端各猜一遍。

本仓的规矩是 Core 携带语义、后端决定表示：运行时 intrinsic 表只说一个原语属于哪个运行时模块，
由各后端决定那是什么（[runtime-intrinsics-design.md](runtime-intrinsics-design.md)）。记录更新照此办理。

### 节点

```
CUpdate(base: CExpr, adt: Int, ci: Int, fields: List[CUpdField], ty: Ty)
CUpdField = { ty: Ty, value: Option[CExpr] }
```

- `fields` 是构造器 `ci` 的**全部**字段，按声明序；`value` 是写入的值，`None` 表示沿用 base 的值；`ty` 是字段的声明类型。
- 求值顺序：先 base，再按字段序求写入的值。书写序与字段序不同时，`lower_ctor` 照旧先把写入的值按书写序落到临时量
  （spec §4.3），所以节点里只剩字段序。
- lowering 总是先把 base 绑到一个专用局部量再交给节点，所以 base 在节点里是 `CLocal`，写入的值不会给它赋值。
  `core.update_as_ctor` 依赖这一点，非局部量直接 panic。
- 字段的声明类型挂在节点上，理由与 `CField` 自带类型相同：native 的 RC pass 要把保留字段拼成投影，它手里没有 ADT 表。
- `core.update_as_ctor` 给出节点对应的整构造器形式（每个保留字段是一个 `CField(base, …)`），
  按构造正好是节点出现之前 lowering 产出的那棵树。只会整体构造记录的后端（JVM 窄记录、native）用它。

### 各消费者

| 消费者 | 做法 |
|---|---|
| `ir/lower` | `lower_ctor` 有 spread 时产出 `CUpdate`，没有时照旧 `CCtor`；`densify` 先走 base 再按字段序走写入值（与原先首次出现序相同） |
| `ir/interp`（comptime） | 求 base，按字段序求写入值，复制字段表再替换，结果与整构造相同 |
| `ir/reach` | 记 ADT 的使用，走 base 与写入值；保留字段按声明类型记一次类型使用（与原先 `CField` 的走法相同） |
| `ir/coredump` | 新拼法：`update R/Ctor : T`，下挂 base，再每字段一行 `set i : T`（下挂值）或 `keep i : T` |
| `jvm/operand` | 窄记录：展开成整构造器再按 `CCtor` 处理，操作数暂存与以前逐字节相同；宽记录：base 与写入值作为 eager 操作数 |
| `jvm/emit` | 宽记录的更新与整构造走复制再赋值（下节）；窄记录的更新按整构造器发 |
| `jvm/codegen` | 宽记录的类去掉字段的 `ACC_FINAL`，加无参 `<init>`、私有拷贝构造与 `copy$` |
| `c/infer` | 各遍历按整构造器形式处理（它要的就是那个形式的需求：保留字段投影在消费位置） |
| `c/rc` | 更新在这里被整体构造：`rw` 把它展开成整构造器再计数；`spread_rebuild` 直接认 `CUpdate`，被调度的更新在提升时展开，嵌套的更新留作节点；认 `CCtor` 的臂只剩手写的整构造器重建（全编译器一处，见 [perceus-design.md](perceus-design.md)） |
| `c/emitc` | 不会见到它（rc 之后没有 `CUpdate`），见到即 panic |

Core dump（`__lower --dump`、`selfhost-core-diff.sh`）打的是 rc 之后的 Core，rc 把 `CUpdate` 展开成整构造器，
所以 dump 与以前逐字节相同；`update` 的拼法只在 rc 之前的 Core 上出现（测试与调试）。

## JVM 的表示

**宽度。** 具名常量 `jvm/codegen.JVM_ARG_LIMIT = 32`：Dawn 发出的方法接收的 JVM 实参（含接收者）必须少于它。
构造器接收者占一个，所以字段数 + 1 ≥ 32（即 ≥ 31 个字段）的记录是宽记录。取 32 而不是实测的 54，
是为了覆盖没测过的平台（JDK 26 发布说明「> 30」、APX 期间的 38）；代价只是多纳入 33 字段的 `HeaderProduct`。
全仓 ≥ 20 字段的记录只有这两个。

**宽记录的类。**
- 字段 `ACC_PUBLIC`，没有 `ACC_FINAL`（类本身仍是 final）。
- `public <init>()V`：只调父类构造器。它必须是 public：类文件是 V52，没有 nestmate，别的类（更新点所在的模块类）调不了私有构造器。
- `private <init>(L自身;)V`：逐字段 `getfield`/`putfield` 拷贝；`public copy$()L自身;`：`new; dup; aload_0; invokespecial` 拷贝构造。
  `copy$` 带 `$`，Dawn 的标识符里不会出现，不会和字段或方法撞名。
- 不生成全参构造器。

**发射。**
- 更新：`<base>; checkcast C; invokevirtual C.copy$; { dup; <值>; putfield C.f }*`，只写 `value` 是 `Some` 的字段，按字段序。
- 整构造（没有 spread，比如 `cx_new`）与 comptime 常量：`new C; dup; invokespecial C.<init>()V; { dup; <值>; putfield C.f }*`。
- 所以 jar 里不存在任何 ≥ 32 个实参的方法，由门禁守（下文）。

**窄记录**的更新按 `update_as_ctor` 展开成整构造器，字节码与改动前逐字节相同，用户程序不变。

**操作数栈。** 宽路径在求写入值时栈上压着新对象（整构造时以前压着 `new; dup` 和已求的实参，也是非空）。
写入值里有跳出循环的 `break`/`continue` 时，`jvm/operand` 的规则照旧：先把 base 与所有写入值按求值序暂存到局部量，
再复制、赋值，栈前缀与循环入口一致（[jvm-operand-jump-design.md](jvm-operand-jump-design.md)）。

### final 的取舍

去掉 `ACC_FINAL` 只发生在宽记录的类上：
- JMM §17.5 的 final 字段发布保证对它们不再成立。Dawn 值跨线程只能经 `use java` 交出去；编译器里唯一的例子是
  `main.dawn` 的 shutdown hook，经 `Thread` 构造与启动交接，启动本身建立 happens-before，不依赖 final 语义。
- HotSpot 今天不对普通实例 final 字段做常量折叠（`TrustFinalNonStaticFields` 默认关），所以今天没有 JIT 损失；
  JEP 500（JDK 26）在为将来信任 final 铺路，宽类拿不到那份将来的优化。
- 写 final 字段只能在声明类的 `<init>` 里（JVMS §6.5 putfield），更新点在别的类，所以去 final 是复制再赋值的前提。
  另一条路是每种更新形状一个构造器，`Cx` 的 465 个更新点有几十种形状，不取。

## 门禁

`scripts/method-size-gate.py` 加一条规则：非 vendored、非 `embed/`、非 test 块的方法，JVM 实参数（含接收者，
按描述符数，long/double 算一个）必须少于 32。同一遍读 class 文件，描述符本来就读了。见
[method-size-gate-design.md](method-size-gate-design.md)「实参数」一节。

## 实测

见分支报告与提交正文；落地后回填。

## 不做的（理由）

- **拆 `Cx`**：465 个更新点、至少 1769 个读点、64 个按源码文本读 `cx.` 的脚本要跟，只治 `Cx` 一个类型，
  用户程序里的宽记录照样撞墙。将来为可维护性拆是另一件事，别拿 C2 当理由。
- **换 JDK**：带修复的只有非 LTS 的 26、27；GraalVM 不发 26 到 28，工具链会分叉；修不好 playground 与用户的 JDK 21。
- **只在 JVM 后端按形状识别（调研的 a1）**：与 `rc.dawn` 已有的识别是同一件事的第二份拷贝，见「裁决」。
- **所有记录一律复制再赋值、一律去 final**（C# `with` 的做法）：会改所有用户程序的字节码，丢掉所有记录的 final 语义，
  窄记录没有测到收益。OCaml `{ r with … }` 也是按宽度切换（`transl_record`：小记录逐字段重建，大记录 `Pduprecord` 再 `Psetfield`）。
- **`Object[]` 或位掩码传宽参数**（Kotlin `copy$default` 式）：装箱 Int/Float、多一次数组分配。
- **K 取 54 写死**：只在 x86_64/JDK 21 实测过。
- **Core dump 在 rc 之前打**：dump 的职责是看 JVM 读不到的那部分（`CDup`、`CSDrop`、`CParam.mode`），那部分只在 rc 之后存在。
