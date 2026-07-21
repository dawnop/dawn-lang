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

## 六、已知硬点（提前记录）

- **诊断顺序**必须与 Kotlin 完全一致——检查顺序（声明序、两遍序、表达式遍历序）
  要逐处对齐，这是对拍最可能反复的地方（P1 的"失败位置"教训的 checker 版）。
- Suggest（"did you mean"）的编辑距离与候选排序要逐字节一致（`diag/Suggest.kt` 51 行，照抄）。
- comptime 求值结果进 golden（const 值），浮点/整数渲染已在 P1/P3a 验证一致。
- 单文件 vs 项目模式的行为差（P0.7 的 unknown-std-module 报错位置）要按 Kotlin 现状复刻。
