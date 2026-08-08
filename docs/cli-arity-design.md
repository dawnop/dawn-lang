# CLI 参数基数统一设计（TOOL-04）

> 状态：**current** —— 本文记录 TOOL-04 的定稿契约与落地边界。它只统一子命令的
> positional target 基数和互斥 selector，不改变任何编译器 option 的既有含义，也不处理
> `run` 的编译器参数/程序参数边界；后者属于 TOOL-03。

## 1. 问题

JVM 驱动与 native 驱动各自解析 argv，这是有意保留的双实现：两端共用同一个 parser，
只能证明同一段代码执行了两次，不能证明两个后端的驱动契约一致。但“双实现”不等于
“双契约”。此前存在三类漂移：

- JVM `check` 接受多个 target，native `check` 只接受一个；
- JVM `doc` / `test` 拒绝第二个 target，native 让最后一个静默覆盖前一个；
- native 的基数错误有时打印整份 `dawnc` help，JVM 则打印命令级诊断，退出码虽同属
  usage error，字节并不一致。

旧的 `scripts/native-cli-diff.sh` 只比较两端是否相等，且相关用例最多给一个 positional。
因此“两端同时接受非法输入”与“未覆盖第二个 positional”都能假绿。

## 2. 定稿契约

| 子命令 | target / selector 契约 |
|---|---|
| `check` | 1..N 个 target；一次运行聚合全部 target 的诊断。 |
| `test` | 恰好一个 target，或 `--stdlib`；两者异或。 |
| `doc` | 恰好在“一个 target / `--stdlib` / `--builtins`”中选择一项。 |
| `build` | 恰好一个 target。 |
| `emitc` | 恰好一个 target。JVM 入口仍叫隐藏命令 `__emitc`，native 入口仍叫 `emitc`。 |
| `fmt` | 1..N 个 target。 |

“N”没有人为上限；门禁以两个 target 证明命令不是“恰一”，不把二误写成最大值。
重复的同一个 boolean selector 继续沿用既有幂等 option 语义；本刀拒绝的是不同输入模式
同时被选择，不顺手新增 duplicate-option 政策。

## 3. 错误与退出码

基数在文件存在性、源码加载、后端生成之前判定。缺参、多 target 和互斥 selector 冲突均：

1. stdout 为空；
2. stderr 使用同一条命令级 usage/诊断；
3. JVM 与 native 都退出 2。

第二个 target 的诊断保留首个与第二个词，避免只报“参数太多”却不告诉用户哪两个词被当成
target。`test` / `doc` 的 selector 冲突则报告“只能选择一种输入模式”，不让某个 flag
按实现分支顺序静默取得优先级。

两端各在驱动文件中保留独立 argv plumbing，但每个驱动内部把下面两件事收进 helper：

- 单 target 命令拒绝第二个 positional；
- target 与 selector 的“恰选一种”计数。

不抽一个供两个驱动共同调用的 argv 模块。独立实现加共享可执行 fixture 才能继续发现
backend drift；为了共享而让 native 驱动绕进 JVM 的 process/classpath plumbing，代价大于收益。

## 4. 编译器 option 边界

本刀只在既有 option 提取完成后数剩余 positional：

- `--std`、`--cp`、`--comptime-fuel`、`--comptime-ffi`、`--closure`、`-o`、
  `--native`、`--vendor` 的接受范围与解析顺序保持现状；
- `run` 不调用新增的基数 helper，不改变它今天对 target 后 token 的处理；
- 不把未知 `-x` 自动归成“未知 option”。现有 parser 若把它当 positional，本刀只按该
  positional 所处的基数边界处理。

这条边界避免 TOOL-04 与 TOOL-03 混成一次无法归因的 CLI 重写。

## 5. 可执行契约

`scripts/native-cli-diff.sh` 新增独立 arity leg。每个边界既比较 JVM/native transcript，
又核对绝对 exit status；reject case 还核对完整诊断字节。覆盖矩阵：

| 子命令 | 最小边界 | 合法上边界 | 冲突边界 |
|---|---|---|---|
| `check` | 0 target → 2 | 1、2 target → 0 | 无 selector 冲突 |
| `test` | 0 → 2 | 1 target、`--stdlib` → 0 | 2 targets、target + `--stdlib` → 2 |
| `doc` | 0 → 2 | target、`--stdlib`、`--builtins` → 0 | 2 targets、任意两种 selector → 2 |
| `build` | 0 → 2 | 1 target → 0 | 2 targets → 2 |
| `emitc` | 0 → 2 | 1 target → 0 | 2 targets → 2 |
| `fmt` | 0 → 2 | 1、2 targets → 0 | 无 selector 冲突 |

`build` 的成功产物在两后端本来就不同（JAR 与 native executable），所以合法一-target
边界分别核对 exit 0 与产物存在；不能为了使用 byte diff 假装两种产物应相同。`emitc`
则比较 JVM `__emitc` 与 native `emitc` 的 C 文本。

arity leg 可单独运行，供变异测试快速证明 oracle 真会变红；默认仍属于完整
`native-cli-diff.sh`，不是可跳过的弱门禁。

## 6. Core 与 Emit 纪律

两个驱动的参数分支会改变 `main.core` / `nmain.core`，只在
`selfhost-core-diff.sh` 实测后用 `--record` 重录实际变化。CLI transcript 是否跨 release
变化同样由 `selfhost-prev-diff.sh` / `selfhost-run-diff.sh` 测量；只有真实变化的闭集 label
才写 `Emit-Change(...)`，本文不预声明。

## 7. 负向控制

至少执行两类同侧共谋变异：

1. 临时让 JVM/native 都接受 `doc --stdlib --builtins`。双端 diff 仍相等，但 arity leg
   必须因绝对期望 exit 2 / 固定诊断而失败；
2. 临时让 JVM/native 都恢复“第二个 target 覆盖第一个”的 `build` 或 `test` 行为。
   两端仍可能相等，但对应多-target case 必须失败。

变异只用于证明门禁，随后恢复；不得把负控提交进历史。

## 8. 不做的（记录理由）

- **不处理 `run` argv 转发。** 它需要 `--` 分隔和 program-args 原样透传，是 TOOL-03。
- **不合并两个驱动 parser。** 会把独立实现 oracle 降成同函数自比。
- **不新增 unknown-option / duplicate-option 规则。** 那不是参数基数，混入会扩大破坏面。
- **不让 `check` 只报告首个 target。** 既有 JVM 契约已经聚合诊断，native 应对齐它，
  不能以实现方便把 1..N 降格为循环调用一遇错即退。
