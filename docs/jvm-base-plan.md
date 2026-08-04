# A 线：收缩 JVM 后端的可信底座

> 状态：**done**（2026-08-03 立项，任务 #127；K-A0/K-A0.5/K-A1/K-A3/K-A5/K-A4 与 K-A7 期 1/2/3 全部落地，`dawn/tool` 已出 jar。2026-08-04 任务 #134 补上 §5.7 末尾那节：自发射把 BOOT-01 的威胁模型搬到了 1,225 字节的自发射类上，参照的 javac 独立性是唯一防线，已写成不变式 + 两道机器兜底；2026-08-04 任务 #132 补上 §5.9：§5.2 最后一条 `[推论]` 换成实验，裁决「记账不是抽象解释」成立、「一遍记账就够」被推翻）。本文是 A 线的动工前设计：
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
| ~~`dawn/tool/AdtClassWriter`~~ | ~~1 个类，5,148 B~~ | ~~**不在工作树**，只在 `kotlin-final` tag~~ | ~~**写 class 文件**~~ |
| `org/objectweb/asm` | 38 个类，253,894 B | 第三方（Maven） | **写 class 文件** |
| `coursierapi` | 2,409 个类，10,057,897 B | 第三方（Maven） | 解析/下载依赖 |

> 第一行已于 2026-08-03 **划掉**：K-A7 期 2/3 把那五个适配器换成从 `rtclasses.dawn`
> 发射的 `dawn/rt/Asm`，`dawn/tool` 退出 `--vendor` 与 `vendor_trust`，那个类不再
> 进任何 jar（§5.7 期 2+3 落地记）。**另外两行原封不动。**

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
| 17 | 「V49 是单向门（D5 不可逆承诺点）」 | **可能高估了**。自算 StackMapTable 的难度是从 **ASM 的处境**继承来的（它面对加载不了的类，只能外挂公共超类型 oracle）；Dawn 刚从 AST 建完整个类型层次，查自己的符号表就能答。若成立，回 ≥50 随时能回。**写这条时是推理、未实测**，K-A4 不依赖它；2026-08-03/04 已实测——本体成立且 oracle 对 Dawn 便宜到有了数（§5.8、§5.9），倒的是第 18 条那条附带推论 | `[推论]`→`[实测]` |

| 18 | 第 17 条附带的那条：「两个宿主引用类型合流时并到 `java/lang/Object` 永远合法，于是自算帧从**算法活**掉成**格式活**（只剩帧的增量编码）」 | **证伪**。把 seed 的 72,408 个 tag 7 站点全压成 `java/lang/Object` 再强制链接：对照组 1022/0，实验组 **953 通过 / 69 非法**；有帧的 421 个类里 **16.4% 失败**，四族（`athrow` 要 `Throwable` 23、后续调用要精确类型 37、`areturn` 要签名返回类型 7、**入口帧不可放宽** 2）。oracle 躲不掉。第 17 条**本体仍然成立**（oracle 对 Dawn 便宜），倒的只是这条附带推论。§5.8 | `[实测]` |
| 19 | （无人提过）自算帧是「难度未知的一大团」 | 已量清成**四项有界的活**：公共超类型 oracle（284 个精确类，符号表能答）、`Uninitialized` 追踪（tag 8 = 526/296 非零划不掉，但 tag 6 恒为 0 可划掉，且 526 条全在栈上）、帧的增量编码（帧占 class 总字节 14.9%，全发 `full` 约翻四倍）、**循环头要第二遍/定点**（第 20 条）。§5.2 | `[扫描]`+`[实测]` |
| 20 | 「发射器**一遍**顺手记账就够——压栈那一刻就知道精确类型，只有汇合点要合并」 | **一半成立一半证伪**。成立的：可达帧 **100%** 能只从「指令+描述符」的账本重建（seed 38,753／backend-dawn 8,275），64.9% 的帧连合并都不需要，要问符号表的只占条目 **0.077%**、**88 条不同提问全是一次查直接父类**。证伪的：`CSLoop`（`emit.dawn:2211`）先发循环头标签再发回边，**单遍走到那儿还没见过回边**——seed 上 **38 个帧／34 个方法**因此写出**比真值更窄**的类型（44/44 处槽位差异全是严格子类型，0 处更宽），而窄正是校验器拒绝的方向。§5.9 | `[实测]` |

第 6/7/8/9/10 条已随 K-A0 改掉（见 §6）。第 11/12/13 条是 K-A3 动工前复验刀序时测出来的，
已改进 §5；第 14 条是 K-A3 落地时撞上的，记在 §5.5；第 15/16/17 条是 K-A4 落地时的，
记在 §5.6（15 另见 §5.7 的 K-A7、17 另见 §5.8）。**第 18/19 条是 2026-08-03、第 20 条是 2026-08-04 为「动工前
必须先实测」这句话补的测量**，记在 §5.8、§5.2 与 §5.9；原始数据在
`~/workspace/notes/stackmap-shape.md`，脚本在 `~/workspace/notes/stackmap-ledger/`。

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
| **K-A7** | **让 Dawn 自己发射那五个 null 适配器**（`dawn/rt/Asm`），`dawn/tool` 整体退出 `--vendor` | 三期种子纪律，可回退 | **全部已做**（§5.7）：期 1 一次发布，期 2+3 合并在 v0.49.0 之后一次落地 |
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

**难点在哪：先后两种说法都不对**（2026-08-03 两轮测量，原始数据与复现命令在
`~/workspace/notes/stackmap-shape.md`，不在仓库里）：

- **原文（审计）说**：「难点不在控制流，在类型格」——要实现公共超类型求解（而且要对
  **尚不存在的生成类**求解，不能 `Class.forName`，所以 adtSupers 表反而得留下并加强）、
  `uninitialized`/`uninitializedThis` 追踪、long/double 双槽配对、帧的增量编码。
  几百行有微妙不变式的代码，且错误模式恶劣：帧算错不是崩溃，是 `VerifyError`，
  **且只在恰好走到那条路径的类上暴露**。
  → **清单本身是对的，「所以很难」这个归因不对**：那个难度是从 ASM 的处境继承来的，
  Dawn 不在那个处境里（§5.8 前半，仍然成立）。
- **后来（主会话）反过来说**：「这是格式活不是算法活」——引用一律压 `java/lang/Object`
  就能绕开求解器，剩下的只是帧的增量编码。
  → **这半被实验直接证伪**（§5.8 后半，`[实测]` 69/421 类 `VerifyError`）。

**量清之后的正确说法：四项有界的活，而其中最贵的那项对 Dawn 特别便宜。**
（前三项 2026-08-03 量清，第 4 项 2026-08-04 量清；每一项都换掉过一个定性说法。）

1. **公共超类型 oracle —— 要，但便宜** `[扫描]`+`[实测]`。今天发射出来的帧里，引用条目
   （tag 7）指向 **284 个不同的精确类**（seed v0.48.0 共 72,408 条；指向
   `java/lang/Object` 的只有 368 条 = **0.51%**。top：`std/pvec$Vec` 18.5%、`Option` 10.9%、
   `java/lang/String` 10.8%、`java/lang/Throwable` 5.7%、`std/hamt$Hamt` 5.7%、`cx$Cx` 4.5%）。
   保守格替代不了它（§5.8）。便宜的理由是**符号表就在手上**，不必像 ASM 那样外挂 oracle。
   **「便宜」2026-08-04 从理由升级成了数** `[实测]`：重建全部帧时真正问到 oracle 的只有
   **533 个帧条目**（占可达帧解码后条目的 **0.077%**）、**77 个不同的问题**，而这 77 个
   **无一例外**答案都是「输入的**直接父类**」，且父类全是 Dawn 自己发射的 ADT
   （`join(Option$None, Option$Some) = Option` 这种）。**零个**问题的答案是
   `java/lang/Object`，**零个**牵扯 JDK 类，**零个**要往上爬一层以上（backend-dawn 语料上
   另 27 个提问同样如此，与 seed 重叠 16 个）。
   即这个 oracle 的实体是 `adt_parent_of(case)` 一次查表。§5.9
