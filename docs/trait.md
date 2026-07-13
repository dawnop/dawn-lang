# Trait 方案设计（已定稿，2026-07-13 落地）

> 状态：**已实现**（六刀全部合入 main）。语言规则的规范化摘要在 `spec.md` §3.5，
> 决策摘要在 `design.md` D9；本文件保留完整的设计推演、实现设计与实现定稿记录（§9）。

## 0. 一句话

给 Dawn 加**单参数、一致性受控的 typeclass**（对外叫 trait）：Rust 的孤儿规则
与一致性 + Haskell 的字典传递实现（契合擦除后端），v1 只解决「泛型约束 +
自定义排序」这一件事，运算符只放开比较族，`==`/Show 暂不动。

## 1. 动机（今天疼在哪）

- **泛型约束不存在**：`fn sort[T](xs, cmp: fn(T,T)->Int)` 式显式传函数是唯一手段，
  每个调用点都要拖一个 cmp——stdlib 至今没有 `sort`，就是因为没有像样的方式提供默认序。
- **`<` 写死三类型**（Checker.kt `BinOp.LT` 分支）：record/ADT 无法参与排序表达式。
- **无法给类型挂开放操作**：想给 `Money` 定义序、给 `Version` 定义比较，只能裸函数 +
  调用点自律。
- 下游被卡住的特性：迭代器协议、`Num` 抽象、可定制 Show、derive 扩展——都在等 trait。

## 2. 调研对照（取什么、弃什么）

| 语言 | 模型 | 取 | 弃 |
|---|---|---|---|
| Rust | trait + impl，孤儿规则，单态化 + dyn | **一致性/孤儿规则**（全局每 (trait,类型) 至多一个 impl）、`[T: Ord + Show]` 约束语法感 | 单态化（Dawn 是擦除后端）、`dyn`（v1 不做）、关联类型、生命周期 |
| Haskell | typeclass + 字典传递 | **字典传递**的实现策略（擦除后端的标准答案）、默认方法 | 全局推断、高阶类型、多参数类 |
| Swift | protocol + witness table | witness = 生成的单例类这个落地形态 | existential、Self 约束 |
| Go | 结构化 interface | ——（结构化匹配与「显式 impl 即文档」冲突） | 全部 |
| Scala | given/implicit | ——（隐式作用域是复杂度灾难，反面教材） | 全部 |

核心定夺：**名义式（显式 impl）+ 字典传递 + 程序级一致性**。Dawn 泛型是擦除+装箱、
单一编译体，运行期必须有东西可调 → 字典传递是唯一贴合的实现；显式 impl 契合
「文档即契约」的语言性格。

## 3. 语言设计

### 3.1 声明

```dawn
# trait 声明：T 是主体类型参数（唯一、必写）
pub trait Ord[T] {
  fn cmp(a: T, b: T) -> Int          # 负=小于，0=等于，正=大于
  fn max_of(a: T, b: T) -> T = if cmp(a, b) >= 0 { a } else { b }   # 默认方法
}

# impl：给具体类型提供实现
impl Ord[Point] {
  fn cmp(a: Point, b: Point) -> Int =
    if a.x != b.x { float_cmp(a.x, b.x) } else { float_cmp(a.y, b.y) }
}
```

- trait 方法签名规则同顶层函数：参数类型/返回类型必写；效果可写 `!io` 或缺省纯，
  **不允许效果变量**（v1）。impl 方法效果必须 ⊑ trait 声明的效果。
- **默认方法**：trait 里可带 `= body` 的方法，impl 可不提供（字典里填默认实现）。
  默认方法体内可调用同 trait 的其他方法。
- 方法名进入 trait 所在模块的**函数命名空间**（与顶层 fn 同域、同冲突规则、
  同 `use` 引入方式）。UFCS 免费获得：`a.cmp(b)`。
- impl 无名字、不能重叠；`pub` 跟随 trait（impl 本身无可见性——见 3.3）。

### 3.2 约束与消解

```dawn
fn sort[T: Ord](xs: List[T]) -> List[T] = ...
fn largest[T: Ord + Show](xs: List[T]) -> String = ...
```

