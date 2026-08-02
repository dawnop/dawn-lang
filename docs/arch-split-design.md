# 拆 God module —— checker 的 `Cx` 与后端的 `Gen`

> 状态：proposed（任务 #88，`docs/codebase-audit.md` 的 **ARCH-01 + ARCH-02**）。
> 四条前提由用户定案，见 §0，本文不再讨论；D1–D18 是本文的裁决，可推翻。
>
> 勘察基线 **4ae6b61**，文中 file:line 与实测输出均对该提交，已逐条复核——两份勘察
> 备忘录给的三个关键数字被本文的复测推翻（§1.2），本文用的是复测后的。
> 前置阅读：[audit/lowered-ir-design.md](audit/lowered-ir-design.md) §3.2/§五
> （本文**取代**它的 `Cx`/`Gen` 拆分方案，并回答它留下的验收条）、
> [bootstrap.md](bootstrap.md)（种子纪律与 prev-diff 的角色）、
> [core-move2-design.md](core-move2-design.md)（Core IR 的结账盘点，本文的前置条件）。
> 落地后回填 §7 与 §8 的文档校正清单。

## 0. 前提（已定，不再讨论）

| # | 前提 | 出处 |
|---|---|---|
| P1 | **拆文件与拆状态两件都做，一个批次多刀**；「一批」不是一个提交，**每刀必须能被单独证明** | 用户裁决 |
| P2 | **诊断语料先行**（刀 0，分支 `arch/checker-diag-corpus`），本文把它当作已存在的门禁 | 用户裁决 |
| P3 | **v0.47.0 发布 + 推种子**（把 `1b8ee7f` 的 `Emit-Change(emit *)` 移出比对窗口）是本批的**开工前提**；没完成就不开工，理由见 §5.3 | 用户裁决 |
| P4 | 主证明 = 编译固定语料 → 逐字节 diff `__emit -o` 出来的 **class 目录**（**不要 diff jar**，jar 里有时间戳） | 用户裁决 |
| P5 | `selfhost-core-diff.sh` 的 `selfhost.sha` **降级**为「爆炸半径的界限」：每刀之后 `changed` 列表必须**恰好等于**该刀声明要碰的模块集 | 用户裁决 |
| P6 | **#122（`stdlib.dawn:174` 的 `nid = 2`）不进这批** | 用户裁决 |
| P7 | error-model **C2 / `LProtect` 与本批无关**（2026-07-31 关档「不做」，`bracket` 已以运行时 intrinsic 落地）；`docs/audit/README.md:68,72,150` 的过期条目**本批同批修** | 用户裁决 |

关于 P3，本文有一条**加强**而不是推翻的补充：本批**预期声明零条 `Emit-Change`**（§5.3），
所以在 v0.47.0 之后，prev-diff 里出现的任何一条 `NOTE` 都是事故信号；而在通配声明还
活着的窗口里，`NOTE` 是默认值——信号被基线淹掉了。这正是 P3 必须先做的原因。

## 1. 现状：真实盘子，与三个被推翻的数字

### 1.1 真实盘子（本文复测，4ae6b61）

```
selfhost/src/checker.dawn    11,308 行   Cx  47 字段 @ :91-164
selfhost/src/codegen.dawn     3,425 行   （无 Gen，一个字段都不碰）
selfhost/src/emit.dawn        2,534 行   Gen 21 字段 @ :92-128
selfhost/src/emitc.dawn       1,661 行   CSt 6 字段（C 后端，已经是目标形状）
selfhost/src/rc.dawn          1,868 行   C 专属，与本批零交集
selfhost/src/jvmops.dawn        137 行   115 个 const，零函数（07-30 的模板刀）
```

`class_table.dawn`(2,089) 与 `case_table.dawn`(1,384) **不是后端模块**，是
`scripts/unicode-contract/probe.dawn` 生成的 Unicode 数据表（文件头写着
「GENERATED -- do not edit」），两个后端都读。把它们算进 ARCH-02 的盘子是口径错误。

**ARCH-02 的真实盘子 = `codegen.dawn` 3,425 + `emit.dawn` 2,534 = 5,959 行，
其中 `codegen.dawn` 那 3,425 行（占盘子 57%）连一处 `Gen` 引用都没有**
（`grep -cE '\bg\.' codegen.dawn` = 0；唯一的 `Gen` 命中是一句提到 `CodeGen.kt` 的注释）。
A1 从中搬走 2,680 行（占该文件 78%），剩下的也不含 `Gen`——所以后端第一刀是搬叶子，
不是给 `Gen` 分层（§2.2）。

### 1.2 被复测推翻的三个数字

| 来源 | 声称 | 复测 |
|---|---|---|
| ARCH-01 勘察备忘录 事实 3 | 拆分须声明 `Emit-Change(emit selfhost)` | **不须**。它把「刀前 vs 刀后」当成了 prev-diff。prev-diff 是**同一份源码、两个编译器**（`selfhost-prev-diff.sh:62-63`），模块拆分在两侧同时出现，差不了。ARCH-02 备忘录 F1 已在真实拆分上实测 prev-diff 全绿 |
| ARCH-02 勘察备忘录 F4 | 21 个函数「只用 `g.mv`」，改签名是零风险第一刀 | **是 10 个**。另外 11 个全部返回 `(Gen, Bool)` 并调用 `gen_cexpr`（整棵表达式生成器），结构上不可能收裸 `MethodVisitor`。备忘录把「**调用**了 mv-only helper」当成了「**是** mv-only」——`gen_cbinary`(:2080) 正是那四个真 helper 的调用方 |
| ARCH-02 勘察备忘录 F5 | codegen 的 rt-class 写手可以直接抬成新模块（「免费刀」） | **刀是真的，但边界不在 :270**。天真地切 :270/:2949 会造出 Dawn **硬禁**的模块环：region 用 head 的 `obj`/`fn_iface`/`tuple_class`/`erased_apply_desc`（:33-42），head 又用 region 的 `UNIT_CLASS`/`PVEC_CLASS`/`HAMT_CLASS`/`ARRAY_CLASS`。**把 :33-42 那 10 行一起搬走，环就消失**（§2.2） |

另外三处文档数字全线过期，本批同批校正（§8）：checker 7,924→**11,308**、
`Cx` 44/46→**47**、`emit.dawn` 3,531→**2,534**、`Gen` `:159`/30 余字段→**`:92`/21 字段**、
`lowered-ir-design.md:139` 的 `DiagSink` 还列着 `reported_key_types`——**该字段全仓零命中**。

### 1.3 语言给拆分设的三道坎（两份备忘录各自实测，结论一致）

1. **Dawn 硬禁模块环**（`analyze.dawn:900-946`，spec §10.5）：任何多模块拆分只能是 DAG。
2. **`pub` 是声明级，没有字段级私有**：把 `Cx` 搬进 base 模块**不带来任何封装**，
   只是换了个定义处。封装在 Dawn 里只能靠「不 `pub` 类型、只 `pub` 构造/访问函数」。
3. **没有 `&mut`、没有嵌套更新糖、lambda 不能捕获 `var`**：
   `Cx2 { ..cx, names.fns: … }` 是语法错误；`(k) => { cnt = cnt + 1 }` 被拒。
   所以「手写线程化」是唯一形状，拆分改不了它，只能改它有多少层。

