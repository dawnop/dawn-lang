# M8:淘汰 Kotlin,selfhost 成为唯一编译器

> 状态:**阶段一、二已落地**(2026-07-23)。
> 阶段一:release.yml 双发 + 祝圣门禁、`scripts/replay-bootstrap.sh`、bootstrap.md 立法。
> 阶段二:CLI 能力移植完成,run-diff 16 项全绿、playground contract 以 selfhost 全栈 10/10,
> 落地记录与发现的坑见 §2.1。前置调研与实测见 §0;各阶段独立可回退。
> 业界对照(Rust/Go/Zig/OCaml/Nim 的做法与出处)见本文 §6。

## 0. 前置事实(全部实测/点数于 2026-07-23)

**动机**:bootstrap.md 写着「Kotlin 冻结」,但整条包管理线(url+hash、MVS、别名糖、
java-deps 合并)实际是双编译器同做的——只要 Kotlin 还是活种子,selfhost 源码想用新特性
就得 Kotlin 先会,金样对拍也要求两边逐字节一致。**每个特性 2×,这个税只有退役 Kotlin 才停。**

**速度不是阻塞**(同机三次取最优,冷 JVM):

| 目标 | Kotlin `dawn` | selfhost jar |
|---|---|---|
| emit site(99 类) | 0.44s | **0.39s** |
| test site | 0.46s | **0.46s** |
| emit selfhost(446 类,最大目标) | 0.79s | 1.55s |

**体量点数**(Kotlin 侧共 15,570 行,其中需要移植的只有两块):

- **LSP:~650 行**(`lsp/Server.kt` 198 + `Completion.kt` 224 + 余件)。原以为是大头,不是。
- **清单/抓取层:~1,838 行**(`Toml.kt` 498、`Manifest.kt` 391、`PkgFetch.kt` 294、
  `Add.kt` 133、`Maven.kt` 68、`cli/Main.kt` 454)。manifest 解析 selfhost 已有
  (`manifest.dawn`),缺的是 Toml **写侧**(dawn add 用)、网络抓取、哈希、coursier 调用。
- **playground 服务端:零**——它本来就是纯 Dawn,经 `DAWN_BIN` 环境变量调 CLI 编译用户
  代码,`bin/dawn` 换人它就跟着换。
- selfhost CLI 已有 check/emit/build/fmt/run/test/doc;缺 add、`__pkghash`、`--native`
  调用、抓取(现在只读缓存)、LSP。

**质量机制现状**:四层金样、fixpoint(stage2==stage3)、standalone 闭包(selfhost 自打
独立 jar 且能重建自己)、run-diff/fmt-diff、生态语料(backend-dawn 60 测 + site +
playground contract)全部在 CI。**oracle 替代所需的四样,已有三样半**(缺 N vs N−1 对拍)。

## 1. 阶段一:种子推进协议(先立法,后动工)

抄 OCaml 的纪律(fixpoint 逐字节复现才准刷新种子)+ Zig 的形态(种子是可再生的制品):

1. **种子定义**:GitHub Release 附带的 **selfhost standalone jar**(自打、内含 ASM shim
   与 coursier interface,无 Kotlin 运行时依赖)。从下一个 release 起双发:
   `dawn.jar`(Kotlin,过渡期)+ `dawn-selfhost.jar`。
2. **祝圣仪式**(已有,固化成规则):fixpoint + standalone 闭包 + 全金样绿 → 才允许打
   tag 出 release。种子 bump 逐条记录在 `docs/bootstrap.md` 的链条表里。
3. **特性纪律**:`selfhost/src` 只准用**当前种子已支持**的语言特性;想用新特性 → 先在
   selfhost 实现、发 release、bump 种子,下一轮才能自用。(Rust stage0 的规矩。)
4. **链条可重放**:保留从 v0.6.0(Kotlin 种子,信任链根)起的每环 release;写一个
   `scripts/replay-bootstrap.sh` 手册化重放,不必每次 CI 跑,发版前手动过一遍即可。

## 2. 阶段二:补齐 CLI 能力(移植 ~2,300 行,大头三件)

按依赖顺序:

1. **Toml 写侧**(CST 保格式编辑,Kotlin `Toml.kt` 的另一半):`dawn add` 的前置。
   读侧 manifest.dawn 已有。
