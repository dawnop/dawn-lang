# 唯一 SourcePlan 设计

> 状态：**current** —— TOOL-10 的定稿与落地契约；只统一 source/MVS 与 Java 坐标规划，
> 不提前实现 LSP workspace 的完整 `ProjectPlan`。

## 问题

源码依赖与 Java 依赖曾沿两条独立路径解析同一份 `dawn.toml`：

- `driver/analyze.dawn` 使用 `manifestv`，抓取远端源码包并完成 MVS，再构造最终 source 图；
- `pkg/maven.dawn` 使用 line-oriented light parser，重新遍历目标目录与已有 package cache。

这使 classpath 和 lock 依赖 cache history：冷 cache 时远端包尚未存在，第二条遍历会静默漏掉
它的 `[java-deps]`；warm cache 又可能把 MVS loser 的坐标带进来。light parser 还会与正式 TOML
校验器在字符串、注释和错误边界上继续漂移。

## 定稿方案

保留 `driver/analyze.dawn` 现有 resolver seam，不新建 `driver/plan.dawn`。`source_plan` 的每次
调用都按以下顺序完成工作：

1. 以完整 `ManifestV` cache 遍历 source requirements，抓取并校验远端包；
2. 用 `SemV` / `semv_lt` 完成 MVS；
3. 只从最终选中的 `PkgR` 图收集 Java 坐标；
4. 将项目路径、最终 package 图、Java 坐标和诊断一起返回。

公开形状为：

```dawn
pub type PkgR = {
  name: String,
  root: String,
  deps: Map[String, PkgR],
  java_deps: List[MCoord]
}

pub type SourcePlan = {
  project: String,
  pkgs: Map[String, PkgR],
  java_coords: List[MCoord],
  diags: List[LocDiag]
}
```

目录目标保留调用者给出的项目路径拼写；文件目标通过最近的 `src/` 推导项目根。存在性与
“不是目录也不是 `.dawn`”的 CLI 前置判断仍留在 `main.dawn`，因为 LSP 必须能为尚未落盘的
`.dawn` buffer 规划工程。

## Java 坐标顺序

坐标顺序是可测试契约，不依赖 cache 遍历：

1. 根 manifest 自身坐标按声明序最先；
2. 根 source deps 按 manifest 声明序；`[deps]` path entry 与 `[deps.<alias>]` URL table
   依据 TOML 绝对 source span 稳定合并，不按依赖形式或 alias 排序；
3. 每个 package 先递归 children，再追加自身坐标；
4. canonical package root 只访问一次，diamond 不重复；
5. 按完整 `group:artifact:version` 去重，保留首见；不同版本不折叠。

`manifestv` 先按 source span 恢复 path/table 混合声明序；`Map` 再保证插入序，因此 resolver
构造的依赖 map 就是 manifest 声明序，不再额外排序。根 `[java-deps]` 仍独立地排在所有
source package 坐标之前。

## Maven 边界

`pkg/maven.dawn` 只消费 `manifestv.MCoord`。删除 `Coord`、第二套 coordinate parser、
light manifest parser 与第二次 package graph traversal；`fetch` 和 `lock_of` 的输入因此只能来自
`SourcePlan.java_coords`。lock 文本仍排序以获得稳定 diff，但排序不反向定义规划顺序。

## 门禁

`scripts/source-plan-contract/run.sh` 隔离 `DAWN_PKG_CACHE` 与 Coursier cache，并把 source URL
和 Maven mirror 都限制为 `file://`。它构造两个同名远端包版本：MVS loser 声明合法但不存在的
`g:poison:1`，winner 声明本地可取的 `g:selected:1`；冷、热 cache 分别 build 文件目标，且
`dawn lock` 只记录 selected。另一个临时 Dawn inspector 直接调用公开 `source_plan`，双向断言
URL table/path entry 的混合顺序，并固定 root `[java-deps]` 始终最先。隔离的失败场景还要求同一
archive 的同一坏 URL 跨 alias/subdir 与 winner 阶段只产生一次 fetch diagnostic，同时坏镜像
在前、同 hash 的可用镜像在后仍必须成功；静态检查拒绝第二
parser/graph helper 复生。`manifestv.dawn` validator 测试固定 span merge；`analyze.dawn` 的
纯测试固定 mirror failure 以 `(hash, url)` 为身份、同 URL 只尝试一次且不同 URL 不被抑制，
并继续覆盖 children-before-parent、diamond visited、完整坐标去重。冷、热两个可执行 JAR 都会
实际运行并精确输出 `winner:42`，不能只靠 build 成功假绿。

落地时实际执行并恢复了六类变异：

| 变异 | 转红原因 |
|---|---|
| 从完整 manifest cache 收坐标 | Coursier 尝试本地仓库不存在的 `g:poison:1`，冷 cache build 失败 |
| 文件目标仍按旧逻辑直接返回空 | `g.Selected` 不在 classpath，文件目标 build 报 class not found |
| 对根 dependency keys 排序 | 纯测试的 `child-a` / `child-b` 声明序断言失败 |
| 删除 canonical-root visited | diamond 第二份 package 坐标泄漏，纯测试失败 |
| 删除完整坐标去重 | child 重复根坐标，纯测试失败 |
| 恢复 `pkg/manifest.dawn` light parser | contract 的静态删除面检查失败 |
| 删除 manifest path/table 的 source-span 稳定合并 | validator 与 SourcePlan 双向顺序测试同时失败 |
| 把 mirror failure 退回 hash-only 或恢复 check/insert key 不一致 | 可用的第二镜像被抑制，或同一坏 URL 被重复抓取并产生多条诊断 |

## 同一 CLI 调用仍不是单次 snapshot

`build` / `run` / `test` 的 JVM 驱动会在 parent process 调用 `source_plan` 取得 Java 坐标，
扩展 classpath 后 re-exec；child loader 随后再次调用同一 `source_plan`。两次调用已经共享唯一
validator、MVS 与 graph algorithm，但**不共享同一个 `SourcePlan` 值**。若两次之间
`dawn.toml`、source archive/cache 或本地 path package 改变，classpath 与实际加载的 source 图
仍可能来自两个时刻；本刀不能冒称提供 invocation snapshot。

在当前进程边界下复用同一值需要序列化递归 `PkgR`、诊断和 canonical roots 传给 child，或取消
re-exec、把动态 classpath 注入当前 compiler process。前者就是后续完整 `ProjectPlan`/workspace
snapshot，后者与 TOOL-06 的 classloader 设计耦合；两者都会扩散 CLI、loader 与 LSP API，
不属于删除“双 parser/双 graph”事实源的小刀。该 TOCTOU 归入 TOOL-05 snapshot，TOOL-10
只关闭 classpath/lock 由另一 parser 和 cache-history graph 产生的问题。

## 不做的（记录理由）

- **不建立完整 `ProjectPlan`。** modules、classpath、lock、stamp、跨 re-exec 序列化与
  workspace snapshot 属于 TOOL-05/06，混入本刀会扩大 Core、API 与行为面。
- **不让 `source_plan` fetch Maven 或校验 lock。** 它只规划 source 图与直接 Java 坐标；
  Coursier 和 lock I/O 仍由 CLI/Maven 层负责。
- **不按 `group:artifact` 去重。** 不同版本仍应交给 Coursier 的传递图版本选择。
- **不 canonicalize `SourcePlan.project`。** CLI 诊断和 transcript 依赖调用者原有路径拼写；
  package identity 才使用 canonical root。
