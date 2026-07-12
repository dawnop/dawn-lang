# M4 执行手册：工程能力（模块系统 / Map·Set / char / 项目构建）

> 本手册是 M4 里程碑的**完整执行方案**，语义决策已在第 1 节全部钉死。
> 执行者按刀序推进，一刀 = 一个 commit，提交前该刀验收项必须全绿。
> **凡是遇到本手册与 docs/spec.md 都没有钉死的语义决策：停下来问用户，不要自作主张。**

## 0. 总则（执行者必读）

- 工作目录 `~/workspace/dawn-lang`。构建前 `export JAVA_HOME="$HOME/tools/graalvm-community-openjdk-21.0.2+13.1/Contents/Home"`；用系统 `gradle`（仓库**没有** `./gradlew`）。
- 常用命令：`gradle :compiler:test`（全部测试）、`gradle :compiler:fatJar`（产出 `./bin/dawn` 用的 jar）、`gradle :compiler:test -DupdateGolden=true`（再生 golden 报错文本，再生后必须逐条 review diff）。
- **代码注释 / 报错 / CLI 输出一律英文；docs 一律中文。**
- **提交绝不加 `Co-Authored-By: Claude`** 或任何 AI 署名。
- 一刀一个 commit；全部刀完成后一次性 push。
- 当前基线：M3 完成，366 项测试全绿（`e684912`）。每刀只增不减。
- 新增的 `.dawn` 示例/夹具会被 `FmtTest` 扫到（examples 全量做幂等校验）——**新写的 example 源码提交前先过 `./bin/dawn fmt`**，否则 FmtTest 红。
- 现有代码锚点（动手前先读）：
  - `check/Analyze.kt` — 单文件入口 `analyze(source)`，产出 `Analyzed(module, diagnostics, functions, types)`
  - `check/Types.kt` — `Type` 层级（`TList` 是唯一内建容器范本）、`preludeSigs`（内建函数注册处）、`AdtInfo`（含 `jvmName`）
  - `check/Checker.kt` — 符号表、did-you-mean 接线、`needsExpected`
  - `codegen/CodeGen.kt` — `CodeGen(module, className)`；`dawn/rt/*` 运行时类（`Lists`/`Strings`/`Io`/`Show`/`Tuple2..8`/`Fn*`）在 `generate()` 里随每次编译生成；ADT 类名走 `AdtInfo.jvmName`/`CtorInfo.jvmName`
  - `cli/Main.kt` — `compile(path)`、`cmdRun/cmdTest/cmdBuild/cmdFmt`
  - 测试范式：`GoldenErrorTest`（golden 报错）、`TutorialTest`（教程块编译+输出比对）、`FmtTest`

---

## 1. 全局设计定夺（本手册即准绳，刀 1 把它落进 spec）

### 1.1 模块系统

**文件与路径**

- 一个 `.dawn` 文件 = 一个模块。模块路径 = 相对**模块根**的路径去掉扩展名，如 `<root>/json/lexer.dawn` → `json/lexer`。
- 路径段必须是 `[a-z_][a-z0-9_]*`（与文件名一致），不合法 → 编译错误。
- **模块根的确定**：
  - 目录模式 `dawn run|test|build <dir>`：根 = `<dir>/src`，入口 = `<dir>/src/main.dawn`（缺失则报错，提示预期路径）。
  - 文件模式 `dawn run|test|build <file.dawn>`（现有形态，保留）：根 = 从该文件所在目录**向上找最近的名为 `src` 的祖先目录**；找不到则根 = 文件所在目录。LSP 用同一条启发式。
    （这样 `dawn test src/json/lexer.dawn` 也能解析它 `use json/value` 之类的根相对导入。）

**语法（两种形式）**

```dawn
use json/lexer                 # 整模块引入，别名 = 末段 `lexer`，限定访问 lexer.next(...)
use json/value.{Json, render}  # 选择性引入，非限定使用
use java "java.lang.Math"      # 既有形式不变
```

- 一个模块只允许被 `use` 一次（整模块或选择性二选一）；重复 → 错误。
- `use` 允许出现在顶层任意位置（与 `use java` 当前行为一致），fmt 不重排。
- 没有 `as` 重命名（v0.1 不做）。两个整模块引入末段同名 → 错误，提示改用选择性引入或重组目录。