**这三条合起来给出本文最重要的一句话：在 Dawn 里，「拆文件」和「拆状态」是两个不同的
项目，只有前一个是免费的。** 模块拆分对调用点的代价是**零**（`names.bind_fn(cx, "f")`
与 `bind_fn(cx, "f")` 同形，备忘录的 base 模块实验实测）；有代价的只有状态拆分，
代价是每个写点多一层 `X { ..cx.x, … }`。`lowered-ir-design.md:134-141` 默认了两者是
同一件事，所以它开出的六组件药方在这里失效（§6.1）。

## 2. 目标形状

### 2.1 checker 侧：三层 DAG

`checker.dawn` 拆成三个模块。分界线不是「六个概念组件」，而是**实测出来的调用图割**：
12 个注册期 pass 的传递闭包是 **67 个函数**，body 检查那半边的闭包是 **162 个**，
**两者对 19 函数 SCC 的交集为空**——没有一条边需要打断。
（备忘录第一版被 `checker.dawn:1839` 骗过：那是 `pass_java_uses` 后面**一个 test 块**里的
`check_module(...)`，不是 pass 的调用边。另一处同样的假边在 `:3598`。）

```
  types / ast / tast / token / jsig / suggest / parser
                      ↑
                  cx.dawn            ~600 行
                      ↑
                passes.dawn          ~2,430 行（含 ~495 行 test）
                      ↑
               checker.dawn          ~8,280 行
                      ↑
   analyze · doc · lspq · stdlib · cdriver · jfold · lsp · interp · main
```

| 模块 | 装什么 |
|---|---|
| **`cx.dawn`**（新） | `Cx`(:91) `AliasE`(:74) `LambdaCx`(:172) `Origin`(:351) `ModExports`(:5060) `Frame`(新，§2.3) + `cx_new` + `test_cx`(:1088) + **两侧共享的 19 个 helper（481 行）**：`cerr`/`cerr_h`/`cerr_o`(:242-256)、`fresh`/`fresh_effvar`、`resolve_type` 解析器族（`resolve_named` :961-1087 / `resolve_qual` :880-960 / `resolve_assoc` / `resolve_alias_target` / `resolve_eff_at` / `wrap_opaque`）、`is_const_serializable`(:1673-1722)、`no_sig`(:6406) |
| **`passes.dawn`**（新） | 12 个注册期 pass + 48 个 pass 专属 helper（1,938 行）+ `Shell`(:1899) + 它们相邻的 ~495 行 test。`use cx`、`use suggest`、`use parser`（只 test 用；parser 不依赖 checker，无环） |
| **`checker.dawn`**（余） | body 检查的 19 函数 SCC + ~150 个被调函数、`EffFrame`(:5322)、`check_module`、`exports_of`、`visible_bins`，以及**两个搬不走的 test**（`:1832` 与 `:3593`，它们调 `check_module`） |

**这个 DAG 只有一条真代价：`Cx` 必须离开 `checker.dawn`。** 9 个下游模块全部从
`checker` 取 `Cx`/`ModExports`，而 **Dawn 没有 re-export**（`DUseModule` 不带 `pub` 位，
`grep "pub use"` 全仓零命中；实测下游写 `use checker2.{Cx}` 直接报
`module 'checker2' has no exported name 'Cx'`）。所以这 9 行 `use` 必须同批改，
不能靠 shim 分批。**漏改是编译错误，不是静默错误**——响亮，可接受。

拆得更细（把 12 个 pass 再分成几个模块）判为**不做**：它们密集共用
`bind_fn`/`cerr*`/`resolve_type`，且只以 `check_module:10024-10039` 的固定顺序跑一次。

### 2.2 后端侧：两个新叶子

```
  jvmops.dawn（零 import）
        ↑
  rtclasses.dawn（新，~2,695 行）
        ↑
  codegen.dawn（~730 行）
        ↑        ↖
  jvmhelp.dawn（新，~150 行）
        ↑
  emit.dawn（~2,300 行）
        ↑
  main.dawn · testrun.dawn
```

**`rtclasses.dawn`** = `codegen.dawn` 的 `:33-42`（4 个命名 helper，**必须一起搬，
否则成环**）+ `:270-2949`（`# ---- shared runtime classes ----`，26 个 const + 49 个函数，
`dawn/rt/{Fn,PanicError,Unit,Show,TupleN,Bytes,Io,Array,Strings,FnCmp,Ord}` 的字节码写手）
+ 唯一测到这块的 test（`:249-265`）。搬完 `codegen.dawn` 只剩 ADT 类合成（`:2951-3425`）
与描述符/槽位映射（`:59-172`），约 730 行。

搬完之后 `codegen.dawn` 反向 `use rtclasses.{obj, fn_iface, tuple_class,
erased_apply_desc, append_const, close_mv, UNIT_CLASS, SB, SHOW_CLASS, PVEC_CLASS,
HAMT_CLASS, ARRAY_CLASS}`——单向，无环。**region → tail 的引用数为零**，这是这条边
能一刀切干净的原因。

**`jvmhelp.dawn`** = `emit.dawn` 里既有的无状态 `MethodVisitor` helper（`:151-201`，
勘察补丁 `arch02-split-experiment.patch` 已经真跑过这个形状）+ 刀 A3 让它们变成
无状态的那 10 个函数。

`emitc.dawn`(`CSt` 6 字段) 与 `rc.dawn` **不在本批范围**：C 后端从来没有宽状态对象问题。
唯一跨后端同型的一块是 `consts: Map[String, CValue]` + `blocks: Map[(Int,Int), CValue]`
（`emit.dawn:124-125` 与 `emitc.dawn:75-76` 类型逐字相同），本批**不抽共享**——
抽它要新建一个两个后端都依赖的模块，收益是消掉两行重复的类型声明，不换。

### 2.3 `Cx` 的 47 个字段怎么分

拆状态的判据只有一条：**只有当一个函数的整个传递闭包只需要子记录时，子记录才买到东西。**
否则它只是把 `cx.f` 写成 `cx.g.f`，把 47 个字段换成「44 个字段 + 一个盒子」。
实测（备忘录事实 7）：`check_fn` 家族五个入口的传递可达字段是 **41/47**——body 检查
那半边是一个真正的整体，任何分簇都收窄不了它的签名。

所以 47 个字段只切**一刀**：

| 簇 | 字段 | 裁决 |
|---|---|---|
| **帧（8）** | `isolated` `used_effects` `eff_witness` `current_sig` `dict_syms` `scopes` `lambda_stack` `loop_stack` | **提成 `Frame`**（D9），声明在 `cx.dawn` |
| 类型环境（6） | `adts` `adts_by_name` `ctors_by_name` `aliases` `alias_resolved` `alias_resolving` | 留 `Cx` 顶层 |
| trait 环境（5） | `traits` `traits_by_name` `local_traits` `local_impls` `impl_table` | 留 |
| 效果（2） | `effects` `effect_infos` | 留 |
| 当前签名绑定（3） | `current_tparams` `current_eff_vars` `current_tparam_bounds` | 留（**故意不进 `Frame`**，理由见 D9） |
| 符号（5） | `syms` `fns` `fn_origin` `std_fns` `scopes`→已进帧 | 留 |
| 控制流杂项（2） | `loop_jumps` `in_test` | 留（同 D9） |
| const（4） | `consts` `const_order` `all_const_names` `const_cutoff` | 留 |
| import/export（5） | `module_aliases` `module_fn_sigs` `imported_names` `module_exports` `moved` | 留 |
| Java（2） | `java_classes` `jsig` | 留（D11 判为不拆） |
| 横切（5） | `diags` `next_id` `src_path` `line_starts` `owner_class` `is_std_module` | 留（D10 判 `DiagSink` 不拆） |

