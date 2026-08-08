# native failure runtime 重设计（#193）

> 状态：**current** —— 定稿。裁决：**刀 1（载荷对象化）+ 路线 A3（平台 unwinder）采纳；
> 路线 B（Result ABI）不做**，理由与重开条件见 §4.3/§8。落地按 §6 的刀序，
> 逐刀进度见各刀末尾的「落地」行。
>
> 勘察基线 `abe5105`（2026-08-08），编译器 `dawn 0.60.0 (selfhost)`；落地基线
> `138adb9`（同日，含 #199/#197 两批——与本文相关的文件 `runtime/c/`、`selfhost/src/c/`、
> spike 脚本在两基线间零改动，file:line 引用仍然成立）。复现程序已收编为
> `scripts/spike-native/` 语料（对应关系见 §5.2 与 §6 刀 0）；本文所有带「实测」的
> 数字都出自它们的前身，没有实测的判断一律标「推断」。

---

## 1. 问题：三个缺陷是不是同一件事

审查把 ARC-03/04/05 并列为 P1，任务书说它们「三件同根：裸 setjmp/longjmp 丢帧、
无显式 cleanup/payload 栈」。**实测之后这个判断要改：它们是两件事，不是一件。**

| | 缺陷 | 根因 | 修它要动谁 |
|---|---|---|---|
| ARC-03 | 消息截断 512 | 失败载荷是一个**固定大小的全局 buffer** | 只动 `runtime/c/dawn_rt.c` |
| ARC-04 | 嵌套 release 覆盖载荷 | 失败载荷是**全局的**（不属于任何 handler） | 只动 `runtime/c/dawn_rt.c` |
| ARC-05 | 恢复路径泄漏 | `longjmp` **跳过被丢弃帧的 drop** | 动 emitter + 运行时 + 编译标志 |

前两件的根因是「载荷的所有权」，第三件的根因是「非局部跳转不跑清理」。载荷问题
在设计上与 setjmp 无关——就算把 setjmp 换成任何别的机制，一个 `static char[512]`
仍然会截断、仍然会被嵌套覆盖。**把三件绑成一刀，等于让两件便宜的修复等一件贵的。**

这直接决定了刀法（§6）：刀 1 只修载荷，不碰 unwind。

### 1.1 ARC-03 复现（实测）

复现程序 `p1_truncate.dawn`（今为语料 `failure_message.dawn`）：把长度递增的消息交给 `panic`，
在 `catch_panic` 里读回 `ForeignError.message`。

```
                     JVM              native
k=100    len=104 tail_ok=true   len=104 tail_ok=true
k=511    len=515 tail_ok=true   len=512 tail_ok=false
k=512    len=516 tail_ok=true   len=512 tail_ok=false
k=600    len=604 tail_ok=true   len=512 tail_ok=false
k=5000   len=5004 tail_ok=true  len=512 tail_ok=false
utf8     len=304 tail_ok=true   len=256 tail_ok=false
```

截断发生在 `dawn_raise` 往全局 buffer 拷贝的那一行：`runtime/c/dawn_rt.c:805`
（`dawn_failure_len = msg->len < DAWN_FAILURE_MAX ? msg->len : DAWN_FAILURE_MAX`），
上限定义在 `:773`，buffer 在 `:774`。**截断在 raise 层，不在读取层**——
`dawn_foreign_error`（`:829`）只是照抄 buffer 里剩下的东西。

`p1b_utf8cut.dawn` 把切点顶到字符中间（1 个 ASCII 字节 + 400 个 `é`，第 512 字节
正好是某个 `é` 的前导字节）：

```
        JVM     native
bytes   801     512
chars   401     257
last    169     195     # 195 = 0xC3，一个孤立的 UTF-8 前导字节
```

native 交回了一个**以半个字符结尾的 String**。这不只是「消息短了」——#113 落下的
不变式「String 里没有非良构 UTF-8」在这里被运行时自己破坏了（`str.len` 把那半个
字符当成一个字符数了进去，257 = 1 + 255 + 1）。

### 1.2 ARC-04 复现（实测；审查记的是「S；未动态验证」，实测比它记的更严重）

复现程序 `p2_nested.dawn`（今为语料 `bracket_release_fails.dawn`）：`bracket` 的 `release` 里自己用
`catch_panic` / `catch_fault` 接住一个失败并咽掉——完全合法的写法，从程序的角度看
什么都没逃出去。外层失败应当原样穿过 bracket。

| 场景 | JVM | native |
|---|---|---|
| 外 panic，release 咽下 panic | `OUTER-r1` / `dawn.rt.PanicError` | **`INNER-FROM-RELEASE`** / `panic` |
| 外 panic，release 咽下 fault | `OUTER-r2` / `PanicError` | **`io_read_file: cannot open file`** / **`fault`** |
| 外 fault，release 咽下 panic | 正常接住，`kind=NoSuchFileException` | **进程死掉，exit 1，stderr `panic: INNER-FROM-RELEASE`** |

三行都是 spec §9.8.2 保证 2（`spec.en.md:1932-1936`，「kind/message 逐字不变，
panic 还是 panic，fault 还是 fault」）的直接违反。第三行最重：**一个本来可恢复的
fault 变成了进程退出**——因为 `dawn_failure_is_panic`（`:789`）被内层写成了 true，
`dawn_reraise`（`:871`）于是把它路由成 panic，外面的 `catch_fault` 按定义拒收，
链上再无 handler，`exit(1)`。

反向同样成立，而且是安全面。`p2b_kindflip.dawn` 用 `bracket.dawn` 那个 `barrier`
的形状问「panic 穿过一个 release 咽过 fault 的 bracket 之后，io 屏障收不收」：

```
JVM     verdict  through     # catch_fault 放行 panic，正确
native  verdict  caught      # catch_fault 吞掉了一个 panic
```

`catch_fault` 吞 panic 正是 `catch_kinds.dawn` 整篇存在的理由，也是
`docs/native-backend-plan.md:1072-1120` 那次修复的主题。它今天又回来了，
只是需要 release 里有一次嵌套捕获才触发——而现有语料的 `close` 从不失败，
所以门禁看不见（§3.4）。

