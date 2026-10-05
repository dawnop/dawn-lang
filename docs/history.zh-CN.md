<!-- doc-check: translation-of docs/history.md @ eaad6c511a5d89b8 -->

# 历史

*[English](history.md) · 正本是英文；本文是它的译本，`scripts/doc-check.py` 盯着两者不脱节。*

> 状态：**current**。项目从第一个提交到今天的时间线；有工作线落地就往后续写，不改写已有条目。

这一页按条目讲 Dawn 从第一个提交到今天的历史，一条工作线一条。
它按时间正序分六个时期，每条给出日期、首次带上它的 release（如果有），以及一句话说清改了什么。
每条的权威出处是它链到的设计文档或规范章节；日期是 UTC+8 的提交日期，背后的提交在 `git log` 里。

## M0–M7：从零到自举（2026-07-11 至 07-22）

- **2026-07-11。** M0 与 M1：第一天就有了一个编译到 JVM 字节码的 Kotlin 编译器和一个语言服务器，
  到当天结束，语言已经有了带穷尽性检查的 ADT、记录、泛型、lambda、效果变量、`?` 与 test 块。
  （[早期设计决定](design.md)）
- **2026-07-12。** M2、M3、M4 同一天收尾：comptime、`use java` 与核心标准库；
  报错 golden、`dawn fmt` 与第一版教程；模块、`Map`/`Set` 与多文件项目，验收物是一个
  通过 JSONTestSuite 的纯 Dawn JSON 库。互操作三件套（SAM 转换、数组直通、List 桥）
  同日落地。（[早期设计决定](design.md)）
- **2026-07-12。** M5：项目站点上线，由一个 Dawn 写的程序生成，它的 JVM 与 native 构建
  产出逐字节相同；Playground 的后端也是 Dawn 程序，编辑器有了实时诊断。
- **2026-07-12 至 07-13。** trait v1：单参数名义 typeclass 加字典传递，
  `derive Ord`，比较运算符桥接到 `Ord`。（[trait.md](trait.md)）
- **2026-07-14 至 07-16。** M6：dawnop.com 的生产后端用 Dawn 分十三刀重写（07-14），
  流量全量切换（07-15），Python 服务退役（07-16）。（[m6.md](history/m6.md)、[m6-retro.md](history/m6-retro.md)）
- **2026-07-16。** `Bytes` 成为一等类型，退役了后端重写暴露出来的 Latin-1 字符串绕行写法。
  （[bytes-design.md](bytes-design.md)）
- **2026-07-17，v0.1.0。** 第一个打了 tag 的 release；从此打 tag 即发布编译器 jar。
  带 `[java-deps]` 的 `dawn.toml` 随它发布，取代了手抄的 classpath。
- **2026-07-18 至 07-22，v0.2.1。** 纯 FFI：`unsafe_pure` 让一个宿主调用撑起一个纯函数，
  builtin 从编译器的表里搬进 std；整条迁移于 07-22 关账。（[pure-ffi-design.md](pure-ffi-design.md)）
- **2026-07-21，v0.3.0。** `Map` 与 `Set` 换成持久哈希字典树，结束了 copy-on-write 的平方代价。
- **2026-07-22，v0.6.0。** M7：Dawn 写的编译器到达固定点（stage 2 与 stage 3 逐字节相同），
  Kotlin 编译器冻结为自举链的根。（[bootstrap.md](bootstrap.md)）
- **2026-07-22，v0.7.0 与 v0.8.0。** 包管理 v1：`[deps]` 源码包，随后是按最小版本选择解析的
  url + hash 依赖，以及 `dawn add`。（[package-design.md](package-design.md)）

## 只剩一个编译器（2026-07-23 至 07-31）

- **2026-07-23，v0.8.0。** M8：第一个由自举编译器构建的 release 成为种子，Kotlin 实现归档在
  `kotlin-final` tag，从此每个 release 都是下一个的种子。（[m8-selfhost-only.md](history/m8-selfhost-only.md)、
  [bootstrap.md](bootstrap.md)）
- **2026-07-25，v0.12.0。** Core IR：带类型的树降到一个小的共享 IR 上，C 后端从它出发。
  （[native-backend-plan.md](native-backend-plan.md)）
- **2026-07-26，v0.15.0。** trait v2：`==` 要求 `Eq` bound，impl 可以带条件。
  （[trait-v2-design.md](trait-v2-design.md)）
- **2026-07-27，v0.25.0 与 v0.26.0。** 集合离开 Java：`Map` 与 `Set` 是 `std/hamt`，
  `List` 是 `std/pvec`，都用 Dawn 写成，运行时不再留任何集合类。
  （[collections-dejava-research.md](collections-dejava-research.md)）
