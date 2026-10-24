# Playground 接 `@codemirror/lsp-client`：分刀与内置补全表懒加载

> 状态：**current**。刀 1（本文 §3，内置补全表懒加载）、刀 2（§4，会话核心 + sanitizeHTML）刀 3（§5，signatureHelp 放行，PR #728）刀 4（§6，references 放行，PR #729）与刀 5（§7，rename 放行，PR #731）已落地；五刀全部完成。
> 依据：内部裁决「Playground 编辑器不换 Monaco」（2026-10-04）第 3 条 b、c，
> 与其后的 `@codemirror/lsp-client` 调研（2026-10-05，下称「调研」）。

## 1. 为什么要分刀

调研的结论是：`@codemirror/lsp-client@6.3.0` 能接上本仓网关与真 `dawn lsp`（initialize、
didOpen、hover、completion、definition、`$/cancelRequest`、didClose、诊断全部走通），
但它接管不了 completion（丢 `item.data`，没有 `completionItem/resolve`，也不做内置表兜底合并），
诊断也只接管一半（`/api/check` 回落、3 s 超时、旧诊断保留是产品逻辑）。真正的收益是
signature help 浮层、references 面板、rename 对话框三块白送的 UI，代价是首屏
**+20.1 KiB gzip（四项）到 +23.0 KiB gzip（全套）**，其中 `marked` 一家 11.5 KiB（调研 §2 实测）。

所以先腾体积，再换核心，最后逐个放行特性。每刀单独可回退，每刀都有自己的判据。

## 2. 刀序与判据

| 刀 | 内容 | 判据（全部满足才算完） |
|---|---|---|
| 1（本刀） | 内置补全表只在 LSP 不可用时动态 `import()` | 首屏 `playground.js` gzip 实测下降，数字写进提交信息；LSP 未连上、断线、请求失败时补全仍给出 builtin（`println`、`str.trim`），且有负控证明表被删掉时测试会红；LSP 在线时不拉表；站点生成器把分出的 chunk 指纹化并改写 import，拼写变了就停构建 |
| 2（已落地，§4） | 换会话核心：`LSPClient` + 自写可重连 Transport；hover、definition、诊断迁过去；补全源、inlay、semantic tokens 改挂 `LSPPlugin`；同刀配 `sanitizeHTML` | `selftest.ts` 与 `lsp_contract.py` 的假子进程先对拍再切；合约（落在前端自测，见 §4.3）里放 `## <img src=x onerror=...>` 变异负控，消毒删掉时必须红；首屏净增量不超过本刀省下的量；网关零改动 |
| 3（已落地，§5，PR #728） | signatureHelp 放行（网关白名单与宣告） | 回包字段白名单与长度上限；`playground/test/contract.sh` 增一项 |
| 4（已落地，§6，PR #729） | references 放行 | 回包只留本 buffer 位置（照 definition）；同刀改写 `docs/lsp-references-design.md` 里「Playground 不转发 references」那条旧结论 |
| 5（已落地，§7，PR #731） | rename 放行 | `WorkspaceEdit` 的 `changes` 与 `documentChanges` 两种形状都过滤到本 buffer；lsp-client 不发 prepareRename，网关不放 |

formatting 不在刀序里：它改用户缓冲区，Playground 上价值低（调研 §7 第 6 条）。

刀 2 的 `sanitizeHTML` 是硬前提，不是可选项：lsp-client 把 hover 与补全文档的 markdown 经
`marked` 转成 HTML 后直接 `innerHTML`，默认不消毒；Playground 的分享链接从 `location.hash`
载入代码，hover 又显示用户自己写的 `##` 文档，不消毒就是一条经分享链接触发的 XSS（调研 结论第 3 条）。
方案是自写白名单（`template` 解析后只留 `p/pre/code/em/strong/ul/ol/li/a(无 href)/span[class]`），
估 40 行、约 0.5 KiB，不引 DOMPurify（+11.4 KiB）。

## 3. 刀 1：内置补全表懒加载

### 3.1 表是什么、多大

`site/play-ui/scripts/gen-builtins.mjs` 从 `dawn doc --builtins` 生成
`src/builtins.generated.ts`（281 项：39 个 prelude 函数、242 个 std 模块函数，带签名与首段文档）。
它是 `@codemirror/view` 之后最大的单一输入。刀 1 之前它静态 import 进 `dawn-lang.ts`，
随首屏 `playground.js` 一起下载。