### 1.3 ARC-05 复现（实测，含对审查描述的一处修正）

复现程序 `p3c_live.dawn`（今为语料 `recover_live.dawn`）：一个引用**活过** raise（raise 之后
还要读它），100 次 `catch_panic`：

```
LeakSanitizer: 412100 byte(s) leaked in 100 allocation(s)
```

412100 / 100 = 4121 = 4096 载荷 + 25 字节头。**泄漏量与被丢弃帧持有的活数据成正比**，
一次恢复一份，不封顶。

**修正一：泄漏不等于「作用域里有对象」。** 最初的 `p3_leak.dawn` 把大字符串
`let more = big ++ "..."` 之后立刻 `str.len(more)`，LSan 只报了 6490 字节 / 200 个
对象——因为最后使用分析（`docs/perceus-design.md:458` §5.8）已经把值**转移**进
`str.len` 并在那里释放了，raise 时帧里根本没有活引用。所以复现必须刻意让引用
跨过 raise 才算数；`p3b_leaksize.dawn`（同样形状、4096 字节、无跨越）**零泄漏**。
这条对写门禁语料是硬要求：**语料写不对，ARC-05 会伪装成已修好。**

**修正二：还有第二个泄漏源，审查没点名——raise 自己的消息。**
`p3d_msg.dawn`（帧里什么都不活，只是消息是算出来的 1000+ 字节）：

```
LeakSanitizer: 103790 byte(s) leaked in 100 allocation(s)   # 1038 B / 次
```

`panic` 是 intrinsic，按约定**借用**实参（`docs/perceus-design.md` §5.1），
调用点本该释放它——但调用点在 raise 之后，永远不会执行到。于是**每一次 raise 都
漏掉自己的消息**，与帧里活不活引用无关。这一条在路线 A 里由 unwind 清理顺手解决，
在「只修载荷」的刀 1 里**不**解决（刀 1 只是把消息复制进载荷，原件仍然漏）。

`p3e_bracket.dawn`（bracket 的 use 抛 fault，资源 2048 字节）：100 圈漏 400 个对象
/ 422780 字节，即每圈 4 个——运行时注释（`:899-903`）只承认了「use 的引用」一个。

---

## 2. 现状机制盘点

### 2.1 native（C）

```
dawn_handler { jmp_buf jb; dawn_handler *prev; bool catches_panic; }   :762
static dawn_handler *dawn_handlers;                                     :768   ← 全局链
static char  dawn_failure_buf[512];                                     :773-774 ← 全局载荷
static int64_t dawn_failure_len;                                        :775
static const char *dawn_failure_kind = "panic";                         :780
static bool dawn_failure_is_panic = true;                               :789
```

- `dawn_find_handler(is_panic)`（`:792`）：从内向外找第一个肯收这个 kind 的 handler；
  panic 会跳过 `catches_panic == false` 的 io 屏障。
- `dawn_raise`（`:798`）：写四个全局，然后 `longjmp`。无 handler 则 `fputs` + `exit(1)`
  ——**这条路径用的是原始 `msg`，所以不截断**；截断只发生在被接住的失败上。
- `dawn_run_caught`（`:839`）：压 handler → `setjmp` → 跑闭包 → 弹 handler。
  非零返回时先弹栈再 `dawn_foreign_error()`（`:829`）从全局造 `ForeignError`。
- `dawn_bracket`（`:908`）：压一个 `catches_panic = true` 的 handler，
  unwind 分支先弹栈、跑 `release`、再 `dawn_reraise()`（`:871`）。
  **`release` 与 `dawn_reraise` 之间隔着任意用户代码，而载荷是全局的** —— ARC-04 就是这条缝。

emitter 侧几乎不参与：`catch_fault` / `catch_panic` / `bracket` 走的是
`rt_symbol`（`selfhost/src/c/emitc.dawn:1266-1274`）那张「模块拥有这个原语、
名字就是语言里的名字」的表，发射成 `dawn_catch_fault(...)` 一类的普通调用；
只有 `panic` / `todo` 在 `emit_intrinsic` 里各有一条臂
（`emitc.dawn:1356`、`:1358`）。**所以载荷的修法完全落在运行时里。**

### 2.2 JVM

无任何全局失败状态（唯一的静态字段是 `Unit.INSTANCE` / `Io.stdin` / Unicode 表）。

- `panic` → `NEW dawn/rt/PanicError; ATHROW`（`selfhost/src/jvm/emit.dawn:2356-2364`），
  `PanicError extends java/lang/Error`（`selfhost/src/jvm/rtclasses.dawn:108`）。
- 两个屏障共用 `gen_try_closure`（`rtclasses.dawn:843-867`）：
  `catch_fault` 只 catch `java/lang/Exception`（`:1074`），
  `catch_panic` 两行异常表 `PanicError` + `Exception`（`:1082`），**都不 catch `Throwable`**。
- `ForeignError` 由 `gen_caught_err`（`:953-1007`）造：
  `kind = getClass().getName()`（`:960-963`），
  `message = getMessage()`，null 换空串（`:965-973`），**无长度上限、无拷贝**。
- `bracket`（`:907-944`）是**手写 try/catch 重抛**，不是 finally：
  正常路径与 unwind 路径各发射一次 `release`（`:925-930` / `:934-941`），
  unwind 路径 `ASTORE 4` 存住原 `Throwable`、跑完 release 再 `ATHROW` **同一个对象**。
  于是 kind/message/栈迹全部原样，**release 内部咽掉别的失败对它毫无影响**。

### 2.3 两后端失败语义差异表

