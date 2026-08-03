# A 线：收缩 JVM 后端的可信底座

> 状态：**in progress**（2026-08-03 立项，任务 #127；K-A0/K-A0.5/K-A1/K-A3/K-A5/K-A4 已落地，下一刀 K-A7）。本文是 A 线的动工前设计：
> 它把一次 V49 可行性审计的结论、量出来的代价、被推翻的预设，和刀表与顺序落进仓库。
>
> **为什么在这儿而不在别处**：这批证据原先躺在 `/tmp` 的备忘录里，已经因为一次 WSL
> 重启丢过 623 行。审计全文见 `~/workspace/notes/v49-audit.md`（330 行，不在仓库里，
> 本文摘它的结论与证据等级）。
>
> 上游：[llvm-backend-research.md](llvm-backend-research.md)、
> [native-backend-plan.md](native-backend-plan.md)、
> [runtime-intrinsics-design.md](runtime-intrinsics-design.md)、
> [bootstrap.md](bootstrap.md)。

## 0. 这条线要解决什么

JVM 后端的**可信底座**里有三样东西不是从这棵树里构建出来的：

| 东西 | 体量 | 源码在哪 | 它干什么 |
|---|---|---|---|
| `dawn/tool/AdtClassWriter` | 1 个类，5,148 B | **不在工作树**，只在 `kotlin-final` tag | **写 class 文件** |
| `org/objectweb/asm` | 38 个类，253,894 B | 第三方（Maven） | **写 class 文件** |
| `coursierapi` | 2,409 个类，10,057,897 B | 第三方（Maven） | 解析/下载依赖 |

三者都靠 `--vendor` 从**正在跑的编译器自己的 classpath**（也就是上一代种子 jar）
按字节抄进新 jar，代代相传。`selfhost-fixpoint.sh` 的 B==C 对此完全失明：
固定点证明的是编译器复现自己，一个被替换过的编译器同样会忠实地复现自己
（同 `codebase-audit.md` 的 BOOT-01/BOOT-03）。

A 线的终点是让这三样**要么有源码、要么有账**。中途的每一步都必须是可逆的。

**度量方法**（本节数字的产生命令）：

```bash
# 类数与字节数
J=.dawn/seeds/v0.47.0/seed.jar
for p in dawn/tool org/objectweb/asm coursierapi; do
  unzip -l "$J" "$p/*" | awk '/\.class$/{n++; s+=$1} END{print n, s}'
done
```

## 1. 证据等级约定

本文每条断言标注来源，**不要把估算读成实测**：

- `[实测]` —— 在这台机器上真跑出来的数。
- `[扫描]` —— 自写的 classfile 常量池 / 逐条字节码扫描器读出来的（扫描器与 `javap -c`
  在 14 个类上逐类对拍一致）。
- `[grep]` —— 只读源码得出的。
- `[估算]` —— 未实装，只能推算；标注方法与不确定度。
- `[推论]` —— 从上面几类推出来的**排序/取舍判断**，不是任何人测出来的。

## 2. V49 审计：结论

> 全文与逐项证据在 `~/workspace/notes/v49-audit.md`。这里只摘可动工的结论。

「V49」= 把发射的 classfile major 版本从 61（Java 17）降到 49（Java 5）。
动机是 JVM 规范的一条硬分界：**major < 50 用推断式校验器，不要求 `StackMapTable`；
major ≥ 50 强制要求**。降到 49 就可以整块不发帧——那是今天 **15.3% 的类字节**。

**V49 能走** `[实测]`：全仓 893 个 selfhost 发射类 + 124 个 site 语料类，降到 major 49
并剥掉 `StackMapTable` 之后，用仓库自己的门禁 `scripts/classfile-verify/Verify.java`
（`Class.forName(initialize=true)` 强制链接 = 强制校验每个方法体）在 GraalVM 21 和
JDK 26 上跑，**两个 JVM 上都是 0 illegal**。

**唯一拦路构造是 `invokedynamic`（149 处）** `[扫描]`。除它以外扫遍常量池 tag 与
63,166 条指令，没有任何其它需要 major ≥ 50 的东西：接口 default/static 方法 0 处、
`invokestatic`/`invokespecial` 打在接口上 0 处、`ldc` MethodType/MethodHandle 0 处、
`ConstantDynamic` 0 处、`NestHost`/`Record`/`PermittedSubclasses` 0 处、
`jsr`/`ret` 0 处、`tableswitch`/`lookupswitch` **0 条**。
字符串拼接走的是 `String.concat` 链而不是 `makeConcatWithConstants`（`emit.dawn:1923`），
所以没有第三处 indy。

### 2.1 三个必须知道的坑

1. **死常量也会炸** `[实测]`。把 indy **指令**换掉、`MethodType`/`MethodHandle`
   **常量池条目**留着，V49 下 29 个类全部
   `ClassFormatError: Class file version does not support constant tag 16`。
   JVM 在 parse 阶段校验**整个常量池**，不管有没有被引用。
   → 任何「先留着以后再清」的过渡方案会立刻撞墙。

2. **49 是地板，不是自由选择** `[扫描]`+`[实测]`。`jvmhelp.dawn:47` 的
   `visitLdcInsn(Type.getObjectType(...))`（支撑 `cast`）在 jar 里有 12 处
   `ldc <Class>`，规范要求 major ≥ 49。（实测把类降到 48，HotSpot 居然照样放行——
   它没强制这条检查。**别依赖这个**。）

3. **降版本不会自动省掉帧** `[实测]`。ASM 在 **V49 + COMPUTE_FRAMES** 下会改写出
   CLDC 老格式的 `StackMap` 属性，**比 `StackMapTable` 还大**（同一方法 147 B vs
   140 B vs 无帧 113 B），JVM 在 V49 下直接忽略它。必须同时把写死的 `ClassWriter(2)`
   换成 `ClassWriter(1)`（COMPUTE_MAXS）——**而那正好在没有源码的那个类里**（§0）。
   （§5.1 复验并收窄了这条：要换的只是构造器传给 `super()` 的 flag，**不需要**先把
   那个类重写一遍，所以「两件事必须一起做」只对 K-A4 内部成立，不构成对 K-A3 的前置。
   §5.6 又把它收窄了一次，方向相反：那个 flag **改不了**（无源码），只能**绕开**——
   K-A4 走的是它已有的静态入口 `plain(int)`，代价是四个发射器的全部调用点。）

### 2.2 校验器真的在跑

故意把一个 V49 方法的首字节改成 `areturn` 制造类型错误 `[实测]`：

```
java.lang.VerifyError: (class: Tbad, method: loop signature: (I)I)
                       Unable to pop operand off an empty stack
```

`(class: X, method: Y signature: Z)` 这个措辞是**老推断式校验器专有**的消息格式
（分裂校验器输出带 `Exception Details:`/`Location:`/`Bytecode:` 的长格式）。
→ 推断式校验器在 GraalVM 21 与 JDK 26 上都活着并且确实在工作，不是被跳过。

`native-image` 也接受 V49 `[实测]`：一组 V49（无帧、无 exotic 常量）的类喂给
`native-image --no-fallback`，11.8s 构建成功，二进制跑出正确结果。
这条最容易被忽略的死角没被堵死。

## 3. 代价：量出来的三个数

### 3.1 需要新增多少个类：**149**（+16.7%）

计法：解析 `BootstrapMethods`，对每处 indy 取 (实现方法 handle, 目标接口) 二元组去重。
显式闭包类正是一对一对应它。