**名字解析（钉死，消除歧义）**

- 整模块引入的别名与本模块顶层声明、局部绑定、参数**同 namespace**：
  **声明任何与模块别名同名的顶层函数/类型/常量/局部/参数 = 编译错误**（"`lexer` shadows the imported module `json/lexer`"）。由此 `lexer.next(x)` 永不歧义：`lexer` 要么是绑定（走现有 UFCS 点调用），要么是模块别名（限定访问），不可能两者都是。
- 限定访问只支持**表达式位置**的 `alias.fn(args)` 与 `alias.CONST`。
  **类型与构造器跨模块只能走选择性引入**（`use m.{Shape}`）；限定类型引用 `m.Shape`、限定构造器模式 v0.1 不做（spec 记为限制）。
- 选择性引入一个 `type` 同时引入其**全部构造器**（与 `pub type` 导出构造器+字段的既有规则一致）。
- 选择性引入的名字与本模块顶层声明/其他引入冲突 → 错误。与 prelude 名冲突沿用「顶层声明遮蔽 prelude」的现行规则（引入视同顶层声明）。

**可见性**

- 默认模块私有；`pub` 导出 `fn`/`type`/`const`。访问/引入非 pub 项 → 错误：`` `parse` is private to module json/parser ``（附 hint：add `pub`）。

**编译单元与求值顺序**

- 目录模式：加载 `src/` 下**全部** `.dawn` 文件（不只 use 闭包）——未被引用的模块也要过检查（防 bit-rot），其 test 块也被 `dawn test` 执行。
- `use` 依赖图**禁止环**，报错打印环路（`json/a → json/b → json/a`）。
- 检查与 comptime 求值按拓扑序进行；跨模块引用的 `const` 值在使用方求值前已就绪。
- 类型同一性：同一 `AdtInfo` 实例跨模块共享（加载器保证每个文件只 parse/check 一次）。

**codegen 与产物**

- 模块 `json/lexer` → JVM 类内部名 `json/lexer`（包 `json`、类 `lexer`）；其 ADT 类沿用现有 jvmName 方案加模块前缀（如 `json/lexer$Token`、构造器 `json/lexer$Token$Num`）。入口模块类名 `main`，jar 的 `Main-Class: main`。
- 单文件模式类名维持现状（文件 stem），零回归。
- 跨模块调用 = 对方类上的 `invokestatic`；跨模块构造器/字段照常（类是公开的）。
- **`dawn/rt/*` 运行时类每个程序只生成一份**（现在随 `CodeGen(module)` 每次生成，多模块会重复——需把运行时类的生成提到程序级）。
- `dawn test <dir>`：跑所有模块的 test 块，报告加模块前缀（`PASS  json/lexer :: tokenize numbers`）。
- `dawn fmt <dir>`：递归格式化目录下所有 `.dawn`。

### 1.2 Map / Set

- 新类型 `Map[K, V]`、`Set[T]`，与 `List` 同级的内建容器（`Type.TMap`/`Type.TSet`）。
- **无字面量语法**。API 全部为 prelude 平铺内建函数（与 `chars`/`split` 同款注册方式；`core/map` 模块化组织推迟到 stdlib-in-Dawn）：

```
map_empty[K, V]() -> Map[K, V]          set_empty[T]() -> Set[T]
map_from(entries: List[(K, V)]) -> Map[K, V]   set_from(xs: List[T]) -> Set[T]
map_insert(m, k, v) -> Map[K, V]        set_insert(s, x) -> Set[T]
map_remove(m, k) -> Map[K, V]           set_remove(s, x) -> Set[T]
map_get(m, k) -> Option[V]              set_has(s, x) -> Bool
map_has(m, k) -> Bool                   set_size(s) -> Int
map_size(m) -> Int                      set_to_list(s) -> List[T]
map_keys(m) -> List[K]
map_values(m) -> List[V]
map_entries(m) -> List[(K, V)]
```

