# Perceus 设计（S4 Phase 4）

> 状态：**current** —— native 的内存管理设计，五刀（1 / 2 / 2b / 3 / 4）已全部落地，
> 关账记在 **§8 的刀表**（补充实测在 §5.7 字符串入账、§6.1 落地形状、§6.3 `CBorrowed` 了结）。
> 仍是该子系统的权威说明。
> （这行原本把关账记指到「§14.x」——本文只有 §1–§9，带 §14.x 的是
> [native-backend-plan.md](native-backend-plan.md)。）
>
> 对应 [`native-backend-plan.md`](native-backend-plan.md) §4 Phase 4。那里三段话定了
> 方向（精确 RC + 复用分析、非原子、无环回收器、必配 `--rc=leak`）；这份是动码前的设计，
> 把「往哪个对象上加计数、drop 怎么递归、掩码放哪」这些真正要裁的东西写下来。
>
> 为什么值得先写：RC 是**改 ABI**，不是加 pass。运行时每个堆对象的形状都要变，
> 两个后端的 Core 层要同时承认它，而错一次的现象是「随机的、跟输入相关的段错误」——
> 是这个仓库到目前为止最难二分的一类 bug。§7 的 `--rc=leak` 就是为它准备的。

## 1. 度量：这件事到底要盖住什么

不是估的。把 `dawn_alloc` 按调用点分类，跑一遍整编译器的前端（lex + parse + check
`selfhost/src/check/checker.dawn`，296 KB 源码）：

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
不需要运行时帮忙。

**「0 次分配」那个数字只对当年那个程序成立。** 它量的是编译器前端，那里的泛型主体
不带类型变量，所以 `dawn_dict_new` 一次都没被调到。tea-core 的 reconciler 推翻了它：
`Node[M]` 的结构相等要 `Eq[Node[M]]`、`Eq[List[Node[M]]]` 这种「字典的字典」，
而那正是 `dawn_dict_new` 唯一负责的一类。counter 每 turn 造 28 个。

所以契约改成一句更窄的：**每种一份，永不释放**，不是每次一份。`dawn_dict_new` 按
(模板地址, 全部实参字典地址) intern，命中就共享同一个。共享是安全的：字典是它输入的
纯函数，返回后无人回写，指针也从不被当身份比较。表只增不删，但规模有界于程序的
实例化图，是类型结构的函数而不是运行时长度的函数。§3 其余裁决（不进 RC、不加头、
结构性排除）原样成立。

事故记录：2026-08-28 之前，任何不退出的 C 后端程序都在线性泄漏（tea-dom 的 counter
reactor 每 turn 约 4KB，10 万 turn 的 native 二进制 RSS 750MB）。三处量内存的地方
当时都是绿的且各有正当理由：LSan 被 `__lsan_ignore_object` 明确告知别看这一类、
`DAWN_RC_BALANCE` 只数进过 RC 的对象、`scripts/rc-contract` 的题面里没有字典。
补的两道门是 `scripts/wasm-dom-contract` 的平台期腿（问「跑久了停不停得下来」）
与 `scripts/rc-contract` 的 `dict_is_shared` / `dict_family_is_keyed`（问键写对没有；
后者是树内唯一能问的地方，因为没有程序会拿一个模板配两组不同实参）。

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

> `CConstRef` / `CComptime` 不在这张表里。原因写在 2026-08-02：那时 C 侧
> `const_literal` 只认标量，结构化常量直接 panic，所以到得了 C 后端的常量一定是标量、
> `is_ref_ty` 一定 false，怎么归类都不会 dup。
>
> **2026-08-04 重看（K-B5）**：结构化常量落地了，结论不变但理由换了一条。emitc 的
> `const_builder` 把折叠值建一次、放进函数内的 static 指针，整张图交给
> `dawn_immortal`——于是它和字符串字面量同类：dup/drop 在它身上是空操作。所以
> `rc.dawn` 的 `lit_immortal` 现在对**所有**类型的 `CConstRef`/`CComptime` 返回
> true，不再只对 `TyString`。两边必须同时改：只要发射端不再标 immortal 而这边还说
> immortal，第一次消费性使用就会释放掉 static 指针仍指着的那个常量。

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

### 5.7 字符串入账（2026-07-29 还清；曾题为「还没解决：字符串不计数」）

`is_ref_ty(TyString)` 曾是 false（刀 1 定的，理由是 §1 的分配次数普查里字符串占
0.1%）。那是**次数**不是**字节**，而编译器是拼字符串的大户——这笔债在五刀关账后
第一个还：LSan 扫整编译器前端，出口不可达 2.46 亿字节，全是没有主人的缓冲。

**表示法**：`dawn_str` 从 16 字节裸值（`{p, len}`，缓冲契约漏）换成计数对象——
头 + 长度 + `p`，堆字符串一块分配、字节紧随结构体；**字面量是发射器写的不朽静态量**
（`p` 指 .rodata 的 C 字面量，零拷贝、零计数流量，运行时自己的 panic 消息走
`dawn_str_lit` 复合字面量、借用即弃）。切片改复制（`cursor_slice` 交出的是 token
级小串；共享缓冲要第二个字才能从中段指针找回头）。**Bytes 缓冲随头释放**，§2.8
同一句契约一并了结。顺带的大头：`dawn_slot` 联合体里只有内联 `dawn_str` 是两字，
删掉后**每个 ADT 槽位从 16 字节减到 8**。

**判据翻转牵出三处缝**（每处都是「pass 与 oracle 要同一份定义」的续篇）：

