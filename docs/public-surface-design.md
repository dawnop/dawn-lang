# SEM-07：public API surface validator

> 状态：**current / accepted design，阶段一与阶段二已落地** —— 本文固定 SEM-07 的
> audience、验证顺序、类型遍历、导出 metadata、工具消费与三阶段落地边界；实现不得用
> 会穿透 opaque representation 且遗漏函数 effect row 的通用类型 walker 代替专用验证器。
> 落地后的实现现状、两处刻意保留的临时件与两条今天没有见证者的分支，见 §十五。

## 一、问题与目标

当前声明上的 `pub` 只回答“入口是否导出”，没有回答“入口公开以后，签名中的每个身份是否也
能被同一批调用者命名”。因此声明模块可能接受下列接口，使用模块却无法写出参数、约束或效果：

```dawn
type Secret = | Secret
trait Hidden[T] { fn hidden(x: T) -> Bool }
effect PrivateAsk { fn ask() -> Int }

pub fn leak(x: Secret) -> Int = 0
pub fn bounded[T: Hidden](x: T) -> T = x
pub fn raises() -> Int !PrivateAsk = 0
```

SEM-07 增加一个 public surface validator。它验证的是**已解析身份构成的可书写契约**，不是
重新解析语法，也不是从 checker 全表删除私有信息。目标固定为：

1. 每个公开 root 的每条类型、trait 与 effect 引用都至少覆盖 root 的 audience；
2. opaque 的名义身份与显式参数公开，但 representation 始终停在声明模块内；
3. observable impl 与普通声明走同一套 audience 判定；
4. exporter 在 body check 前完成验证，body 的私有实现细节不进入 public surface；
5. `dawn doc` 与 LSP 只消费通过验证的结果，不各自复制一份可见性规则。

## 二、唯一 audience 模型

全实现只允许下列三种 audience，不另造布尔 `is_visible`、`is_std` 或“近似 public”集合：

```text
World
StdOnly
Module(owner)
```

- `World`：任何正常使用模块都可命名；普通模块的 `pub` 声明、公开 compiler-owned builtin、
  公开 prelude 身份与合法 Java identity 属于这里。
- `StdOnly`：仅捆绑标准库内部可命名；被 internal-std 模块边界保护、但需要跨 std 模块共享的
  `pub` 身份属于这里。
- `Module(owner)`：只有声明模块 `owner` 可命名；未写 `pub` 的名义类型、trait、effect 与
  opaque identity 属于这里。

可见性判断写成“被引用身份是否覆盖 root audience”，而不是比较枚举序号：

| identity audience | `World` root | `StdOnly` root | `Module(m)` root |
|---|---:|---:|---:|
| `World` | 是 | 是 | 是 |
| `StdOnly` | 否 | 是 | 仅当 `m` 是 std 模块 |
| `Module(owner)` | 否 | 否 | 仅当 `m == owner` |

公开 root 的 audience 由其真实导出边界决定：普通模块是 `World`，internal-std 模块是
`StdOnly`。私有声明不是 surface root；`Module(owner)` 仍必须存在，因为 opaque
representation、声明模块内解析和诊断路径需要准确表达“谁可以看”。builtin、prelude、依赖
模块与本地声明都必须先归一为这三种值，validator 不得用“不是本地 id 就当 public”的捷径。

## 三、checker 顺序：先 exporter，后 body

单模块检查顺序固定为：

1. 注册声明身份，解析类型参数、签名、ADT 字段、alias target、trait/effect method 与 impl
   header，得到不依赖 body 的完整 header metadata；
2. 运行 public surface validator；无泄漏时由 exporter 生成**已验证**的 `ModExports`；
3. 再检查 function、const initializer、trait default、impl method 与 test body；
4. 模块有任意诊断时不交付给依赖模块，但不得把 body check 提前到 surface validator 之前。

这个顺序有两个目的。第一，公开契约的错误稳定落在声明处，不受 body 中无关错误和推断路径
影响。第二，doc/LSP/exporter 共用同一份 header 结果，不必等 body 才重新猜公开面。

