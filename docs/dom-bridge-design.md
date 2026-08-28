# DOM 桥：wasm reactor + 纯消息边界

> 状态：**current**。定稿并已落地。`packages/tea-dom` 是 `tea_core` 调和器的第二个消费者，
> `dawnc build --target wasm --reactor` 是它的宿主形态，`scripts/wasm-dom-contract` 是它的门禁。

## 1. 这份文档回答什么

Elm 架构在这个仓库里已经有两半：`packages/tea-core` 是与词汇无关的那半（`Tree` 契约、
调和器、前序遍历、`trait App`、订阅），`packages/tea-term` 是终端那半。终端是调和器契约的
第一个消费者，而契约的价值只有在有第二个消费者时才说得清。

第二个消费者是浏览器。它带来一个终端没有的问题：计算在 wasm 里，文档在 JavaScript 里，
两边要商量出一个边界。这份文档记录那个边界的形状，以及三个决定的理由：为什么是 reactor、
为什么只传消息、为什么不用 `externref`。

实现分布在四个地方：

| 位置 | 是什么 |
|---|---|
| `packages/tea-dom/src` | DOM 词汇、路由、线格式、reactor 的一轮 |
| `packages/tea-dom/js` | 宿主侧：WASI 垫片、reactor 驱动、patch 解释器 |
| `examples/projects/tea_dom_counter` | 跑通整条环路的最小应用 |
| `examples/projects/tea_dom_todo` | 第二个应用：带身份的列表、草稿、模式。§6 的两笔账在它身上是数字 |
| `scripts/wasm-dom-contract` | 无浏览器的确定性转录门禁（两套转录，各带自己的变异体） |

## 2. reactor，不是命令模块

wasm32-wasi 的默认产物是命令模块：导出 `_start`，宿主调一次，程序跑完退出。
这个形状装不下事件循环。页面上的一次点击要走进 wasm 再走出来，而一个跑完就
`proc_exit` 的实例连第二次都进不去。

另一头的做法是把循环放进 wasm：guest 自己等事件。这需要 guest 持有宿主的事件源，
也就需要 guest 持有宿主引用，正是 §4 要避免的东西。

所以是 reactor：模块实例化一次，`_initialize` 跑完 wasi-libc 的构造器，之后宿主每来一条
消息就调一次导出函数。`dawnc build --target wasm --reactor` 做两件事，各一行：

- 链接时加 `-mexec-model=reactor`，于是没有 `_start`，`main` 变成一个普通函数；
- 在发出的 C 末尾追加一段 shim，导出 `dawn_turn`，里面调 `main(0, NULL)`。

追加而不是改发射器，是因为这不是代码生成的变化：现有目标的每一个字节都没动，
`--reactor` 之外的构建走的还是原来那条路径。shim 里唯一不明显的一行是 `fflush(NULL)`：
`dawn_rt_init` 把 stdout 设成全缓冲（native 差分逐字节比较管道里的 stdout，行缓冲会让它
和 stderr 乱序），进程靠退出时冲刷，而 reactor 不退出。每轮冲一次，是 reactor 版的
「那个不会到来的退出」。

`main` 里跑的是 `tea_dom/reactor.serve`，它读一行、答一行、再读，读到输入结束就返回。
宿主每轮只写一行，所以每次 `dawn_turn` 恰好答一条消息。同一个二进制从终端跑起来就是
一个会话，`dawn run` 能驱动它，`scripts/example-main-contract` 因此能在 JVM 上把它钉成
转录，一个浏览器和一个 wasm 引擎都不需要。

## 3. 只传消息

边界上一行 JSON 进，一行 JSON 出。三件事跟着这个决定走。

**应用的消息类型不过界。** 向外传的 patch 里，监听信息只有事件的**名字**，以及监听器
声明要带回来的数据**种类**；向内传的是一个地址、一个事件名，外加至多一个字符串。
宿主叫不出一个消息的名字，也不需要：`tea_dom/route.at` 拿地址和事件名去问**此刻模型
产生的那棵树**，问到的那个监听器自己的 `to_msg` 在 guest 侧把字符串变成消息。于是 `Msg`
是宿主从没听说过的类型，也不需要编解码器。