1. **账本追踪绑定，不追踪值**。字面量初始化的绑定照常入账——对不朽头的 drop 是
   免费空操作，一条规则胜过两条；只有**字典**（无头，碰了就读垃圾）整体豁免。
   之前 pass 的 `immortal` 与检查器的 `chk_dict` 各判各的，`var s = ""` 的首次
   赋值就在两边的缝里：`dictish`（账本豁免）与 `lit_immortal`（操作数免计数）
   拆成两个判据，两侧共用。
2. **`CReturn` 的清账检查要看 `gone`**。TCO 把整个函数体包成 `return <Never 块>`，
   块尾 panic 处的死代码持有已在发散点被豁免——值本身发散的 return 永不执行，
   不该再要求 live 清空。
3. **`std_shim` 直通是漏**。`std/io.println` 曾被发射成对借用型 C 原语的直呼，
   跳过了本该消费 owned 实参的 Dawn 包装——Core 账面全平、发射毁约，检查器
   永远看不见，是 asan 档抓的（教训 2 的又一实例）。表已删，注释里那句
   「成品后端里该表消失」到期兑现。

**同一笔账里的隐形引用**（前置提交 fd7d423）：动态调用两端的标量箱子（owning
unbox 一族消费边界上的 wire 格式）、发射器列表字面量与运行时累积循环丢掉的中间
头（`dawn_array_push_own`）、`to_host` 跨界临时（join / from_code_points / io_run
改为消费方释放）。

**实测**（整编译器前端跑 `checker.dawn`，工作量与刀 4 完全一致——`array_with`
45.7 万次原样）：

| | 刀 4 后 | 字符串入账后 |
|---|---|---|
| 墙钟 | 2.77s | **2.10s（−24%）** |
| 峰值 RSS | 1.46 GB | **81 MB（−94%）** |
| LSan 出口不可达 | 2.46 亿字节（未启用检测） | **0 字节** |

峰值这一格推翻了 2b 的解读：「峰值由活数据主导」是错的——那 1.4 GB 的地板大头
是契约漏（字符串缓冲、code_points 数组、箱子）堆出来的，真实活数据只有 81 MB。

**门禁收网**：spike-native 的 asan 档 `detect_leaks=1` 常开（连 LeakSanitizer 的
banner 一起 grep，免得 panic 语料用退出码遮住泄漏）。设计内例外只剩一类：
带参字典在分配点 `__lsan_ignore_object`（无头、永活，是 §3 的裁决不是漏洞）。
第二类例外——**被接住的 fault** 漏掉 longjmp 丢弃的 C 帧所持引用，语料旁放
`<name>.leaks-on-catch` 标记单独关检测——已于 2026-08-08 到期兑现：#193 把
raise 改成强制 unwind、owned 槽位挂 cleanup（`docs/native-failure-design.md`
路线 A3），恢复不再泄漏，标记连同机制一起删除，每个语料对每个字节负责。

**未欠但记下**：`dawn_str` 无容量字段，重复 `++` 追加是 O(n²) 复制——与漏时代
行为持平，不是回退；唯一时 realloc 扩展 / builder 是将来复用刀的形状。

### 5.8 刀 2b：最后使用分析

规则叠在 §5.2 的保守版**上面**而不是替换它：**一个绑定的最后一次消费性使用直接
把值交出去**（裸转移，不 dup），同时把它从作用域除名，作用域末的 drop 随之消失。
「最后」由改写全程线程化的 **after 集**判定——之后还会被碰的绑定的集合。「碰」
刻意包含两种非读取：赋值的**目标**（`CSAssign` 展开里有一个 drop 旧值，早转移会让
它变成第二次释放）和 drop 的 sym。整个集合只朝一个方向过估：多一个 sym 多付一次
dup，少一个 sym 就是 use-after-free。

两个**拒绝转移**的位置，各对应一类「最后一次」不成立的执行结构：

- **循环**。循环外的绑定在体内的「最后一次使用」只是本圈的最后一次，下一圈还要读。
  `transferable` 从内向外找绑定的作用域，撞到 loop 作用域就停——循环体自己的绑定
  每圈新建，圈内转移无妨；外面的一律 dup。step 在 loop 作用域弹栈**之前**改写，
  护栏才罩得住它。
- **`&&` / `||` 的右侧**。右侧只在有时求值，一次发生一次不发生的转移无论把 drop
  摆哪儿都配不平，改写右侧时置 `pinned` 整体拒绝（`rw_scircuit`）。右侧内部自己的
  dup 与消费是一对、一起有条件，平衡不受影响。

**分支要调和**：两臂从同一作用域状态出发各自改写，一臂转移了的绑定，另一臂补
drop（`reconcile`）；单臂 if 物化一个只装 drop 的 else。发散的臂在自己的跳转处已经
按自己的路径清了账，不参与调和。

**这一刀自己的坑：C 的实参求值顺序是未定义的。** Core 从左到右求值，pass 按这个
语义给同一个操作数列表里的两次使用定了「先 dup、后转移」——Core 层完全正确。但
emitc 把实参拼成 C 表达式，gcc 实际从右往左跑：`show_go(dup(x), iter_start(x))`
先跑 `iter_start(x)` 把表释放，再 `dup(x)` 读已释放内存。刀 2 的输出撞不上这个缝
（dup 与 dup 可交换），**转移让参数求值第一次有了顺序**。修法是让操作数列表恢复
顺序无关：`consume_all` 的 after 集覆盖**同列表的其他所有操作数**（不只后面的），
与 `borrow_all` 同规则——代价是同一次调用里两次提到同一个绑定时两边都 dup，
只有跨顺序位（语句之间、语句与块尾之间）才有转移。这一条是平衡检查器**看不见**的
（它按 Core 的从左到右走查，那个语义下代码是对的），是 asan 档抓住的——刀 3 给
语料加的那道防线，第一个受益人是刀 2b。

