# SourceView：切片器收敛

> 状态：**Scope A 已落地**（`SourceView` + `view_of`/`slice_cp`/`slice_u16` 上线,
> `utf16_slice`/`utf16_slice_of` 已删,diag/parser/lspc/lsp 全部改用统一切片器;逐字节对拍
> prev-diff/run-diff/lsp-diff/test 全绿）。**Scope B 仍为文档化的未来决策**。
> 背景：v0.9.0 已修掉两处热点 O(n²)(formatter 的 reflow 用 cursor、lexer 注释收集用 `text_of`),
> 本文收口这条线——把源码切片的多套辅助塌缩成一个 `SourceView` + 一个切片 API,删掉
> `utf16_slice`/`utf16_slice_of` 这两个 O(n) 重扫 footgun。
> 语法/语义权威在 [spec.md](spec.md)（§1.8 formatter），本文讲"为什么"与"怎么做"。

## 1. 背景：切片器动物园

「从源码里切出一段子串」这件事,眼下有四套写法,复杂度各异:

| 辅助 | 位置 | 索引 | 复杂度 | 说明 |
|---|---|---|---|---|
| `utf16_slice(text, lo, hi)` | `lexer.dawn`,pub | UTF-16 偏移 | **O(len(text))** | 每次 `for c in code_points(text)` **从头重扫整串** |
| `utf16_slice_of(cps, offs, u16len, lo, hi)` | `lspc.dawn` | UTF-16 偏移 | **O(len(cps))** | 不重新解码,但仍**遍历整个 cps 数组**找区间 |
| `text_of(s: Src, a, b)` | `lexer.dawn`,私有 | 码点索引 | O(hi−lo) | 切预建的 `Src.cps` 数组,真快 |
| reflow cursor（`take_to`） | `fmt.dawn` | UTF-16 偏移 | O(n) 顺序 | v0.9.0 新增,单调前进 |

`utf16_slice` 被**每 token 调用**时是 O(n²)：checker.dawn(7923 行)格式化一度要 **78 秒**。
v0.9.0 修了两处热点——reflow 改用单个前进 cursor 走一遍 `code_points`、lexer 注释收集改用 `text_of`
——把它降到 0.27s(~290×),但 `utf16_slice`(重扫)和 `utf16_slice_of`(全扫)这两个 footgun
**仍然存在**,还挂在几个不那么热的调用点上。本文把它们一并清掉。

## 2. 根因：token 偏移是 UTF-16,源码是码点

token 的 `.lo/.hi` 存的是 **UTF-16 码元偏移**,而源码在 Dawn 里按**码点**解码。两者错位,所以任何
「按 token span 切片」的地方都得在 UTF-16↔码点之间架桥,而天真的桥(`utf16_slice`)每次重扫。

**为什么 token 用 UTF-16?** 因为 **LSP 协议按 UTF-16 码元定位**(`Position` 类型规范:字符偏移基于
UTF-16 表示,非 BMP 字符如 `𐐀`(U+10400)算**两个**码元)。这是 VS Code 把 JS 字符串的 UTF-16 内部
表示泄进了协议;业界公认是设计污点,LSP 3.17 才加了 `positionEncoding` 协商(utf-8/16/32),但 **UTF-16
仍是强制 baseline**。lexer 因此建了 `offs`(码点索引 → UTF-16 偏移)当桥;`offs` 单调递增(每码点 +1/+2)。

## 3. 目标设计：SourceView + 一个切片 API

一份源码解码**一次**,得到共享视图;切片全走它:

```dawn
# offs[i] = cps[i] 起始处的 UTF-16 偏移(单调递增);u16len = 总 UTF-16 长度
pub type SourceView = { cps: List[Int], offs: List[Int], u16len: Int }

pub fn view_of(text: String) -> SourceView        # 解码 + 前缀和,一次 O(n)

pub fn slice_cp(v: SourceView, a: Int, b: Int) -> String    # 按码点索引,O(b−a)  —— 即今天的 text_of
pub fn slice_u16(v: SourceView, lo: Int, hi: Int) -> String # 按 UTF-16 偏移:二分 offs 定位 + 切 cps,O(log n + len)
```

- `slice_u16` 对 `offs` 二分找到 [lo,hi) 对应的码点索引区间,再 `slice_cp`。取代**两个** O(n) 扫描器。
- 顺序遍历(formatter)保留 cursor:一路单调前进比反复二分更省(O(n) vs O(n log n)),是 `slice_u16` 的特例。
- `Src`(lexer 内部的 `{cps, offs, n, base}`)几乎就是 `SourceView`;二者合并或让 `Src` 复用 `SourceView`。