- 约束写在类型参数上：`[T: Ord]`、`[T: A + B]`。约束是签名的一部分（导出/悬停可见）。
- **消解规则**（调用点，两种情形，无搜索无回溯）：
  1. T 实例化为**具体类型** → 查全局 impl 表 `(Ord, Point)`；缺失即编译错误
     （报错列出类型与 trait，提示去哪写 impl）。
  2. T 实例化为**刚性类型参数**（调用方自己的 `[U: Ord]`）→ 转发调用方的字典；
     调用方没有该约束 → 编译错误（提示在调用方签名加约束）。
- trait 方法直接调用（`cmp(a, b)`，a 具体类型）等价于单方法约束的即时消解。
- **v1 不做条件 impl**（`impl Ord[List[T]] given T: Ord`）——字典需要运行期递归
  构造，留 v2；因此 v1 的 impl 主体只能是：ADT/record 具名类型、内建标量。
  元组/List/Map 不能作 impl 主体（报错提示 v2）。

### 3.3 一致性与孤儿规则

- **全局一致**：整个程序内每 `(trait, 类型)` 至多一个 impl，重复即编译错误
  （多模块加载后在程序级注册表查重，报两处位置）。
- **孤儿规则**：`impl Ord[Point]` 只能写在 **Ord 的模块**或 **Point 的模块**里。
  内建标量的 impl 只有 prelude/stdlib 能写（编译器白名单）。
- impl **不需要 use 引入**——加载进程序即全局可见（一致性保证了无歧义）。
  这一点学 Rust 而非 Scala：可见性玩法是复杂度之源。

### 3.4 运算符桥接（v1 只放开比较族）

- `a < b`（及 `<= > >=`）当两侧同为具名类型 `T` 且存在 `impl Ord[T]` 时，
  脱糖为 `cmp(a, b) < 0`。Int/Float/String 维持内建路径（性能 + 报错不变）。
- **`==` 不动**：结构相等已覆盖全类型、与 Map 键的生成 hashCode 深度耦合、
  语义可预测。自定义相等（如忽略大小写）用显式函数——直到真实需求出现前不引入
  Eq trait 与「== 语义可被用户改写」的心智负担。
- `+`/`Num` 抽象不做（等真实需求）。

### 3.5 与既有机制的关系

- **Show 暂不迁移**：`derive Show` 的容器递归渲染（List/元组随载荷）本质是条件
  impl，v1 没有；强行迁移会倒退。等 v2 条件 impl 落地后再把 Show 变成真 trait
  （届时 `derive Show` = 自动生成 impl，用户可手写覆盖）。
- **derive Ord 进 v1**：`type Point = {...} derive Ord` 生成字典序 impl
  （字段序/构造器声明序），机制与 derive Show 平行且此刻就有落点（sort 验收）。
- **效果系统**：约束消解不引入效果；字典是纯值。trait 方法声明什么效果，调用点
  就记录什么效果（同普通函数）。
- **comptime**：v1 禁止在 comptime 中调用带约束的泛型函数（解释器无字典），
  trait 方法对具体类型的直接调用允许（解释器直查 impl 表）。
- **不做 dyn/trait 对象**：异构集合的场景 Dawn 用 ADT 或 fn 字段 record 表达
  （web 框架的 Handler 即先例）。文档里写明这个惯用法。

## 4. 实现设计

### 4.1 Checker（新 `check/Traits.kt` + Checker 挂点）

- 注册表：`TraitInfo(name, tparam, methods: List<FnSig>, defaults, module, span)`；
  `ImplInfo(trait, subject: Type, methods, module, span)`。程序级（analyzeProject
  聚合各模块，查重/孤儿在聚合时报）。
- pass 顺序：trait 头 → impl 头（主体类型解析）→ trait 方法签名 → impl 方法体
  （按普通函数检查，self 类型代入）→ 约束消解发生在既有的调用点合一之后：
  `checkCall` 合一得到 T 的实例化 → 对每个约束走 3.2 的两条规则 → 在 Call 节点
  记 `witnesses: List<WitnessRef>`（`Concrete(impl)` 或 `Forward(callerConstraint)`）。