**事件载荷是闭集。** `Payload` 只有三个值（`NoData`/`Value`/`Key`），
过界的永远是一个 `String`：checkbox 由宿主归一成 `"true"`/`"false"`，整数在 guest 侧
`parse_int`，结构化的东西一概不收——收了就等于把 `json/value.Json` 塞进 `Request`，
把边界拓宽到浏览器 event 对象那么宽，而这恰恰是每一个「guest 与宿主之间真有一根线」的
系统都拒绝做的事。

合并函数**就在**树里，而树仍然有结构相等。Elm 的 `on : String -> Decoder msg` 是一个从
事件到消息的函数，`On[M]` 的 `to_msg: fn(String) -> M` 是同一件东西；`on_value("input",
SetDraft)` 就是全部写法，因为构造子的裸名在 Dawn 里已经是一个 `fn(String) -> M`。
带函数字段的树本来没有结构相等（编译器的原话是 `functions cannot be compared`），而
`==` 是调和器与每一个视图测试的地基。所以 `On` 手写了一份 `impl Eq`，把身份定义成
`(event, payload)`，函数不参与；§9 是这条裁决的完整理由与边界。

一个白拿的好处与一条纪律。种类是树里的数据，于是 `relate` 看见「这个监听器的**读法**变了」
是白拿的一次比较，宿主会被告知重挂；拼错种类是编译错误而不是运行期的 `no-handler`。
纪律是：宿主送来的载荷与监听器声明的不符（该有没有、不该有却有、不是字符串），一律回
`bad-request` 而不是默认或忽略，理由与 `route.at` 答 `None` 时回错误一样，那说明两边看的
不是同一棵树。

这一条动到的只是「消息的**值**可以从树里枚举」，而那从来不是写下来的不变式，只是
「压根没法往页面里打字」的副产品。写下来的那条（宿主叫不出消息的名字）原样成立。

**模型过界，是应用自己编码的不透明文本。** 它必须过界：Dawn 没有模块级可变状态，reactor
两轮之间什么都不留。另一条路是在 guest 侧建一张表、把句柄给宿主，那是反方向的宿主引用，
同样不要。好处比代价大：一轮是它输入的函数，所以同一份转录在 JVM、native 和 wasm 上逐字节
重放，这正是它能被无浏览器测试的原因。

**`SetSelf` 不带子树。** 这不是抄近路，是把契约读细了：`apply` 执行
`rekid(donor, kids(target))`，除了自身数据之外不读捐赠者的任何东西。带上子树会让根节点上
一次 class 变化的代价变成整份文档，而局部性正是 `diff` 存在的理由。`wire.enc_self` 是把这件事
写出来的那个编码器。

一行一条消息的分帧是白拿的：`json/render` 转义每一个 U+0020 以下的码点，所以渲染结果里
不可能出现分隔两条消息的换行。

## 4. 没有 externref

wasm 和 JavaScript 免费共享的只有一段字节。别的一切（一个 JS 对象、一个 DOM 节点、一个
`externref`）都是引用，而跨界持有的引用两边的类型系统都不在追踪它的生命周期。所以 guest
一个都不持有。

这条限制在 Dawn 侧已经有一个更早的版本：树里放消息而不是回调。`tea_term/widget` 的理由是
函数字段会让树失去结构相等，而 `==` 是快照测试和调和器短路的前提。DOM 词汇继承同一条，
理由多一层：一个 `on_click: fn()` 根本没法过界。

## 5. 词汇与契约

`Node[M]` 只有两个构造子：`Text(s)` 和 `Elem(tag, props, on, kids, key)`。终端需要
`Row`/`Column` 是因为终端没有 tag 可变；浏览器的元素就是一个带 tag 的形状。
`on` 的元素是记录 `On { event, payload, to_msg }`，用记录而不是元组，是因为这是监听器
向宿主**声明**东西的位置，载荷种类只是其中第一件：能力位（`prevent`/`passive`）与
宿主本地求值的谓词是同一个声明位，记录加一个字段就行，元组得再破坏一次形状。

