# dawnc 的优化级别开关（`-O0` / `-O1` / `-O2`）

> 状态：**current**。设计先行，实现见 §八。
> 依据：`agent-handoff/ruling-runner-b-path-20261019.md` 第 2、3、5 条（B 路的硬伤是 flash_attn 在 `-O2` 下 cc 25–35 s，超沙箱 15 s；
> 重开条件之一是「dawnc 有优化级别开关且 flash_attn 在沙箱内 `-O0/-O1` 低于 10 s」；派生一刀即本稿）；
> `agent-handoff/research-runner-b-path-20261019.md` §3.2（flash_attn 的 cc 实测，`CC` 包一层追加 `-O0` 约 6.2 s、输出与 -O2 逐字节相同）。

## 一、结论

1. **CLI 形态：`dawnc build|run|test` 接受 `-O0`、`-O1`、`-O2` 三个单词形式的开关**，与 cc、ghc 的拼法相同。
   同一命令里出现多次时最后一个生效（cc、ghc 都是这样）。其它以 `-O` 开头的词（`-O3`、`-Os`、`-Ofast`、裸 `-O`）
   一律报英文错误、退出 2：`unknown optimization level `-O3`; this backend knows: -O0, -O1, -O2`。不透传任意 cc 参数。
2. **默认值不变，三个子命令都是 `-O2`。** 没写开关的调用，cc 命令行与今天逐字节相同，所以发射的 C、二进制、
   native-fixpoint、所有门禁的输入都不动。
3. **不进 `dawn.toml`。** 级别是一次调用的选择（Playground 要快编，发布要快跑），不是包的属性。
4. **级别作用于这次构建的每一条 cc 命令**：native 那一条；wasm 的三条（C++ 垫片、异常 tag、主编译链接）。
   `-DDAWN_RT_INLINE_RC` 与级别正交，互不牵连。
5. **dawnc 没有构建缓存，所以没有缓存键要改。** 将来 runner 的编译缓存（裁决 4）若对同一源码用不同级别，
   键里必须带级别；这条写进 runner 设计时再落。

## 二、为什么要有它

native 后端把 Core IR 降成 C，再调 cc。cc 的级别今天写死在 `selfhost/src/nmain.dawn` 的 `cc_build_with` 里（`-O2`），
用户只能用 `CC` 包一层脚本在命令行末尾追加 `-O0` 来改（调研 §3.2 就是这么测的）。

调研的本地实测（dawnc 0.94.0，gcc 13.3，Ryzen 7 9700X，有别的负载）：

| 配置 | flash_attn `dawnc build` 墙钟 | hello |
|---|---|---|
| `dawnc emitc`（无 cc，C 文本 6,038,090 字节） | 2.4–3.1 s | 0.43–0.49 s |
| 默认 -O2 + 内联 RC | 24.9 / 27.2 / 35.4 s | 1.57–2.42 s |
| `CC` 追加 `-O1` | 14.4 s | 1.03 s |
| `CC` 追加 `-O0` | 6.2 s | 0.74–0.79 s |

`-O0` 的产物运行输出与 -O2 逐字节相同。所以 cc 的时间几乎全花在优化上，6 MB 的 C 在 -O0 下只是解析与直译。
本稿的实测（§七）用正式开关重测一遍，并补运行时间。

## 三、CLI 形态（参照）

| 工具 | 拼法 | 默认 | 出处 |
|---|---|---|---|
| cargo | `--release` 或 `--profile <name>`；级别写在 `[profile.*] opt-level = 0..3/"s"/"z"` | `build`/`run`/`test` 用 dev（opt-level 0），`--release` 用 3 | https://doc.rust-lang.org/cargo/reference/profiles.html |
| rustc | `-C opt-level=N`，`-O` 等于 `-C opt-level=2` | 0 | https://doc.rust-lang.org/rustc/codegen-options/index.html#opt-level |
| go | 没有级别；`go build -gcflags='-N -l'` 关优化与内联（调试用） | 优化开 | https://pkg.go.dev/cmd/compile |
| zig | `-O Debug\|ReleaseSafe\|ReleaseFast\|ReleaseSmall`；`zig build -Doptimize=...` | Debug | https://ziglang.org/documentation/master/#Build-Mode |
| swiftc | `-Onone`、`-O`、`-Osize`（另有 `-Ounchecked`）；SwiftPM 用 `-c debug\|release` | swiftc 为 `-Onone`；SwiftPM 默认 debug | https://www.swift.org/documentation/server/guides/building.html |
| ghc | `-O0`、`-O`（即 `-O1`）、`-O2` | `-O0`（cabal 默认 `optimization: True` 即 -O1） | https://downloads.haskell.org/ghc/latest/docs/users_guide/using-optimisation.html |
| Rust Playground | 页面上选 Debug / Release | Debug | https://github.com/rust-lang/rust-playground |

取舍：

- **数字级别，不用 debug/release 这类名字。** cargo、zig、SwiftPM 的「模式」除了优化还捆着别的语义（debug 断言、溢出检查、
  安全检查）。Dawn 的级别只改 cc 的优化，语言语义在三个级别下相同（整数一律 `-fwrapv` 回绕，panic 文案不变），
  起一个「debug」的名字会暗示有别的差别。ghc 与 swiftc 也是用 `-O` 系列直说优化。
- **单词形式（`-O0`），不用 `--opt 0`。** 它就是 cc 的级别，用 cc 的拼法读者不用换算；也与 `-o` 不冲突（大小写不同）。
- **只开 0、1、2。** -O3 在 cc 上不保证更快、cc 时间更长，没有实测支撑之前不开；`-Os`、`-Og` 同理。将来要加，
  就是在白名单里加一个词，CLI 形态不用变。
