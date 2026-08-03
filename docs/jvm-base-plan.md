# A 线：收缩 JVM 后端的可信底座

> 状态：**proposed**（2026-08-03 立项，任务 #127）。本文是 A 线的动工前设计：
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
   140 B vs 无帧 113 B），JVM 在 V49 下直接忽略它。必须同时把 `ClassWriter(2)`
   改成 `ClassWriter(1)`（COMPUTE_MAXS）——**而那正好在没有源码的那个类里**（§0）。
   这是 A 线两件事必须一起做的原因。

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

### 3.2 jar 体积：**净赚 −13.3%**

`[实测]` 目录级真实字节 + `[估算]` 闭包类那 61 KB（用 javac 编出的等形状类按捕获
元数直方图加权，均值 410 B/类，±20% 量级，对总数影响 < 0.5%）：

| | raw | zipped |
|---|---|---|
| 今天 (V61) | 3,122,794 | 1,351,682 |
| 降 V49（剥 StackMapTable/BootstrapMethods） | 2,647,538 (−15.2%) | 1,251,268 (−7.4%) |
| **净值**（再加 149 个闭包类） | **2,708,681 (−13.3%)** | **~1,288,668 (−4.7%)** |

单 `StackMapTable` 一项就占 478,044 B = **15.3% 的类字节**（2,292 个属性）。

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

第 6/7/8/9/10 条已随 K-A0 改掉（见 §6）。第 11/12/13 条是 K-A3 动工前复验刀序时测出来的，
已改进 §5。

**这批过期陈述的共同根因**：`scripts/doc-check.py` 只检查 `docs/` 下的状态标记、
链接与锚点，**不检查任何源文件头的事实陈述**。第 8 条能在一个自举成功的后端里
活着，就是这个缺口的直接产物。

## 5. 刀表与顺序

| 刀 | 做什么 | 可逆性 | 状态 |
|---|---|---|---|
| **K-A0** | 文档校正 + 本文 | 不碰发射的字节 | 本次 |
| **K-A0.5** | 给无源二进制上 checksum | 只加门禁 | 本次 |
| **K-A1** | 从 `kotlin-final` 捞回 `AdtClassWriter.java`，**先只当参照读**，不进主干 | 不改代码 | **已做**（§5.1） |
| **K-A3** | 闭包下降：`emit.dawn:1494` + `emit.dawn:656` → 显式类；81 处零捕获做单例。**仍在 V61 + COMPUTE_FRAMES 下做** | **Emit-Change，不可逆** | 待 |
| **K-A5** | 门禁：发射的常量池不得出现 tag 15/16/17/18 | 只加门禁 | 随 K-A3 |
| **K-A4** | `jvmops.dawn:26` `V17 = 61` → `49`；`ClassWriter(2)` → `(1)`；删 `getCommonSuperClass` 覆写与 `rtclasses.dawn:530` 的 adtSupers 表 | **Emit-Change**，D5 承诺点 | 待 |
| **K-A4b** | `dawn/tool` 收成静态 null 适配器（`extends ClassWriter` 与覆写一起删） | 换实现，可回退 | 待 |
| **K-A6** | 端到端重测 §3.3 的启动数（那两个数是微基准加减） | 只测量 | 待 |

**K-A2（用 Dawn 重写 `AdtClassWriter`）已取消。** 见 §5.1：K-A4 之后没有 classfile
writer 可重写——`AdtClassWriter` 里跟写 classfile 有关的部分整块消失，剩下的是个
null 适配器（K-A4b），那是另一件小得多的事。

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

**最后一环为什么断**：`AdtClassWriter` 干**两件**事，只有一件跟帧有关。

- 死掉的一半：`supers` 字段、两个构造器、`chain()`、`getCommonSuperClass()` 覆写，
  连同 `rtclasses.dawn:532` 的 `supers_of`（就是 Kotlin 的 adtSupers）——**这一半是净删**。
- **活下来的一半**：`begin`/`beginWithInterface`/`field`/`method` 四个实例方法与
  `plain`/`beginOn`/`beginOnWithInterface`/`fieldOn`/`methodOn` 五个静态方法。它们存在的
  理由写在类的 javadoc 里，和帧毫无关系：**Dawn 没有 null**，而 ASM 的 `visit`/
  `visitField`/`visitMethod` 的 `signature`/`interfaces` 形参是可空的。

所以准确的说法是：**「一行 classfile writer 都不用写」成立**（K-A2 因此取消），
**「`AdtClassWriter` 直接消失」不成立**。K-A4 之后它不再 `extends ClassWriter`、不再覆写
任何东西，收成一个纯静态的 null 适配器——`rtclasses.dawn` 今天走的已经是这条静态路径
（`AdtClassWriter.plain(0)` + `beginOn`/`methodOn`）。那仍是一份无源码的手写 Java 待在
可信底座里，只是小得多。要让它彻底归零，得先让 Dawn 能跨 FFI 传 null，那是另一条线。

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

### 5.4 一条长期战略风险，不是技术障碍

`[网络检索]` 没有找到任何 JEP 或 OpenJDK 计划移除 45–49 的 classfile 支持，
也没有移除推断式校验器的计划。HotSpot 的规则始终是「< 50 用推断式，≥ 50 用
StackMapTable」，JDK 26 上实测仍然如此。

**但风险不是零**：推断式校验器是 OpenJDK 想甩掉的历史包袱；`javac` 早已不能产出
< 52。一旦 Dawn 走 V49，它会成为**极少数**仍在生产 v49 的现代工具，生态上是孤岛。
这条要写进决策，不要装作不存在。

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
- **不自己算 StackMapTable**（§5.2）。
- **不用 Dawn 重写 `AdtClassWriter`**（原 K-A2，已取消）。K-A4 之后没有 classfile writer
  可重写，剩下的 null 适配器是另一件事（K-A4b）。§5.1
- **K-A3 不碰 classfile 版本**。版本下降是 K-A4 独立一刀，也是 D5 的不可逆承诺点。
- **K-A0/K-A0.5 不碰发射的任何字节**。两刀都没有 `Emit-Change`。