“body check 前验证”不等于忽略 header 完整性：当前 `pub fn` 已强制显式返回类型；const 也必须
先得到最终声明类型，才能验证 root。若未来允许 public header 依赖推断，应把**签名推断**与完整
body validation 拆开，而不是把 exporter 挪回所有 body 之后。

## 四、surface roots

validator 必须覆盖下列全部 roots；列表是闭集，新增公开声明种类时必须显式扩表并配负控：

| root | 必查内容 |
|---|---|
| `pub fn` | 类型参数 bounds、参数、返回值、完整 effect row |
| `pub const` | 最终声明类型；initializer 仍归 body check |
| `pub` ADT/record | 所有 constructor field 类型 |
| `pub alias` | transparent alias 的 resolved target |
| `pub opaque` | type parameter bounds；不查 representation。opaque 的实际 args 在每个引用点检查 |
| `pub trait` | trait 参数/bounds、associated type constraints、全部 method signature 与 effect row |
| `pub effect` | 每个 operation 的参数、返回值及其签名中的嵌套 effect row |
| observable impl | impl trait、subject、generic constraints、associated binding RHS |

impl 没有 `pub` 拼写。一个 impl 当且仅当其 trait 与 subject 对某 audience 都可见、且它会进入
该 audience 可用的求解 metadata 时，才是该 audience 的 observable root。private trait 或
private subject 的 impl 只在 `Module(owner)` 内可见，不因 associated binding 使用私有类型而
报 public surface 错误；反之，observable impl 的私有 bound 或 associated RHS 必须拒绝。

impl method 的公开签名由 trait method 契约拥有，method body 仍是私有实现细节。若实现以后
允许 impl 覆盖额外可见签名，那一刻必须把它作为新 root 单独设计，不能静默混入本刀。

## 五、专用类型遍历

### 5.1 基本规则

surface validator 使用专用、穷尽 `Ty` 的 walker，并同时携带 root audience 与最短路径。

- 标量、`Never`、类型变量与合法 Java 类型直接通过；`TyError` 跳过，避免在既有错误上级联。
- `List`、`Map`、`Set`、`Array` 等容器递归所有参数。
- tuple 递归每个元素。
- function type 递归每个参数、返回值，**并递归完整 effect row**。
- effect row 的变量/base 不代表名义可见性；每个 named effect label 检其 identity audience。

### 5.2 `TyAdt`、alias 与 `TyAssoc`

`TyAdt(identity, args)` 只检查 nominal identity 与每个实际 `args`，**不展开 ADT 字段**。
字段由该 ADT 自己作为 root 时检查；在引用点展开会令递归 ADT 成环，也会把“公开名义类型可被
引用”错误升级成“每次引用都重验整份定义”。

transparent alias 必须展开 resolved target。私有 transparent alias 若完全展开为公开类型，
不会把 alias 自己当 nominal identity；展开后触及 private identity 才拒绝。不得因 alias 名字
没有 `pub` 就拒绝，也不得停在 alias 名字上漏掉 target。

`TyAssoc(subject, trait, name)` 检查 `subject` 与 `trait` identity。associated member name 没有
独立 audience；它的可书写性由 subject 与 trait 共同决定。两边都必须有各自 owning mutant。

### 5.3 `TyOpaque` 是硬边界

`TyOpaque(identity, explicit_nominal_args, representation)` 的规则固定为：

1. 检查 opaque identity 是否覆盖 root audience；
2. 递归每个**显式 nominal argument**；
3. **绝不进入 representation**，无论 opaque 在本模块内是否可展开，也无论通用 walker 平时
   为 equality、布局或 codegen 会不会 peel target。

因此以下接口合法：

```dawn
type SecretRep = { bits: Int }
pub opaque type Token[T] = SecretRep
pub fn token() -> Token[Int] = ...
```

而 `Token[Private]` 仍非法，因为调用者无法写出显式参数 `Private`。generic opaque arguments
**不是 existential**：`Token[Int]` 与 `Token[String]` 是不同实例，参数参与替换、相等、统一、
显示、impl key 与 surface validation。不能把“representation 不公开”误读成“类型参数也隐藏”。

现有会穿透 opaque target 的 `ty_map_children`、`ty_any_child`、`peel_opaque` 或同类通用 walker
明确禁止复用：它们服务表示/equality 等别的语义，而且至少有一类还不会检查 `TyFn` 的 effect
row。为它们加开关会把两个相反的 opaque 契约塞进一份遍历，仍容易在新增 `Ty` variant 时漏项。