**`Frame` 的 8 个字段不是我挑的，是代码里已经有的。** `checker.dawn:5322-5331` 的
`EffFrame` 就是这 8 个字段的手工同义词，`enter_isolated`(:5334) 逐字段拷进去、
`leave_isolated`(:5362) 逐字段拷回来。提出 `Frame` 之后：

```dawn
# 今天（enter_isolated，:5335-5343 + :5346-5357，共 22 行）
let frame = EffFrame { isolated: cx.isolated, used: cx.used_effects, … }   # 8 行
(Cx { ..cx, used_effects: [], eff_witness: empty_w, … }, frame)            # 9 行

# 之后
let saved = cx.frame
(Cx { ..cx, frame: Frame { ..cx.frame, used_effects: [], … } }, saved)     # 仍是 9 行，多一层嵌套
```

```dawn
# leave_isolated 的恢复端，:5368-5377（9 行）→ 1 行
Cx { ..cx1, frame: saved }
```

**净收益诚实记账**：删掉 `EffFrame`（10 行的手工同义词）+ 恢复端 9 行变 1 行 +
`Cx` 顶层 47→40；**代价**是 ~86 处读加一层 `.frame.`、~67 处写加一层嵌套。
这就是「无 `&mut`」在本批的全部真实成本：**写入端一分钱都省不掉，省的只在恢复端**。

### 2.4 `Gen` 的 21 个字段怎么分

| 字段 | 裁决 |
|---|---|
| `own_fns`(:99) | **删**（刀 A2）。`emit_module` 收它、存进 `Gen`、**从此无人读**；全仓仅三处出现：字段声明 :99、形参 :1419、构造 :1454。`main.dawn:359/371` 在算它 |
| `class_name` `adts` `traits` `impl_table` `prog_fns` `dicts` `consts` `blocks` | **提成 `GenCtx`**（构造后只读，8 个） |
| `mv` `next_slot` `slots` `syms` `method_ret` `rets_null` `cloops` `lift_descs` `sam_ctr` `pending_sam` `const_fields` `const_by_key` | 留 `Gen`（可变，12 个） |

**二分而不是三分**（D13）：三分（CTX / CLS 类级累加 / METH 方法游标）会让
`gen_load_const`、`emit_sam_conversion`、`gen_ccall` 三个函数返回 `(Cls, Cur, Bool)`
三元组，而换不到任何签名收窄——因为 `GenCtx` 是**只读**的，它不进返回值：

```dawn
# 今天
fn gen_ccall(g: Gen, …) -> (Gen, Bool)
# 二分之后（返回元数不变）
fn gen_ccall(gx: GenCtx, g: Gen, …) -> (Gen, Bool)
# 三分之后（返回元数 +1）
fn gen_ccall(gx: GenCtx, cl: Cls, cur: Cur, …) -> (Cls, Cur, Bool)
```

**只读的那半边不进返回值，元数就不涨。** 这是二分优于三分的全部理由，也是它在
「无 `&mut`」的语言里唯一能白拿的一次便宜。真正的收益不在 `Gen` 变小，而在
**45/62 个函数只碰一个聚类**（备忘录 F4）：二分之后它们里相当一部分连 `Gen` 都不用收，
于是可以继续往叶子模块搬——`jvmhelp.dawn` 的第二批就是这么来的。

`slots`/`syms` **不重置**（`gen_cbody:1241-1249` 只重置 `mv, next_slot, method_ret,
rets_null, cloops` 五个）：按**实际行为**归到可变 `Gen`，**不要**改成每方法清空（D14）。

### 2.5 判为不拆的（理由都在 §6）

`DiagSink`、`SymEnv`/`TypeEnv`/`EffEnv`/`TraitEnv`（lowered-ir §3.2 的六组件）、
checker 的 Java 簇、`mv` 整体移出 `Gen`、`Gen` 三分、`emit_module` 的位置对齐。

## 3. 刀法

### 3.0 刀 0（前置，另一个 agent 在做）

**checker 诊断 golden。** 今天 checker 层诊断在全仓**没有任何外部对拍**：
`grammar-corpus` 只跑 `dawn __parse`（`run.sh:22,38`）、`spike-native` 的 `.expect`
钉的是程序 stdout（`grep -l "error:" *.expect` 零命中）、`__emit` 系列只编译能通过的程序。
245 个 `cerr` 调用点，防线只有 88 个内联 test。而 `cerr` 是 `cx.diags ++ [...]` 追加语义
（`checker.dawn:243`）——**顺序敏感**。

刀 0 **阻塞整条 Lane B**（§3.2）。它**不阻塞 Lane A**：后端刀不碰 checker，
诊断文本不可能变。这是本批可以两条腿同时走的原因之一。

### 3.1 刀表

排序原则：**能被最强证明覆盖的刀排前面。**「最强」= 纯搬运（§5.2 的归一化全量不变量
可用，实测零差异）> 改签名（靠 emit 语料 + 诊断 golden）> 改记录形状（同上，但
diff 最大、人眼评审最弱）。

| 刀 | 动什么 | 预期 `changed` 模块集 | 可与谁并行 |
|---|---|---|---|
| **C1** | 文档校正（§8 的过期数字与过期待办；含 P7 顺路项） | —（不动 `.dawn`） | 全部 |
| **A1** | `codegen.dawn:33-42` + `:270-2949` + test `:249-265` → 新叶子 `rtclasses.dawn`；三个 importer 改 `use` | `rtclasses` `codegen` `emit` `main` `testrun` | 全部 B 刀、A2 |
| **A2** | 删死字段 `Gen.own_fns`（字段 + 形参 + `main.dawn` 两处实参） | `emit` `main` | 全部 B 刀、A1 |
| **A3** | 10 个 mv-only 函数改收 `m: MethodVisitor`（21 处调用点，全在 emit.dawn 内） | `emit` | 全部 B 刀 |
| **A4** | A3 的 10 个 + 既有无状态 helper（`:151-201`）→ 新叶子 `jvmhelp.dawn` | `emit` `jvmhelp` | 全部 B 刀 |
| **A5** | `Gen` 二分：`GenCtx`（只读 8）+ `Gen`（可变 12） | `emit` `main` | 全部 B 刀 |
| **B1** | `pass_register_impls` 尾部两个整模块循环（`:3171-3212`、`:3218-3238`）提成两个顶层函数 | `checker` | 全部 A 刀 |
| **B2** | 新建 `cx.dawn`：`Cx` + `AliasE` + `LambdaCx` + `Origin` + `ModExports` + `cx_new` + `test_cx`；**9 个 importer 改 `use`** | `checker` `cx` + 9 个 importer 中 Core 真变了的那些（**须先实测再写进提交信息**，D16） | 全部 A 刀 |
| **B3** | 19 个共享 helper（481 行）搬进 `cx.dawn` | `checker` `cx` | 全部 A 刀 |
| **B4** | 新建 `passes.dawn`：12 个 pass + 48 个 helper + `Shell` + ~495 行 test；`analyze`/`doc` 改 `use` | `checker` `passes` `analyze` `doc` | 全部 A 刀 |
| **B5** | `Frame`（8 字段）子记录，删 `EffFrame` | `checker` `cx` | 全部 A 刀 |
| **C2** | 收尾：回填结果、把 `docs/README.md` 的索引补上、本文状态行改「已落地」 | — | — |