### 3.2 什么时候要它

LSP 在线时，服务端的 completion 已经给出 checker 看见的 builtin，表只是重复。表只在三种时候有用：

1. LSP 还没连上（首屏到 initialize 回包之间），或根本连不上（429/503、网络失败、预算用完）；
2. 连上后断线，状态回到 `fallback`；
3. 状态是 `ready`，但这次 completion 请求失败或超过 750 ms。

### 3.3 怎么做

- `dawn-lang.ts` 不再静态 import 表，只 `import type { Builtin }`。`loadBuiltins()` 用
  `import('./builtins.generated')` 拉表并建索引（prelude / 模块函数 / 按别名分组），并发调用共享一个 promise，
  失败后忘掉 promise，下次补全再试。
- `dawnCompletions(context, table = 已加载的表)` 保持同步，从不发起拉取：没有表时只给本文件声明、关键字、
  类型与构造子；`alias.` 之后没有表就不给。`staticCompletions` 是离线源，先 `await loadBuiltins()` 再调前者。
- `lspCompletionSource(client, offline, online)`：客户端不 ready 时直接走 `offline`；ready 时用 `online`
  （即同步的 `dawnCompletions`）与服务端结果合并；请求抛错时走 `offline`。服务端答了空列表不算不可用，照旧返回静态半边。
- `prefetchWhenOffline(client, loadBuiltins)` 在 `lsp.start()` 之后订阅状态，一进入 `fallback` 就预取，
  断线后的第一次补全不必等网络。订阅放在 `start()` 之后，因为之前的 `fallback` 只表示「还没试」。
- Vite 去掉 `inlineDynamicImports`，表成为单独的 `playground-builtins.js`。
- 站点生成器（`site/src/gen/pages.dawn` 的 `emit_play_js`）先写 chunk，拿到指纹名，再把
  `playground.js` 里的 `import("./playground-builtins.js")` 改写成指纹名，照 `emit_bridge` 的顺序。
  `/assets/` 下一律 `immutable`，不改写就会按不变的名字取会变的字节。bundle 里找不到这句 import 就停构建：
  要么拆分被撤回、表又回到首屏，要么 Vite 换了拼写，两种都不该静默发布。

### 3.4 行为变化（有意的）

LSP 在线且本页从未离线过时，静态半边里没有 builtin 表，于是两样东西只剩服务端给的那份：

- 未写 `use std/str` 时输入 `tri`，不再出现 `str.trim`（选中后自动补 `use` 那条），因为服务端只给作用域内的名字；
- 未导入模块时输入 `str.`，不再列出 `std/str` 的成员。

写了 `use` 之后两者都由服务端给出。本页离线过一次（表已加载）之后，在线补全照旧与表合并，与刀 1 之前一致。
这是裁决 3c 的直接后果（表只在 LSP 不可用时加载），换来的是下表的首屏体积。

> 2026-10-05 补记：上面两项已由服务端补回，见 [lsp-auto-import-design.md](lsp-auto-import-design.md)：
> 裸词给 `str.trim`、`str.` 给成员，各带插入 `use` 的 `additionalTextEdits`，play-ui 在同一个事务里应用。
> 那篇 §1 也记了：改前「写了 `use` 之后由服务端给出」并不成立，服务端在 `.` 之后一律返回空、裸词也不给限定名。

### 3.5 体积实测

方法：基点 main `4734d08c` 与本刀，各自在 `site/play-ui` 里 `npm ci && npm run build`（Vite 6.4.3），
量 `dist/` 产物；gzip 1.12 从 stdin 压（不带文件名头），brotli 1.2.0 默认级别。
原始产物在 `/home/dawn/workspace/gx-out/play-lazy/size/`（本机证据目录，不进仓库）。

| 文件 | raw | gzip -6 | gzip -9 | brotli |
|---|---|---|---|---|
| 刀 1 前 `playground.js` | 464,795 | 147,862 | 147,525 | 127,363 |
| 刀 1 后 `playground.js`（首屏） | 396,193 | 129,475 | 129,173 | 111,943 |
| 刀 1 后 `playground-builtins.js`（按需） | 70,376 | 18,722 | 18,672 | 15,982 |
| 首屏差 | −68,602 | **−18,387（−17.96 KiB，−12.4%）** | −18,352 | −15,420 |

