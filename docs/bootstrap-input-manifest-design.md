# 自举输入清单协议

> 状态：**Producer、严格 v1 consumer 与递归 launcher discovery 已落地**。完整的
> fail-closed hasher、framed v2 stamp、pre/post re-plan 与可恢复 commit-marker 仍是二期残余，
> 本文逐项区分现状与待办。

## 问题

`bin/dawn` 的 selfhost cache stamp 不能用 direct-only shell 重新解释 `dawn.toml`。权威
source graph 由独立无 Java 包 `compiler-plan/` 的 `source_plan` 完成 MVS、远端包抓取与 path
package 递归；launcher 只读根直接依赖会漏掉 Planner 自己的传递输入。

协议只为 selfhost bootstrap 的**项目目录**提供由最终 `SourcePlan` 导出的输入清单。它不是
通用编译输入 API，不接受 standalone `.dawn` target，不要求旧 seed 认识新命令，也不把同一
CLI 调用升级成 filesystem snapshot。

## 隐藏命令

```text
dawn __source-inputs --base <repo> <project-dir>
```

- `project-dir` 必须是现存目录。现存 `.dawn` 文件在调用 `source_plan` 前以 CLI error
  退出 2，stdout 为空；不能把 direct-file 模式误解释成“它所在项目的全部输入”。
- 目录边界通过后才以显式 `ProjectDirectory(project-dir)` 完整执行 `source_plan`。
- plan 有诊断时沿用编译诊断并退出 1，不输出清单。
- `--base` 只定义持久化路径的相对基准，不参与项目解析，也不改写
  `SourcePlan.project`。后者继续保留调用者拼写，这是
  [`source-plan-design.md`](source-plan-design.md) 已定的 CLI 语义。
- 参数形状错误退出 2。命令保持隐藏，不加入公开 `--help`。

旧 seed 的职责仍只有“用当前源码构建 stage1”，launcher 不要求它认识 `__source-inputs`。
启动时若已有认识该命令的当前工具链 JAR 就直接消费 Producer；否则走下文限定的首次递归
fallback。完整 v2 将由 stage1 及后续 candidate 做 pre/post re-plan，仍不把命令下推给 seed。

## 清单内容

清单只来自 project-directory target 成功得到的最终 `SourcePlan`：

1. 根项目固定加入 `dawn.toml`（必需文件）、`dawn.lock`（可缺失文件）与
   `SourcePlan.source_root`（必需目录树；目录项目通常为 `src/`）。
2. 从 `SourcePlan.pkgs` 的最终选中项递归 `PkgR.deps`。每个 package 加入
   `parent(pkg.root)/dawn.toml`（必需文件）和 `pkg.root`（必需目录树）。
3. package root 先做绝对化与词法规范化，再按这个 canonical spelling 去重；diamond
   只输出一份。loser、失败 requirement 和 resolver cache 中未进入最终图的 package 不得出现。

`PkgR.root` 是 `src/`，所以 package manifest 必须取它的 parent；把 `src/dawn.toml`
当 manifest 是协议错误。package 的 `dawn.lock` 不是当前 build input，不进入清单。

## 线协议 v1

第一行是版本：

```text
dawn-source-inputs-v1
```

后续每行是三个字段：

```text
<scope>\t<kind>\t<path>
```

- `scope`：`R` 表示相对 `--base`；`A` 表示 base 外的绝对路径。
- `kind`：`F` 是必需文件，`O` 是可缺失文件，`T` 是必需目录树。
- parser 只切前两个 tab，剩余整段都是 path；因此 path 中的 tab 可表示。
- path 含 LF 时拒绝。行协议不能无歧义地表示它，不能转义后假装仍是原路径。
- base 内路径必须持久化为规范化相对路径；只有 base 外输入可写绝对路径。这样 checkout
  从一个绝对目录复制到另一个目录时，旧清单不会继续指向仍然存在的旧 checkout。
- header 与每条 record 都以 LF 结束；record 按完整记录的 code-point order 排序，输出不依赖
  map 遍历偶然性。

这里的 canonicalization 是 `fspath.absolute` 的绝对化与词法规范化。Producer 同时拒绝路径
任一现存 component 是 symlink，因此不靠 symlink target 猜 physical identity；也不改变
`source_plan` 对展示路径和诊断路径的既有拼写。

现行 consumer 还在 shell 边界复核持久化 spelling：