| 语料 | 今天的类数 | indy 站点 | 去重后 = 需新增 | 增幅 |
|---|---|---|---|---|
| **selfhost** | 893 | 149 | **149** | **+16.7%** |
| `site` | 124 | 53 | 53 | +42.7% |
| `packages/json` | 73 | 17 | 17 | +23.3% |
| `examples/calc.dawn` | 68 | 17 | 17 | +25.0% |

**去重完全没省**（149→149，复用直方图 `{1:149}`）：每个 lambda 站点的实现方法都不同。
bootstrap 只用了 `LambdaMetafactory.metafactory` 一种（无 `altMetafactory`），下降逻辑单一。
目标接口只有 `Fn1`×104 / `Fn0`×23 / `Fn2`×17 / `Fn3`×4 / `Fn5`×1。
捕获元数直方图 `{0:81, 1:32, 2:18, 3:11, 4:4, 5:1, 6:1, 7:1}`——**81/149 零捕获**，
可做成单例静态字段。

> **K-A3 落地后的实测**：预测全中。selfhost 发射出 **149 个 `dawn/fn/` 类**，其中
> **81 个零捕获单例、68 个带字段**——与上面这份直方图逐项对上。`dawn/sam/` **0 个**，
> 也与「selfhost 里 0 处是 SAM bridge」一致（SAM 路径由 `packages/web` 等语料覆盖）。
> `examples/calc.dawn` 68 → **85** 个类，正是 +17。
>
> 类数从 **895 → 1046（+151）**，比 149 多两个：`emit$ClosB`/`emit$SamC` 两个新记录
> 类型。另有一个字典类因 ADT id 位移改名（`…$Adt15729` → `…$Adt15768`）——**changed
> 与 ADT-shifted 是两个桶**，这一个属于后者。全部 +151 已逐个交代，没有余数。

### 3.2 jar 体积：**净赚 −13.3%**

`[实测]` 目录级真实字节 + `[估算]` 闭包类那 61 KB（用 javac 编出的等形状类按捕获
元数直方图加权，均值 410 B/类，±20% 量级，对总数影响 < 0.5%）：

| | raw | zipped |
|---|---|---|
| 今天 (V61) | 3,122,794 | 1,351,682 |
| 降 V49（剥 StackMapTable/BootstrapMethods） | 2,647,538 (−15.2%) | 1,251,268 (−7.4%) |
| **净值**（再加 149 个闭包类） | **2,708,681 (−13.3%)** | **~1,288,668 (−4.7%)** |

单 `StackMapTable` 一项就占 478,044 B = **15.3% 的类字节**（2,292 个属性）。

> **K-A3 落地后的实测**（非 vendor 类，`build/dawn-selfhost.jar`）：
>
> | | 类数 | raw | zipped |
> |---|---|---|---|
> | K-A3 前（V61 + indy） | 895 | 3,126,865 | 1,241,633 |
> | **K-A3 后**（V61 + 显式闭包类） | **1046** | **3,188,303** (+2.0%) | **1,276,789** (+2.8%) |
>
> **闭包类那 61 KB 的估算是准的**：实测 +61,438 B / 151 个类 = **407 B/类**，
> 估算值是 410 B/类。上表「净值 −13.3%」里唯一的估算成分因此可以按实测收紧——
> 但**剩下的 −15.2% 要等 K-A4**，今天还在 V61，`StackMapTable` 一个字节都没省。
> 换句话说这一刀单独看是 **+2.0%**，收益全部押在下一刀。

> **K-A4 落地后的实测**（同一台机器，同为非 vendor 类，两个 jar 只差这一刀）：
>
> | | 类数 | raw | zipped |
> |---|---|---|---|
> | K-A4 前（V61 + COMPUTE_FRAMES） | 1046 | 3,190,833 | 1,277,843 |
> | **K-A4 后**（V49 + COMPUTE_MAXS） | **1046** | **2,699,473** (−15.40%) | **1,172,131** (−8.27%) |
>
> 预测 raw −15.2% / zipped −7.4%，实测 −15.40% / −8.27%。类数一个没变——这一刀不造类，
> 只是不再写帧；1046 个发射类里 `StackMapTable` **0 个**、CLDC `StackMap` **0 个**、
> `BootstrapMethods` **0 个**、major 版本全部 49（逐个类读头四字节之后的两字节数出来的）。
>
> 唯一的类数差是 −1 个**方法**（`rtclasses.supers_of`），不是类。
>
> 顺带一条对照：vendored 的 `org/objectweb/asm` 那 38 个类**本来就是 major 49**。
> 这条路线上跑得最久的一份 v49 字节码，是我们自己一直在依赖的那个库。

### 3.3 启动时间：**基本对冲**

两个反向作用都实测了，但**加起来那一步是估算**：

**(a) 推断式校验器更慢**（强制链接全部 893 个类，中位数 n=9）`[实测]`：

| | V61 分裂校验 | V49 推断校验 | 差 |
|---|---|---|---|
| GraalVM 21 | 190.4 ms | 230.5 ms | +40.1 ms (+21%) |
| JDK 26 | 156.5 ms | 191.5 ms | +35.0 ms (+22%) |

这是**最坏情况**：真实运行只链接实际用到的类，不会全量。

**(b) 省掉 LambdaMetafactory 引导**（149 个 lambda vs 149 个显式类，中位数 n=11）`[实测]`：

| | 149× LMF | 149× 显式类 | 裸 JVM | 显式类净省 |
|---|---|---|---|---|
| GraalVM 21 | 84.5 ms | 65.8 ms | 41.3 ms | −18.8 ms |
| JDK 26 | 71.3 ms | 36.0 ms | 16.6 ms | −35.3 ms |

**(a)+(b)** `[估算]`：JDK 26 上几乎完全抵消（+35.0 / −35.3），GraalVM 21 上净亏
约 21 ms（占 `dawn --version` 106.2 ms 的 ~20%，占 `dawn build examples/calc.dawn`
750.2 ms 的 ~3%）。这是**两个独立微基准的加减，不是端到端实测**；真实值大概率
优于此估计，因为全量强制链接是最坏情况。**实装后必须端到端重测**。

> **K-A3 落地后：(b) 已是端到端实测**，(a) 仍要等 K-A4。同一台机器、GraalVM 21、
> `java -jar` 直调（绕开 `bin/dawn` 的时间戳检查），两个 jar 只差这一刀：
>
> | | K-A3 前 | K-A3 后 | 差 |
> |---|---|---|---|
> | `dawn --version`（n=11） | 54 ms | 58 ms | **+4 ms (+7%)** |
> | `dawn build examples/calc.dawn`（n=9） | 724 ms | 694 ms | **−30 ms (−4.1%)** |
>
> **两个方向相反，而这不是噪声，是两种负载**：`--version` 几乎不求值闭包，省不到
> LMF 的引导，只白付了 151 个新条目的 jar 目录与类加载开销；真实编译负载里闭包用得
> 密，LMF 引导省下来就压过了。**微基准的 −18.8 ms 因此偏保守**——端到端量到 −30 ms。
>
> 一并纠正上面括号里的基线：`dawn --version` 在本机是 **54 ms** 而非 106.2 ms，
> `dawn build examples/calc.dawn` 是 **724 ms** 而非 750.2 ms。差别在审计走 `bin/dawn`
> 包装脚本（含时间戳检查与一次 shell 启动），本表直调 `java -jar`。**同一份对比里
> 两边用同一种调法**，所以差值仍然可比。

