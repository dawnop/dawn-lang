# Perceus 设计（S4 Phase 4）

> 对应 [`native-backend-plan.md`](native-backend-plan.md) §4 Phase 4。那里三段话定了
> 方向（精确 RC + 复用分析、非原子、无环回收器、必配 `--rc=leak`）；这份是动码前的设计，
> 把「往哪个对象上加计数、drop 怎么递归、掩码放哪」这些真正要裁的东西写下来。
>
> 为什么值得先写：RC 是**改 ABI**，不是加 pass。运行时每个堆对象的形状都要变，
> 两个后端的 Core 层要同时承认它，而错一次的现象是「随机的、跟输入相关的段错误」——
> 是这个仓库到目前为止最难二分的一类 bug。§7 的 `--rc=leak` 就是为它准备的。

## 1. 度量：这件事到底要盖住什么

不是估的。把 `dawn_alloc` 按调用点分类，跑一遍整编译器的前端（lex + parse + check
`selfhost/src/checker.dawn`，296 KB 源码）：

| 类别 | 次数 | 字节 | 占比 | 均值 |
|---|---|---|---|---|
| **array** | 63,471,619 | 1,894,458,792 | **56.2%** | 30 B |
| **adt** | 28,141,923 | 1,335,685,992 | **39.7%** | 47 B |
| box | 6,248,771 | 99,980,336 | 3.0% | 16 B |
| clo | 2,089,581 | 33,946,528 | 1.0% | 16 B |
| str | 226,287 | 2,805,938 | **0.1%** | 12 B |
| bytes | 61 | 1,773,568 | 0.1% | |
| dict | 0 | 0 | 0% | 全是静态全局 |
| **总计** | **100,178,242** | **3,368,651,154** | | |

三条结论，每条都改了这份设计的形状：

**（一）`dawn_str` 不进 RC。** 字符串占 **0.1%**。`dawn_str` 是按值传的 `{const char*, int64}`，
缓冲区没有主人——要管它就得在缓冲区前面加头、改掉每一个 `dawn_str_lit`、并区分「字面量
不能 free」和「concat 结果能 free」。为 0.1% 做这个不值。**结论：字符串继续泄漏，
写进契约而不是留成待办。** `dawn_bytes` 同理（0.1%，61 次）。

**（二）真正要盖的是 array 和 adt，96%。** array 的均值只有 30 字节——烧的不是大缓冲区，
是**持久向量的包装节点 churn**：S3 之后 List/Map/Set 全建在 Array 上，每次结构共享更新
都是一次 `dawn_array` + 一次 `dawn_array_buf` + 一次 data 数组。

**（三）活集与分配量差 2600 倍。** checker.dawn 在 JVM 上 full GC 后占用 37 MB
（SerialGC `-Xmx96m`，`90M->37M`），而 native 分配 3.37 GB。**几乎 100% 是垃圾。**
这条同时否掉了一个便宜的替代方案：per-compilation-unit 的 arena 在这里买不到任何东西，
因为整个编译器跑就是一个编译单元，arena 永远不会 reset。

## 2. drop 怎么递归：一处被实测推翻的判断

### 2.1 原判断（错的）

先想的是 Koka 的做法：**编译器为每个构造器发一个专属 drop 函数**，它知道字段类型，
逐字段递归。Koka 就是这么做的，看起来直接照抄即可。

### 2.2 为什么在 Dawn 上不成立

Dawn 不是单态化，是**字典传递 + 擦除**。看一个泛型函数：

```dawn
fn last[T](xs: List[T]) -> Option[T]
```

编译出来只有一份代码，`T` 的位置是 `void*`。当 `xs` 的最后一个引用在这里消失、
需要 drop 时，**这份代码不知道 `T` 是什么**，因而叫不出「T 的 drop 函数」。
Koka 不撞这堵墙是因为它的 boxed 表示里每个堆值自带一个能查到 drop 的头。

所以 per-constructor drop 要能用，前提是**从值本身能查到它的 drop 函数**——那就是
在头里放一个函数指针。而那已经是「头里带类型信息」这个方案了，只是多绕一层间接。

### 2.3 结论：公共头 + 字段指针掩码

**每个堆对象带一个公共头**，`drop` 是**一个通用函数**，靠头里的 `kind` 分派到怎么递归：