## 六、效果规则

普通 `pub` API 可以携带 public named effect。调用方可以导入、传播或 handle 该 effect，因而
不能把“公开 API 必须纯”当成 SEM-07 规则。

```dawn
pub effect Ask { fn ask() -> Int }
pub fn query() -> Int !Ask = ask()
```

private effect 出现在 `World`/`StdOnly` surface 中必须拒绝。唯一额外封闭规则是入口
`main`：它没有调用者提供 effect label，故 `main` 只能有空 label 集。这条由 main check
唯一拥有；SEM-07 只做 identity audience 判断，不重复发第二条诊断，也不把 `!io` 等 base
规则混入 label 可见性。

## 七、`ModExports`、doc 与 LSP

### 7.1 保留完整 metadata

`ModExports` 继续保留导入、类型解析、字典求解和后端所需的完整 metadata，包括
`effect_infos`、`impls`、`adt_infos`、`trait_infos`、resolved aliases 与身份映射。SEM-07 是
验证，不是裁剪；不能通过删除 private metadata 让泄漏“看不见”，也不能把错误推迟到 importer。

exporter 产物必须带“已经按哪个 audience 验证”的明确结果或等价类型保证，doc 与 LSP 只能
消费这份结果。它们不得从 AST 的 `is_pub`、`local_impls` 或完整 metadata 各自重建 surface。
若模块未通过验证，就没有可供这两个消费者发布的 surface。

### 7.2 本刀的 doc 边界

`dawn doc` 的 JSON schema 本刀不扩展：字段名、层级与已有 declaration 表示全部不变。唯一行为
改动是 `impls` 数组只保留对文档 audience 可见的 observable impl，过滤 private trait/private
subject impl。不是给 impl 新增结构化字段，不是输出 audience，也不是借机重排 JSON。

LSP 的 import completion、hover、definition 与 workspace symbol 使用 validated exports；源文件
尚未形成已验证模块时可保留语法级本地降级，但不得把降级结果宣称为跨模块 public surface。

## 八、诊断与 span

每个独立语法出现位置报告一次，按声明和 source span 稳定排序；alias 展开或递归结构回到同一
span 时去重，避免刷屏，但不能只报每个 root 的第一项而迫使用户逐次编译。诊断主消息点名 root、
private identity kind 与名字，hint 给出最短路径及可执行修法，例如：

```text
public function `read` exposes private type `Secret`
hint: function `read` return type -> list element -> private type `Secret`;
      make `Secret` public or remove it from this public surface
```

span 固定落在公开 header 中**最内层违规引用**：type 泄漏落违规 `TypeRef` token，bound 落
`Bound.lo..hi`，field/associated binding 落 RHS 中的违规 token，alias 落公开 target/use 中的
违规 token并在消息显示展开路径。named effect 当前 AST 只保留字符串，阶段二必须引入带 `lo/hi`
的 `EffectRef`，不能长期把 function 名当精确 span；在该结构落地前只允许以 root 名作明确的临时
fallback。observable impl 若确无更窄 token 才落 impl header。不要落在 private 声明或整文件。
`main` effect 的既有专属诊断继续由 main check 拥有。

同一 root 的 `TyError` 不产出 SEM-07 诊断；其他 header 诊断存在时，validator 可跳过被 poison
的 root，但不能因此跳过同模块中独立、完整的 root。是否整 pass fail-fast 必须以“无级联且不漏
独立泄漏”为准，不用全模块 `diags` 非空作为粗粒度开关。

## 九、三阶段实现

### 阶段一：opaque arguments

- 把 `TyOpaque` 固定为 identity、owner、显式 nominal args、representation 的形状；
- args 进入替换、相等、统一、显示、`type_args_of` 与 impl key；
- representation 仍只供声明模块内语义、lowering 与后端读取；
- 先钉 phantom/generic opaque，证明 args 不是 existential，且不改变运行期表示。

这一阶段不引入 surface 拒绝；它先补齐 validator 必须观察、但旧类型值可能丢失的信息。