- **不透传任意 cc 参数**（不做 `--ccflags`）。dawnc 拼的 cc 命令行是这个后端 codegen 的一部分（`cc_build_with` 的注释与测试逐个钉住每个 flag），
  任意透传会让「同一份 C 编出什么」失去定义。真要试别的 flag，`CC` 包装脚本仍然可用，那是用户自己负责的口子。

## 四、默认值：三个子命令都是 `-O2`

| 子命令 | 默认 | 理由 |
|---|---|---|
| `dawnc build` | `-O2` | 产物是给人跑的；今天就是 -O2，改默认等于静默改变所有现有用户产物的速度 |
| `dawnc run` | `-O2` | 它是「build 然后执行」，用户读到的运行时间应当与 build 的产物一致；Go 的 `go run` 也不降优化 |
| `dawnc test` | `-O2` | #239/#275 已裁「测试档与发布档同 flag」（[c-tu-split-design.md](c-tu-split-design.md) §九）；native-selfhost-tests 走 `dawnc test`，默认一动，CI 测的就不是发布的配置 |

cargo、zig、ghc 选了「默认快编」，代价是每个新人都要学 `--release`，基准测试里常见忘写 `--release` 的误报。
Dawn 的 native 后端从第一天就是 -O2，没有理由现在翻转；需要快编的调用方（Playground 的 B 路、本地迭代）显式写 `-O0`。

## 五、不进 `dawn.toml`

- 级别是调用方的选择：同一个项目，Playground 要 -O0，发布要 -O2。cargo 把 profile 放进清单，但它也规定
  依赖包清单里的 profile 一律忽略、只认根清单，说明这本来就不是包的属性。
- `dawn.toml` 两个工具链都读，JVM 工具链拿到一个 C 优化级别字段只能忽略。
- 没有出现「某个项目必须固定级别」的需求。出现了再加，形态可以照 cargo 的根清单规则。

## 六、与其它路径的关系

| 路径 | 关系 |
|---|---|
| `dawn run`（JVM 驱动） | 无关。JVM 驱动没有 native 目标（`dawn build --native` 是 GraalVM，不经 cc 的级别），也没有 `--target native`；`-O<n>` 是 dawnc 独有的开关，和 `--target`、`--reactor` 一样不在 `scripts/native-cli-diff.sh` 比对的 argv 面上 |
| wasm（`--target wasm`，`DAWN_WASM_CC`） | 级别同样作用于 wasm 的三条 clang 命令。默认 -O2 不变，所以 `site/build.sh`、`scripts/wasm-contract/run.sh` 等调用方不受影响 |
| ASan 变体（`scripts/native-asan-tests.sh`） | 它经 `CC` 包装注入 sanitizer，跑 `dawnc test` 时不写级别，即 -O2，不变。包装脚本若自己追加 `-O<n>`，cc 后者胜，行为与今天相同 |
| 自举（`scripts/native-fixpoint.sh`） | 不受影响。A、B、C 三代都是 `emitc --split` 加 `scripts/cc-units.sh` 构建，不经 `dawnc build` 的 cc 命令行；B==C 比的是发射的 C 文本，级别根本不进 C 文本。`cc-units.sh` 不加级别参数（测试档与发布档同 flag） |
| 内联 RC（`DAWN_NO_INLINE_RC`） | 正交。-O0 下 `static inline` 不会真内联，`-DDAWN_RT_INLINE_RC` 只剩一点解析成本，调研测得 flash_attn -O0 加不加 no-inline 为 6.2 对 6.1 s，不值得为它把两个开关耦合起来 |
| 构建清单（`dawnc version -m`） | 不记级别。清单记的是源码身份；要记构建设置，属于清单格式变更，另立项（见「不做的」） |

## 七、实测

（实现后填。测法：集群单机，同一台机器上串行；每个样例 × 级别 3 次 `dawnc build`，取墙钟；产物各跑 3 次取墙钟；
产物 stdout 与 -O2 的 stdout 逐字节比较。）

## 八、落地记录

（实现后填。）

## 不做的（理由）

- **不改默认值**：见 §四。翻默认会让 CI 测的配置与发布分叉（#239/#275），也静默改变现有用户产物的速度。
- **不开 -O3 / -Os / -Og**：没有实测说明它们在发射的 C 上更好；白名单加词很便宜，等有数据再加。
- **不透传任意 cc 参数**：见 §三。`CC` 包装脚本已经是那个口子。
- **不加环境变量**（如 `DAWN_OPT`）：`DAWN_NO_INLINE_RC` 用环境变量，是因为它要同时穿过多个子命令且只有一个开/关值；
  级别的使用者（Playground runner、本地命令行）都直接拼 argv，开关更可见，也不会意外漏进子进程。
- **不进 `dawn.toml`**：见 §五。
- **不在 `cc-units.sh` 加级别**：它只给 CI 与发布构建编译器，按 #239/#275 两档同 flag。
- **不把级别写进构建清单**：清单格式变更会改 `dawnc version -m` 的输出与清单摘要，是另一刀；Go 的 `go version -m` 记构建设置可作那一刀的参照。
- **不让 -O0 自动关内联 RC**：见 §六，收益在噪声内。
- **本刀不改 Playground runner**：B 路仍按裁决 2 暂不做；本刀只提供开关与实测，供重开条件判断。