```c
typedef struct {
  int32_t rc;
  int32_t kind;   /* DAWN_K_ADT / _CLO / _ARRAY / _ARRAY_BUF / _BOX */
} dawn_hdr;
```

递归进 ADT 字段还差一件事：**槽是擦除的**，`dawn_adt` 今天不记哪个槽是指针、
哪个是内联标量。补一张**字段指针掩码**（bit i 置位 ⟺ 字段 i 是要 drop 的堆指针）。

这张掩码**不需要任何新信息**：`emit_alloc`（emitc.dawn:479）已经拿着
`args: List[CExpr]`，每个 arg 的 `cex_ty` 决定了 `slot_of` 选哪个 union 成员——
掩码就是同一条规则的物化。规则是：`c_repr(ty) ∈ {RAdtPtr, RCloPtr, ROpaque}` ⟹ 置位。
`RInt64/RFloat64/RBoolean/RUnitV/RString` ⟹ 不置位（`RString` 不置位正是 §1 的结论一）。

### 2.4 掩码放不下：41 个字段

整编译器发出的 C 里，`dawn_adt_new` 的最大字段数是 **41**（75 处），闭包最大捕获 23。
**`uint32_t` 掩码不够**，这一条是量出来的，不是猜的。

裁决：**`nfields <= 64` 用内联 `uint64_t`，更宽的用一个指向静态掩码数组的指针**，
两者共用同一个 union 槽，`nfields > 64` 是判据。宽 ADT 在今天的语料里一个都没有，
但用户代码写得出，所以不能把 64 当成语言上限。

```c
typedef struct {
  int32_t rc;
  int32_t kind;
  int32_t tag;
  int32_t nfields;
  union {
    uint64_t narrow;          /* nfields <= 64 */
    const uint64_t *wide;     /* 否则，指向 emitc 发的静态常量 */
  } ptrmask;
  dawn_slot fields[];
} dawn_adt;
```

头从 8 字节涨到 24 字节。ADT 均值 47 字节（≈2.4 个槽），所以 ADT 那 1.34 GB 会涨约
34%、总分配涨约 13%——**在一个要砍掉 96% 的方案里，这不是一个需要优化的数字**。
（能压：`kind` 只要 3 位、`nfields` 塞 29 位、`tag` 16 位，头可以回到 16 字节。
记在这里，但不为它设计——先把正确性做出来。）

### 2.5 Array 不需要掩码

`dawn_array_buf.data` 是 `void **`，**每个元素都是堆指针**（`array_get` 交回
`CUnbox` 要解引用的东西，`array_push` 收 `CBox` 刚产出的东西）。统一表示 ⟹ 无掩码，
drop 一个 buf 就是对 `data[0..high)` 逐个 drop。

`dawn_array` 与 `dawn_array_buf` 是**两个独立计数的对象**：多个版本共享一个 buf，
这正是持久向量的结构共享。buf 的 rc 是「有几个 `dawn_array` 指着我」。

### 2.6 为什么 `kind` 是必需的，不是方便

擦除位置上的 `void*` **不是统一的盒子**。看 `box_call`（emitc.dawn:432）：

```dawn
    RInt64 -> "dawn_box_int(" ++ v ++ ")"      # 分配一个盒子
    RAdtPtr | RCloPtr | ROpaque -> "((void*)(" ++ v ++ "))"   # 已经是指针，不分配
```

标量装箱，引用**直接转型**。所以数组里的一个 `void*` 可能是盒子、可能是 `dawn_adt*`、
可能是 `dawn_clo*`。通用 drop 唯一能问的就是头里的 `kind`——这一条把它从
「三选一的实现风格」变成了**唯一可行的做法**。

### 2.7 盒子要变成真的结构体

今天 `dawn_box_int` 返回裸 `dawn_slot*`，`unbox_expr`（emitc.dawn:201）直接
`((dawn_slot*)(v))->i`。加了头之后这个转型就错了，盒子得是：

```c
typedef struct { dawn_hdr h; dawn_slot val; } dawn_box;
```

`unbox_expr` 相应改成读 `->val.<slot>`。**头必须在偏移 0**——放到指针前面
（`((dawn_hdr*)p)[-1]`）会让 ADT 和盒子的头位置不一致，通用 drop 就没法统一寻址了。

