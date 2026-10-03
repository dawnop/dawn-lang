# 文档注释现代化：设计（D1–D5）

> 状态：current。文档注释这条线的总纲：`##` 的附着规则怎么收紧、`dawn doc` 发布什么、链接与示例怎么做、
> 哪些常见做法不做。D1–D5 已落地；D6（发布出去的示例只提公开名）等有了真实示例再评；D7（LSP 侧）、
> D8（`dawn doc --check` 解析散文围栏）另立。依据是 2026-10-03 的只读调研与裁决（仓外协作档，结论摘在 §1）。
> 规范条文在 [spec.md](spec.md) §1.2（文档注释）与 §3.4（以声明命名的测试），本文只讲为什么与怎么做。

---

## 1. 问题与判断

调研的一句话：**Dawn 的 `##` 不缺记号，缺「示例能跑」「引用能查」两件事。** 前者走 Zig 式 decltest
（示例是代码，由名字挂到声明上），后者走工具层的 `` [`name`] `` 链接检查（`dawn doc` 失败，不进编译器）。
两者都不碰注释的词法地位：spec §1.2「没有块注释，每一行都能独立切词」照旧成立。

调研推翻的前提（作为成果记下）：

1. `dawn doc` 输出 JSON，不是 Markdown；站点与编辑器才是渲染者。
2. 「可执行示例 = 让 `##` 里的代码块能跑」这个默认形状不适合 Dawn：示例应当写成以声明命名的 test 块（§6）。
3. 「弃用标记 + LSP 删除线」在只有一种诊断等级的语言里没有落点：弃用就是删除加 `std/moved.txt`。
4. lint 在 Dawn 里不能是编译警告，只能是工具失败或门禁。
5. 附着规则有一个真漏洞：行尾 `##` 会被下一行的声明认领（D1 修掉）。

## 2. D1：附着规则

- 行尾 `##`（代码后面的）不是文档；它所在的行对附着规则而言是代码行，于是不会被下一行的声明认领。
  理由：它说明的是本行的代码，读成下一行的文档是错位。实现是 `front/docs.doc_src_of` 只归档「本行行首
  到注释起点之间只有空白」的注释。
- `impl` 头算顶层声明的首行：紧接 `impl` 的 `##` 块是那个 impl 的，不是模块文档。
- spec §1.2 用调研的条文补全（整行、正文、附着、可附着的声明、模块文档、发布范围）。

## 3. D2：成员文档

- `dawn doc` 发布构造器、字段、trait 方法的文档（之前只有顶层声明有）；站点在条目下渲染成员行，hover 补字段。
- 修订（D2 验收）：构造器或字段与其所属声明写在同一行时**没有自己的文档**，JSON 给 `null`。理由：实测
  std+packages 的 78 条非空成员文档里 58 条是类型文档的复本（`Rounding` 一段 13 行复制 5 次）；rustdoc 的
  变体文档也只来自变体自己的 `///`。hover 在成员没有自己的文档时回退显示所属声明的，那是显示层的选择。

## 4. D3：pub 必有文档

std 与 packages 的每个顶层 `pub` 声明必须有 `##`，由 `scripts/pub-doc-check.py`（docs 作业）读 `dawn doc` 的
JSON 把关。模块文档不强制：packages 的文件用 `#` 头注释讲「为什么」（CLAUDE.md），强制模块文档等于
为门再写一段。

## 5. D4：符号链接

- 只认 `` [`name`] ``：在 CommonMark 里它是未定义的引用，按字面渲染，不认识它的渲染器照样能读。
  不把所有反引号里的名字当链接：仓里反引号里大多是代码片段，哪些算链接会无法预测。
- 在**文档所在模块的作用域**解析（本模块声明、`use` 别名、选择性导入、prelude、`Owner.member`），解析器
  `driver/doclinks` 由 `dawn doc` 与 hover 共用。坏链接让 `dawn doc` 以非零状态退出、不出 JSON；编译不读链接。
- 站点把链接渲染成页内锚点，指向页上没有的条目时建站失败。

## 6. D5：以声明命名的测试（可执行示例）

### 6.1 形状

`test` 后面除了字符串，还可以写本模块一个顶层声明的名字：`test f`、`test T`、`test T.Ctor`。这个测试就是
该声明的示例，`dawn doc` 把 `pub` 声明的示例发布在它的文档旁。

与 Rust 的「`///` 里写代码块，`rustdoc --test` 抽出来跑」逐项比（调研 §3.1 的对比表的结论）：