> **K-A4 落地后：(a) 也是端到端实测了**，§3.3 整节不再有估算成分。同机同调法，
> 两个 jar 只差这一刀：
>
> | | K-A4 前(V61) | K-A4 后(V49) | 差 |
> |---|---|---|---|
> | `dawn --version`（n=13） | 57.5 ms | 58.6 ms | **+1.0 ms (+1.8%)** |
> | `dawn build examples/calc.dawn`（n=11） | 713.6 ms | 733.1 ms | **+19.5 ms (+2.7%)** |
>
> **微基准的 +40.1 ms 是最坏情况，真实负载上只兑现了一半**——正如上面预告的：
> 全量强制链接 893 个类不是任何真实运行会做的事。`--version` 几乎不链接什么，
> 所以几乎不付这笔钱。
>
> 与 K-A3 的 −30 ms 合起来，两刀在真实编译负载上净赚约 10 ms。**但这个加减跨了
> 两个 release 的基线**（K-A3 那次量的是 724→694，本次是 713.6→733.1，中间还隔着
> v0.48.0），只当量级看，不要当同一条曲线上的两点。

## 4. 被推翻的预设

这一节是本文最该先读的部分。以下每条都曾被当成事实写在文档或备忘录里。

| # | 曾经的说法 | 实际 | 证据 |
|---|---|---|---|
| 1 | 「SAM bridge 是 indy 之外的第 3 件事」 | 它**就是**一处 indy。`visitInvokeDynamicInsn` 精确 2 处：`emit.dawn:656`(SAM 转换)、`emit.dawn:1494`(闭包实例化)。备忘录给的 334/658/1497 是 `Handle.new` 的行号 | `[扫描]`+`javap` 对拍 |
| 2 | 「只要去掉 indy 指令就能降版本」 | 不行，残留常量池条目是硬 `ClassFormatError`（§2.1.1） | `[实测]` |
| 3 | 「降到 V49 就自动省掉 StackMapTable」 | 不会，ASM 改写出更大的 CLDC `StackMap`（§2.1.3） | `[实测]` |
| 4 | 备忘录与任务书都没提 `rtclasses.dawn` | 它是**全仓最大的字节码生产者**（222 处 `visitMethodInsn` vs `emit.dawn` 的 77 处，2700+ 行）。改发射器时它不能漏 | `[grep]` |
| 5 | 「V49 是自由选择」 | 49 是**地板**（§2.1.2） | `[扫描]`+`[实测]` |
| 6 | 「契约表叫 `emit.dawn` 的 `rt_intrinsic_target`」 | 那个名字今天不存在。契约在 `types.dawn:1645-1806`（`Rt`/`Intr`/`intrinsics()`），`emit.dawn` 只剩 `rt_class`(586)/`rt_intrinsic_class`(598) | `[grep]` |
| 7 | 「真要第二后端，得先有 backend-neutral 的 lowered IR 与 FFI capability」 | 第二后端**已经在跑并自举了**（`scripts/native-fixpoint.sh` B==C）。FFI capability 不是前置：全仓 `use c` **0 处**，native 靠**拒绝** `use java`（`emitc.dawn:575`）+ 二十来个 io intrinsic 就走完了自举 | `[grep]` |
| 8 | `emitc.dawn` 文件头「闭包、字典、集合尚未实现」 | 只有 `CForeign` 还成立。闭包在 `emit_closure`、字典在 `slot_shape`/`dict_line`、集合走 `std/pvec`+`std/hamt` | `[grep]` |
| 9 | `runtime-intrinsics-design.md` §11 举 `jarw.dawn` 当「Dawn 写二进制写入器」的先例 | 半错：`jarw.dawn:10` 用的是 `java.util.zip.ZipOutputStream`。真正的先例是 `packages/inflate`（728 行纯 Dawn gzip/zip，`use java` 0 处） | `[grep]` |
| 10 | `CLAUDE.md`「提交信息 `type(scope): 中文摘要`」 | 这条是**写本文时自己撞上的**：照它写会写出一个 2026-07-25 之后再没出现过的格式。`git log --format='%s' -200` 里中文摘要 0 条（历史上 126 条），`type(scope):` 前缀近 200 条里 4 条。实际是英文祈使句一行 | `[实测]` |

| 11 | 「不需要覆写 → 不需要 `AdtClassWriter` 这个子类 → 它直接消失」 | **半错**。子类确实消失（`extends ClassWriter` 与覆写一起删），但类不消失：它另有一半跟帧无关的 null 适配器，因为 **Dawn 没有 null** 而 ASM 的 `signature`/`interfaces` 可空。§5.1 | `[实测]`+`[grep]` |
| 12 | 刀表把「捞回/重写 `AdtClassWriter`」（K-A1/K-A2）排在闭包下降 K-A3 **之前** | 顺序错，且 K-A2 整刀取消。要改的只是构造器传给 `super()` 的 flag，K-A3 完全不碰它；重写一个 K-A4 之后就不存在的 classfile writer 是白做。§5 | `[实测]` |
| 13 | （无人提过）COMPUTE_FRAMES 与 COMPUTE_MAXS 只差算不算帧 | 还差**死代码改写**：前者把不可达代码换成 `nop; athrow`，后者原样保留。V49 推断式校验器只走可达代码，故无害——但这是 K-A4 独有的风险面 | `[实测]` |

| 14 | （无人提过）「闭包下降 = 把 indy 换成等价的类」 | 漏了**访问权限**：提升出来的 lambda 体是 `private`，LMF 拿的是带私有权限的 `Lookup` 够得着，独立类文件够不着。改完编译器读自己第一个文件就 `IllegalAccessError`。**`classfile-verify` 对此失明**——权限是链接期解析才查的，`Class.forName(initialize=true)` 强制不到方法体里的符号引用。§5.5 | `[实测]` |

| 15 | 「`AdtClassWriter` 的 null 适配器那半**必须**是手写 Java，因为 Dawn 没有 null」 | **半错，而且错在关键处**。「Dawn 没有 null」约束的是 **Dawn 源码**，不约束**发射层**：`rtclasses.dawn:2263` 今天就在发 `ACONST_NULL`，`rtclasses.dawn:1147/1198/1284/1344` 今天就在发 `ANEWARRAY <宿主类型>` 并把数组喂给 Java 方法——正是这五个适配器需要的全部指令。**所以它可以由 Dawn 自己发射**（K-A7），从「源不在树上」变成「树内源可重建」 | `[grep]`+`[实测]` |
| 16 | （无人提过）`scripts/classfile-verify` 对 **selfhost 语料**是空转的 | 它的 `URLClassLoader` 双亲优先，而工具链 jar 必须挂在 parent 上（selfhost 的类要引 vendored ASM/coursier）。selfhost 发射出的类名与 jar 里的**逐个同名**，于是每一个都从 jar 里解析，`-o` 那个目录**根本没被读**——那个语料上这道门禁**无论 `__emit` 写出什么都不会红**。已改成 child-first 并做了红演示。§5.6 | `[实测]` |
| 17 | 「V49 是单向门（D5 不可逆承诺点）」 | **可能高估了**。自算 StackMapTable 的难度是从 **ASM 的处境**继承来的（它面对加载不了的类，只能外挂公共超类型 oracle）；Dawn 刚从 AST 建完整个类型层次，查自己的符号表就能答。若成立，回 ≥50 随时能回。**这条是推理，未实测**，K-A4 不依赖它 | `[推论]` |

