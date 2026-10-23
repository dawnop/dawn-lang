# 具名字段离线迁移

本工具在刀 4 完成后删除。先用本 PR 构建编译器，再执行：

```sh
python3 scripts/named-arg-migrate/migrate.py --jar build/dawn-selfhost.jar --out /path/to/review.json
python3 scripts/named-arg-migrate/migrate.py --jar build/dawn-selfhost.jar --root /path/to/scratch --out /path/to/applied.json --write
python3 scripts/named-arg-migrate/run.py
```

`--root` 必须是有跟踪文件的 Git 工作树。默认只读；`--write` 只应用 `source` 清单。
`--java`、`--javac` 可指定与构建产物匹配的 JDK。临时文件遵从 `TMPDIR`。
在 scratch 中迁移并格式化 `std/` 后运行 `python3 scripts/gen-stdsrc.py`，
再用过桥编译器运行该副本的 selfhost 测试；生成的嵌入文本必须与迁移后的 std 一致。

`SpanProbe.java` 调用真实 `front.parser.parse_module`，反射遍历原 AST，
以 `Arg`、`PatArg` 的名字跨度与真实 lexer 的相邻 token 定位值字段冒号，
注释与普通字符串文本不是编辑候选；插值表达式按原始 base offset 重新 lex。
offset、line、column 都按 Unicode
code point 计；倒序单字符替换不移动其他位置。record pun 没有分隔符，不产生编辑。
错误恢复丢失的字段通过真实诊断把错误 RHS `=` 暂改成等宽 `0` 后重解析，
只收原文仍为冒号的位置，并标记 `recovered`，不会把修复文本写回。

JSON 按模块和源文件列出 `N`（调用）、`R`（record）、`P`（模式）、行列及原文。
`embedded_review` 另列 Dawn 解码字符串、Markdown、Python 常量、shell heredoc、
JSON 和文本 golden 的可解析候选。这些是审阅下界；片段包裹、拼接、历史外语引述
仍需人工判断，不能直接用解码 offset 修改宿主文本。正则仅抽取宿主片段，
所有分隔符都由 parser 的 AST 决定，不作全仓正则替换。

三个 grammar 负例丢失字段应核对在
`match_arm_recovery.dawn`（一个）和 `stmt_recovery_nested_brace.dawn`（两个）。
语法诊断清单保留，不能把拒绝语料或 `selfhost/builtins.dawn` 当作可编译模块。
