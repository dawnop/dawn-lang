# DOM 桥：wasm reactor + 纯消息边界

> 状态：**current** —— 定稿并已落地。`packages/tea-dom` 是 `tea_core` 调和器的第二个消费者，
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
| `scripts/wasm-dom-contract` | 无浏览器的确定性转录门禁 |

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

**应用的消息类型不过界。** 向外传的 patch 里，监听信息只有事件的**名字**；向内传的是
一个地址加一个事件名。宿主叫不出一个消息的名字，也不需要：`tea_dom/route.at` 拿地址和
事件名去问**此刻模型产生的那棵树**。于是 `Msg` 是宿主从没听说过的类型，也不需要编解码器。

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

`Node[M]` 只有两个构造子：`Text(s)` 和 `Elem(tag, props, on, kids)`。终端需要 `Row`/`Column`
是因为终端没有 tag 可变；浏览器的元素就是一个带 tag 的形状。

一处非做不可的偏离：impl 是 `impl[M: Eq] Tree[Node[M]]`，终端那份是 `impl[M] ...`。
`relate` 必须看得见一对节点之间**每一个**差别，否则 `apply(old, diff(old, new)) == new` 不成立。
tag、props 和事件名都相同、只有某个事件的**含义**不同的两个元素是不相等的，词汇必须说出来，
而比较 `on` 需要消息类型上的 `Eq`。终端没遇到这件事，因为它携带消息的节点是叶子，
`relate` 一律答 `Unrelated`。

`node.dawn` 的 test 块拿一个 18 个元素的语料对每一个有序对问这条往返，语料里那两对
「只有监听含义不同」的节点就是这个 bound 的存在理由。

## 6. 契约对 DOM 缺的东西

第二个消费者的用处就是找出这些。两条都只登记，没有绕过：

**带 key 的子节点配对。** `diff` 按下标配对子节点，中间删一个会把后面整条尾巴逐位重写。
在终端里那是一次重绘；在 DOM 里那是把删除点之后每个节点的元素状态（焦点、选区、正在播放的
视频）全部丢掉。`tea_core/diff` 的文件头已经写明 key 需要哪三个 op、以及它们的载荷
（`Int` 和 `W`）不需要契约里没有的东西。这里只是记下：想要它的消费者出现了。

**`diff_step`。** `tea_term/step.diff_step` 就是「一轮，要变化而不要帧」，签名是
`W: Tree + Eq`，里面没有一点终端的东西，但它住在终端的包里。`tea_dom/reactor.turn`
选择把那三行重述一遍，而不是为它依赖 `tea_term`。把它搬到 `tea_core` 是一个包边界的
裁决，不是这一刀该顺手做的事。

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
事件路由）跑在一个记录型 document 桩上，逐字节比对 120 行转录。转录里有四种行，各回答一个问题：
`request`/`reply` 是过界的字节，`patch` 是 op 和地址（这是局部性变成可断言的地方），
`dom` 是桥对文档做了什么，`tree` 是文档随后是什么。

请求行里的地址是桥从被点中的元素**走回来**算出来的（脚本是按标签找按钮再点它），所以
路由错会表现为请求行不对。六个变异体逐个说明这些断言有牙：

| 变异体 | 改的是 | 转录怎么变红 |
|---|---|---|
| `truncate-off-by-one` | `dom.mjs` 的 truncate 多留一个子节点 | 只有 `tree` 行不对，没有异常 |
| `patch-kind` | `set-self` 当成 `replace` 解释 | 运行失败 |
| `patch-order` | patch 逆序应用 | `dom` 行顺序不对 |
| `event-address` | 地址回溯写成 push 而非 unshift | `request` 行的地址不对 |
| `setself-payload` | `enc_self` 换成 `enc_node` | 只有 `reply` 行变长 |
| `no-catch` | 去掉边界上的 `catch_panic` | 回复变成 `aborted` |

`scripts/wasm-contract`（失败运行时那套）和这一套共用一个 CI job，因为它们共用两件贵的
东西：钉了版本与 sha256 的 wasi-sdk，以及从 `selfhost/src/nmain.dawn` 构建的 C 驱动。

wasi-sdk 钉在 29 而不是最新，是实测的结果：wasi-sdk 33（LLVM 22）链不动任何
`-fwasm-exceptions` 的产物，报 `undefined symbol: __cpp_exception`，那个 exception tag 从前由
后端定义、现在要从 libc++abi 来。29 是现有链接命令行不加改动就能用的最新一版。25、27、29
产出的 DOM 转录逐字节相同，所以这个钉子是关于工具链的选择，不是关于答案的。
往上抬需要一个把 tag 还回来的 wasi-sdk，或者一条点名 libc++abi 的链接命令行，
那是失败运行时的主人该裁的事。
