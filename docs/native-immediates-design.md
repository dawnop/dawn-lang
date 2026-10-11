# native：擦除位置的 Int 与 Bool 用低位标记立即数

> 状态：**current**（已裁决：`agent-handoff/ruling-native-immediates-20261011.md`；调研 `agent-handoff/research-native-immediates-20261011.md`，原型数据在其 §3）。native 性能线刀 4。2026-10-11，基线 `origin/main` = edea789b（含 #696 偷字段、#690 栈帧瘦身、#687 slab 衰减）。
> 依据：调研里的原型（运行时副本加改写后的发射 C）：counter 1 亿次 3.292 s → 1.792 s，callgrind 每次迭代 861 → 389 条指令；`agent-handoff/bench-koka-20261011/` 是同机 Koka 对照与消融数据。

## 一、结论

1. **擦除位置（类型变量、闭包参数与返回、证据槽、cell、`Array` 元素）里的 Int 与 Bool 不再分配盒子，改成带标记的立即数**：`void*` 的最低位为 1 表示一个值，Int 放 `(v << 1) | 1`，Bool 放 `(b << 1) | 1`。
2. **Int 仍是 64 位回绕，语义不变。** 63 位放不下的值（`[-2^62, 2^62)` 之外）回落到今天的堆盒子，所以没有任何一个 Int 值因此不可表示；wasm32 上指针只有 32 位，立即数是 31 位，更多值回落堆盒子，仍然正确。
3. **最大的风险不是慢而是段错误：** 今天所有读 header 的点都默认 `void*` 指向一个对象，立即数不指向任何东西。所以本稿的主体证据是 §四 的检查点清单：每个读 header 或读盒子的点各有一个「去掉标记判断」的变异体，必须在 ASan 或契约里变红。
4. **不做**：无参构造器立即数、小整数缓存、Float 立即数、GHC 式指针标 tag、效果单态直通，理由见 §八。**不改内联 RC 的默认值**（`-DDAWN_RT_INLINE_RC` 仍默认关，另出裁决）。

## 二、现状（基线 edea789b）

- ADT 字段是 `dawn_slot` 联合，**具体类型的 Int 字段直接存 `i64`**，ptrmask 对应位为 0；装箱只发生在擦除位置。`runtime/c/dawn_rt.h` 的 `dawn_slot` 注释自己写着「tagged pointers for small ints are a later optimisation」。
- `dawn_box_int`（`dawn_rt.c`）是一次 `dawn_alloc(16)` 加 header 初始化，没有小整数缓存；读侧 `dawn_unbox_int` 读值后 `dawn_drop`，再进通用 drop 的 `DAWN_K_BOX` 臂。Unit 已经是 immortal 单例。
- 发射侧：`emitc.dawn` 的 `box_call` 与 `CBox`（写）、`unbox_expr`（内联直读 `((dawn_box*)v)->val.i`，不释放）、`unbox_own_expr`（`dawn_unbox_int`，释放）。
- counter 每次迭代 3 个盒子（调研 §1）：闭包返回值装箱、`store(i-1)` 的参数装箱、`cell_set` 的新值装箱，每个盒子一次分配和一次完整的 `dawn_drop` 工作表。调研测得 counter 与同机 Koka 的比是 5.7 倍。
- 调研测得，nqueens-pvec、rbtree-ck-pvec、deriv 受益 0 到 3%：Int 装箱的热点集中在**效果操作与闭包的擦除 ABI**，不在容器里。所以这是对效果、闭包、`Option[Int]`、`Map[Int, _]` 这类程序的专项收益，不是通用提速。

## 三、设计

### 3.1 表示

```c
/* 一个擦除槽 p：NULL，或低位 1 的立即数，或指向带 header 的堆对象 */
dawn_is_imm(p)   = ((uintptr_t)p & 1) != 0
Int 立即数       = (void*)(((uintptr_t)v << 1) | 1)       v 在 [-2^(W-2), 2^(W-2))，W = 指针位数
读立即数         = (int64_t)((intptr_t)p >> 1)             算术右移（gcc 与 clang 都是算术）
Bool 立即数      = (void*)(((uintptr_t)b << 1) | 1)       总放得下，不存在堆上的 Bool 盒子
```

