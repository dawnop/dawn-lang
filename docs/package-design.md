# 包管理设计（草案）

> 状态：设计已定，分两个项目落地。**项目 A（Maven 依赖）✅ 已完成**（dawn-lang 全量 1170 测试通过，
> backend-dawn 已切换）；项目 B（Dawn 源码包）待启动。
> 本文是调研结论 + 设计决策的单一事实源。调研过程见文末「附录：调研依据」。

## 一、为什么现在做

M6 复盘（[`m6-retro.md`](m6-retro.md)）排了 6 项修复优先级，**没有一项是包管理**。但 backend-dawn
自己的代码里写着这句：

```dawn
# Vendored from examples/m4/json/src/json/value.dawn (M4 acceptance library) —
# keep in sync until Dawn grows a package story.
```
（`backend-dawn/src/json/value.dawn:1`，同样的话在 `lexer/parser/render` 各抄一遍）

**这个 sync 承诺已经破产。** 全机器副本指纹：

| 模块 | examples/m4 | site | playground | backend-dawn |
|---|---|---|---|---|
| `json/value` | 10L | 12L | 12L | **16L（共 3 种 md5）** |
| `json/parser` | 117L | 119L | 119L | **134L** |
| `web/router` | — | — | 134L | **227L** |
| `web/types` | — | — | 140L | **227L** |
| `web/server` | — | — | 165L | **246L** |
| `web/middleware` | — | — | 50L | **85L** |

`web/` 相对 playground **漂移 523 行**。它已经是一个完整的 web 框架（router + types + middleware +
server，带测试），却伪装成某个 app 的子目录。**它想成为一个库，但 Dawn 没地方放库。**

分叉本身是**对的**——backend-dawn 需要整数保真才加了 `JInt`（`value.dawn:8-11` 自己标注了
"backend-dawn divergence, M6 knife 6"），需要二进制响应体才扩了 `web/types`。问题不是分叉，
是**分叉的表现形式只能是复制粘贴，且文件头还挂着一句兑现不了的承诺**。

M6 复盘结尾那句自我总结正好适用：

> Dawn 的问题不是"管得太多"，而是几个地方"省得太狠"。

「没有清单文件」就是又一处省得太狠。

## 二、Dawn 已经做对的三件事

这是本次调研最意外的部分。以下三件都是别的语言事后补、补得很痛的，Dawn 已经有了：

### 1. 整程序源码编译 → 包 = 源码树

`ModuleLoader.loadDirectory`（[`ModuleLoader.kt:54`](../compiler/src/main/kotlin/dawn/check/ModuleLoader.kt)）
走 `src/` 全部文件、拓扑排序、按依赖序类型检查、一把梭出一个 jar。

推论：**一个包就是另一棵源码树**。不需要 ABI、不需要分离编译、不需要 `.rlib`/`.beam` 之类的
二进制产物格式与版本化元数据。Rust 和 Go 在这上面花的力气 Dawn 直接不用付。

### 2. orphan rule + 全程序 coherence 已经有了，而且更严

[`Checker.kt:558-565`](../compiler/src/main/kotlin/dawn/check/Checker.kt) 要求 impl 必须住在声明
trait 或声明 subject 的**模块**里；`implTable`（`Checker.kt:51`）保证全程序一个 `(trait, type)`
只有一个 impl。

这条现在是**模块级**，比 Rust 的 **crate 级**严格。两个推论：

- **跨包不可能出现孤儿 impl**：包 C 既不声明 `T` 也不声明 `X`，就 impl 不了 `T[X]`。
  **coherence 白送**，包管理不需要为它做任何事。这个税 Dawn 在第一天就交了。
- **将来把 orphan rule 从模块级放宽到包级是严格更宽松的**，不会让任何现有程序失效。
  （是否放宽是独立议题，与包管理解耦，见 §7。）

### 3. `use` 的第一段天然就是命名空间

backend-dawn 里 `use` 首段的频次分布：