2. **`Uninitialized` 追踪 —— 要，但范围比想象小** `[扫描]`：
   - tag 8（`Uninitialized`）seed **526** 条、backend-dawn **296** 条。两个互相独立的语料
     （编译器自身、一个 web 后端应用）都非零 → **划不掉**。
   - tag 6（`UninitializedThis`）**两个语料都恒为 0** → Dawn 发射的 `<init>` 从不在
     `super()`/`this()` 之前出现分支目标，**这一项可以从清单里划掉**。
   - **526 条全部在操作数栈上，locals 一条都没有** → 要追踪的是「栈上带 offset 的标记」，
     不是一个局部槽状态机。
   成因两种，**第二种决定了这项躲不掉**：(A) **源码型**——`selfhost/src/doc.dawn:77` 在
   构造器实参位写了 `if`（同族触发者还有 `match`/`?`/`.expect()`/短路运算）；
   (B) **编译器自插型**——`selfhost/src/interp.dawn:1376` 的 `Ok((st, env, VInt(a / b)))`
   源码实参**没有任何分支**，是 lowering 插的**除零保护**（`dup2/lconst_0/lcmp/ifne`）把
   分支目标放进了**三层嵌套**的未初始化窗口（offset 245 同时处在 `new Result$Ok`、
   `new dawn/rt/Tuple3`、`new core$CValue$VInt` 三个窗口内）。
   **就算禁掉「实参里写 `if`」这种风格，(B) 也消不掉**——任何插入检查的 lowering 都会
   重新制造它。
3. **帧的增量编码 —— 要，不是可选** `[扫描]`：`StackMapTable` 占 Dawn 发射的 class
   **总字节的 14.9%**（seed：465,257 B / 43,049 条帧，class 总字节 3,115,916）。
   frame_type 分布**两个口径给出相反的直觉**：按**条数**是 `same` 40.7% /
   `same_locals_1_stack_item` 26.8% / `full` 19.2% / `append` 8.2%；按**字节**则
   `full` 独占 **82.3%**。
   → **偷懒一律发 `full` 帧，帧字节约翻四倍，在 3.1 MB 的 jar 上加约 1.5 MB。**
4. **循环头要第二遍 —— 这项是 2026-08-04 才量出来的** `[实测]`：原文这里挂过一条
   `[推论]`——「发射器不需要推断帧，压栈那一刻就知道精确类型，**发射时顺手记账**即可」。
   实测的裁决是**一半成立一半推翻**（§5.9）：「记账而非抽象解释」成立（两个语料里**可达帧
   100% 逐字节重建成功**），但「**一遍**记账就够」不成立——`CSLoop`（`emit.dawn:2211`）
   先发 `visitLabel(top)` 再发回边，单遍记账走到循环头时**还没见过回边**，seed 语料上
   **38 个帧（34 个方法）**会因此写出**比真值更窄**的类型（`Option$None` 而非 `Option`），
   而窄正是校验器拒绝的方向。**要一个定点/第二遍。**

顺带两条格的形状 `[扫描]`：`Top` **只出现在 locals、从不出现在 stack**（99.7% 集中在
`full` 帧里，是「这个槽在这个汇合点是死的」的填充）；**`Float` 恒为 0**——Dawn 的
`Float` 是 f64 → JVM `double`，格里少一档。

**判断**：V49 是「删掉一个需求」（149 个平凡闭包类 + 一个 ClassWriter flag），
自算帧是「新增一个有微妙不变式的子系统」。两条路都要碰 `AdtClassWriter`，
但 V49 那边是**减法**。**这个判断的方向不变，强度要打折**：上面四项都已量清、
都是有界的，「难度未知」不再是它的理由之一。

### 5.3 `scripts/classfile-verify` 能兜住吗——能，但有边界

- **能**：它 `Class.forName(initialize=true)` 强制链接，HotSpot 在链接时校验整个类的
  所有方法体。帧写错 = `VerifyError` = 门禁 `bad>0` = exit 1。这是真安全网。
- **边界一**：它只覆盖**语料实际发射出的代码形状**（8 个语料；审计实测了其中 4 个
  = 1,158 个类）。语料里没有的形状（比如将来引入 switch）它管不到。
- **边界二**（关键）：**它今天校验的是 ASM 算的帧，不是发射器自己算的帧**。
  对发射器的帧推理零覆盖——只有在 K-A4 之后（校验的变成「根本没有帧」）它才开始
  对这条路线有意义。
- **边界三 —— 它对 selfhost 语料曾经根本没读到字节**（K-A4 落地时才发现，`ddfdb1a` 已修）：
  `Verify.java` 用 `new URLClassLoader(new URL[]{dir}, parent)`，**双亲优先**；而工具链 jar
  必须挂在 parent 上（selfhost 的类要引 vendored ASM/coursier），selfhost 发射出的类名
  （`std.cursor`、`emit`、`main` …）与 jar 里**逐个同名**——于是每一个都从 **jar** 解析，
  `__emit -o` 写出来的那个目录**从来没被读过**。后果说白了：那 **1046 个类，无论 `__emit`
  写出什么都不可能失败**。
  **发现方式值得记**：不是读代码看出来的，是做死码变异实验时**变异体 B（把一条可达指令
  改成 `athrow`）没有变红**才暴露的（§5.6）。
  修完 child-first 之后**计数一个没变**（1946 类 0 illegal 照旧）——所以这不是一个被掩盖的
  红灯，是**一个红不起来的绿灯**；红演示另做：把变异体 B 放进完整 selfhost 语料，修好的
  门禁给出 `1045 classes verified … 1 illegal`。§4 第 16 条、§5.6。
- **边界四 —— 它读到了字节，也只强制到类初始化**：`Class.forName(initialize=true)` 不强制
  解析每个方法体里的符号引用，所以**访问权限一类的错误它抓不到**（K-A3 的 `ACC_PRIVATE`
  bug 就是它没抓到的，§5.5；记在 #129）。

  **边界三与边界四是两回事，别并成一条**：#129 说的是「`forName` 不解析方法体」，
  边界三说的是「它压根没读那些字节」。前者是覆盖深度不够，后者是覆盖面为空。
  两条合起来才是「每一刀都必须**真编一遍东西**，不能只信门禁」的完整理由。

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

> 后续（2026-08-03）：K-A7 期 2+3 落地，那个类已不在 jar 里，本段的「缓解」到那时才
> 转为「关闭」。这一段留着，因为它记录的是**为什么不可达不等于消失**——这个判据本身
> 没有过期。

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

> 这条纪律从 2026-08-04 起是机器强制的：`scripts/emitchange.sh` 直接拒收带 `*` 的
> scope，本节这六行就是它引用的「禁掉通配的代价可测」那份实测（#124）。

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

#### 期 1 落地记（本次）

**做了什么**：`rtclasses.dawn` 多了一个 `gen_asm_class()`，发射 `dawn/rt/Asm`——五个
public static 适配器，与 `dawn.tool.AdtClassWriter` 的五个静态成员同名同描述符。
`main.dawn` 在 `collect_program` 的 rt 类清单里加了一行（带条件，见下）。
**没有任何调用点改动**：四个发射器仍然调 `dawn.tool.AdtClassWriter`。

**那五个入口点确实只有五个** `[实测]`。参照源从 `kotlin-final` tag 捞回
（`compiler/src/main/java/dawn/tool/AdtClassWriter.java`，115 行），与
`.dawn/seeds/v0.48.0/seed.jar` 里那份 5,148 B 的二进制 `javap -c -p` 逐个核对
（全类 269 行输出，其中五个静态方法占 51 行）。再扫一遍 HEAD 发射出来的 selfhost
语料（1047 个类的 `javap -c`，按成员名计数）：