- 语义：**持久（不可变）接口**；v0.1 实现 = `LinkedHashMap`/`LinkedHashSet` **copy-on-write**（与现有 List 的实现哲学一致；文档注明 O(n) 插入、后续可换 HAMT 不动接口）。
- **迭代顺序 = 插入顺序**（LinkedHashMap，JVM/native 确定且一致——这是选它而非 HashMap 的硬理由）；`map_insert` 已有键时**替换值、保留原插入位置**（LinkedHashMap.put 语义）。`map_from` 后写覆盖先写。
- 相等：结构相等、**与顺序无关**（AbstractMap/AbstractSet.equals 自带）。
- Show：渲染成合法 Dawn 源码形状（M3 约定）——`map_from([(k, v), ...])`、`set_from([...])`，按插入顺序。
- 键可以是任何具结构相等的类型（Int/String/Bool/元组/ADT/record）。
  **前置修补：生成的 ADT/构造器/record/元组类目前只有 `equals` 没有 `hashCode`**——必须补齐与 equals 一致的 hashCode（31 进位折叠 equals 参与的字段；无载荷单例构造器用类名哈希常量），否则 HashMap 语义直接坏。

### 1.3 char（走 Go 的 rune 路线：码点即 Int，不引入新类型）

- **字符字面量 `'a'` 是 Int 字面量**，值 = 码点。词法层完成，类型系统零改动；match 里它就是普通 Int 模式。转义与字符串相同，另加 `\'`；空字面量或多码点字面量 → 词法错误。
- 新内建（`dawn/rt/Strings` 实现，按码点计）：

```
code_points(s: String) -> List[Int]       # 含增补平面（代理对合并为一个码点）
from_code_points(cs: List[Int]) -> String # 接受增补码点（Character.toChars）
char_to_string(c: Int) -> String          # 非法码点 panic（程序员错误）
str_len(s: String) -> Int                 # 码点数
substring(s: String, from: Int, to: Int) -> String  # 码点下标，越界 panic
```

- 现有 `chars(s) -> List[String]` 保留不动。
- 顺手核对 `parse_float(s) -> Option[Float]` 是否已实现（spec §11 列了它）；缺则在刀 6 补上（`Double.parseDouble` 包一层格式预校验）。

### 1.4 明确不做（v0.1 cut，spec 里记一笔）

- `bytes` 类型（JSON 验收不需要；二进制 IO 留给后续里程碑）。
- `use ... as` 重命名、限定类型引用 `m.Shape`、限定构造器模式、re-export（`pub use`）。
- 项目清单文件（`dawn.toml`）——目录约定就够。
- Map/Set 字面量语法、for-in 遍历 Map（用 `map_entries` + for-in List 顶）。

---

## 2. 刀 1 — spec 定稿（只动文档）

模块系统是 M4 最大的设计风险，先把语义写死再动代码。

1. 重写 `docs/spec.md` §10「模块系统」：把第 1.1 节全部语义落进去（路径与根、两种 use、名字解析与遮蔽错误、可见性、编译单元=src 全量、环禁止、拓扑序 comptime、v0.1 限制清单）。
2. §11 标准库草案：补 Map/Set 平铺 API 与「模块化组织推迟」的注记；§1.5 字面量补 `'a'`；§12.1 产物表补目录模式三命令与 `Main-Class: main`；§12.2 补模块→类的映射与 ADT 类名前缀。
3. `docs/grammar.ebnf`：`use_decl` 两种形式、char 字面量。
4. `docs/design.md`：若定夺与既有 M4 段落有出入（如 bytes 推迟），同步修正。

**验收**：文档自洽（spec/grammar/design 三处互不打架）；`gradle :compiler:test` 仍 366 绿。commit：`M4 spec: module system, Map/Set, char literals pinned down`。

## 3. 刀 2 — use 解析与模块加载器

1. AST：新增 `UseModuleDecl(pathSegments, selective: List<名字+span>?, span, nameSpan)`；`Module` 加惰性 `moduleUses`。
2. Parser：`use` 后是字符串 → 走既有 `use java`；否则解析 `seg(/seg)*` 与可选 `.{a, b}`。段名不合法、`.{}` 空列表 → 语法错误。
3. 新文件 `check/ModuleLoader.kt`：
   - 输入（根目录, 入口路径列表）→ 输出拓扑序的 `LoadedModule(modPath, file, module, diagnostics)` 列表。
   - 职责：按 1.1 的根规则解析 `use` → 文件；文件缺失（报尝试过的路径）、路径段不合法、重复 use、环（打印环路）→ 诊断。每文件只 lex/parse 一次。
   - 目录模式先 glob `src/**/*.dawn` 全量加载，再对 use 图做环检测与拓扑排序。
