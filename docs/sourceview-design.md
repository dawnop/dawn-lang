# SourceView：切片器收敛

> 状态：**Scope A + Scope B 均已落地**。Scope A 统一了切片器(`SourceView` +
> `slice_cp`,删掉 `utf16_slice`/`utf16_slice_of`);Scope B 进一步把**内部位置货币整体换成
> 码点索引**——token span、行起点、诊断列全是码点,UTF-16 只在 **LSP 出线边界**由 `SourceView`
> 重建。逐字节对拍 prev-diff/run-diff/fmt-diff/lsp-diff/fixpoint(B==C) 全绿,158 selfhost + 33 site
> 测试全绿,并新增非 BMP(`🎈`/`𐐀`)单测锁住列号/LSP 位置行为(对拍语料是 BMP,覆盖不到)。
> 背景：v0.9.0 已修掉两处热点 O(n²)(formatter 的 reflow 用 cursor、lexer 注释收集用 `text_of`)。
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
```

> **Scope A 曾另有 `slice_u16`(按 UTF-16 偏移切片,二分 `offs`)** 作为两个旧扫描器的替身。
> Scope B 落地后,内部再没有"按 UTF-16 偏移切片"的需求(位置货币全是码点),`slice_u16` 与其
> 二分辅助 `lower_bound` 已一并删除;`offs` 只剩下 LSP 边界的位置换算这一个用途。
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

**顺带清理的同类小账**(已做):`toml.is_bare_key`、`pkgfetch.pax_path` 的 `while i < str.len(s)`
——`str.len` 是码点长 O(n),每轮重算 = O(n²)。把 `str.len(s)` 外提到循环外(不变量外提)。
KB 级输入、实际无害,一并收拾。

## 5. Scope B（彻底版,已落地）

把 **UTF-16 赶到 LSP 边界**:token 偏移改存**码点索引**,UTF-16 只在 LSP 出线那一刻转。落地内容:

- **`lexer`**:`off(s, i)` 从 `base + offs[i]`(UTF-16)改成 `base + i`(码点下标);`Src` 丢掉 `offs`
  表;token span 天生是码点索引。lexer 里所有 `+1/+2/+3` 字面偏移都是 ASCII 定界符(`\n`/`_`/`${`/
  `"""`/转义),1 UTF-16 码元 = 1 码点,原样正确。
- **`line_starts_of`**:返回**码点索引**的行起点(`\n` 后一位),与 token/诊断同货币。
- **`diag`**:列号、caret 长度按**码点**数(对人更准——一个 emoji/宽字算 1 列)。
- **`lsp`**:唯一保留 UTF-16 的地方。`Doc` 存 `SourceView`;`lsp_position` 用 `offs` 把码点偏移
  换成 UTF-16 列(线格式),`lsp_offset` 反向走行内 `offs` 把 UTF-16 列换回码点偏移。以后能协商到
  `positionEncoding: utf-32` 时,这层换算直接退化成恒等。
- **删除**:`slice_u16` 与 `lower_bound`(Scope A 建的 UTF-16 切片器,Scope B 后内部无人再按 UTF-16 切)。
  `SourceView` 只剩 `view_of` + `slice_cp`,`offs` 只服务 LSP 边界。

## 6. 验证与落地

- **逐字节对拍全绿**:`prev-diff`(emit/lex/parse/fmt)、`run-diff`、`fmt-diff`(95 文件)、
  `lsp-diff`(50 消息)、`fixpoint`(B==C)。**无需 `Emit-Change:` 声明**——对拍语料是 BMP
  (中文也是 BMP,1 UTF-16 码元 = 1 码点),码点/UTF-16 数值恒等,故所有可观测输出不变。
- **单阶段、自举安全**:只用现成 `code_points`/`from_code_points`,无新内建,任意时刻可落地。
- **非 BMP 单测(对拍覆盖不到,专门补)**:`lexer` 的 `🎈`(span=码点宽)、`diag` 列号
  (`a🎈b` → `:1:3` 而非 UTF-16 的 `:1:4`)、`lsp` 边界往返(`b` 码点偏移 2 ⇄ UTF-16 列 3)。

## 7. 决策

**Scope A + Scope B 均已落地**。Scope A 先统一切片器、删掉两个 footgun(零行为变化的纯重构);
Scope B 再把内部位置货币整体换成码点索引、UTF-16 收束到 LSP 边界——这才是"正确"的终态
(UTF-16 是线格式细节,不该泄进 token)。两步都逐字节对拍全绿、无 `Emit-Change`(BMP 语料下
码点与 UTF-16 数值恒等),非 BMP 行为由新单测锁住。

一个副产品:`diag` 列号现在按码点数,对含宽字符/emoji 的源**比 Kotlin 版更准**(Kotlin 版继承的
UTF-16 列会把一个 emoji 数成 2 列)。这是唯一"更对而非等同"的差异,但对拍语料 BM-only,故未触发对拍。