| 成员 | 调用点数 |
|---|---|
| `methodOn` / `plain` / `beginOn` / `fieldOn` / `beginOnWithInterface` | 54 / 22 / 18 / 16 / 4 |
| `<init>` / `getCommonSuperClass` / `begin` / `beginWithInterface` / `field` / `method` | **各 0** |

（`plain` 与 `beginOn` 比 §5.6 的表各多 1，就是 `gen_asm_class` 自己写这个类时用掉的。）
→ 要复现的表面就是这五个，一个不多。

**逐行可审：61 行，界是 ~115 行** `[实测]`。发射出来的 `dawn/rt/Asm.class` 是 **1,225 字节**，
`javap -c -p` **61 行**（对照：参照 Java 源 115 行、参照 class 的 `javap` 269 行）。
五个方法体里有四个与参照**逐条指令相同**；只有 `fieldOn` 少两条——参照把 `visitField`
的返回值 `astore`/`aload` 走了一趟再调 `visitEnd`，这里直接在返回值上调。

**设计点一（§5.7 只标了没定）：按需发射，不是过渡态。** 触发条件是
**「被编译的程序 import 了 `org.objectweb.asm.ClassWriter`」**（`main.dawn` 的
`program_has_asm`）。理由：`use java` 解析不了的类不可能被 import，所以「import 了
ClassWriter」恰好等价于「这个程序的 classpath 上有 ASM」；编译器自己是这样的程序
（`emit`/`codegen`/`rtclasses`/`testrun` 四个模块都 import 它），而这正是期 1 唯一需要的
那个程序。实测三个语料 `[实测]`：`__emit selfhost` 有 `dawn/rt/Asm.class`，
`__emit site`、`__emit examples/calc.dawn` 都没有。

**这个触发器期 2 不用换**——期 2 的调用点改成 `Asm.plain(...)`，返回值仍是 `ClassWriter`，
那四个模块仍然 import 它。（真要收得更紧，期 2 可以改判「程序 import 了 `dawn.rt.Asm`」，
那是个自指但收敛的条件；不是必须。）**期 2 必须动的是**：`use java "dawn.rt.Asm"` 加进
四个发射器、把 `AdtClassWriter.` 前缀替换掉（发射出来的字节码里 114 处调用 `[实测]`，
源码站点数另算），`rtclasses.dawn` 里
`gen_asm_class` 自己也要改成用 `Asm`（自举：这一代用旧适配器写新适配器，下一代用新的写新的）。
**期 3 必须动的是**：`main.dawn` 的 `--vendor dawn/tool` 说明、`vendor.dawn:410` 的
`vendor_trust` 前缀表、`scripts/selfhost-fixpoint.sh` 等脚本里的 `--vendor dawn/tool`。

**它确实进了编译器自己的 jar** `[实测]`：
`java -jar build/dawn-selfhost.jar build selfhost -o self2.jar --vendor …` 后
`unzip -l` 里 `dawn/rt/Asm.class` 1,225 B 与 `dawn/tool/AdtClassWriter.class` 5,148 B 并存。
期 2 要的就是下一个种子里有前者。

**差分测试（本刀的核心证据）**：`scripts/asm-adapter-contract/`（已接进 `gates.yml`）。
期 1 里没人调这个类——**发射一个空类，其它门禁一样全绿**。所以另立一道能看见的：反射拿到
两个类的五个入口（`getDeclaredMethod` 精确参数类型 + public/static 断言，这一步本身就是
表面对拍），各驱动一遍造出一个 probe 类，**比较造出来的 class 文件字节**。比比较返回值强：
`beginOn` 必须传 `null` 的 `signature`（传别的会多出 Signature 属性）、
`beginOnWithInterface` 必须造长度 1 的数组、`plain` 必须**转发**它的 flag
（COMPUTE_MAXS vs 0 体现为 maxStack/maxLocals）——全都落在字节里。7 项全绿 `[实测]`：

```
PASS  beginOn/fieldOn/methodOn produce identical class files
PASS  beginOnWithInterface produces an identical class file
PASS  plain(0) produces an identical class file
PASS  the probe is flag-sensitive (COMPUTE_MAXS differs from 0)
PASS  the emitted adapter forwards its flag
PASS  the emitted adapter's class links and runs (square(7) == 49)
PASS  the interface form declares its interface
OK: the emitted dawn/rt/Asm matches dawn.tool.AdtClassWriter on all five entry points
```

**红演示：两个变异体，都改的是发射器源码（`gen_asm_class`），不是产物** `[实测]`。

变异体 1——`plain` 里 `iload_0` 改成 `iconst_0`（flag 不转发，写死 0），退出码 1：

```
FAIL  beginOn/fieldOn/methodOn produce identical class files
FAIL  beginOnWithInterface produces an identical class file
PASS  plain(0) produces an identical class file
PASS  the probe is flag-sensitive (COMPUTE_MAXS differs from 0)
FAIL  the emitted adapter forwards its flag
      java.lang.ClassFormatError: Arguments can't fit into locals in class file probe/P
FAIL  the emitted adapter's class links and runs (square(7) == 49)
      java.lang.ClassFormatError: Arguments can't fit into locals in class file probe/P
FAIL  the interface form declares its interface
FAIL: 5 adapter difference(s); dawn/rt/Asm is not a drop-in for dawn.tool.AdtClassWriter
```

变异体 2——`beginOn` 把 `name` 当 `signature` 传（`ACONST_NULL` 改成再 `ALOAD 3`），退出码 1：

```
FAIL  beginOn/fieldOn/methodOn produce identical class files
PASS  beginOnWithInterface produces an identical class file
FAIL  plain(0) produces an identical class file
PASS  the probe is flag-sensitive (COMPUTE_MAXS differs from 0)
PASS  the emitted adapter forwards its flag
PASS  the emitted adapter's class links and runs (square(7) == 49)
PASS  the interface form declares its interface
FAIL: 2 adapter difference(s); dawn/rt/Asm is not a drop-in for dawn.tool.AdtClassWriter
```

**两个变异体都不是全红**，这是负控：变异体 1 里 `plain(0)` 那项照旧绿（flag 写死 0 时两侧
本来就该一致），变异体 2 里只有走 `beginOn` 的两项红、走 `beginOnWithInterface` 的那项绿
——门禁不只会喊红，它指得出是哪个入口点。改回来立刻回到 7 项全绿。

**Emit-Change 只声明一个语料**：

```
Emit-Change(emit selfhost): dawn/rt/Asm, the five ASM null adapters, is now emitted
```

六个 emit 语料里只有 `selfhost` 变了（其余五个不 import ClassWriter，按需触发器不给它们
发这个类）——所以这里**没有**用 `emit *`。任务 #124 记的就是通配声明会把 `emit` 这个
label 在**全部六个语料**上一直盲到下次推进种子；按需发射顺带把这个声明收窄成了一个语料。

**门禁**（本次逐条跑过，全绿）：`dawn test selfhost` 299 项、`dawn fmt … --check`、
`classfile-verify` 八语料 **0 illegal / 0 not initializable**（selfhost 语料
**+1 类**，多的就是它——本刀单独测时 1046→1047，并入 main 后是 1048、八语料合计 1948；
`not initializable` 为 0 说明它在有 ASM 的 classpath 上真的链得上，不是躺在那儿的死类）、
`constpool-scan` 无 tag 15/16/17/18、`selfhost-fixpoint`
**B == C**、`native-fixpoint` **B == C**、`core-diff` 的 `changed` 桶**恰好是
`main` + `rtclasses` 两个我改的模块**（无 ADT-shifted 桶、无余数；三个程序 golden 未动），
`selfhost-prev-diff` / `run-diff` / `fmt-diff` / `lsp-diff` / `spike-native` / `doc-check`。