### 阶段二：visibility pass

- 引入唯一 `Audience = World | StdOnly | Module(owner)` 与身份 audience 查询；
- 让 header effect atom 保留 `EffectRef { name, lo, hi }`，供 surface 诊断精确定位；
- 在 header 完成、body check 前运行专用 walker；
- 覆盖全部 declaration roots 与 observable impl；
- exporter 只从已验证 header 生成 `ModExports`，完整 metadata 不裁剪；
- 接通稳定诊断/span，并为每条新拒绝跑 compiling mutant。

### 阶段三：doc filter 与规范

- doc/LSP 改为消费 validated exports；
- doc JSON 仅过滤不可见 impl，不扩 schema；
- 更新中文规范与英文译本，写清 audience、opaque args、公开 effect 与 `main` 例外；
- 在阶段二行为稳定后再判断 doc JSON/LSP 是否需要 `Emit-Change`，不得预写声明。

三阶段可各自提交，但阶段一必须先于阶段二；阶段三不得反向成为 checker 可见性的事实源。

## 十、兼容与迁移

这是对过去不合法 public surface 的收紧。合法程序的类型、Core IR、JVM/C ABI 与运行期表示不应
改变；generic opaque 的 args 补全可能改变诊断显示和内部 identity key，但不能把 representation
带进 public metadata。

迁移顺序：先在仓库、packages、examples 与已知下游扫描泄漏；对每个命中只能选择把身份提升到
对应 audience、把 API 改为公开 wrapper/opaque、或收回 root 的 `pub`。不得自动把 private
声明改成 `pub`，也不得静默删导出项。internal std API 只需满足 `StdOnly`，不能为过门禁误升到
`World`。

旧 seed 不认识带 args 的 `TyOpaque`，所以阶段一若触及 selfhost 可用语言/metadata 形状，要按
种子纪律安排代际；但它不是语言表面语法新增，不应凭猜测要求一次 release。是否发生 emitted
bytes、Core、CLI、doc JSON 或 LSP 差异一律由门禁实测决定。

## 十一、正例与反例

### 11.1 必须通过

```dawn
type Rep = { raw: Int }
type Local = | Local

pub opaque type Id[T] = Rep
pub alias PublicId = Id[Int]

pub effect Ask { fn ask() -> Int }
pub fn query(id: Id[Int]) -> Int !Ask = ask()

trait LocalTrait[T] { type Item; fn item(x: T) -> T.Item }
impl LocalTrait[Local] {
  type Item = Local
  fn item(x: Local) -> Local = x
}
```

它同时证明：opaque representation 可私有、显式公开 args 可用、函数 effect 被检查但 public
effect 合法、private trait/private subject impl 不可观察而不报错。

### 11.2 必须拒绝

```dawn
type Secret = | Secret
trait Hidden[T] { fn hidden(x: T) -> Bool }
effect PrivateAsk { fn ask() -> Int }

pub opaque type Box[T] = Int
pub alias Leaked = List[Secret]
pub fn bad_box() -> Box[Secret] = ...
pub fn bad_assoc[T: Hidden](x: T) -> T.Item !PrivateAsk = ...
```

至少分别得到 alias target、opaque argument、private trait 与 private effect 的 owning 诊断；
不得因 `Box` 自己公开就放过 `Secret`，也不得穿透 `Box` 的 `Int` representation。

另有独立反例：`pub fn main() -> Unit !Ask` 即使 `Ask` 是 public 也由 main check 拒绝；普通
`pub fn query() -> Int !Ask` 必须通过。

## 十二、compiling mutants 与唯一 owning assertion

负控要求 mutant 编译器自身先成功 build 并能运行；“mutant 编译失败”不算验证。每个 mutant
只改变一条规则，并且恰有一个 owning assertion 首先变红，不能靠一份大 golden 同时认领多条：

