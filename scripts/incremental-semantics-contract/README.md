# 增量语义契约夹具

多文件 LSP 已启用保守前缀缓存；CLI 与 standalone 仍走冷分析。
下列冷路径命令本身不证明缓存命中，命中由前缀/工作区执行计数门禁另行验证。

- `python3 scripts/incremental-semantics-contract/probe.py`：八个 Java hook 与
  refusing guard 的九个可编译负控。
- `./bin/dawn test scripts/incremental-semantics-contract`：query probe 集成、
  冷路径阶段嵌套、错误恢复和 loader 诊断顺序。
- `python3 scripts/incremental-semantics-contract/cold.py`：私有源码副本中注入
  冻结旧循环，对照相同 StdCtx、LoadedModule 和 CtOpts；六个变异体只改新路径。
  需 JDK 21+ 的 `java/javac/jar`。

旧循环来自 `58ebd4a5` 的 `analyze_program`，仅改函数名；它共享未改动的
checker/stdlib helpers，不调用新 transition。13 组结果覆盖模块换序、恢复诊断、
parse/check/comptime 失败、impl/ID 传递和 std 的 impls_before 特例。

比较器由 javac 独立编译，通过反射比较整个 Program（包括 AST/TAST、comptime、
完整 Cx）。只排除 Cx 中同一 refusing oracle 的 jsig 能力；Array 比较逻辑长度内
的内容，不比较 backing capacity/append watermark。未知宿主对象抛错，不算相等。
新增字段自动参与比较，循环引用用对象对去重；浮点按原始位比较。Java 的标量、嵌套数组、
循环引用和未知对象有自检。采用独立比较器是因为直接生成完整 Cx 的 Eq 字典时，
测试程序出现 List_Int 构造器描述符不匹配；此处未修改编译器发射契约。

负控必须成功构建且命中明确的语义差异断言；编译错误、反射错误、timeout 不算通过。
impl 负控清掉 checker 的输入 impl carry，而不是清掉输出 fold 的初值：后者会被
完整 cx.impl_table 重新补齐，是等价变异体，不能用来证明门禁失效。

## 冷路径基准

```sh
python3 scripts/incremental-semantics-contract/bench.py \
  --java-home /path/to/jdk21 \
  --output review/cold-baseline-new \
  examples/projects/hello_mod selfhost
```

输出目录必须不存在。每个目标使用独立 JVM，同一 captured plan/target Java lease
中跑11轮，丢前3轮，cold/observed 交替先后顺序。保存逐轮 TSV、源码 SHA-256、
JDK/OS/参数、构建日志、摘要和进程峰值 RSS；每轮必须无诊断且所有模块执行 check/comptime。
parse replay 不是 loader 内部分段，不能从 load 相减；RSS 包含启动、std 和整个进程，
不是缓存保留内存。八个样本不足以声称稳定的加速倍数；这个入口只测冷分析阶段。

## 前缀与工作区

`prefix.py` 对照完整 warm/frozen-cold 产品，覆盖12个可编译引擎负控，包括预算、
std身份变化及构造器的负预算拒绝。`lsp-prefix.py` 覆盖三个工作区接线负控，要求
owning FAIL 后是断言失败，不把 JVM 链接错误算作成功。工作区计数测试在共享server里，
同时由 JVM/native selfhost 套件运行。原有 `scripts/lsp-workspace-contract/run.sh`
另行守18个协议案例和20个资源/工作区负控，不能只靠新计数测试替代它。

`lsp-bench.py` 通过实际 didChange overlay 编辑目标文件，磁盘源不改；
立即跟 barrier 强制 flush，所以 sync 不包括空闲 debounce。随后单独测
hover/definition/completion，并保存原始回复和 RSS。示例参数：
`--entry <path> --edit <path> --needle <reference> --output <new-dir> -- <server-command>`。

单大模块错误恢复使用 `standalone-large.dawn.txt`（500个简单函数及一个入口，
合成语料，不冒充真实大型应用）。在上述参数后加
`--uri untitled:incremental-large --error-round 5`，entry/edit 指向同一份文件，
needle 为 `value_499(1)`。11轮中的第5轮注入类型错误，第6轮恢复；每轮必须发布
当前文档版本，错误必须落在注入声明的位置，恢复后全部诊断必须清空。
错误轮不混入正常编辑中位数；原始 diagnostics 与 query 回复一同保存，用于旧冷路径
对拍。`lsp-bench.py --self-test` 验证诊断判定器及六个负控，并在 CI 执行。

`lsp-observe.py --output <new-dir>` 构建私有服务器，在 stderr 记录最终模块顺序和
实际复用/执行计数，不改变生产协议；`--cold` 只在私有副本里强制每轮先逐出 Session。
两个模式都可用同一源码、JDK和编辑序列对照，回复必须相同。强制cold仍可能保留本轮
输出prefix，不能用这两者的RSS差直接估算缓存大小。baseline JSON明确记录样本与限制。
