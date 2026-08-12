# `for` pattern 设计

> 状态：**current**。本文记录 SYN-13 的定稿语义与落点；语言规范仍以
> `docs/spec.md` 为唯一权威定义。

## 一、问题

`let`、`match` 已共享完整递归 pattern grammar，但 `for` 头仍只接受一个小写名字。
遍历 pair、record 或单构造器值时，用户必须先绑定临时变量，再在循环体中解构。这使
binding grammar 随语句位置改变，也让 Map、zip 一类 API 的常见用法多出无意义样板。

## 二、语义

`for pattern in source { body }` 与 `for pattern in from..to { body }` 都复用现有
`pattern` 文法，包括 tuple、list、constructor、qualified constructor、or-pattern 以及
行首 `|` continuation。循环 pattern 必须对元素类型不可反驳；不匹配不是过滤，checker
会报告针对性错误。

source 与 range 两端在 pattern scope 外按源码顺序检查和求值，各恰好一次。pattern
只把 binding 引入 body；source、range 上界和循环后的代码都看不到这些 binding。pattern
本身已有类型、构造器或 alternative binding 诊断时，不再派生不可反驳诊断。usefulness
达到确定性预算时沿用 fail-closed complexity diagnostic。

## 三、表示与 lowering

解析树使用 `SFor(pat, from, to, body, lo, hi)`；typed tree 使用
`TSFor(pat, item_ty, from, to, wit, body, has_jumps, lo, hi)`。`item_ty` 独立保存，即使
pattern 是 `_` 或纯结构而没有 binding，lowering 仍知道 subject 类型。

range loop 使用隐藏 induction local，不把用户 binding 当计数器。iterable loop 仍将
source 与 `iter_start` 放在循环外；每轮 `iter_get` 先写入唯一隐藏 item local，再由共享
pattern lowering 建立 selector 与 binding。pattern setup 位于 done 检查之后、body 之前。
`CSLoop.step` 继续承载 range increment 或 `iter_next`，所以 `continue` 执行 step，`break`
不执行 step。

## 四、LSP 与 formatter

pattern header 中的 constructor 和 binding 参加 hover 与 definition。小写 pattern 位是
新 binding 声明，不提供 outer-local completion；source 使用外层 scope，body 再加入 pattern
bindings，循环后不保留 pattern 或 body locals。or-pattern completion 只收第一支的
canonical symbols。

formatter 仍是 token-stream formatter，不增加生产分支；只增加行首 `|` 的 for-pattern
格式化与幂等语料。AST dump 输出完整 pattern，而不是退化成一个名字。

## 五、自举边界与验证

当前 v0.64 seed 不理解新语法，所以 `selfhost/src` 与 inline Dawn tests 不直接书写
for-pattern。新语法只出现在字符串、外部 corpus 和由 HEAD compiler 编译的 JVM/native
fixture 中。

独立 contract 对 parser、checker、lowering 与 LSP 的十三条生产规则各放一个 compiling
mutant，并对每个 mutant 运行完整 assertion set。既有 range bound order 与 source loop
label contract 继续拥有边界顺序和 jump step，不复制同义规则。

## 六、不做的

- 不提供 refutable pattern 的隐式 filter 语义。它会隐藏数据丢失，并与 `let` 的
  irrefutability 规则分叉。
- 不增加 for 专用 pattern 子文法。第二套 grammar 会立即带来 parser、formatter、LSP
  与文档漂移。
- 不在本批改变迭代顺序、range 端点、步长、labelled break 或容器 Iter 实现。
- 不让 selfhost 立即 dogfood 新语法。该迁移要等包含本特性的 release 成为 seed。