第 6/7/8/9/10 条已随 K-A0 改掉（见 §6）。第 11/12/13 条是 K-A3 动工前复验刀序时测出来的，
已改进 §5；第 14 条是 K-A3 落地时撞上的，记在 §5.5；第 15/16/17 条是 K-A4 落地时的，
记在 §5.6（15 另见 §5.7 的 K-A7、17 另见 §5.8）。

**这批过期陈述的共同根因**：`scripts/doc-check.py` 只检查 `docs/` 下的状态标记、
链接与锚点，**不检查任何源文件头的事实陈述**。第 8 条能在一个自举成功的后端里
活着，就是这个缺口的直接产物。

## 5. 刀表与顺序

| 刀 | 做什么 | 可逆性 | 状态 |
|---|---|---|---|
| **K-A0** | 文档校正 + 本文 | 不碰发射的字节 | 本次 |
| **K-A0.5** | 给无源二进制上 checksum | 只加门禁 | 本次 |
| **K-A1** | 从 `kotlin-final` 捞回 `AdtClassWriter.java`，**先只当参照读**，不进主干 | 不改代码 | **已做**（§5.1） |
| **K-A3** | 闭包下降：`emit.dawn:1494` + `emit.dawn:656` → 显式类；81 处零捕获做单例。**仍在 V61 + COMPUTE_FRAMES 下做** | **Emit-Change，不可逆** | **已做**（§5.5） |
| **K-A5** | 门禁：发射的常量池不得出现 tag 15/16/17/18 | 只加门禁 | **已做**（随 K-A3） |
| **K-A4** | `jvmops.dawn` `V17 = 61` → `V49 = 49`；改走 `AdtClassWriter.plain(COMPUTE_MAXS)` 的静态适配器；删 `rtclasses.supers_of` 与整条 `supers` 参数链 | **Emit-Change**，D5 承诺点 | **已做**（§5.6） |
| **K-A7** | **让 Dawn 自己发射那五个 null 适配器**（`dawn/rt/Asm`），`dawn/tool` 整体退出 `--vendor` | 三期种子纪律，可回退 | 待（§5.7） |
| **K-A6** | 端到端重测 §3.3 的启动数（那两个数是微基准加减） | 只测量 | **已做**（随 K-A4，见 §3.3） |

**K-A2（用 Dawn 重写 `AdtClassWriter`）已取消。** 见 §5.1：K-A4 之后没有 classfile
writer 可重写——`AdtClassWriter` 里跟写 classfile 有关的部分整块不再被调用，剩下的是个
null 适配器。**原 K-A4b（把它"收成"静态适配器）也取消**：K-A4 之后它已经只被当静态适配器
用了，那份二进制**一个字节都没少**，"收"无处可收。真正要做的是 K-A7——**从树内源重建它**，
而不是把它缩小到能接受的程度。§5.7

**版本下降（K-A4）为什么排在闭包下降（K-A3）之后**：因为 §2.1.1——先降版本、
后清 indy，中间那个状态是硬 `ClassFormatError`，仓库会处在编不出东西的状态。
反过来先清 indy 再降版本，每一步都留在可运行状态。

**为什么 K-A1/K-A2 不再排在 K-A3 之前**（原表的顺序，已推翻）：那个顺序假设
「要拿到体积收益，得先把 `AdtClassWriter` 弄进主干」。§5.1 的实测把这个前置拆了——
需要改的只是**构造器传给 `super()` 的那个 flag**，而 K-A3 完全不碰它。把捞源码/重写
排在闭包下降之前，是在为一件后来不需要做的事阻塞主线。

### 5.1 `AdtClassWriter` 会消失多少：实测复验 `[实测]`

原文的推论链是：`getCommonSuperClass` 只被 COMPUTE_FRAMES 调用 → V49 不要
`StackMapTable` → COMPUTE_MAXS 就够 → 不需要覆写 → **`AdtClassWriter` 整个消失**。
**前四环成立，最后一环不成立。**

**复验方法**：ASM 9.7.1（仓库钉的同一版，`selfhost/dawn.toml:10`）直接生成一个类，
方法里有 (a) 两个**不在 classpath 上**的引用类型在分支汇合点合流（逼出公共超类求解）、
(b) 一个带回边的 int 循环（逼 COMPUTE_MAXS 真干活）。`getCommonSuperClass` 覆写成
只记账再委托。四个组合各生成一次，再用裸 `DataInputStream` 读常量池与属性名
（不经 ASM，避免用被测对象验被测对象），最后 `Class.forName(initialize=true)` 强制链接。

| flag | major | `getCommonSuperClass` 调用 | 帧属性 | 字节 | 链接 |
|---|---|---|---|---|---|
| COMPUTE_FRAMES | 61 | **1** | `StackMapTable` 7+7 B | 399 | ✅ |
| COMPUTE_MAXS | 61 | **0** | 无 | 320 | ❌ `VerifyError: Expecting a stackmap frame at branch target 14` |
| COMPUTE_FRAMES | 49 | **1** | `StackMap`(CLDC) 19+18 B | 417 | ✅ |
| **COMPUTE_MAXS** | **49** | **0** | **无** | **320** | ✅ |

GraalVM 21 与 JDK 26 上结果逐字相同，`pick`/`loop` 都跑出正确值。

四条读数：

1. **`getCommonSuperClass` 在 COMPUTE_MAXS 下调用 0 次**，跟 major 无关。覆写确实是死重。
2. **V49+COMPUTE_FRAMES 的 CLDC `StackMap` 比 V61 的 `StackMapTable` 大**（19+18 vs 7+7）
   —— §2.1.3 复现。
3. **V49+COMPUTE_MAXS 一个帧属性都不写**，且与 V61+COMPUTE_MAXS **字节数相同**（320）：
   两者只差版本号那两个字节，帧的省略是 flag 干的，不是版本干的。
4. **`M61` 是负控**：同一份 COMPUTE_MAXS 字节在 V61 下 `VerifyError`。没有它，「V49 能过」
   只能证明这个类太简单，证明不了帧真的被省掉了。

**顺带测掉一条没人提过的差异**：COMPUTE_FRAMES 会把不可达代码改写成 `nop; athrow`，
COMPUTE_MAXS 不会（实测 `javap`：前者 `nop/athrow`，后者原样保留 `iload_0; areturn`
这个类型错误的死代码）。V49 的推断式校验器只走可达代码，两个 JVM 上都放行 `[实测]`。
→ 这条差异在 V49 下无害，但它是 K-A4 独有的风险面，记在这里免得将来当成新 bug 查。
**K-A4 落地时在生产语料上两侧对照复验了这条（§5.6），828 个方法带死代码，全部放行。**

**最后一环为什么断**：`AdtClassWriter` 干**两件**事，只有一件跟帧有关。

- 跟帧有关的一半：`supers` 字段、两个构造器、`chain()`、`getCommonSuperClass()` 覆写，
  连同 `rtclasses.dawn` 的 `supers_of`（就是 Kotlin 的 adtSupers）。**Dawn 这侧的
  `supers_of` 是净删；那个类里的对应部分只是不再被调用，字节一个没少**（§5.6）。