### 3.2 顺序依赖与并行

```
C1 ──┬──► Lane A:   A1 ─┐
     │              A2 ─┼──► A5
     │              A3 ──► A4 ─┘
     │
     └──► 刀 0 ──► Lane B:   B1 ──► B2 ──► B3 ──► B4 ──► B5

                              两条 lane 全程并行，收尾 ──► C2
```

- **Lane A 与 Lane B 完全并行**：技术上不存在先后依赖（`emit.dawn` 是叶子，只有
  `main.dawn` 导入它；它与 checker 零耦合）。`docs/audit/README.md:150` 写的
  「ARCH-01 ──► ARCH-02」是**文档排期，不是技术依赖**，C1 顺路改掉它。
- **唯一的交界是 `main.dawn`**：A1/A2/A5 改它的 `use codegen`/`use emit` 与两处
  `emit_module` 实参，B2 只改它第 64 行一个 `use checker.{Cx}`。
  **规定 `main.dawn` 的编辑窗口归 Lane A**，B2 落地时以 rebase 解决那一行。
- **Lane A 内部**：A1 与 A2 互不相干可并行；A3 → A4 严格有序（A4 搬的就是 A3 变干净的
  那批）；A5 排最后（它要 A2 之后的字段表）。
- **Lane B 内部严格串行**：B1 是暖场（同文件、纯语法搬运，也是刀 0 语料的第一次实弹）；
  B2 建 base 模块；B3/B4 往里搬；B5 最后动记录形状。
- **B5 与 A5 都是可取消的**：它们是本批唯二「改记录形状」的刀，收益最薄、风险最高。
  取消它们不会让树停在半拆状态——前面每一刀都是自洽的终点。

## 4. 每刀的验收模板

**照抄，一条不漏，任一红就地停。** 顺序即执行顺序（便宜的先跑）。

```bash
# 0) 准备：★ 在【同一个目录】里出刀前/刀后两份产物，不要用两个 worktree
#    git stash → 重建 → 出「刀前」 → stash pop → 重建 → 出「刀后」
#    （每次重建约 19s）
#
#    【B1 实测教训，别再踩】两个 worktree 的做法有假阳性：路径依赖会被解析成
#    【绝对路径】，而它会出现在 `unwrapped None` 的 panic 字符串里、进而进入
#    发射出的 class。于是 playground（它把 packages/web 当路径依赖）会仅仅因为
#    两棵树在不同路径上就报差异。单目录法从构造上没有这个洞。
#    （两棵树各自都是确定性的——bef-vs-bef、aft-vs-aft 都已验证过。）

# 1) 格式（能抓机械搬运留下的脏——勘察实测抓到过一个多余空行）
./bin/dawn fmt selfhost/src --check

# 2) 内联 test（诊断的最后一道防线，295 个 + 刀 0 新增）
./bin/dawn test selfhost

# 3) ★ 主证明：刀前/刀后逐字节对拍五个外部语料，必须【零差异】
for t in site playground packages/web packages/json examples/calc.dawn; do
  (cd <bef>  && ./bin/dawn __emit "$t" -o /tmp/bef/"$t")
  (cd <work> && ./bin/dawn __emit "$t" -o /tmp/aft/"$t")
  diff -rq /tmp/bef/"$t" /tmp/aft/"$t" || echo "FAIL $t"
done
#    selfhost 不进这一步：它编译的就是被改的源码，必然差异（§5.1）

# 4) ★ 诊断 golden（刀 0 的语料），必须【零差异】

# 5) Core：爆炸半径 + （纯搬运刀）归一化全量不变量
./scripts/selfhost-core-diff.sh
#    → 【changed】列表必须恰好等于声明的模块集，多一个算事故
#    → 【ADT-shifted】列表是漂移，不算事故，也【不要】把它并进上一条
#      （B1 实测：本文原先把两个桶合并，写成了一条不可满足的判据。脚本自己
#       :103-112 就把它们分开，并注明任何改动早期模块的刀都会让 ADT id 漂移
#       ——inference 变量与 ADT 声明共用一个 next_id 计数器。核对方式：
#       s/Adt[0-9]+/AdtN/g 之后各模块哈希须与基线相同，即纯重编号。）
#    → 声明的模块集 = 【Core 真的变了的模块】，不是【改了 use 行的文件】。
#      后者是前者的超集：A1 实测 testrun.dawn 改了 use 但 testrun.core 逐字节不变，
#      因为 Core 打印 const 引用【不带模块前缀】、且 Core dump 里【没有 const 定义】。
#    → 纯搬运刀（A1 A4 B2 B3 B4）另跑 §5.2 的归一化不变量，必须零差异
./scripts/selfhost-core-diff.sh --record
git diff scripts/core-golden/selfhost.sha scripts/core-golden/selfhost.norm.sha
#    ★ 贴进提交信息/PR，人工核对。norm.sha 是脚本自带的归一化伴生 golden，
#      比 §5.2 的临时命令更省事也更可信（它来自门禁而非一次性脚本）。
#
# ★★ 两条 lane 各自 --record 过 golden 时，合并前【必须重录】，
#    绝不能让 git 逐行 auto-merge 这两个文件——拼接出来的 golden 不是构建产物。

# 6) 自举没断
./scripts/selfhost-fixpoint.sh               # OK: B == C

# 7) 字节合法
./scripts/classfile-verify/run.sh

# 8) N-1 对拍：六个 emit 必须全 OK，【零 NOTE】（§5.3）
./scripts/selfhost-prev-diff.sh

# 9) 回归网
./scripts/selfhost-run-diff.sh
./scripts/selfhost-fmt-diff.sh
./scripts/selfhost-lsp-diff.sh

# 10) 文档
./scripts/doc-check.py
```

**逐刀的差异化要求**：

| 刀 | 步 3（五语料零字节差异） | 步 5 的归一化不变量 | 额外 |
|---|---|---|---|
| A1 | 必须 | **必须零差异**（搬家映射 `s/\brtclasses\./codegen./g`） | 编译器自己会挡住模块环——若报 `circular module dependency`，说明 `:33-42` 没一起搬 |
| A2 | 必须 | 不适用（删了东西） | `grep -rn own_fns selfhost/` 必须归零 |
| A3 | 必须 | 不适用（改签名） | diff 里每个 `f(g` → `f(g.mv` 都要能一眼对上，21 处 |
| A4 | 必须 | **必须零差异**（`s/\bjvmhelp\./emit./g`） | |
| A5 | 必须 | 不适用 | `GenCtx` 不得出现在任何返回类型里（这是二分的定义） |
| B1 | 必须 | 不适用（同文件提函数，Core 会多两个符号） | **诊断 golden 是这刀的主证明**：两个尾循环相对于 `(cx1, impl_sigs)` 的执行位置不能变 |
| B2 | 必须 | **必须零差异**（`s/\bcx\./checker./g`） | 9 个 `use` 全改完才编得过 |
| B3 | 必须 | **必须零差异** | |
| B4 | 必须 | **必须零差异** | 两个 test（`:1832`/`:3593`）留在 checker.dawn |
| B5 | 必须 | 不适用（改记录形状） | ★ 见 §5.4 的字段多重集核对 |

