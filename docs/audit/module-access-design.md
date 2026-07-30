# 模块限定访问与「加载哪些源码」

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **LANG-06（P2）** 与 **LANG-07（P2，加载范围那一半）**。
> 状态：**proposed，可做**——与 [`../native-backend-plan.md`](../native-backend-plan.md)
> 完全不重合（纯 checker 前端的事，不碰 emit、不碰运行时）。
> 台账见 [native-plan-overlap.md](native-plan-overlap.md)。

两条都在问「模块这个边界到底管什么」：一条是**引用**模块里的东西时能写什么，
一条是**加载**哪些模块。

## 一、问题

### 1.1 `m.X` 只对函数有效（LANG-06）

`docs/spec.md` §10 只允许 `alias.fn(args)`。类型、构造器、常量必须选择性导入到本地：

```dawn
use json/value as v
use json/value.{Json, JStr, JObj}      # 类型和构造器只能这样

fn f(x: v.Json) -> Int = ...           # 不行
fn f(x: Json) -> Int = ...             # 只能这样
```

后果：

- 同一个模块 API 被迫用两套访问风格（函数走 `v.`，类型走裸名）；
- 类型和常量污染本地命名空间——`packages/web/src/server.dawn` 的 import 块里
  `use types.{Request, Response, HttpError, Handler, Middleware, RouteMeta,
  http_error, error_response, streaming}` 就是这条规则逼出来的；
- 自动补全和批量重命名更难：裸名 `Request` 不带来源信息。

### 1.2 目录模式无条件加载全部源码（LANG-07）

`docs/spec.md` §10.1 要求加载 `src/` 下全部 `.dawn`，未引用的模块也要检查，
依赖图完全禁环。

对小项目这能防 bit-rot（一个没人 import 的模块烂掉了也会被发现），
这个收益是真的。但它同时挡住：

- 大型工程（编译时间随仓库总量走，不随入口闭包走）；
- 平台专用模块（一个只在 Linux 编得过的模块会让所有人编不过）；
- 生成代码、仅测试依赖。

> **2026-07-30 落地进度**：步 1（`m.T` 类型位，ee9bb0a）与步 2（`m.C(..)` 模式位，
> 6011d81）已发——两处都在名字解析层终结，checked 树与两后端所见与本地拼写完全相同。
> **步 3 已落地（同日，晚于下面这段记录）**：`CConstRef`/`XConstRef` 带 owner，空串
> 表示「在本模块视图里解析」（即此前的全部情形，于是现有程序发射逐字节不变），
> 非空则是声明模块的路径，`merged_consts` 另按 `<模块>.<NAME>` 归档。双后端语料
> `qual_const` 钉住「限定常量与同名局部常量并存」这一从前表达不出的情形。
> **表达式位置的 `m.C` 也已落地（同日）**：`check_ctor_call` 收一个「已解析的构造器」
> 参数，于是限定写法把 key 注进去、其余（字段名/arity/spread/泛型实例化/构造器作值）
> 全部走同一段代码——**复用而非合并**，故不可能与不带限定的写法漂移，也因此不必等
> 「调用路径统一刀」。`m.C(a, b)` 走的是同日新增的一般后缀应用（`EApply` over
> `EFieldAcc`），由 `check_apply` 路由进构造检查——两把刀在此咬合。双后端语料
> `qual_ctor` 覆盖有字段/泛型/nullary/同名局部构造器四种形状。
> **至此 LANG-06 四个位置（类型、模式、常量、构造器）全通。** 原始踏勘记录如下：
>
> **步 3（`m.CONST`）实测出一个文档没预见的墙**：Core 的 const 身份是扁平简单名
> （`CConstRef(name, ty)`，JVM/C 两后端都按「本模块 merged_consts 视图」查值），
> 选择性导入靠 `imported_names[name]=owner` 把值并进视图——限定访问若走同一注入，
> `g.MAX` 会与本地/他处导入的同名 `MAX` 相撞。诚实修法 = `CConstRef` 带 owner
> （镜像 `CFnRef(owner, name, ty)`），连动 XConstRef/interp/两后端/merged_consts
> 与 core-golden——单独排一刀，别塞在放宽系列的尾巴上。表达式位置的 `m.C`
> （构造器作值）依赖同一次梳理，一并排。

## 二、方案

### 2.1 `m.X` 推广到类型、构造器、常量（LANG-06）

`use a/b as m` 之后，`m.` 后面可以跟模块导出的**任何** `pub` 名字：

```dawn
use json/value as v

fn f(x: v.Json) -> String =
  match x {
    v.JStr(s) -> s
    _ -> ""
  }

const LIMIT: Int = w.DEFAULT_MAX_BODY
```

