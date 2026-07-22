# Selfhost P4：CodeGen 移植计划与通读笔记

> P3b（checker）已于 2026-07-22 全量对拍绿（见 selfhost-checker.md §七）。本文件是
> P4 的接力棒：目标、金标准、TAST 缺口清单、通读笔记，随移植推进持续更新。

## 一、目标与金标准

- 把 `compiler/src/main/kotlin/dawn/codegen/CodeGen.kt`（4205 行，ASM）移植成
  `selfhost/src/codegen.dawn`（+ 拆分文件），输出 **与 Kotlin 逐字节一致的 .class**。
- 金标准：`dawn __emit <target> -o <dir>`（新增 Kotlin 隐藏命令，把 generate() 的
  Map[String, ByteArray] 落盘为 <dir>/<name>.class）对 `selfhost emit <target> -o <dir>`，
  脚本 `scripts/selfhost-emit-diff.sh` 对拍两目录（diff -r 字节比较）。
  确定性前提：ASM COMPUTE_FRAMES 给定同输入是确定的；不产 jar（zip 时间戳不定）。
- ASM 依赖：selfhost/dawn.toml 加 `[java-deps]` org.ow2.asm:asm（与 compiler
  build.gradle 钉同版本）；`dawn run/test/build` 会经 coursier 拉取。
- 运行 selfhost 侧仍需 `-Xss512m`（沿 P3b）。

## 二、TAST 缺口（checker 需回填的 codegen 注解）

Kotlin CodeGen 从 checked AST 读的注解，逐一映射到 TAST：

- `e.type`（每个表达式的检查后类型）——TAST 未存！codegen 处处要（装箱、分支、erased
  槽位）。方案：TExpr 全变体加 `ty: Ty` 字段（大改），或 checker 在 (Cx, Ty, TExpr)
  已返回 Ty——但**子表达式**的类型丢了。落法：给 TExpr 每个变体补 ty 字段。
- Call.witnesses: List[WitnessRef]（Forward(trait,tvar,sym) | Concrete(impl)）——
  现 TAST 只有 has_witnesses: Bool。要存实引用（dict 转发 vs impl 单例）。
- Binary.ordWitness（< 等号越过标量时的 Ord 见证）——XBinary 只有 has_ord。
- MethodCall.samConvs: Map[argIdx, SamConv]、listBridges: Set[argIdx]、varargsPack
  ——TJavaCall 只有 varargs_pack。SamConv 要 (ifaceCls, samMethod) 数据。
- Lambda.captures 已有 ✓；LocalFn self-sym ✓；fnType（TyFn 完整型）要给 XLambda 补。
- CtorCall.fieldExprs ✓（written+slots）；ctorValue ✓（XCtorValue）；constDecl ✓。
- FieldAccess.owner/field ✓（field_idx）。
- Propagate/Unwrap：需 operand 类型（Option vs Result 分支）→ 由补的 ty 字段覆盖。
- comptime 值：CtOut.blocks（span→CValue）+ consts ✓（P3b 已产）。
- FnDecl.sig ✓（TFun.sig）；dictSyms（签名绑定的字典参数符号，按序）——TFun 需补
  `dict_syms: List[Int]`（enter_fn 的 bind_dicts 现已生成，要带出来）。
- 尾递归：Kotlin 判 self-recursive tail call → goto；需要 fn 名+owner 对比即可（TAST 有）。

## 三、切序

1. `__emit`（Kotlin 落盘命令）+ selfhost/dawn.toml ASM 依赖 + emit-diff 脚本骨架。
2. TAST 补注解（上表）+ checker 回填 + P3b 对拍保持绿（golden 不含这些字段，无影响）。
3. codegen 骨架：DawnClassWriter（getCommonSuperClass 覆写——ASM 子类化！Dawn 不能
   subclass Java 类 ⇒ **硬点**：改用 COMPUTE_FRAMES + 预计算共同父类？不可行——
   ClassWriter.getCommonSuperClass 是 protected 虚方法。替代：CheckClassAdapter？
   或改 Kotlin 侧共同改用 COMPUTE_MAXS + 手算 frames？【待定：通读后定方案，
   候选：a) Kotlin 侧引入非子类化的 frame 计算辅助（两侧共用）；b) selfhost 用
   MethodHandles/Proxy 造子类（ClassWriter 非接口，Proxy 不行）；c) 生成期避免
   需要 getCommonSuperClass 的归并（显式 CHECKCAST 统一到公共类）——Kotlin 注释说
   只有 adtSupers 层级需要；d) selfhost 直接带一个手写 Java shim 类
   DawnClassWriter.java 放进 dawn.rt（编译期反射可见）→ 最省事，shim 收
   Map[String,String] supers。倾向 (d)。】
4. 共享运行时类逐个移植（Maps/Lists/Strings/Bytes/Io/Show/Fn/Tuple/Panic/Unit/
   trait 接口/Ord 预置 impl/比较器），每类一测（字节相等）。
5. 模块类：ADT 类、record、Show、fn 方法、<clinit> 常量、main 包装、测试方法。
6. 表达式/语句发射（最大块）：算术/比较/短路/字符串构建/构造/match 链/lambda
   （LambdaMetafactory）/UFCS/Java interop（含 SAM 桥、varargs、List 桥）/尾递归
   goto/`?` 展开/循环。
7. 金样逐步扩大：examples → std → site/playground → selfhost 自身 → backend-dawn。
8. P5：stage1(Kotlin) 编 selfhost → stage2(selfhost 编 selfhost) → stage3
   （stage2 编 selfhost）；stage2 == stage3 字节相等即不动点。selfhost `build` 模式
   （出可运行 jar：Main-Class manifest + 依赖 lib）。

## 四、通读笔记（滚动追加）

- generateProgram：programAdts = prelude + 各单元 types；先 emitShared（一次），
  再逐单元 emitModule。emitShared：prelude ADT 类 + prelude trait 接口 + prelude
  Ord impls + DictComparator/FnComparator + Panic/Unit/Lists/Strings/Bytes/Io/Show/
  Maps + Fn0..8 + Tuple2..8 + emitStd（vendored rt 家族 + std 模块逐个 emitModule）。
- 类名：module → className（loader 清洗）；ADT → a.jvmName；ctor → c.jvmName；
  tuple → dawn/rt/TupleN；fn 接口 → dawn/rt/FnN（apply erased Object）。
- vendored rt：StdStrings/StdBytes/StdIo/DawnList/DawnMap/DawnSet + 嵌套类，从
  编译器 jar 资源拷字节。selfhost 侧同样从 **stage1 编译器 jar**（或 --rt <dir>）
  取这些字节；对拍时两侧同源即可字节等。
- 帧上下文：mv/currentFn/fnStart/nextSlot/methodRet/loopStack/methodRetsNull/
  selfPending/pendingLambdas/pendingSamBridges/pendingBridges(Unit 值桥)/
  pendingBuiltinBridges/pendingCtorBridges/constFields(<clinit>)。