2. **抓取与哈希**:HTTP 下载(backend-dawn 的 `http.dawn` 已证明可行)、zip/tar 解包
   (tar 逻辑照抄 `PkgFetch.untar`)、sha256(JDK MessageDigest,FFI)、d1 树哈希、
   内容寻址缓存写入、`__pkghash`。**尊重 `https_proxy` 与 `DAWN_MAVEN_MIRROR` 语义不变。**
3. **Maven 解析**:不重写——经 java-deps 引 `io.get-coursier:interface`(纯 Java、
   全 shaded,见 package-design.md 的坑:别用 Scala API 那个),FFI 调用。
   鸡蛋问题的解法:coursier interface **打进 standalone jar**(Kotlin 现在也是 fat jar
   内含它,形态不变)。
4. **小件**:`dawn add`(133 行)、`--native`(找 native-image + 拼命令行,几十行)。
5. **验收**:run-diff 扩到 add/`__pkghash`/build --native(dry-run 比命令行);
   playground contract 以 `DAWN_BIN=selfhost` 跑一遍全绿。

### 2.1 落地记录(2026-07-23)

新模块五个:`toml.dawn`(CST 保格式编辑)、`pkgfetch.dawn`(下载/解包/d1/缓存)、
`maven.dawn`(coursier interface FFI + 依赖图 java-deps 并集)、`add.dawn`、
`errio.dawn`(stderr,静态字段经 `findStaticGetter` 方法句柄绕行);改四个:
`manifest.dawn` 补 `[java-deps]` 读侧、`analyze.dawn` 缓存 miss 改真抓取、
`jarw.dawn` 补 manifest Class-Path(72 字节折行)、`main.dawn` 接线
(add/`__pkghash`/`--native`/lib vendoring/依赖解析)。

**验收全绿**:run-diff 16 项(add 三形态 + 错误路径、`__pkghash` 正误两路、
冷缓存自主抓取,连编辑后的 dawn.toml 都逐字节比);playground contract 以
`DAWN_BIN=selfhost` 全栈 10/10(服务器本身也由 selfhost 编译运行);
`--native` 带 gson 依赖出可跑二进制(13.7s);tar.gz 与 zip 同树同 d1;
standalone 闭包含 coursierapi vendor(4.9MB),独立解析 Maven 依赖。

**设计取舍与发现的坑**:

- **checker 可见性走 re-exec**:Kotlin 用进程内 URLClassLoader 让 `use java`
  反射看见依赖,selfhost 的 jreflect 只读系统类加载器 → 解析后把 jar 追加
  classpath 重新 exec 自己一次(`DAWN_SELFHOST_CP` 环境变量防循环、给 build
  传 jar 清单)。有 java-deps 的目标多付一次 JVM 启动,可接受。
- **枚举常量是静态字段**,互操作只有方法 → `valueOf("NORMAL")`/`valueOf("ATOMIC_MOVE")`。
- **`java_try` 不接 `NoClassDefFoundError`**(Error 非 Exception)——coursierapi
  缺席时直接崩,所以 standalone jar 必须 vendor 它(已进祝圣命令)。
- **`--std` 默认值是仓库相对路径**,selfhost 只能在仓库根跑 → 阶段三切
  `bin/dawn` 时包装脚本须注入绝对 `--std`(contract 的 wrapper 已验证此路),
  或把 std 嵌进 jar 资源(更彻底,列为阶段三工项)。
- **错误路径的人类渲染仍在 Kotlin**:add/manifest 校验失败的 span 渲染
  selfhost 不做(与编译错误 panic 的既有缺口同类),成功路径与消息型错误
  逐字节对齐。校验权威移交与诊断渲染合并为一个工项,挂阶段四前。

## 3. 阶段三:切换日常驱动

1. `bin/dawn` 默认执行 selfhost standalone jar(`-Xss512m` 写死在包装脚本);
   `DAWN_KOTLIN=1` 逃生阀退回 Kotlin jar。
2. CI 全部 job 改由 selfhost 驱动;Kotlin 仍跑金样对拍(oracle 余热),期间新特性双做
   或冻结——**并行期 ≥ 2 个 release**。