| 维度 | JVM | native 今天 | 规范怎么说 |
|---|---|---|---|
| 失败载体 | Throwable 对象，每个失败一个 | 一个进程全局 buffer + 三个全局标量 | 未规定机制 |
| message 长度 | 无限 | **≤512 字节，可切在字符中间** | `message` 是失败自己的 message（`spec.en.md:1873-1875`），**无任何长度条款** |
| kind | 类的 binary name | `"panic"` / `"fault"` | **按定义后端自有**，不可移植（`spec.en.md:1866-1872`） |
| cause | `getCause().toString()` | 恒 `None` | 允许 |
| bracket 保原失败 | 重抛同一对象，天然成立 | **嵌套捕获会替换掉它**（§1.2） | 保证 2：逐字不变（`spec.en.md:1932-1936`） |
| release 恰一次 | 两条路径各发射一次 | 两条路径各调一次 | 保证 1（`spec.en.md:1930-1931`） |
| release 自己抛 | 顶掉原失败，无 suppressed | 顶掉原失败 | **两边都没规定**（勘察确认 spec/docs 零命中） |
| 恢复后的内存 | 收集器负责 | **漏掉丢弃帧的活引用 + raise 的消息** | 规范无条款；`perceus-design.md:449-453` 记为设计内例外 |
| 资源耗尽 | `VirtualMachineError` 穿过两个屏障 | 栈溢出 = 静默崩溃（`dawn_rt.h:394-401` 明写不装 SIGSEGV handler） | `spec.en.md:1836-1838` 要求穿过 |

---

## 3. 约束盘点

### 3.1 规范红线（改不动的）

- 判据：**语言自己定义的失败是 panic，外部世界造成的不是**（`spec.en.md:1846-1854`），
  且这条明说「与后端无关」。
- `catch_fault` 不收 panic（`:1826-1828`）；`catch_panic` 收 panic+Exception 但不收资源耗尽（`:1836-1838`）。
- `ForeignError` 形状与 `message` 语义（`:1863`、`:1873-1875`），**不带栈**。
- bracket 三条保证（`:1928-1940`），其中保证 2 是逐字。
- 两后端可观察一致（`:2414-2418`），但 `kind` 取值被显式挖了洞（`:1866-1872`）。

**规范里没有 512、没有 `DAWN_FAILURE_MAX`、没有任何截断条款**（勘察在 `spec.md` /
`spec.en.md` 全文零命中）。所以去掉上限不是「放宽规范」，是**停止违反规范**。

### 3.2 Perceus 账本

- 插入规则与非局部退出的作用域栈：`docs/perceus-design.md:286`（§5.2）、`:336`（§5.3）。
  §5.3 那张表已经把「`CReturn` 要 drop 函数内全部层 / `CBreak` 到 loop 层为止」写死了
  ——**这正是任何 cleanup 方案需要的那份信息，pass 里已经有了。**
- 本地 oracle `rc_check`（`selfhost/src/c/rc.dawn:1566`），由 `rc_module` **硬断言**
  （`rc.dawn:1317-1320`，不平衡直接 panic）。它管的是**结构平衡**：每个绑定在每条
  路径上恰好释放一次，释放 = drop **或转移**。
- 它看不见的两半，都与本题相关（`rc.dawn:27-32`）：
  1. dup 数是否等于消费性使用数——语料是 spike-native 的 asan；
  2. **它完全看不见 longjmp**：Core 里没有这条边，所以 ARC-05 在 `rc_check` 眼里
     根本不存在。修 ARC-05 不会让 `rc_check` 变红，也不会被它保护。
- `--rc=leak` 实际是环境变量 `DAWN_RC_LEAK`（`dawn_rt.c:46`），drop 变 no-op，
  用来把 codegen bug 与计数 bug 拆开——改 unwind 时这是现成的二分工具。

### 3.3 bracket / 错误模型的既有裁决

- `CSProtect` / `LProtect`（Core 层的 protect 节点）**已关档不做**，
  `docs/audit/error-model-design.md:205-215`：「bracket 以运行时 intrinsic 落地（v0.39.0）」，
  「**推翻需新证据**」。本文的路线 A 不需要这个节点（§4.2），路线 B 需要（§4.3）——
  这是判据之一。
- 资源是**值**不是 acquire 闭包，理由是 Dawn 没有异步失败（`spec.en.md:1909-1916`）。
  新方案不得引入这个窗口。
- 尾恢复档效果处理器**不欠 unwind**：`docs/effects-design.md:39-40` 明确把
  aborting handler 推回既有屏障族，`:197-201`「没有栈魔法可失效」。
  **所以效果系统不会在将来逼出一个通用 unwind 机制**，本题可以只按失败模型定形。
- `io.exit` 的四条出口根本没有栈可退（`docs/core-move2-design.md:366-369`），
  与本题无关但别顺手改。

### 3.4 门禁现状（含两个洞）

| 门禁 | 位置 | 与本题的关系 |
|---|---|---|
| spike-native 差分 + asan/lsan | `scripts/spike-native/run.sh`，CI job `native-diff`（`gates.yml:347-348`） | 主战场 |
| `.leaks-on-catch` 豁免 | `run.sh:211-213` | **ARC-05 的 oracle 就是这个开关**，今天有 7 个文件开着 |
| rc-contract | `scripts/rc-contract/run.sh`，CI（`gates.yml:265-266`） | 运行时 dup/drop 的 C 级契约 |
| native-cli-diff | CI（`gates.yml:460-461`） | **`:397-405` 刻意把消息压在 512 以下**，注释直说这是真分歧 |
| native-fixpoint（B==C） | `scripts/native-fixpoint.sh` | **不在 CI**（`native-fixpoint.sh:8-10` 有意），手动里程碑门禁 |
| 五语料 / prev-diff | `scripts/selfhost-prev-diff.sh` | 只有改到 `rtsrc.dawn` 或 emitter 才会红（§7） |

7 个 `.leaks-on-catch`：`bracket`、`bracket_fatal`、`catch_kinds`、`foreign_error`、
`index_panic_text`、`io_run`、`io_utf8`。

**洞一：现有语料的 `release` 从不失败**，所以 ARC-04 整类缺陷零覆盖。
**洞二：`.leaks-on-catch` 是「关掉检测」而不是「记账」**——它既不断言泄漏量，
也不断言泄漏只发生在预期形状上，所以那 7 个程序里任何**新的**计数漏洞都进不了视野。
这一条比 ARC-05 本身更值得写进裁决：门禁的绿在这 7 个文件上没有信息量。

---

## 4. 路线对比与推荐

先把**必做且与路线无关**的那部分摘出来，否则比较会被它污染。