`impl Tree[Node[M]]` 与终端那份一样不带 bound，但两边不带的理由不同。`relate` 必须看得见
一对节点之间**每一个**差别，否则 `apply(old, diff(old, new)) == new` 不成立；tag、props
相同而事件名或载荷种类不同的两个元素是不相等的，词汇必须说出来。比较 `on` 曾经需要消息
类型上的 `Eq`（那时监听器里装的是消息值），现在不需要：`Eq[On[M]]` 是手写的，只读那两个
字段。终端没遇到过这件事，因为它携带消息的节点是叶子，`relate` 一律答 `Unrelated`。

`node.dawn` 的 test 块拿一个 19 个元素的语料对每一个有序对问这条往返，语料里那对「只有
事件名不同」、那对「只有载荷种类不同」和那对「只有监听器次序不同」的节点就是这几条比较
的存在理由。语料里**没有**「只有监听含义不同」的那一对，也不可能有：那两棵树是同一棵。

`dsl.dawn` 的书写面在默认参数（#207）落地后重切过一次：除 tag 外每个形参都有默认值，
调用只写自己有的那几项（`el("li", class: "row", kids: [...])`），`div_of` 因此删掉，
`input` 补进来当第五个也是最后一个具名简写。其中只有 `class:` 是糖：它展开成**恰好一个
props 项、且排在最前**，`props` 的其余部分原样保留，也不做去重（同时给 `class:` 和
`("class", ..)` 就出两项）。前置而不是后置是硬要求：props 上线是有序的，视图从前手写
class 时它就在第一位，改成后置会挪动每一份 transcript 的字节。这层是纯书写变化，
`scripts/wasm-dom-contract` 的两份期望文本一个字节都没改。

## 6. 契约对 DOM 缺的东西

第二个消费者的用处就是找出这些。第一条已经落地，第二条仍只登记：

**带 key 的子节点配对：已落地（2026-08-26）。** `diff` 现在按 key 配对子节点：每个子节点
都答 `key` 且互不重复时走键控路径，删中间一行是 1 条 `RemoveKid`，换位是 `MoveKid` 而不是
重建；否则回落下标配对，行为与从前逐字节相同。落地前的账（曾经是本节的登记理由）：50 行的
列表删中间一行要 98 条 patch、24 行被重写，删首行 198 条；键控后各为 2 条，与行数无关。
监听器函数化（§9）之后不键控的那两个数字降到 26 与 51：每个下移的行从 4 条 patch 变成
1 条，因为它的三个监听器现在与上一行的相等。键控的 2 条不变。
这些数字钉在 `packages/tea-dom/src/node.dawn` 的测试里，回归会红。仍然开着的邻账在
`tea_core/diff` 的文件头：键控路径的成员判定是 O(n²)，尾部追加是每子一条 `InsertKid`。

**`diff_step`。** `tea_term/step.diff_step` 就是「一轮，要变化而不要帧」，签名是
`W: Tree + Eq`，里面没有一点终端的东西，但它住在终端的包里。`tea_dom/reactor.turn`
选择把那三行重述一遍，而不是为它依赖 `tea_term`。把它搬到 `tea_core` 是一个包边界的
裁决，不是这一刀该顺手做的事。

第二个应用之后这条要补一句：两份实现今天仍然给同样的答案，但**不是同一个函数**。
`diff_step(m, msg, vw)` 自己算 `vw(m)`，而 `turn` 手里已经有那棵树了（`route.at` 要它来
把地址解成消息），于是重述的那两行复用 `old` 而不是重算。差价可测：1000 行时一次 `view`
加一次前序遍历是 5.1 ms。所以搬家帮不到这个消费者，它的签名收不下「旧树已经在手上」。

## 7. 失败

`serve` 用 `catch_panic` 包住每一轮。应用 panic 时宿主拿到一条 error 回复，手里的模型不动，
下一条消息照常应答。这就是 wasm 失败运行时的消费者：没有 landing 的话，wasm32-wasi 上一个
panic 会中止模块，页面就死了。

`scripts/wasm-dom-contract` 的 `no-catch` 变异体把这条链拆开验过：去掉边界上的 catch 之后，
同一次点击的回复变成 `{"ok":false,"kind":"aborted"}`，那是 guest 调了 `proc_exit`、
垫片抛出、实例作废。

回复里的 `kind` 归一成 `panic` 而不是原样透传，因为 `e.kind` 在 JVM 上是
`dawn.rt.PanicError`、在 C 运行时上是 `panic`，而一个随后端变化的边界没法有一份转录。
`catch_panic` 只接 panic，所以这个词没有丢掉任何信息。