```
110 java     37 json     21 web     15 jsonx     12 sql     8 db     8 auth ...
```

`json` 和 `web` 是仅次于 `java` 的两个——**恰好就是那两个 vendored 库**。它们的调用点
已经长得和包一模一样了。这直接决定了 §4 的别名设计：**迁移时一行 `use` 都不用改。**

## 三、两个可分离的项目

| | 项目 A：Maven 依赖 | 项目 B：Dawn 源码包 |
|---|---|---|
| 治的病 | 版本号手抄三份、9.7MB jar 进 git、systemd 硬编码 | `web/` 523 行静默 fork、`json/` 四份三种 |
| 动语言语义？ | **否**（只动 CLI + classpath 来源） | 是（模块解析、类名命名空间） |
| 工作量 | ~2–3 人日 | ~1–2 周 |
| 依赖关系 | 无 | 建议在 A 之后（A 先钉死 manifest 格式） |

**先做 A 的理由不只是它便宜**：它逼我们把 manifest 的文件名、格式、schema 版本定下来——
**正好是那批不可逆决策**（§6）——用一个低风险项目去锁定它们，而不是在 B 的复杂度里顺手定。

## 四、设计

### 4.1 Manifest：`dawn.toml`

**这推翻了 spec §10.1 的一条明写决定**：

> 没有清单文件（`dawn.toml` 之类）；目录约定即工程定义。

这是一次**有意识的反转**，不是悄悄加个文件。落地时须同步改 spec §10.1。

目录约定仍然成立（根 = `<dir>/src`，入口 = `src/main.dawn`）；manifest 只增加
「目录约定表达不了的东西」：身份与依赖。**没有 `dawn.toml` 的项目继续按今天的方式工作**——
manifest 是可选的，直到你需要依赖。

```toml
schema = 1
name = "backend_dawn"

[java-deps]
sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"
bcrypt = "org.mindrot:jbcrypt:0.4"

# 项目 B 才启用：
# [deps]
# web  = { url = "...", hash = "..." }
```

**`schema = 1` 必须是第一个 key。** 见 §6。

### 4.2 TOML 子集 + 格式保留（自己写，约 300 行）

**决策：手写一个保留 CST 的 TOML 子集解析器，不引第三方 TOML 库。**

这个决策经过一次反转，理由值得记下来，否则未来的自己会想「为什么不用现成库」：

1. **JVM 上没有 `toml_edit` 的对等物。** Cargo 读 `Cargo.toml` 用 `toml` crate，
   **写用 `toml_edit`**（`cargo add` 靠它做格式保留编辑）。JVM 这边：`tomlj` 只读、
   **根本没有 writer**；`toml4j` 已死（2024 年最后一个提交是加 "no maintenance intended" 徽章）；
   `commons-configuration2` 不支持 TOML。**引库拿不到我们最终要的能力。**
