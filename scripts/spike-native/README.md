# native 接缝 spike(Phase −1)

回答一个问题:[`docs/native-backend-plan.md`](../../docs/native-backend-plan.md) 的 codegen 接缝
**真的是「`TModule` + 语义表进,目标文本出」吗**,以及 `发 C → cc → 跑` 这条工具链链路通不通。

```bash
./scripts/spike-native/run.sh                      # 默认跑 hello.dawn
./scripts/spike-native/run.sh path/to/prog.dawn    # 换个程序
```

脚本把同一个程序在两个后端各跑一遍,`diff` 它们的 stdout。**结论:逐字节一致。**

## 组成

| 件 | 说明 |
|---|---|
| `selfhost/src/emitc.dawn` | TAST → C 发射器,只覆盖平凡子集,其余 `panic` 报节点名 |
| `runtime/c/dawn_rt.{h,c}` | 极小运行时:标量、`dawn_str`(UTF-8 + 字节长度)、stdout、panic |
| `hello.dawn` | 语料:递归/循环/break/continue/短路/位运算/字符串比较与插值/Unicode |
| `run.sh` | 两后端对拍 |

入口是隐藏命令 `dawn __emitc <file> -o <out.c>`,与 `__lex`/`__parse`/`__check` 同族。

## 覆盖面(以及为什么就到这)

**在内**:顶层函数、`Int`/`Float`/`Bool`/`String`/`Unit`、算术与位运算、比较、短路、
`if`/`while`/`for i in a..b`/`break`/`continue`/`return`、字符串字面量与插值、`panic`。

**在外**(碰到就 `panic`):ADT、闭包、trait 字典、集合、comptime const、`use java`、`match`。
这不是偷懒——**Phase −1 的价值在于不踏进没有 oracle 的地带**。上面这些每一样都要等 Core IR(Phase 0)。

## 三个结论

**一、接缝成立。** `emitc.dawn` 只吃 `(class_name, TModule)`,没碰 `Adts`/`Traits`/`impl_table`——
平凡子集用不上它们。真正的 `emit_c` 会用,但形状确认了:**换后端换的是 `emit_module` 的返回类型,
不是它的入参。**

**二、表达式→语句的下降没有意外。** Dawn 是表达式语言,C 是语句语言。标准的「发进临时变量」手法
足够:`emit_expr(st, e) -> (CSt, String)` 往缓冲区追加语句、返回一个 C 表达式串。唯一需要特殊处理的是
`&&`/`||`——右侧可能要发语句,所以不能用 C 的 `&&`,得降成 `if`。

**三、抓到一个真 bug,而且它是给 Core IR 的一条设计输入。**

第一次跑,Unit 返回函数里的**最后一句 `println` 整个消失了**。根因:`emit_expr` 返回的是一个
*C 表达式串*,调用方若不把它写进输出,那次调用就从未发生。函数返回 `Unit` 时我直接写了 `return DAWN_UNIT;`,
把尾表达式的串丢了——**连同它的副作用**。

同样的漏在 `while`/`for` 的循环体、`if` 的 Unit 分支上各有一处。修法是引入 `discard(st, v)`,
所有丢值的地方都必须过它。

> **给 Core IR 的输入**:这个 bug 之所以可能,是因为「表达式的值被丢弃」这件事在 TAST 里**没有节点**,
> 全靠每个消费者自觉。Core IR 应该把语句/表达式边界**显式化**(比如一个 `CDrop` 节点),
> 否则第二个后端会把同一个 bug 再犯一遍——而且这次没有第一个后端可以对拍。

## 已知的不对等(有意留下)

- **Float 的 `to_string` 不逐字节等于 Java**。Java 出的是最短往返形式,`%.17g` 不是。语料因此不含
  Float 打印;真发射器要带一个 dtoa。
- **不释放内存**。`dawn_str_concat` 每次 malloc,永不 free。Perceus 是 Phase 4 的事,
  现在猜一个方案只会白猜。
- **`panic` 直接 `exit(1)`**,没有 setjmp/longjmp,所以 `catch_panic` 不存在。Phase 3 补。
- **名字混淆是有损的**:`sanitize` 把非 `[A-Za-z0-9_]` 折成 `_`,不同 Dawn 名字可能撞车。
  真发射器需要一张表。