- **活下来的一半**：`begin`/`beginWithInterface`/`field`/`method` 四个实例方法与
  `plain`/`beginOn`/`beginOnWithInterface`/`fieldOn`/`methodOn` 五个静态方法。它们存在的
  理由写在类的 javadoc 里，和帧毫无关系：**Dawn 没有 null**，而 ASM 的 `visit`/
  `visitField`/`visitMethod` 的 `signature`/`interfaces` 形参是可空的。

所以准确的说法是：**「一行 classfile writer 都不用写」成立**（K-A2 因此取消），
**「`AdtClassWriter` 直接消失」不成立**。K-A4 之后没人再实例化它，`rtclasses.dawn`
早就在走的那条静态路径成了唯一的路径（`AdtClassWriter.plain(...)` + `beginOn`/`methodOn`）。
但**它仍然 `extends ClassWriter`、仍然带着那份覆写**——死码不等于删掉，5,148 字节一个没少。
那仍是一份无源码的手写 Java 待在可信底座里。

（原文这里写的是「要让它彻底归零，得先让 Dawn 能跨 FFI 传 null，那是另一条线」。
**这句话是错的**：null 只是 Dawn **源码**拼不出来，**发射层**可以发 `ACONST_NULL`。
归零的路是让 Dawn 自己发射这个适配器——见 §4 第 15 条与 §5.7 的 K-A7。）

这一半的净删也是不选另一条路的理由：

### 5.2 为什么不自己算 StackMapTable

（V49 实测能走，所以这条只是备选。结论是**它明显更难**。）

**起点是零** `[grep]`：全仓 `visitFrame` **0 处**，`visitMaxs` 几乎全是占位的 `(0,0)`。
发射器是对 `CExpr`/`CStmt` 的单遍树遍历，**没有基本块图、没有活跃性分析、没有抽象栈模型**。
拿掉 COMPUTE_FRAMES，当前代码库里没有任何东西能顶上。

**好消息：控制流确实简单** `[扫描]`——有 Code 的方法 5,478 个，含 ≥1 分支的 2,288 个
（41.8%），分支指令 43,822 条，`tableswitch`/`lookupswitch` **0 条**，
**有异常表的方法仅 8 个**（占 0.15%），没有 `jsr/ret`。

**坏消息：难点不在控制流，在类型格**——要实现公共超类型求解（而且要对**尚不存在的
生成类**求解，不能 `Class.forName`，所以 adtSupers 表反而得留下并加强）、
`uninitialized`/`uninitializedThis` 追踪、long/double 双槽配对、帧的增量编码。
几百行有微妙不变式的代码，且错误模式恶劣：帧算错不是崩溃，是 `VerifyError`，
**且只在恰好走到那条路径的类上暴露**。

**判断**：V49 是「删掉一个需求」（149 个平凡闭包类 + 一个 ClassWriter flag），
自算帧是「新增一个有微妙不变式的子系统」。两条路都要碰 `AdtClassWriter`，
但 V49 那边是**减法**。

### 5.3 `scripts/classfile-verify` 能兜住吗——能，但有边界

- **能**：它 `Class.forName(initialize=true)` 强制链接，HotSpot 在链接时校验整个类的
  所有方法体。帧写错 = `VerifyError` = 门禁 `bad>0` = exit 1。这是真安全网。
- **边界一**：它只覆盖**语料实际发射出的代码形状**（8 个语料；审计实测了其中 4 个
  = 1,158 个类）。语料里没有的形状（比如将来引入 switch）它管不到。
- **边界二**（关键）：**它今天校验的是 ASM 算的帧，不是发射器自己算的帧**。
  对发射器的帧推理零覆盖——只有在 K-A4 之后（校验的变成「根本没有帧」）它才开始
  对这条路线有意义。
- **边界三**（K-A4 落地时才发现，已修）：它的加载器**双亲优先**，而工具链 jar 必须挂在
  parent 上，selfhost 语料的类名与 jar 逐个同名——于是那 1046 个类**从来是从 jar 解析的，
  `-o` 目录根本没被读**，那个语料上这道门禁不会红。加载器已改成 child-first 并做了红演示。
  §4 第 16 条、§5.6。
- **边界四**：它 `Class.forName(initialize=true)` 只强制到**类初始化**，不强制解析每个
  方法体里的符号引用，所以**访问权限一类的错误它抓不到**（K-A3 的 `ACC_PRIVATE` bug 就是
  它没抓到的，§5.5；记在 #129）。这就是为什么每一刀都必须**真编一遍东西**，不能只信门禁。

### 5.4 一条长期战略风险，不是技术障碍

`[网络检索]` 没有找到任何 JEP 或 OpenJDK 计划移除 45–49 的 classfile 支持，
也没有移除推断式校验器的计划。HotSpot 的规则始终是「< 50 用推断式，≥ 50 用
StackMapTable」，JDK 26 上实测仍然如此。

**但风险不是零**：推断式校验器是 OpenJDK 想甩掉的历史包袱；`javac` 早已不能产出
< 52。一旦 Dawn 走 V49，它会成为**极少数**仍在生产 v49 的现代工具，生态上是孤岛。
这条要写进决策，不要装作不存在。

### 5.5 K-A3 落地记（闭包下降）

**做了什么**：`gen_cclosure` 与 `emit_sam_conversion` 不再发 `invokedynamic`。
前者发 `dawn/fn/<模块>$<n>`——`implements dawn/rt/FnN`，捕获进字段，`apply` 里
`unerase` 参数 → 调提升出来的静态体 → `box_ty` 返回值；零捕获走 `singleton_scaffold`
的 `INSTANCE`。后者发 `dawn/sam/<模块>$<n>`，只转发给本来就在发的桥。
`ClassWriter` 的 flag、classfile 版本、帧，**一律没碰**。

**LMF 干的适配就是 `unerase`/`box_ty` 这一对**，而且它已经在仓库里了——`gen_cdynamic`
在调用侧反着写同一对（先 `box_ty` 参数、后 `unerase` 结果）。这一刀没有新增类型逻辑，
只是把同一份适配挪到被调用侧。

**三件实测教训**：

1. **`private` 是这一刀唯一的真 bug，而且门禁抓不到它**。提升出来的 lambda 体与 SAM 桥
   一直是 `ACC_PRIVATE + ACC_STATIC`：LMF 拿到的是**带私有权限的 `Lookup`**，它 spin 出
   的类够得着；独立的类文件够不着。改完第一次跑就是
   `IllegalAccessError: class dawn.fn.std$io$1 tried to access private method std.io.lambda$1`
   ——**栈顶是 `std.io.read_file`，编译器读自己的第一个文件就炸**。
   值得记的是：**`classfile-verify` 对此完全失明**。访问权限是**链接期解析**才检查的，
   而它 `Class.forName(initialize=true)` 只强制到类初始化，不强制解析每个方法体里的
   符号引用。抓住它的是「跑一次真的编译」，不是任何静态门禁。
2. **`new` 得在捕获求值之前压栈**（构造器要接收者在实参底下）。原来 indy 是把捕获当
   实参、指令在最后，顺序天然对；换成 `new/dup` 就得提前。捕获类型是 `cex_ty` 的纯函数，
   所以能在发射任何字节之前算出来，这一步才成立。SAM 那边受值已经在栈上，
   用 `NEW/DUP_X1/SWAP` 把未初始化引用穿到它下面（全是单字，无需 DUP2 族）。
3. **`core-diff` 是这一刀最好的正确性证据**：changed 集合**只有 `emit` 一个模块**
   （我改的那个）。这一刀在 Core 之后，所以「别的模块 Core 一个字节没动」是可机器验证的
   「语义没变」。另有一个字典类因 ADT id 位移改名，属 **ADT-shifted 桶，不并进 changed**。

