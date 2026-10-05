# Playground 接 `@codemirror/lsp-client`：分刀与内置补全表懒加载

> 状态：**current**。刀 1（本文 §3，内置补全表懒加载）已落地；刀 2 起未动。
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
| 2 | 换会话核心：`LSPClient` + 自写可重连 Transport；hover、definition、诊断迁过去；补全源、inlay、semantic tokens 改挂 `LSPPlugin`；同刀配 `sanitizeHTML` | `selftest.ts` 与 `lsp_contract.py` 的假子进程先对拍再切；合约里放 `## <img src=x onerror=...>` 变异负控，消毒删掉时必须红；首屏净增量不超过本刀省下的量；网关零改动 |
| 3 | signatureHelp 放行（网关白名单与宣告） | 回包字段白名单与长度上限；`playground/test/contract.sh` 增一项 |
| 4 | references 放行 | 回包只留本 buffer 位置（照 definition）；同刀改写 `docs/lsp-references-design.md` 里「Playground 不转发 references」那条旧结论 |
| 5 | rename 放行 | `WorkspaceEdit` 的 `changes` 与 `documentChanges` 两种形状都过滤到本 buffer；lsp-client 不发 prepareRename，网关不放 |

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

## 4. 不做的（理由）

- **不换 Monaco、VS Code Web**：首屏 gzip Monaco 仅编辑器 712 KiB、带可用功能 1.0 MiB，
  monaco-languageclient 2.3 到 3.0 MiB，VS Code Web 不少于 3.9 MiB；Monaco 官方不支持触屏（裁决 2026-10-04 第 1 条）。
- **不做「高级模式懒加载 Monaco」、不并存两套编辑器**：两套编辑器长期维护，且两个 LSP 客户端各自分配请求 id、
  各自做 didChange 同步，在一条 WebSocket 上复用要自己做多路复用（裁决第 2 条，调研 §7）。
- **不把 completion 交给 lsp-client**：它的补全源丢掉 `data`、不发 resolve，会失去 resolve 文档（D7）与内置表兜底，
  二者都是已上线行为。补全源留手写，刀 2 只把它改挂到 `LSPPlugin` 的 client 上。
- **不引 DOMPurify**：+11.4 KiB gzip；文档 markdown 只来自服务端，标签集合小，自写白名单够用（刀 2）。
- **LSP 在线时不为补回未导入的模块限定名而拉表**：那会让表在每次页面加载后都被下载，裁决 3c 就不成立了。
  需要它的读者写一行 `use` 即可得到服务端的成员补全（§3.4）。
- **不在空闲时预取表**：理由同上；只在 `fallback` 时预取。
- **不放行 documentHighlight、declaration、typeDefinition、implementation**：lsp-client 不默认发前者，
  服务端未实现后三者（调研 §8）。