3. **新增 N vs N−1 差分 job**(crater 的微缩版,退役后的主 oracle):上一 release 的
   selfhost jar 与 HEAD 编同一语料(corpus 288 文件 + site + playground + backend-dawn),
   产物逐字节 diff;有意变更必须在提交里声明,未声明的差异 = 红灯。
4. 可选顺手项:checker/codegen 深递归改迭代,摘掉 `-Xss512m`(独立小项,不挡路)。

## 4. 阶段四:LSP 移植(~650 行)

- 协议 = JSON-RPC over stdio;`jsonx`/`jsonread` 已有,选手齐备。
- 验收:编辑器实测诊断推送 + 补全;另录一段编辑会话的请求/响应报文,Kotlin vs Dawn
  对拍作金样。
- playground `/check` 是独立端点不走 LSP,不受影响。

## 5. 阶段五:归档 Kotlin

1. 触发条件:selfhost 驱动的 CI 全绿 ≥ 2 个 release,N vs N−1 job 稳定。
2. 打 `kotlin-final` tag(含最后的 bug 修),主干删除 `compiler/` Kotlin 源与 gradle;
   release jar(v0.6.0 起)永久保留。**这就是我们的 mrustc**:独立实现 + 可重放链条,
   信任链保底,不必像 Rust 那样等社区十年后重造一个。
3. 金样脚本改造:`*-diff.sh` 的参照从「Kotlin vs selfhost」改为「HEAD vs 上一 release」;
   check dumps 等入库为静态金样。
4. README / CLAUDE.md / bootstrap.md / 本文档全面改写,常用命令更新。

## 6. 业界对照(调研于 2026-07-22,出处见链接)

| 语言 | 旧实现下场 | 种子形态 |
|---|---|---|
| Rust | OCaml 版 2011 删除;十年后社区以 [mrustc](https://github.com/gentoo/gentoo/pull/40095) 补回独立实现做纯源码引导(能建 rustc 1.74 再逐版爬) | 上一 beta 二进制(stage0) |
| Go | C 版 1.5(2015)机翻成 Go 后删除;Go 1.21 起工具链[完全可复现构建] | 指定旧版工具链,1.20 起每年推进下限 |
| Zig | [C++ 版 2022 整个删除](https://ziglang.org/news/goodbye-cpp/) | 仓库内 `zig1.wasm` blob + 自写 4,000 行 [wasm2c](https://github.com/jacobly0/zig-wasm2c),语言变化时用上代 zig 再生 |
| OCaml | 一直自举 | 仓库内 `boot/` 字节码 blob;`make bootstrap` 逐字节复现才准刷新 |
| Nim | — | 生成的 C 源码快照(csources),偶尔祝圣新版 |
| TypeScript | **反例**:2025 年为 10× 性能把自举 TS 编译器移植到 Go——自举是手段不是目的 | — |

共性:**没有一家在自举成功后继续维护旧实现**;oracle 的替代 = 三阶段字节比对(GCC/OCaml,
即我们的 fixpoint)+ 金样 + 生态差分(Rust crater,即我们的 backend-dawn/site/contract)+
N vs N−1。

## 7. 风险清单与回退

| 风险 | 处置 |
|---|---|
| 编译速度 | **已证伪**(§0 实测平价) |
| playground / LSP 体量 | **已证伪**(白迁 / ~650 行) |
| coursier FFI 边角(代理、镜像) | §2 明确语义不变,run-diff 验收 |
| oracle 降级 | N vs N−1 + 静态金样 + 生态差分三层补(§3.3、§5.3) |
| `-Xss512m` 永久化 | 包装脚本固化,不优雅但无害;§3.4 可选摘除 |
| trusting-trust | 根 = v0.6.0,链条每环 release 可重放;Kotlin 历史即自带 mrustc(§5.2) |
| 任一阶段翻车 | 阶段独立回退;阶段三有 `DAWN_KOTLIN` 逃生阀;阶段五之前 Kotlin 一直在 |

**工作量估计**(按既往节奏):阶段一 ~1 天、阶段二 ~3–5 天、阶段三 ~1–2 天 + 并行观察期、
阶段四 ~2–3 天、阶段五 ~1 天,合计 **8–12 个工作日**,可穿插进行。
