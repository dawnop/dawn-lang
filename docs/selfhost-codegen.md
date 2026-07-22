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

### 通读进度 500–1250

- emitModule：own ADT 类 → trait 接口 → impl 单例类 → derive Ord 的 impl 类 →
  模块类（ARGS_FIELD 静态字段 [Ljava/lang/String;）→ 每 fn genFn+drainLambdas →
  impl 方法（implMethodName 静态）→ trait 默认体（defaultMethodName 静态）→
  derive Ord cmp 静态 → tests（dawn$test$i）→ 有 main 则 genJvmMain → constFields。
- TupleN：public final Object _i 字段、ctor、结构 equals（IF_ACMPEQ 快路 + INSTANCEOF
  + 逐字段 Object.equals）、hashCode 31 链、toString 经 Show.show。FnN 接口：
  ClassWriter(0)（不是 COMPUTE_FRAMES！）、apply erased。
- descOf：Int/Cursor=J Float=D Bool=Z String Bytes="[B" Unit/Never/Error=V TVar=Object
  TAdt=jvmName TList/TMap/TSet=java.util 接口 TTuple=TupleN TJava=internalName TFn=FnN。
- slotsOf: J/D=2, Z=1, V=0, ref=1。box/unerase/adaptTo(declared TVar→box)/adaptFrom。
- boxedDescOf + instantiatedType（LMF 用 AsmType.getMethodType）。
- trIface=dawn/tr/<owner$…$>Name；implClass=dawn/impl/<owner$>Trait$Subject；
  implMethodName=dawn$impl$Trait$Subject$m（静态落声明模块类）；
  defaultMethodName=dawn$default$Trait$m；fnDescWithDicts=声明参数+每约束一个 Object。
- ADT 类：record=单 final 类基 Object；sum=abstract 基类(PROTECTED <init>) + 每 ctor
  final 子类；无字段 ctor = singleton INSTANCE + <clinit>；ctor 类含字段 public final、
  <init> PUTFIELD 链、equals/hashCode/toString（derive Show 才有 toString? —— 待核：
  genCtorClass 里 toString 是否受 derivesShow 门控）。
- genFn：mv 上下文 + Symbol.slot 顺序分配（声明参数先、dictSyms 后）；fnStart Label
  （尾递归 goto 目标）；genExpr(body, tail=true) 返回 falls（是否顺落）→ emitMethodReturn。
  **Symbol.slot 是 checker Symbol 上的可变槽 → 端口在 codegen 里自建 Map[sym id → slot]。**
- 单例脚手架 singletonScaffold；impl 字典类:各 trait 方法 erased → unerase 参数 →
  INVOKESTATIC 具体静态 → ret TVar 则 box;derived Ord → 调 derivedCmp;缺省 → 调
  default 静态 + ALOAD 0 作字典。prelude Ord: cmp = unerase + emitNativeCmp
  (LCMP / Double.compare / String.compareTo, I2L)。
- genDerivedOrdCmp：record 逐字段;sum 先 tag 序（INSTANCEOF 链算 tag）再同 ctor
  逐字段;emitFieldCmp 标量原生、TAdt 经其 ordImpl 的 cmp 静态。
- genTraitDefault：currentFn=null（自调用不做尾递归改写）。

### 通读进度 1250–2660 + TAST v2 方案定稿

- genTest/genJvmMain（try/catch PanicError→stderr+exit1，visitTryCatchBlock 有 String
  type 参数——shim 不需要 null）；Lists/Strings 等运行时类照抄即可。
- genStmt：LetStmt 要 init.type + **isDiscard（name=="_"）**——TSLet.sym 应为 None
  表示丢弃（现端口总是 Some，需改 check_stmt）；ExprStmt 弹栈按 expr.type；
  while/for 用 loopStack (cont,end)，for 的增量段 reachable = bodyFalls || hasJumps ✓
  （TSWhile/TSFor 的 has_jumps 语义与 Kotlin s.hasJumps 完全一致，值必须一样——
  Kotlin hasJumps 是 checker 填的？【待核对：Kotlin ForStmt.hasJumps 谁填、含义
  （any break/continue targeting THIS loop）——与 loop_jumps 集合语义对齐】）。
- genExpr 返回 falls；Break/Continue → GOTO loopStack；Return → adaptTo(v.type,
  methodRet)；ComptimeExpr → genLoadConst(e.value, e.type, key=节点)（标量 LDC、
  结构→静态字段 dawn$const$i + <clinit> constructValue，VAdt 字段 boxed=字段类型是
  TVar）；Index 按 target.type List/Map 分派+unerase(e.type)；FieldAccess GETFIELD
  + adaptFrom(field.type, e.type)。
- **TAST v2 注解定稿**（checker 回填）：
  1. 每个 TExpr 变体加末位 `ty: Ty` 字段（构造处 = check 返回的类型）。
  2. TSLet.sym: None ⟺ `_`。
  3. XBinary 换 `ord: Option[WitRef]`；XCallFn 换 `witnesses: List[WitRef]`；
     `WitRef = WForward(sym: Int) | WConcrete(trait_id: Int, subject: Ty)`。
  4. TJavaCall 加 `sam_convs: List[(Int, String, JMethod)]`（argIdx, ifaceCls, sam）、
     `list_bridges: List[Int]`；XLambda 加 `fn_ty: Ty`。
  5. TFun 加 `dict_syms: List[Int]`（enter_fn 的 bind_dicts 顺序）。
  6. trait 方法调用：Kotlin genCall 分派 sig.trait != null → genTraitMethodCall
     （字典虚调用）——XCallFn 需带 `trait_id: Option[Int]`（取自 Sig）✓ Sig 已有。
  7. UFCS/module 调用已在 TAST 展开为 XCallFn/XApply/XJava ✓ 无需 desugared 引用。
- 这些字段进 TAST 不进 __check 金样 → P3b 对拍不受影响（对拍只看 diags/签名/常量）。

## 五、进度账(随做随记)

- ✅ P4-1 `dawn __emit <target> -o <dir>`（Kotlin 落盘金样，确定性已验）+
  dawn.tool.AdtClassWriter shim（getCommonSuperClass 共用；Kotlin CodeGen 已改用）。
- ✅ P4-2 TAST v2：全节点 ty（tex_ty 访问器）、WitRef（XCallFn.witnesses/trait_id、
  XBinary.ord）、TJavaCall.sam_convs/list_bridges、TFun.dict_syms（bind 序）、
  TModule.syms、TSLet.sym=None 表 `_` 丢弃。__check 金样 337 文件仍逐字节一致。
- ✅ P4-3 selfhost/dawn.toml 钉 asm 9.7.1（本地要 DAWN_MAVEN_MIRROR）；codegen.dawn
  骨架：desc_of/method_desc/slots_of/is_ref + ASM 互操作 spike。shim 加 List
  版 ctor（"child super" 对）与 plain/beginOn/fieldOn/methodOn 静态（Dawn 传不了
  null、Map 不过界）。
- ✅ P4-4 第一批发射器字节级一致：Fn0..8、Tuple2..8、PanicError、Unit（18/65 类，
  scripts/selfhost-emit-diff.sh 子集模式，`selfhost emitrt -o dir`；运行 selfhost
  要把 compiler/build/libs/dawn.jar 挂 classpath——AdtClassWriter 在编译器 jar 里）。
- ✅ P4-5 Bytes/Io/DictComparator/FnComparator/dawn/tr/Ord/prelude Ord impls
  字节级一致（26/65）。Kotlin genBytesClass/genIoClass 的 doc 注释是旧的——实际
  只有 concat 和 javaTry/catchPanic，以字节对拍为准。
- ✅ P4-6 Show/Lists/Strings/Maps + vendored rt 字节拷贝（vendor.dawn：从
  classpath 上的编译器 jar 枚举 dawn/rt/<outer>[$*].class，JarFile+Enumeration
  互操作）→ 42/65。Dawn 字面量没有 \r 转义，用 str.from_char(13)。
- ✅ P4-7 ADT 类发射（gen_adt/gen_ctor_class + equals/hashCode/toString；
  toString 无条件生成、checker 才是 Show 门控；genToStringMethod 的装箱只对
  TyInt/TyFloat/TyBool，TyCursor 走 else）→ prelude Option/Result 48/65。
- ✅ P4-8 emitrt 接受 target：load_std + analyze_program 后按 owner==class_name
  发射用户 ADT（calc$Token 家族、calc$Parser record）→ 57/65。supers 表用全
  程序 adts 的并集。
- ✅ P4-9 **全套 genFn/genExpr 落地（emit.dawn，~3600 行）+ P5 不动点达成**：
  - 语料全部逐字节一致：examples 全部（含 traits/derive Ord）、site（99 类）、
    playground（91 类）→ `scripts/selfhost-emit-diff.sh` 严格模式，进 CI。
  - **selfhost 自举**：`selfhost emit selfhost` 432 类与 Kotlin 逐字节一致
    （stage2==stage1），再用自己发射的类跑一遍仍逐字节一致（stage3==stage2）
    → `scripts/selfhost-fixpoint.sh`，进 CI。**Dawn 编译器已自举。**
  - 途中补的 TAST 缺口：XCallBuiltin 加 witnesses（sort/max/min 的 Ord 字典）、
    TJavaCall/JMethod 加 decl_cls（invoke owner 得用声明类不是接收者类）、
    TFun 加 impl_of/default_of、StdCtx 加 mods（每个 std 模块的 Cx/TModule/CtOut）。
  - 跨模块常量：XConstRef 只带名字，值在声明模块的 CtOut 里——main.dawn 的
    merged_consts 按 cx.imported_names（名字→声明模块）路由。
  - vendor.dawn 支持 file: 协议（stage3 用类目录跑，资源不在 jar 里）。
  - Dawn 侧 ldc 注意：visitLdcInsn 传 Dawn Int 会装箱成 Long（长整型常量，对）；
    要发 int 常量必须 Integer.valueOf（push_int/ldc_jint），否则 LDC 类型错。
  原方案备忘（已全部落实）：
  1. TFun 加 `impl_of: Option[(Int, Ty)]`、`default_of: Option[Int]`（4 个构造点
     全传 None，check_module §5.75 调用点用 `..tf` 改写；pass_register_impls 需
     多返回按 module_impls 序的 (trait_id, subject) 以拿到 subject）。发射名:
     impl → dawn$impl$<Trait>$<Subject>$<m>，default → dawn$default$<Trait>$<m>。
  2. StdCtx 加 `mods: List[(String, Cx, TModule, CtOut)]`（load_std 已 check 了每
     个 std 模块，只是丢了 per-module 三元组；std 的 className = mod_path 即
     "std/str"，'/'→'$' 只在方法名 mangle 时做）。
  3. 新模块 selfhost/src/emit.dawn：Gen 记录线程化 Kotlin 的可变字段
     {mv, class_name, adts, traits, impl_table, fn_sigs, syms, slots: Map[Int,Int],
     next_slot, method_ret, rets_null, fn_start: Option[Label], self_pending,
     loop_stack, lambda_ctr, sam_ctr, pending_*(队列), const_fields, cur_fn,
     consts/blocks(CtOut)}。gen_expr(g, e, tail) -> (Gen, Bool)（falls）。
  4. 调用点声明签名查找：XCallFn.owner None → 本模块 cx.fns；Some(cls) → 程序级
     (class_name, name)→Sig 表（从各 CheckedMod.cx.fns + std exports 建）。
     trait 方法 provided 的具体签名 = trait MethodSig 的 tvar→subject 代换。
     witnesses: WConcrete(tid, subject) → impl_table 查 ImplI（owner/derived）。
  5. 关键 Kotlin 细节别忘：LMF_BSM Handle；lambda impl 是 dawn$lambda$N（计数器
     per-module）；Unit 返回 fn 值要 dawn$fnval$ 桥（LMF 不适配 void）；builtin
     值桥 dawn$bi$<name>（直连表：get/range/sort_by/join/parse_int/parse_float/
     java_try/catch_panic）；ctor 值桥 dawn$ctor$<jvm 名 '/'→'$'>；SAM 桥
     dawn$sam$N；genConstFields 的字段名 dawn$const$N 按首用序、key=const 名或
     comptime 块 (lo,hi)；ARGS_FIELD="dawn$args"；genJvmMain 仅当有 main；
     __emit 是 includeTests=true（std 模块不含 tests）；除零 panic 检查；
     shift 先 L2I；assert 的 == 解构只对 Int/Float/Bool/String。
  6. 发射序（进 class 的方法序影响字节）：module.fns（每个后 drainLambdas：
     lambdas→fnval 桥→builtin 桥→ctor 桥→sam 桥的 while 序）→ impl 方法 →
     trait defaults → derived Ord cmp 静态 → tests → jvm main → const 字段+clinit。
     selfhost 的 tm.fns 已是 fns++impl++defaults 序，靠 impl_of/default_of 区分。
- ✅ `selfhost emit <target> -o <dir>` 全流程 + emit-diff 严格模式 + CI（上条）。
- ✅ P5 不动点：stage2==stage3（`scripts/selfhost-fixpoint.sh`，CI）。
- ✅ `selfhost build <t> -o out.jar [--vendor <pkg>]…`：可执行 jar（jarw.dawn，
  确定性——manifest 在先、时间戳钉死，同类表必出同字节）。`--vendor` 用
  vendor.classpath_package 从 java.class.path 按包前缀拷类（首个命中的
  class-path 条目赢，同类加载器语义）；打 selfhost 自身时 vendor 进
  dawn/tool（AdtClassWriter shim）+ org/objectweb/asm，产物单独可跑。
  验收 `scripts/selfhost-standalone.sh`（CI）：独立性（只挂 standalone jar
  重发射 calc 逐字节一致）+ 闭包（standalone jar 重建自身逐字节一致）。
