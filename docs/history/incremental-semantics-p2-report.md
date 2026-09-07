# 增量语义引擎第2期验收报告

> 状态：**historical** —— 2026-09-08，第1–2期交付的验收记录。
> 不是七期整体完成报告；后续能力以[当前设计](../incremental-semantics-design.md)为准。

## 结论与准确版本

多文件 LSP 已启用保守的模块前缀缓存。每次仍加载、解析整个输入闭包，
只跳过输入完全相同且无错误、无 Java 查询的连续前缀；首次差异之后全部重算。
不支持函数体缓存，standalone/Playground 仍冷分析，未发布或部署。

| PR | 实现提交 | 合并提交 | 合并前 CI |
|---|---|---|---|
| #105：Java 查询观测 | `58ebd4a5` | `4814d367` | 48/48 |
| #106：冷路径分步与独立对照 | `d5f8cb59` | `8c2312bc` | 49/49 |
| #107：前缀与 Workspace 接线 | `d8687d24` | `2f9655c4` | 50/50 |

#107 于 2026-09-08 01:47:45（新加坡时间）合并，准确 HEAD 无未处理 review。
上述是 PR 的检查结果，不冒充合并后的 main CI 或生产验收。

## 任务与证据

| 范围 | 已验收内容 |
|---|---|
| 1.1–1.2 基线 | 冻结旧循环、完整 Program/Cx 对照；load、独立 parse replay、check、comptime、query 分开计量；真实 overlay 编辑记录首差位置，barrier 排除 debounce |
| 1.3 外部观测 | 八个 Java hook 全覆盖，包括失败查询和 import 间接带入类型；九个编译成功负控；共享 checker 无 JVM 可变对象依赖 |
| 2.1 分步分析 | ModuleStep/Carry 保留 exports、完整 impl carry、next_id、诊断顺序与 std.impls_before 特例；CLI 保留冷入口 |
| 2.2 前缀 | 完整 LoadedModule 与当前 std identity 比较；首差后不接回后缀；冷暖完整产物对拍、12个引擎负控，包括“总是 cold” |
| 2.3 所有权 | Session 与 Program/entries/diagnostics 同次更新；冲突清缓存；最后关闭沿现有 Workspace 移除及 lease 释放路径退出；三个接线负控及既有协议/资源契约 |
| 2.4 逐出与编辑 | 每工作区128模块/1,048,576源码字符的一代前缀预算；evict、错误、FFI 安全回退；增删重排和 AST-only 输入变化；多模块与大单模块错误恢复实测 |

本地最终验证（源码为 #107；补充 benchmark 判定器随本报告提交）：

- `./bin/dawn test selfhost`：619项；native selfhost：485项。
- `./bin/dawn test scripts/incremental-semantics-contract`：354项。
- `probe.py`、`cold.py`、`prefix.py`、`lsp-prefix.py`（均在
  `scripts/incremental-semantics-contract/`）：分别9、6、12、3个可编译负控通过。
  冷循环及前缀比较覆盖13组完整 Program/Cx；编译、链接或反射失败不算有效负控。
- `scripts/lsp-workspace-contract/run.sh`：18个协议案例、20个资源/工作区负控通过。
- `scripts/selfhost-fixpoint.sh`：B==C，独立 calc 发射通过。
- Core：17份固定文本不变、89模块哈希门通过。新增 incremental 和 LSP 接线属于真实源码变更；
  exitmem 两处 handler ID 从29401移至29468，consolemem/lspq 生成 ADT 取号变化均已对照。
  没有扩大归一化规则；重录本身不作为正确性证明。
- 完整 doc-check（132个负控）、gate-map、CI budget、fmt 通过；上述生产验证由 #107 CI 再次运行。

## 实际收益与限制

compiler-plan 的13模块闭包中修改末模块，复用12、检查1。selfhost 的72模块
LSP entry closure 中修改 main（索引71），复用26、检查46；修改 parser（索引3），
复用3、检查69。Java 查询限制了前缀长度，不能宣称任意模块增量。

同源码私有观测服务器、GraalVM Community 21.0.2、SerialGC、2 GiB 最大堆，
各11轮丢前3轮：planner 强制冷路径刷新中位119.189ms，前缀模式61.180ms；
全部 hover/definition/completion 回复一致。原始轮次、执行计数和环境见
[`planner-20260908.json`](../../scripts/incremental-semantics-contract/baselines/planner-20260908.json)。
这是先 cold 后 warm 的单进程/模式小样本，不是通用倍数、置信区间或 SLA。

另用501函数的合成单模块，通过非 file URI 各跑11轮：第5轮注入类型错误，
第6轮恢复。旧版 `4814d367` 与候选 `d8687d24` 每轮诊断和三种查询完整一致；
错误落在当前注入声明的位置，恢复后诊断清空。丢前3轮并排除错误轮后，各7个
正常样本中位15.860ms/14.293ms，错误轮18.252ms/16.975ms。**两边均是冷分析，
不是缓存收益**。可复现命令见[夹具说明](../../scripts/incremental-semantics-contract/README.md)，
逐轮诊断、时间、环境与完整查询投影摘要见
[`standalone-20260908.json`](../../scripts/incremental-semantics-contract/baselines/standalone-20260908.json)。

hello_mod/selfhost 早期并行负载下的时间不用于稳定加速结论。parse replay 不是
loader 内部分段，不能从 load 相减。RSS 是进程级数据；强制冷模式也可能保留本轮
输出前缀，不能用两模式 RSS 差声称缓存占用。实际 retained heap 和长期编辑内存
仍属于第7期，未以逻辑字符预算替代该验收。

## 后续与未达范围

第3期仅开始原型调查：必须证明稳定声明身份、完整 ID 重定位和源码位置更新，
且不靠重新执行全部 checker 重建 ID。第4–7期依赖查询、函数体复用、Playground、
复杂 comptime/Java 答案依赖、语义索引和长会话验收均未完成。
第5、7期报告仍在各自验收后产出，不提前关账。
