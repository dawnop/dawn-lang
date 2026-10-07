# stdlib 命名：破坏性重组为模块限定式（P0.7）

> 2026-07-22 初版曾定「平铺名永久有效、永不改名」，同日被否决：**要优雅，
> 可以做破坏性更新**。本文改写为破坏性路线的设计定稿；实施排为 P0.7（自举 P1 之前）。
>
> **状态：historical** —— 已实施。v0.4.0 落地 §一/§二全部三处语义与双拼写过渡（平铺名逐处
> 警告），本仓与 backend-dawn 全量迁移；v0.5.0 删平铺名。规范表述见 spec §10.6/§11。
>
> §五是**第二批改名**（v0.54.0/v0.55.0）的沿革，与本文原题同族但晚了半年：
> 那次动的不是「平铺 vs 限定」，是几个模块内已经叫错的名字。今天的**准入判据**
> 在 CONTRIBUTING §七，本节只留判据答不了的那半边——每个名字改之前是什么、
> 为什么，以及被否掉的另一条路。
>
> §六是**第三批**（v0.80.0，#210）：动的是形参名。具名实参（`named-args-design.md`）
> 落地后，形参名成了调用方写得出来的 API；§六记这一批的判据、改名表与冻结门。

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

## 六、第三批：形参名（v0.80.0，#210）

具名实参（#207）让 `str.split(s, sep: ",")` 成立，于是 std 的每个形参名都成了 API，
而这些名字从没按「会被调用方写出来」审过。调研见
`agent-handoff/research-std-param-names-20261001.md`（仓外）：394 个 top-level pub fn、
997 个形参槽位，外加 prelude trait；改 20 处，其余不动。

### 判据

1. **接收者按类型取惯用名，不统一成一个词**：`List` 是 `xs`，`String` 与 `Set` 是 `s`，
   `Bytes`/`Buf` 是 `b`，`Map` 是 `m`，`Char` 是 `c`，`Tensor` 是 `t`。类型未知的 trait
   接收者，容器类用 `it`（`Iter`、`Index`），值类用 `x`（`Hash`/`Show`/`Display`），
   对称二元用 `a, b`（`Ord`/`Eq`/`Narrow`）。接收者在点调用里本来不可具名
   （`x.f(xs: y)` 报 given twice），统一它要动 170 多个槽位，只换来形式上的整齐。
2. **单字母可以，当它在整个 std 里只表示一个角色**：`i` 位置、`n` 个数、`x` 元素或 Float
   标量、`f` 回调、`c` 游标或字符（两者从不在同一签名里出现）；术语与公式变量
   （`matmul(m, k, n)`、IEEE 的 `p/emin/emax`）在 `##` 注释写出公式时也可以。
3. **不可以**：单字母藏住了顺序敏感的角色（`atan2` 的哪个是 y）；同族兄弟把同一角色
   写成别的名字；相邻的 prelude trait 里同一字母表示不同角色；下划线前缀（`_x` 在 Dawn
   里没有语义，却会原样进入 API，成为调用方要写的 `_dtypes:`）。
4. **一个概念一个名字**，推到形参：回调 `f`、子串 `sub`、分隔符 `sep`、区间端点
   `from`/`to`、累加初值 `init`、在处理器下运行的体 `body`、`List[Float]` 数据 `xs`、
   字节数据 `b`、dtype 列表 `dtypes`。`str.replace(s, from, to)` 的 `from/to` 是子串
   而不是位置，同词不同义，但类型立刻分得清（Rust 的 `str::replace` 也这么叫），不改。

### 改名表（20 个槽位，18 个函数）