### 2.8 `dawn_bytes` 也要头

`c_repr(TyBytes) = ROpaque`（emitc.dawn:166）⟹ `Bytes` 在槽里是指针 ⟹ 掩码会标它
⟹ `dawn_drop` 会收到 `dawn_bytes*`。所以它必须有头、必须有 kind。
**它的 `p` 缓冲区仍然泄漏**（§1 结论一），被 free 的只是那个 24 字节的结构体本身。

## 3. 不朽对象

有三类堆形状的东西永远不该被 free，dup/drop 必须对它们是**无害的**而不是被调用方
小心避开——避开是靠不住的，Core 层的所有权分析看不见「这个值恰好是个静态字典」。

| 东西 | 处理 |
|---|---|
| 字符串字面量 `dawn_str_lit` | 不是堆对象，压根没有头，不参与 |
| Unicode 表 / case 表 | 同上，静态数组 |
| `static dawn_dict dawn_dict_1_String = {...}` | **整个字典家族退出 RC**，见下 |

```c
#define DAWN_IMMORTAL INT32_MAX
```

`dawn_dup`/`dawn_drop` 都先测 `rc == DAWN_IMMORTAL` 并直接返回。留着这个哨兵是因为
以后会有别的不朽形状（比如 interned 常量），一次比较换掉一整类推理。

**字典不加头。** 先想的是给 `dawn_dict` 也加头、静态的初始化成 `DAWN_IMMORTAL`。
但那要改 `DAWN_DICT_MAX` 的结构和 emitc 写出的**每一个**静态初始化式，而收益是零：
字典在整编译器的前端跑里分配了 **0 次**（§1），全是静态全局。

改成**结构性排除**：`CFun.dicts` 在 Core 里本来就是与 `params` 分开的一个字段
（`core.dawn`），字典类型的表达式也认得出来，所以刀 2 的所有权分析可以直接跳过它们，
不需要运行时帮忙。代价：`dawn_dict_new` 造出来的参数化字典会泄漏——0 次分配，
写进契约而不是留成待办。

## 4. 原语表

```c
void *dawn_dup(void *p);        /* rc++，返回 p；NULL 与 IMMORTAL 是 no-op */
void  dawn_drop(void *p);       /* rc--，到 0 则按 kind 递归后 free */
bool  dawn_is_unique(void *p);  /* rc == 1，复用分析用（刀 4） */
```

`dawn_drop` 的递归按 `kind`：

| kind | 递归 |
|---|---|
| `_ADT` | 按 `ptrmask` 逐字段 `dawn_drop` |
| `_CLO` | 按捕获掩码逐个 `dawn_drop`（同 ADT，闭包环境也是擦除槽） |
| `_ARRAY` | drop `buf` |
| `_ARRAY_BUF` | 对 `data[0..high)` 逐个 drop，再 free `data` |
| `_BOX` | 直接 free（装的是标量；引用位置根本不走 box，见 §2.6） |
| `_BYTES` | free 结构体，**不** free `p`（§2.8） |

> `_ARRAY_BUF` 递归到 `high` 而不是 `len`：`len` 是某一个版本的长度，
> `high` 是这个 buf 曾经交出过的槽位上界，也就是它真正持有的东西。

**递归深度**：drop 一条 10 万节点的链会递归 10 万层，栈会炸。这不是理论问题——
persistent vector 与 HAMT 都是深结构。**必须用显式工作栈而不是 C 递归**，
在 `dawn_drop` 里就地实现（一个 `void**` 栈，初始容量小、按需翻倍）。
这一条写在这里是因为它极容易被漏掉，而它的现象是「大输入下随机段错误」。

## 5. Core 层：dup/drop 落在哪

节点已经有了，且**零构造点**：

```dawn
  | CDup(inner: CExpr, ty: Ty)   # CExpr
  | CSDrop(sym: Int)             # CStmt
```

（原来两个都是语句。写 pass 的时候发现 dup 那个形状不成立——`f(p.x)` 里要计数的是
`p.x`，它没有名字，直到 let 执行完才有；作为语句它在表达式内部也无处可放。所以
dup 改成了表达式，drop 留作语句：drop 永远发生在作用域出口、永远点名一个绑定。）

