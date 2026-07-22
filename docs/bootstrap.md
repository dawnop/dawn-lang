# Bootstrap 链：从种子到自举闭包

> 2026-07-22 自举完成（design.md M7、selfhost-gaps.md §七）。本文回答一个问题：
> **手上只有源码和一个种子 jar 时，如何从零得到一个能编译自己的 Dawn 编译器**，
> 以及每一步靠什么验收。
>
> 后续：**M8 计划淘汰 Kotlin**（[m8-selfhost-only.md](m8-selfhost-only.md)），
> 种子推进协议见下文——它是 M8 阶段一，2026-07-23 立法生效。

## 种子（seed）

学 Go 保留 go1.4：**Kotlin 版编译器自 v0.6.0 冻结为 bootstrap 种子**。
种子 jar 由 GitHub Release 永久保存（`release.yml` 对每个 `v*` tag 出
`dawn.jar`），任何一个 ≥ v0.6.0 的 release jar 都可以当种子——冻结的硬义务
只有一条：**种子必须始终能编译 selfhost/**。

冻结的含义（也记录在 design.md M7 验收结论）：

- bug 修照收，种子失去「能编译 selfhost」的能力算 P0；
- 新语言特性默认不再进 Kotlin 版——要做就得 selfhost 同步实现，双份成本是
  刻意的刹车；
- 日常工具链已基本迁齐（2026-07-22 补）：`selfhost fmt`（词法级格式化器移植，
  全仓 298 文件 + 打乱副本与 `dawn fmt` 逐字节一致）、`selfhost run`（子进程跑
  新发射的类）、`selfhost test`（合成 `dawn$TestMain` runner 类，PASS/FAIL 报告
  与退出码同 `dawn test` 逐字节）、`selfhost doc`（pub API 与 builtin 参考的
  JSON 逐字节）——金样 `scripts/selfhost-fmt-diff.sh`、`selfhost-run-diff.sh`
  均在 CI；
- CLI 能力层已迁齐（2026-07-23，M8 阶段二）：`selfhost add`/`__pkghash`/
  `build --native`/url 依赖抓取（冷缓存自主下载验证）/Maven 解析（coursier
  interface，FFI）。仍留在 Kotlin 侧的只有 **LSP**（M8 阶段四）。

## 种子推进协议（2026-07-23 立法，M8 阶段一）

1. **种子的下一形态**：自下一个 release 起，`release.yml` 双发
   `dawn.jar`（Kotlin，过渡期）与 **`dawn-selfhost.jar`**（selfhost 自打的独立 jar，
   vendor 了 `dawn.tool` shim 与 ASM，无 Kotlin 运行时依赖）。M8 完成后
   `dawn-selfhost.jar` 是唯一种子，Kotlin jar 停止发布；v0.6.0 起的历史 release
   永久保留，构成可重放的信任链。
2. **祝圣仪式（机器强制）**：`release.yml` 在 tag 上重跑 fixpoint + standalone
   闭包，且闭包验证跑在**将要上传的那份字节**上——任一红则 release 不出。
   push CI（ci.yml）的全金样绿是前置。种子 bump 逐条记进下面的链条表。
3. **特性纪律**：`selfhost/src` 只准用**当前种子已支持**的语言特性。想用新特性：
   先在 selfhost 实现 → 发 release（过祝圣）→ bump 种子 → 下一轮才能自用。
   （Rust stage0 的规矩。过渡期由「Kotlin 同步实现」的旧规则兜着；M8 阶段三
   CI 改由种子 jar 驱动后，这条变成机器强制。）
4. **链条可重放**：`scripts/replay-bootstrap.sh <seed-jar | vX.Y.Z>` 从任一环
   种子重放：种子编 selfhost → 固定点（stage2==stage3）→ standalone 闭包 →
   （本地有 HEAD 编译器时）验证收敛到与 HEAD 逐字节一致。**一代洗净种子**：
   stage2 只由 selfhost/src 决定、与谁编译 boot 无关，所以「老种子 + 新源码」
   也必须对出与 HEAD 相同的字节。发版前手动过一遍，不进 CI。

### 链条表

| release | 种子形态 | 备注 |
|---|---|---|
| v0.6.0 | `dawn.jar`（Kotlin） | **信任链根**；Kotlin 冻结为 bootstrap 种子 |
| v0.7.0 | `dawn.jar`（Kotlin） | 包管理线收官版 |
| （下一个） | `dawn.jar` + `dawn-selfhost.jar` 双发 | 首个 selfhost 种子候选 |

## 链

```bash
# 0) 种子：GitHub Release 的 dawn.jar（bin/dawn 即其包装），或本地
./gradlew :compiler:fatJar          # 从 Kotlin 源现编种子

# 1) 种子编译 selfhost（Dawn 写的编译器，selfhost/src/*.dawn）
./bin/dawn build selfhost -o selfhost.jar

# 2) selfhost 发射自己 → 与种子发射的逐字节一致（stage2 == stage1）
#    再用自己发射的类重跑发射 → 仍逐字节一致（stage3 == stage2，固定点）
./scripts/selfhost-fixpoint.sh

# 3) selfhost 自打独立 jar：把 dawn.tool 的 frame-writer shim 和 ASM
#    按包前缀 vendor 进产物，从此不再需要任何 Kotlin 产物在 class path 上
java -Xss512m -cp selfhost.jar:compiler/build/libs/dawn.jar main \
  build selfhost -o dawn-selfhost.jar --vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi

# 4) 闭包：独立 jar 单独重建自身，两个 jar 逐字节相同
java -Xss512m -jar dawn-selfhost.jar build selfhost -o rebuilt.jar \
  --vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi
cmp dawn-selfhost.jar rebuilt.jar
```

步骤 2 与 3+4 分别由 `scripts/selfhost-fixpoint.sh` 与
`scripts/selfhost-standalone.sh` 固化，**都在 CI**（ci.yml），每次 push 重验。

## 为什么字节级一致做得到

两个编译器共享同一个 frame 写入器 `dawn.tool.AdtClassWriter`
（COMPUTE_FRAMES 的公共超类解析两边必须同一实现），selfhost 侧其余全部
用 Dawn 重写（词法/语法/检查/comptime 解释器/codegen，账在
`selfhost-codegen.md`、`selfhost-checker.md`）。金样对拍
（`dawn __lex/__parse/__check/__emit` vs `selfhost lex/parse/check/emit`）
覆盖全仓 .dawn 文件 + site + playground。

## 运行注意

- 跑 selfhost 要 `-Xss512m`：comptime 解释器递归吃宿主栈。
- `selfhost build` 产物的确定性由 `jarw.dawn` 保证（manifest 在先、条目
  时间戳钉死、同类表必出同字节）——闭包验收能 `cmp` 整 jar 靠这个。
- ZipEntry 的 DOS 时间经本地时区换算：确定性按机器成立（同机重建必同字节），
  跨时区机器构建的 jar 之间不保证逐字节相同。
