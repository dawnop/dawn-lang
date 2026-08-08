# `Int.MIN` 直接字面量设计（SYN-08）

> 状态：**current** —— 本文记录 SYN-08 的定稿契约与落地边界。Dawn 的整数仍是有符号
> 64 位；本刀只让其最小值能够用十进制、十六进制和二进制直接写出，不引入无符号整数，
> 也不把 `2^63` 变成可独立存在的值。

## 1. 问题

旧 lexer 在看见负号之前，先把整数 token 的 magnitude 解析成正 `Int`。因此
`9223372036854775808` 会在词法阶段越界，parser 后续再构造 `EUnary(OpNeg, ...)` 已经太晚。
结果是 `Int` 的 2^64 个值里唯独 `-9223372036854775808` 没有直接字面量；const、pattern 与
边界测试只能写成 `-9223372036854775807 - 1`。

不能把所有整数先塞进更宽的宿主类型：JVM 与 native 自举必须共享一条语义，而且编译器本身
只有 `Int`。也不能让越界 token 的 `ival` 临时装一个伪值；那会把内部恢复值误当成语言值。

## 2. 定稿语法与诊断

- 十进制、十六进制、二进制都允许把**精确 magnitude `2^63`** 写在一元负号后：
  `-9223372036854775808`、`-0x8000000000000000`、
  `-0b1000...000`（共 64 位）。
- “直接”指 parser 看见相邻的 `MINUS`、marker 两个 token；空白不产生语法节点，已有的换行
  continuation 规则也不改。括号会隔开二者，所以 `-(9223372036854775808)` 拒绝。
- 裸 `2^63` 不是 `Int`；任何进制中大于 `2^63` 的 magnitude 也不是。裸 marker 固定报告
  `integer literal out of 64-bit range: <text>`，并提示它只可直接跟在一元 `-` 后。
- 非法进制数字与范围溢出是两类错误：例如 `0b2` 报 invalid literal，合法数字组成的
  `0x8000000000000001` 报 out of range。即使非法字符出现在一个已经超长的前缀后，invalid
  仍优先，不能由扫描到哪一步决定诊断类别。
- 负的最小值可以作普通表达式和字面量 pattern；折叠后都是普通 `EInt(Int.MIN)`，后续阶段
  不认识 marker。

## 3. token 与 lexer

`Token` 增加 INT 专用的 `is_min_magnitude: Bool`。所有普通 token 构造器都写 `false`；只有
精确 magnitude `2^63` 的 INT token 写 `true`，并约定此时不得读取 `ival`。`lexdump` 用
`<2^63>` 显示 marker，避免把内部占位值误报成源码的数值。

十进制、十六进制与二进制共用 `parse_magnitude`。它先验证至少有一个数字且每个非下划线
字符都属于 radix，再以负数累加：累计值始终处于 `Int.MIN..0`，所以不需要构造不可表示的
正 `2^63`。结果只有四种：普通值、精确 marker、非法数字、范围溢出。

## 4. parser 与 postfix

表达式 parser 只在一元 `MINUS` 后立即看见 marker 时消费二者，并直接生成
`EInt(Int.MIN)`。裸 marker 在 `primary_expr` 拒绝；pattern parser 使用相同边界，只有
`MINUS` 后的 marker 能生成 `PLit(EInt(Int.MIN))`。

原来的 postfix 循环从 `postfix_expr` 抽成 `postfix_tail`。普通 primary 与刚折叠出的
`Int.MIN` 都进入同一条尾链，因此 `?`、调用、成员和下标等既有 postfix 解析不会因这个
特例被截断。是否通过类型检查仍由 checker 决定，本刀不为 `Int` 新增 postfix 能力。

## 5. C emitter

C 不能可靠地把 `INT64_C(-9223372036854775808)` 当作一个有符号 64 位常量：宏参数先形成
不可由 `int64_t` 表示的正 literal，再应用负号。`int_lit` 因此统一承接两个来源：Core 的
`CInt` 与 comptime 的 `VInt`。普通值输出 `INT64_C(n)`，唯一的 `Int.MIN` 输出标准宏
`INT64_MIN`。

## 6. 可执行契约与负控

- lexer/parser/lexdump 单测钉住三进制边界、非法数字与溢出分流、直接负号、括号隔开、
  pattern、postfix 以及诊断后的声明/臂恢复；新语法在 selfhost 源码中只出现在字符串里，
  保持当前种子可编译。
- grammar corpus 以绝对 accept/reject oracle 钉住三进制正例、裸 marker、括号隔开和
  `2^63 + 1`。
- `scripts/int-min-contract/run.sh` 用书面期望同时检查 JVM/native 输出，并检查生成 C
  同时包含 `INT64_MIN`、不包含错误的 `INT64_C(-9223372036854775808)`；probe 同时经过
  `CInt` 与折叠后的 `VInt` 路径。
- 五类负控已实际见红后恢复：放行裸 marker 时 bare/parenthesized reject 红；把
  `2^63 + 1` 也标成 marker 时 overflow reject 红；把非法 digit 归为 overflow 时精确诊断
  oracle 红；让折叠分支绕过 `postfix_tail` 时 parser selftest 红；让 C emitter 退回普通
  `INT64_C(...)` 拼写时专项 C contract 红。

Core golden 与跨 release Emit 差分只按实测更新或报告，不根据方案预声明。

## 7. 不做的（记录理由）

- **不引入无符号整数或 BigInt。** marker 不是一种值，只是把一元负号所需的唯一 magnitude
  跨过 lexer/parser 边界。
- **不接受裸 `2^63` 后再靠上下文变负。** 类型推断、常量折叠或运算符重载都不应把词法越界
  追溯性改成合法；只有直接一元负号局部可判定。
- **不让括号透明。** 若 `-(2^63)` 也合法，marker 就必须作为越界表达式穿过 group 节点，
  内部状态会泄漏进一般 AST。
- **不改下划线与换行规则。** 三种进制沿用既有分隔习惯，lexer/formatter 的 continuation
  规则不属于 SYN-08。