### 4.0 刀 1（与路线无关）：载荷对象化

把四个全局换成**每个 handler 帧自己拥有的一个载荷对象**：

```c
typedef struct dawn_failure {
  dawn_str *msg;       /* 完整字节，运行时拥有 */
  const char *kind;    /* 静态字面量，仍然不拷贝 */
  bool is_panic;
} dawn_failure;

typedef struct dawn_handler {
  jmp_buf jb;
  struct dawn_handler *prev;
  bool catches_panic;
  dawn_failure f;      /* ← 新增：这个 handler 将要收到的那个失败 */
} dawn_handler;
```

- `dawn_raise`：找到 handler `h`，**把载荷写进 `h->f`**（不是全局），再 longjmp。
- `dawn_run_caught`：`setjmp` 非零分支从 `h.f` 造 `ForeignError`，然后释放 `h.f.msg`。
- `dawn_bracket`：unwind 分支先把 `h.f` **搬到自己的局部**（所有权转移），
  再跑 `release`，再 `dawn_reraise(saved)` —— 把这个载荷写进下一个 handler。
  release 内部的嵌套 handler 有自己的帧、自己的 `f`，**够不着这一份**。
- 无 handler 的致命路径：raise 用原 `msg` 打印（今天就对），reraise 用手上的载荷打印
  （今天截断，改后不截断）。

**这一刀把 ARC-03 和 ARC-04 一起修掉，只动 `runtime/c/dawn_rt.c`，
不动 emitter、不动 JVM、不改任何 ABI，约 80 行。** 消息长度上限直接消失
（载荷持有一个正常的 `dawn_str`，与其他堆对象无异）。

它**不**修 ARC-05：raise 的消息仍然漏（§1.3 修正二），丢弃帧的引用仍然漏。

### 4.1 路线 A：显式 cleanup（保留 setjmp 作为「落地」，unwind 时跑清理）

分两个可实现的形态，语义相同、代价不同。

#### A1 — 自建影子栈

每个持有引用的函数在入口压一条 cleanup 记录（一个指向本帧 owned slot 数组的指针），
出口弹出；raise 时运行时从栈顶走到 handler，逐帧释放非 NULL 的 slot。
emitter 必须把 owned 绑定放进**帧内的连续数组**而不是普通 C 局部变量。

- 优点：纯 C11，零编译器方言，任何平台都成立。
- 代价：owned 局部被强制落到内存，寄存器分配失效——**这是真代价，且遍布热路径**
  （selfhost 的 C 里有 26482 个 dup、31778 个 drop 站点，量级见 §4.4）。
- 推断：这条会在编译器自身的跑分上留下可测的退步；未实测。

#### A3 — 平台 unwinder（`-fexceptions` + `__attribute__((cleanup))` + `_Unwind_ForcedUnwind`）

owned 绑定照旧是普通 C 局部，只是带上 cleanup 属性；raise 改成强制 unwind，
stop 函数在到达 handler 帧时 longjmp 进它的 `setjmp` 分支。
**清理由 C 编译器生成的 landing pad 负责，正常路径零表以外的开销。**

实测（本机 gcc 13，勘察期 spike `unwind_spike.c`，未入库）：
三层帧、每帧两个带 cleanup 的对象，raise 之后 —

```
round 0 -> raise boom / drop inner-b / drop inner-a / drop middle-m / caught
...
live objects after 3 catches: 0
```

**清理按内向外逐帧运行，三次恢复后存活对象归零。** 机制在这条工具链上成立。

正常路径代价，两个实测：

1. 把真正的 `selfhost` 发射出的 C（186111 行）分别用带不带 `-fexceptions` 编译：
   text 段 2468181 → 2468469 字节（**+288 字节，+0.01%**），二进制 3064840 → 3064848；
   同一任务（`fmt --check` 两个大文件）两遍各测：0.97/0.98 s 与 0.98/0.96 s，**无可测差异**。
   cc 自身耗时 15.0 s → 16.1 s。
2. cleanup 属性 vs 显式 drop 的微基准（`cleanup_bench.c`，2000 万圈，
   `-fno-builtin-malloc` 防止 malloc/free 对被消掉）：

   | | 显式 drop | cleanup 属性 |
   |---|---|---|
   | 作用域末释放 | 0.173 / 0.191 / 0.195 s | 0.187 / 0.169 / 0.185 s |
   | 转移（+ 置 NULL） | 0.103 / 0.091 / 0.110 s | 0.090 / 0.086 / 0.086 s |

   **噪声内。** 注意这是微基准不是真实语料，只能说明「没有量级代价」，
   不能说明「真语料上是 0」。

emitter 需要做的事，比想象的小：

- owned 绑定的声明加属性；
- **RC pass 说「这里释放了」的每一处（drop 或转移），都要把 slot 置 NULL**
  ——而这两类站点正是 `rc_check` 已经在枚举的那一组（`rc.dawn:27-32`），
  所以这不是新分析，是把已有分析的结论多写一次。
- C 块结构必须与 Dawn 作用域对齐（cleanup 在 C 块出口跑）；这条要在动工前核对 emitc。

风险清单：
- `_Unwind_ForcedUnwind` 是 Itanium C++ ABI 的东西，glibc 的 pthread cancel 就靠它；
  **Apple 平台是否可用需要单独验证**（`docs/native-backend-plan.md:43` 说 macOS「应接近免费」）。
  没验之前不能写进计划。musl 同样待验。
- 今天的 `runtime/c/dawn_rt.{c,h}` **一个编译器方言都没用**（全文只有一个 `_Noreturn`）。
  A3 会打破这一点，是要自觉付的一笔一致性税。
- stop 函数如何精确认出 handler 帧：spike 里用的是「CFA ≥ handler 结构体地址」，
  能跑但粗糙；正式实现要用记录下来的帧地址做相等判定，并对「handler 帧被内联掉」
  做防御。
- cleanup **不**在 longjmp 上运行。所以 handler 落地那一跳必须是整条路径上唯一的
  longjmp，且它上面的帧必须已经被 unwinder 清理过——spike 验证的正是这一点。