4. 新 `analyzeProgram(root, entries) -> AnalyzedProgram`（`check/Analyze.kt` 旁边）：本刀先只做「加载+逐模块沿用现有单文件 check」（跨模块名字本刀还解析不了会报 unknown——**本刀测试只覆盖加载器本身的成败路径**，跨模块正例留给刀 3）。
5. Golden 报错新增：missing module file / bad path segment / duplicate use / cycle（环路文本）/ selective 空列表。加载器单测（Kotlin，临时目录造文件树）：拓扑序正确、每文件只 parse 一次、src 全量收录。

**验收**：新增测试全绿，既有 366 不动。commit：`Module loader: use parsing, cycle detection, topological order`。

## 4. 刀 3 — 跨模块检查

1. `Checker` 接受「导入环境」：上游模块的 `functions`/`types`/consts 中 `pub` 的部分，按整模块别名或选择性名字注入。
2. 限定访问：checker 在解析 `x.f(a)`（现有 UFCS 点调用 AST）与 `x.NAME`（字段访问 AST）时——`x` 不是任何绑定且是模块别名 → 改走模块成员解析；成员不存在/非 pub → 错误（did-you-mean 复用 `diag/Suggest.kt`，候选 = 该模块 pub 成员）。
3. 遮蔽错误：顶层声明/局部/参数与模块别名同名 → 错误（两处 span 都给）。
4. 选择性引入：注入名字（type 连带构造器）；冲突检测（vs 顶层声明、vs 其他引入）。
5. 跨模块 comptime：`evalComptime` 按拓扑序逐模块执行，上游 const 值可见。
6. `AnalyzedProgram` 补齐聚合诊断（渲染时带各自文件名——`Diagnostic.render(SourceFile)` 已接受文件路径，golden 用相对路径保持机器无关）。
7. Golden 新增：private access（含 hint）、unknown member（did-you-mean）、alias shadowing（顶层/局部两种）、selective 冲突、selective 引入不存在的名字。正例集成测试（Kotlin，临时文件树）：跨模块 fn/const/type+ctor/泛型 fn/效果传播/跨模块 `?` 各一例，走 `analyzeProgram` 断言零诊断。

**验收**：全绿。commit：`Cross-module checking: qualified access, selective imports, visibility`。

## 5. 刀 4 — 多模块 codegen + 项目 CLI

1. `CodeGen` 拆分：`dawn/rt/*`（Lists/Strings/Io/Show/Tuple*/Fn*/PanicError）提为**程序级一次生成**；每模块一个 `CodeGen` 产出模块类 + 该模块的 ADT 类（jvmName 带模块前缀，改在 checker 构造 `AdtInfo` 处）。跨模块调用 `invokestatic` 对方类。
2. `cli/Main.kt`：`run/test/build/fmt` 接受目录（按 1.1 根规则）；文件模式走 src 向上启发式找根后同管线（单文件无 use module 时行为与现在逐字节一致）。`dawn test <dir>` 聚合所有模块 test 块、名字带模块前缀。jar 收全部类，`Main-Class: main`。
3. 新 `examples/m4/hello_mod/`（src/main.dawn + src/greet/words.dawn 之类的最小多模块工程，含跨模块 ADT、泛型、const、test 块）——同时当集成测试夹具与文档示例。**记得 `dawn fmt`。**
4. 测试：Kotlin 集成测试编译+运行 hello_mod 断言输出；`dawn test` 聚合报告测试；单文件全量回归（366 项里所有走 `compile()` 的路径不回归）。
5. **native 验证（手动，本刀必做）**：`./bin/dawn build examples/m4/hello_mod --native -o /tmp/hello_mod && /tmp/hello_mod`，输出与 JVM 逐字一致。

**验收**：全绿 + native 一致。commit：`Multi-module codegen, project-directory CLI (run/test/build/fmt)`。

## 6. 刀 5 — Map / Set