拆开后两文件合计 gzip 148,197，比合在一起多 335 字节，只在离线时付。调研估刀 2 首屏 +20.1 到 +23.0 KiB gzip；
本刀抵掉其中约 18 KiB，刀 2 加自写消毒后的首屏预计比刀 1 之前多 2 到 5 KiB，判据见 §2。
`playground.css`（8,364 raw）与页面 HTML 本刀不动。

### 3.6 测试与负控

`site/play-ui/test/selftest.ts` 新增一段，必须在任何代码拉表之前跑：

- LSP ready 且服务端有答：结果含服务端的 `println`，不含 `str.trim`，且表未加载；
- 状态 `connecting`、`ready` 不预取，`fallback` 预取一次；
- LSP 不 ready：结果含 `println` 与 `str.trim`，且表已加载；
- LSP ready 但请求抛错：结果含 `println`。

之后的既有用例 `await loadBuiltins()` 再跑。负控三条，各自单独改源码后跑 `selftest`，全部变红（输出在
`/home/dawn/workspace/gx-out/play-lazy/negctl/`）：

| 变异 | 红的用例 |
|---|---|
| 表被删掉：loader 改为返回空表 | 「LSP down: builtins still complete」「LSP request failure: builtins complete」及既有的 `println`、`str.trim` 等 |
| 离线分支被短路：不 ready 时走 `online` | 「LSP down: builtins still complete」 |
| 退回急加载：模块顶层调 `loadBuiltins()` | 「a live LSP answer does not fetch the builtin table」 |

拆分本身（产物里确有单独 chunk、bundle 里确有那句 import）由站点生成器守：`./site/build.sh` 在拼写不符时停构建。

## 4. 刀 2：会话核心换成 `LSPClient`，配 `sanitizeHTML`

### 4.1 换了什么、没换什么

`@codemirror/lsp-client@6.3.0` 接管 JSON-RPC 会话：请求 id、`initialize`/`initialized` 握手、超时、服务端发来的请求
（回 -32601）、`didOpen`/`didChange` 的报文构造，以及 `LSPPlugin`（视图上的 `docToHTML`）。`DawnLspClient`
的对外面不变（`status`、`onDiagnostics`、`completionList`、`hover`、`definition`、`inlayHints`、`semanticTokens`……），
所以 `lint.ts`、`main.ts` 与全部 CodeMirror 胶水原样不动；它的内部换成：

- `SocketTransport`：一条 WebSocket 当一个 `Transport`。重连预算、握手超时、子协议校验、坏帧即断仍在 `DawnLspClient`
  里，每条新连接新建一个 transport，旧的随 socket 丢掉。对未打开的 socket 发送不抛（`LSPClient` 在 promise 回调里发通知，
  抛了就是未处理的拒绝），而是结束这条连接。
- `DawnWorkspace`：唯一一份文档。**何时发一个版本**仍由 `DawnLspClient` 决定（一次一个 Full 同步，按版本号与诊断配对）；
  工作区只把待发文本变成 `LSPClient.sync()` 要的变更记录。同文本也照发：一次编辑在飞行中被改回去，仍需要自己的版本，
  回来的诊断是按版本配对的。
- 诊断仍走 `DawnLspClient` 自己的通知处理器（`/api/check` 回落、3 s 超时、按版本丢弃旧诊断都是产品逻辑，不用库的
  `serverDiagnostics`）。
- 请求自带截止时间，并在连接断开时立刻失败：`LSPClient` 的超时是固定 3 s，且不会在断线时让在飞的请求失败。
- 补全源（resolve、内置回退合并）、inlay、semantic tokens、hover 的内联提示路由仍是手写，只是它们渲染文档时经
  `LSPPlugin.docToHTML`；编辑器挂 `lsp.extension()`（`client.plugin(uri, 'dawn')`）。

### 4.2 `sanitizeHTML`