## 5. 证明与风险

### 5.1 证明矩阵：每条门禁在本批还能证明什么

| 门禁 | 本批**能**证明 | **不能**证明 |
|---|---|---|
| **刀前/刀后五语料逐字节**（本批主证明，P4） | 编译器对**与自身无关的程序**发射的字节逐字节不变；归因到单刀 | 只走**编译成功**的路径；不覆盖任何诊断；不覆盖编译器源码里才有的构造 |
| **刀 0 诊断 golden**（新增的另半边） | 失败路径的诊断文本 / 条数 / **顺序** | 只覆盖语料写到的那些 `cerr` 点（全仓 245 个）——覆盖率就是语料的覆盖率 |
| `selfhost-prev-diff.sh` 的 `emit selfhost` | **前后对拍覆盖不了的那半边**：编译器源码这份语料，由两个编译器同源比对 | v0.47.0 之前被 `Emit-Change(emit *)` 整体豁免（§5.3） |
| `selfhost-prev-diff.sh` 的另五个 emit | 与主证明重叠，但基线是冻结的 release，能抓累积漂移 | 同上的豁免问题 |
| `selfhost-prev-diff.sh` 的 lex/parse/fmt backend-dawn | 前端与格式化对生产语料的输出 | 与本批几乎无关（本批不碰 lexer/parser/fmt）；网络挂了会 `SKIP` |
| `selfhost-core-diff.sh` 的 **13 份 flat dump** | **std + calc/traits/eqhash 的 Core 全文逐字节**——本批**必须全程零差异**，是 checker 侧最强的机器证明（勘察实测拆分后不变） | 后端（Core 是它的**输入**）；发射的字节 |
| `selfhost-core-diff.sh` 的 `selfhost.sha` | **爆炸半径的界限**（P5） | 「代码没被改坏」——每刀 `--record` 覆盖基线，§5.2 补这块 |
| `selfhost-fixpoint.sh`（B==C） | 自举没断：新划分没让编译器编不出自己 | **行为等价**。A/B/C 三代编译的是**同一份 HEAD 源码**（`:27-30`），行为一起变照样 B==C。勘察实测：拆完直接通过 |
| `native-fixpoint.sh` | 同上（不在 CI） | 本批不碰 `emitc`/`rc`，可不跑 |
| `bin/dawn test selfhost`（295 内联 test） | 搬运时 test 块必须原样跟着走；顺序敏感的 `diags` 被 88 个 checker test 抽样 | 245 个 `cerr` 点里没写 test 的那些 |
| `classfile-verify/run.sh`（1386 class） | 字节**合法** | 字节**正确**（脚本头 :5-6 自陈） |
| `spike-native/run.sh`（58 程序） | 两后端行为一致 | JVM 发射的字节 |
| `run-diff` / `fmt-diff` / `lsp-diff` | CLI 转录、格式化、LSP JSON | 发射字节 |
| **「编译器编译自己」这件事本身** | accept 侧最大的语料：11,308 行 checker + 全部 std + 五个语料程序都要过 checker。任何**误拒**当场变成构建失败 | reject 侧零覆盖 → 这就是刀 0 存在的全部理由 |

### 5.2 `selfhost.sha` 全程失防怎么补（本文的实测答案）

问题：`--record` 会把旧哈希整体覆盖，于是这条门禁在整批期间无法区分
「代码搬了家」和「代码搬家时被改坏了」。

**答案：对纯搬运刀，用「模块无关的归一化全量 Core 不变量」当收据。**
把全部 `.core` 拼起来，抹掉模块头、抹掉 ADT id、按作者声明的**搬家映射**把模块前缀归一，
排序后比对——**一次纯搬运应当逐行零差异**。

```bash
norm() {  # $1=dump 目录  $2=搬家映射（sed 脚本，刀作者声明）
  cat "$1"/*.core | grep -v '^module ' \
    | sed -E "s/Adt[0-9]+/AdtN/g; $2" | LC_ALL=C sort
}
./bin/dawn __lower --dump /tmp/coreA selfhost   # 刀前（在 <bef> 里跑）
./bin/dawn __lower --dump /tmp/coreB selfhost   # 刀后
diff <(norm /tmp/coreA '') <(norm /tmp/coreB 's/\bjvmhelp\./emit./g')
```

**已实测**（4ae6b61 + `arch02-split-experiment.patch`，即把 7 个无状态 helper
搬进 `jvmhelp.dawn`）：

| 比对 | 行数 | 差异 |
|---|---|---|
| 归一化后 | 389,288 | **0** |
| 未归一化（只去模块头 + 排序） | 389,288 | 94 行 |
| **负控**：在搬走的代码里把一个字面量 `127` 改成 `126` | 389,288 | **4 行** |

未归一化 94 行说明归一化确实在干活；负控 4 行说明它不是空检查。

**用法与边界**：
- **搬家映射由刀作者在提交信息里声明**（「这些符号从 X 搬到了 Y」），脚本只负责验证
  「除此之外什么都没变」。声明可评审，验证是机械的——这正是 `--record` 缺的那一半。
- 只对**纯搬运**刀成立（A1 A4 B2 B3 B4）。改签名/改记录形状的刀（A3 A5 B1 B5）
  它必然不为零，那几刀靠五语料 + 诊断 golden。
- **不进 `selfhost-core-diff.sh`**（D17）：在门禁正当门禁的时候改门禁，是把唯一的界限
  也拆掉。本批以**临时命令**跑，输出贴进提交信息。批次结束后若还想常设化，另行立项。
- 兜底纪律：无论有没有不变量，**`git diff scripts/core-golden/selfhost.sha` 每刀都要
  贴出来人工核对**，且只能含本刀声明的模块。
- **脚本自带 `selfhost.norm.sha`**（归一化伴生 golden，一行一模块）。B1 实测它给出的
  「除此之外什么都没动」收据与本节的临时命令同强度，却来自门禁本身——**优先用它**，
  临时命令留给需要声明搬家映射的纯搬运刀。

> **★ 两份 Core 收据都看不见 const。**（A1 实测，被它自己的负控抓出来）
> Core 打印 const 引用**不带模块前缀**（`constref UNIT_CLASS : String`），且 Core dump 里
> **根本没有 const 定义**。后果有两条：
> 1. 一个模块只导入了被搬走的 const 时，它的 `use` 行变了、`.core` 却逐字节不变——
>    所以**声明的模块集要按「Core 真的变了」算，不是按「改了 `use`」算**（A1 的 `testrun`）。
> 2. **改掉一个 const 的值，两份收据都是零差异**。A1 的第一次负控就撞在这上面：把
>    `ARRAY_MIN_CAP: Int = 8` 改成 `9`，归一化不变量返回 0；换成改函数体里的字面量才得到
>    预期的 4 行。
>
> 所以搬 const 的刀（A1 搬了 26 个；B2 实测**没有**搬 const），**const 那部分只由五语料
> 逐字节比对覆盖**。写这类刀时要确认：被搬的 const 确实被那五个语料实际用到；否则它们
> 处在全部门禁的盲区里。

