# P3b：Checker 移植设计（Dawn 版类型检查器）

> P3a（Parser）已完成：`selfhost/src/parser.dawn`，全语料对拍逐字节一致。
> 本文件是 Checker 半刀（`check/*.kt` ≈ 5,100 行）的移植决定，按 [`selfhost-ast.md`](selfhost-ast.md)
> 选甲：checker 是 lowering 一刀，消费 `ast.dawn` 的纯解析树。**动码前先出草案**（序 4/5 先例）。

## 一、验收

金标准 `dawn __check <target>`（Kotlin 侧新增）：对每个语料目标跑完整 analyze
（含 comptime），dump（1）全部诊断（消息+span+hint+severity，`!`/`w` 行格式）、
（2）每个顶层 fn 的 resolved signature（`FnSig.render()`）、（3）每个 const 的求值结果。
`scripts/selfhost-check-diff.sh` 双跑逐字节比。单文件目标用单文件 analyze 语义，
项目目录用 analyzeProject 语义（backend-dawn、site、selfhost 自身都是项目语料）。

## 二、Kotlin 依赖身份语义 → Dawn 的 id+表

Kotlin 检查器的核心对象全是**身份相等 + 可变 + 循环引用**，Dawn 不可变记录三样都没有：

| Kotlin | 问题 | Dawn 表示 |
|---|---|---|
| `Type.TVar`（identity equality） | 同名不同签名的 T 必须不等 | `TyVar(name, id)`，id 从 checker 状态里的计数器分配，相等按 id |
| `Eff.Var`（identity，"one instance per name per signature"） | 同上 | `EffVar(name, id)`；`EUnion` 存按 id 排序的 var 列表（结构相等 = Kotlin 的集合相等） |
| `AdtInfo` ↔ `CtorInfo.adt` 循环引用 | 不可变记录无法成环 | ADT 表：`Map[Int, AdtInfo]`（id → info），`CtorInfo.adt_id: Int`；`Ty.TyAdt(adt_id, args)`。渲染/取构造器都过表 |
| `AdtInfo.ctors` 两遍填充（先壳后字段，递归类型） | 可变追加 | 两遍构建：第一遍注册壳（id+名+tparams），第二遍生成带字段的完整 info 覆盖表项 |
| `AliasInfo.resolved/resolving` 缓存+循环检测 | 可变槽 | alias 表 `Map[String, AliasEntry]`，resolving 集合线程传递 |
| `Type.TJava(fqcn, cls: Class<*>)` | ADT 字段装 Class 对象 | `TyJava(fqcn)` 只存名字；反射统一走 `jreflect.dawn` 帮助层，按 fqcn 现查（JVM 自身缓存 Class，无需自建缓存正确性也够） |
| `FnSig.owner/srcPath/trait/dictSyms` 事后可变填充 | 可变槽 | 构建 FnSig 时一次性给全（checker 内部分阶段用中间记录） |
| AST 节点上的 `e.type = t` 等 44 个槽 | 写回节点 | 选甲：checker 产出 `Typed*` 新树（`tast.dawn`），节点自带类型/解析结果 |

**显示字符串**：Kotlin 在构造器里急切拼 display；Dawn 改为 `ty_show(adts, t)` 按需渲染
（TyAdt 需查表取名）。诊断文本必须逐字节一致，渲染规则照抄（`Map[K, V]`、
`fn(A) -> B !e`、`(A, B)`、Java 简名截取）。

## 三、状态线程

Checker 的可变成员（sink、scopes `ArrayDeque<HashMap>`、fresh 计数、当前效果上下文…）
统一进一个 `Cx` 记录线程传递，写法沿 P3a 的 `St` 惯例：

```
type Cx = { diags: List[Diag], next_id: Int, scopes: List[Map[String, Symbol]], ... }
alias CR[T] = (Cx, T)          # checker 不中止：错误 = 记诊断 + TyError 继续
```

与 parser 不同：**checker 没有异常控制流**（错误产出 `TyError` 毒化继续），
所以不需要 Result——一律 `(Cx, T)` 元组返回。作用域栈是形状 A（小、随即丢弃），
HAMT Map 性能无虞（selfhost-gaps §二）。