`src/sanitize.ts`，约 40 行、0.5 KiB 量级：`DOMParser` 惰性解析，然后**按白名单另建一棵新树**（不是在原树上删），
只留 `p/pre/code/em/strong/ul/ol/li/br/a/span`；`a` 保留标签文字、去掉全部属性（文档里的链接指向服务端路径，浏览器打不开），
`span` 只留符合 token 类名字符集的 `class`；`script/style/svg/math/iframe/object/embed/template/noscript…` 连同内容丢弃，
其余未知元素拆开只留文字。输出由新树重新序列化，因此只含这些标签与已转义文本。

hover 与补全的文档现在是 Markdown 渲染的 HTML（以前是只处理反引号的纯文本节点），CSS 相应把 `white-space` 改回 `normal`、
给块级元素留间距。没有 `LSPPlugin` 的视图（测试里的假视图）退回纯文本节点。

### 4.3 判据对照

| 判据 | 结果 |
|---|---|
| `selftest.ts` 的假网关先对拍再切 | 旧 `DawnLspClient` 的全部握手/串行同步/版本配对/预算用例原样跑在新核心上，只改了两处：假 `initialize` 回包要带 `textDocumentSync: 1`（库按它决定发不发 `didChange`；网关本来就宣告 1），以及等待由一个微任务改为一个定时器回合（库经几跳 promise 处理回包） |
| XSS 变异负控 | `test/sanitize-tests.ts`：29 条直接喂 sanitizer 的敌对输入（script、on* 属性、`javascript:` 链接含实体混淆、svg/math 载荷、mXSS 形状、iframe srcdoc、style、form、注释……），6 条走真实 `LSPPlugin.docToHTML`（含 `## <img src=x onerror=...>`）。每条先用**不带消毒的 `LSPClient`** 证明载荷是活的，再证明配置后的客户端输出里没有任何白名单外的元素或属性。三个变异体各自单独改源码后全部变红：sanitizer 改成原样返回（52 项红）、`LSPClient` 配置里删掉 `sanitizeHTML`（6 项红）、`a` 放回 `href`（10 项红） |
| 网关零改动 | 是；`playground/` 未动 |
| 首屏净增量 ≤ 刀 1 省下的量 | 见 §4.4 |

DOM 由 `linkedom` 顶替（仅 devDependency，不进 bundle）。node 里没有 DOM，而 sanitizer 的行为就是 DOM 的行为；
`ParseHTML` 参数让同一份代码在浏览器里用 `DOMParser`、在测试里用 linkedom 的。没有在真浏览器里跑，这是本刀的已知缺口：
hover 的版式（间距、暗色）与移动端行为要人在页面上看一眼。

### 4.4 体积实测

方法同 §3.5：基点 main 与本刀各自 `npm ci && npm run build`，量 `dist/playground.js`。

| | raw | gzip -6 | brotli |
|---|---|---|---|
| 刀 2 前（`a3d45a59`） | 419,370 | 136,723 | 118,203 |
| 刀 2 后 | 474,002 | 154,068 | 133,046 |
| 差 | +54,632 | **+17,345（+16.9 KiB）** | +14,843 |

刀 1 省下 18,387，所以刀 2 后首屏仍比刀 1 之前少约 1.0 KiB（gzip -6）。增量里 `marked` 约 11.5 KiB（调研 §2），
`sanitize.ts` 本身不到 1 KiB。`playground-builtins.js` 与 `playground.css`（+0.5 KiB raw）之外不动。

## 5. 刀 3：signatureHelp 放行

### 5.1 网关

`playground/lsp_gateway.py` 把 `textDocument/signatureHelp` 加进白名单，与 hover、definition 同一个分支：请求按字段重建，
只剩 Playground 那一个文档和一个位置，客户端多带的 `context` 与别的键不过网关。`initialize` 回包宣告
`signatureHelpProvider: {triggerCharacters: ["(", ","]}`，与服务端自己的宣告一致。

回包经 `signature_help_value` 重建，只留浏览器要读的字段：

- 至多 4 条 signature（服务端今天只给 1 条）；每条留 `label`（非空，≤ 2048 字符）、`parameters`、markdown 或纯文本的 `documentation`（≤ 16384 字符）。
  服务端以后加的 `command`、逐参数 `documentation` 之类一概不过。