| # | compiling mutant | 唯一 owning assertion |
|---:|---|---|
| 1 | `TyOpaque` 递归 representation | `public_opaque_private_rep_is_accepted` |
| 2 | `TyOpaque` 跳过显式 args | `public_opaque_private_arg_is_rejected` |
| 3 | generic opaque args 按 existential 比较 | `opaque_phantom_instances_remain_distinct` |
| 4 | `TyAdt` 跳过 nominal args | `adt_private_argument_is_rejected` |
| 5 | `TyAdt` 递归字段 | `recursive_public_adt_is_accepted_once` |
| 6 | transparent alias 不展开 target | `transparent_alias_private_target_is_rejected` |
| 7 | `TyAssoc` 跳过 subject | `assoc_private_subject_is_rejected` |
| 8 | `TyAssoc` 跳过 trait identity | `assoc_private_trait_is_rejected` |
| 9 | function type 跳过 effect row | `nested_function_private_effect_is_rejected` |
| 10 | 所有 public effect 一律拒绝 | `ordinary_public_effect_is_accepted` |
| 11 | private effect label 一律放过 | `private_effect_is_rejected` |
| 12 | observable impl 跳过 constraints | `observable_impl_private_bound_is_rejected` |
| 13 | observable impl 跳过 associated RHS | `observable_impl_private_assoc_is_rejected` |
| 14 | private impl 被当 observable | `private_impl_private_assoc_is_accepted` |
| 15 | doc 不过滤不可见 impl | `doc_json_omits_private_impl` |
| 16 | exporter 挪到完整 body check 后 | `surface_diag_precedes_unrelated_body_diag` |
| 17 | 只在 importer 使用点检查 | `exporter_rejects_unused_private_surface` |

容器、tuple、function 参数与返回值还要有正常合同覆盖；若实现为各自独立分支，则每个分支再加
自己的 compiling mutant，不能让 `List[Secret]` 一例冒充所有递归形状。源码 grep/结构断言只可
补充第 16 条顺序约束，不能代替行为 mutant。

## 十三、验收

实现与验收必须从 clean checkout 开始；先记录 `git status --porcelain` 为空，并确认起始不存在
`build/dawn-selfhost.jar` 与 ignored ASM JAR，再从当前 seed 自建，避免别人的未提交产物、旧 jar
或已存在的 `Emit-Change` 声明替本刀挡灯。每阶段至少运行最窄合同与 selfhost 测试，最终完整
验收固定包含：

```bash
./bin/dawn test selfhost
./scripts/selfhost-core-diff.sh
./scripts/selfhost-prev-diff.sh
```

- **Core**：合法程序的归一化 Core 应不变；若变化，逐项解释，不得直接 `--record` 掩盖。
- **N/N-1**：当前编译器与上一 release 对同一 HEAD 语料的行为差异必须实测，尤其 generic
  opaque metadata、checker 诊断、doc 与 LSP 消费路径。
- **Emit**：运行仓库规定的 emit/run/fmt/LSP 差分门禁；只有真实字节差异出现、且 owning
  gate 已先看过红，才按 `scripts/emit-labels.txt` 的闭集逐条写 `Emit-Change(<label>)`。
- **负控**：至少上表 17 个 compiling mutants 全部各自打红唯一 owning assertion；原编译器
  同一合同全绿。
- **doc**：运行 `python3 scripts/doc-check.py`；阶段三另对 doc JSON 做 schema 不变与 private
  impl 缺席的精确断言。

clean checkout、Core、N/N-1 与 Emit 四类证据缺一不可。单跑 `./bin/dawn test selfhost` 不足以
证明没有输出变化，单跑差分也不足以证明新拒绝真的由目标规则拥有。

## 十四、不做的（记录理由）

- 不复用会穿透 opaque target 且遗漏 function effect 的通用 walker：契约相反，漏检已知。
- 不裁剪 `ModExports` metadata：import、求解与后端仍需要完整身份表。
- 不把 generic opaque args 当 existential：它们是显式 nominal identity 的一部分。
- 不禁止普通 public effect：公开 effect 本来就是跨模块传播与处理的能力。
- 不检查 body 中使用的 private 实现细节：surface 只约束 header，body 有自己的 checker。
- 不在本刀扩 doc JSON schema：只过滤不可见 impl，缩小兼容面。
- 不让 doc 或 LSP 重新决定 visibility：它们只能消费 checker 的 validated result。
- 不预写 `Emit-Change`：先跑门禁看到真实差异，再按唯一 label 声明。

## 十五、实现现状（阶段二落地后记录）

