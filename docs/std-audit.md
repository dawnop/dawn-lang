# std 审计:交付方式调研、优雅性判据、现状体检与 S5 开题

> 状态:**S5 已开工并完成大半;本文降为判据与欠账台账**。写于 2026-07-30(S4 进行中),
> 那句「动手等 S4 落地后排期」的等待条件**当日就到期了**(native fixpoint B==C)。
> §4 骨架五条的今天:**4.1 分层已做**(`bf87ef4` fspath 降成 `packages/fspath`;
> `b346e7b` 用 `internal_std_modules` 拦住 hamt/pvec)、**4.2 迭代协议已 trait 化**
> (`5d45b1e` + `05ff60c`,`Iter` 成第五个 prelude trait,按名解析的 `iter_sig` 退休)、
> **4.5 缝 3 已做**(`b72eabd`)、**4.4 做了一半**(`912a984` 的 `dawn doc --stdlib` 已出,
> std 的 go-to-def 未修——根因仍是 `lspq.dawn` 的 `module_ast_by_class` 交回
> `def_path=None`)、**4.3 io 表面设计整条未动**,而它现在挡着 LSP-04
> ([audit/lsp-robustness-design.md](audit/lsp-robustness-design.md) 要的
> `io_stdin_ready` 正是这条该产出的东西)。
>
> **另有一批 std API 补件已于 2026-07-31–08-02 落地,走的是 re-audit 的 RD 通道
> (§六 triage 的 C 批并入 #78),不是本文 §4 的条目**:spec §4.8 的断言/问询/钳位三判据
> (`fd5e0bf`)、str 词缀族(`575076b`)、list 量词层(`4f74cba`)、bytes hex + base64
> (`4f7f4d3`)、cursor↔Int 桥(`677762b`)、fspath 四函数(`604c879`),另新增 `std/fmt`
> (`b6cb9808`)。**仍在册的欠账**:§4.3 整条、§4.4 的 go-to-def、§4.5 记的「`--std` 目录
> 优先」skew 口子,以及等破坏窗口的 RD-06 命名族与 RD-09 参数序。
> §5 的两条纪律仍生效;§6「为什么现在不动手」整节已成历史。
>
> 起因是缝 3(「native 编译器怎么拿到 std」,native-backend-plan §14.10)的调研,
> 调研出的判据回头照了一遍自己的 std,照出的东西够格开一个 S5。

## 1. 调研:其他语言的编译器怎么拿到 std

业界只有三种模式,而且三种模式各自隐含一个「std 是什么」的回答。

### 模式 A:预编译产物随工具链发行,相对可执行文件定位

- **Rust**:std 以预编译 `.rlib`(目标代码 + 序列化 crate metadata)放在 *sysroot*
  (`lib/rustlib/<target>/lib/`)。rustc 找 sysroot 的办法是**从自己的可执行文件 /
  rustc_driver 动态库位置向上推**,`--sysroot` 覆盖。源码只在 `rust-src` 组件里,
  供 IDE 与 `-Zbuild-std` 用。
- **Kotlin/Native**:stdlib 是一个 **klib**(序列化 Kotlin IR + 元数据,非机器码),
  钉死在发行版目录 `$konanHome/klib/common/stdlib`。`~/.konan`(`KONAN_DATA_DIR`)
  只是下载依赖(LLVM、平台库)的仓库,stdlib 本体始终随编译器安装目录走。
- 同族:Swift(.swiftmodule)、OCaml(.cmi/.cma,configure 烤路径 + `OCAMLLIB`)、
  GHC($topdir 相对可执行文件)。

### 模式 B:源码随工具链发行,按需编译 + 缓存

- **Zig**:std 纯源码在 `lib/std/`,编译器**从自身路径向上搜**
  `lib/`、`lib/zig/`、`../lib/`……找到为止——解包即用,也兼容
  `/usr/bin/zig` + `/usr/lib/zig` 的系统安装;`--zig-lib-dir` 覆盖。
  每次构建从源码编 std,靠 lazy analysis(只分析可达声明)+ 缓存压成本。
- **Go(≥1.20)**:从模式 A 迁来——发行版**不再带**预编译 `$GOROOT/pkg` 归档,
  std 按需从 `$GOROOT/src` 编进 build cache,发行版 ~140MiB → ~60MiB。
  GOROOT 同样相对可执行文件发现。
- 同族:Nim、Crystal、V。

### 模式 C:源码/IR 嵌进编译器本体,单文件发行

- **Node.js**:内置 JS 模块经 `js2c` 生成 C 数组编进二进制。Deno 用 V8 snapshot,
  Janet/Chez 用 boot image。
- **Dawn 今天就是这个**:std 源码作为 jar 资源、`ClassLoader.getSystemResourceAsStream`
  读出(`stdlib.dawn`)——jar 就是「嵌入」的 JVM 拼法。

### 三个跨语言共识

1. **主路径一律相对编译器自身**(或在体内),环境变量/flag 只作覆盖,没人拿绝对
   路径或环境变量当主路径。
2. **人人都留开发逃生阀**:`--sysroot`、`--zig-lib-dir`、`GOROOT`、`-Xkonan-data-dir`。
3. **std 版本与编译器版本铆死**是三家共同的不变量,只是实现手段不同。谁都不允许
   「随便捡一个 std 配任意编译器」。

来源:rustc filesearch 模块文档、kotlinlang.org native-libraries、
kotlin-native Distribution.kt、ziglang/zig #463、Go 1.20 release notes。

## 2. 判据:按优雅性标准,三种模式各自在说什么

- **模式 A 说「std 是一个编译单元」**。代价是引入语言的第二份表示(rlib metadata /
  klib IR 是把类型系统再定义一遍的影子规范)。按本仓「一件事只许有一份定义」的教义
  (native-backend-plan §11.3),这是三者中最不优雅的——除非需要分离编译,而 Dawn
  是全程序编译,不需要。
- **模式 B 说「std 是一组普通源文件」**。真实的优雅:编译器是可见输入的纯函数,
  std 可读可改可单步。但对 Dawn 它含一个谎:**std 在 Dawn 里不是普通源文件**——
  `for` 的 lowering 展开成 std/list 的游标协议、`==` 降成对着 std 合成的 Core 函数、
  derive 的落点、四个 prelude trait,编译器按名字引用 std 内部。允许 std 被独立编辑,
  等于允许「commit X 的编译器」不再指称唯一的函数,而 fixpoint B==C、N vs N−1 oracle、
  种子纪律全建立在这个指称唯一性上。
- **模式 C 说「std 是编译器用 Dawn 写的那一部分」**。这是真话,且本仓已两次做出
  同构裁决:Unicode 表从「问宿主」收进编译器、两后端各领一份(§14.16/14.17);
  相等的七份定义收成 lowering 合成的一份。语义上不可分的东西做成可分离的产物是撒谎,
  嵌入是身份的诚实形式。

**缝 3 的方向裁决(待实现)**:留在模式 C,把它做成后端中立——构建期一步生成器把
`std/*.dawn` 变成普通 Dawn 模块(字符串常量表),`stdlib.dawn` 改读它。两个后端同一条路,
native 免费,`stdlib.dawn` 最后一个 `use java` 归零,缝 3 变成「结构上不存在」。
生成物是构建产物不入库,确定性生成(排序)保 B==C;N−1 种子编译它无压力(就是普通源)。
注意:JVM 常量池单字符串 64KB UTF-8 上限、MSVC 字符串字面量限制→生成器按需分块拼接。

选 C 之后,优雅性开出三张账单,作验收标准:

1. **嵌入的边界必须是语义边界**:编译器发出对它的引用、或 spec 点它名的模块,
   才配嵌入;其余都该是普通包(json/web 的驱逐先例)。
2. **只许有一条摄入管线**:嵌入的 blob 喂进和用户文件同一个 lexer/parser/checker,
   特殊性只允许存在于「字节从哪来」一层。
3. **override 是影子不是第二机制**:`--std-dir`(或 `DAWN_STD_DIR`)的语义 =
   「替换本应嵌入的那份」,是调试透镜。

元评论:各语言的优雅解不同是因为约束不同(Rust 的分离编译逼出 metadata、Go 1.20
编译器快到重编 std 不心疼、Zig 有 lazy analysis)。Dawn 的约束——全程序编译、
一份定义教义、两后端逐字节对拍、种子即单产物——之下,C 是唯一不含谎言的解。

## 3. 现状体检(2026-07-30,实测过的)

### 3.1 地基是好的

- **窄腰是真窄**:集合层对后端的全部要求 = `Array` 五操作 + `popcount`(S3);
  HAMT/pvec 纯 Dawn,「every backend gets it for free」。
- **键合法性走 `[K: Eq+Hash]` bound**:哪个相等关系决定「同一个键」由键类型声明。
- **str 原语边界 18→7**、Unicode 表收进编译器、json/web 已逐出成版本化包。

### 3.2 四处不合理(按 §2 的判据)

1. **std 是平的,没有分层**。语言强制件(list/map/set/str/bytes/io——lowering 落点
   与效应边界)、表示基底(hamt/pvec)、编译器自用便利品(fspath)平铺同权、全量随行。
   fspath 按判据不该在 std:它只是 main/pkgfetch/analyze 的便利品,没有任何 lowering
   或 spec 引用它。
2. **表示基底泄漏是结构性的**。hamt/pvec 今天只被 map/set/list 引用(实测,编译器
   代码没碰),但作为 std 模块任何用户都能 `use`——`pub` 是模块级的,map 要用 hamt
   就得把 hamt 的 13 个函数向全世界公开。Map 的身份应是其契约(opaque 教义),
   现在它的表示有公开名字。缺一个 std-internal 可见性层级,或至少一条命名约定。
3. ~~**迭代协议是伪装成库内部的语言表面**。`lower.dawn`(iter_sig 处)按**名字**从
   std/list 解析 `iter_start/iter_done/iter_next/iter_get`,而这四个函数**不是 pub**
   ——只有编译器能用的私有协议。两层后果:用户类型无法接入 `for`(没有 trait 可实现);
   四个「私有」函数实际不可改名不可动签名,是语言表面却没有语言表面的待遇。
   这是有意识的推迟(Iter 等 #44 关联类型,S2.4 改判),但按一份定义教义是在册特例。~~
   **已除名(2026-08-02,#44 刀 2)**:`Iter` 成第 5 个 prelude trait,`for..in` 对它
   普通脱糖;四个函数收进 `impl[T] Iter[List[T]]`,按名解析的 iter_sig 退休;用户
   类型实现 Iter 即可接入 `for`。
4. **io 的表面是编译器需求的沉积层**。十个 io 原语由「编译器迁出 `use java`」驱动、
   休眠落地(§14.3/§14.7),每个都对,但总和从未按「用户的 io 库该长什么样」设计过:
   `temp_dir`/`io_run` 这类编译器刚需俱全,行读取/buffered/目录遍历等常规件缺席。
   加上已知发现性缺口(无 API 文档、std go-to-def 坏),用户视角的 std 是毛坯。

### 3.3 成因,以及为什么不丢人

顺序是对的:S0–S3 期间语义一直在动(ADT 相等两后端相反、Float 表合错、trait v1
处处特判)——在流沙上设计通用 stdlib 才是错误。std 跟着编译器需求长是自举语言的常态
(Rust 的 std 也被 rustc 塑形多年)。真正的问题不是长歪,是**它从没排上自己的 S-pass**:
语义有 S0/S1、trait 有 S2、集合有 S3,std 的 API 表面从未被整体审过。

## 4. S5「std 收口」骨架(未排期)

1. ~~**分层落地**:fspath 降级为包;substrate(hamt/pvec)加可见性层级或命名约定;
   分层判据进 spec 或 CONTRIBUTING。~~ **已做(2026-08-01,#109 破坏批)**:fspath 成
   `packages/fspath`(编译器另留一份四函数的 `selfhost/src/pkg/fspath.dawn`,不能依赖包);
   hamt/pvec 由 `checker.internal_std_modules` 拦住 std 之外的 `use`;判据进
   CONTRIBUTING「命名族」。
2. **迭代协议 trait 化**:#44(关联类型)落地后,`for` 从「按名解析 std/list 私有函数」
   改走 Iter trait;用户类型获得接入 `for` 的能力;那四个函数的特例除名。
3. **io 表面设计**:按用户视角补常规件、审名字;与 native 的 io 运行时(fault/panic
   两分)对齐。
4. **发现性**:`dawn doc --std` + 站点 /stdlib 页(已有独立待办);修 std go-to-def
   (根因:module_ast_by_class 对 std 返回 def_path=None)。
5. **缝 3 实现**(可先行,属 S4):§2 的生成模块方案,三张账单作验收。
   **已完成(2026-07-30,b72eabd,见 native-backend-plan §14.21)**:管线唯一与
   override-即-影子两张账单已兑现;「嵌入边界=语义边界」仍归本节的分层刀。
   顺带记档:`--std` 默认 `std` 且目录优先,任意 cwd 下恰好有 `std/` 会被静默
   当作 std 用——skew 口子,S5 一并收。

## 5. 立即生效的两条纪律(不等 S5)

1. **新增 std 内容按 §2 判据进**:进 std 要答「lowering/spec 引用它吗」,答不上就进包。
2. **`iter_start/iter_done/iter_next/iter_get` 从今天起按语言表面对待**:改名、动签名
   视同 Emit-Change 级别的变更,别被「不是 pub」骗了。

## 6. 为什么现在不动手

S4(native 自举)在关键路径上;且 std 的 API 还会被 native 的教训重塑(字符串构建器 /
unique-realloc 拼接、split/chars 的码点索引这些账未清)——现在收口等于收两次。
本文的作用是把判据立住、让欠账停止增长;存量等 S4 落地后按 §4 排期。
