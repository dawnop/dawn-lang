# `run` argv 边界设计（TOOL-03）

> 状态：**current** —— 本文记录 TOOL-03 的定稿契约与落地边界。它把编译器参数和
> 被运行程序的参数分成两个互不抢占的名字空间；允许破坏旧的“target 后继续写编译器
> option”用法，因为 Dawn 尚处早期，稳定而可组合的接口比兼容这个偶然行为更重要。

## 1. 问题

JVM 驱动原先依次调用 `extract_cp`、`extract_ct_opts`、`extract_flag`，每个 helper 都扫描
完整 argv；等它们全部结束后，`run_run` 才确定 target 并把剩余 token 当程序参数。因此：

- 程序无法收到恰好拼作 `--comptime-ffi`、`--closure` 或未来新增 compiler flag 的参数；
- 新增一个编译器 option 会追溯性改变既有程序的 argv，wrapper 无法可靠透传；
- native 驱动的通用 tail parser 又走另一条路，target 后任何 token 都只会触发整页 help，
  两端既没有共同边界，也没有共同的命令级诊断。

这不是 unknown-option 政策，而是两个名字空间没有显式分界。

## 2. 定稿契约

唯一语法是：

```text
dawn run [compiler-options] <target> [-- <program-args>...]
```

- 没有程序参数时可省略 `--`；`run target` 与 `run target --` 都传空 argv；
- target 后若还有 token，第一个必须是 `--`，否则 stdout 为空、stderr 为固定 usage、退出 2；
- 分隔符自身不转发；它后面的 token 逐字原样转发，包含空串、`--`、
  `--comptime-ffi`、`-o` 等 option-like 字符串；
- compiler option 只在 target 之前解析。target 之后即使拼写成已知 compiler option，也只
  能放在分隔符后作为程序参数，不能再影响本次编译。

固定错误为：

```text
error: usage: dawn run [compiler-options] <target> [-- <program-args>...]
```

本文中的 `dawn` 同时表示 JVM 驱动与 native 驱动的公共命令契约；native 可执行文件仍名
`dawnc`，但同类 usage 诊断沿用仓库既有的 `dawn ...` 拼写。

## 3. JVM：一次顺序解析

`run` 不再把 argv 依次交给三个“过滤整表”的 helper。专用 parser 从左到右走一次：

1. target 出现前识别 `--std`、`--cp`、`--comptime-fuel`、`--comptime-ffi`、`--closure`；
2. 第一个不属于这些 option 的 token 是 target；
3. target 后只检查“结束或 `--`”，随后把剩余 token 不经解释地收进 program argv。

解析结果同时携带编译选项、target 与程序 argv，后续编译和执行只消费这份结果。通用
`extract_*` 继续服务没有程序 argv 的 `test` / `build`，不在本刀顺手重写。

## 4. dependency re-exec 不得改写 argv

`maybe_with_deps` 需要在第一次进程里知道 target 与显式 `--cp`，才能解析工程
`[java-deps]` 并扩展宿主 classpath。`run` 会把已经顺序解析出的 target / classpath 计划
交给重启 helper，但 re-exec 命令必须附回调用者给出的**完整原始 rest**，而不是重建一份
规范化 argv：

- 空串不能消失；
- `--` 的位置不能移动；
- program argv 不能被父进程解释或过滤；
- 子进程在扩展后的 classpath 上再对自己的原始 argv 顺序解析一次。

没有发生 re-exec 时，同一进程只解析一次；发生 re-exec 时，每个进程各解析自己收到的 argv
一次，这是跨进程继续同一 invocation，不是同一 parser 多次扫表。

## 5. native：独立 parser，真实传入入口

native 驱动保留自己的 run parser，只共享上面的可执行契约，不调用 JVM parser。它识别自己
已有的 target 前 compiler option（目前是 `--std`），返回 `(std, target, program_args)`。
`build_and_exec` 由只执行 `[bin]` 改为执行 `[bin] ++ program_args`；test runner 继续显式传
空列表。这样 C runtime 的 `args()` 才真正看到 `dawnc run` 收到的程序参数。

不继续复用 `build` / `emitc` 的 `-o` tail parser：`run` 没有输出产物可命名，共享 parser
正是旧实现把不相关 option 混进命令契约的原因。

## 6. 仓内迁移

只有真实向程序传参的调用需要加分隔符；无参数调用保持短式。迁移七个 invocation：

- `scripts/dtoa-contract/run.sh` 一处；
- `scripts/inflate-contract/run.sh` 一处；
- `scripts/json-suite.sh` 一处；
- `scripts/selfhost-run-diff.sh` 的 calc 两处与 interop 两处。

`examples/projects/calc.dawn`、`examples/interop/interop.dawn` 与
`docs/seq6-research.md` 的可复制命令同步，不留下会被新契约拒绝的说明。

## 7. 可执行契约

`scripts/native-cli-diff.sh` 在 arity leg 后增加独立 run absolute leg。它不只比较两端相等，
还逐例钉 stdout、stderr 与 exit：

- `run target` 与 `run target --` 都得到空 argv；
- `--` 后的 option-like token 与空串逐项、逐长度可见，且分隔符不出现；
- target 前 `--std` 仍按 compiler option 生效；
- target 后裸普通 token或 flag-like token都命中固定 usage、stdout 空、exit 2。

两端 parser 继续独立；绝对期望防止“同时实现错”让 differential 假绿。

## 8. Core、Emit 与负向控制

驱动控制流会改变 `main.core` / `nmain.core`，先运行 Core gate 测量，再用 `--record` 只记录
实测变化。跨 release 的 CLI transcript 同样先跑 `selfhost-prev-diff.sh` 与
`selfhost-run-diff.sh`，只为真实变化写闭集 `Emit-Change(...)`，不在实现前预声明。

至少执行两次共谋变异并恢复：

1. 临时让两端都接受 target 后裸 token；双端仍一致，但 absolute reject 必须红；
2. 临时让两端都把分隔符自身传给程序；空 argv 的 `run target --` 必须红。

## 9. 不做的（记录理由）

- **不为其他子命令引入 `--`。** 它们没有被执行程序的第二个 argv 名字空间。
- **不合并两端 parser。** 会把 backend differential 降成同函数自比。
- **不新增全局 unknown-option 政策。** 本刀只规定 target 前后与分隔符，不替全部 CLI
  决定以 `-` 开头的路径是否允许。
- **不兼容 target 后 compiler option。** 双重解释会让名字空间继续不稳定；迁移仓内真实
  调用比保留偶然行为更便宜、更清楚。
