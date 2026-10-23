# Playground C 独立视图

> 状态：**current**。按 2026-10-23 协调者裁决实施，实现入口已落地，完整交付 SHA 与门禁证据记在交接报告。基线 `fdebffc0aca84ef8346a550381488912cb247a89`。

本刀之前 C 请求先探测 JVM 工具链，然后生成 C/JVM 两张 map，以交集建表。这既使 C 页依赖 javap，也把双后端缺口混入 C 页的 gaps。方案 A 把两种用途分开：C 页只映射 native emitc 的 C map，JVM 页保留原有 paired oracle。`table_from_maps`、`explore`、`explore_strict` 不变。

独立入口只接收源码、C text 和 C map。筛 module 与范围，按 `(lo,hi,nlo)` 去重、排序；标识符仍从源码读，不比较 what；非标识符只核对 C 同键 what，再识别运算符或数字。tree、check_table、pane 按 `(lo,hi)` 聚合及直接子项扣行规则保持。C 的 gap=0 只证明 C 局部映射，不证明 JVM 与它一致。

请求先解析 target，再构造能力上下文。C 只信部署期有效的 `PLAY_TOOLCHAIN_ID`，只探测匹配 release 的 dawnc。缺元数据、缺 dawnc 或 release 不匹配答 503；native 拒绝 Java 程序保留诊断；非零空诊断答 500；超时不重试。C job/result 单独编码，只读 C 原料，沿用 staging、工程三依赖、沙箱、flock、清理和限额。/check、JVM、/run、Tile 的回落策略保留。

C 与 JVM 使用独立 schema 前缀的答案键，共用请求与 warm helper。C 键不含 javap，JVM 键保留工具链与 javap presence。旧库同工具链必 miss。只向请求目标写成功、诊断或 422；超时、503、500 不保存。部署 warm 显式请求 C/JVM/run/必要 Tile，继续 fail closed 与整目录替换；服务只读答案库。通用 cache_key 不变。

UI 的局部 id 只在当前表内有效。跨页保留源码快照、build 与 `(name,from,to,nfrom,nto)`，目的表唯一匹配后换成局部 id。缺失、歧义或截断不高亮并说明，回原页可恢复。编辑、取消与关闭清空身份，过期异步结果不应用；Tile 中转相同。503 按目标解释，旧 listing 必须 stale 并清除活动高亮，C 状态独立。

验收保留旧 paired 严格门，增加 C-only 夹具、HTTP 零 JVM 哨兵、错误/缓存隔离和前端交互负控。逐个记录 14 侧栏及 3 个工程补充的身份集合、id/parent/outs/gaps 差分；相同工具链与原料下 JVM 除 ms/cached 外字节不变。性能采用本刀交错五组实测，不引用历史倍率。该旧/新对比是一次性验收工具，不是每次 push 的回归门或速度门槛；原始数据与中位数保存在 `agent-handoff/play-c-only-view-report-20261023.md`，需重新验收时手动运行 `playground/test/c-only-acceptance.sh 0` 到 `4`，或用 `all` 一次运行五组。

同提交交付站点和 runner；当前 wire 没有 schema 字段，build 无法识别同工具链的协议混版，旧标签页必须刷新。canary 不能全局忽略 calls/outs/gaps：C 的集合、编号、parent、行归属和 gaps 可按上述规则改变；C pane text/src/total 与 JVM paired payload 保持。编译器源码及 emit C/map 字节不在改动范围，因此没有预先声明 Emit-Change 或推进版本的理由。

不做的（理由）：不改 JVM 对照语义，不以 C map 伪造 JMap；不修 emitter 漏图（遇到则保留失败例交协调者）；不新增运行期缓存或无 JDK 完整部署模式；不改 /run、Tile 键；不部署或访问服务器。门禁证据由协调者发布。

实现记录：`f87312045145e3d04f5d2a564e57e436acb3ced1` 新增独立 xmap、native job/result、目标能力和答案 schema，并将 UI 切页改为源码身份。验收补充包括局部映射夹具、真实 pane DOM 交互、8 MiB/262144 bytes/2000 calls 边界、HTTP 哨兵、旧 runner 同工具链逐字节 oracle、完整 warm、交错五组性能和六类源码变异负控。所有重门通过外部门禁执行。完整 HTTP/制品/预热矩阵保留一个常驻作业，性能组仅保留手动入口。矩阵的最终命中检查复用同作业前半段已取得的 28 份 C/JVM 冷响应，保留完整 warm、答案数量、冷库为空、cached 标志及仅归一 ms/cached 的逐字节断言；不重复发出这 28 个编译请求。HTTP 哨兵和源码变异负控继续由原 Playground contract 作业执行。steps lock 随作业移除重录。