| | Rust 形状（注释里的代码块） | Zig 形状（`test name { ... }`） |
|---|---|---|
| 语言改动 | 无，纯工具 | `test` 后多接受一个名字 |
| 代码在哪 | 注释里：`dawn fmt` 不碰、编辑器无高亮补全跳转 | 普通代码：fmt、LSP、诊断照常 |
| 诊断位置 | 要从去掉 `## ` 的文本映射回源码 | 原生 |
| 哪些块跑 | 要块属性（`ignore`/`no_run`/`should_panic`），一套新的小语言 | 写成 test 就跑；不想跑就写成散文围栏 |
| 声明改名或删除 | 注释照旧，静默过期 | 名字解析失败，编译错误 |
| 与 §1.2 的原则 | 工具要跨行重建代码 | 完全不碰注释 |

Zig 形状每一行都不比 Rust 形状差，唯一的成本是一处加法式的语法扩展。

### 6.2 名字

- 三种写法：`f`（函数）、`T`（类型、类型别名、trait、effect；常量名同样是 TYPEIDENT，写作 `test LIMIT`）、
  `T.Ctor`（类型的构造器）。**构造器取 `T.Ctor`，不取裸 `Ctor`**：记录与它的构造器同名，裸写会有两种
  读法；「裸写的大写名字总是顶层声明」这条规则因此没有例外。`dawn doc` 的 JSON 也是把构造器嵌在类型下，
  `T.Ctor` 就是它在 JSON 里的位置。
- 不接受路径（`test a.b`、`test T.C.D`）：parser 报 `a test is named by a declaration of this module, not by a path`。
- 只能指向**本模块**的顶层声明（私有也算）或其构造器，比 Zig 的「作用域内任意声明」更严。理由：test 块本来
  就属于所在模块，指向别处的声明说明示例放错了地方；若导入的名字也算，同一个示例会随 `use` 的增删换主人。
- 其余成员（字段、trait 方法、effect 操作）不能命名测试：它们的示例就是所属声明的示例，多一种写法只多一处
  要解析的东西。真有需要时再加 `T.member`，与 `T.Ctor` 同一个形状。

### 6.3 实现

- **AST**（`front/ast`）：`DTest` 多一个字段 `example_of: Option[ExampleOf]`，`ExampleOf = { name, ctor }` 只记
  拼写。`name` 字段仍是 `dawn test` 报告用的标签：parser 写 `example f`，模块解析完后 `number_examples` 给
  同一个名字的第二个起编号（`example f #2`）。标签在 parser 里定，是因为它同时是 test 的身份
  （`identity` 的 `Named(TestDecl, name)`）与报告名，下游一律不必再知道这是哪一种测试。
  `nlo`/`nhi` 对这种测试指向名字（`T.Ctor` 整段）。改字段数连带改了所有对 `DTest` 的位置模式，包括
  `lsp/` 里三处（各加一个 `_`），没有改 LSP 的行为。
- **解析**（`check/decltests`）：作为头部的一个 pass（`pass_main_check` 之后、`pass_export_surface` 之前）。
  它只读 parse 树：规则就是「本模块的顶层声明」，parse 树正好是这张表；checker 的表里还混着导入与 prelude，
  只在报错时用来说明「这个名字是从哪儿导入的」。放在头部而不是测试体检查里：名字是关于声明的事实，与测试体
  无关，错误也因此排在所有函数体诊断之前，并且不进函数体调度器（及其在 `scripts/incremental-semantics-contract`
  里的参照实现）。报错样例：

  ```
  error: `test nope`: nothing in this module is declared as `nope`
    = hint: a test named by a declaration is its example: name a function, type, trait, effect or constant declared here, or give the test a string name
  error: `test trim` names `trim`, which this module imports from `std/str`
    = hint: an example belongs in the module that declares `trim`; give this test a string name to keep it here
  error: `test Shape.Circl`: type `Shape` has no constructor `Circl`
    = hint: did you mean `Circle`?
  error: `test Ask.Circle`: `Ask` is an effect, and only a type has constructors to name
  ```

- **`dawn test`**：不用改。测试照常进 `ModuleBodies.tests`，报告名就是标签：`PASS  node :: example deliver`。
- **`dawn doc`**（`doc.dawn` 的 `module_json`，项目模式与 `--stdlib` 共用）：fn、type、构造器、const、trait、
  effect 的对象在 `doc`（与 `links`）之后写 `examples`（按出现顺序的源码字符串数组），没有就不写键，于是
  没有示例的对象逐字节不变（与 D4 的 `links` 同一条省略规则）。`--builtins` 不写：它是手写分组的参考，
  站点用的是 `--stdlib`。`scripts/api-snapshot.py` 认这个键并与 `doc` 一起丢掉：示例是文档，体的改动不是 API 变化。