**检查器跟着换了语义**：消费位上的裸局部 = 转移（从 live 除名），所以 `chk_expr`
带上了位置标志 `k`，镜像 pass 对消费位/借用位的分类；原来 return 值、块尾、赋值
右值三个手写特例被统一吃掉。「每个绑定每条路径恰好释放一次」的不变量不变，
「释放」的定义从「drop」扩成「drop 或转移」。

实测（静态计数）：整编译器 dup 30145 → 23596（−22%）、drop 26034 → 18193（−30%）；
语料程序 dup 约 −35%。`checker.dawn` 探针 3.45s → 3.00s，峰值内存持平
（峰值由活数据主导，不由瞬态引用对主导）。

**`CBorrowed` 不在这刀里，改判给刀 4。** §8 原来把它挂在 2b 下，但 `core.dawn`
里 `CMode` 的注释一直写的是「Phase 4's analysis is what makes Borrowed appear」——
两处本来就不一致，现在按后者裁：borrowed 参数是**调用约定**，调用方不 dup、被调方
不 drop，需要每个调用点知道被调方的参数模式，而 rc 逐模块跑、`CFun` 不带可见性、
跨模块只有 `CDirect(owner, name)` 一个名字——那是一张跨模块签名表的事。且 §5.1 已
裁定 Dawn 函数参数 owned 是刀 4 唯一性判据的前提，borrowed 只该作为刀 4 在同一张
`Intr` 表上开的**个别口子**出现，不是 2b 这种整体规则。

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

### 6.1 落地后的形状：一个运行时分支，四件「早放」

运行时那半很小：`dawn_array_with` 改为**消费**它的数组和元素（`types.intr_owned_args`
在表上开的 owned 口子——§5.1 预留的正是这一格），数组头与 buf **都** `rc == 1` 且不在
leak 模式时就地写并原样交回，否则照旧复制、末尾把消费掉的引用还账。两个都要查：
数组自己 rc 1 时 buf 仍可能被另一个版本共享。leak 模式下计数只增不减，判据永远
不成立——顺手成了「全复制基线」的量法。

难的那半全在 pass 里。第一轮实测**命中 0 / 456,977**：唯一性判据没有错，是引用
根本死得不够早。四个钉子，每拔一个都是让某个引用在 `array_with` 跑之前消失：

1. **sweep（早放）**。绑定在最后一次被碰的语句之后立刻 drop，不再等作用域末——
   骑在 2b 的 after 集上，位置就是每对语句之间。被匹配的旧节点提前释放，
   它的字段引用随之解开，`kids` 的计数才降得到 1。
2. **unloop（match 一次性循环还原成分支树）**。lower_match 把 match 编码成
   「`if (test) { arm; break }` 行列 + 不可达 panic + 一次性循环」——JVM 后端读它是
   廉价标签，rc 的循环护栏读它是「整个 match 里外层绑定全部冻结」。而护栏不能
   简单放开：**它同时是 break 重汇合路径记账一致的前提**（各 break 路径与循环后
   代码在汇合点必须对得上账，臂内的单边释放会把账拆散）。解法是在 C 这条路上
   把戏服脱掉：严格匹配该形状就重写成嵌套 CSIf，break 消失，臂间走现成的
   reconcile。严格匹配还包括终止语句不得含当前 loop id 的 break 或 continue；普通
   `while` 与 range `for` 也以退出测试开头，若源码 body 自己无条件跳转，只看“终止语句
   发散”会把源码循环误拆，并留下没有 C 标签的 goto。带 guard 的臂（break 是有条件的）
   不匹配，保守保留循环。
3. **开放循环 + pin**。TCO 让尾递归参数看起来跨迭代存活，退出臂里也不敢放。
   体**不可能正常完成**（唯一回边是 `continue`）且**无自身 break** 的循环标记为
   `open`：穿越它的释放只需查 after 集里有没有该循环的 **pin**（负数哨兵 sym，
   `fv` 在 `CContinue` 处播下）——还会继续的那条臂被 pin 住，退出臂自由。
   源码 `while`/`for` 体正常完成，照旧全冻结。
4. **赋值交接**。`m = map.insert(m, k, v)` 的展开是「先算后放」，目标进 after 集，
   实参永远 dup——rc 恒 ≥ 2，整条 spine 的复用被这一处堵死。改判：值表达式自己
   消费了目标绑定时，**那次转移就是旧值的释放**，展开里的 drop 消失，绑定随赋值
   重新入账。为让闭合循环里的这一形状也成立，改写值表达式期间把绑定临时改挂到
   最内层作用域（同一条语句内转移与重建配平，回边插不进来）；值里含跳向外层循环的
   jump 时拒绝。

第四件之外还有一件不在编译器里：`std/hamt` 的 `assoc` 原来写作
`Hamt { ..m, root: node_put(m.root, …) }`——字段读取内联在一个大表达式里，`m` 活到
表达式末，把整条 spine 钉在 rc 2。分析是**语句粒度**的，切不进一个表达式中间；
把字段先落成绑定（`let root = m.root` …），sweep 就有缝可下。这是「源码形状影响
复用」的第一个实例，记在这儿当先例：**热路径上的记录更新要写成字段绑定式**。
（自动化的出路是 pass 学会拆投影进 let——将来的活，不欠在这刀里。）

