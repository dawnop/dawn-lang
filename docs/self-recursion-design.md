# 无条件自递归是编译错误

> 状态：**current**。规则、实现位置与实测。

## 1. 问题

一份 std 原型里写了 `impl Len[List[T]] { fn len(xs) = len(xs) }`。impl 体内，方法名
`len` 解析到方法自身（impl 体内的方法名遮蔽 prelude 的同名函数），checker 接受了它；
编出来的程序在 `-Xss512m` 下无限递归，吃掉约 19 GB，本机因此崩了两次。
最小复现：

    pub type Box = { n: Int }
    impl Len[Box] {
      fn len(b: Box) -> Int = len(b)
    }

这不是 `len` 特有的：任何 impl 方法与 prelude/导入函数同名，而作者想调的是后者时，都是这个形状。
`fn f(x) = f(x)` 是同一个缺陷的最朴素形式。

## 2. 规则

**一个函数或 impl 方法，若它的体在每一条控制路径上、返回之前都调用了自己，是编译错误**：

    unconditional recursion: function `f` calls itself on every path and never returns
    unconditional recursion: method `len` calls itself on every path and never returns

位置是那次自调用，hint 说怎么办（加一个不自调用就返回的分支；impl 内则提醒同名的
prelude/导入函数在此被遮蔽）。

「自己」是**同一个已解析的符号**，不是同一个拼写：同模块、同名；impl 方法还要求同一个 trait，
且调用的 witness 主体与 impl 主体吻合（泛型 impl 的主体记作 `List[?]`，任何实例都是同一个方法）。
所以另一个模块的同名函数、同 trait 同名方法在**另一个类型**上、局部同名 `fn`，都不算。

「无条件」按 Rust 的定义：`unconditional_recursion` lint 报「function cannot return without
recursing」（<https://doc.rust-lang.org/rustc/lints/listing/warn-by-default.html>），
即从入口到返回的每条路径都经过一次自调用。实现的读法：

- `if`/`match` 的所有分支都自调用才算；有一个分支不自调用就返回，则不报。
- 返回之前的 `return`、`?` 是出口；`while`/`for` 的体可能一次也不跑；`&&`/`||` 的右侧可能不跑。
- lambda 体、局部函数体不在写下的地方求值，不能提供自调用。
- 调用带效果行的函数（含效果操作）可能被 handler 中止，算出口：
  `fn skip(p) !Fail = { expect(p); skip(p) }` 靠 `expect` 失败结束，不报。
- 一路 panic（类型 `Never`）的路径不是「返回」路径，与 Rust 一致。

**范围之外**：互递归（`even`/`odd` 互相调用）。要判它需要调用图上的不动点，且「每条路径」的
论证跨函数后很快失真；本刀只管函数体里直接可见的自调用。

## 3. error 还是 warning

error。`front/diag.dawn` 的 Diag 不带 severity，LSP 一律 `severity: 1`，`dawn check` 有诊断即
退出 1：Dawn 只有一种诊断等级，[unused-imports-design.md](unused-imports-design.md) §2 已经为此
立过先例，本刀不新增第二种。误报代价（正确程序编不过）靠「只往漏报一边错」约束：
任何不理解的构造都读作「这条路径可能不经自调用就离开」。

## 4. 在哪里跑

checker 末尾，`execute_module_bodies` 里 `report_unused_imports` 之前，读已检查的 typed 树
（`check/selfrec.dawn`）。不用语法遍历：`len(b)` 是不是方法自身是名字解析的结论，语法里同一个
拼写可能是 prelude 函数、导入或方法；typed 的 `XCallFn` 带着解析后的 owner、名字、trait 与 witness。
不放 Core IR pass：到 Core 时诊断已无源码位置的归属与 `dawn check` 的出口，且 impl 的主体信息已被抹平。
和未使用导入一样，**模块已有其它诊断时不报**（带 `XError` 的体上的结论不可信）；因此它排在未使用导入前，
会让同一模块的未使用导入诊断让位给它，这是可接受的。

trait 默认体与 test 不看：默认体里的 `m(x)` 是经 witness 的调用，不是对自己；test 没有调用者。

## 5. 实测

- 全仓无新增诊断：`dawn check` selfhost、std、site、playground、compiler-plan、
  `packages/*` 十一个包、`examples/projects/*` 九个项目、`dawn test --stdlib`（230 项）全部通过，
  零处命中，没有需要压制的真实代码。
- selfhost 自检墙钟（`dawn check selfhost`，直接用两份 jar 交替各 6 次，同一负载下）：
  无此遍 5.41–5.53 s（均值约 5.48 s），有此遍 5.35–5.55 s（均值约 5.45 s）；
  用户态 CPU 15.18 s 对 15.40 s，差在噪声之内。遍历是对每个函数体的一次线性扫描。

## 6. 落点

`selfhost/src/check/selfrec.dawn`（遍）；`checker.dawn` 一行接线与内联 test；
`scripts/checker-corpus/cases/self_recursion*`（golden：四条应报、若干形似而不报的，
外加一个跨模块同名的负例）。

## 7. 不做的（理由）

- **互递归**：见 §2，需要调用图不动点，且收益远小于直接自调用；另开设计再说。
- **warning 档**：Dawn 只有一种诊断等级（§3）。
- **把「impl 内同名方法遮蔽 prelude」本身改掉**：那是名字解析规则，spec 与 `Len` trait 的裁决依赖它
  （impl 体内的方法名不遮蔽模块顶层，但在体内是可见的）；本刀只让踩到它的后果在编译期可见。
- **证明函数终止**：这不是终止检查器；`fn f(n) = f(n - 1)`（没有基础分支）会报，
  `fn f(n) = if n > 0 { f(n - 1) } else { f(n + 1) }` 也会报，而带分支但永不到达基础分支的函数不会报。
- **把「调用带效果的函数」之外的 panic 当出口**：与 Rust 一致，panic 路径不是返回路径。
- **spec 条文**：规则暂只在本文与诊断文本里，等第二次引用时再写进 spec §3。