- 堆对象指针至少 8 字节对齐（`dawn_alloc` 走 slab 或 malloc，`dawn_str`、`dawn_adt` 等结构含 `int64_t`），最低位恒为 0，所以标记不会与指针混淆。NULL 不是立即数（最低位 0），Int 0 的立即数是 `1`，不会撞上 NULL。
- **回落**：`dawn_box_int(v)` 在 `v` 放得下时返回立即数，否则返回今天的堆盒子 `dawn_box_int_heap(v)`。读侧 `dawn_peek_int(p)` 看最低位决定是移位还是读盒子，所以两种形态可以在同一个程序、同一个容器里并存。
- **Bool** 的堆盒子取消（`dawn_box_bool` 总是立即数），读 Bool 不看最低位，直接移位；没有任何生产者能造出堆上的 Bool 盒子，因为声明已删。
- **Float 与 Unit 不变**：Float 的 64 位放不下，不做；Unit 已经是单例。
- 标记值**不是引用**：不分配，不计数。dup 与 drop 对它们是空操作，`dawn_is_unique` 对它们答 false，不进账本（`DAWN_LEDGER_BIRTH`/`DEATH` 只在 header 初始化与释放处计数，立即数两头都不经过，天然平衡）。

### 3.2 wasm32

站点 Demo 与全站搜索的 wasm 由 `site/build.sh` 用 `DAWN_WASM_CC`（clang-20，`--target=wasm32-wasi`）把发射的 C 和同一份 `runtime/c/dawn_rt.c` 编成 reactor。**选择：不关闭，用同一份代码，立即数位数由 `sizeof(void*)` 推出（wasm32 上 31 位）。** 装不下的值走堆盒子，这一条回落路径在 64 位主机上也被边界测试覆盖（`2^62` 附近），wasm32 只是把边界挪到 `2^30`，代码路径相同。`scripts/wasm-contract` 与 `scripts/wasm-dom-contract`（`DAWN_WASM_CC=clang-20`）是这条选择的回归，见 §六。

### 3.3 发射

- `box_call`：`RInt64 -> dawn_box_int(v)`（现在内联、返回 `void*`），`RBoolean -> dawn_box_bool(v)`；Float 与 Unit 不变。
- `unbox_expr`（借用读）：Int 与 Bool 改成 `dawn_peek_int(v)`、`dawn_peek_bool(v)`；Float 与 Unit 仍是内联直读盒子。`expect`、`unwrap_or`、`cast` 三个 intrinsic 走同一个函数，不另写。
- `unbox_own_expr`（拥有读）：名字不变，`dawn_unbox_int` 与 `dawn_unbox_bool` 在头文件里内联，立即数分支不调用任何函数。
- 运行时自己造或读擦除 Int 的地方（`from_code_points`、`bytes` 打包、GPU 参数、`Result` 里的句柄等）一并改。

## 四、标记检查点清单与变异体矩阵

下表列全「读 header 或读盒子」的点。**每一行都有一个变异体：在那一处去掉标记判断（或还原成盒子直读）。**变异体的跑法与红的证据见 §六。基线行号取自 edea789b。

| # | 点 | 文件 | 今天读什么 | 标记值上的行为 |
|---|---|---|---|---|
| P1 | `dawn_dup`（外联） | `dawn_rt.c` | `h->rc` | 原样返回，不写 |
| P2 | `dawn_dup`（内联，`DAWN_RT_INLINE_RC`） | `dawn_rt.h` | `h->rc` | 同上 |
| P3 | `dawn_drop` 的入口与快路径（外联；内联构建里是 `dawn_drop_slow`） | `dawn_rt.c` | `h0->rc` | 直接返回 |
| P4 | `dawn_drop`（内联） | `dawn_rt.h` | `h->rc` | 直接返回 |
| P5 | `dawn_ws_push`（`drop` 工作表与 `dawn_immortal` 共用；覆盖 ADT 字段、闭包捕获、数组缓冲的每个子节点） | `dawn_rt.c` | 之后弹出时读 `h->rc`、`h->kind` | 不入表 |
| P6 | `dawn_is_unique` | `dawn_rt.c` | `rc == 1` | 答 false |
| P7 | `dawn_ev_is_node` | `dawn_rt.c` | `kind` | 答 false |
| P8 | `dawn_discard` | `dawn_rt.c` | `kind` | 走「不是 continuation」的 panic，不解引用 |
| P9 | `dawn_peek_int` / `dawn_unbox_int` | `dawn_rt.h` | `((dawn_box*)b)->val.i` | 移位读值 |
| P10 | `dawn_peek_bool` / `dawn_unbox_bool` | `dawn_rt.h` | `->val.b` | 移位读值 |
| P11 | `dawn_box_int` 的放得下判断 | `dawn_rt.h` | 无 | 决定立即数还是堆盒子，错了会截断 |
| P12 | `dawn_from_code_points` | `dawn_rt.c` | `->val.i` | `dawn_peek_int` |
| P13 | `bytes` 打包循环 | `dawn_rt.c` | `->val.i` | `dawn_peek_int` |
| P14 | GPU launch 参数 | `dawn_rt.c` | `->val.i` | `dawn_peek_int` |
| P15 | emitc 的 `unbox_expr` | `emitc.dawn` | 发射 `((dawn_box*)(v))->val.i` | 发射 `dawn_peek_int(v)` |
| P16 | LSAN/账本宏 `DAWN_LEDGER_*` | `dawn_rt.c` | 计数 | 立即数不经过，计数平衡 |