**后话：这处手工改写被 §6.4 的借用推断撤销过，又由 §6.5 的规则恢复。** 借用推断
读同一个 `assoc`，看见的正是「`m` 只被投影，没被消费」，于是判它 borrowed；而
borrowed 参数在被调方永远不 drop，`m` 于是根本不死，整条 spine 又回到 rc 2。
把字段先落成绑定这件事，反过来让 `m` 更像个只读参数，更招来这个判定。**给作者的
写法建议，在一年后的另一刀下变成了触发条件**；今天恢复的办法不是改回源码形状，
是让推断认得这个形状（§6.5）。

### 6.2 这一刀自己的坑：completes 与 diverges 的缝

unloop 把臂尾的 break 剥掉之后，臂变成「语句发散、tail 为 None」的块——
`core.diverges` 只看 tail，于是 `yields` 说这个臂**会正常完成**。reconcile 信了，
把发散臂当成完成臂参与对账，**给还活着的兄弟臂缝了补偿 drop**——真双重释放。
这次是平衡检查器自己抓住的（它逐语句追 `gone`，臂间账对不上当场红）；修法是让
rc 本地的 `yields` 换底成语句级的 `completes`，与检查器的判断同源。教训与 2b 的
互补：**pass 与它的 oracle 对「哪条路径还活着」必须只有一份定义**。

### 6.3 实测与 `CBorrowed` 的了结

整编译器前端跑 `checker.dawn`（46 万次 `array_with`）：

| | leak 基线 | 刀 4 |
|---|---|---|
| 就地 / 复制 | 0 / 456,977 | **337,170 / 119,863（就地 73.8%）** |
| 墙钟 | — | 3.00s → **2.77s** |
| 峰值 RSS | — | 持平 ~1.46 GB（活数据主导，2b 已确认这一解读） |

线性更新的最小探针（8 键 ×100 次 `m = map.insert(m,…)`）**92 / 92 全就地**——
整条 spine 原地改写。剩下的 26% 复制是真共享（环境快照等）与只借用的绑定，
不是缺口。静态计数：dup 再 −23%（23,596 → 18,077）；drop 静态数上升是 reconcile
在多臂各放一份补偿 drop，动态每路径仍恰好一次。

**73.8% 是刀 4 当天的读数，口径是「前端跑 `checker.dawn`，全部 `array_with` 调用」。
它后来动过两次**，所以引用这个数之前先看 §6.5 的表：借用推断上线把它压到 69.62%，
刀 G 抬到 82.98%。这一格是比率不是常量，README 的对外说法已经改成不钉死数字；
门禁那边 `scripts/array-contract` 与 `scripts/map-reuse-contract` 各给一条轴立预算。

**`CBorrowed` 至此了结而未被构造。** §5.8 曾判它「作为刀 4 在表上开的个别口子
出现」——方向说反了：唯一性要的是**更多的交出**而不是更少，刀 4 开的是 owned
口子。borrowed 作为跨模块调用约定的那格当时仍然空着；那张跨模块签名表后来
真的有了，就是 §6.4。

### 6.4 借用约定：模式契约与保守推断（借用线，2026-08-27 落地）

§1 的画像在刀 4 之后仍然成立：扫描型代码的 RC 流量大头不是真实生死，是**约定税**
——owned 约定下每个实参传递一对 dup/drop，外加被调方的 own-frame。lexer 语料
（4M 字符，每字符三次 std cursor 包装调用）量出 76% 墙钟花在这上面。借用约定把
这两半一起减掉：调用方不 dup（自己的引用活过调用，单线程严格求值下成立——被调方
先返回，之后的语句才可能释放它），被调方不 drop（绑定不入账本，同 `dict_syms`
的待遇，也不占 own-slot）。

**契约（`core.CMode`）有两个读者，必须逐函数一致**：被调方读 `CParam.mode`
（`rc.rc_fn` 决定什么入账本，`emitc.emit_fn` 决定什么占 own-slot），每个调用点读
全程序模式表，键 `(owner, name)`（`rc.owned_positions` 与 `emitc.arg_flags`，
一张表两个读者）。分开存是故意的：错位的两个方向（表说 borrowed 而被调方还 drop
= use-after-free；被调方不 drop 而调用点还交出 = 泄漏）都不打印错字节，差分看不见，
所以 mutant harness（scripts/rc-mode-contract）要能单边翻转它。防线分三层：
`rc_module` 开头的**契约断言**（`mode_mismatch`，错位=编译期 panic，指名函数、
位置、两边答案）、`rc_check` 按同一张表分类调用实参（借用位是读取不是转移）、
再往下才是 asan / LSan（断言落地前逐面实测过：callsite 半翻 = heap-use-after-free，
callee 半翻 = LSan direct leak）。

**推断是全程序预 pass（`c/infer.dawn`），方向照 Lean（InferBorrow）**：引用参数
默认 borrowed，不动点把「不止是读」的翻成 owned。`__emitc` 本来就是全程序编译，
表在 `cdriver.build_units` 里天然可得——先 lower 全部模块，推断，盖章
（`stamp_modes` 把同一个答案写上 `CParam.mode`），再逐模块 `rc_module`。
规则分两类，牙齿不同：