- `FnSig` 加 `constraints: List<TraitRef>`（按 tparam 对齐）；渲染进 hover。
- 比较运算符：`checkBinary` 的 LT 分支在三内建类型之外查 impl 表，命中则在
  Binary 节点记 witness、类型 TBool；未命中维持现报错并**追加 hint**
  （"impl Ord[$lt] 可让它可排序"）。

### 4.2 CodeGen（字典传递）

- 每个 trait 生成一个**擦除 witness 接口**：
  `interface dawn/tr/Ord { Object cmp(Object a, Object b); }`（全 Object，同现有
  fn 接口族的擦除约定；原始类型走既有 box/unerase）。
- 每个 impl 生成**单例类** `mod$Ord$Point implements dawn/tr/Ord`（INSTANCE 字段，
  方法体 = unbox → INVOKESTATIC 真实现（impl 方法平放为模块 static 方法）→ box）。
  默认方法：trait 声明模块生成 static 默认实现，未覆盖的 impl 在单例里桥到它。
- **带约束的泛型函数**：每个约束追加一个隐藏参数（描述符尾接
  `Ldawn/tr/Ord;`），体内 trait 方法调用 = ALOAD 字典 + INVOKEINTERFACE。
- **具体类型调用点**：不走字典——直接 INVOKESTATIC impl 的 static 方法
  （天然「去虚化」，零开销）。字典只在泛型边界出现。
- 传字典：具体 → GETSTATIC INSTANCE；转发 → ALOAD 调用方的隐藏参数槽。
- native-image：无反射、无动态类——生成的都是普通类与 GETSTATIC/INVOKEINTERFACE，
  与现有 LMF 同级安全。**JVM/native 对拍进验收**。

### 4.3 波及面清单

- Parser/AST：`TraitDecl`/`ImplDecl`/约束语法；fmt（trait/impl 块缩进 = 现有 type 块规则）。
- LSP：trait 方法 hover/跳转（方法 → trait 声明与所在 impl 两个目标）、补全
  （方法进 rank "1" 函数池）、约束渲染。
- 教程新章 + spec 新 §（放 §6 效果系统之前，编号顺延或作 §5.5）。
- `dawn doc`：trait/impl 出文档。

## 5. v1 范围表

| 进 | 不进（защ何时） |
|---|---|
| trait/impl/约束/默认方法 | 条件 impl（v2，Show 迁移的前置） |
| 字典传递 + 具体调用去虚化 | 单态化（性能刀，需求出现再说） |
| `< <= > >=` 桥接 Ord | `==`→Eq、`+`→Num（真实需求驱动） |
| derive Ord | derive 用户自定义 trait（远期） |
| stdlib：Ord[Int/Float/String] + `sort/sort_by/max/min/max_by/min_by` | 迭代器协议（等条件 impl + 关联类型论证） |
| 孤儿规则 + 程序级查重 | dyn/trait 对象（ADT/record-of-fns 惯用法顶住） |
|  | 多参数 trait、关联类型、supertrait |

## 6. 验收样例（先行，`examples/traits/`）

```dawn
use core/list.{sort, max_by}

type Version = { major: Int, minor: Int, patch: Int } derive Show

impl Ord[Version] {
  fn cmp(a: Version, b: Version) -> Int =
    if a.major != b.major { a.major - b.major }
    else if a.minor != b.minor { a.minor - b.minor }
    else { a.patch - b.patch }
}

type Task = { name: String, priority: Int } derive Show, Ord   # derive = 字段字典序

fn newest(vs: List[Version]) -> Option[Version] = max_by(vs, fn(v) => v)   # 约束转发

pub fn main() -> Unit !io = {
  let vs = [Version{major:1,minor:2,patch:0}, Version{major:1,minor:10,patch:3}]
  println(to_string(sort(vs)))                 # 泛型 sort 走 Ord[Version]
  assert vs[1] > vs[0]                         # 运算符桥接
  println(to_string(sort([3, 1, 2])))          # 内建标量 impl，直接 INVOKESTATIC
}
```

验收：JVM 与 native 输出一致；`sort` 对 record/标量都工作；错误路径三连
（缺 impl、重复 impl、孤儿 impl）进 golden 报错套件。

## 7. 刀法（预估 6 刀，均含测试）