参数模式也有了，且 `CBorrowed` 从未被构造（`core.dawn:218`，lower 的七处
`CParam { ... }` 全标 `COwned`）。所以刀 2 不是「加节点」，是**让这两组已声明的
东西第一次有值**。

规则（Perceus 论文的标准形，Dawn 的纯性让它可解）：

1. **每个 owned 参数在函数体末尾要么被消费、要么被 drop。**
2. **一个变量被用了 n 次（n ≥ 2），在前 n−1 次使用点前各插一个 `CDup`。**
   最后一次使用把所有权交出去。
3. **分支要平衡**：`if`/`match` 的各臂对同一个变量的消费必须一致，不一致的臂补 drop。
4. **borrowed 参数不 dup 也不 drop** ——调用方保证它在调用期间活着。
   这是把「只读一下就扔」的常见形状从 dup/drop 对里救出来的那一格。

Dawn 的纯性给了两个便宜：**严格求值 + 不可变 + 无可变别名 ⟹ 构造不出环**，
所以朴素 RC 是完备的，不需要环回收器；**单线程 ⟹ 非原子计数**，`rc++` 就是 `rc++`。

### 5.0 这个 pass 只跑在 C 那条路上

原计划是无条件跑，靠「JVM 后端忽略这两个节点」拿零 Emit-Change。实际写下来是
**只在 `__emitc` / `__lower` 这条路上跑**（`main.dawn`，JVM 的 `build` 路径不碰），
两个理由：

1. **JVM 有回收器**，在那边数引用是纯开销。RC 是 native 后端的事，pass 就该挂在
   native 后端前面。
2. **只有这样，pass 才能造绑定**——而它必须能造。两个地方绕不开：

   - **块尾的 drop 无处可站。** `CBlock(stmts, tail, ty)` 的 tail 按构造就是最后一个
     东西，「tail 之后」这个位置在 Core 里不存在。作用域的 drop 必须在 tail 求值
     *之后*跑，所以 tail 得先有名字：`{ stmts; let t = tail; drop ...; t }`。
   - **借用位上的 owned 临时值会漏。** §5.1 定了运行时原语借用，那么
     `list_len(f(x))` 里 `f(x)` 那个新表就没人放——原语不 drop 它，调用方也不认识它。
     它得有个名字和一次 drop。

   插 `CDup`/`CSDrop` 对 JVM 是零字节（两个后端都直接透传），插 `CSLet` 不是。
   跑在 C 专用路径上，这个矛盾就不存在了。

于是「JVM 零 Emit-Change」从一条要验的门禁变成了**构造性的事实**。仍然验了一遍：
`examples/calc.dawn` 的 jar 与不带这个 pass 时逐字节相同。

### 5.1 调用约定：两条，不是一条

刀 1 给运行时原语定了**借用**（头里写着：参数是借的，留下什么自己 dup）。
Dawn 函数不能照搬——**刀 4 的出口条件要求它是 owned**：

`array_with(a, i, x)` 要就地写，得知道 `a` 唯一。如果参数是借的，调用方手里那份
引用还在，`rc >= 1` 永远成立，被调方**永远看不到 `rc == 1`**。唯一性只有在
调用方把所有权交出去之后才成立。所以 Perceus 的复用分析和 owned 参数是同一件事，
拆不开。

于是：

| 谁 | 参数 | 理由 |
|---|---|---|
| Dawn 函数 | **owned** | 刀 4 的唯一性判据依赖它；`CParam.mode` 本来就是为它准备的 |
| 运行时原语（`CIntrinsic`） | **borrowed** | 50+ 个手写 C 函数各自负责正确 drop，是最难查的那类 bug 的最大来源面 |

这不是妥协出来的不一致，是 Koka 也有的形状——它同样按函数标注 borrowed/owned。
`CMode` 存在的意义就是承载这个区别，而 `types.Intr` 那张「声明属性」表
（`rt` / `erased` / `internal`）就是刀 4 给个别原语开 owned 口子的地方。
刀 2 只用整体规则，不动那张表。

### 5.2 插入规则：先要正确，不要最优

刀 2 只做**保守但正确**的那版：

> **在每个「消费性使用」前 dup，在每条离开作用域的路径上 drop 该作用域的全部绑定。**