## 四、Java 互操作反射

Kotlin 用 `Class.forName` / `getMethods` / SAM 检测 / 变参匹配（spec §9 整章）。
Dawn 侧集中到 `selfhost/src/jreflect.dawn`：

- `use java "java.lang.Class"` 等 + `Class.forName(fqcn)`；数组返回值
  （`getMethods()` 等）用 `java.lang.reflect.Array.get/getLength` 遍历
  （spec §9.5 数组不可索引的既定绕法）。
- 反射查询包装成纯数据返回（方法名/参数类型名/静态与否/…的记录列表），
  checker 主体只吃数据不碰 Java 对象——把 unsafe_pure 面积压到一个文件里。

## 五、切序（每步可测，最后过全语料金标准）

1. `types.dawn`：Ty/Eff/subst/lub/render + 单测（本文件 §二的表示落地）。
2. `tast.dawn`：Typed 树节点（随 3–6 增量补齐）。
3. 声明收集：ADT 两遍构建、alias、const/fn 签名、trait/impl 注册、use 处理
   （std 导出表要么由 Dawn 检查 std 源自举生成，要么先从 Kotlin dump 引导——决定：
   **自举生成**，std 就是普通 Dawn 源，检查它正是检查器的第一份真语料）。
4. 表达式/语句/模式检查 + 效果推断 + 泛型实例化 + 键类型检查（P0.7 语义）。
5. Exhaustive（193 行，独立小刀）；trait witness 解析（Traits.kt 86 行）。
6. Comptime 解释器（751 行；B5 的 TCO 之忧在此实测）。
7. `__check` 金标准 + 全语料 diff 进 CI。

## 五点五、通读 Checker.kt 后的移植笔记（2026-07-22，全文已读）

**P3b 产出 TAST（改判，2026-07-22 通读 Comptime.kt 后）**：解释器重度消费 checker
注解（e.sig/e.symbol/e.desugared/e.ctor/e.fieldExprs/p.fieldPats/e.captures…），
重解析方案的重复与发散风险高于建树成本——**checker 即刻产出 Typed 树**（选甲第二棵，
`tast.dawn`），comptime 与 P4 codegen 共同消费。Symbol 发唯一 Int id，comptime env =
`Map[Int, CValue]`。TExpr 节点形态跟随消费者需要增量收敛（先覆盖 Comptime 所需的槽）。

**Cx 状态记录**（Kotlin Checker 的全部可变成员，`(Cx, Ty)` 线程传递，无异常控制流）：
diags、next_id（TyVar/EffVar/adt/trait 计数）、fns/adts_by_name/aliases/ctors_by_name、
traits_by_name/local_traits/local_impls、impl_table `Map[(Int, Ty), ImplI]`（Ty 可作键：
全 ADT 无 Float/Bytes 字段）、module_aliases/imported_names、consts(有序)/all_const_names/
const_cutoff、java_classes（简名→fqcn）、scopes `List[Map[String, Sym]]`、
used_effects `List[Eff]`+eff_witness `Map[Eff, (Int, Int, String)]`（Eff 可作键）、
current_eff_vars `Map[String, Eff]`、lambda_stack `List[{boundary, expected_ret, captures}]`
（captures 更新 = 改写栈元素）、loop_stack `List[(Int, Int)]`（loop 标识用序号，
hasJumps 写回改为 jump 集合：记 loop 节点 span 或索引，P4 供 codegen 查）、
current_tparams `Map[String, Ty]`、current_fn_sig `Option[Sig]`、
dict_syms `Map[(Int, Int), Sym]`（tvar_id×trait_id）、in_test、reported_key_types `Set[String]`、
is_std_module。Symbol 身份=结构相等可行（同一声明位置 span 唯一）。