- **2026-07-29，v0.31.0。** C 后端的 Perceus 引用计数：所有权推断、`dup`/`drop`、原地复用，
  再把字符串也记进账，编译器前端在同一输入上的峰值内存从 1.46 GB 降到 81 MB。
  （[perceus-design.md](perceus-design.md)）
- **2026-07-30，v0.31.0。** C 后端自举：native 编译器到达自己的固定点，B == C。
  （[native-backend-plan.md](native-backend-plan.md)）

## 效果与前端（八月）

- **2026-08-01，v0.44.0。** 具名效果：用户声明 `effect`，用 `with handle` 处理，
  先从尾恢复的 handler 做起。（[effects-design.md](effects-design.md)、
  [spec.md](spec.md) §6）
- **2026-08-02，v0.45.0 至 v0.47.0。** 关联类型，`Iter` 成为 prelude trait 并承接 `for..in`，
  `[]` 经 `Index` trait 解析。
  （[assoc-types-design.md](assoc-types-design.md)、
  [operator-traits-design.md](operator-traits-design.md)）
- **2026-08-03，v0.50.0。** 后端上的两条线：JVM 侧收缩可信底座，直到 `dawn/tool` 退出 jar；
  native 驱动补全，并把后端契约写成文字。（[jvm-base-plan.md](jvm-base-plan.md)、
  [native-driver-plan.md](native-driver-plan.md)）
- **2026-08-04，v0.50.0。** native 编译器 `dawnc` 作为 release 资产发布。
  （[bootstrap.md](bootstrap.md)）
- **2026-08-05 至 08-07，v0.52.0 至 v0.58.0。** 站点双语化（英文在 `/`，中文在 `/zh/`）；
  教程改以英文为正本，记录的输出纳入检查，规范与设计文档有了英文译本。
- **2026-08-06，v0.57.0。** `Char` 成为 `Int` 上的 opaque type。
  （[nominal-types-design.md](audit/nominal-types-design.md)）
- **2026-08-08，v0.61.0。** 尾块、具名实参与默认参数，这是声明式 UI 语言会需要的语法。
  （[tail-block-design.md](tail-block-design.md)、
  [named-args-design.md](named-args-design.md)）
- **2026-08-08。** 第二次全仓审查，以 v0.60.0 为冻结基线。
  （[codebase-audit-v2.md](codebase-audit-v2.md)）
- **2026-08-19 至 08-20，v0.67.0。** 效果参数，定案为 trait 上的关联效果。
  （[effect-params-design.md](effect-params-design.md)）
- **2026-08-20。** VS Code 扩展上架 marketplace（10-01 发 0.1.2）。
- **2026-08-20，v0.68.0。** wasm32-wasi 目标（`dawnc build --target wasm`），带自己的失败运行时。
- **2026-08-20 至 08-28。** 用 Dawn 写的 Elm 架构：`packages/tea`（08-20），拆成核心与终端两半
  （08-22）；建在 wasm reactor 上的 `packages/tea-dom`（08-26）；浏览器 Demo `/tea.html`
  （08-28，v0.70.0）。（[dom-bridge-design.md](dom-bridge-design.md)）
- **2026-08-21 至 08-24，v0.68.0。** 效果证据改由调用点传入，规范第 6 节随之重写。
  （[spec.md](spec.md) §6）
- **2026-08-27 至 08-30，v0.69.0 至 v0.71.0。** native 内存第二轮：全程序推断借用形参（08-27），
  小对象从按尺寸分级的 slab 分配（08-28），slab 每次物化 32 KiB（08-30）。
  （[perceus-design.md](perceus-design.md)、[slab-residency-design.md](slab-residency-design.md)）
- **2026-08-29 至 08-30，v0.70.0。** handler 局部状态：在 handler 里声明的 `var`，不得逃出它。
  （[handler-state-design.md](handler-state-design.md)）
- **2026-08-30，v0.71.0。** Playground 有了真正的语言服务器：每个浏览器 buffer 对一个隔离的
  native LSP 进程。（[playground-lsp-design.md](playground-lsp-design.md)）
- **2026-08-31 至 09-01，v0.71.0。** 一次性恢复：`ctl` 效果、`resume k` 与 `discard`，
  两个后端都支持。（[oneshot-design.md](oneshot-design.md)）

## 设备与标准库（2026-09-01 至 09-07）

- **2026-09-01，v0.71.0。** 每个 release 附带公开 API 快照，以及相对上一版的分类差异。
- **2026-09-02 至 09-04，v0.71.0 至 v0.76.0。** 标准库的效果按触及的对象拆开：
  `Fs`（09-02），`Proc` 与 `Env`（09-03），`Exit` 与 `Console`（09-04）；
  native 编译器自己就跑在这五个真实 handler 之下。