**这一刀没有关掉什么**（别把它读成 BOOT-01 已收）：`dawn/tool/AdtClassWriter.class`
仍然在 jar 里、仍然是全部调用点的目标、仍然是 5,148 字节。期 1 只是把**下一代种子的
classpath 备好**。真正的减法在期 3。

#### 期 2 + 期 3 落地记（v0.49.0 之后，2026-08-03）

**期 3 折进了期 2，省掉一次发布。** §5.7 原本排了三次发布，这里改正它：**测出来
只需要两次** `[实测]`。

原文把「期 3 要等一次发布 + 推进种子」当成前提写死了。实际前提只有一条——
**种子的 classpath 上要有 `dawn/rt/Asm`**，而那正是 v0.49.0 供上的；期 3 自己的
前提是「没有源码再引用 `dawn/tool`」，这在期 2 的同一个提交里就已成立。链条走一遍：
种子（期 1 那代）带 `dawn/rt/Asm` → 它编期 2 的源码得 A，`use java "dawn.rt.Asm"`
对着种子的 classpath 解析通过，A 的 jar 里的 `dawn/rt/Asm` 是**种子发射**的
（A 仍 import `ClassWriter`，`program_has_asm` 仍为真）→ A 编出 B、B 编出 C，各自
对着上一代的 classpath 解析。**不是论证，是跑出来的**：`selfhost-fixpoint.sh`
**B == C**、`native-fixpoint.sh` **B == C**，两条都在 `--vendor dawn/tool` 已删掉
之后跑的 `[实测]`。

**期 2 做了什么**：`use java "dawn.rt.Asm"` 进四个发射器，`AdtClassWriter.` 前缀
在 `emit`/`codegen`/`rtclasses`/`testrun` 里替换掉，`gen_asm_class` 自己也改用 `Asm`
——这一代用 N−1 代的适配器写新适配器。源码调用点 **114 处**，与 §5.7 预告的
发射调用点数**恰好相同** `[实测]`（`emit` 27 / `codegen` 22 / `rtclasses` 60 /
`testrun` 5）。顺手把 `scratch_mv` 那个一次性写入器的名字从 `dawn/tool/Scratch`
改成 `dawn/rt/Scratch`：它从不落盘，但留着会让「没有源码再提 `dawn/tool`」这句话
在 grep 下不成立。

**期 3 做了什么**：`--vendor dawn/tool` 从 `bin/dawn`（两个构建阶段）、
`scripts/selfhost-fixpoint.sh`、`scripts/replay-bootstrap.sh`、
`scripts/selfhost-bench.sh`、`.github/workflows/release.yml` 里删掉；
`vendor.dawn` 的 `vendor_trust` 去掉 `dawn/tool` 分支和那个 digest。
`vendor.dawn` 的测试里**新加一条 `assert vendor_trust("dawn/tool") == None`**——
退休了的前缀要是哪天又被 `--vendor` 抄进来，走的是「未登记 → panic」那条路，
而不是被默默信任。

**调用点真的移了：**`[扫描]`**。** 这是本刀最容易假绿的地方：两个适配器**行为完全
一致**（`asm-adapter-contract` 证的就是这个），所以只要 `dawn/tool` 还在 classpath
上，一处都没改的编译器**照样构建、照样自举、门禁照样全绿**。
新门禁 `scripts/adapter-callsites.py` 读发射出来的常量池直接回答：

```
scanned 1048 class files in 1 directory
  name dawn/rt/Asm:  5 classes
  name dawn/tool/*: 0 references
OK: the adapter surface is reached, and only at dawn/rt/Asm
```

`javap -c` 独立复核（1048 个类的反汇编按成员名计数）`[实测]`：

| | `methodOn` | `plain` | `beginOn` | `fieldOn` | `beginOnWithInterface` | 合计 |
|---|---|---|---|---|---|---|
| `dawn/rt/Asm` | 54 | 22 | 18 | 16 | 4 | **114** |
| `dawn/tool/AdtClassWriter` | 0 | 0 | 0 | 0 | 0 | **0** |

**两条断言缺一不可**，因为各自单独都是可满足的。「没有 `dawn/tool` 引用」在空目录上
恒真——拿 `site` 语料（没有 ASM）实跑一遍就能看见 `[实测]`：

```
scanned 177 class files in 1 directory
  name dawn/rt/Asm:  0 classes
  name dawn/tool/*: 0 references
FAIL: nothing names dawn/rt/Asm -- the adapters are not reached at all
```

**新门禁的红演示 + 负控** `[实测]`。变异体 M1：`codegen.dawn` 里**一处**调用点改回
`AdtClassWriter.methodOn`（连带补回 `use java`），退出码 1，且指得出是哪个类：

```
scanned 1048 class files in 1 directory
  name dawn/rt/Asm:  5 classes
  name dawn/tool/*: 1 references
FAIL: 1 reference(s) to the vendored adapter remain
      /tmp/ka7-emit/codegen.class: dawn/tool/AdtClassWriter
```

负控 M2：把 `scratch_mv` 的名字**改回** `"dawn/tool/Scratch"`——一个真实落在字节里的
改动（`emit.class` 前后 `cmp` 不同，实测确认它落地了），而这道门禁**照旧绿**。
这就是负控要证的事：它读的是常量池里的 `CONSTANT_Class`，不是「文本里出现过
`dawn/tool`」，所以它不是个「什么都变红」的报警器。两个变异体的输出不同、且都与
正确版本不同，门禁因此是有判别力的。

**`dawn/tool` 出 jar 了** `[实测]`：

```
$ unzip -l build/dawn-selfhost.jar | grep -E "dawn/tool|dawn/rt/Asm"
     1225  2020-01-01 00:00   dawn/rt/Asm.class
```

（`dawn/tool/AdtClassWriter.class` 无匹配。）编译器照常工作：`dawn --version`、
`dawn test selfhost` 299 项、`classfile-verify` selfhost 语料仍 1048 个类
**0 illegal / 0 not initializable**——`not initializable` 为 0 说明 `dawn/rt/Asm`
真的链得上，不是躺着的死类。

**`asm-adapter-contract` 的参照换了源，红演示重跑过。** 期 3 之后 jar 里没有
`dawn.tool.AdtClassWriter` 了，`Class.forName(REF)` 无处可取。参照改成**从
`kotlin-final` tag 的 Java 源现编**（`git show` + `javac`）——这比读 jar 里那份
二进制更好：它是那份二进制的来源，而且不会随二进制一起消失。门禁日志里打出参照
的 code source（`from file:.../ref/`），换没换一眼可见。

改了门禁就要重跑它的红演示。变异体 2（`beginOn` 把 `name` 当 `signature` 传）
**复现出与期 1 逐字相同的形状** `[实测]`——2 红 5 绿，红的恰是走 `beginOn` 的两项：

```
FAIL  beginOn/fieldOn/methodOn produce identical class files
PASS  beginOnWithInterface produces an identical class file
FAIL  plain(0) produces an identical class file
PASS  the probe is flag-sensitive (COMPUTE_MAXS differs from 0)
PASS  the emitted adapter forwards its flag
PASS  the emitted adapter's class links and runs (square(7) == 49)
PASS  the interface form declares its interface
FAIL: 2 adapter difference(s); dawn/rt/Asm is not a drop-in for dawn.tool.AdtClassWriter
```

**变异体 1（`plain` 不转发 flag）的红变了形状，这是期 2 带来的真实变化** `[实测]`。
期 1 里 `gen_asm_class` 用参照适配器写这个类，所以写出来的类**本身是良构的**，只是
`plain` 的方法体不对，门禁能跑完七项报 5 红。期 2 之后它**用自己写自己**，同一个缺陷
自我作用：写出来的 `dawn/rt/Asm.class` 连 `maxLocals` 都不对，加载即
`ClassFormatError`，后面一项也比不了。红更早更狠，但**判别信息变少了**。为此给
`Diff.java` 加了一层：把加载失败报成一条 FAIL 行而不是裸栈：

