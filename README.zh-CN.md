<!-- doc-check: translation-of README.md @ be4b8f53decdafc2 -->

# Dawn

*[English](README.md) — 正本是英文；本文是它的译本，`scripts/doc-check.py` 盯着两者不脱节。*

一门**小而优雅的函数式语言**：不可变数据、代数数据类型与穷尽的模式匹配、把效果写进
类型签名。语言小，实现也小——紧凑的标准库保持**零 `use java`**；编译器**已自举且只此一套**
（最初的 Kotlin 实现归档在 `kotlin-final` tag）。两个**平级**后端：**JVM 字节码**与 **C**
（再交给 `cc`）；同一份源码在两边给出同一个答案，这件事由门禁机器管着，不是一句承诺。

```dawn run
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)

fn area(s: Shape) -> Float =
  match s {
    Circle(r)  -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }

pub fn main() -> Unit !io =
  [Circle(1.0), Rect(2.0, 3.0)]
    |> map(area)
    |> fold(0.0, (a, x) => a + x)
    |> t => println("total: $t")
```

## 安装

每个 release 挂四件安装资产：两个产物，外加各自的 SHA-256。**请核对摘要**。工具链自举用的种子
每次使用前都要验一遍，安装这一步如果跳过同样的核对，那这套纪律就只在这里断了。

**不装 JVM**（linux-x86_64）：一个静态可执行文件，`std` 与 C 运行时都在里面。

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawnc-linux-x86_64
curl -fsSLO $base/dawnc-linux-x86_64.sha256
sha256sum -c dawnc-linux-x86_64.sha256
chmod +x dawnc-linux-x86_64 && sudo mv dawnc-linux-x86_64 /usr/local/bin/dawnc

printf 'pub fn main() -> Unit !io = println("hello, dawn")\n' > hello.dawn
dawnc run hello.dawn
```

**装 JVM**（JDK 21 及以上，任意平台）：工具链 jar 自带 `std`，所以这个 jar 本身就是整套工具链。

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawn-selfhost.jar
curl -fsSLO $base/dawn-selfhost.jar.sha256
sha256sum -c dawn-selfhost.jar.sha256      # macOS 上是 shasum -a 256 -c

printf 'pub fn main() -> Unit !io = println("hello, dawn")\n' > hello.dawn
java -jar dawn-selfhost.jar run hello.dawn
```