- **2026-09-02，v0.72.0。** 经 cuTile 面向 NVIDIA GPU 的设备后端：带假设备的 `Gpu` 效果、
  `packages/tileir`，以及端到端的 `vadd`。
  （[tile-backend-design.md](tile-backend-design.md)）
- **2026-09-03 至 09-07，v0.73.0 至 v0.77.0。** leetgpu 题目台账及覆盖它的战役、view 族，
  以及 sm_100 上的第二本台账。
  （[tile-backend-design.md](tile-backend-design.md)）
- **2026-09-04 至 09-07，v0.76.0 至 v0.77.0。** 程序不再携带它够不着的东西：std 按程序裁剪
  （09-04），控制运行时也一样（09-05），再把 `std/pvec` 一并裁掉后，hello-world 的 C
  从 1,205 行降到 438 行（09-07）。
  （[std-pruning-design.md](std-pruning-design.md)、
  [control-freight-design.md](control-freight-design.md)）
- **2026-09-07，v0.77.0。** `tea` 有了命令：`update` 返回 `(model, Cmd)`。

## 收紧（2026-09-08 至 09-30）

- **2026-09-08 至 09-27。** 一个增量语义引擎以 opt-in 方式建起来（第一期 09-08，声明身份 09-13），
  对照目标实测三次，其 opt-in 切片于 09-27 拆除（tag `incremental-slice-final`）；
  它留下的身份与调度保留。（[incremental-semantics-removal.md](incremental-semantics-removal.md)、
  [incremental-semantics-design.md](history/incremental-semantics-design.md)）
- **2026-09-23 至 09-26，v0.78.0 至 v0.79.0。** GitHub 之外的门禁：全部门禁可在本地或集群上跑，
  证据签名写进 `refs/notes/gates`，release 接受它（09-24），带着它的 pull request 跳过托管门禁（09-26）。
  （[gates-external-design.md](gates-external-design.md)）
- **2026-09-24 至 09-25，v0.78.0。** 09-24 的各条裁决一起落地：`pub(pkg)`；语法窗口
  （五个关键字降为上下文关键字、删 `$name` 插值、或-模式可带前导 `|`）；效果窗口
  （`io` 是唯一的环境效果、删 `unsafe_pure`）；未用 import 报错；builtin 类型特权；门禁漂移守卫。
  （[package-visibility-design.md](package-visibility-design.md)、
  [syntax-window-design.md](syntax-window-design.md)、
  [effects-window-design.md](effects-window-design.md)、
  [unused-imports-design.md](unused-imports-design.md)、
  [builtin-privileges-design.md](builtin-privileges-design.md)、
  [gate-drift-guards-design.md](gate-drift-guards-design.md)）
- **2026-09-25 至 09-26，v0.79.0。** 门禁成本棘轮：每次 push 的门禁总时长有上限，
  只有提交里带声明才能上调。（[gate-drift-guards-design.md](gate-drift-guards-design.md)）
- **2026-09-25 至 09-30，v0.79.0。** `packages/web` 进入第五个 major，收窄公开面。
  （[web5-design.md](web5-design.md)）
- **2026-09-26 至 09-27，v0.79.0。** symbol ID：顶层函数在依赖图、调度、header 产物与 LSP 里
  一律以声明路径标识。
  （[symbol-id-design.md](symbol-id-design.md)）
- **2026-09-28 至 09-30，v0.79.0 至 v0.80.0。** LSP 记住每个模块的检查步骤；编译器自身工作区的
  sync 中位数从 1.5–2.0 s 降到 0.05–0.39 s，随后复用改为按模块实际导入的内容键控。
  （[lsp-module-memo-design.md](lsp-module-memo-design.md)）

## 十月

- **2026-10-01，v0.80.0。** 标准库形参名冻结，改动须带 `Param-Change` 声明。
  （[stdlib-naming.md](stdlib-naming.md)）
- **2026-10-01，v0.80.0 至 v0.81.0。** 符号链接，分三步：`std/memfs` 作为内存中的 `Fs` handler、
  `Fs.real_path`、编译器测试迁到它上面；v0.81.0 之后在 main 上，包、模块与工作区的身份
  经链接解析。
  （[fs-real-path-design.md](fs-real-path-design.md)）
- **2026-10-01，v0.81.0。** `web` 5.1 给路由一个有类型的 body 上限，在读 body 之前检查；
  5.2 随后进了 main。（[web5-design.md](web5-design.md)）
- **2026-10-01。** 站点审计并分三批修复：教程从 release 下载开始，Playground 压缩发布并保留编辑，
  站点与 Playground 按 release tag 部署。
- **2026-10-01。** GPU 参考实现从 `std/gpu` 迁到 `packages/tileref`
  （已在 main，尚未发版）。（[tile-backend-design.md](tile-backend-design.md)）