## 8. 门禁

`scripts/wasm-dom-contract/run.sh` 把整条环路（reactor、消息边界、patch 流、DOM 变更、
事件路由）跑在一个记录型 document 桩上，逐字节比对两份转录。计数器那份 120 行，
里面有四种行，各回答一个问题：
`request`/`reply` 是过界的字节，`patch` 是 op 和地址（这是局部性变成可断言的地方），
`dom` 是桥对文档做了什么，`tree` 是文档随后是什么。

请求行里的地址是桥从被点中的元素**走回来**算出来的（脚本是按标签找按钮再点它），所以
路由错会表现为请求行不对。计数器那份的七个变异体逐个说明这些断言有牙：

| 变异体 | 改的是 | 转录怎么变红 |
|---|---|---|
| `truncate-off-by-one` | `dom.mjs` 的 truncate 多留一个子节点 | 只有 `tree` 行不对，没有异常 |
| `patch-kind` | `set-self` 当成 `replace` 解释 | 运行失败 |
| `patch-order` | patch 逆序应用 | `dom` 行顺序不对 |
| `event-address` | 地址回溯写成 push 而非 unshift | `request` 行的地址不对 |
| `setself-payload` | `enc_self` 换成 `enc_node` | 只有 `reply` 行变长 |
| `payload-ignores-kind` | 宿主无视声明的种类，一律读 `value` 送过来 | `request` 行多出 `payload`，guest 回 `bad-request` |
| `no-catch` | 去掉边界上的 `catch_panic` | 回复变成 `aborted` |

第二份转录（`transcript-todo.mjs` / `expected-todo.txt`，455 行）驱动
`examples/projects/tea_dom_todo`：五个待办、一次筛选、一次就地编辑、一次中间删除、一次
panic、一次落空的事件。它多一种行 `state`，即根的 class、编辑框的 `value`、`<ul>` 子树与
状态行——那是每一轮真正在变的东西，整份文档每轮全打一遍只会把变了的行埋在重复的标题与
筛选条里；整份文档在 init 后打一次，而 init 之后的 `dom` 行是不过滤的，所以「没动过的
区域不该被动过」仍然是可断言的。它自己的两个变异体（`todo-msg` 让行内编辑器的监听器指向
composer 的草稿消息、`todo-filter` 让 done 筛选放行一切）都改在应用里而不是桥里：
改桥的变异体两份转录一起红，说明不了第二份有没有牙。`todo-msg` 顺带说明 §9 的商同余相等
在这里没花掉门禁的牙：改前改后那两个监听器是相等的，patch 流一个字节都不动，红的是模型
与文档。

那个应用原本用一块 28 键的按钮键盘打字，因为边界带不了 `ev.target.value`。载荷落地后它
换成两个受控 `<input>`，账面是：init 回复 4125 B → 1247 B（−70%）、节点 77 → 19（−75%）、
init 的 DOM 变更 228 → 55（−76%），而打一个标题从「每字符一轮」变成一轮。**没有**变的是
中间删除那一轮：仍是 17 条 patch，因为那笔账是配对方式的，不是输入法的。监听器函数化
（§9）之后这一轮是 11 条：走掉的 6 条全是「监听器含义变了」的 `set-self`，而整份转录的
298 行 `dom` 一行都没少，`state` 与 `tree` 也逐字节相同。那 6 条从来没让宿主做过任何事。

转录之前还有三套只要 node 的检查，各带自己的变异体，因为它们钉的东西转录看不见：
`keyed-ops.sh` 驱动两个应用都不会走到的三个 op；`payload.sh` 驱动两个应用都不声明的那些
载荷路径（`key`、checkbox 归一、种类变了要重挂监听器、以及那个有条件的 `preventDefault`）；
`props.sh` 驱动 `value`/`checked` 的属性写。最后这套钉的是 WHATWG 的 dirty value flag——
用户打过字之后，`value` 这个内容特性就不再写进用户看到的那个值，于是一个只会 `setAttribute`
的桥把模型渲染进输入框**只有一次**，之后模型再也改不动它，而且不抛异常：patch 流是对的、
document 对象是对的，只有屏幕是错的。
桩里那个带 dirty 标志的 `StubInput` 就是为了让这件事有地方红。