- **管辖 pin**：调用点不读表的函数，参数必须全 owned，体内怎么用都不看——
  emitc 直呼其名的 `std/pvec` 面（`xs[i]` 是 Core intrinsic `list_index`，
  只在 emitc 映到 `std/pvec.index`，字面量/`++`/host 边界同理；名单
  `emitc.emitter_named_pvec_fns`）、字典槽指名的函数（`CSlotFn`，`CMethod`
  按裸函数指针全 owned 调）、`CClosure` 指名的函数（函数值经 `CDynamic` 全
  owned 调；具名函数作值有 `lift_fn_value` 包一层，pin 落在包装 lambda 上，
  里面的直呼调用照常读表）、impl/default/带捕获的函数（`CFun.name` 与普通
  函数可撞名，表键不上）、fn 类型的参数（高阶恒 owned，Lean/Koka/Swift 共识）。
  **删一条 pin 是泄漏**，spike 语料的 asan 档与探针都能点名（见下表）。
- **需求规则**：参数到达消费位就翻 owned——被返回（体尾/`CReturn`）、存进
  构造器/元组/列表、被闭包捕获、`let` 别名、被重赋值（TCO 循环变量：自尾递归
  在 Core 已是对参数的赋值，赋值展开要 drop 旧值，而 drop 是调用方从没授权过的
  释放）、流入已知函数的 owned 位（不动点传播）、流入 intrinsic 的 owned 位
  （`intr_owned_args`，保护刀 4 的就地率）、流入 CImpl/CDefault/CMethod/CDynamic
  调用的实参位（那些调用点全 owned）。走查（`dm_expr`）逐臂镜像 `rc.rw` 的
  消费分类。

**镜像由另一侧强制，这是「零新增 dup 点」变成机器契约的地方**：`rc.rw` 的
`CLocal` 消费臂里，borrowed 参数到达消费位是 panic，不是默默补一个 dup。于是
走查漏一条规则=第一个被错盖的 std 函数拒绝编译（删规则的 production mutant
全靠它红，见下表）；走查多看一条=多付一个 owned 位，只丢性能。唯一豁免是
**hoisting**：混合行的操作数列表为了求值顺序给每个操作数具名，借用位上的
borrowed 根在那里 dup 进临时、调用后 drop，本地配平，不算消费——豁免只罩
`borrows` 形状（裸局部或其上的投影/box 链；`bracket` 的资源以 `CBox(CLocal)`
到达，泛型槽把它装了箱，链正是把 consume 传到根的形状，链里嵌不进别的表达式，
旗子漏不进无关上下文）。另一条 spike 抓的缝：**字典操作数不具名**——它是不跑
代码的静态地址，具名会把 let 写在字典伪类型上，那不是值能住的 C 类型；全 owned
路径（`consume_all`）从不具名，借用行第一次把带字典的调用送上 `intr_args`
才撞见。

**harness 语义随之升级成「拨动」**：单边翻转在推断结果上拨一半，断言点名；
`both` 不再改成品表——第一次实测就翻了车：把 `str.len` 拨回 owned 后，靠旧行
判为 borrowed 的**调用方**（`is_empty`）立刻撞 borrowed-consume panic——而是
**带约束重跑不动点**（`infer.ForcedMode`：位置钉在反向，需求不许翻回，pin 对
钉成 borrowed 的位置让路），一个自洽的另一世界，传播到所有调用方。四条
known-red 各有名目：`std/pvec:index=both` 是 intrinsic 管辖泄漏（也是 pin-pvec
的 production mutant 本体）；`str:len` / `list:reverse` / `list:take` 三条是
拒绝——推断判了 owned（体内消费），拨成 borrowed 撞零新增 dup 契约，红在
编译期。

**实测**（基线 52c561b，9700X/WSL2，gcc -O2，hyperfine 15 次）：

| | 前 | 后 |
|---|---|---|
| lex 动态 dup / drop（4M 字符） | 12,000,003 / 12,000,035 | **1 / 33** |
| lex 墙钟 | 47.5 ± 0.3 ms | **18.1 ± 0.3 ms（2.64×）** |
| psum_build `array_with` 就地率 | 6180 / 5061（55.0%） | 6180 / 5061（持平；**只量了 pvec 那条轴**，见 §6.5） |
| psum_build 动态 dup | 1,262,669 | 1,262,671（+2，噪声） |
| spike 语料 88 项静态 dup 点 | 60,179 | 48,110（−20.1%） |
| 同上 own-frame | 26,649 | 22,380（−16.0%） |
| `__emitc` 墙钟（lex/json_lib） | 0.90s / 0.81s | 0.90s / 0.82s（推断在噪声内） |

18.1ms 与勘察时手工改产物 C 模拟的上界 17.9ms 相差 1%：这一版推断在扫描形状上
基本拿满。分布照旧极不均匀：psum 型（分配/指针追逐主导）≈0，勘察备忘录预测的
形状原样兑现。输出侧 oracle：lex/psum 输出逐字节同基线；spike-native 106 项全绿
（含 asan+LSan 档）；JVM 零字节变化（模式只在 C 路上盖章，`selfhost-prev-diff`
无新增声明）；JVM 与 native 双 fixpoint B==C。

**每条规则一个 production mutant，观察到的红**（删掉该规则后）：