**行为对拍**（逐字节 diff 必红——形状变了——所以证明换成行为）：
`dawn test selfhost` 298 项、`selfhost-fixpoint` B==C、`native-fixpoint` B==C、
`selfhost-run-diff`、`classfile-verify` 八语料 1946 类 0 illegal、`selfhost-prev-diff`
（`Emit-Change(emit *)` 声明覆盖六个语料）、`fmt-diff`/`lsp-diff`、以及十余个 contract 门禁
全绿。

**K-A5 的红演示**（门禁没红过就不算门禁）：`scripts/constpool-scan.py` 在**未改动的
HEAD** 上跑，`34 of 963 emitted classes name a method-handle constant`，exit 1；
同一条命令在 K-A3 之后 `1131 emitted classes, no constant-pool tag 15/16/17/18`，exit 0。
它挂在 `classfile-verify/run.sh` 末尾，复用那里已经发射好的语料。

**留给 K-A4 的**：版本降到 49、`ClassWriter(2)`→`(1)`、删覆写与 `supers_of`。
§3.2 的 −15.2% 与 §3.3 的 (a) 都在那一刀里，本刀单独看是 **jar +2.0%、真实编译 −4.1%**。

### 5.6 K-A4 落地记（版本下降）

**这一刀的成果，一句话**：**拆掉了那块无源二进制里危险的那一半——写帧的那半。**
体积、启动那些数是副产品，不是理由；下面所有段落按这个精度读。

**做了什么**：`jvmops.dawn` 的 `V17: Int = 61` 换成 `V49: Int = 49`，并新增
`COMPUTE_MAXS: Int = 1`；`emit`/`codegen`/`rtclasses`/`testrun` 四个发射器不再
`AdtClassWriter.new(supers)`，改走 `AdtClassWriter.plain(COMPUTE_MAXS)` 拿一个**朴素的
ASM `ClassWriter`**，再用那五个**静态**适配器（`beginOn` / `beginOnWithInterface` /
`fieldOn` / `methodOn`）驱动它。`rtclasses.supers_of` 与它那条穿过十几个签名的
`supers: List[String]` 参数链整条删掉。

**为什么非得动这么多调用点**（原设想只是"改一个 flag"）：`AdtClassWriter` 的**两个构造器
都把 `ClassWriter(2)` 写死在字节码里**（`invokespecial ClassWriter.<init>:(I)V`，实参是
`iconst_2`），而这个类**没有源码、本机也没有 javac 去重编**。所以「把 `(2)` 改成 `(1)`」
这个动作**不存在**——唯一的路是**别走实例那条路**。`plain(int)` 正好是
`new ClassWriter(flag); areturn`，把 flag 原样透传，于是 `plain(1)` 就是需要的东西。
这是本刀里唯一一处「设计上以为是一行、实际是八十处」的地方。

#### 那块二进制到底怎么样了：**结局 (a)，而且要如实降级**

`javap` 读发射出来的编译器（`build/dawn-selfhost.jar`），`AdtClassWriter` 的成员被引用的
情况 `[实测]`：

| 成员 | 调用点数 |
|---|---|
| `plain` / `beginOn` / `beginOnWithInterface` / `fieldOn` / `methodOn` | 21 / 17 / 4 / 16 / 54 |
| `<init>`（两个构造器） | **0** |
| `getCommonSuperClass` | **0** |

`dawn/tool/AdtClassWriter.class` **仍然在 jar 里，仍然是 5,148 字节，一个字节没少**。
它不再被**实例化**，因此 `supers` 字段、两个构造器、`chain()`、`getCommonSuperClass()`
覆写成了**类文件内部的不可达代码**。

**这是缓解，不是关闭。** 不可达是一个关于**今天的调用点**的分析性论断，不是那个文件的性质：

- 反射进得去，不受调用图约束；
- `<clinit>` 不在任何人的可达性图里；
- 下一次谁改了调用点，死的那半就活了，而**没有任何门禁会告诉你**。

而且这个论断是对一个**你无法从源重建的 class** 做的——比它看上去弱。所以：
**不要说「`AdtClassWriter` 的危险面已消除」**。准确的说法是「危险的那一半当前不可达」。
BOOT-01 的状态照此；`selfhost/src/vendor.dawn` 的 `vendor_trust` 注释里也写了同一句话。
真正关门的是 **K-A7**（§5.7），不是本刀。

（顺带排除掉另一条路：**能不能绕开这个适配器直接从 Dawn 调 ASM**？`plain` 可以——它只是
构造器包装，Dawn 写 `ClassWriter.new(1)` 就够。另外四个不行：`visit`/`visitField`/
`visitMethod` 的 `signature`/`interfaces`/`value` 形参要 null，**Dawn 源码拼不出 null**。
所以在 Dawn 源码层面，五去其一，那个类还是得留着。§5.7 走的是另一个层面。）

#### 死代码改写：从 §4 第 13 条到实测

§4 第 13 条预告的差异确实存在，而且规模不小 `[实测]`——自写的线性扫描 + 可达性分析
（不经 ASM，避免用被测对象验被测对象）读两个 jar：

| | 有 Code 的方法 | **含不可达代码的方法** | 不可达区里是什么 |
|---|---|---|---|
| K-A4 前（COMPUTE_FRAMES） | 5,879 | **828** | 一律被改写成 `nop … athrow` |
| K-A4 后（COMPUTE_MAXS） | 5,878 | **828** | **原样保留**（`getstatic`/`areturn`/`goto`/`pop` …） |

（−1 个方法是删掉的 `supers_of`。828 完全相同——**这一刀不产生也不消除死代码**，
死代码是发射器的产物，本刀只决定它以什么形态落到 class 文件里。）

**理论说 V49 的推断式校验器只走可达代码，所以无害。本刀不引用理论，做了两侧对照**
`[实测]`：取一个真发射出来的 V49 类（`std/cursor`，`skip_go` 的不可达区是
`getstatic; lreturn`），造两个突变体，**同一份门禁加载器**跑：

| 突变体 | 改了哪里 | 结果 |
|---|---|---|
| 对照（未改） | — | 无 `VerifyError` |
| **A** | 把**不可达**那 4 个字节全填成 `athrow`（空栈上 athrow = 类型错误） | **与对照逐字一致，无 `VerifyError`** |
| **B** | 把**一条可达指令**（偏移 35 的 `aload_3`）改成 `athrow` | `VerifyError: (class: std/cursor, method: skip_go signature: …) Unable to pop operand off an empty stack` |

B 是负控：没有它，A 的绿只能证明这个类太简单。B 的消息还是**老推断式校验器专有的
`(class: X, method: Y signature: Z)` 格式**（§2.2）——校验器活着、在跑、而且严格；
它就是**不看**不可达代码。→ §4 第 13 条从 `[实测]`（在 spike 上）升级为**在生产语料上实测**。

#### `classfile-verify` 对 selfhost 语料一直是空转的（§4 第 16 条）

造 B 突变体时它**没红**。追下去是门禁自己的缺陷，不是本刀的：`Verify.java` 用
`new URLClassLoader(new URL[]{dir}, parent)`，**双亲优先**；而 `run.sh` 必须把
`build/dawn-selfhost.jar` 挂在 parent 上（selfhost 的类要引 vendored ASM/coursier）。
selfhost 发射出的类名（`std.cursor`、`emit`、`main` …）与 jar 里**逐个同名**，
于是每一个都从 **jar** 解析——`__emit -o` 写出来的那个目录**从来没被读过**。