```
FAIL  the emitted dawn.rt.Asm is a loadable class file
      java.lang.ClassFormatError: Arguments can't fit into locals in class file dawn/rt/Asm
FAIL: the emitted adapter does not load; no entry point could be compared
```

改回来即刻回到 7 项全绿。

**BOOT-01 的状态：`dawn/tool` 这一项从「缓解」转为「关闭」，但要说清楚剩下什么。**
按用户的裁决——「如果结论是『留着但不可达』，那记成缓解措施而不是关闭」——K-A4 当时
只能记缓解，因为那 5,148 字节还在 jar 里，不可达只是个关于当天调用点的论断。现在
**它不在 jar 里了，也不在 `vendor_trust` 里，也不在任何 `--vendor` 的调用里**，
所以这一项可以记成关闭。

**关闭的是「无源二进制」这个性质，不是「不依赖上一代」**：第 N 代 jar 里的
`dawn/rt/Asm` 仍然是第 N−1 代发射的。那是编译器自举的常态、也正是 DDC
（diverse double-compiling）能处理的形状，与「源码不存在、只能逐字节抄」是两回事——
后者 DDC 无从下手。另外 **`org/objectweb/asm`（38 类 / 253,894 B）与
`coursierapi`（2,409 类 / 10,057,897 B）原封不动**，两者都还在 `--vendor` 和
`vendor_trust` 里（前者记哈希、后者按成本豁免）。§0 那张表现在少了第一行，另外两行
一个字没动。

**V49 这条线拆掉的是二进制里危险的那一半**——写 class 文件的那个手写 Java 没了源码
问题。jar 体积那类副产品不是这一刀的论点，别让它爬到叙述前面来。

**门禁**（本次逐条跑过，全绿）：`dawn fmt --check`、`dawn test selfhost` 299 项、
`dawn test site`、五个包的测试、JSON 套件、`classfile-verify`（八语料 1948 类，
0 illegal / 0 not initializable，含常量池 tag 15/16/17/18 扫描）、
`asm-adapter-contract` 7/7、**`adapter-callsites`（新）**、`selfhost-fixpoint` B == C、
`native-fixpoint` B == C、`spike-native`、`native-cli-diff`、`core-diff`
（`changed` 桶两次都恰好是我改的模块：期 2 是 `codegen`/`emit`/`main`/`rtclasses`/
`testrun`，期 3 是 `vendor` 一个；**无 ADT-shifted 桶、无余数**，两次都 `--record`
重录、没有手动合并）、`selfhost-prev-diff` 六语料 + 生态三项、`run-diff`、`fmt-diff`、
`lsp-diff`、`doc-check`、`intrinsic-parity`、`opaque-twin`、
array/hamt/pvec/path/inflate/unicode/error/rc 八个契约、`table-freight`、
`grammar-corpus`、`checker-corpus`、`lock --check`。

#### 自发射把 Thompson 攻击缩到了 1,225 字节（任务 #134，2026-08-04）