三个位置分别要改：

| 位置 | 现在 | 之后 |
|---|---|---|
| 类型标注 | `resolveType` 只认裸名与内建 | 认 `m.T` |
| 模式 | 构造器模式只认裸名 | 认 `m.C(..)` |
| 表达式 | `m.f(args)` 已支持 | 加 `m.CONST`、`m.C`（构造器作函数值） |

`Cx` 已经有 `module_exports: Map[String, ModExports]`（存的就是导出面，
今天用于调用诊断），所需信息都在。

**与点调用的冲突**：`v.Json` 里 `v` 是模块别名还是局部变量？
spec §10.3 对模块别名同名**早已拒绝**——一个别名和一个局部变量同名是编译错误。
所以这里不产生新歧义，沿用既有规则。

**与 SYN-06 的关系**：`r.f(x)` 的字段/函数歧义规则不变。
模块别名不是值，走的是另一条解析路径。

### 2.2 加载范围：把「检查全仓」与「构建入口闭包」拆开（LANG-07）

**保留**今天的默认行为——`dawn build`/`run` 仍然加载 `src/` 全部。
新增的是一个**收窄**的模式，而不是换掉默认：

```
dawn build <dir> --closure        # 只加载入口的 use 闭包
dawn check <dir>                  # 全仓（今天的行为，显式化）
```

理由：默认全仓是**对的默认**——bit-rot 防护是真收益，而遇到问题的是大型工程，
它们有能力显式说出自己要什么。反过来（默认闭包、可选全仓）会让小项目静默失去防护。

CI 的推荐用法写进文档：`dawn check` 守全仓，`dawn build --closure` 出产物。

**禁环不改**——见 §四。

## 三、为什么不顺手把 X 也改了

- **不引入「入口声明」到 `dawn.toml`**。spec §10.1 现在明说「目录约定即工程定义，
  不需要清单文件」。`--closure` 是命令行的事，不动那条约定。
- **不做条件编译**（`#[cfg(linux)]` 之类）。平台专用模块是 LANG-07 列的痛点之一，
  `--closure` 只能绕开它（不 import 就不编），不能解决「同一个模块两种实现」。
  那是另一个特性。
- **不改 `use` 的语法**。`use a/b as m` 已经够了，本文只是让 `m.` 后面能跟更多东西。

## 四、不做的（记录理由）

- **允许 type-only cycle**（审查建议的一半）。**驳回**，理由在
  codebase-audit.md 的 LANG-07 里，这里展开：Dawn 的编译单元是模块，
  求值顺序按拓扑序定义（spec §10.5），而顶层 `const` 的 comptime 求值**依赖这个顺序**。
  要支持 type-only cycle 就得把「类型引用」与「值依赖」拆成两张图，
  分别判环——checker 的结构性改动，换来的是这个仓库还没遇到过的场景。
  真遇到了再说，那时它会有一个具体的例子，比现在的假设更值得改。
- **`m.*` 通配导入**。`use a/b.*` 把整个模块塞进本地命名空间——
  正是 §1.1 抱怨的「污染命名空间」的加强版。
- **让 `m.X` 在 `use` 之外也能用**（比如直接写 `json/value.Json` 不 import）。
  那会让「一个文件依赖哪些模块」不再能从 import 块读出来。
- **给 `--closure` 加缓存/增量**。那是另一个量级的工作（要设计失效判定），
  而 `--closure` 本身已经把「编译量随仓库总量走」这条改掉了。

## 五、落地点

| 步 | 文件 | 测试 |
|---|---|---|
| 1 | `selfhost/src/checker.dawn`：`resolveType` 认 `m.T` | 「`m.T` 解析到导出类型」「未导出的报错并说明」 |
| 2 | `selfhost/src/checker.dawn`：构造器模式与表达式认 `m.C`、`m.CONST` | match 用 `m.C(..)`；`m.CONST` 参与 comptime |
| 3 | `selfhost/src/parser.dawn`（若类型位置的 `.` 还没 parse） | parser 内联 test |
| 4 | `selfhost/src/main.dawn`、`analyze.dawn`：`--closure` 开关 | 一个「未被 import 的坏模块，`--closure` 能过、`check` 不过」的 test |
| 5 | `docs/spec.md` §10.1/§10.2、`CLAUDE.md` 常用命令 | — |

步骤 1–3 是**放宽**，现有代码全部继续编译，可以直接发。
步骤 4 是新增开关，同样不破坏。整份文档没有破坏性变更——
这是它优先级不高、但成本也低的原因。