- `parameters[i].label` 只收 `[start, end)` 偏移对：两个非负 int32，`start ≤ end`，且 `end` 不超过 label 的 UTF-16 长度。
  偏移按 UTF-16 单位数（和 JavaScript 字符串下标一致），所以一个星面字符占两格。字符串形式的参数 label 不收：
  服务端本来就只发偏移（`handle_signature_help` 的注释写了理由），浏览器不必再做子串查找。
- `activeSignature`、`activeParameter` 只收非负 int32。
- **超长的不杀会话**：label 或文档超过上限时，该 signature 或该文档被丢掉（没有签名剩下就回 `null`），不当作子进程协议错误。
  结构不对（偏移越界、字段类型错）才是 `ChildProtocolError`，与 semantic tokens、completion resolve 的回包校验一致。

### 5.2 客户端

没有用 `@codemirror/lsp-client` 自带的 `signatureHelp()`：它经 `LSPClient.request` 直接发请求，问的是服务端**上次收到**的文本，
而 Playground 的核心保证「每个回包都对着屏幕上的那一版文本」（`DawnLspClient.queryWith`，见 §4.1）。所以 `DawnLspClient.signatureHelp(offset)`
走与 hover 相同的 `query`，`lspSignatureHelp` 是手写的一个 `StateField` + `showTooltip`（约 100 行，gzip 净增约 0.7 KiB）：

- 输入 `(` 或 `,`（`input.type` 事件）时发请求；打开之后每次改文本或移动光标都再问一次，让高亮的参数跟着光标走；
  服务端回 `null`（光标出了调用）或 Esc 就关。`Mod-Shift-Space` 手动触发（和库的键位一致）。
- 浮层是 `.dp-hover` 的样式：签名里当前参数加粗加下划线，函数整体文档经 hover 同一个 `docElement`（`sanitizeHTML` 之后的 Markdown）。
- `initialize` 的客户端能力里声明 `labelOffsetSupport`；网关自己重建 `initialize`，这只对直连其它服务端有意义。

### 5.3 测试

- `playground/test/lsp_contract.py` 增一项（`lsp-contract.sh` 由 28 项增到 29 项）：请求重建、回包白名单、超长丢弃、UTF-16 偏移、
  结构错误是协议错误；会话级用例里再走一遍真 WebSocket。变异体四个，各自单独改网关源码后合约必须红：回包不过滤、label 不设上限、偏移不查界、偏移按码点数。
- `site/play-ui/test/selftest.ts`：请求形状（对着已诊断的那版文本）、回包解析（越界偏移丢弃、字符串 label 丢弃、字符串文档）、活动参数切分、
  `(` 与 `,` 才触发。变异体：偏移上界检查、`start ≤ end` 检查、活动参数切分各删一次，selftest 全部变红。

## 6. 刀 4：references 放行

### 6.1 网关

`textDocument/references` 进白名单。请求重建为 Playground 的文档、一个位置和 `context.includeDeclaration`
（缺 `context` 按假，与服务端读法一致；不是布尔值就关会话，同其它字段校验）。

回包经 `references_value` 重建：只留 `uri` 等于 Playground 文档的位置（别的文档的位置丢弃，照 definition），每个位置重建成
`{uri, range}`，范围不是两个合法位置就是子进程协议错误，至多 1000 条（超出的截掉，不报错：256 KiB 的单条上限下，
每条约 100 字节的回包放得下的数量级就是这个；64 KiB 的缓冲区里一个名字出现上千次本来也不是读得过来的列表）。
`initialize` 宣告 `referencesProvider: true`。documentHighlight 与 rename 不放（刀序里 rename 是刀 5）。

旧结论的改写在 `docs/lsp-references-design.md` §R2.4：那里原来写「网关白名单里没有 references，与 R1 同样不转发」，今天不成立了。
文档是 `untitled:` 缓冲区，服务端本来就把它当 standalone，所以 R2 的工作区引用程序不参与，Playground 得到的是 R1 的单文件回答。

### 6.2 客户端

同刀 3 的理由不用库自带的 `findReferences`：它问服务端上次收到的文本。`DawnLspClient.references(offset)` 走 `queryWith`，
`lspReferences` 是一个 `StateField` + `showPanel`（编辑器下方，约 80 行，gzip 净增约 0.5 KiB）：