期 2 之后 `gen_asm_class` **用适配器写适配器**——那五个静态方法自己发射自己。这是编译器
自举的常态，但它同时把 [Thompson 的 trusting-trust](https://dl.acm.org/doi/10.1145/358198.358210)
**原样缩到小尺度重放了一遍** `[推论]`：一个足够讲究的错适配器可以发射出一个同样错的
适配器，产物**加载得了、自洽、行为一致**，于是

- `selfhost-fixpoint` 照旧 **B == C**——固定点复现一个被替换过的编译器，和复现一个诚实的
  编译器一样忠实，这正是 `codebase-audit.md` BOOT-03 那句「固定点证明被表述成了供应链证明」；
- `scripts/adapter-callsites.py` 照旧全绿——它数的是常量池里的 `CONSTANT_Class` 引用，
  不是语义；
- 期 3 关掉的是「**无源二进制**」这个性质，**不是**「不依赖上一代」。BOOT-01 的威胁模型
  没有随那 5,148 字节一起消失，它**搬家了**：从一块续传的 vendored 二进制，搬到一个
  1,225 字节的自发射类上。

**挡在前面的只有一条链，而且只有一处**：`asm-adapter-contract` 的参照是 **javac 从
`kotlin-final` tag 的 Java 源现编的**。那是整条链上**唯一不经过 Dawn 编译器**的一步，
也就是 DDC（diverse double-compiling）论证的立足点。

**问题在于这个独立性是承重的、却是隐式的** `[推论]`：没有任何东西声明「参照必须独立编译」。
要是哪天有人觉得「编 Java 太麻烦，直接跟发射出来的类比不就行了」，门禁**照样 7/7 全绿**，
DDC 性质无声蒸发——这正是本仓的头号失效形态。另一个危险动作是把 tag 里的源**抄进工作树**
「以免 tag 哪天不可达」：tag 拉不到是**幸运**结局（响得很大声），抄进工作树才是灾难——
参照从此变成一个我们自己的提交能改的文件，而且看起来更稳健了。

##### 落地：一条不变式 + 两道机器兜底 + 判别力复原

**不变式写进了 `scripts/asm-adapter-contract/run.sh` 的头注释**，连同理由（光写「别改这里」
挡不住一个有理由的人）。三条：参照必须由**另一个工具链**（javac）从**归档源**编；
门禁不得改成跟我们自己构建出来的任何东西比；tag 里的源不得抄进工作树。

**机器兜底两道，都演示过红** `[实测]`：

1. **工作树副本守卫**（`run.sh`）：`REF_SRC` 路径不得存在，且 `git grep 'class AdtClassWriter'
   -- '*.java'` 不得命中。**能力边界要说清**：它挡的是「一份 Java 副本落进树里」这个具名动作，
   挡不住换类名的副本，也挡不住有人直接删掉这道检查。
2. **参照异源守卫**（`Diff.java` 的 `referenceIsForeign`）：断言参照**不是这个编译器写得出来的
   类**。发射出来的适配器恰好是 `java.lang.Object` 上的五个 public static——无字段、无构造器、
   无父类；而 tag 里那份是 `ClassWriter` 子类，带 `supers` 字段、两个构造器、
   `getCommonSuperClass` 覆写和四个 §5.7 实测**零调用点**、因而**故意没有重新发射**的实例
   helper。「参照必须仍然带着我们选择不发射的那些成员」——参照一旦变成我们自己的产物，
   这句话立刻不成立。

**没有做的、以及为什么** `[推论]`：三个方向里有一个判为**不诚实**，没有实装——「断言参照源是
经 `git show kotlin-final:<path>` 取的」。任何写在 `run.sh` 里、断言 `run.sh` 用了 `git show`
的检查都是自指的：删掉 `git show` 的那一次编辑顺手就把断言也改了。放到 `run.sh` 外面 grep 它，
也只是个拼写检查——**断言的是某个字符串在场，不是那个性质成立**。**一道不可能变红的检查，
本身就是这个任务要防的那个错误。**上面两道之所以留下，是因为它们各自对着一个具体的危险重构
**真的会红**，且演示过。至于「没有门禁能断言自己的独立性」——那部分的缓解就是头注释，
这不是遗憾，这是结论。

##### 变异体 1 的判别力：丢了，又拿回来了 `[实测]`

**原因**：`gen_asm_class` 在写「定义 plain/beginOn/methodOn 的那个类」时，自己正调用
`Asm.plain`/`beginOn`/`methodOn`。所以这三个里的缺陷**在同一时刻**既污染被发射的字节、
又污染发射它的代码路径，产物**畸形**而非仅仅**错误**（`ClassFormatError:
Arguments can't fit into locals`），门禁跑不完，说不出是哪个入口点。

**解法：把「写出去的字节」和「执行的代码路径」拆开。** 同一份 tag 源再用 sed 换个
包名/类名编成 `dawn.rt.Asm`（只改 `package` 与类名，五个静态方法是 tag 的 javac 产物），
**放在 jar 前面**顶掉 classpath 上的 `dawn/rt/Asm`。于是发射器仍是今天的 `gen_asm_class`，
而**替它干活的适配器是参照**。五路判别力回来了，并且这次发射多退了一步 javac。

门禁因此变成**两个受试体**，每次都各跑一遍完整的七项差分：

| 受试体 | 谁写的 | 它能抓什么 |
|---|---|---|
| `self-emitted` | 适配器写适配器（bin/dawn 出的那份，**就是进 jar 的产物**） | 上一代传下来的缺陷 |
| `reference-emitted` | 今天的 `gen_asm_class`，但由 javac 参照代劳 | 今天源码里的缺陷，**且指得出入口点** |

两者字节相等时第二遍在构造上冗余——**照跑不误**：这是「判别力在工作」与「判别力躺在一个
没人走的分支后面」的区别。

**新增第三项断言：两次发射逐字节相等。** 这不是差分的复述——它覆盖的是**今天的
`gen_asm_class` 完全正确、而写出那份 jar 内副本的上一代适配器不正确**的情形。

##### 门禁自带负控：canary `[实测]`

classpath 顶替**没生效**是看不见的：两次发射会一模一样，全部检查照旧绿，解耦白做。
这就是 2026-08-03 `scripts/classfile-verify` 被抓到的那个形状。所以门禁**自带一个变异体**：
第三份 shadow，`plain` 拒绝转发 flag，每次都断言它**改变了发射结果**。

比较对象是 `reference-emitted` 而**不是** `self-emitted`：两边都是 shadow 发射的、只差
shadow 本身，机制失效时两者必然相等。早先的版本拿 `self-emitted` 比，结果变异体 1
（`plain` 不转发 flag）跑出来时这道负控**跟着红了**——它对着自己本该独立的那件事开火。
换成对 `reference-emitted` 比之后不再误报 `[实测]`。

##### 六个演示，每个都带判别性负控 `[实测]`

改了门禁就得重跑红演示，原来的 7/7 不顺延。当前绿态是 **18 项全绿**
（1 工作树守卫 + 1 参照异源守卫 + 1 canary + 1 两次发射字节相等 + 两个受试体各 7 项）。
六个演示：

| # | 变异体 | 结果 | 它证明了什么 |
|---|---|---|---|
| D1a | tag 里的源抄回 `compiler/src/main/java/dawn/tool/` | 红（守卫 1） | 工作树副本挡得住 |
| D1b | 同一份源换个路径 `git add -N` | 红（守卫 1） | 不只盯那一个路径 |
| D2 | shadow 放到 jar **后面**（解耦静默失效） | **17 绿 1 红**，红的只有 canary | 负控真的在看 |
| D3 | 参照改指**编译器自己发射的类**（就是那个危险重构） | **14 项差分全绿**，只有守卫 2 红 | 门禁不加这道就是全绿放行 |
| D4 | 源码正确，jar 里塞一个被改过的上一代适配器 | **14 项差分全绿**，只有字节相等红 | 见下 |
| D5 | `gen_asm_class` 的 `plain` 写 `iconst_0` 而非 `iload_0` | self 加载即死；**reference-emitted 复现期 1 的 5 红 2 绿**，`plain(0)` 照绿 | 判别力拿回来了 |
| D6 | `gen_asm_class` 的 `beginOn` 把 name 当 signature | 两块都是 **2 红 5 绿**，红的恰是走 `beginOn` 的两项 | D5 的判别性负控：形状不同 |

**D4 是本次唯一一处真正的能力增益，不只是诊断变清楚** `[实测]`。把 tag 源改成
`beginOn` 传一个合法的 `Ljava/lang/Object;` 当 signature，编好塞进 jar 副本顶掉
`dawn/rt/Asm`——模拟「今天的源码没问题，上一代传下来的适配器有问题」。产物 **1266 B**
（对 1225 B），行为**完全正确**（差异只在被发射类自身多了个 Signature 属性，差分看不见）。
**改前的门禁在同一个 doctored jar 上是 7/7 全绿、退出码 0**（实跑 `git show HEAD:` 的旧版
复核过）；改后红在「两次发射逐字节相等」这一项。

D5 与 D6 的形状不同、且都与正确版本不同，所以门禁不是个「什么都变红」的报警器。

##### 这道门禁现在依赖什么 `[推论]`

写下来，免得下一个人重新推一遍：

1. **`kotlin-final` tag 可达**，且其中的 `AdtClassWriter.java` 未被改写。tag 没了 → 门禁大声
   坏掉，这是好结局。
2. **javac 与 Dawn 编译器不同源**。DDC 的全部力量在此。javac 自己被投毒不在本门禁射程内
   （那是 JDK 供应链问题，另一条线）。
3. **`org/objectweb/asm` 与 `coursierapi` 仍然是逐字节续传的 vendored 二进制**（38 类 /
   253,894 B、2,409 类 / 10,057,897 B，§0 那张表的后两行）。ASM 才是真正写 class 文件的那个
   ——本门禁两侧**用的是同一份 ASM**，所以它证不了 ASM 的任何事。K-A7 关掉的是适配器，不是
   ASM。
4. **没有门禁能断言自己的独立性**。守卫 1、2 各挡一个具名的危险重构，挡不住有人把它们删了。
   头注释在这里是**承重构件**，不是装饰。

**跑时开销** `[实测]`：三次 `__emit selfhost`（self / ddc / canary）+ 三次 javac，
本机 13.8 s（jar 已在）。改前是一次 emit、5.6 s。

**门禁**（本次逐条跑过）：`asm-adapter-contract` **18/18**、`adapter-callsites`、
`classfile-verify`（含 `constpool-scan`）、`dawn test selfhost` 299 项、
`dawn fmt site selfhost packages --check`、`selfhost-fixpoint` **B == C**、
`shellcheck scripts/asm-adapter-contract/run.sh`。**编译器源码一行未改**
（`selfhost/src/rtclasses.dawn` 只在做变异体时改过，演示完即 `git checkout` 还原并重建），
所以**没有 Emit-Change**，`core-diff` / `native-fixpoint` / `*-diff` 系列不涉及。

### 5.8 V49 未必是单向门：一半成立，一半已被实验证伪（§4 第 17 条）

本节原文自己写着「动工前必须先实测这条推论」。2026-08-03 实测了，**结论是一半对一半错**，
两半都留在这儿。

#### 仍然成立的一半：oracle 的难度确实是从 ASM 的处境继承来的 `[推论]`

§5.2 判「自算 StackMapTable 明显更难」，难点落在**公共超类型求解**。这个判断值得挂一个
问号：**那个难度是从 ASM 的处境继承来的**。ASM 面对的是「一个它加载不了的类」，所以
必须外挂 oracle（`getCommonSuperClass`），所以 `supers_of` 那张合成表才存在。
**Dawn 不在那个处境里**——它刚从 AST 建完整个类型层次，`Adts` 就在手上，查自己的符号表
就能答，而且答案对**尚不存在的生成类**同样成立（那正是 `supers_of` 当初能写出来的原因）。

再加两条已经量过的：控制流很干净（`tableswitch`/`lookupswitch` **0 条**，5,478 个有 Code
的方法里**只有 8 个**有异常表，§5.2），而且写出来是 **Dawn 代码，不引入新的手写 Java**。

**这一半没有被推翻，别删。** 2026-08-03 的测量反而给它加了个数：今天的帧里引用条目指向
**284 个不同的精确类**，全都是符号表答得出的（§5.2 第 1 项）。

#### 被证伪的一半：保守格（引用一律压 `java/lang/Object`）不成立 `[实测]`

**原先怎么说**（`[推论]`，原文照录）：

> 两个宿主引用类型在汇合点合流时，**并到 `java/lang/Object` 永远是合法的公共超类型**；
> 只在「后续还需要更精确的类型而又没有 `checkcast`」时不够用。若这条成立，难度就从
> 「实现一个类型格求解器」掉到「实现帧的增量编码」（same / same_locals_1_stack_item /
> chop / append / full）。

**实验怎么答**：把 `.dawn/seeds/v0.48.0/seed.jar` 里 Dawn 发射的 1022 个类中**全部 72,408 个
tag 7 站点改写成指向 `java/lang/Object`**（其中 72,040 个索引真的变了；另 368 个本来就指向
`Object`，与 §5.2 第 1 项的 368 精确对上，互为校验），再用仓库现成的
`scripts/classfile-verify/Verify.java` 强制链接。

改写是**零代价**的：tag 7 条目固定 3 字节，改的只是常量池索引，`attribute_length` 与所有
偏移都不动；1022 个类每一个本来就带 `java/lang/Object` 的 `Class` 项，常量池一次追加都不
需要——**1022 个文件改写后逐个与原文件字节数相同**。所以这个实验测的是纯粹的类型问题，
没有体积变量混进来。

| | 通过 | **非法（`VerifyError`）** |
|---|---|---|
| **对照组** `orig/`（未改写） | **1022** | **0** |
| **实验组** `new/`（tag 7 全压 `Object`） | **953** | **69** |

**对照组零失败是这个结果能被采信的前提**（负控干净，测量环境本身没问题）。

1022 个类里有 **601 个一条帧都没有**（ADT case 类、闭包类、字典类——无分支），与本实验
无关；**真正有帧的是 421 个，其中 69 个失败 = 16.4%**。而且 **JVM 在每个类的第一个失败
方法处就中止验证**，所以 69 是失败**类**数，失败**方法**数只多不少，这个实验测不出上界。

**四族失败——它们就是「精度不够」的实际形态**：

- **族 A：`athrow` 要 `Throwable`（23 例，最大一族）**
  `analyze.put … @61: athrow — Type 'java/lang/Object' (current frame, stack[0]) is not
  assignable to 'java/lang/Throwable'`。异常值一旦在某个汇合点被声明成 `Object`，后续
  `athrow` 就过不去。§5.2 里 `java/lang/Throwable` 有 4,117 条帧条目，就是这个位置。
- **族 B：后续调用要精确类型（37 例）**
  `add.bad_subdir … @29: invokestatic — 'java/lang/Object' is not assignable to 'std/pvec$Vec'`。
  注意报告里有 `stack[7]`、`stack[3]`——被压宽的值在栈上待了很久才被消费，不是「压完立刻用」
  这种好抓的形状。
- **族 C：`areturn` 要方法签名的返回类型（7 例）**
  `astdump.atoms … @36: areturn — 'java/lang/Object' is not assignable to 'java/lang/String'
  (from method signature)`。
- **族 D：入口帧不可放宽（2 例）**
  `std/map.hash_go … @0: lload_1 — locals[0] 'java/lang/Object' 不可赋给 stack map 的
  'std/pvec$Vec'`。尾递归自循环使 **bci 0 成为分支目标**，那条 offset 0 的帧要与**方法描述符
  推出来的初始帧**核对。**方向是反的**：校验器嫌**声明帧比推导帧宽**——「往宽了写总是安全的」
  在这个位置直接不成立。

**两条顺带排除的**：69 个失败里**没有一条**要求的是接口类型（校验器确实把接口当 `Object`
看，协调者预判的那种可疑形态没有出现）；也**没有一条**直接要求 JVM 数组类型。但因为每类
只报第一个错，这不能当成「接口/数组位置安全」的证明。

**推论的净结果**：oracle 躲不掉，`[推论]` 里「难度掉到只剩增量编码」那一步作废。
正确的替代说法在 §5.2——**三项有界的活**，而不是「一项算法活」或「一项格式活」。

#### 对 K-A4 的影响

**方向不变**：V49 让这整块消失，**K-A4 已经落地**（§5.6，随 A 线 #127），这里不是在
建议什么，是在给已经关上的那扇门称重。**权重仍然该降，但降得比原先少**：自算帧不是
不可行（§5.2 那四项都有界，且最贵的 oracle 对 Dawn 便宜），所以 D5 的「不可逆」没有
原来看上去那么硬；但它也不是「顺手就能补」的格式活，回 ≥50 是一个要排期的子系统，
不是一个开关。

### 5.9 「发射时顺手记账」：部分成立（任务 #132，2026-08-04）

§5.2 上一轮留下的最后一条未实测断言，原文照录：

> 发射器**根本不需要「推断」帧**。它每压一个值都是从带类型的 IR 发射的，**压栈那一刻
> 就知道精确类型**。所以要做的不是「对已经发射出来的字节码做抽象解释」，而是
> **「发射时顺手记账」**——只有汇合点需要合并，合并才需要问符号表。

它承重：它决定 V49 那扇门有多可逆。**裁决：前半成立，后半被推翻。**

| 断言拆开 | 裁决 |
|---|---|
| 「记账，不是对字节码做抽象解释」 | **成立** `[实测]` |
| 「只有汇合点需要合并」 | **成立** `[实测]`（可达帧 64.9% 只有一个前驱，根本不合并） |
| 「合并才需要问符号表」 | **成立且比预期便宜** `[实测]`（0.077% 的条目，88 条不同提问，全是一次查父类） |
| 「**一遍**顺手记账就够」 | **推翻** `[实测]`（循环头看不见回边，写出的类型太窄） |

#### 实验怎么做的

不去实现自算帧（那是动工，本任务不做），而是**模拟记账纪律**再和真值对拍：

- **真值** = ASM `COMPUTE_FRAMES` 已经算在 jar 里的 `StackMapTable`。
- **被测方** = 一个纯 Python 的前向模拟器，只用**指令 + 常量池描述符**推类型
  （`checkcast X` → `X`、`invoke*` → 描述符返回类型、`new` → `Uninitialized(bci)`、
  `invokespecial <init>` → 把栈上和 locals 里**每一份**那个 `Uninitialized` 换成初始化后的类……）。
  **这比发射器手里的信息严格更少**（描述符 vs 带类型的 IR），所以**它成功 = 发射器必然成功**，
  它失败才可能是发射器的洞。这条不对称是整个实验能成立的前提。
- 每个帧偏移与 bci 0 各起一个块，块的入口状态取**该处声明的帧**（bci 0 取描述符推出的隐式帧），
  于是误差留在局部不会串味；再把每条前驱边送到每个帧偏移的状态收齐，用一个**没有 oracle 的格**
  合并（相等→原样、沾 Top→Top、两个不同引用→记一次 oracle 提问），最后与声明帧逐条比。
- 为什么局部对拍能推出全局：bci 0 的入口状态**不是**取自声明帧，是描述符算的；而每个声明帧
  都被证明等于其全部前驱出口状态的合并——从 bci 0 归纳上去，整条链就都是从描述符导出的。

#### 结果：两个互相独立的语料

| | seed v0.48.0（编译器自身，1022 类） | backend-dawn.jar（web 后端，171 类） |
|---|---|---|
| 帧总数 | **43,049** | **10,843** |
| 分析到的帧 | 43,049（100%） | 9,262（85.4%） |
| 跳过 | 0 | 1,581（144 个还带 `invokedynamic` 的方法，该 jar 是 K-A3 之前那代） |
| 不可达帧（ASM 死代码改写产物，无前驱） | 4,296 | 987 |
| **可达帧** | **38,753** | **8,275** |
| **逐条重建成功** | **38,753（100%）** | **8,275（100%）** |
| 只有 1 个前驱（完全不用合并） | 25,157（64.9%） | 5,275（63.7%） |
| 前驱状态真的不同（需要合并） | 3,959（10.2%） | 684（8.3%） |
| 需要 oracle 的帧 / 条目 | 517 / **533** | 207 / 207 |
| 不同的 oracle 提问 | **77** | **27** |
| 异常处理器帧 | 2 | 1 |

**两个语料合计 88 条不同的 oracle 提问（seed 77 + backend 27，重叠 16），无一例外是
「输入的直接父类」，父类全是 Dawn 自己发射的 ADT。**
最常见的几个：`join(Option$None, Option$Some) = Option` 152 次、`join(Option, Option$None) = Option`
90 次、`join(Result$Err, Result$Ok) = Result` 44 次。零个答案是 `java/lang/Object`，
零个牵扯 JDK 类，零个要爬一层以上。

`[口径]` 两处要说清：**(a)** oracle 位置在对拍时按**通配**处理（记下真值要求的答案，不算重建失败），
所以严格说「100% 重建」是「99.92% 逐条相等 + 0.077% 委托给一次查父类」。
**(b)** 异常表在 v0.48.0 上只有 **2 个方法**（backend-dawn 1 个，两边都是 `catch dawn/rt/PanicError`），
所以「处理器帧也重建成功」的样本量是 2 和 1，**基本等于没测**——§5.2 引的「8 个」来自审计当时
那份语料，不是这份，别把两个数当同一个。

#### 被推翻的那半：循环头

`emit.dawn:2211` 的 `CSLoop` 先 `visitLabel(top)`，走完 body 与 step 才发 `goto top`。
**单遍记账走到 `top` 时，回边还不存在。** 于是问：只用**偏移比帧小**的前驱（即单遍走到那儿
时已经见过的那些）合并，答案还对不对？

- seed：1,494 个帧有回边前驱，**1,456 个照样对，38 个不对**（涉及 34 个方法）。
- backend-dawn：139 个有回边前驱，**0 个不对**。

**38 个全是同一个形状，而且方向是坏的那个**：单遍答案是真值的**严格子类型**——44 处槽位差异
逐一用类层次机器判定，**44/44 都是「更窄」，0 个「更宽」**。

```
add.run_add     @21   声明 = Option        单遍 = Option$None
checker.check_match @559 声明 = types$Ty   单遍 = types$Ty$TyNever
lower.pat_test  @280  声明 = core$CExpr    单遍 = core$CExpr$CBool
```

槽位差异按对分布：`Option$None → Option` 32、`core$CExpr$C*  → core$CExpr` 7、
`types$Ty$Ty* → types$Ty` 3、其余 2。

来源清楚：入口路径上那个槽装的是 `None`，回边上装的是 `Some`。**「往窄了写」正是校验器
拒绝的方向**——这与 §5.8 族 D（`std/map.hash_go` 的 offset 0 帧）是同一条规则的两次撞击，
那次撞的是方法入口帧，这次撞的是循环头。

所以第 4 项不是「优化」，是**正确性前提**：自算帧要么对循环体跑第二遍/定点，要么在
lowering 阶段保证回边不会加宽任何槽（后者是个未验证的语言级约束，`[推论]`，别当便宜话）。

#### 负控：这四个数不是因为检查器不会红

「一条检查没被证明会红，它的绿不说明任何事」。四个变异体，每个只改一处，
**基线 0 红，四个全红**（红的数量本身也有信息：改得越靠近核心，红得越多）：

| 变异 | 改了什么 | seed 红帧 | backend 红帧 |
|---|---|---|---|
| 基线 | —— | **0** | **0** |
| `MUT=cmp` | 只在**对拍那一刻**把真值的第一个 `Object` 条目改宽（不污染块入口种子） | **35,983 / 38,753** | 5,690 / 8,275 |
| `MUT=cast` | `checkcast X` 改成压 `java/lang/Object` | 2,006 | 404 |
| `MUT=init` | `invokespecial <init>` 不再把 `Uninitialized` 换成初始化后的类 | 955 | 268 |
| `MUT=join` | 合并时保留第一个输入而不加宽 | 369 | 166 |

`MUT=cmp` 是最关键的一个：它证明**对拍本身有齿**——把真值改动一个条目，93% 的可达帧立刻翻红。
（先写的 `MUT=truth` 版本连块入口种子一起改宽，结果自洽，只红了 16%——**那种变异体测不出东西，
留在这里当反面教材**：变异体也要挑，改到能被系统自我吸收的地方等于没改。）

而「单遍够不够」那项检查**在基线就自己红了 38 个**，同一次运行里同时给出 1,456 绿和 38 红——
它的区分度不需要另外演示。

#### 这条对 V49 那扇门的净影响

比 §5.8 收尾时又硬了一点点，方向没变：

- **变便宜的**：最贵的那项（oracle）现在有了数——**88 条不同提问全是一次查 `adt_parent_of`**。
  「Dawn 刚从 AST 建完类型层次，查自己的符号表就能答」不再是类比，是实测。
- **变贵的**：多了第 4 项。发射器**不能**只是一边发一边记，它对**循环体要跑两遍**（或定点）。
  这把「顺手记账」从「零结构改动」变成「发射器要能重放一段」——`emit.dawn` 今天是**单遍树遍历**，
  重放一段 `CSLoop` 的 body 不是免费的。
- **净结论**：回 ≥50 仍然是**一个要排期的子系统**，不是一个开关；但四项都有界、都量清了，
  它也不是不可行。D5 的「不可逆」照旧该读成「贵，不是不可能」。

#### 复现

原始输出与脚本在 `~/workspace/notes/`（**不在仓库里**，同 §5.2 引的那份测量报告）：
报告 `stackmap-shape.md` 尾部的「追加二」，脚本 `stackmap-ledger/`（纯 stdlib，无第三方依赖）。

```bash
cd ~/workspace/notes/stackmap-ledger
python3 ledger.py    ~/workspace/dawn-lang/.dawn/seeds/v0.48.0/seed.jar   # 主表
python3 fwd.py       ...seed.jar        # 38 个单遍分歧，逐槽打印
python3 direction.py ...seed.jar        # 判定分歧方向（更窄/更宽）
python3 oracle.py    ...seed.jar        # 104 个 oracle 提问的分类
MUT=cmp python3 ledger.py ...seed.jar   # 负控，另有 cast / init / join
```

本次实验**未触发任何构建、未运行 `bin/dawn`**，只读 jar。

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
- **不自己算 StackMapTable**（§5.2）。**这条的理由已经打过折，也已经量清折多少**：
  「难度从 ASM 的处境继承来」成立（§5.8 前半），「保守格能把它降成格式活」被实验证伪
  （§5.8 后半，`[实测]`）。今天的正确理由是——它是**三项有界的活**，不是难度未知的一团，
  但仍然是一个要排期的子系统，而 V49 是减法。
- **不用 Dawn 重写 `AdtClassWriter`**（原 K-A2，已取消）。K-A4 之后没有 classfile writer
  可重写。§5.1
- **不把那块二进制"收小"当成关门**（原 K-A4b，已取消）。K-A4 之后它的危险那半只是
  **不可达**，字节一个没少；缩小不是关闭。要关门只有 K-A7：**从树内源重建它**。§5.6/§5.7
- **K-A3 不碰 classfile 版本**。版本下降是 K-A4 独立一刀，也是 D5 的不可逆承诺点
  （但见 §5.8：这个"不可逆"该降权——回 ≥50 可行，只是要排期，不是一个开关）。
- **K-A0/K-A0.5 不碰发射的任何字节**。两刀都没有 `Emit-Change`。
