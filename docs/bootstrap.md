# Bootstrap 链：从种子到自举闭包

> 2026-07-22 自举完成（design.md M7、selfhost-gaps.md §七）；2026-07-23 **M8
> 收口：Kotlin 实现归档在 `kotlin-final` tag，main 上只剩 selfhost**
> （[m8-selfhost-only.md](m8-selfhost-only.md)）。本文回答一个问题：
> **手上只有源码和一个种子 jar 时，如何从零得到一个能编译自己的 Dawn 编译器**，
> 以及每一步靠什么验收。

## 种子（seed）

**现行形态（M8 后）**：种子 = `scripts/seed-release.txt` 钉住的上一 release 的
`dawn-selfhost.jar`。`bin/dawn` 首次运行自动下载到 `.dawn/seeds/` 并用它编译
HEAD 工具链（`DAWN_SEED=<jar>` 指本地 jar 逃生）。种子 jar 自带一切：编译器类、
`--embed-std` 嵌入的 std 源、vendored 的 `dawn.tool` shim / ASM / coursier
interface——这三样二进制自 `kotlin-final` 起像 OCaml 的 `boot/` 一样**随种子
逐代续传**（vendor 从当前运行 jar 的类路径拷出），不再有对应的在库源码
（`dawn.tool` 的 Kotlin 源在 `kotlin-final` tag 里）。

**信任链根**：学 Go 保留 go1.4，Kotlin 版编译器 v0.6.0 冻结为 bootstrap 根。
v0.6.0–v0.8.0 的 release jar 永久保存；`kotlin-final` tag 保有 Kotlin 全源，
从它 `./gradlew :compiler:fatJar` 可现编根种子。硬义务不变：
**种子必须始终能编译 selfhost/**（现由 CI 机器强制）。

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
- **日常驱动已是 selfhost**（2026-07-23，M8 阶段三）：`bin/dawn` 默认跑
  selfhost 独立 jar（源码变更自动重建，`DAWN_KOTLIN=1` 逃生阀回 Kotlin）；
  人类诊断渲染与 dawn.toml 校验权威已移交（`diag.dawn`/`manifestv.dawn`，
  错误路径逐字节对拍）；std 嵌进独立 jar（`--embed-std`），出仓库可用；
  金样脚本的 oracle 侧固定为 `bin/dawn-kotlin`；新增 N vs N−1 差分
  （`scripts/selfhost-prev-diff.sh`，上一 release 与 HEAD 编同一语料 +
  backend-dawn 前端扫描，未声明差异红灯，同时机器强制种子特性纪律）。

## 种子推进协议（2026-07-23 立法，M8 阶段一）

1. **种子形态**：v0.8.0 双发 `dawn.jar`（最后一个 Kotlin jar）与
   **`dawn-selfhost.jar`**（首个 selfhost 种子）；自 v0.9.0 起只发
   `dawn-selfhost.jar`。v0.6.0 起的历史 release 永久保留，构成可重放的信任链。
2. **祝圣仪式（机器强制）**：`release.yml` 在 tag 上重建整条链
   种子→A→B→C（B = HEAD 编 HEAD，即要上传的那份字节），验证 `cmp B C` 闭包
   与版本一致——任一红则 release 不出。push CI（ci.yml）的全金样绿是前置。
   种子 bump 逐条记进下面的链条表。
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
V="--std std --embed-std std --vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi"
java -Xss512m -jar seed.jar build selfhost -o a.jar $V
java -Xss512m -jar a.jar    build selfhost -o b.jar $V
java -Xss512m -jar b.jar    build selfhost -o c.jar $V
cmp b.jar c.jar
```

`scripts/selfhost-fixpoint.sh` 固化此链，**在 CI**（ci.yml），每次 push 重验；
`scripts/replay-bootstrap.sh <seed|vX.Y.Z>` 从任一环重放（发版前手动过）。

## 为什么字节级一致做得到

codegen 是确定性的：同一份源经同一实现必出同字节；frame 计算走 vendored 的
`dawn.tool.AdtClassWriter`（COMPUTE_FRAMES 的公共超类解析），随种子逐代续传、
从不重编。历史上的跨实现验收（Kotlin vs selfhost 的 `__lex/__parse/__check/
__emit` 全仓逐字节对拍）已随 `kotlin-final` 完成使命；现行 oracle 是
**N vs N−1**（`selfhost-prev-diff.sh`：上一 release 与 HEAD 编同一语料 +
backend-dawn 生态扫描，未声明的字节差异红灯）加 CLI/格式化/LSP 三条转写差分
（`selfhost-run-diff.sh` / `selfhost-fmt-diff.sh` / `selfhost-lsp-diff.sh`）。
故意改变输出的提交在信息里声明 `Emit-Change: <说明>`。

## 运行注意

- 跑 selfhost 要 `-Xss512m`：comptime 解释器递归吃宿主栈。
- `selfhost build` 产物的确定性由 `jarw.dawn` 保证（manifest 在先、条目
  时间戳钉死、同类表必出同字节）——闭包验收能 `cmp` 整 jar 靠这个。
- ZipEntry 的 DOS 时间经本地时区换算：确定性按机器成立（同机重建必同字节），
  跨时区机器构建的 jar 之间不保证逐字节相同。