1. **先补 hashCode**：`genCtorClass`/`genTupleClass` 生成与 equals 一致的 `hashCode`（Kotlin 测试：结构相等的两值 hashCode 相等；作 HashMap 键能命中）。
2. `Types.kt`：`TMap(key, value)`/`TSet(elem)`（仿 `TList`：结构相等、`subst` 分支、`resolve` 里 `"Map"/"Set"` 带参数）。
3. `preludeSigs` 注册 1.2 节全部函数（泛型签名仿 `map`/`fold` 的 `typeParams` 写法；`map_empty`/`set_empty` 零参靠期望类型实例化——现有「期望播种」机制应当直接可用，不行则报「cannot infer, add annotation」即可，不强求）。
4. 运行时 `dawn/rt/Maps`（ASM 生成，仿 `genListsClass`）：LinkedHashMap/LinkedHashSet copy-on-write；`map_get` 包 `Option`（键装箱语义与 List 元素一致——恒装箱）。
5. Show：`dawn/rt/Show.show` 加 `instanceof Map`/`Set` 分支，渲染 `map_from([(k, v), ...])`/`set_from([...])`；checker 的 `isShowable` 放行 Map/Set（键值均 showable 时）。
6. 相等：`==` 对 Map/Set 走 `equals`（与 List 现行路径一致，确认即可）。
7. 测试：Dawn 端 30+ 断言（插入/覆盖保位/删除/get→Option/keys 顺序/结构键（元组、ADT）/相等与顺序无关/Show/set 全套/泛型推导）；golden：Map 用不可 show 的值调 to_string、类型不匹配各一条。
8. spec §2.2 内建复合类型补 Map/Set 小节（刀 1 已写 §11，此处补类型章）。

**验收**：全绿。commit：`Map and Set: builtin persistent containers (+ structural hashCode)`。

## 7. 刀 6 — char 字面量与码点 API

1. Lexer：`'...'` → INT token（值=码点）；转义同字符串 + `\'`；空/多码点/未闭合 → 词法错误（golden 各一条）。注意 `Formatter` 按 span 重印，char 字面量天然保真——补一个 fmt fixture 确认。
2. `dawn/rt/Strings` 补 1.3 节五个函数 + 对应 `preludeSigs`；核对/补齐 `parse_float`。
3. 测试：Dawn 端断言（ASCII/中文/emoji 增补平面各一批：`str_len("🙂")==1`、`code_points`↔`from_code_points` 往返、substring 中文边界、`'a'==97`、match 里 `'{' -> ...`）；`char_to_string(-1)` panic 路径。
4. spec §1.5 已在刀 1 写过字面量；§11 字符串函数清单更新。教程留刀 8。

**验收**：全绿。commit：`Char literals as code points, code-point string API`。

## 8. 刀 7 — JSON 库 + JSONTestSuite 验收（M4 验收物）

1. 工程布局（**每个源文件写完过 `dawn fmt`**）：

```
examples/m4/json/
├── src/
│   ├── main.dawn          # 读 args()[0] 指定的文件，解析；首行输出 "valid" 或 "invalid"
│   └── json/
│       ├── value.dawn     # pub type Json = JNull | JBool | JNum(Float) | JStr | JArr(List[Json]) | JObj(Map[String, Json])  derive Show
│       ├── lexer.dawn     # 基于 code_points 的手写词法（字符串转义含 \uXXXX 与代理对合并）
│       ├── parser.dawn    # 递归下降，返回 Result[Json, String]；深度上限 const MAX_DEPTH = 512，超限 Err（防 n_ 深嵌套用例打爆 JVM 栈）
│       └── render.dawn    # pub fn render(Json) -> String（序列化，round-trip 自测用）
└── suite/                 # 供第 3 步 vendor
```

   语义要点：数字一律 Float（格式由语法层校验，转换用 `parse_float`）；**解析失败必须走 `Result`，任何输入都不得 panic**；各模块自带 test 块（`dawn test examples/m4/json` 全绿）。