消费性使用 = 值被交出去且对方会持有它：Dawn 调用的实参、`CCtor`/`CTuple`/
`CClosure`/`CListLit`/`CDictApply` 的操作数、`CBox` 的内层、`CReturn` 的值、
`CSLet` 的 init、`CSAssign` 的右值。**非**消费性 = `CIntrinsic` 的实参（借用）、
`CField`/`CTupleGet`/`CIsCtor`/`CTagOf` 的 target、`CIf` 的条件、`CBinary` 的操作数。

但**只有借用来源需要 dup**。一个刚构造出来的值（`CCall`/`CCtor`/`CIntrinsic` 的结果）
本来就带着自己那份引用，交出去就是转移，不必 dup。要 dup 的是那几个**产出借用**的
节点：`CLocal`、`CField`、`CTupleGet`、`CDictArg`，以及内层是借用的 `CUnbox`。
这也正是 `CDup` 必须是表达式而不是语句的原因——`f(p.x)` 里要计数的是 `p.x`，
它没有名字。

> `CConstRef` / `CComptime` 不在这张表里，查过了：C 侧 `const_literal`
> 只认标量，结构化常量直接 panic「native cannot rebuild yet」。所以到得了 C 后端的
> 常量一定是标量，`is_ref_ty` 一定是 false，怎么归类都不会 dup。等结构化常量能落地时
> 这条要重看。

这条规则的正确性不需要活跃性分析：

- 一个绑定被消费 n 次 ⟹ n 个 dup + 作用域末 1 个 drop。交出去 n 份、自己那份还掉。
- 一次没被消费 ⟹ 只有那个 drop。
- **返回值也是它管的**：`return x` 先 dup（消费性），再 drop 掉包括 `x` 在内的
  全部绑定，净效果是引用数不变、交出去的是那个 dup。返回不需要特例。

**不最优在哪**：最后一次使用本该直接转移所有权，这版仍然 dup 一次再 drop 一次。
那是「最后使用分析」，是刀 2 之后的细化，不是刀 2 的内容。先让它对。

**求值顺序是要守的。** 借用位上的 owned 临时值要提成绑定（§5.0），而提出来的绑定
跑在整个节点之前——于是它就跑到了写在它前面的操作数**之前**。`f(g(), h())` 里
`h()` 要提，`g()` 不提，两个调用就换了顺序。所以规则是：**一旦有一个操作数要提，
整排都提**，按原顺序。多几个临时名字，换顺序不变。

**借用的根必须是局部变量。** `p.x` 借的是 `p`，作用域替它活着；`g(y).x` 借的是一个
没人持有的临时值，那个投影一旦被当成借用就会在临时值 drop 之后被读到。所以
「产出借用」的判据是**投影链的根是 CLocal**，不只是「最外层是 CField」。

**赋值的顺序**：`CSAssign(sym, v)` 展成 `let t = v; drop sym; sym = t`。先算后放——
`s = s ++ "x"` 里新值读了旧值。

### 5.3 非局部退出是这一刀的难处

`CReturn` / `CBreak(id)` / `CContinue(id)` 会跳过作用域末尾的 drop。所以要维护一个
**作用域栈**，每层记该层拥有的 sym：

| 出口 | 要 drop 的 |
|---|---|
| 正常走到作用域末 | 该层 |
| `CReturn` | 函数内**全部**层 |
| `CBreak(id)` | 到该 loop 的 body 层为止的所有层 |
| `CContinue(id)` | 同上（`step` 在 drop 之后跑，它读的是循环外的变量） |

`CSAssign(sym, v)`：先求 `v`（消费性 ⟹ dup），**再 drop `sym` 的旧值**，最后写入。
顺序是有讲究的——`s = s ++ "x"` 里新值已经持有了自己的引用，先算后 drop 才安全。

### 5.4 字典按结构跳过

`CFun.dicts` 是与 `params` 分开的字段，字典类型的表达式（`CDictRef`/`CDictApply`/
`CDictArg`）也认得出来。这一族整个不进所有权分析——§3 说过为什么它们不在 RC 里。

### 5.5 局部 oracle：平衡检查器

刀 3 之前没有任何东西读 dup/drop，所以这个 pass 的 bug 会一直隐身，然后在刀 3 里
和一堆 codegen bug 缠在一起——正是 `--rc=leak` 想拆开的那种纠缠。所以刀 2 自带
`rc_check`：走一遍产出的 Core，断言

