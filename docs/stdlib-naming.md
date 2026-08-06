# stdlib 命名：破坏性重组为模块限定式（P0.7）

> 2026-07-22 初版曾定「平铺名永久有效、永不改名」，同日被否决：**要优雅，
> 可以做破坏性更新**。本文改写为破坏性路线的设计定稿；实施排为 P0.7（自举 P1 之前）。
>
> **状态：已实施。** v0.4.0 落地 §一/§二全部三处语义与双拼写过渡（平铺名逐处
> 警告），本仓与 backend-dawn 全量迁移；v0.5.0 删平铺名。规范表述见 spec §10.6/§11。
>
> §五是**第二批改名**（v0.54.0/v0.55.0）的沿革，与本文原题同族但晚了半年：
> 那次动的不是「平铺 vs 限定」，是几个模块内已经叫错的名字。今天的**准入判据**
> 在 CONTRIBUTING §七，本节只留判据答不了的那半边——每个名字改之前是什么、
> 为什么，以及被否掉的另一条路。

## 一、目标拼写（端态）

```dawn
use std/map                     # 整模块：限定访问
use std/list.{map, filter}      # 选择性：热名直呼（Gleam 模型）

let m = map.insert(map.empty(), "k", 1)
let v = map.get(m, "k")
xs |> filter(x => x > 0)    # 选择性引入的短名进管道，零摩擦
```

- std 收进**真模块**：`std/list`、`std/map`、`std/set`、`std/str`、`std/bytes`、
  `std/cursor`、`std/io`。短名 API（`insert/get/has/keys/…`、`len/at/slice/…`）。
- **平铺前缀名（`map_insert`/`byte_len`/`cursor_next`…）整体退役**：迁移完成后从
  全局命名空间删除。编译器内建保留**内部**实现（intrinsic），但公开拼写只有模块名。
- prelude 收缩到真正的高频核：`println`、`map/filter/fold/range/len/get`、
  `sort/max/min/max_by/min_by`（排序族迁 std 后保住裸拼写，pure-ffi-design §十四）、
  `Option`/`Result` 构造器、`to_string`、`panic`/`todo`、`java_try`/`catch_panic` 等
  一屏以内；其余一律 `use`。

## 二、要动的三处语义（P0.7 的实现清单）

1. **捆绑 std 的可引入性**：`use std/x` 命中 classpath 资源 `std/x.dawn`（磁盘同名
   路径优先报冲突而非静默遮蔽）。std 模块经正常 ModuleExports 走 §10.3 的限定访问
   与选择性引入，LSP 跳转/补全免费获得。
2. **顶层声明遮蔽内建改为合法**（Rust 式）：注册期「`map` is a builtin and cannot
   be redefined」的错误删除；解析顺序本就是本模块声明 → std → 内建，遮蔽自然生效。
   design.md D10 的相应条目作废、就地修订。std 模块自身正是第一批受益者
   （`std/list` 里的 `pub fn len` 不再非法）。
3. **键类型合法性检查（§2.2）改挂 `TMap`/`TSSet` 实例化处**，不再按内建函数名点名
   （KEYED_CREATORS），使 wrapper/转发天然穿透、报错落在用户代码的实例化点。

## 三、迁移（破坏性，两仓一次结清）

- v0.4.0：std 模块 + 短名落地，平铺名保留但**弃用警告**；本仓（std 内部、examples、
  site、playground、golden、教程）与 backend-dawn 全量迁移到新拼写。
- v0.5.0：平铺名删除。两版之间不接受新的平铺名用法。
- 自举编译器（M7 四刀）直接用新拼写书写。

删除之后旧拼写并没有变成一句「undefined function」就完事：编译器留了一张搬迁表
（`stdlib.moved`），写出 `map_insert` 会被告知它搬去了哪个模块、新拼写长什么样。
这条至今有效，spec §10.6 只留这个行为、不留版本号。

## 四、不做的

- 不做 `m.insert(k, v)` 式方法调用（UFCS 只认非限定名，无重载消解可依）——限定
  `map.insert(m, k, v)`、选择性引入短名、管道三条路已够优雅。
- 不为 `x |> map.insert(k, v)`（限定名进管道）扩语法：需要时选择性引入即可。

## 五、第二批改名（v0.54.0/v0.55.0）：四个名字的沿革

来源是 `docs/audit/re-audit-2026-07-30.md` 的 RD-06（命名族各行其是）。判据本身已
固化进 CONTRIBUTING §七，这里记的是四处**具体**的前后与取舍。四个都走了「一代
转发器」：新名与旧名同期上线、旧名降为一行转发器，下一版才删——理由是机器的，
`bin/dawn` 的 stage 1 用**种子自带的那份 std** 编译今天的 `selfhost/src`。

**`str.substring` → `str.slice`（v0.54.0）。** 「一个概念一个名字」：`list.slice`
与 `bytes.slice` 早就这么拼，三者都两端钳位，落单的那个偏偏叫的是一个**名词**
（*sub-string*）而不是那个操作。

**`bytes.len(b: Buf)` → `bytes.size`。** 这是命名族的**第一个具名例外**——全库唯
一一处把「长度」问了第二遍。Dawn 无重载，而 `len(b: Bytes)` 是成品字节的长度、
先占住了名字，所以让路的只能是写入游标。例外落在 `Buf` 而不是落在容器上，是因为
`Buf` 根本不是容器：它是一个写游标，契约到 `freeze` 为止，调用方是解压器——读回
自己刚写下的那几个字节。

**`bytes.get(b: Buf, i)` → `bytes.buf_at`。** 第二个具名例外，成因同上（无重载，
`at(b: Bytes, i)` 先占住了对的名字）。但旧名错得更重一层：`get` 是判据 2 的词
（`list.get`、`map.get`——问询，答 `Option`），而这个函数 panic。它是 std 里唯一
一处用问询的词去做断言的地方，这正是新名要记下的缺陷。

> **被否的另一条路**：改 `at(b: Bytes, i)`、把 `at` 腾给 `Buf`。否掉的理由是
> `bytes.at` 按 §4.8 判据 1 **本来就叫对了**，而且调用点都在它身上；把对的名字
> 挪走给错的名字腾地方是反的。这条后来上升成了 CONTRIBUTING §七里的判据本身。

**`cursor.at` → `cursor.seek`（v0.54.0）。** `at` 与 `seek` 是语言两条越界政策的
词，一个名字扛不了两条：`at` 是判据 1（`str.at`、`bytes.at`、`xs[i]`——调用方声称
位置存在，落空 panic），`cursor.at` 是判据 3（钳位，永不 panic）。于是三字符的串上
`str.at(s, 9)` 是 panic、`cursor.at(s, 9)` 是末尾，两者的差别取决于读者当时恰好在
哪个模块里。那不是取舍，是缺陷。

**同批还退了一处导出**：`std/fmt` 的三个 `parse_*` 实现自 v0.55.0 起不再导出，
`fmt.atoi`/`fmt.atod`/`fmt.atoi_radix` 从此不是可写的名字——同一件事只留内建拼写
这一种写法。spec §10.6 只说今天的状态。