> **★ 两份 Core 收据也看不见 test 块。**（B2 实测）
> `__lower` 不发射 test 块——实测 `checker.core` 里只有 4 处 `test_cx` 调用，而源码里有 89 处。
> 于是「只被 test 块用到」的搬运在 Core 侧完全隐形：B2 的 9 个 importer 里有 **6 个**
> `use` 行变了而 `.core` 逐字节不变，全部是这个原因（与 A1 的 `testrun` 是同一个
> 「`use` ≠ Core」缺口，但成因不同：A1 是 const 不入 Core，B2 是 test 块不入 Core）。
> **B4 又添了第三个成因：死导入。**`analyze` 的十个 pass 导入只出现在 `use` 行、
> 函数体里一次都没调过，所以改了它的 `use` 而 `analyze.core` 逐字节不变。
> 三个成因合起来的结论是同一条：**声明的模块集永远按「Core 真的变了」算。**
>
> 这一块由 **`dawn test selfhost`** 覆盖，不由任何 Core 收据覆盖。含义是：
> 搬动只被 test 块引用的东西时，唯一的守卫是 295 个内联 test 本身——所以那一刀不能同时
> 改动 test 的内容，否则守卫和被守卫的东西一起变了。

> **★ 「纯搬运 ⇒ 归一化后逐行为零」有一个例外：拆模块会【合法地新造 Core】。**（A4 实测）
> lowering **按模块合成结构化相等**——一个模块只要比较某个 ADT，就会得到自己的
> `structeq$AdtN` 与配套 `prim$…$eq`。A4 把比较 `Ty` 的函数搬进 `jvmhelp` 后，
> 该模块获得了自己的一份，于是不变量返回 **376 行、全是新增、零删除**。
> 排除这份重复后才是 0。
>
> 判别方法（A4 用的，机械可查）：新增行必须能在原模块的 `.core` 里**逐字找到对应**
> （模块前缀不同），即它是既有实例的副本而非新语义。**验证靠子串包含，不靠肉眼。**
>
> 与上面两条盲区不是同一类：那两条是「收据看不见」，这条是「拆分本身正当地造出了东西」。
> A1 与 B2 没撞上，是因为它们的两半没有比较同一个 ADT。**今后任何「两半都比较同一 ADT」
> 的拆分都会撞上**，别把这 376 行当成事故。
>
> **判据的准确表述**（B3 独立测到同一机制后给的说法）：**对作者写的代码是零**——
> 0 删除，新增行**全部限于合成定义**（`dict …` / `prim$…$eq` / `structeq$AdtN`）。
> B3 是 0 删除 + 448 新增（18 个合成定义），排除后 376,929 行两侧相等。
> 交叉验证：A4 那一刀两侧的「排除 shim 后总行数」**也是 376,929**——一棵新增了模块的树
> 落回同一个数字，说明这个指标量的是作者代码而不是模块簿记。
>
> **B4 会撞得最狠**（它搬 12 个 pass），别在那一刀上重新惊讶一次。
>
> **★ 归一化配方里还要加一项：lambda id 也按模块重编号。**（B4 实测）
> 它和 ADT id 是同一个形状，必须同样归一——**不归一会得到 32 处伪「删除」**。
> 这是最危险的一种假信号：删除正是我们用来断定「作者代码消失了」的依据，
> 伪删除会让不变量朝**危险方向**说谎。前面的刀没撞上，只是因为没有一刀搬走过
> 足够多的闭包让那个计数器重编号。
>
> **交叉验证的分量**：B4 用 B3 那套更窄的 shim 集重跑，得到 **376,929**——与 B3
> 逐行相同。两个 agent、两棵不同的树、两套 shim 定义，数字对上了，这才让「排除 shim」
> 从权宜之计变成规则。

### 5.3 v0.47.0 为什么是开工前提（P3 的理由）

`1b8ee7f` 的提交尾行声明了 `Emit-Change(emit *): every jar gains the Index trait
interface class`。`emitchange.sh:24-41` 的 `declared_for()` 扫
`$(cat scripts/seed-release.txt)..HEAD` 的全部提交，`seed-release.txt` 今天是 `v0.46.0`，
glob `emit *` 命中 prev-diff 打印的**全部六个** emit 标签。实跑 prev-diff，六条全是
`NOTE ... declared`，没有一条是 `OK`，脚本末尾照样打印
`OK: HEAD agrees with v0.46.0 on the corpus`。

关键点在于**本批预期声明零条 `Emit-Change`**：

- 模块拆分对 prev-diff **不可见**——prev-diff 是同一份源码、两个编译器
  （`selfhost-prev-diff.sh:62-63`），新模块两侧都会出现（ARCH-02 备忘录 F1 在真实拆分上
  实测：`jvmhelp.class` 两边都有，唯一差异是 `#120` 已声明的 `dawn/tr/Index.class`）。
- 这条与 `lowered-ir-design.md:163-172` 定的验收条一致：
  「emit 语料**不允许有任何字节差异**，**不接受 `Emit-Change:` 豁免**——这次改造的定义
  就是『结构变、输出不变』。一旦出现差异，说明改变了语义，是 bug 不是变更。」

于是：**v0.47.0 之后，prev-diff 里任何一条 `NOTE` 都是事故信号。而在通配声明还活着的
窗口里，`NOTE` 是默认值——信号被基线淹掉。** 这才是 P3 的准确理由，不是「少一条豁免」
而是「豁免把红灯的定义改掉了」。

**不为 A1 开特例**：A1 是纯搬运、归一化不变量最airtight的一刀，理论上可以先做。
判为不开（D18）——一个批次里两套开工规则，评审时没人记得住哪刀适用哪套。

### 5.4 最可能出事的地方，以及早期信号

**排第一：B5（`Frame`）改变了 `enter_isolated`/`leave_isolated` 保存-恢复的字段集。**

这是一个具体的、已经踩到的陷阱，不是抽象担忧。今天 `EffFrame`(:5322) 有 8 个字段，
`leave_isolated`(:5368-5377) 恢复的就是这 8 个。如果 `Frame` 按「概念」多装几个——
比如把 `current_tparams`/`current_tparam_bounds`/`current_eff_vars` 也放进去——那么
`Cx { ..cx1, frame: saved }` 会**连带恢复今天不恢复的字段**。comptime 体里只要有一个
local fn（`enter_fn:9724-9731` 会写 `current_tparams`/`current_tparam_bounds`），
行为就变了。

**而这个变化只影响诊断，不影响发射的字节**——五个 emit 语料、13 份 flat dump、
fixpoint、classfile-verify **全部看不见它**。能看见它的只有刀 0 的语料（如果语料恰好
写到了这条路径）和 88 个内联 test 里的那一个（`:5401`）。

**这就是 §2.3 把 `Frame` 定死成 8 个字段的原因**——`Frame` 的字段集必须逐字等于
`EffFrame` 今天的 8 个，一个不多。同理 `loop_jumps`/`in_test` 判为留在 `Cx` 顶层：
它们按概念属于帧，但今天不在保存-恢复集合里。

**早期信号（机械可查）**：B5 的 diff 里，`enter_isolated` 与 `leave_isolated` 提到的
字段名**多重集必须不变**：

```bash
for f in isolated used_effects eff_witness current_sig dict_syms scopes lambda_stack loop_stack \
         current_tparams current_tparam_bounds current_eff_vars loop_jumps in_test; do
  echo "$f $(sed -n '5334,5380p' <bef>/selfhost/src/checker.dawn | grep -c "\b$f\b") \
           $(sed -n '/pub fn enter_isolated/,/^## Does this/p' selfhost/src/checker.dawn | grep -c "\b$f\b")"
done
```
两列不等就停。