不用改、但清单里点名核对过的：`dawn_adt_reset_masked` 的 `a->h.rc` 读的是**有类型的 ADT 指针**（不是擦除槽），调用方是 `match` 的 scrutinee，永远不是标记值；`dawn_own_leftover` 与 `dawn_own_drop` 只比较 NULL 与调用 `dawn_drop`；哈希与相等走字典里的类型化函数（适配器先 `unbox_own_expr` 再比较），不看 `kind`；`dawn_array_*` 与 `dawn_cell_*` 对元素只做 `dawn_dup`、`dawn_drop` 和搬运。

## 五、边界测试

- 立即数边界：`-2^62`、`-2^62 - 1`、`2^62 - 1`、`2^62`，以及 `INT64_MIN`、`INT64_MAX`、0、1、-1；经 `dawn_box_int` 装箱再 `dawn_peek_int` 读出，必须逐位相等，并检查它们落在哪一侧（立即数还是堆盒子）。
- 回绕：`2^62 - 1` 加 1、`-2^62` 减 1、`INT64_MAX + 1`、`INT64_MIN - 1`，运算在具体类型的 `i64` 上做，结果跨过边界后再装箱。
- 存放：闭包捕获与返回、cell（`var` 与 `dawn_cell_set`）、效果操作的参数与返回、`List`、`Option`、`Map`、`Array` 元素、元组，写进去再读回，值与分配计数（堆盒子数量）一致。
- Bool：作为类型变量实参、闭包返回、`Option[Bool]`、`Array[Bool]`。
- dup/drop 对立即数的空操作：在 `rc-contract` 里直接断言，立即数 dup 后仍是同一个字，drop 不崩溃、不进账本。

## 六、测量与验收

（实现落地后在本节填写：变异体矩阵的红的证据、交错最短 5 次的墙钟表、callgrind 指令数、cc 时间与门禁。）

## 七、刀序

1. 本文。
2. 运行时认标记（P1 到 P14、P16）与契约、变异体；重生成 `rtsrc.dawn`。
3. 发射：`box_call`、`unbox_expr`、`unbox_own_expr` 改用立即数，附 `Emit-Change` 声明与 emitc 单测。
4. 测量与回填本文 §六。

## 八、不做的（理由）

- **无参构造器立即数**：调研原型里 rbtree 墙钟 +5%（噪声内），callgrind 指令 +3%（非内联）与 +28%（内联 RC，多出的位测试摊在每个内联 dup/drop 上）。immortal 单例的 dup/drop 本来就是「一次调用加一次比较」，换成位测试省下的只是调用，而调用可被内联 RC 吃掉。rbtree 里 Color 的开销真正的解法是偷字段（#696）。除非先把 NULL 并入标记、让 RC 路径只剩一次测试，否则不做。
- **小整数缓存**：counter 的值域 0 到 1e8，命中率约 0.07%；其余场景被立即数完全取代。
- **Float 立即数 / NaN 装箱**：63 位放不下 `double`，Koka 的 NaN 装箱复杂度高；Dawn 的 Float 热路径多在具体类型位置，装箱不是瓶颈。
- **GHC 式指针标 tag**：所有指针产生点都要打标、所有解引用点都要掩码，是全局改动；收益主要是省间接跳转，而 Dawn 的 `match` 现在是一次 load 加比较，不是瓶颈。
- **效果操作按单态签名直通 ABI**：不依赖标记，但要碰「擦除的证据槽」并出第二套闭包入口，且只覆盖效果。立即数落地后 counter 剩下的主要是闭包 ABI 与 cell 的调用，量过再决定。
- **改内联 RC 的默认值**：不在本裁决内。10-04 的 ffi-llvm 裁决 4.a 记有 cc CPU +83% 的代价，立即数落地后用实测另出裁决。
- **让 Bool 的读看最低位**：堆上的 Bool 盒子在本改动后不存在，多一个分支没有对应的值。