### 4.2 路线 B：Result 式 unwind ABI（错误按返回值层层上传）

每个可能失败的函数多一个出参 `dawn_failure **err`；每个调用点后插一次分支，
失败就跳到本帧的 unwind 标号，跑本帧的 drop，再把错误返给调用者。
`setjmp`/`longjmp` 整体消失。

**量化（实测，`dawn __emitc selfhost/src/nmain.dawn`）：**

| | |
|---|---|
| 发射出的 C | 186111 行 |
| 顶层 C 函数定义 | 2120 |
| Dawn→Dawn 调用点（mangled 符号） | **21656** |
| 运行时函数调用点 | 92411 |
| `dawn_panic(...)` 站点 | 1580 |
| `dawn_dup` / `dawn_drop` | 26482 / 31778 |

也就是说：**光 selfhost 一个语料就要插两万一千多个分支、两千多个 unwind 标号，
并且每个函数签名、每个闭包适配器、每个字典槽、每个 erased 槽都要改。**
运行时里回调 Dawn 闭包的地方（排序比较器、io hook）也要跟着改 ABI。

而且 Dawn 这门语言把这条路线的代价推到最大：**失败不在效果行里**。
任何函数都可能 panic（下标、除零、`expect`），所以「哪些函数需要 err 出参」的答案
是「全部」——没有任何一处能靠类型省下来。这一点与 Rust/Swift 那种「Result 文化」
的直觉相反：那些语言里可失败是**类型上标出来的少数**，这里是**全体**。

它真正的优点只有一个，但很硬：**账本天生平**。所有退出都是普通返回，
失败路径上的 drop 就是 `CReturn` 的 drop，`rc.dawn` §5.3 那张表已经覆盖，
`rc_check` 这个既有 oracle 直接就能证明它——不需要任何新门禁。
路线 A 得不到这个：`rc_check` 看不见 unwind（§3.2），正确性要靠 LSan 语料来证。

另外两个附带好处，都指向将来而不是现在：LLVM / wasm 后端不必依赖 unwinder
（`docs/llvm-backend-research.md:170-173` 当初推荐 setjmp/longjmp 时也承认这一层），
以及不再需要 `CSProtect` 之外的任何东西——但它本身要求把 protect 的形状放回 Core，
而那个节点是**已关档的裁决**（§3.3），推翻它要新证据。

代价估计（**推断，未实测**）：两万个分支绝大多数完美预测，但多一个出参会抬高
寄存器压力、阻断部分尾调用与内联；量级猜 3–10%，需要原型才能定。

### 4.3 推荐

**推荐：刀 1（载荷对象化）立刻做；ARC-05 走路线 A3，A1 作为不支持平台的回退；
路线 B 记录为「不做」，但写下重开条件。**

四条判据逐条对照：

| 判据 | A3 | B |
|---|---|---|
| 与 Perceus 的相容性 | 清理由 C 编译器生成，RC pass 只多写一个「置 NULL」；`rc_check` 看不见它，正确性靠 LSan 语料 | **账本天生平**，`rc_check` 直接覆盖；这是 B 唯一的、也是真实的优势 |
| 两后端语义收敛度 | 收敛到 JVM 语义（JVM 也是「清理跑在 unwind 上」）；机制不同、语义同 | 同样收敛，但 native 的实现形状离 JVM 更远 |
| 实现工作量 | 运行时 ~150 行 + emitter 两处机械改动（声明形式、释放点置 NULL）+ 一个编译标志 | **每个函数签名 + 21656 个调用点 + 全部 ABI 面**；跨 emitc/rc/lower/运行时/intrinsic 表 |
| 对 bracket/catch_fault 既有承诺 | 全部保持；bracket 仍是运行时 intrinsic，无需 Core 节点 | 需要把 protect 形状放回 Core，撞上已关档裁决 |

补充两条不在表里的：

1. **B 让致命路径也付钱。** 未被接住的失败今天是「打印 + exit(1)」，一步到位；
   B 之下它要一层层返回到 main 才知道没人接。A3 保持一步到位。
2. **A3 的 oracle 已经建好了。** 那 7 个 `.leaks-on-catch` 标记就是验收条件：
   删掉它们、spike-native 全绿，就是 ARC-05 修好的机器证明。B 需要的新门禁反而更少
   （`rc_check` 已在），但 B 的**改动本身**大到需要它自己的一整套护航。

重开路线 B 的条件（写下来，省得三个月后重想）：
- 出现一个没有可用 unwinder 的目标（wasm、某个 freestanding 平台），且必须支持恢复；
- 或者 A3 在 macOS/musl 上被证明不可行，而 A1 的内存化代价实测超过某个阈值；
- 或者失败进入效果行（`!fail`），使「需要 err 出参的函数」从全体缩小到少数
  ——那时 B 的代价函数完全变样，值得重算。

---

## 5. failure payload 的契约化

把「载荷」从一个实现细节升成后端契约，写进 `docs/spec.md` §9.8.1 旁边一小节
（**只写可观察的部分**，机制不进规范），并由门禁负例钉住。

### 5.1 契约条款

1. **所有权**：一个失败的载荷属于**将要接住它的那个 handler**，从 raise 写入到
   barrier 造出 `ForeignError`（或 bracket 交给下一个 handler）为止。
   任何其他 handler 都不能读写它。
2. **嵌套**：在 handler 的清理代码（`bracket` 的 `release`，或将来的等价物）内部
   raise 并接住一个新失败，**对外层载荷没有任何影响**——kind、message、panic 位
   全部保持。这是 §9.8.2 保证 2 在「release 自己也会失败」情形下的展开。
3. **message 字节**：**没有上限**，逐字节等于 raise 拿到的那个 String；
   两后端逐字节相同。**显式上限不设**——理由：设一个上限就要选一个数字，
   而任何数字都会在某天被一条合法消息越过，且截断点还得处理字符边界；
   载荷是个普通堆对象，不设限反而是更简单的实现。
4. **String 不变式**：载荷交回的 `message` 必须是良构 UTF-8（#113 的不变式）。
   这条在契约里显式写出来，因为今天正是它被破坏（§1.1）。