- 每个绑定在每条路径上恰好被 drop 一次（不多不少）；
- `if` 两臂对「放掉了什么」的答案一致；
- 循环体结束时的持有集合与开始时相同；
- `return` 除了正在交出去的那个值以外不留任何东西。

它看不见的那一半是「dup 数是否等于消费性使用数」——那要每个接收者的类型，语料是
刀 3 的运行时。

**它当场就有用**：第一次跑，62 个模块里 50 个红。最后定下来的形状里，其中六类是
检查器自己太朴素（把 `let t2 = t1` 当成了转移、不认返回值也是一种转移、在必然跳走的
语句之后继续走死代码），一类是 pass 真错了——`wrap` 把一个 `continue` 埋进无尾块，
`diverges` 就看不见它了，而 C 后端正是靠 `diverges` 判断分支有没有值要赋，于是发出了
`dawn_str t = DAWN_UNIT;`。这一条是 `cc` 报出来的，不是检查器；检查器管的是平衡，
不管类型。

### 5.6 emitc 用 Dawn 函数实现的那几个 intrinsic

刀 3 上把整个语料打红的**只有一条**，而它把七个程序一起打红了：

Core 里 `len` / `get` / `list_index` / `list_slice` / `sort_by` / `range` 是 intrinsic，
`++` 是运算符——按 §5.1 两者都**借用**操作数。但 C 后端把它们实现成
**`std/pvec` 的 Dawn 函数调用**（S3 之后集合就是 std），而 Dawn 函数**拿走所有权**。
于是被调方 drop 了一份调用方从没交出去的引用：

```c
bool dawn_std_list__iter_done(void* v234, int64_t v235) {
  bool v400 = (v235 >= dawn_std_pvec__count(v234));   /* count 会 drop v234 */
  dawn_drop(v234);                                     /* 第二次 */
  return v400;
}
```

`show_go` 的循环第一轮就把自己遍历的那张表放掉了。**规则**：凡是 emitc 用 Dawn 函数
实现的 intrinsic/运算符，引用要在**调用点**取（`own_args`）。同理，返回值指向参数
内部的那几个（`array_get` / `expect` / `unwrap_or` / `cast`）也在调用点 dup，这样
「调用结果 owned」这条 Core 规则在 C 层才成立——放进运行时函数里不行，运行时自己也
调它们，那里要的正是借用。

闭包同理：`env->caps[i]` 交给的那个函数按 owned 参数收，会 drop 它。adapter 得先 dup，
否则第一次调用就把闭包自己指着的东西放掉了。

### 5.7 还没解决：字符串不计数

`is_ref_ty(TyString)` 是 false（刀 1 定的，理由是 §1 的分配次数普查里字符串占 0.1%）。
那是**次数**不是**字节**，而编译器是拼字符串的大户：ASan 开 leak 检测，一个 json_lib
跑下来 24 KB / 758 处。这一条对 native 自举是要还的债，但不属于任何一把刀——先记下。

## 6. 复用分析（刀 4）

`dawn_rt.h` 里已经把这一格写下来了：

> `array_with` 总是复制，这个不对称是设计而不是缺口：槽 `i < len` 已经交给过这个版本
> 也许还交给过别人，没有任何水位线能说谁还在读。**Perceus 能说（`rc == 1`），
> 以后可以把这条放开。**

出口条件是这句话的兑现：**`array_with` 在唯一时确实就地写**，用计数器验。

**但对照基准要重新量。** `native-backend-plan.md` §4 写的「对照 JVM 侧实测的 99.1%
快路径命中率」已经被同一份文档 §11.4 作废了：那 99.1% 是**另一个操作**、
在一个 D3 已经删掉的类上量的。照抄它等于拿一个不存在的东西当门禁。

替代：**在 `dawn_array_with` 里放一对计数器（就地 / 复制），先在 leak 模式下跑一遍
整编译器的前端拿到基线分布，再看刀 4 把多少复制转成了就地。** 门禁是「就地比例
显著大于零且内存下降」，不是一个抄来的百分数——这一格本来就是 native 相对 JVM
多出来的，JVM 上没有可比的数。