**check() 的遍序**（诊断顺序的骨架，必须逐字节复刻）：
prelude → java uses → processImports → 类型壳（冲突/derive 检查）→ 构造器字段类型 →
alias 全解析 → derive Show 字段检查 → registerTraits → registerImpls（derive Ord 先行 →
本模块 impls：subject 规则/orphan/coherence/方法匹配 → derive Ord 字段检查）→
fn 签名（重名/遮蔽规则：本地覆盖 std/builtin 合法）→ 常量声明（类型+serializable）→
main 检查 → 推断函数按调用依赖序 checkFnInferred（nameRefs 过近似 + 循环报错）→
const 初始化器按声明序（checkComptimeBody：纯度检查）→ 其余 fn → impl 方法体 →
trait 默认体 → test 块。

**表达式层要点**：checkExpr=inferExpr（P3b 不写回 e.type）；needsExpected 两轮参数检查
（含 argTypes 数组与 done 标志）；unifyInto/unifyEff（Var 累积 lub；Union 只查 subsumes）；
checkCall 的 witness 解析（Concrete/Forward + lambda 捕获字典）；checkFnValue/checkCtorValue
的期望型实例化；checkJavaCall 两相重载决议（Fit(phase, score)，vararg 打包在 phase 0）+
SAM 延迟实参 + List 桥接 + mapJavaReturn（引用包 Option、String→Option[String]、
byte[]→Option[Bytes]、char 报错）；checkUnsafePure 的效果隔离（掩 io、拒效果变量、
拒冗余）；`!` 的 panicMsg 在 checker 生成（"unwrapped None from X at path:line"，
需 line 表 = SourceFile.lineOf）；checkMatch 接 Exhaustive（useful/SPat）；
checkBinary/checkIf/checkBlock/checkStmt 按源逐条。

**jreflect.dawn 所需反射面**：Class.forName(名, false, loader→省略)、getMethods/
getConstructors（数组走 reflect.Array.get/getLength）、isSynthetic/isBridge/isVarArgs/
isInterface/isPrimitive/isArray/componentType/canonicalName、Modifier.isStatic/isAbstract、
isAssignableFrom、getParameterTypes/getReturnType、Object 方法剔除（getMethod 探测）、
方法/构造器 toString（错误信息里逐字打印 candidates）。resolveJavaClass 的嵌套类
`.`→`$` 回退循环照抄。

## 五点七五、Comptime/StdLib/Loader/Analyze 通读笔记（全部源码已读毕）

- **Comptime 控制流**：Kotlin 用异常（EarlyReturn/Break/Continue/DawnError）——Dawn 版
  `alias ER = Result[(ESt, CValue), (ESt, Ctl)]`，`Ctl = CErr(Diag) | CReturn(CValue) |
  CBreak | CContinue`，`?` 即 throw；callFn/applyFn 捕 CReturn，循环捕 CBreak/CContinue。
  ESt = { fuel: Int, depth: Int }（burn/burnN/MAX_CALL_DEPTH=100_000 照抄）。
- **comptime 内建子集**（callBuiltin 白名单）：panic/todo/expect/unwrap_or/to_float/
  to_int/to_string/len/get/range/sort_by/chars/join/split/cursor 家族(经 StdStrings，
  Dawn 版 use java "dawn.rt.StdStrings" 同源调用)/parse_int/parse_float；其余报
  "not available at comptime"。VAdt 相等按 ctor 同一性 → (adt id, ctor idx)。
  Float == 用原生 `==`（NaN != NaN，DCMPL 语义——注意与 Dawn 源码层 == 的全序不同，
  解释器里要走 Java 语义：经 unsafe_pure { Double 比较 } 或存 bits 比对，落地时验证）。
- **Route C**（unsafe_pure 折叠 Java 调用）：只允许静态方法、Int/Float/Bool/String 边界；
  Dawn 版经 jreflect 的 Method.invoke（Object[] 用 reflect.Array 组装）。
- **栈深**：Kotlin 给解释器 64MB 独立线程；Dawn 版不开线程，改由脚本给 selfhost JVM
  `-Xss512m`（记入 diff 脚本与 CI）。
- **StdLib**：names 按 modules.txt 依赖序；每模块 lex+parse+check（ImportEnv=已查 std，
  无 stdFns 保持自举无环）+ evalComptime；坏 std = 直接 panic。PRELUDE={println,print,
  map,filter,fold}；INTERNAL_BUILTINS/MOVED 表照抄。selfhost 读 std 源：CLI `--std <dir>`
  （默认 compiler/src/main/resources/std），P5 再考虑打包内嵌。