`scripts/wasm-contract`（失败运行时那套）和这一套共用一个 CI job，因为它们共用两件贵的
东西：钉了版本与 sha256 的 wasi-sdk，以及从 `selfhost/src/nmain.dawn` 构建的 C 驱动。

wasi-sdk 钉在 34。到 30 为止，现有的 `--target wasm` 链接命令行不加改动就能用；
31 及以后（LLVM 22）链不动任何 `-fwasm-exceptions` 的产物，报
`undefined symbol: __cpp_exception`。那个 exception tag 从前在每个用得着它的目标文件里
都发一份 weak 定义，上游把它挪进了 libunwind，链接命令行于是不再定义它。上游给的修法是
链 `-lunwind`（tag 在 libunwind.a 的 `Unwind-wasm.c.o` 里，CppExceptions.md 就是这么写的），
但那个库只存在于 sysroot 33 及以后，一加就把 33 以前的每一套工具链连同 apt 那条路一起断掉。
这里改成运行时自带这个 tag：`runtime/c/dawn_rt_wasi_tag.c`，内容是 libunwind 那段内联汇编的
副本。它必须是一个自己的编译单元，理由写在该文件开头，LLVM 21 及更早的后端仍会给任何抛或接的
编译单元发一份 weak 定义，同一个单元里再放一份强定义就是汇编器错误。

三元组是另一半，与异常无关：31 把 wasm32-wasi 标为废弃，34 直接删掉了这个 target；
反方向上 apt 的 wasi-libc 只铺了 wasm32-wasi，没有 wasm32-wasip1。没有哪一个写死的拼法
能同时够到两端，所以 `cc_build_for` 不写死，而是问编译器手上有哪一个的 sysroot
（`-print-file-name=crt1.o` 给绝对路径就是有，原样回显文件名就是没有），apt 那条备用路因此还活着。
代价是 clang 18 不再够用：它的汇编器在那段 tag 汇编上会崩，要 clang 20 或更新。

有了这两件，25、27、29、30、31、33、34 全都能构建，产出的 DOM 转录逐字节相同，
所以这个钉子仍然是关于工具链的选择，不是关于答案的。选 34 是因为它最新，而且它是 LLVM 23：
逼着失败运行时走 A1 影子栈的那个 isel 崩溃（`dawn_rt.c` 的 "landing at a handler"）在它上面
没有了，将来要撤影子栈得从这个钉子过。

## 9. 监听器函数化：`On` 装函数，相等按线上身份取商

`On` 从 `{ event, payload, msg: M }` 变成 `{ event, payload, to_msg: fn(String) -> M }`，
`trait Fill` 连同应用里的每一个 `impl Fill` 一起删掉。这一节记录为什么、代价在哪、
以及那条不能被读大的裁决。

### 9.1 问题：一次带值的交互要记四遍

带值的监听器从前的写法是「留一个洞」：视图里写 `on_value("input", SetDraft(text: ""))`，
那个空串是个占位符，宿主把真正的字符串带回来之后由 `fill` 倒进洞里。于是一次带值交互
要在四个地方登记：`Msg` 的构造子、`update` 的臂、留洞的监听器、`Fill` 的臂。第四个是
纯粹的簿记：它说的事情（`SetDraft` 的洞收 payload）在第三个地方已经说过一遍了，只是
说的是值不是函数，所以要再写一遍才能把两者接上。

`Fill` 的默认方法体是 `= m`，于是不带值的应用还要写一行 `impl Fill[Msg] { }`，一条
什么都不做的声明，只为让 `turn` 的 bound 满足。

监听器装函数之后，第三、第四两处并成一处：`on_value("input", SetDraft)`。构造子的裸名
在 Dawn 里已经是一个 `fn(String) -> M`，所以带值的应用一个字的胶水都不用写，不带值的
应用什么都不用声明。

### 9.2 线和宿主一个字节都没动

这不是一次边界改动。向外传的监听信息一直只有两样东西：事件名，以及监听器声明的载荷
种类（`wire.jevent`，`packages/tea-dom/src/wire.dawn`）。向内传的一直是地址、事件名、
至多一个字符串。宿主从来没见过 `msg`，也就没有东西可以从它面前拿走。