**其余风险，按降序**：

| 风险 | 早期信号 | 响亮度 |
|---|---|---|
| B4 把某个 pass 相对 `check_module:10024-10039` 的执行顺序挪动了 → 诊断顺序变（`cerr` 是 `++ [...]` 追加语义） | 刀 0 语料出现差异 | 只有刀 0 看得见 |
| B1 提取尾循环时改变了它相对 `(cx1, impl_sigs)` 的位置 | 同上。**B1 是刀 0 的第一次实弹**，故意排在最前 | 同上 |
| A5 的 `GenCtx` 混进了返回类型（三分蜕变） | `grep -nE '\->[^=]*\bGenCtx\b' selfhost/src/emit.dawn` 必须零命中 | 一条 grep |
| ↑ **原先写的 `grep "GenCtx" \| grep "\->"` 是错的**（A5 实测）：每一行签名都含 `->`，所以在**正确**的实现上它返回 44 行。一条在正确实现上就报警的检查比没有检查更糟——第一个跑它的人会以为刀坏了 | | |
| A1 的模块环（`:33-42` 没一起搬） | 编译器直接报 `error: circular module dependency` | **响亮**，编译期 |
| B2/B4 漏改某个 `use`（Dawn 无 re-export） | `module 'checker' has no exported name 'Cx'` | **响亮**，编译期 |
| B2 的 `changed` 集比预期大（9 个 importer 里哪些的 Core 真变了，事前不知道） | 步 5 的列表 ≠ 声明 | 会红，但要求**先在丢弃分支上实测再写提交信息**（D16） |
| A3 的 21 处调用点漏改一处 | 类型错误（`Gen` vs `MethodVisitor`） | **响亮**，编译期 |

**共同的结构性事实**：本批的错误分两类——**编译期错误（响亮，零风险）**和
**诊断变化（静默，只有刀 0 看得见）**。发射字节的变化几乎不可能悄悄发生，因为
五个外部语料 + 13 份 flat dump 从两个角度盯着它。所以刀 0 的语料覆盖率
**就是本批的真实安全边际**。

## 6. 不做的（记录理由）

### 6.1 `lowered-ir-design.md` §3.2 的六组件——退役

`SymEnv` / `TypeEnv` / `EffEnv` / `TraitEnv` / `JavaResolver` / `DiagSink` 那张表
**判为不执行**，理由三条，全部实测：

1. **收窄不了签名**。`check_fn` 家族五个入口的传递可达字段是 **41/47**——body 检查
   是一个整体，切成六份不会让任何一个函数少收一个字段。
2. **`DiagSink` 的漏斗已经存在**。`diags` 全仓 **253 读 / 3 写**，那 3 个写点就是
   `cerr`/`cerr_h`/`cerr_o`。把它变成子记录只换来 47→44 的**算术**；若真要让它变成参数，
   245 个 `cerr` 调用点全部要改成 `Cx { ..cx, diag: cerr(cx.diag, …) }`。
3. **表本身已经烂了**：`reported_key_types` 在 4ae6b61 上零命中；字段数写的是 46
   （实为 47）。而 `src_path` 被它划进 `DiagSink`，实测 `src_path` 与 `local_traits`
   的共现相关度（0.60）高于它与 `diags` 的——因为孤儿规则报错要说清 impl 在哪个文件。
   **`src_path` 是身份不是输出。**

`lowered-ir-design.md:182-183` 的那条非目标（「不要趁机改 `Cx` 的不可变记录风格」）
**继续有效，且现在有语言层面的理由**：Dawn 没有 `&mut`、没有嵌套更新糖、lambda 不能捕获
`var`，想改也改不了。

### 6.2 逐条

- **checker 的 Java 簇不拆**（`java_classes` + `jsig` + `checker.dawn:5889-6585`）：
  `check_java_call`(:8523) 就在 19 函数 SCC 里面，拆它要么把 body 检查一起拖走，
  要么用函数值破环（`jsig.dawn:44-55` 的形状），代价是被穿过去的函数失去名字与 go-to-def。
  J 簇的边界确实最干净（Jaccard 0.38，外部触点只有 analyze/interp/jfold），但那是
  **字段**干净，不是**调用图**干净。
- **`mv` 不整体移出 `Gen`**：266 处读、39 个函数，收益是删掉 `scratch_mv()`
  （`emit.dawn:1372-1378`，一个每模块造一次又丢掉的 `dawn/tool/Scratch` ClassWriter）。
  不换。A3 只搬那 10 个**本来就不需要 `Gen`** 的函数，`scratch_mv` 留着。
- **`Gen` 不三分**：见 §2.4 的三行签名对比。
- **`slots`/`syms` 不改成每方法清空**：会改 map 内容，要单独证明发射字节不变，
  收益为零。按 `gen_cbody` 的**实际行为**归类即可。
- **`emit_module` 的 TModule/LMod 位置对齐不碰**（`emit.dawn:1484-1491`）：改成
  「按 Core 遍历 + 查 TAST 边表」会**改方法进 class 的顺序**，而
  `selfhost-codegen.md:210-213` 明确记着发射序影响字节。非目标。
  （顺路发现，**本批不修**：`:1485` 的 `lm.fns[fi]` 在长度检查**之前**取下标——
  若 `lm.fns` 短于 `tm.fns`，得到的是越界而不是那句 panic。改它会改 panic 文本
  = 改 CLI 输出，单独立案。）
- **不抽 `consts`/`blocks` 到跨后端共享模块**：见 §2.2 末。
- **#122 不进这批**（P6）：`nid` 从 2 变 6 会让 std 起的整条 id 链平移 +4，波及
  `scripts/core-golden/std.*.core` 十份全文 golden 与 `calc/eqhash/traits.core` 里的
  `AdtNNNN` 字面量——**恰好毁掉 §5.1 里 checker 侧唯一完好的那半边证明**。
- **不在批次内改 `selfhost-core-diff.sh`**：见 §5.2 末。
- **不为 A1 开「先于 v0.47.0」的特例**：见 §5.3 末。

## 7. 决策点汇总

前十条是两份勘察备忘录的决策点，后八条是本文新增。