后果说清楚：**八个语料里，selfhost 那个的 1046 个类，这道门禁无论 `__emit` 写出什么
都不会红**。另外七个语料类名不与 jar 冲突，一直是真的在验。

**已修**：加载器改成 child-first（JDK 前缀除外）。修完：

- 八语料 **1946 类、0 illegal** 照旧（所以这不是一个被掩盖的红灯，是一个**不会红的绿灯**）；
- **红演示**：把突变体 B 放进完整的 selfhost 语料，修好的门禁
  `1045 classes verified, … 1 illegal` 并打出上表那条 `VerifyError`。修之前同一份输入是
  `1046 verified, 0 illegal`。

这与 #129 记的是同一族问题（门禁的绿说明的比它看上去少），但**不是同一条**：#129 说的是
`Class.forName` 强制不到方法体的符号解析（漏掉 `ACC_PRIVATE`），这条说的是**它连字节都没读到**。

#### 门禁

逐字节 diff 必红（版本号在每个 class 头里），所以主证明是行为：

- `dawn test selfhost` **299 项**、`dawn test site` 40 项、四个 package 测试全绿；
- **`classfile-verify` 八语料 1946 类 0 illegal**（child-first 修好之后跑的），
  `constpool-scan` `1946 emitted classes, no constant-pool tag 15/16/17/18`；
- `selfhost-fixpoint` **B == C**、`native-fixpoint` **B == C**、`spike-native` differential ok；
- `selfhost-prev-diff`：六个 emit 语料各自匹配到**自己那条**声明
  （`Emit-Change(emit site)` / `(emit playground)` / `(emit packages/web)` /
  `(emit packages/json)` / `(emit selfhost)` / `(emit examples/calc.dawn)`），
  `lex`/`parse`/`fmt backend-dawn` 三项 OK；
- `selfhost-run-diff` / `fmt-diff`(327 文件) / `lsp-diff`(50 消息) 全绿；
- `core-diff`：`changed` **恰好是我改的那六个模块**（codegen / emit / main / rtclasses /
  testrun / vendor），**没有 ADT-shifted、没有余数**。这一刀在 Core 下游，所以
  「别的 69 个模块 Core 一个字节没动」是可机器验证的「语义没变」；
- 其余：opaque-twin / array / pvec / hamt / path / inflate / unicode / error / rc /
  table-freight / intrinsic-parity / grammar / checker / json-suite / playground /
  doc-check / lock / site build，全绿。

**`Emit-Change` 逐个 target 显式列举，不用 `*`**（K-A3 用了 `emit *`，那正是任务 #124
的形状，为此专门发了 v0.48.0 把 oracle 擦回来）。通配会连**将来新增的 label** 一起豁免；
六条显式声明只覆盖今天存在的六个语料，新加一个语料照样会红。代价是六行提交信息，
没有实际问题。

#### 「真编一遍」（门禁绿不算完）

#129 的盲区正对着这一刀，所以不只信门禁：

- `dawn build examples/calc.dawn` → 85 个类，**全部 major 49、零帧属性**，
  `java -jar` 跑出 `2 + 3 * (10 - 4) = 20`；
- `dawn build --native examples/calc.dawn` → **`native-image` 吃下了这批 V49 无帧类**，
  12.0s 构建成功，二进制跑出同一个答案。审计 §3.5 那个 spike 现在是生产路径上的实测；
- `selfhost-fixpoint` 本身就是最强的一次：**一个 V49 编译器把整个编译器编了两遍，
  B == C**。

**留给 K-A7 的**：让那五个适配器从树内源重建（§5.7）。

### 5.7 K-A7：让 Dawn 自己发射那个适配器

§4 第 15 条推翻的前提是「适配器必须是手写 Java，因为 Dawn 没有 null」。
**「Dawn 没有 null」约束的是 Dawn 源码，不约束发射层。** 发射出来的字节码里当然可以有
`ACONST_NULL`——而且**今天就有**：

| 需要的东西 | 发射器今天在哪儿已经这么干了 |
|---|---|
| `ACONST_NULL` | `rtclasses.dawn:2263`（`emit.dawn:2374` 也有） |
| `ANEWARRAY <宿主类型>` + `AASTORE`，把数组喂给 Java 方法 | `rtclasses.dawn:1147` / `:1198` / `:1344`（`ANEWARRAY cls` 在 `:1284`） |
| `new X(int)` + `invokevirtual` 到宿主类 | 整个 `rtclasses.dawn` |
| 把合成类装进程序的输出 | `dawn/rt/*` 共 **24 个类**，就在编译器自己的 jar 里 |

所以这五个适配器**没有一条指令**超出发射器的现有本事。它们可以变成第 25 个
`dawn/rt/*` 类（比如 `dawn/rt/Asm`），由 `rtclasses.dawn` 合成。

**性质的变化才是重点，不是省下 5,148 字节**：从「源不在树上、逐字节代代抄」变成
**「从树内源可重建、可被 DDC（diverse double-compiling）验证」**。这是 BOOT-01
真正的关门方式——而不是把那块二进制缩到足够小然后接受它。

**自举顺序 = N 代产物、N+1 代消费**（本仓已有的三期种子纪律）：

1. **期 1**：`rtclasses.dawn` 开始发射 `dawn/rt/Asm`，但**没人用它**。这一代的
   编译器把它发进自己的输出 jar。（`Emit-Change`：多一个类。）
2. **期 2**：发布 + 推进种子。现在种子的 classpath 上**有** `dawn/rt/Asm` 了，
   `use java "dawn.rt.Asm"` 能过类型检查。把四个发射器的调用点从 `dawn.tool.AdtClassWriter`
   切到 `dawn.rt.Asm`。
3. **期 3**：发布 + 推进种子。`dawn/tool` 不再被任何人引用 → 从 `--vendor` 的前缀列表
   和 `vendor.dawn` 的 `vendor_trust` 里删掉。**那 5,148 字节这时才真的离开可信底座。**

**仍然是种子依赖**（第 N 代的二进制里那个类是第 N−1 代发射的），但那正是编译器自举的
常态，也正是 DDC 能处理的形状——与「源码不存在」是两回事。

**两个要先想清楚的设计点**（不是障碍，是选择）：

- `dawn/rt/Asm` 会引用 `org/objectweb/asm/ClassWriter`，而绝大多数用户程序的 classpath
  上没有 ASM。要么**按需发射**（`gen_strings_class(u: TableUse)` 就是现成的先例），
  要么接受一个引用了缺席类型的类躺在输出里（惰性解析，不初始化就不炸，但
  `classfile-verify` 会多出一行 note）。倾向前者。
- 名字：`dawn/rt/Asm` 还是别的。`dawn/tool` 这个包名在第 3 期之后就没有别的居民了。

**为什么这一刀不在 K-A4 里做**：它跨三个 release，而 K-A4 是一个提交。硬塞进来会让
一个不可逆的 Emit-Change 和一条三期链条互相扣住。

### 5.8 一条要记的账：V49 未必是单向门（§4 第 17 条，`[推论]` 未实测）

