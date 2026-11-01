# Mem 捕获作用域与按域消解（#847，K1）

> 状态：**proposed**（分刀实现中）。2026-10-23 裁决采 A；K2 已提供类型与语法基础，
> K3a 已完成运行器身份、分配归域和完整 Mem[s] 契约。K3b-1 接入显式 trait Capture
> 表面及静态契约检查；普通 T 空默认、实际环境传播、出口和 std 迁移留 K3b-2，
> 按域消解与控制边界留 K4。§8 的基线是 10 例拒绝、3 例仍接受，不表示 #847 完成。

## 1. 问题、依据与边界

现行 [Mem 设计](mem-buffer-design.md) §4 的 R1 检查结果类型，R2 限制安装 handler，
R3 检查操作与格子，R4 检查 Java 边界。现行 Mem 检查尚不传播函数环境依赖，故缓冲可以藏在
`Source.read`、`List`、泛型 `bind[T]` 的闭包里。另开 `with_mem` 又能消掉同一个
`Mem` 标签。#847 的程序在域外连续调用 `read(1)` 输出 `0`、`1`。
JVM 的 GC 与 native 的 RC 保活了对象；此处证明的是作用域与纯度漏洞，没有证明悬空指针。

即使值不逃逸，`peek(b) = with_mem(() => at(b, 0))` 仍会被当作纯函数。
`poke` 修改同一缓冲后，相同参数的 `peek` 返回不同值，违反 [spec §6.2](spec.md#62-规则)。
旧 `local` 的纯函数注解也必须拒绝，不能把“同域合法”误写成“读写没有效果”。

采用有限捕获作用域类型，并让 `Mem[s]` 只由域 s 消解。只追踪 Mem 域，允许同域别名、
可变共享、普通列表/记录、可存储的一等函数与高阶回调。控制效果第一版不得跨 Mem 边界
捕获栈。不是借用、线性使用、通用所有权或区域释放系统。

依据是 2026-10-23 的维护者裁决及同日研究、停工探针；研究不等于本实现的证明。
仓库内可重复的证据是 §8 的夹具。K1 不引入外国语言的整套类型系统。

## 2. 唯一表面拼写（K2 基础已实现，目标语义分刀接入）

命名沿用 spec §1：类型/种类名 PascalCase，参数名 lower_snake_case；不以大写的
`S` 冒充普通类型参数。值字段和实参仍用 `=`，类型和约束用 `:`。不增加硬关键字，
不复活 `fn(...) => ...`，不增加调用点类型实参或另一套块调用语法。

| 含义 | 唯一拼写 | 约束 |
|---|---|---|
| Scope 参数绑定 | `@s`，声明表如 `fn peek[@s](...)` | s 是静态身份，不是值或普通类型 |
| 缓冲的域 | `I64Buf@s`、`F64Buf@s` | 域不变；没有隐式无域缓冲 |
| 捕获集参数绑定 | `^c`，如 `[T: ^{c}, ^c, !e]` | c 是有限集合变量，不是 Scope |
| 捕获上界 | `T^{s, c}`、`fn(Int) -> Int !Mem[s] ^{s}` | 花括号内逗号表示并集；`^{}` 为空 |
| 域化效果原子 | `Mem[s]`、`mem.Mem[s]` | 同标签不同域是不同原子 |
| 受限 Scope 多态函数类型 | `fn[@s]() -> R !(Mem[s] \| e) ^{c}` | 仅 Scope 可在函数类型内部量化 |
| 对应 lambda binder | `[@s] () => body` | 括号参数与既有箭头 lambda 相同 |
| 不跨边界捕获的行上界 | `!e: fn` | 只含 io、尾恢复效果和同样受限的变量/投影 |

Mem 内核声明使用 `effect Mem[@s]`，操作结果和证据字段共享这个参数。
仅编译器识别的 std/mem.Mem 可声明一个 Scope 参数，不允许普通类型、Capture 或效果
参数，也不把这一接入口开放为通用参数化用户效果。

`^{...}` 是类型的最后一个后缀；在函数类型上修饰整个箭头的环境，不修饰返回类型。
返回一个带捕获的函数要用括号分组，如 `fn() -> (fn() -> Int ^{s})`。
`I64Buf@s^{s}` 合法但冗余；`I64Buf@s^{}` 不合法，后缀是上界而非擦除命令。
集合成员只收已绑定的 Scope 名或捕获集名，不收值路径、通配符、效果名或运行时表达式。
重复成员和顺序由 fmt 规范化；不同 binder 的同名参数先作 alpha 重命名，不能合成同一域。



最小新增产生式如下；这是本设计的语法片段，不另建独立 grammar.ebnf 正本。
Scope 与 Capture 是编译器种类，不成为可构造的用户值或通用 kind 多态入口。

```text
scope_binder   := "@" lower_name
capture_binder := "^" lower_name [":" capture_bound]
capture_bound  := "^" "{" [lower_name ("," lower_name)*] "}"
scoped_buffer  := ("I64Buf" | "F64Buf") "@" lower_name
scope_fn_type  := "fn" "[" scope_binder ("," scope_binder)* "]" fn_type_tail
scope_lambda   := "[" scope_binder ("," scope_binder)* "]" "(" params ")" "=>" expr
```

`fn_type_tail` 沿用参数、返回和效果行，再接可选捕获上界；空参数表仍写 `()`。
这里只开放 Scope 的内部量词，`fn[T]`、`fn[^c]`、`fn[!e]` 的函数类型不合法。
同一普通参数表不许用同名的 T/s/c/e 遮蔽另一种类；内部 binder 也不许文本遮蔽外部名字，
alpha 重命名只用于类型比较和替换，不给作者两种解析。

这是有意增加的三类参数，分别与类型参数、效果参数共享现有 `[...]` 列表。
约束可并列，如 `T: Show + ^{c}`；`^c: ^{s, d}` 表示集合包含上界。
`@s` 不带生存期大小关系或用户自定 bound。捕获参数必须显式绑定，未绑定的 c 报错，
避免一个拼写错误默默新增 API 参数。所有 binder 在同一参数表内同时可见。

解析冲突审查：`@` 当前不在类型后缀；`^` 在表达式中是异或，类型中只在后随 `{`
或参数绑定位置使用；`!` 仍只引入调用效果。`Mem[s]` 只扩展效果原子的参数位置，
不是开放任意参数化效果。`fn[@s]` 只增加函数类型的 Scope binder；lambda 以 `[` 开头时，
仅 `[@name ...] (...) =>` 识别为 binder，其余仍是列表，列表元素不允许 `@` 起始。
`fn` 在 `!e: fn` 内是既有关键字的约束位置，含义来自 `fn`/`ctl` 的既有区分。
不使用 `scope`、`captures`、`forall`、`exists` 等新关键字。

同一域可在类型、效果与捕获集合里出现：`I64Buf@s` 给缓冲身份，`!Mem[s]` 给调用义务，
`^{s}` 给可保存环境的上界，三个位置不是同义别名。类型实参仍由调用实参和期望类型推导；
名义类型中可写 `Holder[s]`、`Source[s]`（如 `type Source[@s] = { read: fn(Int) -> Int !Mem[s] ^{s} }`），不开放 `f[s](x)`。
若一个签名不能推得唯一合法域则报错，不按缓冲布局合一 s 与 t。

### 2.1 trait Capture 参数与关联成员

trait 声明恰有一个 Type 主体参数，可另声明零个或多个 Capture 参数；Capture binder、集合实参与参数上界复用既有 `^c`、`^{...}`。本刀不增添第二个 Type 主体、不开放 trait 方法独立泛型、不增加 Scope/Capture 的内部高阶量词。

`trait M[T: ^{c}, ^c]` declares the subject capture upper bound. A subject without a bound uses the empty computation contract, `T: ^{}`. Data representation parameters follow the separate structural rule in section 3. All trait binders are visible together; unbound names are errors, and the subject position does not admit supertrait bounds.

impl 头写完整应用 `M[Subject, CaptureArgs...]`，如 `impl[@s] M[I64Buf@s, ^{s}]`；类型参数的 trait bound 隐含该主体，只写其余实参，如 `[T: M[c] + ^{c}, ^c]`。显式命名集合实参 `c` 与既有名义类型同义；缺少实参报错，不推导成旧 API 或偷偷新增 binder。普通方法调用仍只用值实参/期望类型推断，不开放 `m[c](x)`。

关联类型允许 `type Item: ^{c}`，省略捕获 bound 等于空。第一版仍不支持成员自身的参数、类型默认、任意 trait bound 或关联类型等式约束。`T.Item` 的 trait identity 按既有唯一成员规则解析，同时保留完整 trait 应用。

关联效果 binding 的一个 atom 可为 `!Mem[s]`；s 必须由 impl 已绑定且由完整 impl 应用决定。空行、io、单个具名非参数化效果照旧；不扩成任意行变量/投影 RHS 或一般参数化用户效果。默认关联效果在 trait Capture 作用域下不能凭 Capture 集合生成一个 Scope；没有可命名 s 就不能写 `Mem[s]`。

新增产生式：

```text
trait_params := '[' subject_param (',' capture_binder)* ']'
subject_param := TypeName [':' capture_bound]
trait_impl_app := TraitName '[' type_ref (',' capture_arg)* ']'
trait_bound := TraitName ['[' capture_arg (',' capture_arg)* ']']
capture_arg := capture_name | capture_bound
trait_assoc_type := 'type' TypeName [':' capture_bound]
assoc_effect_atom := effect_name ['[' scope_name ']']
```

最后一条仍只对有 Scope 参数的内建 Mem 合法。现有 `@s` 继续在 impl/function/type 参数表绑定，不把 Capture 当 Scope 来填 Mem 的域槽。


## 3. 类型判断与默认值

用 `Γ; Δ ⊢ x: T ! E ▷ C` 表示：活跃域集合 Δ 中，表达式 x 返回 T，求值需 E，
结果可达域依赖的上界为 C。`cap(T)` 包含 T 的域、环境与所有可达字段的依赖；
`free_scope(T, E, C)` 还包括参数类型、效果行等契约里出现的静态域。
V(T) is the reachable value capture upper bound. F(T) is the free Scope support
of the complete public type contract, and S(T) = V(T) union F(T). Both components
may overlap. A boundary checks the type delivered there and its support. Function
contracts represent hidden environment dependencies with C; nominal data and
opaque values retain their complete arguments and structural summary or public
envelope. A value bound on T does not prove that its unknown full support fits it.

- Int、Float、String、Bytes、Unit 等独立不可变值的 cap 为空。
  `cap(I64Buf@s) = cap(F64Buf@s) = {s}`，即使长度为零或只作 `len` 也如此。
- tuple、List、Option、Result、记录、变体的 cap 为可达成分之并。
  泛型字段先代换再求依赖；ADT 递归用有限集合的最小不动点，不能遇环就返回空。
  没有字段路径精度时保守取整个值的上界，投影不能把未知依赖变为空。
- An ordinary lambda, local function or synthesized ordinary closure obtains C
  from its resolved graph of free values, functions, cells, witnesses and evidence.
  An ordinary value contributes V only. Its type-only F does not enter C.
  A function contributes its declared or inferred environment; a dictionary
  contributes its complete witness contract W; frozen evidence contributes its
  support. Permitted cells retain their installation lifetime, invariant content
  contract and alias identity.
- Closure formation checks the captured values' well-formed types and the body.
  Moving the closure checks its complete public arrow and C, without reopening
  hidden ordinary fields to add F. This limited hiding neither exposes an
  existential Scope nor renames a Scope or adds an implicit parameter. It cannot
  hide V, witness W or frozen evidence. Free Scopes still present in parameters,
  results and calling rows remain visible.
- A Phantom[Buf@s] or an empty-environment fn(Buf@s)->Int may be captured by an
  otherwise independent ordinary closure whose public arrow omits s. Delivering
  either original type directly still refuses escape. A pure calling row does
  not prove an empty environment. Lambda rows are inferred; local named functions
  check their written calling contract.
- `T: ^{c}` bounds reachable value captures. Function and impl parameters, trait subjects,
  and associated type outputs default to empty capture contracts. Data, transparent alias
  and opaque representation parameters do not acquire that default. Explicit bounds remain
  mandatory at every application. These computation defaults remain staged until the later
  K3b-2 slice enables them with the required standard library migration.
- 未写捕获后缀的显式一等函数类型默认 `^{}`；局部无注解 let/lambda 推断集合。
  顶层/导出签名不从实现体偷偷推导非空公共捕获契约；需显式参数与上界。
  聚合的隐含字段依赖照常存在，不能用省略后缀清空它。
- 捕获上界只允许扩大：`C_actual ⊆ C_expected`。函数环境协变，函数参数逆变、
  返回值协变、调用行按 spec §6.2 的包含关系；进入可写格子的值类型不变。
  分支合流取并集，循环和递归固定点保留符号集合变量，不能用空集打断递归。

type alias 保留展开后的依赖，opaque 的公开签名必须给出足以覆盖隐藏表示的捕获参数/上界。
隐藏实现不会创造存在域。trait 关联类型/效果、impl 见证、默认参数闭包、构造器和方法转值
均用同一套替换、包含与自由域检查；跨模块只读接口契约也能得出同一结果。
模块缓存、导出面摘要、LSP 与 doc 的类型打印必须保留这三类信息。

泛型工厂的契约示例（待实现）：

```dawn
fn bind[T: ^{c}, ^c, !e](value: T,
  read: fn(T, Int) -> Int !e ^{c}) -> (fn(Int) -> Int !e ^{c}) =
  n => read(value, n)
```

At a call, c covers V(T) and read's environment; e preserves read's calling row.
T:^{c} does not prove F(T) is contained in c. The result arrow retains every free
Scope in e and c. When T has only type support, V(T), read's environment and e
may be empty, allowing c to be empty. The hidden input type does not automatically
enter result support. Captured witnesses and evidence still contribute their
public support.
给定域 s 的缓冲及读取函数，结果不会变成 `fn(Int) -> Int ^{}`，也不会变成纯函数。
上界可比实际环境宽；调用方不得根据未导出的函数体把它缩小。
高阶调用、递归调用和命名函数转值都实例化同一个契约；把运行器改名或装入记录不绕过规则。

### 3.1 trait 应用、见证支持与关联投影

Capture defaults follow quantification duties. Function declarations, including local functions, impl parameters, trait subjects and associated type outputs use empty computation contracts when omitted. A trait bound does not widen that default. Data representation parameters follow the structural rule below. `T: ^{c}` only bounds reachable value captures; free scopes in parameter and result types are checked independently.

trait 应用的 Capture 实参是方法/成员契约的静态参数，并集为该见证环境的公开上界 W。应用良构要求 `support(Subject) ⊆ W`；support 是可达捕获与完整类型自由域支持之并，不改变普通 Type 参数捕获 bound 的含义。impl 可在输入 trait 应用良构的前提下检查，其实例化/见证求解必须实际验证此前提。impl 注册还须证明主体 cap 符合主体 bound，各关联类型绑定符合各自 bound，且字典的子见证与 Scope 实例键等依赖被 W 覆盖。无 Capture 实参的见证按空环境契约检查。对完整见证类型的自由域另作支持检查；第一版保守纳入 W，不得因运行时擦除、去虚化或 singleton 而丢弃静态依赖。

一个 impl 的 Scope/Capture 形参必须可由完整主体与 trait 实参唯一确定或以公开的显式上界约束；仅出现在成员绑定/方法体中的私有自由域不合法。Scope 身份从完整应用作等式求解，不从任意多元素 Capture 集合随意挑一个域。无法唯一推断就报错。每个 trait 与 subject head 仍至多一个 impl，Capture 实参不参加择优、重叠或特化选择。

Capture 在 trait 应用上第一版按不变实参检查；同一个 trait 的不同实参 bound 不静默合并。方法里普通函数捕获后缀的包含/方差规则仍按本节，不能用字典参数“统一协变”绕过嵌套函数参数的逆变。

默认方法一次性在刚性主体/刚性 Capture 参数与声明的字典上界下检查。声明的返回函数省略捕获后缀仍为空；任何在默认体中捕获主体值、字典或局部格子的函数都必须证明其环境被返回契约覆盖。禁止从具体 impl 或使用点回头推导更宽公共契约。

未归约关联类型使用其声明捕获上界，不能按未知=空处理。主体定型时，类型、Scope、Capture、关联类型、关联效果及见证使用同一实例化映射；投影归约完成后才检查结果/存储出口。具体 Cur=Int 可恢复为空，不能把所有投影结果永久赋予主体捕获。

未归约关联效果保留投影 identity、主体及见证静态支持；实例化到 Mem[s] 时保留 s。效果证据由调用点供给，普通字典不自动冻结某次 handler 的证据。未知关联效果不默认满足 `!e: fn`；控制分类随 K4 的关联效果上界/剩余行检查处理，不以捕获为空代替。

方法转函数值、默认方法调用、字典应用与转发、opaque 函数表、模块导出/再载入使用同一捕获与自由域契约。缓存和类型打印保存 trait Capture 参数、应用实参、成员上界；不保留无 Capture 信息的旧接口读取分支。

The premise S(Subject) contained in W is independent of T's value bound.
N8 conservatively refuses a dictionary whose public contract retains a local
Scope, even when its runtime representation stores code only. Ordinary closure
hiding of an ordinary value's type-only F does not eliminate witness W.
Backend erasure, devirtualization and scalar method results cannot narrow W.



### 3.2 Structural data contracts and opaque envelopes

Data, transparent alias and opaque representation parameters accept any well-formed Type
argument whose support is nameable at the use. Explicit bounds still apply. Declaring a
Scope or Capture axis still requires its complete explicit application. No hidden Capture
binder is added to a constructor or a data declaration.

Generated constructors, projections and pattern decomposition inherit their parent data
quantification and explicit bounds. They substitute fields before computing dependencies.
User wrapper functions, derived methods and default argument computations retain their own
computation contracts. Constructor values are instantiated to ordinary monomorphic function
types, whose environment and complete free scopes must fit the storage position.

Tuple, List, Option, Result and user records and variants use substituted reachable fields.
Recursive declaration components require a finite symbolic dependency summary and its least
fixed point. An unresolved parameter or recursive edge cannot be treated as empty. A phantom
nominal argument remains in complete type support; a transparent alias argument disappears
only when expansion removes it. Function fields keep their own explicit environment and
calling row. Structural data rules do not introduce nominal covariance or mutable slot
covariance.

The first opaque contract is determined by its public head. Its value capture envelope
includes every Type argument's value captures and all explicit Scope and Capture arguments;
complete support also includes free scopes in Type and effect arguments. The definition must
prove that its hidden representation fits this envelope. Imports use the exported envelope
without opening private fields, and missing envelope metadata is not interpreted as empty.
Interfaces, caches, documentation and language server types retain quantification duties,
explicit bounds, envelope metadata and static identities.

The second K3b-2 slice implements data summaries and opaque envelopes with explicit
contracts while computation defaults remain disabled. Before enabling computation defaults,
a real seed closure audit must cover the actual compiler and library migration. Control
boundaries and domain discharge remain in K4.

### 3.3 Finite summaries and declaration duties

The second K3b-2 slice keeps computation defaults staged. Its declaration
contracts distinguish data representation and data introduction from computation.
A generated constructor inherits the parent declaration's Type parameters and
explicit bounds. A user function, derived method or default argument computation
keeps its computation contract. This distinction adds no Scope or Capture axis.

A data summary has two components: reachable value captures and complete free
support. Each component is a finite union of projections of declared Type
parameters and declared Scope or Capture identities. Projections belong to the
summary representation and are substituted with actual Type arguments. They are
not surface capture arguments or implicit binders. Function environments enter
the value component; function parameters, results and calling rows also enter
complete support. All nominal arguments remain in complete support, including
phantom arguments. Transparent aliases retain only the dependencies left after
expansion.

Declaration dependencies form a graph. Each strongly connected component is
solved by monotone union over that finite domain, with dependency components
settled first. Empty is an iteration lower bound, never an answer to an
unresolved edge. Applying a settled summary substitutes its projections instead
of recursively expanding instantiated fields. This also covers recursive calls
whose Type arguments grow structurally. Declaration order cannot affect the
settled result.

Explicit data constraints are obligations at both declaration and application.
An unrestricted representation parameter cannot prove an empty capture bound.
Header obligations which depend on an unfinished declaration component are
checked after its summaries settle and before body checking. An alias or field
cannot become well formed merely because one client later chooses Int.

Opaque envelopes use the public head, including every Type argument's value
captures and explicit Scope and Capture arguments. Complete support also retains
the arguments' free domains. The owner proves that the representation fits the
envelope. Client dependency checks do not open the hidden target. Exported
contracts retain declaration duties, explicit bounds and settled summaries or
the opaque head envelope. Missing required metadata refuses the interface or
invalidates its cached product; it cannot supply an empty summary.

Actual environments use a separate graph of resolved value identities, closure
captures, dictionaries, evidence and mutable cells. Joining or recursively
referring to values preserves these edges. Cell writes retain the cell's
installation scope and invariant content contract. Solving this graph does not
replace the type summary, and a pure calling row does not erase an environment.
The value and support summary components answer different questions. Ordinary
value capture uses value; boundary well-formedness, witness premises and nominal
results use complete support. A single traversal of all dependencies cannot
replace both. Ordinary Type value bounds do not prove complete support; each
trait support premise has an independent source.

Validation uses explicit contracts for the M and N programs while computation
defaults remain disabled. Independent mutations must build and execute their
owning semantic oracle. The later default activation still requires the actual
seed closure audit, and K4 retains domain discharge and control boundaries.


## 4. 运行器与按域 Mem 消解

运行器签名（K3a 已接入，R 的捕获上界由 c 表示）：

```dawn
pub fn with_mem[R: ^{c}, ^c, !e: fn](
  body: fn[@s]() -> R !(Mem[s] | e) ^{c}
) -> R !e
```

调用方先确定 R、c、e，它们在 s 的 binder 外，不能含新 s。检查 body 时引入刚性新 s，
同一源码位置的递归/再次调用也必须生成新身份。它不是可供调用方挑选的类型变量。
运行器函数值、别名、导出包装器保留这个内部量词；不能降成 `fn() -> R !Mem`。
受限多态值可按这个类型传递、存放和调用；没有任意 T 的 rank-N 或存在包装。
普通 helper 的声明级 `[@s]` 是由调用方实例化的参数，不能充当生成域。

body 的旧无参 lambda 改写为 `[@s] () => ...`。分配选用这次运行的 Mem 域；
没有显式参数可推导域的分配，选择当前最内层运行器的域。
有域参数的 helper 转发其行所需的那份证据；期望类型不能把已分配缓冲重标为别的域。
`with_mem` 对新 s 安装唯一的 Mem[s] 证据，用户不能直接安装或伪造它。

| 操作 | 域与调用行（待实现） |
|---|---|
| new、f64_new、from_list 等分配 | 结果缓冲属 s，`!Mem[s]` |
| at、set、fill、to_list、字节编码等读写 | 缓冲属 s，`!Mem[s]` |
| copy_from(dst@t, ..., src@s, ...) | `!(Mem[t] \| Mem[s])`，允许 s=t |
| len(b@s) | 纯，参数/闭包持有的依赖仍含 s |
| 复制出的 List[Int]/List[Float]/Bytes | 不含缓冲引用，cap 为空；复制本身仍读 Mem[s] |

从 body 的效果行中只减去 **Mem[s]**，其余原子原样转发。嵌套 t 读写外层 s，
内层出口保留 `Mem[s]`，在外层 s 结束时才消解。证据键必须含域身份；不能继续只按
`std/mem` 的声明 id 排槽或在内层覆盖外层槽。s 与 t 的 copy 同时要求两份证据。

```dawn
fn peek[@s](b: I64Buf@s) -> Int !Mem[s] =
  mem.with_mem([@t] () => mem.at(b, 0))
fn poke[@s](b: I64Buf@s, n: Int) -> Unit !Mem[s] =
  mem.with_mem([@t] () => mem.set(b, 0, n))
```

删去上述签名的 `!Mem[s]` 必须拒绝。`!io` 也不能独自覆盖这个具体原子。
在外层 s 内调用的局部 read 应为 `fn(Int) -> Int !Mem[s] ^{s}`；可以保留内部 t，
也可删掉无用的内层运行器。这保持 spec §6.2 的调用点应答，不改成创建点结算。
捕获集非空不自动引入读写效果：只捕获缓冲求 len 的闭包可以纯，但仍不能离开域。
每次调用才新建独立 Mem 状态的返回闭包，环境可以为空，仍允许纯调用。

## 5. 传播、存储与全部出口

Every boundary checks the delivered type's complete S and residual effects.
For an ordinary function value this is its public arrow and environment contract,
without reopening hidden ordinary environment fields. Direct nominal values,
arrow parameters, results and rows, opaque envelopes, witness W and cell contents
retain their full checks. Each storage location has the active Scope set L from
installation or creation. Writes must fit L and the invariant content contract;
aliases share that lifetime even when read in a deeper block. A cell write has no
closure hiding step, so empty V alone cannot justify an escaping F. External
storage without a capture contract accepts only delivery types without local
support.

| 通道 | 必须证明的条件 |
|---|---|
| Mem s 的正常返回、提前 return、`?` 的答案、分支答案 | 结果类型、cap、残余行均不含新 s |
| 写入外层 handler var、可变闭包格子、聚合更新 | 来源依赖在该位置有效域内，Unit 返回不豁免 |
| effect 操作的参数/答案、转发及 handler 臂 | 接收端契约与安装寿命覆盖全部依赖 |
| Ordinary lambdas, local functions, factories, dictionaries and synthesized closures | Preserve V environment edges, witness W, frozen evidence and cell lifetimes; check the complete public arrow |
| opaque、模块导出与接口再载入 | 不遗失隐藏表示的上界，不封装新 s 为未声明身份 |
| Java 参数、SAM、Object/List bridge 以及其他无捕获契约的外部存储 | 只接受空捕获且无局部自由域；io 不代替域证明 |

R3 的“任何操作/格子都不得含缓冲”由这套契约取代：域内安装的局部 handler 可以持有该域，
域外安装的不可以。暂不开放通用参数化用户效果；需要在操作里传缓冲的接口必须等有可表达的
域契约，证明不了就拒绝。同域 handler 臂通过普通闭包读取外层缓冲仍合法。
`with_fake` 的 Clock 操作只传标量，但其 evidence 闭包持有缓冲，仍受安装寿命检查。
普通 lambda 继续从调用点取证据；续延的已冻结证据另见 §6，不能因行里不再显示标签就丢掉依赖。

panic 的非返回出口可以销毁局部状态；catch_panic/bracket 的回调与答案同样保留捕获信息。
被捕获的诊断文本只能是独立 String；不可把有局部依赖的任意答案偷装进无域错误包。
所有出口都检查静态作用域，GC/RC 是否保活不是放行条件。

## 6. 控制边界

Mem 的计算可以调用尾恢复效果、io、panic/catch_panic，并在同一 Mem 内安装 ctl handler。
如果 ctl 的目标 handler 在新 Mem 边界之外，它会截取含该 Mem 运行帧的栈，第一版一律拒绝，
即使臂当场恢复或丢弃也不例外。域内先处理的 ctl 不在剩余行中，可继续使用。

`!e: fn` 是可组合的“不含未处理 ctl”约束，随泛型、效果投影、函数值和导出面保留。
未知 e 或无此保证的关联效果不默认安全；外层泛型 wrapper 必须转发约束。
递归 runner 同样检查。约束针对剩余行，不能按操作名、with_mem 字面名字或最终 main 的
具体调用图补白名单。普通效果变量被 `!io` 包含时也不能抹掉这个控制分类。

域内合成续延 k 的 capture 至少包含它保存的运行帧、handler 格子与证据的依赖。
它的调用行仍按 continuation 规则计算，但行缩减不清空 capture。局部恢复、局部保存后恢复、
丢弃均可；放到外层格子、操作或返回记录必须拒绝。下面两种均须有负例：

1. 外层 ctl handler 接住内层 Mem 的 ask，再把 k 存起来：在跨界捕获处就拒绝。
2. Mem 内处理 ask，再把 k 装入返回的 Waiting 字段：在结果存储出口拒绝，不能只拦第一种。

这保留 mem-contract 的域内 Ask 丢弃测试，同时明确拒绝在外层调度器挂起 Mem 的新用法。
不以一次性续延或运行时二次恢复 panic 代替作用域检查。

## 7. 落地点、分刀与成本核查

K2 提供 front 的 TypeRef/参数与 lambda binder、check 的 Ty/Sig/行/替换/统一基础，
以及 formatter、doc/LSP 与导出接口中的静态身份和集合。单一 TyFn 增加内部 Scope binder
与捕获上界；缓冲保留独立域身份，名义类型与 opaque 的域/捕获实参不混入普通类型轴。
Scope 和 Capture 参数、类型参数的捕获 bound、`!e: fn` 标记随 Sig/ADT/alias/impl 导出。
域化效果原子按声明身份和域身份比较、合并和替换；这不是运行器的证据消解实现。
显式名义类型应用和聚合字段替换保留这些参数，内部 Scope 量词按 alpha 等价比较，
替换遇到捕获风险时同时换新身份和显示名。函数捕获上界按集合包含关系比较。

K2 不把省略的注解应用成对旧程序的新拒绝，不推断闭包或 continuation 的实际环境，
也不根据调用实参求 Scope/Capture 约束。未绑定、重复、种类误用、内部量词越界、
文本遮蔽与显式擦除缓冲域有独立诊断。类型/打印/解析测试均使用旧种子可编译的源码；
新拼写仅出现在测试字符串。K2 的旧 Mem API 与未带域的内部缓冲形状仅供该刀过渡，
K3a 删除无域缓冲形状，不能保留为兼容分支。

名义类型的捕获实参可写集合参数名或同一 `^{...}` 集合字面量，例如 `Cell[c]`、
`Cell[^{s, c}]`；域实参仍写 `Holder[s]`。格式化对无注释集合去重排序，有注释时保留原成员与注释。

2026-10-30 补裁把运行器身份从原 K4 前移，实际刀序为 K2 → K3a → K3 → K4 → K5。

K3a 接入受限运行器量词：`with_mem` 的回调类型带 `fn[@s]`，每次运行器调用都产生
刚性新身份，重复、递归、函数转值、别名与包装器均遵守同一个契约。
普通 Scope 多态值按参数域或当前域实例化，例如 `let alloc = mem.new` 仍在调用处的
当前分配域分配；它的普通调用不安装 Mem 运行器。声明级 `@s` 同样由实参推导，
不是生成域；不能用 with_mem 的函数名或源位置充当域身份。
分配原语及 Mem 分配操作的结果为 `I64Buf@s`/`F64Buf@s`，无显式值参数可推导域的
分配选择当前最内层运行器域；期望结果类型不能把分配重标为另一个域。
buffer_sigs、缓冲内建类型入口和各消费者删除 TyI64Buf(None)/TyF64Buf(None) 旧形状。
std/mem 的运行器及分配操作、handler 臂、两种缓冲族的最小签名桥接在本刀完成，
必要的客户和夹具注解同步迁移，不能把旧 API 不识别或无关类型错误当作漏洞拒绝。

2026-10-30 第二次补裁选择一次接入 §4 的完整 `Mem[s]` 运行器契约，不提供裸 Mem
阶段签名，类型中的裸 `Mem` 同样按缺少域实参拒绝。K3a 同时接入域化证据 ABI、provider、分配 handler 桥接及必有域缓冲；
eff_labels 的裸标签视图与域化原子不能混为一谈，计数、pack、绑定、转发和两个后端
必须使用同一套完整证据布局。公共捕获参数保留最终契约，实际环境传播仍由 K3 实施。

证据查找键由原子的键和域实例键共同组成，裸标签的域键为零；不能对两个整数作
可能碰撞的压缩来代表二元身份。受限 Scope 多态调用与声明级 Scope 参数传递域实例键，
使一个泛型函数的形参域与调用者实参域对应；递归重入不能重新使用同一个域实例键。
这些执行键只用于证据路由，不加在缓冲对象中，也不作为运行时逃逸检查。
Scope 隐藏值参数可能使现有八值参数函数需要更宽的 JVM 接口；按实际闭包及类型
生成这些接口，保留普通值参数的原有限制，不能把隐藏参数漏当成额外证据槽。
分配 handler 与回调必须使用同一个新实例键；别名、包装器、函数转值都走同一个 ABI。

Mem 声明只允许一个 Scope 参数，其分配操作和证据记录的字段使用该参数；不开放
通用参数化用户效果。std/mem 的公开 with_mem 委托给编译器内部的运行器原语，由它
生成新域并安装两种分配操作的证据，避免给库作者增加另一套 Scope 块绑定语法。
完整签名不分两次迁移，无域缓冲和裸 Mem 阶段签名均不能作为兼容分支留下。
K3a 验收用双后端运行器身份与分配归域正负例；§8 的 13 例中，只有不依赖传播且在
指定语义处拒绝的才在本刀翻转，其余保持基线；不得用普通 T 的空捕获默认提前挡住实参。

2026-10-31 补裁采显式 trait Capture 参数，K3 分为两刀。
K3b-1 先交付 §2.1/§3.1 的表面、表示、序列化与声明/见证检查：AST、formatter、doc/LSP、
TraitI、完整 Bound、类型/效果投影、WitRef、接口摘要与缓存保留 Capture 实参及成员上界。
默认方法在定义处以刚性主体和 Capture 参数检查，不能借具体 impl 扩大返回环境。
本刀不启用普通 T 的空捕获默认、不迁移 std，不改变现有程序行为。
K3b-2 再闭合实例化与 lowering、实际环境、聚合固定点、默认启用、必要 std 迁移和全部出口，
加入来源链诊断。若自举闭包必须由种子直接读取新语法，先发布并按种子协议推进 K3b-1；
种子与 std 的实际读取阶段须经两阶段启动链实测，不能只凭单次 seed 检查失败推断。
原 K3 的 6–9 人日估计作废，依表示与替换原型重估后刀。

实现中若显式 Capture 实参仍不能给出可导出的确定推断、不能保留合法同域 Iter、
Item/效果必须藏未确定域或破坏单头一致性、见证支持拒绝另有承诺的合法客户，
或实测自举/接口规模/配对成本推翻前提，必须停止并重新裁定完整方案，不能加隐式实参、
字典协变、内建名字放行或第二个 Type 主体来挽救。
K4 保留控制边界、continuation 环境、local/peek/poke 的外域 Mem 不得被内层运行器
消去的语义验收及后端审计；ctl_cross、ctl_store 均归 K4。
K5 完成高阶 std 与 tileinterp 等客户的闭合迁移；发版后 K6 迁移站点 bcrypt/fake_clock。
不能只改类型显示或只让七个返回反例拒绝就关闭 #847。

K3b-2 starts with a separate call instantiation slice. Explicit value Capture bounds are
inferred before witness selection. Forwarded trait arguments remain invariant when a
value also has a wider declared bound. Item and associated effect reduction use the
same Scope and Capture equations as the selected witness. The erased callee ABI keeps
ordinary Type parameters while substituting its static Scope identities.

Dictionary definitions retain complete applications until lowering has selected their
subwitnesses and Scope keys. Scope arguments outside the subject participate in their
identity and constructor layout. A projected Mem atom is read from the caller's evidence
pack with that same instance key. Capture sets have no runtime slots. Actual environment
inference, ordinary empty defaults, standard library migration and the remaining exit
checks follow this slice; control boundaries and domain discharge remain in K4.

The second slice adds data introduction duties, finite declaration summaries,
opaque head envelopes and actual value and storage dependency graphs. Ordinary
closure environments merge V; delivered types retain S, witnesses retain W, and
storage retains its original installation contract. Explicit callback contracts
and closed scalar witness premises preserve the necessary scoped library uses.
Computation defaults stay disabled. Their switch and the remaining library
migration require a real audit of the compiler's seed closure before the next
slice proceeds.

The computation default audit checks both bootstrap edges. The recorded seed
builds the compiler against its matching standard library. That compiler must
then build the real compiler closure against the migrated current library.
Passing the first edge does not establish the second. Omitted value bounds
must not become complete support premises during this audit. Required source
contracts must be representable without implicit Capture arguments, name
exemptions or an older API fallback. Computation defaults remain disabled
until this closure is established.

两后端可以擦除静态域，不要求缓冲运行时增加域 id，也不承诺证据布局或 emit 零变化。
必须验证 at/set 仍是直接原语，重新量 bcrypt 与 tileinterp；K1 无性能实测，不作速度承诺。
诊断须能给出 `cursor -> Holder.buffer -> read -> Source.read -> scope exit` 的来源链，
泛型情况还须指出工厂上界与实参代换；不能只显示无法解释的 skolem 不一致。

6–10 人周是裁决的规划估计，非测量。本文未发现可以省掉泛型契约、受限高阶 binder、
证据键或控制分类中的任一项，也没有发现必须加入任意 rank-N/exists 的新前置，
目前没有充分依据认定估计偏差悬殊。最大风险仍是接口表示和约束推断；K2 原型须复核。
旧 seed 的编译 closure 不得自用尚未发布的新语法；实现内部先用旧语法，证明 closure 后
安排必要的 seed 推进。新 Mem API 闭合切换，不提供旧 API 长期兼容层。

## 8. 可执行 oracle 与交接条件

`scripts/checker-corpus/cases/mem_k1_*.dawn` 的 `.expected` 在 K1 为空，
**是已知误接受基线，不是正确性期望**。反例清单、未来拒绝点与翻转规则见下表。现有 corpus 会拾取它们，
修复后诊断增加会使门红，后续切必须审阅并替换对应 golden，不能整批重录成新的接受。
新语法迁移后的同语义反例必须解析通过，再在指定语义点拒绝，不能用旧 API 不认识来冒充修复。

固定基线：源码 `2037c283`，`dawn 0.100.0 (selfhost) b1:e59abbdd98c7`。
每例的 JVM `check/run` 与本树构建的 native 编译器 `check/run --std std` 均为 0；
表中 stdout 为两后端分别运行的共同结果，不是期望未来继续输出的 golden。
K1 中下列每个 `.expected` 的字节数为 **0**，对应 ACCEPTED；后续切把该文件替换为
非空的、完整且按序的 checker 诊断（REJECTED），保留案例语义与这一历史基线记录。

| `mem_k1_` 后缀 | 当前 stdout（`\n` 为换行） | 后续必须拒绝的原因 |
|---|---|---|
| repro | `0\n1\n` | 返回记录的函数字段捕获 s |
| record | `0\n1\n` | 通过 Holder.buffer 捕获 s |
| list | `0\n1\n` | 通过 List 元素捕获 s |
| direct | `0\n1\n` | 直接返回的闭包环境含 s |
| stored | `0\n1\n` | 跨函数存储不能擦掉捕获上界 |
| stored_effect | `0\n1\n` | 返回 Unit 但写入外层格子 |
| generic | `0\n1\n` | 刚性 T 的依赖经工厂代换进入结果 |
| local | `1\n` | 同域 read 的显式纯注解丢掉 Mem[s] |
| peek | `5\n` | 新域不能消掉旧缓冲读取效果 |
| poke | `5\n` | 新域不能消掉旧缓冲写入效果 |
| len_capture | `3\n` | 即使调用纯，捕获缓冲仍不许逃逸 |
| ctl_cross | `0\n7\n` | 跨 Mem 边界捕获栈并存储续延 |
| ctl_store | `0\n7\n` | 域内续延经 ADT 字段存到域外 |

重现步骤是对每个 case 执行 `./bin/dawn check <case>`、`./bin/dawn run <case>`，
再用 `./bin/dawn __emitc selfhost/src/nmain.dawn --split <units>`、
`CC_JOBS=8 scripts/cc-units.sh -o <dawnc> <units>` 构建本树 native 编译器，
逐例执行 `<dawnc> check --std std <case>` 与 `<dawnc> run --std std <case>`。
仅用 JVM checker 发出 C 不算这里的 native compiler check。
当前全套 corpus 会守住接受基线；它的绿灯不证明新规则健全。

翻转时须隔离要测的规则：generic 的 bind 先迁为 §3 的捕获/效果多态契约，
不能靠普通 T 的空捕获默认值提前拒绝实参来声称捕获传播已完成；local 的函数环境显式给
`^{s}` 而仍省略调用效果，才单独验证纯注解被拒。返回记录/列表/闭包的案例先让中间类型
容纳其真实域与行，再在域出口拒绝。stored/stored_effect 则允许在参数上界或外层位置的
存储边界拒绝，但必须指明丢失的域，不能以无关类型不匹配充当 oracle。


七个 #847 反例之外，基线还含旧 local 纯注解、peek、poke、只求 len 的隐藏捕获、
两类续延存储。每例先用当前 JVM 和 native 编译器 check，再实际运行两后端确认接受。
运行输出只说明漏洞被触及；最终 oracle 是拒绝而非维持有状态的输出。
正例 `scripts/spike-native/mem_capture_scope_ok.dawn` 及既有 `mem_ok_scopes`、mem-contract
守住同域 List/记录、回调、handler、跨域 copy、递归 runner、局部 ctl、panic 和独立状态闭包。
正例需迁移注解与 binder，行为与接受必须保持。

K2–K4 还须新增新语法的 alpha 等价、替换防捕获、上界扩大、分支/递归固定点、
opaque/trait/导出再载入、函数转值与 wrapper 运行器、未知控制行等检查。
这些在 K1 无法作为“已接受反例”运行，不伪称已测试。规则实现时逐条配负控，
例如抹掉导出 capture、合并 s/t、内层减掉外域 Mem、清空 k 环境，分别应让专门用例红。

## 不做的（理由）

- 不只禁具体缓冲的 lambda 捕获：刚性泛型 T、字典、间接聚合和续延都能藏环境。
- 不只禁返回、嵌套或重入 with_mem：外层存储返回 Unit，peek 定义没有词法嵌套，逃逸调用也可不重入。
- 不按 helper 名白名单放行：运行器与高阶存储必须有能跨别名和模块传递的契约。
- 不把 capture 当 Mem 调用行：len-only 捕获仍不能逃，创建工厂不一定读写。
- 不恢复创建点效果结算、不并入 io：两者会掩盖外域读写并改坏 spec §6.2 的纯度承诺。
- 不做运行时域检查、区域释放、借用互斥、线性或值语义：现有共享别名与 GC/RC 足够，题目是静态契约。
- 不做任意 rank-N、exists、一般依赖类型或捕获隧穿：受限 Scope 量化已覆盖 runner，扩大范围没有客户证据。
- 不开放跨 Mem 边界的栈捕获：第一版用可导出的控制行上界收口，不把健全性推到后续刀。
- 不保留旧 Mem API 兼容层，不在 K1 修改编译器、std 或迁移客户：本刀只把实现目标与反例固定下来。
