# Dawn

一门**小而优雅的函数式语言**：不可变数据、代数数据类型与穷尽的模式匹配、把效果写进
类型签名。语言小，实现也小——标准库 10 个模块 3,300 行、**零 `use java`**；编译器
**已自举且只此一套**（`selfhost/`，用 Dawn 写的 5.4 万行，最初的 Kotlin 实现归档在
`kotlin-final` tag）。两个**平级**后端：**JVM 字节码**与 **C**（再交给 `cc`）；同一份源码
在两边给出同一个答案，这件事由门禁机器管着，不是一句承诺。

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

## 特别在哪儿

每条后面括号里是**能去核对的东西**：一条门禁、一份实测、一节规范。

### 一、效果进类型，而且不止两级

函数默认纯，碰 IO 必须标 `!io`——看签名即知它碰不碰外界，纯函数测试零 mock。这是基轴。另一条
轴是**用户自己声明的具名效果**：`effect` 声明操作、`with handle` 就地应答，标签随签名传播，
只在 handle 这一个语法节点上被减掉。

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
魔法；代价是不支持多次恢复与非尾恢复。std 与编译器自身**还没**改用具名效果，这个特性是纯
加法。（[docs/spec.md](docs/spec.md) §6.5；对拍语料 `scripts/spike-native/effect_handler.dawn`。）

### 二、两个后端，一个答案，机器保证

多后端语言普遍带着一份「已知分歧」清单。这里没有，因为分歧会红灯：

- `scripts/spike-native/run.sh`——59 个语料程序两边编、两边跑，比 **stdout、stderr、
  退出码**，外加一档 AddressSanitizer。
- `scripts/intrinsic-parity.py`——走原语表，任何 primitive 只在一个后端有实现就红。
- `scripts/native-cli-diff.sh`——把 native 二进制的 `fmt`/`doc`/`add`/`lsp` 输出按**字节**
  钉在 JVM 工具链的输出上。
- 以上每次 push 都跑，另有 `unicode`/`array`/`hamt`/`pvec`/`path`/`inflate`/`error`/`rc`
  八份契约同行。太贵而不进每次 push 的是 `scripts/native-fixpoint.sh`——**整个编译器**：
  JVM 发的 C == native 自己发的 C == 再发一次的 C。

规范把它写成了承诺（[docs/spec.md](docs/spec.md) §12.1）。

### 三、native 侧既没有 GC，也没有 malloc/free

所有权由编译器推导，走 Perceus 引用计数 + 复用分析（`rc == 1` 就地改写）。用户代码里没有任何
内存管理原语。整个编译器前端跑 `checker.dawn` 的实测，在字符串也入账之后：**峰值 RSS
1.46 GB → 81 MB（−94%）**、墙钟 2.77s → 2.10s（−24%）、**LSan 出口不可达 2.46 亿字节 → 0**。
复用分析在整个编译器上就地率 73.8%。（[docs/perceus-design.md](docs/perceus-design.md) §5.7；
门禁 `scripts/rc-contract` 与 spike-native 常开的 `detect_leaks=1`。）

### 四、语义不借宿主

答案不该随宿主的版本变，所以有数据的地方语言自己带数据：

- **Unicode 大小写表与分类表是编译器的**（`selfhost/src/case_table.dawn`、`class_table.dawn`），
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
./bin/dawn run examples/m4/hello_mod        # 编译并运行（单文件或多模块项目）
./bin/dawn test <target>                    # 跑源码里内联的 test 块（构建时剥除）
./bin/dawn build <target> -o app.jar        # JVM 后端：可执行 jar
./bin/dawn build <target> --native -o app   # 上一步 + GraalVM native-image
./bin/dawn fmt <target>                     # 就地格式化（--check 供 CI 校验）
./bin/dawn doc <target>                     # pub API 导出为 JSON；add 保格式编辑 dawn.toml
./bin/dawn lsp                              # LSP 服务器（stdio，编辑器用）
```

依赖有两种：源码包（`url` + `hash` 内容寻址，MVS 选版本——单版本对 Dawn 不是便利而是承重墙，
impl 一致性是全程序唯一映射）与 `[java-deps]`（coursier 解析 Maven 传递依赖，只在 JVM 后端
有意义），见 [docs/package-design.md](docs/package-design.md)。注意 `--native` 走的是
**GraalVM native-image**（拿上一步的 jar 去编），跟下面那个 C 后端是两条不同的路。

内置 LSP 服务器两个后端各有一份、输出逐字节对齐：实时诊断、悬停、跳转定义、文档大纲；
前端做了完整的错误恢复，文件残缺时一次报出全部错误。VS Code / Neovim / Helix 配置见
[editors/](editors/)。

### 不装 JVM 的那条路

**从 v0.50.0 起**，每个 release 还挂着 **`dawnc-linux-x86_64`**：C 后端编出来的单文件静态
可执行程序（约 3.6 MB），std 与 C 运行时都嵌在里面，不需要这个仓库、也不需要 JVM。

子命令是 `check|emitc|build|run|test|fmt|doc|add|lsp`；`build`/`run` 会调用机器上的 `cc`
（`$CC` 可覆盖），其余的不碰 C 工具链。它**拒绝 `use java`**——那是这个后端的答案，不是缺陷；
打包成 jar、`lock`、`cache` 需要 JVM，故不在它的子命令里。只有 linux-x86_64 一个目标，理由见
[docs/native-driver-plan.md](docs/native-driver-plan.md) §22.1。

**说准一点**：「用 Dawn 可以完全不碰 JVM」成立——从编译器到产物有一条完整的路径；但
**自举种子仍然是 jar**（`scripts/seed-release.txt`），`bin/dawn` 仍是 JVM 工具链，JVM
后端仍是一等目标。

## 文档

- [docs/tutorial.md](docs/tutorial.md) — 上手教程
- [docs/design.md](docs/design.md) — 设计目标与决策记录（为什么是这样而不是那样）
- [docs/spec.md](docs/spec.md) — 语言规范（权威定义）
- [docs/bootstrap.md](docs/bootstrap.md) — 自举链与种子推进协议
- [docs/README.md](docs/README.md) — 全部设计文档的索引，每份都标了状态；示例在 [examples/](examples/)

## 状态

当前工具链 0.50.0，M0–M8 已实现。此后的主线（C 后端与 native 自举、Perceus、trait v2、
效果处理器、包管理）落地记录在 `docs/` 各自的设计文档里。

## 许可证

[Apache-2.0](LICENSE)。`dawn` fat jar 打包的第三方代码及其各自的许可证见 [NOTICE](NOTICE)。