5. **kind**：仍然是后端自有的名字（`spec.en.md:1866-1872` 不变），
   但 **panic/fault 这个二分是可观察的**，由「哪个屏障收得下」体现，不由字符串体现。
6. **release 自己失败（逃逸而非咽下）**：今天两后端都是「顶掉原失败、无 suppressed」，
   规范零条款。建议**明确写下现状**（原失败丢失）而不是趁机改语义——改它要设计
   suppressed 链，属于另一个题目。写下来的价值是：它从此是裁决，不是巧合。

### 5.2 门禁怎么写

**双后端负例，进 `scripts/spike-native/`**（CI job `native-diff` 跑它），
理由：这一族的判据全是「两后端答案必须一样」，而 spike-native 是唯一同时跑
JVM、native、`.expect` 三方的地方；`.expect` 是唯一不来自任何后端的独立 oracle
（`run.sh:59-64`）。

新增语料（建议名字与形状）：

| 文件 | 问的问题 | 关键点 |
|---|---|---|
| `failure_message.dawn` | 消息长度 0 / 1 / 511 / 512 / 513 / 5000，以及在 512 字节处**切在字符中间**的那条 | 就是 `p1_truncate` + `p1b_utf8cut`；断言的是长度、尾巴、以及 `str.len` 与 `bytes.len` 的关系 |
| `bracket_release_fails.dawn` | **2×2 矩阵**：外层 {panic, fault} × release 内部咽下 {panic, fault} | 就是 `p2_nested`；再加 `barrier` 形状问「io 屏障收不收」（`p2b_kindflip`） |
| `bracket_release_fatal.dawn` | 同上但外层无人接，比对两后端的 stderr 与退出码 | 需要 `.exits-nonzero` 标记 |
| `catch_nested_payload.dawn` | 不经 bracket 的嵌套：handler 里再 catch | 今天就对，但契约条款 1 要有正例钉住 |

`native-cli-diff.sh` 那条腿要动两处：删掉 `:397-405`「每条消息都压在 512 以下」的
自我设限，并**新增一条超过 512 字节的 panic 消息**，让 CLI 层也覆盖。

ARC-05 的门禁不是新写的，是**把已有的打开**：删掉 7 个 `.leaks-on-catch`，
并在 `run.sh` 里把 marker 机制本身删掉（连同 `:45-50` 的头部说明）——
留着一个没人用的豁免开关，等于给下一次退步准备好藏身处。

**刀 0 先行**：上面这些语料在修之前就写好、加进 `known-red.txt`。
ratchet 的双向性（`run.sh:88-112`：列进去的检查一旦转绿也是红）会把
「修好了忘了删豁免」变成硬失败。这是本仓最省事的验收方式。

---

## 6. 迁移刀法

五刀。每刀单独可合并、单独可回滚。

### 刀 0 — 负例先行

- 写 §5.2 的四个语料 + `native-cli-diff` 的长消息腿；全部列进 `known-red.txt`。
- **oracle**：新语料在 JVM 上绿、在 native 上按预期红；`known-red` 行数增加。
- 破坏面：零（只加文件）。
- **落地**（2026-08-08）：七个语料进 `scripts/spike-native/`——ARC-03/04 四件
  （`failure_message` / `bracket_release_fails` / `bracket_release_fatal` /
  `catch_nested_payload`）+ ARC-05 三件（`recover_live` / `recover_msg` /
  `recover_bracket`，无 `.leaks-on-catch` 标记，其 `:asan` 就是刀 3 的验收 oracle）。
  实测红：`failure_message:native/diff`、`bracket_release_fails:native/diff/stderr/exit`
  （第三格外层 fault 直接把进程打死）、`bracket_release_fatal:stderr`、三个
  `recover_*:asan`。长消息腿并入刀 2（在修复前加会把 `native-cli-diff` 打红，
  它没有 known-red 机制）。两处语料返工也记下：`kind` 字符串与 io fault 的
  message 都是后端自有的，语料只能问「裸奔与穿 bracket 相同」和「两个 kind 相等」，
  不能印原文。

### 刀 1 — 载荷对象化（ARC-03 + ARC-04）

- 只改 `runtime/c/dawn_rt.c`：§4.0 那个 `dawn_failure` + handler 帧持有。
- `python3 scripts/gen-rtsrc.py` 重生成 `selfhost/src/embed/rtsrc.dawn`
  （忘了这一步会被 `cdriver.dawn:268-287` 的内联陈旧检查当场抓住，
  它跑在 CI 的 `test` job 里）。
- **oracle**：刀 0 的三个语料转绿并从 `known-red.txt` 删行；
  `spike-native` 全量绿；`rc-contract` 绿；`native-cli-diff` 的长消息腿绿。
- **Emit-Change**：预测是「`rtsrc.dawn` 变 → `Emit-Change(emit selfhost)` 一行」，
  **实测推翻**：prev-diff 的 emit 差分是 N−1 jar 与 HEAD jar 编**同一份 HEAD 源**，
  纯数据改动对它不可见——六个 emit label 全 OK，零声明。`scripts/core-golden/selfhost.sha`
  确要 `--record` 重录（漂移恰好只有 `embed.rtsrc` 一个模块，这本身就是「除了运行时
  数据什么都没动」的机器证明）。
- 跑一次 `native-fixpoint.sh`（它不在 CI，但这刀改的是运行时形状，正好是它的适用条件）。
- **落地**（2026-08-08）：全局四件套换成 `dawn_failure` 值 + 单个 `dawn_inflight`
  在途槽。与 §4.0 的差别有一处，值得记：载荷**不**放进 handler 帧（setjmp 之后经
  longjmp 回来再读被改过的自动存储对象，是 C 标准明说的 indeterminate），而是留一个
  全局在途槽——它只在「raise 写入 → longjmp → 下一次 setjmp 返回立即搬走」这个
  不跑任何用户代码的窗口内被占用，每个屏障落地第一件事就是把它搬进自己的帧。
  语义与 §4.0 相同（嵌套够不着），少一处未定义行为。门禁全绿：spike 全量、
  rc-contract、prev-diff、native-fixpoint（B==C）、`dawn test selfhost`（335）。

