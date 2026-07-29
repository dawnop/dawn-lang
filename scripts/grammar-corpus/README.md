# 语法 accept/reject 语料（TEST-04）

`docs/grammar.ebnf` 自 2026-07-25 标为 **historical**——手工维护第二份近似语法必然
再次过期，而它过期的方式最糟：读起来仍然可信。当时写下的出路是两条，
「要么从 parser 的 production 生成，要么纳入 accept/reject corpus 测试」。
这里是第二条。

## 它检查什么，不检查什么

**检查**：parser 对**写下来的**期望负责。每个 `accept/` 文件必须零诊断解析通过；
每个 `reject/` 文件必须被拒绝，**且理由要对**——首行 `# expect: <子串>` 钉住诊断文本，
所以一个因为别的原因失败的用例不算通过（否则语料会在语法演化中静默退化成
「只要报错就行」）。

**不检查**：EBNF 文本本身。没有机器能把散文式的 EBNF 与 parser 对齐——
本语料的作用是把 EBNF 想表达的规则变成可执行的形式，于是 EBNF 与实现分叉时，
分叉点会以一个失败用例出现在这里，而不是等人读出来。每个文件的头注释写明它
对应哪条 production（或哪条 spec 条款），这样两边都能被人查。

**只到语法**：用的是 `dawn __parse`，不做类型检查。`accept/` 里的程序不必有意义，
只须合法；类型层面的期望属于 selfhost 的内联 test 与 spike 语料。

## 跑

    ./scripts/grammar-corpus/run.sh
