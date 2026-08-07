# Bootstrap 链：从种子到自举闭包

> 状态：**current** —— 自举与种子推进协议的现行说明（M8 收口后仍照做）。
>
> 2026-07-22 自举完成（design.md M7、selfhost-gaps.md §七）；2026-07-23 **M8
> 收口：Kotlin 实现归档在 `kotlin-final` tag，main 上只剩 selfhost**
> （[m8-selfhost-only.md](history/m8-selfhost-only.md)）。本文回答一个问题：
> **手上只有源码和一个种子 jar 时，如何从零得到一个能编译自己的 Dawn 编译器**，
> 以及每一步靠什么验收。

## 种子（seed）

**现行形态（M8 后）**：种子 = `scripts/seed-release.txt` 钉住的上一 release 的
`dawn-selfhost.jar`。`bin/dawn` 首次运行自动下载到 `.dawn/seeds/` 并用它编译
HEAD 工具链（`DAWN_SEED=<jar>` 指本地 jar 逃生）。种子 jar 自带一切：编译器类、
`--embed-std` 嵌入的 std 源、vendored 的 ASM / coursier interface——这两样二进制
像 OCaml 的 `boot/` 一样**随种子逐代续传**（vendor 从当前运行 jar 的类路径拷出），
在库没有对应源码。

> 曾经是三样：`dawn.tool` 的 `AdtClassWriter` shim 也在里面，源码只在 `kotlin-final`
> tag。**2026-08-03（v0.49.0 之后）它退出了**——那五个 null 适配器改由 `rtclasses.dawn`
> 发射成 `dawn/rt/Asm`，`dawn/tool` 从 `--vendor` 和 `vendor_trust` 里删掉
> （docs/jvm-base-plan.md §5.7 K-A7）。它现在是**由上一代编译器发射**的类，而不是
> 无源逐字节抄的二进制——前者是自举常态、DDC 能处理，后者不能。