### 刀 2 — 契约落文 + 门禁收口

- `docs/spec.md` §9.8.1 增补 §5.1 的条款（中文正本，随后补英译，
  `docs/README.md:26-27` 的规矩）。
- 删 `native-cli-diff.sh:397-405` 的 512 自我设限说明。
- 回填 `docs/codebase-audit-v2/03-...md` 的 ARC-03/04 状态。
- **oracle**：`doc-check.py`（双语 digest）；无代码改动，无 Emit-Change。
- **落地**（2026-08-08）：§5.1 条款进 `spec.md` §9.8.1「载荷契约」+ §9.8.2 保证 2
  的展开句与「release 逃逸顶掉原失败、无 suppressed」的现状裁决；`spec.en.md`
  同步补译并重登 digest。`native-cli-diff` 的自我设限注释删除、新增 654 字节
  消息腿（`str.repeat("long-", 130)`），实测两后端逐字节一致。

### 刀 3 — unwind 清理（ARC-05）

最大的一刀，内部再分三步，每步都能单独跑通语料：

- **3a**：验证 `_Unwind_ForcedUnwind` 在目标平台可用（至少 Linux glibc；
  macOS/musl 若不可用，此刀降级为 A1 并重估）。加 `-fexceptions` 到
  `selfhost/src/nmain.dawn:208`、`scripts/spike-native/run.sh:183-189`、
  `scripts/native-cli-diff.sh:48`、`scripts/native-fixpoint.sh:18`。
  单独提交，**此时语义零变化**——已实测这一步对 text 段与运行时间无可测影响（§4.1）。
- **3b**：运行时改 raise/reraise 为强制 unwind + stop 函数落地；
  `dawn_rt.c` 自己持有引用的地方也要带 cleanup。
- **3c**：emitter 给 owned 绑定加 cleanup 属性、在每个释放点置 NULL。
- **oracle**（这一刀的核心）：**删掉 7 个 `.leaks-on-catch` 标记后 spike-native 全绿**，
  外加刀 0 里为 ARC-05 专写的语料（活引用跨 raise、消息本身、bracket 资源三种形状，
  分别对应 `p3c` / `p3d` / `p3e`）。再加一遍 `DAWN_RC_LEAK=1` 跑同一组语料
  （drop 变 no-op），用来在出问题时把「清理没跑」和「清理跑重了」拆开。
- **Emit-Change**：改 emitter 会动**所有** emit 语料 →
  `emit site` / `emit playground` / `emit packages/web` / `emit packages/json` /
  `emit selfhost` / 五个 examples，逐条各写一行（`emit *` 不接受，CONTRIBUTING §五）。
  `core-golden` 全量重录（`CDup`/`CSDrop` 的形状变了）。
- **native-fixpoint 必跑**：这刀直接改发射出的 C 的形状，B==C 是唯一能证明
  「新编译器编译自己仍然稳定」的东西，而它不在 CI。
- **落地**（2026-08-08），与上面的方案有四处实测修正，每处都值得记：
  1. **CFA 比较被 ASan 实测打破**（§4.1 风险清单第三条料到「粗糙」，没料到全错）：
     ASan 把局部搬上 fake stack（堆地址），与真栈无任何序关系，stop 函数在**第一帧**
     就命中比较、longjmp 直达 handler，中间所有 landing pad 被跳过——泄漏原样存在，
     且恰好只在「本该证明它修好」的 sanitizer 档下复现。改成**身份判定**：handler
     结构体自带 cleanup（`dawn_handler_landing`），unwind 走到目标帧时由帧自己的
     landing pad 认领（指针相等）并 longjmp；stop 函数只剩 END_OF_STACK 的响亮 abort。
     身份不排序，fake stack 与内联都骗不了它。
  2. **每变量一个 cleanup 属性是实测过的死路，槽位收进每帧一个数组**。第一版给每个
     owned 局部各挂 `__attribute__((cleanup))`：先是撞出「声明必须提升到函数顶」
     （Core 的 loop 用 `goto` 落标签，跳过 cleanup 变量的初始化是 UB，
     -Wmaybe-uninitialized 当场抓住）与「按符号去重」（lowering 在分支两臂各绑一次
     同一符号，提升后成 C 重定义错，native-fixpoint 抓住）两刀，然后在 CI 上撞出
     致命的一刀：**-O2 编译时间爆炸**——每个调用点都成了拖着 N 条 cleanup 链的独立
     EH region，gcc 的 sched2/postreload 对其超线性，单个语料 cc 1.1s→8.5s，
     selfhost 驱动 16s→354s（22 倍），CI 两个 native job 双双超时。终形态：每个函数
     **一个** `dawn_own` 数组（槽 0 存计数，`dawn_own_drop` 一个 cleanup 走全部槽），
     整帧一个 EH region，驱动 cc 回到 27s（基线 16s，+70% 是 -fexceptions +
     landing pad 的真实价格）。运行期代价（槽位落内存，A1 当初被拒的那笔税的
     缩小版）：实测 fmt --check 场景 ~5%、emitc 场景 ~15%——比 §4.1 对 A1 的
     预估温和得多，因为热路径的标量与游标本就不进账本。
  3. **转移的记号不进 Core、不动 rc**：emitter 的 `emit_expr` 带上与 `rc_check`
     同一份消费位分类（`k`），有槽符号在消费位即发 `dawn_take`。镜像
     不会漂：漏一个 take = 正常路径 cleanup 双释放（asan 全语料立刻红），多一个
     take = 值被提前清掉（立刻错答案）。owned 形参经 `pN` 进入、第一件事搬进
     自己的槽（形参本身当不了槽）。
  4. **Emit-Change 实测为零**（方案预测「全部 emit label」）：prev-diff 的 emit
     差分是 N−1 jar 与 HEAD jar 编同一份 HEAD 源，emitc.dawn 自己也是被编的源码
     而不是被对拍的行为——JVM 字节码两边同源同答。C 文本的形状变化由
     native-fixpoint（B==C）与 spike 差分护住，不经 Emit-Change 机制。
     `core-golden` 也只有 embed.rtsrc（运行时数据）漂移，`CDup`/`CSDrop` 的
     Core 形状根本没变——rc pass 一行未动。
  残留（诚实记账）：**未具名的中间值**——`f(g(x), h(y))` 里 g 的结果不落名字、
  直接嵌进实参表达式——若同一实参表里更晚的表达式 raise，该中间值仍会漏。全语料
  LSan 全绿说明现有语料没有这个形状；系统性收口要么 rc A-normalize 所有 owned
  中间值（顺带修掉 C 实参求值顺序未定的老账），要么等语料先红。负控两枚都红在
  该红处：去掉 `-fexceptions` → unwinder 走不过无表帧，END_OF_STACK 响亮
  abort（比静默泄漏更硬）；删一处清槽 → asan heap-use-after-free 在
  `dawn_drop`。`DAWN_RC_LEAK=1` 二分档照常成立（drop 含 cleanup 全成 no-op）。