| 规则 | 红 |
|---|---|
| pin：pvec 面 | LSan direct leak（psum 探针；known-red `std/pvec:index=both` 同体） |
| pin：字典槽 | LSan direct leak（`list.sort` 探针；桥函数被盖 borrowed） |
| pin：闭包指名 | LSan direct leak（`list.map` + 引用参数 lambda 探针） |
| pin：fn 类型参数 | **无红**（见下） |
| 需求：返回/逃逸 | rw 拒绝，selfhost 8 个模块 GAP（如 `emitc.dup_expr`） |
| 需求：存入构造器 | rw 拒绝，33 GAP |
| 需求：闭包捕获 | rw 拒绝，17 GAP |
| 需求：let 别名 | rw 拒绝，58 GAP |
| 需求：重赋值 | `rc_check` unbalanced（2 GAP + TCO 探针） |
| 需求：owned 位传播 | rw 拒绝，50 GAP |
| 需求：intrinsic owned 位 | rw 拒绝，2 GAP（lexer/astdump 的 `array_with` 流） |
| 需求：非直呼调用实参 | rw 拒绝，6 GAP + `list.sort` 探针编译红 |
| 契约断言本体 | rc-mode-contract 整跑 FAIL（callsite 翻转落到 rw 拒绝，不是 harness 认的 oracle） |

fn 类型 pin 是唯一没有机器判词的规则：`CDynamic` 的目标在 rw 里本来就是借用位
（调用函数值是读它，刀 1 就这么定的），只持有并调用函数值的参数即便 borrowed
也两侧自洽，三家共识 pin 的是「部分应用看不见借用」这类 Dawn 今天没有的力学。
留着它是零成本对齐共识（fn 参数维持现状即 owned），删它的 mutant 三个探针全绿。
若后续想给它立判词，得先让某个调用点对函数值位置读表，今天没有这样的读者。

### 6.5 刀 G：重建形状不判 borrowed（2026-08-27）

§6.4 上线当天带进来一处回归，`array_with` 的就地率从 43.5% 掉到 14.0%。查下来
**损失 100% 集中在一个调用点**（`std/hamt.node_put` 的 `array_with`），而那个调用点
的责任人是**上游一个参数的借用决策**：`std/hamt.assoc` 的第 0 个形参。

机制不是「借来的参数传给消费型 intrinsic 前要 dup」（那条在代码上不可能发生：
`dm_expr` 的 `CIntrinsic` 臂把 owned 位上的实参当场判 owned，真漏了也会撞
`rc.rw` 的 borrowed-consume panic）。真正的链条是：

> **借来的参数不会在被调方被 drop；于是从它身上投影出来的字段，在被调方的整个
> 函数体里 rc 都 ≥ 2。而 Perceus 复用靠的正是「先放掉容器、把唯一性交给孩子」。
> 借用把那次 drop 删掉了。**

判断没错，错的是代价模型。借用省下的是「调用方少一对 dup/drop」，付出的是
「被调方拿不到容器的所有权，因此拿不到孩子的唯一性」。对扫描型函数前者大后者为零，
对**改写型**函数（拆开一个持久结构、装回一个改过的）恰好反过来。

**规则（`c/infer.proj_demands`）**：形参的投影落在消费位、且**本函数自己也构造同一个
ADT** 时，该形参不判 borrowed。判据就是 Perceus 复用存在的那个形状，实现是查表
不是分析：`CField` 本来就带着 `adt: Int`，比对的是同一函数体构造过的 tag 集合
（`rebuilt_adts`，全程序算一遍，与模式表无关所以提在不动点外面）。投影可以写在
构造之前（`let root = m.root` 在 `Hamt { .. }` 之前），所以收集必须是独立的一遍。

**它只翻 15 个参数**，整张表 1568 → 1554（另 +1 是新函数自己的参数）：

```
std/hamt:assoc:0        std/hamt:sadd:0         std/map:insert:0        std/set:insert:0
c/rc:reconcile:0        c/rc:reconcile:1        check/cx:ty_span_kid:0  check/types:insert_impl:0
driver/analyze:apply_rewrites:0   driver/analyze:qualify_uses:0
front/parser:sync_arm:1 front/parser:sync_arm:2 ir/interp:fold_expr:2
lsp/server:append_diagnostic:0    dawn$pkg$compiler_plan/source:resolve_src_deps:2
```

这张表读起来像「持久结构更新」的名单，不像一次误伤。owned 是安全方向（本模块头
注释：每次拒绝只多一次 dup，绝不少一次 free），所以这一刀不可能引入 `rc.rw` 的
panic 或泄漏，它整个是个性能判断。

**实测**（nmain 全管线自编译，同一份输入，三个二进制交错跑各 3 次取中位数）：

| | 借用全关 | 单点拨回 borrowed | **刀 G** |
|---|---:|---:|---:|
| `array_with` 就地 / 复制 | 1,092,848 / 1,666,599 | 353,709 / 2,405,738 | **1,092,848 / 1,666,599** |
| 就地率 | 39.60% | **12.82%** | **39.60%** |
| 峰值 RSS 中位数 | 287.7 MB | 316.0 MB | 316.2 MB |
| 墙钟中位数 | 8.48 s | 8.27 s | 8.28 s |

「单点拨回」是 `DAWN_RC_MODE_FLIPS='std/hamt:assoc:3:0=both'`，即带约束重跑不动点、
把这一格钉回 borrowed，也就是刀 G 之前的世界。三个二进制**产出的目标 C 逐字节相同**，
这是本节唯一的正确性 oracle：模式决策改的是 dup/drop 落在哪，从不改答案。

**刀 G 与借用全关在六个计数器上逐位相同**。也就是说这一刀把 §6.4 欠下的复用**全额**
收回了，同时留住借用自己的 RC 收益。前端口径（`checker.dawn`，固定输入所以跨版本可比）：