- **体源码怎么截**（`front/docs.example_source`，`dawn doc` 与将来的 hover 共用）：取花括号之间的文本；一行的
  去首尾空白；多行的，`{` 那一行与 `}` 那一行若只剩空白就丢掉，再去掉所有非空行共有的缩进和每行行尾空白，
  空行保留为空行，注释原样保留（它们是示例的一部分）。不重新格式化：示例就是写在那里的代码。
- **站点**（`site/src/gen/stdlib.dawn`）：条目文档之后、成员列表之前渲染一个 `api-examples` 块，小标题
  「Example」/「Examples」（中文页「示例」，两种语言的字放在 `Chrome` 表里），每个示例一个
  `<pre class="dawn api-example">`，高亮走 `highlight_dawn`。构造器的示例渲染在它的成员行里；只有示例、
  没有文档的构造器也有一行。没有示例的条目逐字节不变。packages 页（裁决 P2/P3）以后复用同一个 `entry`。

### 6.4 种子纪律与迁移

`selfhost/src` 与 `std/` 由种子编译，种子的 parser 不认 `test f`，所以要等带这个语法的 release 成为种子后才能
在那里写（[bootstrap.md](bootstrap.md)）。packages 由当前工具链编译，立刻能用：仓里唯一的文档示例
（`packages/tea-dom/src/node.dawn` 的 `deliver`）已搬成 `test deliver`，tea-dom 0.2.0 → 0.2.1（只动文档与测试，
patch）。原示例用 `tea_dom/dsl` 的 `on_value`，而 dsl 是写在 node 之上的，node 里的测试用不了它，所以示例改为
手写 `On { ... }` 记录，并且只用公开名字（`On`、`Value`、`deliver`），文档里留一句说明应用怎么写。

### 6.5 代价（实测）

见本文末「实测」一节。没有 decltest 的模块，新 pass 只是对 `module_tests` 的一次遍历；有的，每个 decltest 一次
对本模块声明表的线性查找。

## 7. 不做的（理由）

- **注释里的可运行代码块**（Rust 的 doctest 形状）：见 §6.1 的表。散文里的 ```` ```dawn ```` 围栏只是插图；
  「能被 parser 解析」的便宜检查是 D8，可选。
- **块属性**（`ignore`、`no_run`、`should_panic`）：不想跑的代码写成散文围栏，要跑的写成测试，不需要第三种。
- **示例只提公开名字的检查**（D6，SEM-07 的延伸）：示例在模块内作用域，看得见私有 helper，读者照抄会编不过。
  等有了真实示例再评，可能不需要；tea-dom 那一条已手工做到只用公开名字。
- **hover 显示示例**：留给 D7 之后的小刀（`front/docs.example_source` 已可共用）。
- **约定小节**（Panics / Errors / Examples / Effects）与小节 lint：效果与错误已经在签名里，示例由测试承担。
- **弃用标记**：只有一种诊断等级，弃用 = 删除 + `std/moved.txt`。重开条件：引入第二个诊断等级。
- **单独的模块文档记号**（`//!`、`////`）：第 1 行起的 `##` 块已经是模块文档。
- **文档做成值或属性**、**`dawn doc --html`**、**逐参数文档**、**放错位置的 `##` 报错**：调研报告里各有理由
  与重开条件；放错位置的 `##` 只是注释，报错会让注释影响编译。
- **裸 `Ctor` 命名测试**：§6.2。
- **测试指向别的模块的声明**：§6.2。

## 8. 状态

| 刀 | 内容 | 提交 |
|---|---|---|
| D1 | 行尾 `##` 不是文档；`impl` 头断开模块文档；spec §1.2 补全 | `a3923806` |
| D2 | `dawn doc` 发布构造器、字段、trait 方法文档；同行成员无文档 | `c358dd6f` |
| D3 | std+packages pub 必有文档，`pub-doc-check.py` 门 | `bc64fde8`、`22dc48e1` |
| D4 | `` [`name`] `` 链接：`dawn doc` 解析与失败、`links`、站点锚点、hover | `a0d94d5b` |
| D5 | 以声明命名的测试；`examples`；站点渲染；tea-dom 迁移 | （合并后回填） |

## 实测

（见下。）
