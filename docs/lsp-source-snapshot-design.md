# LSP 每修订共享源快照

> 状态：**proposed**：实验实现已完成，等待性能验收。以下计时门是采用条件，不是通过声明。

## 问题与边界

基线 f58c5fbb 的变化文档在 Doc 的 UTF-16 视图、Doc 行表、parser 和 loader 行表各有一次
整文 code_points 入口，行起点全扫两次。源码依据为 lexer 的 view_of、
line_starts_of、lex_go，parser 的 parse_marked，以及 analyze 的 fresh_parse。
现有未变文件解析复用继续保留。

## 方案

lexer 构造绑定原文的不可变 SourceSnapshot，共享 code points、UTF-16 视图和
行起点。parser 从快照调用原有 parse_marked 的恢复流程，取得同次 ParseMarks，
不保存 token 流。server 在替换 Doc 时一次构造视图与行表，在已通过冲突检查的
overlay 上把同一修订交给 loader；loader 逐原文验证快照，错误修订回退冷构造。
快照只在文本准备阶段使用，不进入 LoadedModule 或模块准入的结构相等比较。
普通调用保留原入口，工作区与 standalone 共用快照入口。

## 验收

独立 JVM 入口探针对 b/d 各两次修订的计数均为：整文解码 4→1、行扫 2→1。
这些是次数实测，不是计时收益。生产产物交错 A/B 至少三组完整批次，固定 3 轮预热、6 会话、7 正式轮
及 150 函数各两组加删。b/d 非 GC 区间成对中位净省须达到 8 ms；原始 L-edit
p90 不扣 GC，每批各场景不超过 100 ms 且 b 模型 F p90 不超过 117 ms 才称缺口
关闭。另比较 L-ws、RSS 和初次 open。数值门槛用于决定是否采用，不以次数下降代替延迟实测。

契约比较 cold/incremental 的诊断正文、位置及 full/range semanticTokens；覆盖
首行插入、非 BMP、CRLF、删括号恢复态，并故意复用错误修订与重复解码。
既有 stale-line-starts、identity 碰撞、选择导入提示及 comptime 传递读取守卫保留。

## 不做的（理由）

- 不改模块准入或语义失效；它们需要独立证据，与本次重复文本处理无关。
- 不改 JVM 参数、调度、诊断先发次序或解析恢复规则；避免混入另一把刀的收益。
- 不缓存完整 token 流，也不为所有未打开模块保留 UTF-16 映射；避免扩大驻留内存。