1. **Parser/AST/fmt**：trait/impl/约束语法 + fmt 幂等（golden/fmt 加样例）。
2. **Checker 注册与查重**：TraitInfo/ImplInfo、孤儿/重复/签名匹配校验、约束入 FnSig；
   报错 golden。
3. **Checker 消解**：调用点两规则、witness 标注、比较运算符桥接、comptime 禁令。
4. **CodeGen**：witness 接口/单例/隐藏参数/去虚化；JVM+native 对拍。
5. **stdlib + derive Ord**：prelude impl、sort 族函数（归并，稳定排序）、derive。
6. **收尾**：LSP（hover/补全/跳转）、教程、spec 定稿、验收样例入库、
  playground 示例加一个 traits。

预计新增测试 ~80-100 项（对齐 M4 的量级）。

## 8. 开放问题（已全部按推荐定稿）

1. **`cmp` 返回类型**：`Int` ✅（负/零/正 = 小于/等于/大于）。
2. **关键字**：`impl` ✅（硬关键字，`trait` 同）。
3. **约束语法**：`[T: Ord]`，多约束 `[T: Ord + Show]` ✅。
4. **derive 多 trait 语法**：`derive Show, Ord` 逗号并列 ✅。

## 9. 实现定稿记录（2026-07-13）

六刀提交：`001c971`（语法）→ `e6925d0`（注册/一致性）→ `3849fea`（消解/桥接）→
`d878b02`（codegen 字典）→ `897e750`（stdlib + derive Ord）→ 本刀（收尾）。
实现与设计稿的偏差与补充判定，按发现顺序：

- **跨模块重复 impl 结构性不可能**：模块 DAG + 孤儿规则意味着一个 (trait, 类型)
  的两个合法归属模块互相需要对方的名字（成环）。第三方模块的「重复」在到达
  一致性检查前就被孤儿规则拦截。一致性表仍保留——拦同模块重复、支撑消解。
- **prelude 交互**：`Ord` 是 prelude trait，`Int`/`Float`/`String` 的 impl 随语言
  提供；`impl Ord[Bool]` 无处可写（trait 与主体都在 prelude）——Bool 保持不可
  排序，这是有意的。用户 trait 以标量为主体的 impl 必须写在该 trait 的模块。
- **字典即隐藏局部**：受约束函数的每个（类型参数 × 约束）生成一个合成 Symbol
  （`dictOf` 标记、类型记作该 tvar、擦除后一槽），lambda 捕获走既有机制——
  `fold(xs, first, fn(acc, x) => ...acc < x...)` 里字典随捕获进闭包，零特判。
- **去虚化**：具体见证点直接 `invokestatic` 到 impl 静态方法；prelude 标量的
  `cmp` 内联为 `LCMP`/`DCMPL`/`String.compareTo`。仅 Forward（约束转发）走
  `invokeinterface`。
- **Float 的 cmp 与 NaN**：`cmp(NaN, x)` 采用 JVM `DCMPL` 语义（含 NaN 的比较
  偏负）。运算符路径维持既有语义：标量走原生指令，NaN 的每个有序比较均为 false。
- **v1 限制落地**：trait 方法/受约束函数不可作函数值（报错建议包 lambda）；
  comptime 拒绝带 witness 的调用与 impl 排序（字典是运行时构造）；`sort_by`
  无约束，comptime 可用。
- **derive Ord**：先于显式 impl 注册（撞车时报 duplicate impl 并提示来自 derive）；
  字段须为 Int/Float/String 或具 Ord impl 的类型（含跨模块、含其他 derive）；
  和类型先比构造器声明序（instanceof 标签），再逐字段；泛型主体拒绝。
- **stdlib**：`sort`/`max`/`min`（要求 `Ord`）、`sort_by`（自定义比较）、
  `max_by`/`min_by`（键要求 `Ord`，键缓存）；排序 = ArrayList 拷贝 + TimSort
  （稳定），极值平局取第一个。
- **测试规模**：六刀新增 ~120 项（parse 22 / check 35 / resolve 27+golden /
  run 11 / stdlib+derive 16 / 收尾若干），JVM 与 native-image 双跑验证。