§5.2 判「自算 StackMapTable 明显更难」，难点落在**公共超类型求解**。这个判断值得挂一个
问号：**那个难度是从 ASM 的处境继承来的**。ASM 面对的是「一个它加载不了的类」，所以
必须外挂 oracle（`getCommonSuperClass`），所以 `supers_of` 那张合成表才存在。
**Dawn 不在那个处境里**——它刚从 AST 建完整个类型层次，`Adts` 就在手上，查自己的符号表
就能答，而且答案对**尚不存在的生成类**同样成立（那正是 `supers_of` 当初能写出来的原因）。

再加两条已经量过的：控制流很干净（`tableswitch`/`lookupswitch` **0 条**，5,478 个有 Code
的方法里**只有 8 个**有异常表，§5.2），而且写出来是 **Dawn 代码，不引入新的手写 Java**。

**还有一条纯推理、未实测**：两个宿主引用类型在汇合点合流时，**并到 `java/lang/Object`
永远是合法的公共超类型**；只在「后续还需要更精确的类型而又没有 `checkcast`」时不够用。
若这条成立，难度就从「实现一个类型格求解器」掉到「实现帧的增量编码」（same /
same_locals_1_stack_item / chop / append / full）。

**这不改变 K-A4 的方向**——V49 让这整块消失，先落地是对的。但它改变一个**权重**：
我们此前把 V49 当**不可逆承诺点**（D5）来权衡，如果自算帧确实可行，那么将来想回 ≥50
随时能回，那个权重该降。**动工前必须先实测这条推论**，别把它当成已知。

## 6. 本次落地（K-A0 / K-A0.5）

### K-A0：文档校正

改了 §4 表里第 6/7/8/9 条对应的四处，外加一处计数漂移：

| 位置 | 改了什么 |
|---|---|
| `CLAUDE.md` | 契约表改指 `types.dawn` 的 `Rt`/`Intr`/`intrinsics()`；「第二后端的两个前置」整段改写成「第二后端已在跑，FFI capability 不是前置」；提交信息格式（§4 第 10 条）；`docs/` 篇数不再复述 |
| `docs/README.md` | 同族两条：`runtime-intrinsics-design.md` 的说明、`llvm-backend-research.md` 的「第二后端调研」 |
| `docs/runtime-intrinsics-design.md` | 文首加「`rt_intrinsic_target` 是旧名」；§11 的 `jarw.dawn` 先例更正为 `packages/inflate` |
| `selfhost/src/emitc.dawn` | 文件头的「尚未实现」清单收成只剩 `CForeign` |
| `scripts/selfhost-core-diff.sh:33` | 「across all 52 modules」→ 不再复述计数（今天 75，文件本身就是计数） |

**判定不改的**（都是带日期或带上下文的历史测量，改了等于伪造）：

- `scripts/selfhost-core-diff.sh:105`「Measured 2026-07-26: one added function to
  types.dawn moves 6 of 52 modules」——自带日期的一次测量。
- `selfhost/src/coredump.dawn:257`「churned 19 of 52 modules」——同类，过去式测量，
  只是没写日期。
- `docs/native-backend-plan.md:674` S0.4 行的「编译器 52 模块的哈希清单」——
  落地记录表里的一行，记的是 S0.4 落地时的样子。

### K-A0.5：给无源二进制上 checksum

登记在 **`selfhost/src/vendor.dawn` 的 `vendor_trust`**，不是
`scripts/seed-checksums.txt`。理由三条：

1. **它是常量，不是每 release 一条**。`dawn/tool` 与 `org/objectweb/asm` 的哈希
   在 **v0.8.0（第一个 selfhost 种子）到 v0.47.0 的每一代种子里逐字节相同**
   `[实测]`——用 Python 独立重算过整条种子链，两个值都复现。
   `seed-checksums.txt` 的全部内容是「每个 release 一行」、每次发版都要 bump；
   把一个永不变的常量放进去，会让它看起来像个需要重新推导的东西，
   而「从手上这个 jar 重新推导」恰恰就是这个检查要挡住的动作。
2. **它必须在编译时被检查，而编译器可能在任何地方跑**。发布出去的 jar 身边没有
   这个仓库，读不到 `scripts/` 下的任何文件。写进源码则随编译器走完整条种子链。
3. **种子推进时漏不掉**：常量在源码里，每次构建都算一遍；漏了就是红灯，
   不是「忘了改一行数据文件」。

**检查点选在 `vendor.classpath_package`**（vendor.dawn），因为**全仓每一处
`--vendor` 都从这里过**：`bin/dawn` 的两个构建阶段（:141/:144）、
`scripts/selfhost-fixpoint.sh:19,23`、`scripts/replay-bootstrap.sh:44`、
`scripts/selfhost-bench.sh:65`。收在这里 = 一份检查；收在 shell 调用方 = 四份
拷贝加一个迟早不带检查的第五个调用方。

**三个分支**：

- 有记录的哈希，对不上 → **panic 退出**（不是警告）。
- 明确豁免（`Exempt`，带理由）→ 放行。
- **没登记 → 也 panic**。这是刻意的：`--vendor` 的全部工作就是把没有源码的二进制
  塞进可信基，一个没有决定记录在案地进来，正是要防的事。报错里直接打出它当前的
  哈希，补一行即可。

`coursierapi` 是唯一的 `Exempt`，理由写在源码里并可复核：10,057,897 B，
本仓的纯 Dawn SHA-256 实测约 7 MB/s（用 5 KB / 254 KB / 10 MB 三个输入计时得出），
即每次 vendor 约 1.4 s、两阶段工具链重建约 2.9 s，而重建总时长基线是 10.7 s
`[实测]`——**+27%**，换来的是三者中唯一不写字节码的那个（它是依赖解析器）、
且唯一有 Maven Central 发布校验和可另行核对的那个。
**豁免在成本，不在原则**：哈希变便宜了就记上。

对比之下 `org/objectweb/asm` 是 253,894 B ≈ 36 ms，约占一次重建的 0.3%，值得记。

**失败演示**（这一步是本刀的实质——一个从没被证明会红的检查，它的绿不说明任何事）：
把表里的期望值临时改错（不动二进制），`./bin/dawn --version` 以 **exit 1** 失败，
打印期望/实际/类数与该怎么办。三个分支各演示过一次。

## 7. 不做的（以及为什么）

- **不把 `AdtClassWriter.java` 恢复进主干**（用户裁决）。恢复它等于把一份手写
  Java 重新变成要维护的东西，而 A 线的方向是让它消失。K-A1 只把它捞出来当参照读。
- **不给 `coursierapi` 记哈希**（§6，成本）。
- **不自己算 StackMapTable**（§5.2）。但**这条的理由要打折**：§5.8 记了一条尚未实测的
  推论，说那个难度可能是从 ASM 的处境继承来的，而 Dawn 不在那个处境里。
- **不用 Dawn 重写 `AdtClassWriter`**（原 K-A2，已取消）。K-A4 之后没有 classfile writer
  可重写。§5.1
- **不把那块二进制"收小"当成关门**（原 K-A4b，已取消）。K-A4 之后它的危险那半只是
  **不可达**，字节一个没少；缩小不是关闭。要关门只有 K-A7：**从树内源重建它**。§5.6/§5.7
- **K-A3 不碰 classfile 版本**。版本下降是 K-A4 独立一刀，也是 D5 的不可逆承诺点
  （但见 §5.8：这个"不可逆"的权重可能该降）。
- **K-A0/K-A0.5 不碰发射的任何字节**。两刀都没有 `Emit-Change`。