| 世界 | 就地 / 复制 | 就地率 |
|---|---:|---:|
| 借用关 | 165,137 / 33,816 | **82.98%** |
| 借用现状（刀 G 之前） | 138,571 / 60,382 | **69.65%** |
| **刀 G** | 165,137 / 33,816 | **82.98%** |

顺带把两笔账记清楚：

* **峰值 RSS 的 +28 MB 是借用自己的代价，不是这一刀的。** 单点拨回与刀 G 只差
  0.2 MB，借用全关才是 287.7 MB。借来的引用由**调用方**在调用返回之后才释放，
  活数据的水位线整体抬高，这笔在 §6.4 的验收表里一格都没有。
* **墙钟不动。** 74 万次少掉的数组复制在 8.3 秒里是 1% 上下，测不出来。计数器是
  确定性的，结论建立在它们身上；墙钟这次只用来说明它没有反向变化。

**门禁：新增 `scripts/map-reuse-contract`。** 这次回归的机器可见度是零，原因值得单独
写下来：`scripts/array-contract` 那道「就地率 ≥ 80%」的门量的是 `steal_native.dawn`，
它用 `++` 累积，所以它数到的每一次 `array_with` 都来自 `std/pvec.push_tail`；而
`map.insert` 走的是 `std/hamt.node_put`。**两条轴各走各的**：回归两侧那道门测到的都是
同一个 `11241/11241`。新门跑 20 万次 `map.insert` 加 5 万次 `set.insert`，按
`DAWN_RC_STATS` 的就地率立预算（实测悬崖：刀 G 36.6%，`assoc` 拨回 borrowed 后
**0.0%**，预算取 25%），并把那次拨回作为 production mutant 钉在 `matrix.txt` 里，
连同一个必须保持绿的控制判词（`finished`：模式决策不许改答案）。

### 6.6 那 17% 是什么：失败分布实测（2026-08-31）

外部评审建议引入 Koka 的 `fip` 标注，按本仓纪律先测后裁。测量（前端负载 = native 编译器
check `checker.dawn`，`DAWN_RC_STATS=1` + 逐调用点插桩 + rc 直方图 + addr2line 归因；
方法与脚本见 agent 研究档案 review-recon-p13-fip）钉住四件事：

- **`array_with` 只有三个活调用点**：`std/pvec.push_tail`（就地率 100.0%）、
  `std/hamt.node_put`（45.4%，占全部拷贝的 99.57%）、`std/hamt.coll_put`（0%，150 次）。
- **34,952 次失败里 rc > 2 的真多版本共享为零**：失败时头部 rc 恒等于 2，缓冲区恒唯一。
  整个 17% 都是分析或源形状把所有权白白交了出去，不是程序在真共享。
- 失败两族：**约 49% 是 record-spread 钉根**（`Cx { ..cx, syms: map.insert(cx.syms, …) }`
  这一形状，四个零唯一调用点占 79.6%，47 字段的 `Cx` 每次更新还多付 45 个 dup；§6.1 末
  「投影提升成 let」的缓办修法即此，公开 issue #30）；**39% 是下降钉父**（`node_put` 用
  `array_get`+dup 而不是 `pvec` 的 `array_steal`，改生成 C 验证方向 +3,984 就地，issue #31）。
- **ADT 复用的天花板**：本仓今天 ADT 复用为零；对 1,382 万次构造分配做时间邻接探针，
  51.4% 紧跟同形释放（k1）、74.7% 在最近 8 次内（k8）。数量级在这里，不在标注。

**#30 已落地（2026-09-01）。** `c/rc.dawn` 现在只在 C 路径识别 lowering 写下的
「一个 spread-base `let`，尾部为同构造子 rebuild」形状，把该 record 的字段投影提升到
base 后面的语句里；written expression 里仍指向源码变量的 `r.f` 也统一改读合成 base。
于是 `let base = r` 是 hand-over，投影完成后 sweep 在 updated expression 之前释放 base，
`map.insert` 收到的字段重新是唯一 owner。JVM Core/字节码不经过这一步。

这里要修正本节当时把两件事写成一件事的表述：现有 runtime 没有 ADT field-steal，
所以这刀消掉的是 **record 自身**的 dup/drop 并解除集合的 pin；引用字段从不可变 record
投影成独立 owner 时仍需一次 dup，随后才由临时量 transfer 给新 record。把 47 字段 `Cx`
的全部 45 个字段 dup 都消掉，需要未来的 ADT reuse/field-steal，不属于这次纯调度修复。

同一份 2026-09-01 `origin/main` 上重新冻结 native compiler 后，前端负载从
`177,133 / 35,732`（83.21%）到 `180,583 / 32,282`（84.83%，多 3,450 次原地写）；
对 `hamt.assoc` 入参的临时探针从 rc==1 `81,141` / other `41,149` 到
`85,946 / 36,344`。这低于上面 2026-08-31 归因推算的约 17k 上限，说明 main 上的负载/调用
分布已经演化，验收以新的冻结前后对拍为准。`map-reuse-contract` 因而没有虚抬原本看不见
record spread 的 direct-map 预算，而是新增 focused record-wrapper leg：修复后
`199,968 / 566,176`（35.3%），删除 scheduling 的 production mutant 为
`0 / 566,176`，同时 direct-map negative control 仍为 36.6%。
热缓存下以各自冻结的 native compiler 连跑自编译，旧版 5 次中位数 6.81s、新版 5 次中位数
6.91s（约 +1.5%，在墙钟噪声量级内）；确定性的复用计数上升，但没有可声称的墙钟收益。