**信任链根**：学 Go 保留 go1.4，Kotlin 版编译器 v0.6.0 冻结为 bootstrap 根。
v0.6.0–v0.8.0 的 release jar 永久保存；`kotlin-final` tag 保有 Kotlin 全源，
从它 `./gradlew :compiler:fatJar` 可现编根种子。硬义务不变：
**种子必须始终能编译 selfhost/**（现由 CI 机器强制）。

冻结的含义（也记录在 design.md M7 验收结论）：

- bug 修照收，种子失去「能编译 selfhost」的能力算 P0；
- 新语言特性默认不再进 Kotlin 版——要做就得 selfhost 同步实现，双份成本是
  刻意的刹车。

> **迁移过程已经结束。** M8 阶段二/三/四的逐阶段快照（哪些能力还在 Kotlin 侧、
> `DAWN_KOTLIN=1` 逃生阀、`bin/dawn-kotlin` 作为金样 oracle）曾写在这里，读起来
> 像现状——而它们都不是了：Kotlin 实现在 `kotlin-final` tag，`DAWN_KOTLIN` 与
> `bin/dawn-kotlin` 都已删除，LSP 也早已是 selfhost 的。过程记录见
> [m8-selfhost-only.md](history/m8-selfhost-only.md)，本文只留现行链。

**现行的 oracle**：`scripts/selfhost-prev-diff.sh`——上一 release 与 HEAD 编同一
语料 + 生态扫描，未声明的字节差异红灯（声明方式：提交信息里的 `Emit-Change(<label glob>):` 行），
同时机器强制种子特性纪律（N−1 的 jar 必须仍能编 HEAD 的 `selfhost/src`）。
配套还有 `selfhost-run-diff.sh`（CLI 转写）、`selfhost-fmt-diff.sh`（格式化）、
`selfhost-lsp-diff.sh`（LSP 会话）。

## 种子推进协议（2026-07-23 立法，M8 阶段一）

1. **种子形态**：v0.8.0 双发 `dawn.jar`（最后一个 Kotlin jar）与
   **`dawn-selfhost.jar`**（首个 selfhost 种子）；自 v0.9.0 起**种子只有**
   `dawn-selfhost.jar`。v0.6.0 起的历史 release 永久保留，构成可重放的信任链。
   K-B7（`docs/native-driver-plan.md` §22）给 `release.yml` 加了第二件产物
   `dawnc-linux-x86_64`（native 编译器的静态可执行文件）与它的 `.sha256`，
   但那一步落在 `v0.49.0` 的 tag 之后，所以 **v0.46–v0.49 的 release 页面上没有它；
   v0.50.0 是第一个真的挂上它的 release**（四件产物齐全，下载下来的二进制核过
   `.sha256`、报 0.50.0、并在只有一个 `.dawn` 文件的裸目录里编译运行通过）。
   它也**不是种子**：`scripts/seedjar.sh` 只下载、只校验 jar，
   `scripts/seed-checksums.txt` 里也只有 jar 的摘要。
2. **祝圣仪式（机器强制）**：`release.yml` 在 tag 上重建整条链
   种子→A→B→C（B = HEAD 编 HEAD，即要上传的那份字节），验证 `cmp B C` 闭包
   与版本一致——任一红则 release 不出。push CI（ci.yml）的全金样绿是前置。
   下面的链条表记的是**种子形态变过的那几环**，不是每一次 bump——每次 bump 的记录
   就是 `scripts/seed-release.txt` 那一行和它的提交，再抄一遍只会过期（这张表一度
   写着「逐条记」，却停在 v0.8.0，中间二十一个 release 一个没记）。
3. **特性纪律**：`selfhost/src`（连同它引用的 `std/`）只准用**当前种子已支持**
   的语言特性。想用新特性：先在 selfhost 实现 → 发 release（过祝圣）→ bump
   `scripts/seed-release.txt` → 下一轮才能自用。（Rust stage0 的规矩，
   CI 机器强制：种子编不动 HEAD 直接红。）
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
| v0.8.0 | `dawn.jar` + `dawn-selfhost.jar` 双发 | **首个 selfhost 种子**（LSP 移植完成，Kotlin 最后一发）；随后 `kotlin-final` 归档 Kotlin |

## 链

```bash
# 0) 种子：seed-release.txt 钉住的 release 的 dawn-selfhost.jar
#    （bin/dawn 自动下载缓存；信任链根 v0.6.0 的 Kotlin jar 也可作种，
#    或从 kotlin-final tag 现编：git checkout kotlin-final && ./gradlew :compiler:fatJar）

# 1) 种子编 HEAD → A；A 编 HEAD → B（HEAD 编 HEAD，规范产物）；
#    B 编 HEAD → C；cmp B C 逐字节相同 = 固定点 + 闭包一步到位。
#    每一步都是独立 jar（--embed-std 嵌 std 源，--vendor 续传 shim/ASM/coursier）
./scripts/selfhost-fixpoint.sh

# 手工展开（release.yml 的祝圣即此链，B 是上传的那份）：
V="--std std --embed-std std --vendor org/objectweb/asm --vendor coursierapi"
java -Xss512m -jar seed.jar build selfhost -o a.jar $V
java -Xss512m -jar a.jar    build selfhost -o b.jar $V
java -Xss512m -jar b.jar    build selfhost -o c.jar $V
cmp b.jar c.jar
```

`scripts/selfhost-fixpoint.sh` 固化此链，**在 CI**（ci.yml），每次 push 重验；
`scripts/replay-bootstrap.sh <seed|vX.Y.Z>` 从任一环重放（发版前手动过）。

## 为什么字节级一致做得到

codegen 是确定性的：同一份源经同一实现必出同字节。**帧已经不算了**——发射的 class
是版本 49，那以下 JVM 用推断式校验器、不要 `StackMapTable`，写入器是 COMPUTE_MAXS
（docs/jvm-base-plan.md K-A4）。那五个静态 null 适配器（ASM 的 `visit*` 要 null，
Dawn 源码拼不出）现在是编译器自己发射的 `dawn/rt/Asm`；`dawn.tool.AdtClassWriter`
曾经随种子逐代续传、从不重编，K-A7 之后已退出（jvm-base-plan.md §5.7）。同一家的第六个类
`dawn/rt/AsmWriter`（K-A8.1）是 `ClassWriter` 子类，帧计算要问的公共超类型由它回答——**只查
编译当下那张 `supers_of` 表，不走 `Class.forName`**，正是为了不让发射的字节取决于编译器
碰巧跑在哪个 JDK 上（§5.10 的 D4）。
历史上的跨实现验收（Kotlin vs selfhost 的 `__lex/__parse/__check/
__emit` 全仓逐字节对拍）已随 `kotlin-final` 完成使命；现行 oracle 是
**N vs N−1**（`selfhost-prev-diff.sh`：上一 release 与 HEAD 编同一语料 +
backend-dawn 生态扫描，未声明的字节差异红灯）加 CLI/格式化/LSP 三条转写差分
（`selfhost-run-diff.sh` / `selfhost-fmt-diff.sh` / `selfhost-lsp-diff.sh`）。
故意改变输出的提交在信息里声明 `Emit-Change(<label glob>): <说明>`（裸声明=通配，兼容历史）。

## 运行注意

- 跑 selfhost 要 `-Xss512m`：comptime 解释器递归吃宿主栈。
- `selfhost build` 产物的确定性由 `jarw.dawn` 保证（manifest 在先、条目
  时间戳钉死、同类表必出同字节）——闭包验收能 `cmp` 整 jar 靠这个。
- 条目时间戳走 `ZipEntry.setTimeLocal`（钉死 2020-01-01T00:00:00，无时区参与），
  故**跨时区、跨机器**重建同一 jar 得同样的字节。此前用的是 `setTime(epoch millis)`，
  它经默认时区换算成 DOS 时间——确定性只按机器成立，而 release 以字节固定点为核心，
  「只有在我的时区才同字节」撑不起这个说法。
