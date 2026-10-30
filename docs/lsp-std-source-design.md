# LSP 标准库源文档

> 状态：**current**：已实现统一源身份与 std 分析视图。

## 问题与被推翻的方案

内嵌 std 已有原文、AST、类型化树与文档注释，却因为没有磁盘路径而丢弃声明跨度，
连带使语义 token 的解析输入消失。磁盘 std 打开后，workspace 保存的规划名 `math`
与检查后的 `std/math` 不同，查询入口失配。诊断仍按路径发布，因此零诊断不能证明查询正确。

只修规划名无法恢复内嵌库阅读；将内嵌源码落盘会多出缓存和版本一致性责任。两者均不采用。

## 源身份与分析归属

源身份分为 canonical 文件、缓冲区、库快照中的模块。查询使用明确的声明源身份与跨度，
本地名字在遍历收集边界绑定到当前源；无声明的内建名仍没有定义。
库快照登记模块的身份、SourceSnapshot、AST 和 CheckedMod，快照摘要覆盖全部模块名及原文。
std 属性来自登记表，不能从路径前缀推断。沿用现有 SourceSnapshot 的 UTF-16 表。

磁盘 workspace 按 canonical 文件与最终 CheckedMod 绑定入口，早期发布与引用程序也使用该绑定。
磁盘编辑沿用检查器现有的 `impls_before`；内嵌文档复用库检查结果，不重新当作用户模块检查。
外部库改名继续拒绝写入，用户导入别名沿用原边界。

## 协议与客户端

内嵌源使用 `dawn-stdlib:<摘要>/std/math.dawn`。客户端在
`capabilities.experimental.dawnSource` 声明内容读取能力；服务端提供 `dawn/source`，
参数 `{uri}`，回复 `{uri, text, languageId: "dawn"}`。未登记身份返回请求错误。
没有该能力的客户端仍取得 token 与 hover，但不会收到无法读取的虚拟跳转目标。
VS Code 同一交付注册内容提供方与文档 selector；提供方读取服务端快照，不写磁盘。
虚拟 didOpen 必须与登记原文一致；伪造 URI 或篡改文本不能取得 std 分析权限。

## 验收与落点

真实 LSP 会话覆盖 embedded 与 disk，从用户 definition 返回的 URI 读取并打开，继续查询
math/narrow/cursor 的 token、hover、局部与跨 std definition；覆盖编辑、关闭重开、双 URI、
符号链接、UTF-16、别名与双身份引用、外部改名拒绝和普通用户名字。
每个负控必须是能构建的实现变异或修前服务端上的失败断言。源码落点为 lsp 的源登记、
查询、token、引用与 server，以及 VS Code 提供方；不改语言规则与 std 实现。

## 不做的（理由）

- 不把内嵌源码落盘，不伪造 file URI：源对象已在内存中。
- 不加 std 名单或路径拼写回退：权限只能来自所选库快照。
- 不扩展网页 std 阅读：网页继续只暴露当前缓冲区；token 不依赖虚拟文档能力。
- 不修改 W3 的 `walk_method` 与选择性导入的 `ImportValueUse`：它们是必须保留的既有语义。