- `R` 的 `.` 专指 checkout root；除此之外，空路径、绝对路径、`.`/`..` segment、前导 `./`、
  重复分隔符与 trailing slash 全部拒绝。通过 spelling 校验后才拼到 checkout root，并再次检查
  没有逃逸。
- `A` 明确允许规范根 `/`；其他值必须是规范绝对路径。相对路径、`.`/`..` segment、重复分隔符
  与非根 trailing slash 全部拒绝。base 外 package 合法存在，所以规范 `A` 不会被强行拉回
  checkout。

header 错误、空 manifest、空 record、未知 scope/kind、未以 LF 结束或只有 header 的 manifest
全部拒绝，且不会把此前已解析的前缀暴露给 stamp。

## Fail-closed 边界

Producer 在向 stdout 写任何字节前验证完整清单：

- base 必须是无 symlink component 的目录；
- `F` 必须存在、不是目录、不是 symlink，且可读；
- `O` 缺失是显式正常状态；一旦存在，就按 `F` 验证；
- `T` 必须是无 symlink component 的目录；递归列举每层，拒绝任意 symlink，并读取每个
  叶文件以暴露权限、消失竞态和 file/directory type 错误；
- list/read 失败、路径在遍历中消失、必需输入缺失或类型不符都退出 1；
- 错误前缀与原因稳定，诊断里的 LF 显示为 `\\n`，避免路径把一条诊断注入成多行。

验证不是 snapshot。源码可在 preflight 后改变；TOOL-05 记录的两次 plan TOCTOU 与
filesystem 的 A→B→A（ABA）仍然存在，不能借本协议宣称关闭。

## launcher consumer：已落地边界与二期残余

Producer 清单只替代 launcher 对 source graph 的自行解析。consumer 仍须把它与 launcher
拥有的静态 recipe inputs 合并：`std/`、`scripts/seed-release.txt`、
`scripts/seed-checksums.txt`、`scripts/seed-std-checksums.txt`、`scripts/seedjar.sh` 与
`bin/dawn`；不能因为 source graph 有了权威清单，就漏掉 seed/std/recipe identity。

现行 `bin/dawn` 在已有当前工具链 JAR 时执行 `__source-inputs`，把 v1 的 `R/A`、`F/O/T`
记录原样保留为 typed stamp input；`F` 必须是可读的普通文件，`O` 只允许缺失或普通文件，`T`
必须是可遍历目录树，树内 symlink、非普通叶、`find`/`cat` 失败和遍历中的类型变化都 fail
closed。因此 `compiler-plan` 以及它传递依赖的 `fspath`、`sha2`、`inflate` 都会进入摘要。
Producer 非零退出、空输出或坏 manifest 均直接终止，stderr 保留；**不会**因为已有 JAR 的
Producer 出错而回退到 shell parser。

只有当前工具链 JAR 完全不存在的首次 checkout 才使用受限递归 fallback。它只接受本仓采用的
`[deps] name = "relative-path"` 形状，按每份 manifest 自身目录解析；URL/table 或其他陌生形状、
绝对依赖、解析后逃出 checkout 的依赖、缺失目录和超过深度上限的图全部 fail closed。它是
zero-toolchain 引导器，不是第二个 validator/MVS resolver；只要当前 JAR 存在，该次启动就让位给
Producer。

这一 fallback 是为解决 zero-toolchain 引导边界作出的架构裁决。原“绝不 fallback”条款没有
回答“当前工具链尚不存在时由谁运行当前 Producer”，实际只能漏传递依赖或形成鸡生蛋。
递归输入覆盖由 `scripts/bootstrap-guards/run.sh` 对 Planner 及其传递依赖逐文件变异固定。

以下完整 v2 consumer 协议仍待整体落地，不能因递归发现已经修好就冒称 TOOL-14 全部关闭：

1. legacy stamp 或缺少 `dawn-selfhost.inputs` 一律 cache miss。
2. 旧 seed 只构建 stage1；不得要求旧 seed 执行隐藏命令。首次 fallback 只覆盖 checkout-local
   path closure，不能扩张成另一套 URL/MVS/manifest validator。
3. stage1 生成 `inputs.pre` 与 `source.pre`，再构建 final candidate；candidate 重新 plan，
   生成 `inputs.post` 与 `source.post`。两份 inputs 与 source digest 必须分别相同，否则报告
   `bootstrap inputs changed during build`，不提升。
4. SHA-256 工具启动时先验证 `abc` known vector。无工具、启动失败、空输出、非 64-hex、
   或摘要值错误全部 fail closed；删除 mtime 与 `no-sha256` fallback。