2. **ktoml 不能格式保留往返。** 它是 kotlinx.serialization format，无 CST；
   parse → 改 → 写回会丢注释、缩进、key 顺序。连值都不保真（[ktoml#376](https://github.com/orchestr7/ktoml/issues/376)：
   `5e+22` 往返变 `50000000000000000000000.0`）。
3. **ktoml 也不是规范权威。** [ktoml#383](https://github.com/orchestr7/ktoml/issues/383)：
   接入 toml-test 套件后发现**接受了 151 个本该被拒的非法 TOML**。它是宽松而非完整——
   引它换不来「用户写什么合法 TOML 我们都对」的保证。
4. 代价还不止：ktoml 要 `kotlin("plugin.serialization")` 插件 + kotlinx-serialization +
   kotlinx-datetime，为一个六个 key 的文件。

**Go 的先例更有力，而且理由是原话。** Rob Pike 亲自开 issue 骂 go.mod 不该自造语法
（[golang/go#23966](https://github.com/golang/go/issues/23966)），rsc 的回复正中要害：

> "Both TOML and YAML also turn out to be more complex than they first appear, a detail that's
> very important **if you need not just a parser but a mechanical editor that can parse, edit,
> and reprint the file**."

而他的附言几乎是在描述 JVM 今天的处境：

> "The answer is that **Dep can't reliably modify hand-written TOML, preserving comments and the
> like**… This seems to be an artifact of the available libraries as much as it is a design choice."

**我们的解法取两者之长**：文件**是合法 TOML**（编辑器高亮、CI 脚本、任何 TOML reader 都能读，
不像 Zig 的 `.zon` 只有 zig 读得懂），**但解析器是自己的、保留 CST 的**（`dawn add` 能只改一行，
不打乱文件；诊断走 Dawn 现有的 `Diagnostic`/`Span`，报错格式与编译器其余部分一致）。

**接受的文法（全部）**：

```toml
# 注释
key = "string"        # 基本字符串，支持 \" \\ \n \t \r \uXXXX
key = 123             # 十进制整数（可带 _ 分隔）
key = true            # 布尔
key = ["a", "b"]      # 单行字符串数组
[table]               # 表头
```

**明确拒绝**（报错，不静默误解）：表数组 `[[x]]`、多行字符串 `"""..."""`、字面量字符串 `'...'`、
内联表 `{...}`、点分 key `a.b = 1`、日期时间、浮点、八/十六进制。

子集 → 全集是**加宽**，永远向后兼容；反向不行。所以这个方向是安全的——
和「MVS 先于 PubGrub」是同一个论证（§4.5）。

### 4.3 别名在 manifest，不在源码（项目 B）

**不抄 Go 的「模块路径 = URL」。** Go 要求源码写 `import "github.com/x/dawn-web"`，
而 Dawn 的段文法是 `^[a-z_][a-z0-9_]*$`（[`ModuleLoader.kt:51`](../compiler/src/main/kotlin/dawn/check/ModuleLoader.kt)），
**禁止 `.` 和 `-`**，`github.com/dawnop/dawn-web` 根本不合法。改文法迁就它，代价远大于收益。

**走 alias-in-manifest（Zig `build.zig.zon` / Cargo 模型）**：manifest 把本地别名映射到远端源，
源码只写别名。

解析规则：`use web/router` 的首段 `web` 若命中 `[deps]` 别名 → 在该包根下解析；
否则走现有的 `<dir>/src` 本地路径。两者都存在 → **报错**（不许静默 shadow）。

**这给出一条近乎完美的迁移路径**：backend-dawn 删掉 `src/web/` 和 `src/json/`，manifest 加两行——
那 **21 行 `use web/...` 和 37 行 `use json/...` 一个字都不用改**。

### 4.4 类名命名空间（项目 B 的唯一硬阻塞）

[`ModuleLoader.kt:113`](../compiler/src/main/kotlin/dawn/check/ModuleLoader.kt)：

```kotlin
val modPath = modulePathOf(root, file)
val className = modPath.split('/').joinToString("/") { sanitizeSegment(it) }
```

**JVM 类名 = 模块路径。** 两个包各带一个 `json/value` → 生成同名 JVM 类 → 在 jar 里静默互相覆盖。

修法很干净：模块路径段文法禁止 `$` 和大写，**所以任何含 `$` 的类名前缀在构造上不可能与用户模块撞车**。

- 本包模块：保持裸 `main` / `api_fm`（向后兼容，`Main-Class: main` 不用动）
- 依赖包模块：`dawn$pkg$<包名>/<模块路径>`

命名空间取**包自己 manifest 里声明的 `name`**，不是消费者起的别名——否则同一个包在不同 app 里
类名不同，且两个别名指向同一个包时会重复编译。**包名是身份，别名只是本地糖。**

### 4.5 MVS，而且这次它不只是图省事（项目 B）

版本求解选 **MVS（Minimal Version Selection）**，Go 那套。实测 Go 的完整工业级实现是
**819 行**（不是流传的「几十行」——Cox 原话是 "a few hundred lines"）；Dawn 第一版砍到 200–300 行。

**但对 Dawn 有一条别人没有的、结构性的理由**：MVS 保证「一个模块路径至多一个版本」。
而 Dawn 的 coherence 是 `implTable` 上的全程序 `(trait, type) → impl` 唯一映射。
**npm 式的嵌套多版本共存会直接炸掉它**——同一个包链接两次，`TAdt` 的 `info` 就是两个不同对象，
「同一个类型」有了两个 impl，字典传递选哪个都是错的。这就是 Rust orphan rule 要解决的
hashtable problem。

**所以「单版本」对 Dawn 不是便利，是承重墙。** 选择是被 coherence 逼定的——而它恰好也是最便宜的那个。

**红线（Cox 自己算过）**：requirement **只能是最小版本；不准有上界、不准有 exclude、
绝不准传递性 exclude**。排除项一旦条件化就变成 NP-complete，Horn 结构一破就掉进需要 PubGrub 的
世界——而 PubGrub 要 registry index（它的 `choose_version(P, range)` 要求能枚举 P 的版本），
而我们没有 registry。**这三件事是一根绳上的，一起立一起倒。**

诚实标注：matklad 的批评是对的——MVS 的价值**不在**避开 NP（难度来自约束表达力，不是求解方向）。
它在**生态纪律**：「作者声明的最小版本必须是真的、v2 必须换名」。这个纪律大生态执行不了
（所以 Cox 的 "I expect users will end up almost as up-to-date" 至今只是预测，他没法强制生态），
**但单人生态能 100% 执行，而且只有现在能立。**

演进方向是安全的：**MVS 的「最小版本」是 PubGrub「区间」的特例**，`1.2.0` → `>=1.2.0` 是无损升级，
反过来是有损的。次序不能反。

## 五、该砍的

| 砍掉 | 理由 |
|---|---|
| **PubGrub** | 5–7K 行 + 必须有 registry index。发明人自己花 9 个月（5 月读论文 + 3 月写 + 1 月打磨）。Cargo 立了两期 Project Goal、有专职人，**至今没做完**（顺带纠正流传说法：Cargo 现在**没有**在用 PubGrub，还是自己的朴素回溯器）。我们有 0 个包，冲突还不存在。 |
| **registry / 中心化索引** | 名字发出去收不回（crates.io: "Crate deletion by their owners is not possible"）。运营成本与抢注纠纷单人付不起。GitHub 已经替我们做了名字仲裁。 |
| **命名空间 / scope** | RFC 3243 自己划界："does not intend to address the general problem of squatting"。没 registry 就没抢注问题。 |
| **yank / delete** | 不可变换来的另一面，别开这个口子。 |
| **自建 sumdb / 透明日志** | 给「不信任 proxy」用的。我们没有 proxy。**但 hash 字段先留在格式里。** |
| **上界约束 / exclude / 传递 exclude** | 见 §4.5，会当场炸掉 MVS 的 Horn 结构。 |
| **版本区间语法** | MVS 只要最小版本。将来升区间无损，反之有损。 |
| **lockfile（项目 A）** | 见 §4.6。 |

### 4.6 项目 A 不做 lockfile，靠「禁 SNAPSHOT + 禁区间」换可复现

Go 的形态是 **manifest 兼任 lockfile**（1.17 图剪枝后 go.mod 显式列全部传递依赖）。
Filippo Valsorda 说得对——"go.mod serves as both manifest and lockfile"；
**别学 Go 官方宣传「我们不需要 lockfile」**，我们需要 lockfile 的功能，只是把它并进一个文件。

项目 A 更简单：直接坐标是**精确版本**，Maven Central 的 release 版本**不可变**，
所以只要**禁掉 SNAPSHOT 和版本区间**，coursier 的解析结果就是确定的——不需要 lock 也可复现。
这条纪律与 §4.5 的 MVS 红线同源（都是「不准有上界」）。

将来若发现传递依赖里有区间，再加 `dawn.lock`（schema 版本让这一步无痛）。

## 六、三个「今天免费、以后无价」的决定

调研里最值钱的部分是「哪些决策不可逆」。规律：**格式与命名不可逆，指导意见可逆**
（Cargo 能一句话反转 lockfile 建议；Go 公告删除 GOPATH 后**又活了 5 年 9 个版本**——
实测 go1.26.5 至今 `GO111MODULE=off` 仍可用）。

对我们只有三条：

### 1. manifest 必须是数据，不能是代码

[PEP 518](https://peps.python.org/pep-0518/) 把死锁写得极准：

> "You can't execute a `setup.py` file without knowing its dependencies, but currently there is
> no standard way to know what those dependencies are in an automated fashion without executing
> the `setup.py` file where that information is stored."

2016 年写的，**十年了 setup.py 还在**。

对一门语言来说「用自己写 build 脚本」的诱惑极大。注意 **Zig 的 `build.zig.zon` 是 Zig 字面量
但刻意不是可执行的 `build.zig`**——这个区分是故意的。**不要写 `build.dawn`。**

### 2. 每个文件第一行写 schema 版本

`dawn.toml`、将来的 lock、hash 字符串本身都要。这是唯一一条**把不可逆变可逆**的技巧
（"Version the schema, not the tool"）。

Zig 是活体教材：它承诺过 hash 格式变更给一个 release 的宽限期，**没做到**
（[zig#23100](https://github.com/ziglang/zig/issues/23100)：含 `-` 的包名直接报错而非警告），
然后在新格式里硬塞了个 `"P"` 标记，好让未来能区分格式。**吃完亏才加的东西，我们现在零成本先加。**

### 3. v2 = 新名字（import 兼容规则）

唯一一个「今天不做、以后做不了」且「今天做、成本为零」的决策——**因为我们就是整个生态**。

它是 MVS 的**前提**不是配套：没有它，MVS 的「取 max」会把不兼容的 v2 塞给 v1 使用者。

Go 社区普遍讨厌 `/v2`（GORM 甚至把 2.0 打成靠后的 1.x tag 来绕开规则；有人在 Go meetup 上
发现参与者"very skeptical the rule existed at all"），但那些成本是**在几十万个包之后**才浮现的。
我们现在加，代价是改自己那两个 vendored 目录。

> **一句话**：求解器是可逆的（藏在接口后，将来换）；名字格式是不可逆的。我们有 0 个包，
> 任何求解器都对；但敲下的第一个模块路径会活到这门语言死。**把周末花在命名和文件格式上，
> 求解器随便写。**

## 七、明确不在本设计范围内

- **orphan rule 模块级 → 包级放宽**：独立议题。放宽是严格更宽松的，不会破坏现有程序，
  但与包管理解耦，可择机单独做。
- **`dawn add` 子命令**：格式保留解析器为它铺路，但 A 不实现。
- **stdlib 变成包**：不需要。stdlib 完全内建在编译器里（`PRELUDE_ADTS`/`PRELUDE_TRAITS`/
  `PRELUDE_IMPLS`，随编译器分发零 `.dawn` 源码），**没有 bootstrap 问题**。

## 八、推进顺序

1. **项目 A（Maven 依赖）** — 独立、低风险、不动语言语义。钉死 manifest 格式与 schema 版本。
2. **类名命名空间**（`dawn$pkg$<name>/<mod>`）— 纯编译器内部改动，不改语法，可独立验证。
3. **项目 B（Dawn 源码包）** — 第一个用户就是把 `web/` 从 backend-dawn 拆出来变成真包。
   它已经证明自己够格了（523 行漂移 + 自带测试）。

---

## 附录：项目 A 实施细节

### A.1 依赖解析：`io.get-coursier:interface:1.0.28`

**注意有两个不同的东西，别搞混**：

- `io.get-coursier::coursier`（即 `coursier_2.13`）= Scala 库、Scala API、要 Scala runtime。**不要用。**
- **`io.get-coursier:interface`** = [coursier/interface](https://github.com/coursier/interface)，
  **纯 Java API，把 coursier 及其全部依赖（含 Scala 库）shade 进单 jar**。用这个。

```java
List<File> jars = Fetch.create()
    .addDependencies(Dependency.of("org.xerial", "sqlite-jdbc", "3.36.0.3"))
    .fetch();   // -> List<File>，直接就是 classpath
```

**实测**（子 agent 在本机跑过）：冷缓存 65s（国内网络到 repo1），**热缓存 413ms**，
传递依赖图正确（jackson-databind:2.15.2 → 正确解析出 7 jar）。缓存在 `~/.cache/coursier/`
（镜像 URL 结构，**默认不用 `~/.m2`**）。

**选它而不是 maven-resolver / MIMA 的决定性理由是依赖隔离**：后两者会往 classpath 塞 32–39 个 jar，
含 `asm-9.x`——**而 dawn 编译器自己就用 ASM（`org.ow2.asm:asm:9.7.1`）生成字节码，当场撞车**。
coursier `interface` 全 shaded，这类问题结构性消失。

**native-image 风险已排除**：dawn 编译器自己**不是 native-image，是 fat jar**
（`bin/dawn:31` → `exec java -jar "$JAR"`）；native-image 只用于编译**用户程序**
（`cli/Main.kt:285`）。所以 coursier 的 10.6MB shaded jar 和它的反射配置**不进 native 路径**。

**已知代价**：
- `dawn.jar` 体积 +10.6MB（fatJar 打包 runtimeClasspath）。
- POM 里有一个**非 shaded 的真依赖** `org.slf4j:slf4j-api`，必须一起带（否则 `NoClassDefFoundError`）。
- 最新是 `1.0.29-M4` 里程碑版；**钉 1.0.28 稳定版**。
- 冷缓存在国内 65s → 支持镜像（见 A.3）。

### A.2 产物布局：保持现有部署形态

`dawn build . -o backend-dawn.jar` →
解析 `[java-deps]` → coursier 取 jar → **复制进 `<out 同级>/lib/`** →
jar manifest 写相对 `Class-Path: lib/x.jar lib/y.jar`。

这**正好匹配 backend-dawn 现在的部署布局**（jar + 同级 `lib/`），部署脚本与 systemd 单元无需改结构。

三个消费端从同一份 manifest 声明喂：
1. 编译期互操作类型检查（`cpLoader` 的 URLClassLoader，`cli/Main.kt:113`）
2. `dawn test` / `dawn run` 的运行期 classpath
3. `dawn build` 写进 jar manifest 的 `Class-Path`

`--cp` **保留**（其他客户端 / 本地 jar / 应急用），与 `[java-deps]` 解析结果**合并**。

### A.3 镜像

Maven 仓库地址走**环境变量 `DAWN_MAVEN_MIRROR`**，不进 manifest——
镜像是「我在哪」的属性，不是「这个项目是什么」的属性。放进 manifest 会让同一个项目在不同网络
环境下需要改文件。

### A.4 校验

- **禁 SNAPSHOT**：坐标含 `-SNAPSHOT` → 报错（不可复现）。
- **禁版本区间**：坐标含 `[` `]` `(` `)` `+` → 报错（同 §4.5 红线）。
- 坐标必须是精确的 `groupId:artifactId:version` 三段。

### A.5 backend-dawn 的收益（✅ 已验收）

三处手抄的版本号已全部消失，`dawn.toml` 是唯一事实源：

| 原处 | 结果 |
|---|---|
| `build.sh:8` 的 `CP="lib/sqlite-jdbc-3.36.0.3.jar:lib/jbcrypt-0.4.jar"` | ✅ 删除，`dawn test .` / `dawn build .` 不再传 `--cp` |
| `README.md:14` 手抄的第二份 | ✅ 改为指向 `dawn.toml`（顺带修正过期的测试数 46 → 59） |
| `deploy/dawnop-dawn.service:28` 手抄的第三份 | ✅ `-cp` 长串 → `java -Xmx256m -jar backend-dawn.jar` |
| git 里的 **9.7MB sqlite jar + 17KB jbcrypt jar** | ✅ `git rm --cached` + `.gitignore` 加 `backend-dawn/lib/` |

**同批修掉的过期注释**：`dawnop-dawn.service:19-22` 声称 jar 的 manifest `Class-Path` 是绝对构建
路径、故 `-jar` 找不到 lib、须用 `-cp` 展开。**实测解包 jar，`Class-Path` 是相对路径**
（`lib/sqlite-jdbc-3.36.0.3.jar lib/jbcrypt-0.4.jar`）——这段注释描述的是某个历史版本，
是**为已修复问题打的补丁，理由已失效**，而它是**生产在跑的那份**。现已连同 `ExecStart` 一起改正。

**验收记录**：

- 干净树（删 `lib/`、无 `--cp`）跑 `./build.sh` → 59 测试通过、jar + `lib/` 自动就位
- 产出 jar 的 manifest 与从前**逐字节一致**：`Class-Path: lib/sqlite-jdbc-3.36.0.3.jar lib/jbcrypt-0.4.jar`，
  `Main-Class: main`（部署形态不变）
- 按**新 ExecStart 形态**（`java -Xmx256m -jar`，无 `-cp`）实跑：`/api/health` → 200；
  `/api/articles` → 500 `no such table: articles`——**这条 500 正是驱动可用的证明**
  （sqlite JDBC 经 SPI 找到、连上、建出空库、执行查询，只是没 seed），零 `ClassNotFoundException`
- dawn-lang 全量 **1170 测试 0 失败**（原 1142 + ManifestTest 28）

**未纳入 A 的相邻问题**（另开）：`backend-dawn/backend-dawn.jar` 本身仍在 git 里、靠人肉 rebuild
（当前 HEAD 的 jar 落后一个 commit）。这是产物入库问题，与依赖声明无关，且部署流程可能依赖它，
未擅动。

---

## 附录：调研依据

### 版本求解
- [Minimal Version Selection (Russ Cox)](https://research.swtch.com/vgo-mvs) — MVS 原始设计；
  靠 Schaefer 二分定理（2-SAT ∩ Horn-SAT ∩ Dual-Horn-SAT）保证**唯一最小解**；
  exclude 下放会 "leading to an NP-complete search problem"
- [Minimal Version Selection Revisited (matklad)](https://matklad.github.io/2024/12/24/minimal-version-selection-revisited.html) — 最强反驳，"SAT is not a big deal"
- [Dart pub solver.md](https://github.com/dart-lang/pub/blob/master/doc/solver.md) — PubGrub 参考实现（1233 行文档）
- [pubgrub-rs](https://github.com/pubgrub-rs/pubgrub) — 4408 行 + version-ranges 1590 行
- [Cargo resolver 源码](https://raw.githubusercontent.com/rust-lang/cargo/master/src/cargo/core/resolver/mod.rs) — 自述 "just a naive backtracking version"（证明 Cargo **未**用 PubGrub）

### 分发与命名
- [Go Modules Reference](https://go.dev/ref/mod) — GOPROXY 协议："even a site serving from a fixed
  file system (including a `file://` URL) can be a module proxy"；本地 cache 布局 == proxy URL 空间
- [Defining Go Modules (rsc)](https://research.swtch.com/vgo-module) — go.mod 格式四目标；registry **可选**不是敌对
- [golang/go#23966](https://github.com/golang/go/issues/23966) — Rob Pike vs rsc，「为什么不用 TOML」的定论
- [go.sum Is Not a Lockfile (Filippo Valsorda)](https://words.filippo.io/gosum/) — "go.mod serves as both manifest and lockfile"
- [What we got wrong about HTTP imports (Deno)](https://deno.com/blog/http-imports) — 四条公开尸检
- [build.zig.zon doc](https://github.com/ziglang/zig/blob/master/doc/build.zig.zon.md) — "packages do not come from a `url`; they come from a `hash`"
- [zig#18089](https://github.com/ziglang/zig/issues/18089) / [zig#16272](https://github.com/ziglang/zig/issues/16272) — 内容哈希的平台不稳定教训
- [crates.io policies](https://crates.io/policies) — "deletion is not possible"
- [Package management is a wicked problem (Andrew Nesbitt)](https://nesbitt.io/2026/01/23/package-management-is-a-wicked-problem.html) — "Version the schema, not the tool"

### Maven 复用
- [coursier/interface](https://github.com/coursier/interface) · [Fetch.java](https://github.com/coursier/interface/blob/master/interface/src/main/java/coursierapi/Fetch.java)
- [maveniverse/mima](https://github.com/maveniverse/mima) — tools.deps 底层（32 jars / 3MB）
- [jlbp.dev: Maven vs Gradle 版本解析](http://jlbp.dev/how-does-version-resolution-work-in-maven-and-gradle) — nearest-wins 的降级定时炸弹

### TOML
- [ktoml (orchestr7)](https://github.com/orchestr7/ktoml) · [#376 往返丢表示](https://github.com/orchestr7/ktoml/issues/376) · [#383 接受 151 个非法 TOML](https://github.com/orchestr7/ktoml/issues/383)
- [Cargo.toml](https://raw.githubusercontent.com/rust-lang/cargo/master/Cargo.toml) — 同时依赖 `toml` + `toml_edit` + `toml_parser` + `toml_writer`
- [PEP 518](https://peps.python.org/pep-0518/) — manifest 即代码的死锁

### 已标注的不确定项
- ktoml 不能格式保留：由架构（kotlinx.serialization format，无 CST）+ issue #376 推断，
  **未实跑 parse→edit→write 验证**。
- Ryan Dahl "10 Things I Regret" 原始幻灯片够不到，引述来自三份互相吻合的转录（二手）。
- 「Cargo 团队后悔扁平命名空间」是流传说法，**查无出处，别引**。

---

## 落地记录：项目 B v1（2026-07-22）

**已上线**（双编译器同做、金样互拍守护，冻结纪律首次实战）：

- `[deps]` 别名 → **本地路径包**（值为路径字符串；url + hash 的形态留给版本化阶段，
  表内联写法向前兼容）。别名必须等于包 manifest 的 `name`（§4.3 的别名糖延后）。
- **传递依赖 + 菱形共享**：包可以有自己的 `[deps]`；按规范目录缓存，同一路径的包
  只装载一次——`app → web → json` 与 `app → json` 链接同一个 json，类型身份唯一，
  coherence 免费成立（§4.5 预言的「单版本是承重墙」，path 世界里由文件系统身份兑现）。
  循环依赖报错。
- **类名命名空间**（§4.4 原样）：依赖包模块 = `dawn$pkg$<包名>/<内部路径>`。
- **use 规范化**：包内部裸 `use types` 由 loader 改写为 `use <包名>/types`
  （首段命中自家依赖别名的除外），checker/拓扑/重复检测全程只见一种拼写，零下游改动。
- **库目标**：带 dawn.toml 的目录不再强制 `src/main.dawn`（run/build 缺入口自报）；
  `dawn test packages/web` 直接可跑。
- **第一批真包**：`packages/web`（4 模块 + 10 测试，出自 playground）与
  `packages/json`（游标版正典，出自 examples/m4）；playground 与 site 经 `[deps]`
  消费，`use web/... use json/...` 一字未改——§4.3 承诺兑现。site 的 vendored
  `src/json/` 已删除。
- v1 栅栏：依赖包不得带 `[java-deps]`（合并进消费者 classpath 是下一步）。

**尚未做**：url + hash 抓取与版本（MVS 到那时才有内容）；backend-dawn 迁移
（跨仓库，等 url 形态）；examples/m4/json 保留原样（它是 M4 验收工件与包的上游正典）；
`dawn add` 与格式保留编辑。
