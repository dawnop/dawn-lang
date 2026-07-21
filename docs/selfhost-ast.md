# 自举 AST 架构：Parsed → Typed 双树（P0.5 草案）

> 这是 [`selfhost-gaps.md`](selfhost-gaps.md) §三「选甲」的兑现草案，属**动码前的
> 定稿**（惯例见 [`bytes-design.md`](bytes-design.md)/[`unwrap-design.md`](unwrap-design.md)）。
> 目标：在写第一行 Dawn 版 lexer **之前**，把「哪一刀产出哪棵树、每个注解落在哪」定死，
> 免得像 Kotlin 版那样把 49 个 `var` 洞散在一棵树上、靠读全代码才知道「`e.type` 在哪刀被填」。
> 具体节点定义会在 P3（parser+checker 两刀）落地时随真代码收敛，此处给架构与骨架。

## 一、结论先行

- **两棵不可变树，`Parsed*` → `Typed*`，checker 是把前者降低成后者的一刀**（rustc 的
  `ast::Expr` → `hir::Expr`、GHC 的 `HsSyn` → Core 同构）。Parsed 是纯语法，Typed 是
  **消歧 + 定型 + 降糖**后的结果。
- **全量分裂两套 hierarchy，不做 "Trees That Grow"**（GHC 那种一棵树带 phase 参数的做法要
  type family / 行多态，Dawn 没有，硬凑只会更脏）。重复是诚实的代价，且换来两处真收益（§二）。
- **Typed 比 Parsed 更小更规整**：Kotlin 版 checker 往节点上写的 44 个 `var`，在 Typed 里
  要么是**必填字段**（`ty: Type`、`symbol: Symbol` 不再是 `Option`），要么让**一个有歧义的
  Parsed 节点分裂成 N 个无歧义的 Typed 节点**（§四）。codegen 从此不再二次决策。

一句话：**Kotlin 版「先建带洞的树、逐刀往洞里写字段」的 44 个可变槽，Dawn 版归零——
洞不存在了，因为 Parsed 节点根本没有那个字段，Typed 节点的字段全是必填的。**

## 二、为什么两棵，而不是一棵带 `Option` 洞

`selfhost-gaps.md` §三已论证不可变性堵死了「建树后写回」。这里补两条**正面**理由，
它们独立于性能（HAMT 落地后性能已不是理由，见 §三复盘）：

1. **分刀由类型系统保证，不靠约定。** Kotlin 版里 `e.type: Type?` 全程可空，「这一刀之后
   一定非空」只是口头约定，`recv.type = TUnit // a namespace, not a value` 那种注释就是欠债的
   利息。Dawn 版 `TExpr` 的 `ty: Type` 非空——**拿到 `TExpr` 就拿到了类型**，拿到 `PExpr`
   就**根本没有** `ty` 可读。误用在编译期即挡下。
2. **消歧一次到位。** Parsed 的一个节点常代表多种可能（`FOO` 是构造器还是常量？`x.f(y)` 是
   UFCS、记录字段调用、还是 Java 方法？），Kotlin 版靠往同一节点挂 `constDecl`/`ctorValue`/
   `desugared`/`javaMethod` 等互斥字段区分，codegen 得挨个判空猜。Typed 把它拆成**互斥的构造器**
   （§四表），codegen `match` 到哪个就是哪个，无判空、无猜。

## 三、四刀与树的对应（一页图）

```
源码 ──Lexer──▶ List[Token] ──Parser──▶ ParsedModule ──Checker──▶ TypedModule ──CodeGen──▶ 字节码
                (无树)                     (纯语法树)     (+诊断)      (定型+消歧+降糖)         (只读 Typed)
```

| 刀 | 吃 | 吐 | 可假设 / 职责 |
|---|---|---|---|
| **Lexer** | `String` | `List[Token]` | 无树。游标已线性化（v0.2.1） |
| **Parser** | `List[Token]` | `ParsedModule` | 只认语法。**不查符号、不知类型**。每个字段 `val`，无「待填」洞 |
| **Checker** | `ParsedModule` | `TypedModule` + 诊断 | 名字解析（产 `Symbol`）、类型检查（产 `Type`）、trait 消解（产 `WitnessRef`）、comptime 求值（产 `CValue`）、降糖（`PMethodCall`→`TCall`/…）。**这一刀是唯一的 Parsed→Typed lowering** |
| **CodeGen** | `TypedModule` | `Map[String, Bytes]` | 只读 Typed。**不再决策**：类型、符号、witness、降糖结果全已固化，`match` 即用 |

> Checker 内部还分**名字解析 → 类型检查/降糖**两趟（符号先于类型），但对外只有一个
> `ParsedModule → TypedModule`。中间的「已解析名字、未定型」状态**不物化成第三棵树**——
> 它活在这一刀的局部（环境 `Map[String, Symbol]` + 递归返回值），不落 AST。

## 四、两棵树的骨架（Dawn，草案）