本节只记录实现事实，不改变以上任何裁决。

### 15.1 已落地

阶段一（`TyOpaque` 带 `args`）与阶段二（visibility pass）都在 selfhost 里：
`check/types.dawn` 的 `Audience = AWorld | AStdOnly | AModule(owner)` 与 `audience_covers`
是唯一的可见性词汇；`AdtI`、`EffectI` 与 `AliasE` 各存一个 `audience` 字段，由**声明模块**
决定后随 `ModExports` 整体嫁接过去，所以导入方不必重新解释别人的 `pub`；`TraitI` 是四种身份
记录里唯一本来就同时带 `is_pub` 与 `owner` 的，因此它的 audience 由 `trait_audience` 推导，
存一份副本只会有机会和导出器读的 `is_pub` 说法不一。校验器是 `check/passes.dawn` 的
`pass_export_surface`，调用点在 `check_module` 的 `pass_main_check` 之后、任何 body 之前。

`Array` 的 `StdOnly` 不是一句约定：`std/pvec` 的 `pub fn to_array` 合法，而同样在 std 里、
同样能拼写 `Array` 的 `std/bytes` 若加一个 `pub fn f(a: Array[Int])` 会被拒——两条都在
`scripts/export-surface-contract/run.sh` 里，前者靠捆绑 std 能加载证明，后者靠一份加了料的
std 副本证明。二值公私模型两条都表达不了。

### 15.2 span：`resolve_type` 侧记的边表

§八 要求诊断落在最内层违规 token，而校验器读的是已解析的 `Ty`，不带 span。实现的做法是
让 `resolve_type` 在 header 阶段顺手记一棵与 `Ty` 同构的 `TySpan { lo, hi, kids }`，按每个
`TypeRef` 自己的 `(lo, hi)` 存进 `Cx.ty_spans`——那是一个天然唯一的键，两个类型引用不可能
占同一段偏移。走查时 `Ty` 与 `TySpan` 并行下降，`kids` 用完就停在作者真正写下的那个 token 上。

这条路是相对「事后拿 AST 与 `Ty` 对着走」选的：透明别名展开后两棵树不再同构，`List[Secret]`
底下没有任何 `TypeRef`，事后对齐必然失真。侧记则天然正确：别名节点的 `kids` 是空的，于是
诊断落在别名名字上，展开路径由消息给出——正是 §八 要的那两件。

### 15.3 两件临时的、点名在案的

- **`EffectRef` 尚未引入。** AST 仍把声明的 effect 存成裸字符串，所以一条 effect label 的
  泄漏诊断落在 **root 的名字 token** 上，而不是那条 label 上。§八 允许这个 fallback，
  §九 阶段二把 `EffectRef { name, lo, hi }` 列为要做的事——它没做，这里点名它是临时件，
  不是成品。`surface_sig_leaks` 里的注释同样点名。
- **mutant #15（`doc_json_omits_private_impl`）属于阶段三。** 它拥有的规则是 doc 过滤器，
  过滤器还不存在，所以这个 mutant 没有东西可以拿掉；它与过滤器同批落地。

### 15.4 两条今天没有见证者的分支

§5.2 要求 `TyAssoc` 的 subject 与 trait 各有 owning mutant，§5.1 要求递归函数类型的完整
effect row。实现里两条分支都在，但今天的语言写不出它们的反例：

- **projection 的 subject 永远是刚性类型变量。** 归约是急切的（assoc-types-design D3），
  ground 类型里不会留下 `TyAssoc`，而 `TAssoc` 的 subject 在语法上只能是一个裸名字，
  必须解析成作用域里的类型参数。所以 subject 不可能是私有身份。
- **写下的函数类型不能命名声明的 effect。** `refuse_written_label`
  （effects-soundness-design §4.1）在解析函数类型时就拒绝，并把行降成 base，
  所以 header 里的 `TyFn` 的 label 集恒为空。

两条分支保留，因为规则说的是类型，不是今天的 parser 允许作者写什么：其中任一条一旦放宽，
遍历已经是对的。它们没有 compiling mutant，因为 mutant 必须先编译并运行**再**打红一条断言，
而这两条今天打不红任何东西——记在这里，好过用一个永远绿的断言冒充负控。