**#31 已接在 #30 后落地（2026-09-01）。** `std/hamt.node_put` 的 branch descent 现在与
`std/pvec.push_tail` 用同一个合同：先以 `array_steal(kids, pos)` 暂时清空 slot，把 child 的
slot owner 交给递归，再以 `array_with` 把 rebuilt child 写回同一位置。shared array 上 steal
保守退化为 get+dup；unique array 上 parent 不再沿整个下降路径多钉一个 child owner。

独立基线固定在 #30 提交：同一当前前端负载从 `180,605 / 32,285`（84.84%）到
`184,825 / 28,065`（86.82%，多 4,220 次原地写）；新增的 hamt steal 中 36,826 次直接
transfer、27,915 次因该层仍 shared 而保守 dup。focused gate 的 direct-map 从
`249,936 / 682,352`（36.6%）升到 `682,352 / 682,352`（100%），record-wrapper 从
`199,968 / 566,176`（35.3%）升到 `566,176 / 566,176`（100%）；两项预算都升到 95%，
borrowed-assoc 与 keep-record-source mutant 仍把各自管辖的复用率打回 0%，新增的
get-child-again N−1 mutant 则把 direct/record 分别精确打回 36.6%/35.3%，并让独立的
`child_steal_taken` 从 100% 红到没有一次 steal。

**`fip` 标注本身自我否决**：最严读法下全部函数 7.9%、std 公开面 14.0% 可标，且可标集合
全是访问器与 IO；`map.insert`/`pvec.push`/`list.reverse` 这些 `fip` 存在理由一个都标不上
（S3 之后集合是 Array 背身、arity 动态，Koka 的固定 arity 复用信用对不上）。且 Dawn 没有
静态复用 pass（Core 只有 `CDup`/`CSDrop`），标注没有东西可查。裁决：不立 `fip` 设计文档；
先做 #30/#31，静态构造子复用 pass 落地并重测 std 公开面之后再回头看 `fip(n)`/`fbip`。

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
| 2b | 最后使用分析：把「dup 一次再 drop 一次」收成一次转移（§5.8；`CBorrowed` 改判给刀 4） | **完成**：同上全绿（含 asan），整编译器 dup −22% / drop −30%，语料 dup 约 −35%；probe 3.45s → 3.00s |
| — | 刀 2 落地后 Core golden 不只多了 dup/drop 行，还多了绑定（§5.0）。这是原计划没预见的，已重录 | |
| 3 | emitc 消费两个节点 | **完成**：语料 23 个程序全绿，且新增 `asan` 一档（每个程序再用 AddressSanitizer 编译跑一遍）；整编译器前端 native 跑通、与 JVM 答案一致，`checker.dawn` 峰值内存 **4.4 GB → 1.42 GB** |
| 4 | 复用分析（`rc == 1` 原地写）：owned 口子 + sweep + unloop + 开放循环/pin + 赋值交接（§6.1） | **完成**：整编译器就地 **73.8%**（337,170 / 456,977，leak 基线全复制），线性探针 92/92；probe 3.00s → 2.77s，峰值持平；全套门禁绿（含 asan、fixpoint、8 契约、4 个 N−1 对拍） |
| B1 | 借用机制不推断：`CMode` 两个真相（`CParam.mode` / 模式表）、`rc_module`/`emitc` 两侧消费、表恒空 | **完成**：产物 C 逐字节等于基线（纯机制门），语料全绿 |
| B3 | 模式契约 mutant harness（scripts/rc-mode-contract）：单边翻转必须被机器点名，DAWN_RC_MODE_FLIPS 注入 | **完成**：先于推断落地，「门禁的绿没有信息量」的顺序课；两个停-报发现（rc_check 落后于表、`list_index` 在表的管辖外）都成了 B2 的输入 |
| B2 | 保守借用推断（§6.4）：`rc_check` 学表 + 契约断言，然后 `c/infer` 全程序不动点 + 双侧盖章 + rw 的零新增 dup 拒绝 | **完成**：lex 语料 dup 12M→1、墙钟 2.64×、就地率持平；spike 106 项全绿含 asan，双 fixpoint B==C，JVM 零字节；13 个 production mutant 12 红 1 记名豁免（§6.4 表） |
| G | 重建形状不判 borrowed（§6.5）：`proj_demands` 一条规则，翻 15 个参数，收回 B2 欠下的复用 | **完成**：`array_with` 就地率与「借用全关」逐位相同（nmain 39.60%、前端 82.98%），目标 C 逐字节不变；新门 `scripts/map-reuse-contract` 带 production mutant（拨回 borrowed → 就地率 0.0%），同场景 `array-contract` 保持绿 |

刀 1 与刀 3 之间语料必须一直是绿的：刀 1 只改形状不改行为，刀 2 只改 Core 不改 C，
**第一次真正开始 free 是刀 3**，所以刀 3 是唯一一个「跑起来会段错误」的位置。
这是故意的——把风险压到一刀里，比三刀各担一点更好二分。

**2b 让到了 3 后面**，理由是同一条：刀 3 是唯一会段错误的那一刀，它该建立在已经被
平衡检查器验过的最保守版本上，而不是再叠一层最后使用分析。真出事时候选只有一个。
事后看这条挑对了——刀 3 打红的那一条（§5.6）与所有权推断无关，如果 2b 也在里面，
分诊要多一个方向。反过来也成立：2b 落地时自己的坑（§5.8 的 C 实参顺序）是刀 3
留下的 asan 档在第一轮就抓住的，检查器对它天生失明。

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