check 侧的数据结构（`Symbol` / `Type` / `FnSig` / `CtorInfo` / `TraitInfo` / `WitnessRef` /
`CValue`）本身也要用 Dawn 的不可变 record 重写，Typed 树**按引用**指向它们；这里当已存在。

### 4.1 Parsed 树（parser 产出，纯语法）

```
type PExpr =
  | PIntLit(value: Int, span: Span)
  | PFloatLit(value: Float, span: Span)
  | PBoolLit(value: Bool, span: Span)
  | PUnitLit(span: Span)
  | PStrLit(parts: List[PStrPart], span: Span)
  | PVarRef(name: String, span: Span)                      # 只有名字，不知指向谁
  | PCall(callee: String, args: List[PExpr], calleeSpan: Span, span: Span)
  | PApply(target: PExpr, args: List[PExpr], span: Span)
  | PMethodCall(target: PExpr, name: String, args: List[PExpr], nameSpan: Span, span: Span)
  | PCtorCall(ctorName: String, args: List[PCtorArg], spread: Option[PExpr],
              hasParens: Bool, calleeSpan: Span, span: Span)   # 构造器/常量/构造器作值 —— 尚未消歧
  | PFieldAccess(target: PExpr, fieldName: String, fieldSpan: Span, span: Span)
  | PLambda(params: List[PLambdaParam], body: PExpr, span: Span)
  | PListLit(elems: List[PExpr], span: Span)
  | PTupleLit(elems: List[PExpr], span: Span)
  | PBinary(op: BinOp, left: PExpr, right: PExpr, opSpan: Span, span: Span)
  | PUnary(op: UnOp, operand: PExpr, span: Span)
  | PIf(cond: PExpr, then: PBlock, else_: Option[PExpr], span: Span)
  | PMatch(scrutinee: PExpr, arms: List[PMatchArm], span: Span)
  | PIndex(target: PExpr, index: PExpr, span: Span)
  | PPropagate(operand: PExpr, span: Span)
  | PUnwrap(operand: PExpr, span: Span)                    # 尚无 panic 消息
  | PReturn(value: Option[PExpr], span: Span)
  | PComptime(body: PExpr, span: Span)
  | PUnsafePure(body: PExpr, span: Span)
  | PBlock(block: PBlock)
```

不变量：**每个字段 `val`；没有 `ty`、没有 `symbol`、没有 `sig`、没有 `Option[Type]` 占位洞。**
`PStrPart` / `PMatchArm` / `PPattern` / `PStmt` / `PDecl` 同构，此处省略。

### 4.2 Typed 树（checker 产出，定型 + 消歧 + 降糖）

```
type TExpr =
  | TIntLit(value: Int, ty: Type, span: Span)
  | TFloatLit(value: Float, ty: Type, span: Span)
  # … 字面量类推，ty 必填 …
  | TVarRef(symbol: Symbol, ty: Type, span: Span)         # 已绑定到具体 Symbol
  | TFnValue(sig: FnSig, ty: Type, span: Span)            # 顶层 fn 当值：从 PVarRef 分裂出来
  | TCall(target: CallTarget, args: List[TExpr],
          witnesses: List[WitnessRef], ty: Type, span: Span)
  | TApply(target: TExpr, args: List[TExpr], ty: Type, span: Span)
  | TJavaCall(recv: Option[TExpr], method: JavaRef,       # PMethodCall 的 Java 分支
              samConvs: List[SamConv], listBridges: List[Int],
              varargsPack: Option[Int], ty: Type, span: Span)
  | TCtorCall(ctor: CtorInfo, fieldExprs: List[Option[TExpr]],
              spread: Option[TExpr], ty: Type, span: Span)
  | TConstRef(decl: ConstId, value: CValue, ty: Type, span: Span)  # FOO 解成常量
  | TCtorValue(ctor: CtorInfo, ty: Type, span: Span)              # 裸构造器当值
  | TFieldAccess(target: TExpr, owner: CtorInfo, field: FieldInfo, ty: Type, span: Span)
  | TLambda(params: List[TLambdaParam], body: TExpr,
            fnType: Type, captures: List[Symbol], ty: Type, span: Span)
  | TBinary(op: BinOp, left: TExpr, right: TExpr,
            ordWitness: Option[WitnessRef], ty: Type, span: Span)
  | TUnwrap(operand: TExpr, panicMsg: String, ty: Type, span: Span)  # 消息已生成
  | TConst(value: CValue, ty: Type, span: Span)           # PComptime 求值后塌缩成常量
  # … TUnary/TIf/TMatch/TIndex/TPropagate/TReturn/TList/TTuple/TBlock 类推，均带 ty …

type CallTarget =                                          # 把 Kotlin 版 sig/dynamicTarget 的判空拆成和类型
  | StaticFn(sig: FnSig)                                   # 顶层 fn / builtin
  | Dynamic(symbol: Symbol)                                # 局部函数值
```

**没有 `TMethodCall`**——UFCS 的 `x.f(y)` 在 checker 里就降成 `TCall(StaticFn f, [x, y])`，
Java 的降成 `TJavaCall`，记录字段函数的降成 `TApply`。codegen 见不到 `.` 调用。