- `Shift-F12` 发请求，`includeDeclaration` 恒为真；面板按文档顺序列出每处引用「行:列 + 去掉首尾空白的那一行（至多 120 字符）」，
  同一起点只列一次，至多 500 行；点击一行选中该引用并聚焦编辑器，Esc 关闭。
- 面板里的偏移是对着请求时的文本算的，所以文档一改面板就关；回包到达时文本已变也丢弃。
- 面板内容全部用 `textContent` 写入，不经 `innerHTML`。

### 6.3 测试

- `lsp_contract.py` 再增一项（29 到 30 项）：请求重建（多余的键、多余的 `context` 字段不过）、回包只留本缓冲区并重建、缺 `context` 按假、`null` 通过、
  超过 1000 条被截、别的文档/非布尔标志/负位置进不去子进程、回包结构错是协议错误；会话级用例走真 WebSocket，假子进程把标志回显在位置里，
  验证标志真到了子进程。四个变异体各自单独改网关源码后合约必须红：回包不过滤、别的文档的位置不丢、不设上限、标志不查类型。
  原来拿 `textDocument/references` 当「网关不提供的方法」的未知方法用例，改用 `textDocument/documentHighlight`。
- `selftest.ts`：请求形状、非位置项丢弃、行排序/去重/行内容裁剪/别的文档丢弃；四个变异体（不查 uri、不去重、不排序、标志写假）各让 selftest 变红。

## 7. 刀 5：rename 放行

### 7.1 网关

`textDocument/rename` 进白名单，`prepareRename` 不放（刀序已定：Playground 的输入框直接取光标下的词当初值，不需要服务端先回区间）。
请求重建为 Playground 的文档、一个位置和 `newName`（非空字符串，≤ 256 字符；别的类型关会话，同其它字段校验）。`initialize` 宣告 `renameProvider: true`。

回包经 `rename_value` 重建，两种 `WorkspaceEdit` 形状都认，出口只有一种：

- `documentChanges` 里 `textDocument.uri` 不是 Playground 文档的条目丢弃，文件操作（create/rename/delete，没有 `textDocument`）一并丢弃；
  没有 `documentChanges` 时读 `changes[Playground URI]`，别的 URI 丢弃。出口统一为 `{changes: {<Playground URI>: [{range, newText}]}}`，
  `annotationId`、`changeAnnotations` 之类的字段不过。
- 每条编辑重建成范围（两个合法位置）加 `newText`（≤ 256 字符）；结构不对是 `ChildProtocolError`。
- 至多 1000 条。**超出的不截**：截掉一部分的改名会把程序改坏，所以整个回包换成 `-32803` 的错误回复，客户端什么也不应用。

### 7.2 客户端

`DawnLspClient.rename(offset, newName)` 走 `queryWith`（理由同刀 3、4：问的必须是屏幕上那一版文本）。`lspRename` 是手写的一个 `StateField` + `showPanel`
（编辑器上方的一行输入框，gzip 净增约 0.56 KiB）：`F2` 打开，初值是光标下的词，Enter 提交，Esc 关闭。
`renameChanges` 把编辑转成 CodeMirror 的 changes，**一次 `dispatch`**，所以一次撤销就整体还原；编辑重叠、区间反向、为空或超过 1000 条时什么也不应用。
服务端拒绝时（`RequestFailed`）把原因显示在输入框旁，输入框不关；回包到达前文本已变则丢弃。

**服务端的配合**：落地时（PR #731）真服务端对 `untitled:` 缓冲区的 rename 一律拒绝，Playground 上按 F2 得到的是那条拒绝原因。
随后服务端改为：有分析的 `untitled:` 缓冲区以缓冲区本身为改名边界（`docs/lsp-references-design.md` §R3.1a），所以 F2 现在真能改名；
std 里的名字照旧被拒绝，回包仍只含本缓冲区的编辑，网关与客户端不需要改。

### 7.3 测试

- `lsp_contract.py` 再增一项（30 到 31 项）：请求重建、`documentChanges` 与 `changes` 两种形状都只留本缓冲区并重建、`null` 通过、超过 1000 条是错误回复而非截断、
  别的文档/空名字/非字符串名字/超长名字/负位置进不去子进程、回包结构错是协议错误；会话级用例走真 WebSocket，假子进程把新名字回显在编辑里。
  五个变异体各自单独改网关源码后合约必须红：回包不重建、`changes` 里别的 URI 不丢、`documentChanges` 里别的文档不丢、不设上限、新名字不查。