| callee | 旧 | 新 | 理由 |
|---|---|---|---|
| `list.find` | `pred` | `f` | 同模块 `filter/any/all/none` 与 prelude `filter` 都叫 `f` |
| `bytes.slice` | `start` | `from` | `str/list/cursor.slice` 与 `range` 都是 `from, to` |
| `bytes.slice` | `end` | `to` | 同上 |
| `bytes.index_of` | `needle` | `sub` | `str.index_of` 等六处都是 `sub` |
| `fmt.dtoa` | `v` | `x` | Float 标量全库是 `x` |
| `gpu.view_atomic_bf16_ref` | `_dtypes` | `dtypes` | 与 134 个兄弟一致；下划线把实现细节漏进了 API |
| `gpu.view_atomic_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.dtype_i16_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.dtype_i64_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.dtype_i4_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.pack_roundtrip_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.dtype_convert_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.dtype_e2m1_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.mmaf_scaled_ref` | `_dtypes` | `dtypes` | 同上 |
| `gpu.ref_atan` | `t` | `x` | 标量数学族另外 12 个都是 `x` |
| `gpu.ref_atan2` | `a` | `y` | 顺序敏感：第一个就是 y，C 的 `atan2(y, x)` |
| `gpu.ref_atan2` | `b` | `x` | 同上 |
| `gpu.pack_to` | `data` | `xs` | 11 个 `pack_<dt>(xs)` 的泛化版 |
| `gpu.unpack_from` | `raw` | `b` | 11 个 `unpack_<dt>(b)` 的泛化版 |
| prelude `Index.index` | `c` | `it` | 与 `Iter` 的接收者同名；`c` 在相邻的 `Iter` 里是游标 |

> **0.82.0 起表中 `gpu.*_ref` 与 `gpu.ref_atan` / `gpu.ref_atan2` 这 12 行（11 个函数）已迁出 std**，
> 到源码包 `packages/tileref`（写作 `tileref/ref.<name>`），形参名照上表不变。它们从此不受
> `Param-Change` 冻结门管（它只看 std）；理由与实测见
> [tile-backend-design.md](tile-backend-design.md) §5.3「参考实现迁出」。`gpu.pack_to` /
> `gpu.unpack_from` 两行仍在 std。

同批把 `bytes.slice` 包的内部 intrinsic `bytes_slice` 的形参也改成 `from, to`
（它不是 pub 面，改它只为读源码的人看到同一套名字），`selfhost/builtins.dawn` 镜像随改。
刀 a（#293，同在 v0.80.0）已把 prelude `Iter` 的四个方法改成接收者 `it`、游标 `c`，
共 7 个槽位；v0.80.0 的 release note 把两刀的 27 行列在一张表里。

**破坏面是零**：用编译器自己的 parser 扫本仓 863 个 `.dawn` 与 backend-dawn 44 个文件，
没有一处按名传实参调用 std。selfhost 对 std 也不用具名实参，所以这一批不需要一代转发器
（本来也做不了：同名函数不能并存）。

### 冻结门

从这一版起形参名按 API 冻结：`scripts/selfhost-param-diff.sh`（prev-diff job 的一步）
拿种子（N−1）的 `doc --stdlib` 与 HEAD 的比，每个两边都在的 callee 按位置比形参名，
每处变化都要在提交信息里声明：

```
Param-Change(<item>): <old> -> <new>
```

`<item>` 是 `<module>.<fn>`、`<module>.<Trait>.<method>`、`<module>.<Effect>.<op>`、
`prelude.<Trait>.<method>` 或 `builtins.<fn>`；一个槽位一行；删掉一个形参写 `<old> -> -`。
不接受通配与裸 `Param-Change:`，解析不了就判红；item 不在 N−1 里、`<old>` 不是 N−1 的名字，
也判红。声明窗口与 `Emit-Change` 相同（`seed-release..HEAD`），但不复用它的标签表：
item 集合就是 N−1 快照本身，每版都变，塞进 `emit-labels.txt` 等于每加一个 std 函数就改一次
登记表。比较与声明解析在 `scripts/param-change.py`（带 `--self-test`），头部注释写了
为什么种子必须显式 `--std`、以及拿什么证明它真读了那份 std。