5. digest 输入使用 `frame(x) = byte_length ":" raw_bytes`。record、scope、kind、path、树根、
   相对叶路径、存在/缺失状态和内容分别 framing；空树与 optional missing 也有显式 frame，
   不再拼接 `path + newline + contents`。
6. bootstrap identity 同时覆盖默认 seed 与 `DAWN_SEED` override；撤掉 override 后不得复用
   未验证 seed 构建的 jar。
7. v2 stamp 至少记录 `source`、`bootstrap`、`inputs` 与 `jar` 四个 SHA-256。正常启动复验
   inputs 与 jar 摘要，任一缺失、损坏或交错都重建，不执行旧 jar 兜底。
8. 每个 builder 在唯一 staging 目录完成 candidate、inputs 与 stamp。验证后按
   jar → inputs → stamp 的顺序 rename，stamp 是 commit marker；提升后再次复验，遇到并发
   交错最多重试两次。

固定三个目标文件不能形成真正的多文件原子事务。以上只能称**可恢复 commit-marker 协议**：
进程若在 jar 与 inputs 之间崩溃，旧 stamp 摘要会让下次重建；不能称“原子三文件事务”。它也
不提供 filesystem snapshot，源码在构建期间的 ABA 仍是明确残余。

## 门禁与负控

`scripts/bootstrap-input-manifest-contract/run.sh` 独立固定：

- root、递归 path package、外部 package、diamond 去重与 optional lock 的精确 v1 输出；
- checkout 迁移后所有 repo 内记录仍是 `R`，不残留旧绝对目录；
- 现存 direct `.dawn` file 在 plan 前以 exit 2 拒绝，stdout 为空；
- LF、symlink、缺失、错误 file/tree/optional type 与遍历失败均不产生部分清单；plan
  diagnostics 与参数错误同样保持 stdout 为空，命令不进入公开 help；
- 三个私有 Planner mutant 必须先成功构建**只依赖 `compiler-plan` 的薄 producer probe**，
  再分别因以下合同转红：删除
  `PkgR.deps` 递归、漏 package `dawn.toml`、把 repo 内路径持久化为绝对路径。

SourcePlan/MVS 的顺序、mirror、cache 与 lock 断言留在
`scripts/source-plan-contract/run.sh`。拆分后两边均不制造 ASM fixture，也不复制或编译整套
`selfhost`；真实 CLI 正例仍由 `dawn __source-inputs` 驱动，probe 只服务 post-plan 边界和 mutant。

`scripts/bootstrap-guards/run.sh` 另以 fake Java/current-JAR 进程边界固定 consumer：producer
非零、空输出、坏 header/record/scope/kind/path 都必须失败且不产出 digest；缺失/错误类型的
`F/T` 必须失败，缺失 `O` 必须成功，遍历与读取错误必须传播。zero-toolchain leg 还拒绝 URL
table、绝对依赖和逃出 checkout 的相对依赖，并逐文件证明递归 closure 会改变 stamp。

二期还必须补 hasher known-vector、无长度定界碰撞、持久化 v2 inputs 的缺失或摘要错配、
jar/inputs digest 漏记、旧 seed 被提前调用、删除 final re-plan、共享 staging 并发和 stamp
提前提升等 consumer mutants。这里的“坏 inputs”指尚未落地的持久化 v2 artifact，不是已经有
负控的 v1 producer stdout。

## 不做的（记录理由）

- **不因递归 discovery 已接入就提前升级 stamp schema。** 当前切换只关闭 direct-only 漏输入；
  hasher、framing、持久化 inputs 与 promotion 恢复必须连同各自负控按完整 v2 一次关闭。
- **不把绝对路径写回 `SourcePlan`。** 调用者拼写属于公开诊断语义，只有序列化层需要
  可迁移 canonical spelling。
- **不支持 direct-file target。** selfhost bootstrap 构建的是有 manifest 与 `src/` 的项目；
  `SourcePlan.project` 无法表达 standalone file 本身，把它固定展开成项目 manifest/tree 会
  错报缺失或扩大输入边界。通用 direct-file 输入模型若未来需要，必须另行设计。
- **不序列化整个 `SourcePlan`。** diagnostics、Java coordinates 与 workspace overlay 属于
  TOOL-05/06 的 `ProjectPlan`/snapshot，不是 selfhost source digest 的输入格式。
- **不承诺真正多文件原子性或构建期 snapshot。** 普通 filesystem rename 没有这个能力；
  commit marker 只保证下次可检测、可恢复。