- `selftest.ts`：请求形状、非编辑项丢弃、拒绝原因原样透出、编辑排序；重叠、区间反向、空、超限都不应用。变异体五个（反向检查、重叠检查、上限检查、排序、非编辑项过滤）各让 selftest 变红。

## 8. 不做的（理由）

- **不换 Monaco、VS Code Web**：首屏 gzip Monaco 仅编辑器 712 KiB、带可用功能 1.0 MiB，
  monaco-languageclient 2.3 到 3.0 MiB，VS Code Web 不少于 3.9 MiB；Monaco 官方不支持触屏（裁决 2026-10-04 第 1 条）。
- **不做「高级模式懒加载 Monaco」、不并存两套编辑器**：两套编辑器长期维护，且两个 LSP 客户端各自分配请求 id、
  各自做 didChange 同步，在一条 WebSocket 上复用要自己做多路复用（裁决第 2 条，调研 §7）。
- **不把 completion 交给 lsp-client**：它的补全源丢掉 `data`、不发 resolve，会失去 resolve 文档（D7）与内置表兜底，
  二者都是已上线行为。补全源留手写，刀 2 只把它改挂到 `LSPPlugin` 的 client 上。
- **不在测试里用真浏览器、不把 jsdom/happy-dom 级别的大 DOM 引进来**：linkedom 够跑 sanitizer 与 `docToHTML`，且只在 devDependency。
- **不引 DOMPurify**：+11.4 KiB gzip；文档 markdown 只来自服务端，标签集合小，自写白名单够用（刀 2，§4.2）。
- **LSP 在线时不为补回未导入的模块限定名而拉表**：那会让表在每次页面加载后都被下载，裁决 3c 就不成立了。
  需要它的读者写一行 `use` 即可得到服务端的成员补全（§3.4）。（2026-10-05 起不用写：服务端自己给，附 `use` 编辑，见 [lsp-auto-import-design.md](lsp-auto-import-design.md)。）
- **不在空闲时预取表**：理由同上；只在 `fallback` 时预取。
- **不放行 prepareRename**：输入框的初值取光标下的词，服务端的拒绝在 rename 回复里就能拿到，多一次往返没有收益。
- **不放行 documentHighlight、declaration、typeDefinition、implementation**：lsp-client 不默认发前者，
  服务端未实现后三者（调研 §8）。


## 8. 提示中的代码与文档（2026-10-24）

`doc-render.ts` 与编辑器共用命名为 `dawn` 的 StreamLanguage、`dawnHighlight` 和 `tok-*` 主题变量。
签名完整解析一次，再按 UTF-16 活动参数范围切分安全 DOM；活动参数加粗和下划线不覆盖 token 色。
文档片段没有主编辑器的语义位置，不伪造 LSP semantic token 装饰。

hover 只拆出最前面的 Dawn 签名围栏与协议分隔线，正文 Markdown 原样交给
`LSPPlugin.docToHTML`。LSPClient 的 `highlightLanguage` 对 Dawn、无标签和缩进代码返回既有语言，
其他语言保持纯文本；顺序仍为 Markdown、语法高亮、`sanitizeHTML`。代码块中的 `<br>` 恢复为真实换行，
便于选择和复制。未解析的代码引用链接只整理 prose 的相邻节点，不改写代码字面量。
`MarkupContent.kind=plaintext`、无插件和解析异常均保留安全的字面文本。

普通 hover、inlay tooltip、signature help、在线与静态 completion info 共用文档排版。
completion 有 detail 时显示完整签名，resolve 失败仍可读签名，过期响应不显示。
`documentedCompletionSource` 从 CompletionContext 捕获 view，只替换静态字符串 info，
保留结果字段、插入行为和 builtin 表原有延迟加载时机。

提示尺寸和颜色变量定义在 `.dp-editor`，正文 13px/1.45、外壳 6px×8px、代码块 4px×6px。
代码块保留缩进并横向滚动，长签名可换行；hover 的 CodeMirror 外壳与 signature 根各只保留一层边框和内边距。
规则只覆盖产品文档提示，不改变诊断的纯文本或站点文章代码块。