| # | 问题 | 裁决 | 一句话理由 |
|---|---|---|---|
| D1 | 本批的机器证明用什么 | 自建刀前/刀后五语料逐字节对拍 **+** 刀 0 诊断 golden；每刀小到能人眼评审 | 单靠现有门禁不成立：emit 半边被通配声明豁免、`selfhost.sha` 每刀 `--record` |
| D2 | 先发 v0.47.0 吗 | **是，且是开工前提** | 通配豁免把「红灯」的定义改掉了（§5.3） |
| D3 | 拆多模块还是拆记录 | **两个都做，但分工不同**：模块拆到位，记录只切两刀（`Frame`、`GenCtx`） | 在 Dawn 里模块拆分对调用点零代价，记录拆分每个写点加一层。它们不是同一件事 |
| D4 | `Cx` 定义放哪 | 新建 `cx.dawn` | 唯一能让子模块真正持有 `Cx` 的形状；代价是 9 行下游 `use` 同批改 |
| D5 | 第一刀切哪 | Lane A 起于 A1，Lane B 起于 B1 | 都是纯搬运，都被最强证明覆盖 |
| D6 | `selfhost.sha` 每刀 `--record` 怎么办 | 归一化全量 Core 不变量（**实测 0 差异 / 负控 4 行**）+ 强制人工核对 `--record` diff | §5.2 |
| D7 | 先建诊断语料吗 | **是**（刀 0，已在做） | 245 个 `cerr` 点今天只有 88 个内联 test 看着 |
| D8 | #122 同批吗 | **否** | 会毁掉 flat dump 那半边唯一完好的证明 |
| D9 | `Frame` 装几个字段 | **恰好 8 个**，逐字等于今天的 `EffFrame` | 多一个字段就改变 `leave_isolated` 的恢复集，而那是**只影响诊断**的静默变化（§5.4） |
| D10 | `DiagSink` 拆吗 | **不拆** | 漏斗已经是那个抽象（253 读 / 3 写，写点就是 `cerr*` 三个） |
| D11 | checker 的 Java 簇拆吗 | **不拆** | `check_java_call` 在 19 函数 SCC 里 |
| D12 | ARCH-01 必须在 ARCH-02 之前吗 | **否，两条 lane 并行** | `emit.dawn` 是叶子，与 checker 零耦合；文档里的顺序是排期不是依赖 |
| D13 | `Gen` 二分还是三分 | **二分**（`GenCtx` 只读 + `Gen` 可变） | 只读的那半边不进返回值，元数不涨；三分会让三个函数返回三元组换不到任何收窄 |
| D14 | `slots`/`syms` 不重置怎么办 | **按实际行为归到可变 `Gen`**，不改语义 | 改 map 内容要单独证明，收益零 |
| D15 | `own_fns` 删还是留 | **删，且是独立一刀（A2）** | 混进结构重排会污染爆炸半径读数 |
| D16 | B2 的 `changed` 集怎么定 | **先在丢弃分支上实测，再写进提交信息** | 9 个 importer 里哪些的 Core 真会变，事前不可推断 |
| D17 | 归一化不变量要不要进门禁脚本 | **否，本批以临时命令跑** | 在门禁正当门禁的时候改门禁 |
| D18 | 给 A1 开「先于 v0.47.0」的特例吗 | **否** | 一个批次两套开工规则，评审时记不住 |
| D19 | `lowered-ir-design.md` 说的「前提是先有 lowered IR」还成立吗 | **已满足，前提解除** | Core IR 随 native 计划 Phase 0 落地，三处漏进 emit 的 lowering 已全部关闭——逐行核对见 `core-move2-design.md:35-60`（该核对做在 `77d7aa4` 这个基线上，`77d7aa4` 本身是种子推进提交，不是关闭它们的提交）。emit 残余的 TAST 依赖是「关于**类**的问题」（方法名/描述符），不流经 `Cx`（`emit.dawn:1408-1412`） |

## 8. 收尾：文档校正清单

C1（开工前，把数字改对）与 C2（收尾，把结论回填）两刀。

**C1 —— 数字与过期待办**

| 文件 | 行 | 改什么 |
|---|---|---|
| `docs/codebase-audit.md` | ARCH-01 段 | checker `7,924` → **11,308** 行；`Cx` `44` → **47** 字段；`checker.dawn:76-132` → **`:91-164`**；「前提是先有 lowered IR」→ 标注 **已满足**（D19）；六组件建议加一行「已被 `arch-split-design.md` 复测取代」 |
| `docs/codebase-audit.md` | ARCH-02 段 | `emit.dawn` `3,531` → **2,534** 行；`Gen` 在 `:159` / 30 余字段 → **`:92` / 21 字段**；补一句真实盘子 = `codegen.dawn` 3,425 + `emit.dawn` 2,534，**`class_table`/`case_table` 是生成的 Unicode 数据表，不是后端模块** |
| `docs/audit/README.md` | :68, :72, :150 | 删掉与 ARCH-02 并排的 **error-model C2（`LProtect`）**——已于 2026-07-31 关档「不做」，`bracket` 以运行时 intrinsic 落地（v0.39.0, `79e205b`），JVM 侧是 `codegen.dawn:1083 gen_bracket(cw: AdtClassWriter)`，签名里没有 `Gen`（P7 的顺路项） |
| `docs/audit/README.md` | :150 表 | 「ARCH-01 ──► ARCH-02」串行 → **无技术依赖，可并行**（D12），并指向本文 |
| `docs/audit/lowered-ir-design.md` | §3.2 | 整节标注「**被 `arch-split-design.md` 取代**」；`46 字段` → 47；删 `DiagSink` 里的 **`reported_key_types`**（该字段已不存在） |
| `docs/audit/lowered-ir-design.md` | §七 E/F 行 | 指向本文 |
| `docs/audit/re-audit-2026-07-30.md` | :389 | `pass_register_impls` `388 行` → **461 行**（`:2780-3240`；`:3241` 是空行、`:3242` 已是下一个函数的文档注释） |
| `docs/README.md` | 索引 | 新增本文一行（`docs/audit/` 那组的邻居，状态 proposed） |
| `docs/runtime-intrinsics-design.md` | :3 | 状态头写「规划中，未实现」与 `docs/README.md:30` 标的 `current` 冲突，顺路统一（可选） |

**C2 —— 收尾回填**

- 本文状态行 proposed → 已落地，并在各节末尾记落地与设计的偏差（体例同
  `prelude-namespace-design.md` §6）。
- `docs/codebase-audit.md` 的 ARCH-01/ARCH-02 由「待办 —— 认可」改成「已处置」，
  指向本文；把本文 §6 判为不做的几条原样记进去（它们是审查建议的**否决**，
  不写下来下一轮审查会重新提一遍）。
- `docs/audit/README.md` 第 3 批表里划掉 ARCH-01/ARCH-02。
- 按 CONTRIBUTING §四，若刀数最终超出本文预估，另开 progress 文档回填提交哈希。

## 9. 附：本文引用的实测

| 事实 | 怎么测的 |
|---|---|
| 归一化全量 Core 不变量：389,288 行 / 0 差异；未归一化 94 行；负控 4 行 | 4ae6b61 worktree + `arch02-split-experiment.patch`，`bin/dawn __lower --dump` 前后各一次，§5.2 的 `norm` 函数 |
| `Cx` 47 字段 @ `:91-164`；`Gen` 21 字段 @ `:92-128` | 直接数 |
| `reported_key_types` 零命中 | `grep -rc` 全 `selfhost/src/` |
| 12 个 pass 的传递闭包 67 函数、body 半边 162 函数、交集为空 | 按列 0 声明切段、只从 `fn` 段取调用边（`test` 段丢弃）后传递闭包 |
| mv-only 是 10 个不是 21 个 | 逐函数看 `g.<field>` 与被调函数是否也收 `g` |
| codegen 天真切分会成环 | 逐个符号数 region↔head↔tail 的引用；region → tail 引用数为零 |
| prev-diff 对模块拆分不可见 | ARCH-02 勘察在真实拆分源上跑 `selfhost-prev-diff.sh`，全绿，`jvmhelp.class` 两侧都有 |
| `EffFrame` 是 `Frame` 的手工同义词 | `checker.dawn:5322-5380` 直读 |
| `Emit-Change(emit *)` 正在生效 | 在 4ae6b61 上跑 prev-diff，六条 emit 全 `NOTE` |
