# native 差分测试(Phase −1 spike → Phase 5 的第一道验收门)

同一个 Dawn 程序在两个后端各跑一遍,`diff` stdout。

```bash
./scripts/spike-native/run.sh                      # 跑全部语料
./scripts/spike-native/run.sh path/to/prog.dawn    # 只跑一个
```

它起初是 Phase −1 的接缝 spike(TAST 直接发 C,平凡子集),现在 `emitc` 已改吃 **Core IR**,
语料也压到了 `match`/ADT/`?`/`!`。**当前状态:两个语料全部逐字节一致。**

## 组成

| 件 | 说明 |
|---|---|
| `selfhost/src/core.dawn` | Core IR 节点集 |
| `selfhost/src/lower.dawn` | TAST → Core(糖在这里死) |
| `selfhost/src/emitc.dawn` | Core → C |
| `runtime/c/dawn_rt.{h,c}` | 运行时:标量、`dawn_str`(UTF-8+字节长度)、`dawn_adt`(tagged union)、装箱槽、stdout、panic |
| `hello.dawn` | 语料一:递归/循环/break/continue/短路/位运算/字符串/Unicode |
| `adt.dawn` | 语料二:match 决策树/守卫/嵌套模式/ADT/`?`/`!`/元组/从 match 臂里 break |
| `run.sh` | 差分 harness |

入口是隐藏命令 `dawn __emitc <file> -o <out.c>`,与 `__lex`/`__parse`/`__check` 同族。

`-Werror` 是**真门禁**不是洁癖:Core 的类型错到 C 里,先表现为 int-from-pointer 警告,
远早于表现为算错答案——模式绑定的类型 bug 就是这么抓到的。

## 覆盖面(以及为什么就到这)

**在内**:顶层函数、`Int`/`Float`/`Bool`/`String`/`Unit`、算术与位运算、比较、短路、
`if`/`while`/`for i in a..b`/`break`/`continue`/`return`、字符串字面量与插值、`panic`、
**ADT 构造与字段读、match(含守卫、嵌套模式、字面量模式、元组模式)、`?`、`!`、元组**。

**在外**(碰到就 `panic` 报节点名):闭包、trait 字典、集合、comptime const、`use java`。
最后一个不是缺口而是设计——`use java` 正是 FFI 里不可移植的那一半,native 后端**应该**拒绝它。

## 三个结论

**一、接缝成立。** 换后端换的是 `emit_module` 的返回类型,不是它的入参。而 Core IR 落地后更进一步:
`emitc.dawn` 连 `Adts`/`Traits`/`impl_table` 都不需要——构造器布局、判别式、字段类型全部已经烘进 Core。

**二、表达式→语句的下降没有意外。** Dawn 是表达式语言,C 是语句语言。标准的「发进临时变量」手法
足够:`emit_expr(st, e) -> (CSt, String)` 往缓冲区追加语句、返回一个 C 表达式串。唯一需要特殊处理的是
`&&`/`||`——右侧可能要发语句,所以不能用 C 的 `&&`,得降成 `if`。

**三、抓到一个真 bug,而且它是给 Core IR 的一条设计输入。**

第一次跑,Unit 返回函数里的**最后一句 `println` 整个消失了**。根因:`emit_expr` 返回的是一个
*C 表达式串*,调用方若不把它写进输出,那次调用就从未发生。函数返回 `Unit` 时我直接写了 `return DAWN_UNIT;`,
把尾表达式的串丢了——**连同它的副作用**。

同样的漏在 `while`/`for` 的循环体、`if` 的 Unit 分支上各有一处。修法是引入 `discard(st, v)`,
所有丢值的地方都必须过它。

> **给 Core IR 的输入(已采纳)**:这个 bug 之所以可能,是因为「表达式的值被丢弃」这件事在 TAST 里
> **没有节点**,全靠每个消费者自觉。Core IR 因此有了 `CSDiscard`,由 lowering 显式产生,
> 后端不可能忘。

## 四、Core IR 落地后又抓到两件

**`CSLoop` 需要一个 `step` 字段。** 最初 `for` 的自增放在循环体末尾——于是 `continue` 会跳过它,
循环永不终止。把 step 做成节点的字段(正好是 C 的 for 第三子句),这件事就不再是每个后端各自的坑。

**`CBreak` 必须点名它要离开哪个循环。** `match` 降级成一个「只走一遍的循环」,而用户写在 match 臂里的
`break` 要离开的是**外层的源码循环**。两个 break 同时存在,所以 break 不能是「最内层」的意思。
C 侧因此用 `goto` 而不是 `break` 实现。语料 `adt.dawn:first_shape_over` 专门压这一条。

## 已知的不对等(有意留下)

- **Float 的 `to_string` 不逐字节等于 Java**。Java 出的是最短往返形式,`%.17g` 不是。语料因此不含
  Float 打印;真发射器要带一个 dtoa。
- **不释放内存**。`dawn_str_concat` 每次 malloc,永不 free。Perceus 是 Phase 4 的事,
  现在猜一个方案只会白猜。
- **`panic` 直接 `exit(1)`**,没有 setjmp/longjmp,所以 `catch_panic` 不存在。Phase 3 补。
- **名字混淆是有损的**:`sanitize` 把非 `[A-Za-z0-9_]` 折成 `_`,不同 Dawn 名字可能撞车。
  真发射器需要一张表。