2. 该工程刻意覆盖 M4 全部新特性：嵌套模块目录、整模块+选择性两种 use、pub 边界、Map、char 字面量与码点 API、跨模块 const。
3. Vendor 测试套件：`git clone --depth 1 https://github.com/nst/JSONTestSuite /tmp/jts`，拷 `test_parsing/` 到 `examples/m4/json/suite/`（MIT，`suite/LICENSE` 注明来源）。**网络不通就停下来问用户**，不要手造替代品。
4. 新 `compiler/src/test/kotlin/dawn/JsonSuiteTest.kt`（仿 TutorialTest 的 `../` 路径探测）：用 `analyzeProgram`+多模块 codegen **编译一次**，对 suite 每个文件反射调 `main(arrayOf(path))` 捕获 stdout。判定：`y_*` 必须 `valid`、`n_*` 必须 `invalid`、`i_*` 任意但不得抛异常。
   - 非法 UTF-8 的用例经 `read_file` 有损解码后判定可能翻转：允许一个 `suite-overrides.txt`（每行 文件名+一句英文理由），**上限 5 条，超了停下来问用户**。
5. 手动验收：`./bin/dawn run examples/m4/json <某 y_ 文件>` 与 native 构建产物输出一致；`dawn test examples/m4/json` 全绿。

**验收**：JsonSuiteTest 全绿（含 overrides ≤5 且各有理由）+ 上一行手动项。commit：`M4 acceptance: pure-Dawn multi-module JSON library passing JSONTestSuite`。

## 9. 刀 8 — 收尾

1. LSP 最小多文件支持：打开的文件按 1.1 根启发式解析其 use（从磁盘读依赖），跨模块名字不再误报 unknown；解析不到的 use 出诊断。悬停/跳转对导入名 best-effort（跳到对方文件的能力可留 TODO，不阻塞）。
2. `docs/tutorial.md` 新章「模块与项目」+「Map 与字符」：多文件示例代码块加 `skip-check`（TutorialTest 的 skip-check 上限当前是 3，可在同一 commit 内上调到 6 并注明理由）；Map/char 单块示例正常受检。
3. `README.md`：状态补 M4、命令表补目录模式、测试数更新；`docs/design.md` M4 里程碑标完成（日期、刀列表、测试数、验收物）；spec 与实现若有出入最后校一遍。
4. 全量回归：`gradle :compiler:test` 全绿；`./bin/dawn fmt --check` 扫 examples 全部通过；shapes/calc/hello_mod/json 四个样例 JVM 与 native 输出一致。
5. 删除本文件（`docs/m4-plan.md`）。

**验收**：上述全部。commit：`M4 complete: module system, Map/Set, char, project builds, JSON library`。

---

## 10. 风险与已知坑（写代码前读一遍）

- **`dawn/rt/*` 重复生成**：多模块下若每个 CodeGen 都生成运行时类，jar 里同名 entry 会炸/覆盖——刀 4 第一件事就是提到程序级。
- **ADT jvmName 前缀**：改名要同时波及 codegen 的所有 `GETSTATIC`/`NEW`/`CHECKCAST` 引用点与 `DawnClassWriter.adtSupers` 表（COMPUTE_FRAMES 依赖它算公共父类）——它们都从 `AdtInfo`/`CtorInfo` 取名则自动跟随，硬编码处要搜干净。
- **equals 无 hashCode**（刀 5 前置）：现状是故意没写，因为此前没有任何哈希容器；上 Map 必补，且单例构造器的 equals 语义（引用相等 or instanceof）要先读代码确认再写配套 hashCode。
- **迭代顺序决定 JVM/native 一致性**：Map/Set 一律 LinkedHash*，禁用 HashMap 裸迭代。
- **JSON 深嵌套**：JVM StackOverflowError 不可被 Dawn 捕获，必须用解析深度上限把 n_/i_ 深嵌套用例转为正常 `Err`。
- **`Formatter` 是 token 流重排器**：新 token（char 字面量）按 span 原样重印即可，但要防它被 `space()` 规则错误贴合——加 fixture。
- **golden 里的路径必须机器无关**：多文件 golden 用相对路径渲染（GoldenErrorTest 现有做法是固定 `case.name`，多文件场景沿用相对根的路径）。
- **Dawn 源码里注释是 `#` 不是 `//`**；record 函数式更新必须带类型名 `Point { ..p, x: 1.0 }`；字符串里 `{` 恒为插值开始（字面 `{` 用不了，测试夹具避开）；`Unit` 不能实例化类型参数。
- **多行文本夹具**用脚本（如 Python）落盘生成，别用 shell heredoc/printf 拼（历史上多次踩坑）。