`packages/tea-dom/js` 一行没改，这一点是验过的而不是推的：计数器那份转录 120 行逐字节
相同，待办那份 298 行 `dom`、19 行 `state`、`tree` 行全部逐字节相同。

### 9.3 裁决：`On` 的相等就是它的线上身份

**`Eq[On[M]]` 比较 `(event, payload)`，`to_msg` 不参与。** 这是一份手写的 `impl`
（配套 `impl Hash` 读同样两个字段），不是 derive，理由有三层：

1. 宿主被告知的全部就是这两样（§9.2），patch 能携带的关于一个监听器的全部也是这两样。
2. 派发不查旧树。事件到达时 `route.at` 拿地址和事件名去问**此刻**模型产生的那棵树，
   跑的是那棵树里的 `to_msg`。宿主手上挂着的监听器是按事件名挂的，跟消息无关。
3. 于是「(event, payload) 相同的两个 `On`」对宿主、对 patch 流、对派发三者都不可分辨。
   对它们答「相等」不丢任何信息。

这是**有意取的商**：消息函数是行为，不是身份。

**边界。** 这不是「给函数定义相等」，这里和别处都没有比较过任何函数：`to_msg` 是被
排除在身份之外，跟「比得不对」是两回事。相等仍然自反、对称、传递，因为它就是一对普通
值上的 `Eq`。让出去的是「消息的**值**可以被树的 `==` 看见」：从前一个测试可以拿
`view(m) == 期望的树` 顺带断言「这个按钮现在意味着 `Drop(2)`」，现在不行了。

### 9.4 测试得到什么、失去什么

失去的就是上面那一条：树的 `==` 看不见消息内容了。补上它的是**派发层的断言**，
`node.deliver(listener, payload) -> M` 是那个入口，等于 `settle` 减去载荷种类的校验：

```dawn
assert deliver(on_value("input", SetDraft), "buy milk") == SetDraft(text: "buy milk")
```

得到的是这种断言比从前的强。从前「消息对不对」是靠整棵树相等顺带断到的，一次断言里
混着 tag、props、children 和消息；现在是直接问「事件 `ev` 带着 `p` 落在这个监听器上会
产生哪个消息」，答案就是消息本身。`route.dawn` 因此多了一条测试：地址解析到的监听器
「意味着」什么。从前那几条 `at(...) == Some(hear("click", Ping))` 在商同余相等下已经
不能区分消息了，把整棵树的监听器全接到同一个消息上也能全绿。

一笔顺带的账：不键控的列表删中间一行，50 行时从 98 条 patch 降到 26 条（§6）。走掉的
那些是「监听器含义变了」的 `set-self`，而它们携带的字节与宿主手上已有的逐字节相同。
换句话说，那些 patch 从前就是白发的，商同余相等只是让调和器不再发它们。

### 9.5 两处实现上的记账

**`Node[M]` 的 `Eq`/`Hash` 也改成手写了**，`packages/tea-dom/src/node.dawn` 里写了理由。
一是语言的：合成的 `Eq` 会向 ADT 的每一个类型参数要 bound，不管那个参数是否真的到达了
可比较的位置，而 `M` 到不了（它只出现在 `On[M]` 底下，而 `On` 的 `Eq` 只读两个字段）；
写出这个 impl 才让 `turn`/`serve`/`impl Tree` 三处的 `M: Eq` 全部去掉。二是编译器的：
JVM 后端在「合成的 `Eq` 的结构里够到了一条**条件用户 impl**」这条路径上会发出一个
构造函数是 private 的字典类，需要它的模块在第一次于刚性 `M` 上比较时就死于
`tried to access private method ... <init>`，而 `turn` 正是这样一个调用点。这条待修，
修好之后手写的 `Eq[Node[M]]` 可以删回 derive。

手写 `Eq` 换来一个新的失手方式：漏掉 `Elem` 的某个字段，而往返契约
`apply(old, diff(old, new)) == new` 对此是瞎的（它用的是同一个瞎了的 `==`）。
`node.dawn` 因此多了一条测试，逐字段各给一对「只差这个字段」的节点，`==` 和 `hash`
都得看见。