这两件是**两个不同的编译器**，不是同一个东西的两种下载方式。`dawnc` 是 C 后端，它拒绝
`use java`；jar 是 JVM 工具链。该选哪个、各自做不到什么，见下面的[工具链](#工具链)一节。

release 还挂两件**描述**它、而不是安装它的文件：`dawn-pub-api.json` 是 `std` 与 `packages/`
里每一条公开签名连同它的效果行，`dawn-pub-api-diff.md` 是与上一个 release 的分类差异。
升级前该读的是后者。效果就在类型里，所以某个单元开始做 IO 是藏不住的：报告会把这次扩张点名。
它是报告不是门禁，而且它比的是签名，不是行为。

**从仓库检出**（本文其余部分默认的就是这条路）：`./bin/dawn` 首次运行会下载种子、按
`scripts/seed-checksums.txt` 验它，再用它编译 HEAD。

### 一个项目

一个项目就是一个装着 `src/main.dawn` 的目录。没有别的东西要创建，所以也没有 `dawn new`：

```text
myapp/
├── dawn.toml     # 有依赖之后才需要
└── src/
    └── main.dawn # pub fn main() -> Unit !io
```

`dawn run myapp` 编译并运行它；`src/` 下放多少个模块都行，`examples/projects/hello_mod`
就是这个形状、里面放了三个。`dawn.toml` 起手是两行 `schema = 1` 与 `name = "myapp"`，
之后交给 `dawn add <spec> --dir myapp` 维护。

## 特别在哪儿

每条后面括号里是**能去核对的东西**：一条门禁、一份实测、一节规范。

### 一、效果进类型

函数默认纯，碰 IO 必须标 `!io`——看签名即知它碰不碰外界，纯函数测试零 mock。这条轴处处承重：
`std` 绝大部分是纯的、并且在签名上说了；编译器给自己不纯的那些部分打标；签名不说而函数伸手到
外界，是编译错误。（`scripts/doc-check.py` 的 effect-inference 探针把两个分支都钉住了：显式声明为纯
却调用 `println` 的签名被拒，不写效果的那个推断出 `!io`。）

还有第二条轴，而这个仓库里还没有任何东西用它：**用户自己声明的具名效果**。`effect` 声明操作、
`with handle` 就地应答，标签随签名传播，只在 handle 这一个语法节点上被减掉。

```dawn run
effect Ask {
  fn ask() -> Int
}

## 纯函数。签名上写着它要问，但没说去哪儿问。
fn total() -> Int !Ask = ask() + ask()

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 21 }
  println("${total()}")
}
```

这一档是**尾恢复**：handler 臂就是普通闭包，没有延续捕获，于是两个后端不必为它各造一套栈
魔法；代价是不支持多次恢复与非尾恢复。它有规范、两个后端都实现了、对拍语料也盯着，并且有了
**第一个内部使用者**：`std/io` 声明了 `Fs`，把文件系统写成十四个操作，生产安装的 handler 是
`with_fs_real`，于是测试可以用一张表应答一次文件读取。第二个是 `std/gpu`：它声明了 `Gpu`，把设备的宿主侧写成
六个操作，测试安装的 handler 是一个纯的假设备，于是 `!Gpu` 程序在没有 GPU 的机器上也能跑。这是
`std/` 与 `selfhost/src/` 下仅有的两条声明；`doc-check.py` 持有这份清单（`NAMED_EFFECT_EXPECTED`），清单外冒出声明、或这一条
消失，它都会把这一段判红。所以请把它读成一个扛过一条真实接缝、还没扛过一个真实程序的可用特性，
而不是「Dawn 与众不同」的那个理由。
（[docs/spec.md](docs/spec.md) §6.5；对拍语料 `scripts/spike-native/effect_handler.dawn`。）

### 二、两个后端，一个答案，机器保证

多后端语言普遍带着一份「已知分歧」清单。这里没有，因为分歧会红灯：

- `scripts/spike-native/run.sh`——整套差分语料两边编、两边跑，比 **stdout、stderr、
  退出码**，外加一档 AddressSanitizer。
- `scripts/intrinsic-parity.py`——走原语表，任何 primitive 只在一个后端有实现就红。
- `scripts/native-cli-diff.sh`——把 native 二进制的 `fmt`/`doc`/`add`/`lsp` 输出按**字节**
  钉在 JVM 工具链的输出上。
- 以上每次 push 都跑，另有 `unicode`/`array`/`hamt`/`pvec`/`path`/`inflate`/`error`/`rc`
  八份契约同行。太贵而不进每次 push 的是 `scripts/native-fixpoint.sh`——**整个编译器**：
  JVM 发的 C == native 自己发的 C == 再发一次的 C。

规范把它写成了承诺（[docs/spec.md](docs/spec.md) §12.1）。它的**适用范围**是两个后端都能编的
那些程序：C 后端拒绝 `use java`，所以带 Java 互操作的程序只有一个答案、不在对拍之内。这条边界
划在哪儿，见[两样东西都叫「native」](#两样东西都叫native)。

### 三、native 侧既没有 GC，也没有 malloc/free

所有权由编译器推导，走 Perceus 引用计数 + 复用分析（`rc == 1` 就地改写）。用户代码里没有任何
内存管理原语。整个编译器前端跑 `checker.dawn` 的实测，在字符串也入账之后：**峰值 RSS
1.46 GB → 81 MB（−94%）**、墙钟 2.77s → 2.10s（−24%）、**LSan 出口不可达 2.46 亿字节 → 0**。
同一次运行里，复用分析把大多数机会写成了就地改写而不是复制（写下这句时是 `array_with`
调用的 83%；它是个比率，下面的门禁给它立预算而不是钉死）。
（[docs/perceus-design.md](docs/perceus-design.md) §5.7、§6.4；门禁 `scripts/rc-contract`、
`scripts/array-contract`、`scripts/map-reuse-contract` 与 spike-native 常开的 `detect_leaks=1`。）

### 四、语义不借宿主

答案不该随宿主的版本变，所以有数据的地方语言自己带数据：

- **Unicode 大小写表与分类表是编译器的**（`selfhost/src/embed/unicode_case.dawn`、`unicode_class.dawn`），
  codegen 写进 `dawn/rt/Strings`、`__emitc` 写进生成的 C，两边领同一份表。从前是一边
  `Character.toUpperCase`、另一边生成的头文件——那只在两个 JDK 的 Unicode 版本恰好相同时才是
  「一个答案」。（`scripts/unicode-contract`，每次 push。）
- **`Float` 渲染是纯 Dawn 的 Schubfach**（`std/fmt.dawn`），规则由规范拥有，宿主换算法也不跟。
- **UTF-8 解码器是自己的严格 walker**（`runtime/c/dawn_rt.c`）：拒 overlong 形式、代理半区、
  超出 U+10FFFF，畸形输入答 U+FFFD 并报告吃掉几个字节。
- `Ord[String]` 是**码点序**，`cmp` 只承诺 `-1`/`0`/`1`（[docs/spec.md](docs/spec.md) §3.5）。

### 五、trait 有条件 impl 和关联类型，集合是 Dawn 写的

单参数、名义式的 typeclass，字典传递。条件 impl（`impl[T: Eq] Eq[List[T]]`）与关联类型
（`type Item`，`C.Item` 投影随实例化归约）都在；六个预置 trait 里有四个背着语法：
`Eq`→`==`、`Show`→`${...}`、`Iter`→`for..in`、`Index`→`[]`，用户类型写个 impl 就能用。
没有单态化——**具体类型的调用点不走字典，直接静态调用**，字典只在泛型边界出现。

`Map`/`Set` 是 32 路 HAMT、持久 `List` 是 pvec，都在 `std/` 里用纯 Dawn 写。后端要实现的
集合原语只有 `Array` 的五个操作加一个 `popcount`——所以新后端把全部容器白拿。
（[docs/spec.md](docs/spec.md) §3.5、§4.8；[docs/trait.md](docs/trait.md)；
门禁 `hamt-contract`/`pvec-contract`/`array-contract`。）

### 六、自举，而且种子纪律是机器强制的

链条是 种子 → A → B → C，`cmp B C` 必须逐字节相等；tag 上 `release.yml` 重跑整条链，任一环红
则 release 不出。`selfhost/src` 只准用**当前种子已支持**的语言特性——种子编不动 HEAD 直接红。
日常的 oracle 是 `scripts/selfhost-prev-diff.sh`：上一 release 与 HEAD 编同一语料，**未声明的
字节差异红灯**。（[docs/bootstrap.md](docs/bootstrap.md)。）

## 同样重要的是没有什么

没有 null、没有继承、没有宏（要编译期计算就写 `comptime { ... }`，结果烧进常量池）、
没有 async、没有**用户自定义**运算符（运算符集固定，其中四个经上面那些 trait 分派到你的
类型）、没有可变引用。理由见 [docs/design.md](docs/design.md)。

**「没有异常」要说准**：Dawn 没有 `throw`/`catch`，可恢复失败一律走 `Result` + `?`。
但 `use java` 调用抛出的异常仍会**穿透** Dawn 栈并终止程序（等同 panic 语义）——边界上有
两个屏障，都返回 `Result[T, ForeignError]`：`catch_fault` 拦外部失败、放 panic 穿透，
`catch_panic` 是隔离点（单个请求 panic 变 500，而不是掀翻进程）。`bracket` 谁也不拦，只
保证 release 在每条退出路径上恰好跑一次。`cast` 已经**不抛**了：它签名为纯，失败是一个值。
这条分工与后端无关——native 没有异常，失败带一个种类走同一条 `longjmp`。
（[docs/spec.md](docs/spec.md) §9.8。）

## 工具链

`<target>` 可以是单个 `.dawn` 文件，也可以是项目目录（`src/main.dawn` 为入口）。

```bash
# 需要 JDK 21。首次运行自动下载种子（上一 release 的 dawn-selfhost.jar）并用它编译 HEAD。
./bin/dawn run examples/projects/hello_mod        # 编译并运行（单文件或多模块项目）
./bin/dawn test <target>                    # 跑源码里内联的 test 块（构建时剥除）
./bin/dawn build <target> -o app.jar        # JVM 后端：可执行 jar
./bin/dawn build <target> --native -o app   # 把上一步那个 jar 交给 GraalVM native-image 打包
                                            #   （不是 C 后端；见下）
./bin/dawn fmt <target>                     # 就地格式化（--check 供 CI 校验）
./bin/dawn doc <target>                     # pub API 导出为 JSON；add 保格式编辑 dawn.toml
./bin/dawn lsp                              # LSP 服务器（stdio，编辑器用）
```

依赖有两种：源码包（`url` + `hash` 内容寻址，MVS 选版本——单版本对 Dawn 不是便利而是承重墙，
impl 一致性是全程序唯一映射）与 `[java-deps]`（coursier 解析 Maven 传递依赖，只在 JVM 后端
有意义），见 [docs/package-design.md](docs/package-design.md)。

内置 LSP 服务器两个后端各有一份、输出逐字节对齐：实时诊断、悬停、跳转定义、文档大纲；
前端做了完整的错误恢复，文件残缺时一次报出全部错误。VS Code 扩展已上
[marketplace](https://marketplace.visualstudio.com/items?itemName=dawnop.dawn-lang)
（`dawnop.dawn-lang`）；Neovim / Helix 配置见 [editors/](editors/)。

### 两样东西都叫「native」

`dawn build --native` 与 `dawnc` 都会给你一个不装 JVM 也能跑的可执行文件，但它们不是同一条路。
光看这个词分不出你在哪条上：

| | `dawn build --native` | `dawnc` |
|---|---|---|
| 它是什么 | 拿 JVM 后端刚写出来的 jar 过一遍 GraalVM `native-image` | C 后端：Core 出 C，交给 `cc` |
| 你的代码由谁编 | JVM 字节码 | C |
| `use java` | 可用，编进映像里 | **拒绝**，有意为之 |
| `[java-deps]` | 解析并带上 | 无此概念 |
| 机器上要有 | GraalVM `native-image` | 一个 `cc` |
| 从哪儿来 | 自己在仓库检出里跑出来 | 每个 release 挂的 `dawnc-linux-x86_64` |
| 目标平台 | GraalVM 能跑的地方 | 只有 linux-x86_64 |

一个文件就能说清。`examples/interop/interop.dawn` 用了 `use java`：`dawn build --native`
写出一个跑得起来的可执行文件；`dawnc check` 对同一个文件答的是
`Java interop needs a JVM host with a class path to resolve java.lang.String against;
this build has none`。

撞名是历史造成的：`--native` 比 C 后端早，而 `scripts/` 下所有带 `native` 的东西
（`spike-native`、`native-fixpoint.sh`、`native-cli-diff.sh`、`release-native.sh`）指的都是
C 后端，不是那个 flag。把 flag 读成「把 JVM 那份产物提前打包」，把脚本读成「第二个后端」。

**上面那条对等承诺的范围也在这里。**「两个后端一个答案」说的是两个后端都能编的那些程序，
凡是带 `use java` 的都在范围之外——那些程序根本没有第二个答案可比。`scripts/spike-native/`
下的每个语料入口按构造就在这个交集里。

### 不装 JVM 的那条路

**从 v0.50.0 起**，每个 release 还挂着 **`dawnc-linux-x86_64`**：C 后端编出来的单文件静态
可执行程序，std 与 C 运行时都嵌在里面，不需要这个仓库、也不需要 JVM。

子命令是 `check|emitc|build|run|test|fmt|doc|add|lsp`；`build`/`run` 会调用机器上的 `cc`
（`$CC` 可覆盖），其余的不碰 C 工具链。打包成 jar、`lock`、`cache` 需要 JVM，故不在它的
子命令里。只有 linux-x86_64 一个目标，理由见
[docs/native-driver-plan.md](docs/native-driver-plan.md) §22.1。

**说准一点**：「用 Dawn 可以完全不碰 JVM」成立——从编译器到产物有一条完整的路径；但
**自举种子仍然是 jar**（`scripts/seed-release.txt`），`bin/dawn` 仍是 JVM 工具链，JVM
后端仍是一等目标。

## 文档

站点渲染的每一篇都有中英两版：本 README（[README.md](README.md) 是正本，本文是译本）、
站点首页、教程、标准库参考、规范与设计笔记。最后那两篇是其中唯一以中文为正本的一对——
每次改语言都在中文里改它们，所以正文写在那边，英文按它登记。`docs/` 其余部分是设计方案、
计划与落地日志，**仍然是中文的**，这是有意为之、且暂时不变：它的读者是作者本人，一段要先
翻译才能写出来的话，就是一段写不出来的话。

- [docs/tutorial.md](docs/tutorial.md) — 上手教程（另有[中文版](docs/tutorial.zh-CN.md)）
- [docs/design.en.md](docs/design.en.md) — 设计目标与决策记录（为什么是这样而不是那样；
  正本是 [docs/design.md](docs/design.md)）
- [docs/spec.en.md](docs/spec.en.md) — 语言规范（权威定义；正本是 [docs/spec.md](docs/spec.md)）
- [docs/bootstrap.md](docs/bootstrap.md) — 自举链与种子推进协议（中文）
- [docs/README.md](docs/README.md) — 全部设计文档的索引，每份都标了状态；示例在 [examples/](examples/)

## 状态

当前工具链 0.72.0，M0–M8 已实现。此后的主线（C 后端与 native 自举、Perceus、trait v2、
效果处理器、包管理）落地记录在 `docs/` 各自的设计文档里。

## 路线图与贡献

[ROADMAP.md](ROADMAP.md)（英文）写明工作朝哪去、哪些线已关账；具体可上手的
起点放在 GitHub issues 里。[CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)
讲清一个改动在这里从想法走到代码的路：先写设计文档，用门禁代替审查清单。

## 许可证

[Apache-2.0](LICENSE)。`dawn` fat jar 打包的第三方代码及其各自的许可证见 [NOTICE](NOTICE)。