### 刀 4 — 清账

- 删 `run.sh` 的 `.leaks-on-catch` 机制（`:45-50`、`:211-213`）。
- 改 `docs/perceus-design.md:449-453`：那条「设计内例外」到期兑现，删掉。
- 回填 ARC-05 状态、`docs/native-backend-plan.md` 的相关行。
- **落地**（2026-08-08）：机制连注释一起删（`detect_leaks=1` 无条件）、perceus
  的例外段改为关账记录、审计 ARC-05 回填；`native-backend-plan.md` 经查没有
  直接引用该豁免的行，无需改。`dawn_bracket` 注释里那句「documented cost of
  the mechanism」同批改写。

### 护航总表

| 门禁 | 刀 1 | 刀 3 |
|---|---|---|
| `./bin/dawn test selfhost`（含 rtsrc 陈旧检查） | 必跑 | 必跑 |
| spike-native（含 asan/lsan） | 必跑 | **验收就是它** |
| rc-contract | 必跑 | 必跑 |
| native-cli-diff | 必跑（新长消息腿） | 必跑 |
| selfhost-prev-diff（五/十语料） | 1 条 Emit-Change | 全部 emit label |
| core-golden | 重录 selfhost.sha | 全量重录 |
| **native-fixpoint（B==C，不在 CI）** | 建议跑 | **必跑** |
| selfhost-fixpoint / run-diff / fmt-diff / lsp-diff | 例行 | 例行；`run errors/barriers example` 需确认输出未变（该例的消息都很短，推断不变） |

---

## 7. 破坏面

**理想目标是达成的：JVM 侧零改动。** 所有三个缺陷都只存在于 C 运行时；
JVM 的 `bracket` 重抛同一个 Throwable（`rtclasses.dawn:934-941`）、
`message` 取自 `getMessage()` 无上限（`:965-973`）、无任何全局失败状态。
这次重设计是 **native 单向收敛到 JVM 语义**，不是两边各让一步。

规范改动清单：

- `docs/spec.md` §9.8.1 加载荷契约（§5.1 的 6 条）；`spec.en.md` 补译。
- **`spec.md` 里没有 512 这个数**，不需要删任何条款——去掉上限只是让实现追上规范。
- §9.8.2 保证 2 建议加一句「release 内部自己接住的失败不影响正在传播的那个」，
  把今天的隐含读法写明。

会变的可观察行为（native 侧）：

1. `catch_*` 拿到的 `message` 在超过 512 字节时**变长**（变成正确值）。
   影响谁：任何依赖被截断长度的东西——勘察确认只有 `native-cli-diff.sh:397-405`
   的自我设限，用户代码不可能依赖它（它本来就是 bug）。
2. bracket 跨 release 的失败**变回原来那个**。同上，只有正确性方向的改变。
3. 致命路径（无人接住）打印的消息**不再截断**（今天 raise 不截断、reraise 截断，
   本身就不自洽）。`bracket_fatal.expect` 需要复核。
4. 刀 3 之后，**内存行为改变**：恢复不再泄漏。没有任何输出依赖它。

不会变的：

- `kind` 取值（仍然 `"panic"` / `"fault"`）；两后端 kind 仍然不同，规范允许。
- `cause` 仍然恒 `None`。
- 资源耗尽仍然穿过屏障（栈溢出仍是静默崩溃——那是 ARC-10 的题目，别顺手做）。
- 闭包 ABI、Core 节点集合（路线 A 不需要 `CSProtect`，已关档裁决不动）。

新引入的依赖（刀 3，要自觉承认的税）：

- 编译器方言：`__attribute__((cleanup))` + `-fexceptions` + `_Unwind_*`。
  今天的运行时是纯 C11 零方言（全文只有一个 `_Noreturn`）。
- 平台面：Linux/glibc 已实测可行；**macOS 与 musl 未验**，是刀 3a 的准入条件。

---

## 8. 不做的（记录理由）

- **不做路线 B（Result ABI）。** 理由与重开条件见 §4.3。一句话版：
  Dawn 的失败不在效果行里，所以「可失败函数」是全体，B 的代价函数取到最大值；
  而它唯一的硬优势（账本天生平）可以用一个已经建好的 oracle（LSan + 7 个待删的
  豁免标记）替代。
- **不做 `CSProtect` / Core 层 protect 节点。** `docs/audit/error-model-design.md:205-215`
  已关档，本方案不需要它，因此不构成「新证据」。
- **不给 message 设新的显式上限。** 见 §5.1 条款 3。
- **不改 `release` 自己逃逸时的语义**（今天顶掉原失败）。只写下现状。
  做 suppressed 链是另一个题目，且要 JVM 侧配合（`addSuppressed`），
  会打破「JVM 零改动」这条最值钱的性质。
- **不顺手改 512MB 栈 / SIGSEGV 报告**（ARC-10）。它与失败模型相邻但不同根：
  那是资源耗尽，规范明说要穿过屏障。
- **不动 `io.exit` 的四条出口**（`core-move2-design.md:366-369`）：那里根本没有栈可退，
  与 unwind 无关。
- **不把 `.leaks-on-catch` 换成「断言泄漏量」的更精细豁免。** 那会把一个应当消失的
  例外制度化。刀 3 的验收就是让它消失。