### 4.3 一个 Parsed 节点 → 多个 Typed 节点（消歧的价值）

| Parsed（歧义） | Kotlin 版靠哪个可空字段区分 | Typed（无歧义构造器） |
|---|---|---|
| `PMethodCall` | `desugared` / `javaMethod` / `javaCtorRef` | `TCall` / `TApply` / `TJavaCall`（三选一，已定） |
| `PCtorCall` | `ctor` vs `constDecl` vs `ctorValue` | `TCtorCall` / `TConstRef` / `TCtorValue` |
| `PVarRef` | `symbol` vs `fnValue` | `TVarRef` / `TFnValue` |
| `PCall` | `sig` vs `dynamicTarget` | `TCall(target: StaticFn \| Dynamic)` |
| `PComptime` | `value`（求值后） | `TConst`（直接是常量，body 已消失） |

## 五、44 个可变槽的去向（覆盖性核对）

穷举 `ast/Ast.kt` 的每个 `var`，证明双树把它们全接住——分五类：

| 类 | Kotlin 版 `var` 槽 | Typed 归宿 |
|---|---|---|
| **符号**（名字解析，9 个） | `VarRef.symbol` `Param.symbol` `LambdaParam.symbol` `BindPat.symbol` `LetStmt.symbol` `LocalFnStmt.symbol` `AssignStmt.symbol` `ForStmt.symbol` `ListPat.restSymbol` | 对应 Typed 节点的**必填 `symbol: Symbol`** |
| **类型**（4 个） | `Expr.type` `CtorPat.fieldTypes` `TuplePat.elemTypes` `ListPat.elemType` | 必填 `ty: Type` / `fieldTypes` / `elemTypes` |
| **签名/解析**（多） | `FnDecl.sig`+`effVars` `TraitMethod.sig` `ConstDecl.constType`+`resolvedAnn` `TraitDecl.info` `ImplDecl.info` `CtorDecl.info` `UseModuleDecl.exports` `Call.sig`+`dynamicTarget`+`witnesses` `CtorCall.ctor`+`fieldExprs` `FieldAccess.owner`+`field` `CtorPat.ctor`+`fieldPats` `VarRef.fnValue` | Typed 节点必填字段，或分裂成 §4.3 的和类型构造器 |
| **降糖**（MethodCall 一族 + 杂项） | `MethodCall.desugared`+`javaMethod`+`javaCtorRef`+`samConvs`+`listBridges`+`varargsPack` `Binary.ordWitness` `Unwrap.panicMsg` `Lambda.fnType`+`captures` `CtorCall.constDecl`+`ctorValue` | 降成 `TCall`/`TApply`/`TJavaCall`；`ordWitness`/`panicMsg`/`fnType`/`captures` 成必填字段；`constDecl`/`ctorValue` 成 `TConstRef`/`TCtorValue` |
| **comptime**（2 个） | `ConstDecl.value` `ComptimeExpr.value` | `TConst.value: CValue`；const 声明携带其 `CValue` |
| **源文本**（1 个） | `AssertStmt.sourceText` | 从源码可得，**Parsed 就携带**（`PAssertStmt.sourceText`），非 checker 产物 |

全部 44 槽有主，无遗漏。

## 六、代价与不做的（记录在案）

- **重复两套节点定义**：约 30 个 expr/pattern/stmt 各写 Parsed 与 Typed 两份。这是选甲的
  已知代价（§三理由三），rustc/GHC 都付。缓解：Typed 因消歧+降糖**更小更规整**，不是机械复制；
  `Span`/`BinOp`/`UnOp` 等纯语法枚举两树共享，不重复。
- **不做 Trees That Grow / phase 参数化单树**：Dawn 无 type family / 行多态，表达不了「同一
  构造器在不同 phase 有不同字段」。硬用 `Option` 凑等于退回 Kotlin 版的洞。
- **不物化「已解析未定型」第三棵树**：名字解析与类型检查在 checker 内分趟，但中间态留在局部，
  不落 AST（否则三套定义，得不偿失）。
- **`Symbol`/`Type`/`FnSig` 等仍是 check 侧独立 record**，两棵树都按引用指向；它们的不可变化
  是 checker 一刀自己的事，不属本文。
- **分配量**：Typed 是新树，AST 节点数量级的额外分配——与 **B1 序 6**（值类型特化）相干。
  按 `seq6-research.md` 的教训**不预判**，等 P1 试水刀的实测（见 [`selfhost-gaps.md`](selfhost-gaps.md) §三）。

## 七、下一步

P0.5 到此为架构定稿。按 [`selfhost-gaps.md`](selfhost-gaps.md) §七，接着是 **P1 第一刀 Lexer
（试水）**——它不产 AST、不依赖本文，正好独立验证 Dawn 写编译器的工效，并用它撞出的摩擦
回头修订本文的节点细节与 B 类优先级。Parsed/Typed 的完整节点表在 **P3**（parser+checker）
随真代码收敛。