## 7. `--rc=leak`

`native-backend-plan.md` §6 R3 定的：**drop 全部 no-op 的调试模式**。
现象在 leak 模式下消失 ⇒ RC bug；不消失 ⇒ codegen bug。

这不是可选项，是刀 1 的交付物之一。理由：RC bug 与 codegen bug 的现象**完全一样**
（读到已经 free 的内存 = 读到没写对的内存 = 段错误或错答案），没有这个开关，
每一个 native bug 都要从零区分这两类。成本几乎为零——drop 的入口加一个全局标志位。

实现放在**运行时**而不是编译器：`dawn_drop` 开头 `if (dawn_rc_leak) return;`，
由环境变量或链接期常量控制。放运行时的好处是同一个二进制能两种模式各跑一遍，
不必重新编译——而重新编译会改变布局，正是要排除的变量。

## 8. 刀

| 刀 | 内容 | 门禁 |
|---|---|---|
| 1 | 运行时 ABI：公共头、掩码、`dawn_dup/drop/is_unique`、显式工作栈、`--rc=leak`；emitc 侧同步改 `unbox_expr`（§2.7）与 `emit_alloc`（发掩码） | 语料全绿（此时还没人调 dup/drop，纯粹验 ABI 改动没打坏东西）+ 整编译器仍能发 C 并与 JVM 逐字一致 |
| 2 | Core pass：所有权推断 + `CDup`/`CSDrop` 插入（§5.2 的保守版） | **JVM 侧零 Emit-Change**（§5.0 之后是构造性的，仍验了 calc 的 jar 逐字节相同）；平衡检查器在 std + 编译器 + site + 五个包共 168 个模块上全绿；语料仍全绿 |
| 2b | 最后使用分析：把「dup 一次再 drop 一次」收成一次转移；`CBorrowed` 第一次有值 | 同上，且 dup/drop 计数显著下降 |
| — | 刀 2 落地后 Core golden 不只多了 dup/drop 行，还多了绑定（§5.0）。这是原计划没预见的，已重录 | |
| 3 | emitc 消费两个节点 | **完成**：语料 23 个程序全绿，且新增 `asan` 一档（每个程序再用 AddressSanitizer 编译跑一遍）；整编译器前端 native 跑通、与 JVM 答案一致，`checker.dawn` 峰值内存 **4.4 GB → 1.42 GB** |
| 4 | 复用分析（`rc == 1` 原地写） | `array_with` 就地命中率计数器 |

刀 1 与刀 3 之间语料必须一直是绿的：刀 1 只改形状不改行为，刀 2 只改 Core 不改 C，
**第一次真正开始 free 是刀 3**，所以刀 3 是唯一一个「跑起来会段错误」的位置。
这是故意的——把风险压到一刀里，比三刀各担一点更好二分。

**2b 让到了 3 后面**，理由是同一条：刀 3 是唯一会段错误的那一刀，它该建立在已经被
平衡检查器验过的最保守版本上，而不是再叠一层最后使用分析。真出事时候选只有一个。
事后看这条挑对了——刀 3 打红的那一条（§5.6）与所有权推断无关，如果 2b 也在里面，
分诊要多一个方向。

## 9. 风险

- **R1 — drop 的深递归炸栈。** 见 §4 末。缓解：显式工作栈，且刀 1 就要有一个
  「构造 10 万节点的链再丢弃」的语料。
- **R2 — 掩码与 `slot_of` 分岔。** 掩码是 `slot_of` 那条规则的第二份物化，
  两份就会分岔（这个仓库刚在 S1 上花过一整轮收「一件事有几份定义」）。
  缓解：**掩码从 `slot_of` 派生，不另写判断** —— emitc 里让两者读同一个函数。
- **R3 — 静态字典漏掉 IMMORTAL。** 现象是 free 一个 `.data` 段的地址，直接崩。
  缓解：`dawn_drop` 里对 `rc <= 0` 断言，debug 构建下打印 kind 与地址。
- **R4 — 与 `array_push` 的水位线规则冲突。** `buf->high` 说「这个槽从没属于过任何
  版本」，rc 说「有几个人指着我」——两条独立的唯一性判据，刀 4 要把它们对齐而不是
  各说各话。缓解：刀 4 之前不动 `array_push`。