- **2026-10-06。** `+ - * / %` 与一元 `-` 经六个 prelude trait（`Add` 到 `Neg`）用到程序自己的类型上，
  每个都带一个设备类型可以绑定的效果成员；Int 与 Float 保留原生运算，不透明类型不继承目标的算术。
  这六个名字从此不能再用作 `trait` 或 `effect` 的名字（已在 main，尚未发版）。
  （[arith-operator-traits-design.md](arith-operator-traits-design.md)）
- **2026-10-06。** 数字字面量按期望定型：`let f: Float = 1` 与 `3.14159 * 2 * r` 都能编译，
  程序自己的类型经 `FromInt`、`FromFloat` 接收字面量，纯 impl 在编译期执行，所以 `let b: U8 = 300`
  是编译错误，而范围写在库里（已在 main，尚未发版）。（[literal-system-design.md](literal-system-design.md)）

从 2026-07-17 的 v0.1.0 到 2026-10-01 的 v0.81.0，共 83 个 release tag。

## 被推翻的决定

早期决定按当时写下的样子保留。其中后来被推翻的，这张表写明被什么取代、在何时。

| 当初 | 现在 | 何时 |
|---|---|---|
| 编译器用 Kotlin 写，预算 6–8 千行（§1、D7） | 唯一的编译器是 `selfhost/` 里的自举实现；Kotlin 实现只留在 `kotlin-final` tag | 2026-07-23 |
| 日常工具链（run、test、fmt、doc、LSP）仍是 Kotlin 版（M7） | 全部工具都来自自举编译器 | 2026-07-23 |
| Kotlin 编译器冻结为 bootstrap 种子，学 Go 保留 go1.4（M7） | 种子是上一个 release 的 `dawn-selfhost.jar`；v0.6.0 仍是可重放链条的根 | 2026-07-23 |
| 唯一后端是 JVM 字节码，native 由 GraalVM native-image 得到（§1、D1） | C 后端与 JVM 后端平级并已自举，另有面向 GPU 的 cuTile 后端 | 2026-07-30；2026-09-02 |
| 无中间 IR（D6） | Core IR 位于检查与两个后端之间 | 2026-07-25 |
| JVM 的 GC 就是我们的 GC（非目标表） | native 后端没有 GC，内存由 Perceus 引用计数管理 | 2026-07-29 |
| 效果系统只有两级：pure 与 io（D2） | 用户可声明具名效果并处理它们；`io` 是唯一的环境效果 | 2026-08-01；2026-09-24 |
| 纯度/效果标记致谢 Flix，「简化到两级」（§4） | 带 handler、控制臂与 handler 状态的具名效果；勘察过的先例是 Koka 与 Effekt | 2026-08-01 |
| 延续捕获与 C 后端的单栈模型冲突（非目标表） | 一次性恢复（`ctl`、`resume k`、`discard`）两个后端都支持；仍不做的只有多次恢复 | 2026-08-31 至 09-01 |
| unsafe 逃生门不向用户代码开放（D5） | `unsafe_pure` 曾向用户开放，后收窄到 std，再连同关键字删除 | 2026-07-18；2026-07-30；2026-09-24 |
| `TList` 运行时就是 `java.util.List`，桥成本约一次调用（D8） | `List` 是用 Dawn 写的 `std/pvec`；交给 Java 的 `List` 以 `Array` 过桥 | 2026-07-27 |
| 单参数 trait，无条件 impl；`==` 保持结构相等（D9、trait v1） | 条件 impl、关联类型，`==` 走 `Eq` bound | 2026-07-26；2026-08-02 |
| `Map`/`Set` 是 copy-on-write 的 `LinkedHashMap`/`LinkedHashSet`（M4） | 持久哈希字典树，07-27 起用 Dawn 写成 | 2026-07-21；2026-07-27 |
| 无 `dawn.toml`，目录约定即工程（M4） | `dawn.toml` 可选，承载工程身份与依赖 | 2026-07-17；2026-07-22 |
| 字符字面量是 `Int`（M4） | `'a'` 的类型是 `Char`，`Int` 上的 opaque type | 2026-08-06 |
| 教程 11 章，由 Kotlin 测试检查（M3） | 17 章，英文为正本，每个 `dawn run` 块由 `doc-check.py` 实跑 | 2026-08-05 至 08-07 |
| 异常屏障叫 `java_try`（M6） | 改名为 `catch_fault` | 2026-07-29 |
| M5 只是计划；M6 等待生产切流 | M5 于 2026-07-12 上线；M6 于 2026-07-15 切流、2026-07-16 退役 Python | 2026-07-12；2026-07-16 |

## 早期决定

[早期设计决定（M0–M7）](design.md)按当时写下的样子，保留了自举之前每个选择背后的理由。
