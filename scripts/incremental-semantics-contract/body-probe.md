# 第3期私有函数体原型

这不是生产函数缓存，也不代表第3期完成。先验证“保留发射取号时，不重查函数体能否
重定位已检查产物”这一决策门的小范围前提，再实现稳定声明身份与完整重定位。

`body-probe.py` 复制编译器到新的输出目录，追加读取生产 `check_module_headers`
阶段产物的私有适配入口；不再复制header流程，生产源码不改。11个显式签名样例覆盖局部绑定、泛型、闭包、默认参数、
循环、trait 字典、声明效果、效果多态、局部函数、跳转和类型错误。

执行方式（输出目录必须不存在）：

```sh
DAWN_BIN=/path/to/independent/worktree/bin/dawn \
  python3 scripts/incremental-semantics-contract/body-probe.py \
  --java-home /path/to/jdk21 --output review/body-probe-new
```

追加 `--all` 运行完整 positive 和八个编译负控；也可用 `--mutant <name>` 单跑。
负控包括 skip-symbol、skip-captures、skip-spans、skip-operator-spans、ambiguous-key、
skip-cx-symbols、skip-diagnostics、skip-symbol-location，分别遗漏符号、闭包捕获、
源码位置、运算符位置、重复声明拒绝、Cx符号更新、诊断和符号声明位置。
每个必须成功编译且命中自己的语义不一致断言，编译失败不算通过。

当前原型同时验证：

- 私有顺序检查得到的每个 TFun 与正常 `check_module` 的对应产物完整一致。
- 每个函数不改变先前已有的符号；只有 `wrong` 样例新增一个诊断。
- 起始 next_id 平移1000后，分配数量与诊断不变。
- 纯 Dawn 数据遍历只重定位本函数区间内的符号，所得完整 TFun 与平移起点重新
  冷检查的产物一致。独立 Java 结构比较器不依赖编译器生成的完整 Eq 字典。
- 在前一个函数增加局部变量，并在文件前插入含非 BMP 字符的注释；复用侧只检查
  改动函数，后面10个函数纯数据重放得到的 TFun 和每个 body 边界的完整 Cx 均与
  冷检查一致，覆盖符号取号、码点位置、恢复诊断与旧符号保留。冷检查只作对照 oracle。
- 私有 ModuleKey/FunctionKey 不含位置和数字 ID；函数重排不改变唯一名称的 key，
  重复声明、缺失名称不提供 key，不同分析 world 的 key 不相等。

2026-09-08 本地11例及真实编辑对拍通过。状态变化的并集为 `frame`、`next_id`、
`syms`、`diags`、`current_tparams`、`current_eff_vars`、`loop_jumps`。
这只是样例观察，不能据此删掉 Cx 的其他字段或断言它们在全语言中恒定。
正常 check_module 在检查 body 之后还合成默认参数函数并更新函数表，不能遗漏。

尚未完成：覆盖所有声明类别的 ModuleKey/DeclKey、nominal/type/effect身份迁移、
所有 TAST 形态、全语言 Cx 增量拼接、非均匀源码位置映射和双后端/Core对照。
当前 relocation 对未知表达式/语句直接失败；固定 header 下保持类型和效果引用原样，
不能直接用于 header 已改变的会话。原型留在测试文本，不接生产路径；独立完整实验在
incremental-semantics CI job 执行，本地 positive 加八负控共35.66s。
每个 body 内只支持整体平移；默认参数合成仍由原 check_module 完成，未宣称整模块
装配已迁移。当前复用条件由固定实验输入保证，尚未实现 query 依赖失效或真实缓存资格判定。