## 4. Scope A（保守版,推荐先做）

token 仍存 UTF-16 偏移,只统一切片器。

**逐调用者迁移**

| 调用者 | 原状 | 落地 |
|---|---|---|
| `fmt` reflow | cursor+cps(v0.9.0) | 不动(顺序遍历本就是 `slice_u16` 的 O(n) 特例) |
| `lexer` 注释收集 | `text_of`(v0.9.0) | 不动(`slice_cp` 即今天的 `text_of`) |
| `diag.render` | 每诊断 `utf16_slice` 重扫 | ✅ `slice_u16(view_of(text), …)` |
| `parser` assert 源文本 | 每 assert `utf16_slice` 重扫 | ✅ `slice_u16(view_of(text), …)` |
| `lspc` 补全上下文 | `utf16_slice_of`(全扫 cps)+ 手搓 offs 表 | ✅ `view_of` 建一次视图,`lex_ctx` 收 `SourceView`,`slice_u16`(二分) |
| `lsp` | `import utf16_slice`(已无调用) | ✅ 删死导入 |

**已删除**:`lexer.utf16_slice`、`lspc.utf16_slice_of`。footgun 清零。

> **落地记录**：`diag`/`parser` 仍每次 `view_of(text)`(与旧 `utf16_slice` 一样是一次 O(n) 解码,
> 无回归;这两条不热,未做"每文件建一次 view"的进一步合并)。`slice_u16` 用二分,`offs` 严格递增,
> 取"整个 UTF-16 范围落在 span 内"的码点(与 Kotlin `substring` 一致);两个旧 footgun 的谓词
> 只在**跨代理对半**的非对齐偏移上不同,而 token span / 行边界永远对齐到码点,故逐字节等价。

**顺带清理的同类小账**(同一模式、小输入不上规模,但一并收拾):

- `toml.dawn`、`pkgfetch.dawn` 的 `while i < str.len(s)`——`str.len` 是码点长 O(n),每轮重算 = O(n²)。
  把 `str.len(s)` 提到循环外即可(循环不变量外提)。作用于 dawn.toml/包记录,KB 级,实际无害,但既然在改就顺手。

## 5. Scope B（彻底版,备选,单独决策)

把 **UTF-16 赶到 LSP 边界**:token 偏移改存**码点索引**,UTF-16 只在 LSP 出线那一刻转。

- 内部全 `slice_cp`/cursor,连 `offs` 都不用外传;lexer 建 token 时直接用码点数组下标。
- `diag` 的列号变**码点**(对人更准)。
- LSP 层在**发/收 position 时**做码点↔UTF-16 换算(它本就在做行列映射,集中到边界即可);以后支持
  `positionEncoding` 协商、能协商到 utf-32 时**零换算**。

**代价 / 风险**:动 token 偏移语义,牵连**所有读 `.lo/.hi` 的地方**(lexer/parser/lsp/diag)+ LSP 位置
映射要补边界换算。blast radius 大,须谨慎逐处对拍。**建议 Scope A 落地、footgun 清零后再评估是否值得。**

## 6. 验证与落地

- **纯重构,输出逐字节不变** → `fmt-diff` / `lsp-diff` / `prev-diff` / `run-diff` / 单测全绿即达标;
  **无需 `Emit-Change:` 声明**(codegen 输出不变)。
- **只用现成原语**(`code_points` + Dawn 里手写二分)→ **单阶段、自举安全**,任意时刻可落地
  (不像"加编译器内建"那样要发 release 进种子的两阶段)。
- 针对性单测:`slice_u16` 对含**非 BMP 字符**(`𐐀`,占 2 个 UTF-16 码元)的源验证 UTF-16 偏移边界对齐。

## 7. 决策

**Scope A 已落地**——定义清晰、机械、零行为变化,一次删掉两个 footgun。逐字节对拍
(prev-diff emit / run-diff / lsp-diff)+ selfhost/site 测试全绿,单阶段、自举安全(只用现成
`code_points` + 手写二分,无新内建),无 `Emit-Change`。§4「顺带清理」的 toml/pkgfetch `str.len`
外提尚未做(小输入、无害),留作随手项。

**Scope B 作为文档化的未来决策**留着:它是"正确"的终态(UTF-16 是线格式细节,不该泄进 token),
但更深更险(动 token 偏移语义、牵连所有读 `.lo/.hi` 处),按需再评估。