- **ModuleLoader**：目录模式 root=<dir>/src 全量收文件（排序 by path）；文件模式沿 use
  闭包；SEGMENT 正则 `^[a-z_][a-z0-9_]*$`；std/ 磁盘保留报错；重复 use 检测；DFS 拓扑
  + 首个环报错（cycleReported 单发）。modPath=相对路径去 .dawn；className=段清洗
  （非字母数字→_，数字开头前缀 m_）。
- **Analyze**：analyze()（单文件）与 analyzeProgram()（依赖序逐模块，exports 滚动累积，
  parse 失败跳过 check）；exportsOf 的 pub 面（含 trait 方法并入 fns）；hasErrors 只数
  ERROR。__check 的 dump 按此层组织：每目标 = 诊断行 + pub fn 签名渲染行 + const 值行。

## 六、已知硬点（提前记录）

- **诊断顺序**必须与 Kotlin 完全一致——检查顺序（声明序、两遍序、表达式遍历序）
  要逐处对齐，这是对拍最可能反复的地方（P1 的"失败位置"教训的 checker 版）。
- Suggest（"did you mean"）的编辑距离与候选排序要逐字节一致（`diag/Suggest.kt` 51 行，照抄）。
- comptime 求值结果进 golden（const 值），浮点/整数渲染已在 P1/P3a 验证一致。
- 单文件 vs 项目模式的行为差（P0.7 的 unknown-std-module 报错位置）要按 Kotlin 现状复刻。

## 七、落地记录（2026-07-22，P3b 完成）

`selfhost check` 与 `dawn __check` 在全语料（repo 337 文件，含 backend-dawn 1.35 万行）
金标准逐字节一致，`scripts/selfhost-check-diff.sh` 入 CI。与预案的偏差与实测教训：

- **ER 带 env**：`ER = Result[(ESt, Env, CValue), (ESt, Env, Ctl)]`——赋值/绑定要跨过
  break/continue 存活，Err 侧必须携带 env（预案里只有 (ESt, Ctl)）。
- **模块文件改名 interp.dawn**：`comptime` 是关键字，`use comptime` 不可写。
- **两处 id 冲突**（Kotlin 用对象同一性，端口用 id+表的代价）：用户 ADT id 曾从 1 起
  与 RESULT_ID=1 相撞（首个用户类型覆写 Result）；跨模块各自从 2 起，嫁接来的 id 又被
  本地新类型覆写（playground 全线炸）。修法：cx_new 从 2 起 + id 计数器经 StdCtx.next_id
  从 std 一路串到每个用户模块。
- **导入的 alias 带解析结果**：`use types.{Adts}` 的目标 `Map[Int, AdtI]` 在导入方
  无从解析（AdtI 未导入）——ModExports 增 `alias_resolved`，inject_selective 连
  解析类型一起搬（Kotlin 靠 AliasInfo 对象自带缓存，端口必须显式携带）。
- **反射顺序不确定**：getMethods() 顺序跨进程会变，重载候选列表两次运行都不一致。
  两侧一并改为按 Method.toString() 排序后再去重/评分（顺带修了 Kotlin 侧本身的
  不确定性，两个 golden .err 随之再生成）。
- **consts 的 resolvedAnn**：常量类型不可序列化被毒化成 TError 后，初始化器仍按
  原注解检查（Kotlin resolvedAnn 与 constType 分开存，端口曾只存了毒化后的）。
- **route C 的调用**：Dawn 无 null，Method.invoke(null, ...) 写不出——改走
  MethodHandles.publicLookup().unreflect + invokeWithArguments(List)（List 桥直送），
  装箱经 Objects.requireNonNull 擦成 Object。
- **栈**：解释器在宿主栈上递归（ceval 帧很大），diff 脚本与 CI 给 selfhost JVM
  `-Xss512m`；fuel 测试用循环而非深递归。
- 单测 110 个全绿；`dawn test` 侧曾见"FAIL 无详情"= 空 message 的 StackOverflowError。
