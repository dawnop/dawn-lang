# slab residency benchmark

这是 #10 的本地 measurement harness。它回答 allocator 方案间的相对问题，不是功能
contract，也不是 CI gate：机器负载、kernel、glibc 和 mimalloc 版本都会移动 RSS 与 wall
time，所以这里保存原始样本、打印中位数，但**不设通过阈值**。

## 它量什么

三个 workload 都在被测动作结束、临时对象图已经离开作用域后先打印动态结果行
`checksum\t<值>`，再打印固定的 `ready` 行。随后进程只用 `stdin_ready` 轮询；runner 收到
第二行后读取同一个进程的 `/proc/<pid>/status`，采样完成才写一个字节让进程调用
`read_stdin` 并退出。这样 stdin read buffer 的分配不会落入 quiet RSS：

- `quiet_vmrss_kib` 是 churn 后的 `VmRSS`；
- `vmhwm_kib` 是该进程的 `VmHWM`；
- `to_ready_ms` 从 `exec` 前量到 `ready`，不含等待采样的时间。

workload 固定为：

| 名称 | 动作 |
|---|---|
| `lexer` | 从固定 corpus 复制 `selfhost/src/front/lexer.dawn`，默认每进程 lex 100 次；源码字符串跨轮存活，token/diagnostic 图逐轮释放。 |
| `rbtree` | 纯 Dawn 持久红黑树；每轮按固定排列插入 32768 个 key、每 256 次保留一个旧 root、按固定 key 集覆盖值，再校验新旧两棵树的固定 checksum。默认 24 轮，使被测段约 2 秒。 |
| `compiler` | 原生编译器形状：调用与 `dawnc emitc` 相同的 `load_std` → `load_target` → `analyze_program` → `cdriver.c_text` 管线，对归档中的 `selfhost/src/nmain.dawn` emit 一次。它故意不把外部 `cc` 的 RSS 混进 compiler allocator 曲线。 |

`lexer` 与 `compiler` 的输入在开始时从同一个 Git ref 或目录复制进结果目录；三个 workload
入口也复制到该 corpus 下，从其中的 `std` / `selfhost` emit。运行中即使原目录变化，每个
变体仍读同一份字节；实际 emitted C 的 MD5 记在 `builds.tsv`。三个 workload 各自只 emit
一份 C，所有 allocator 变体都使用同一份 emitted C。若 eager 与
candidate 的 `dawn_rt.h` 字节相同，program object 也复用；若头文件不同，则分别编译，
避免把旧 ABI runtime 与 candidate object 混用。

## 变体

默认矩阵是：

| label | runtime 与链接方式 |
|---|---|
| `eager` | `--eager-ref` 的 `runtime/c`（默认 `HEAD`），或 `--eager-runtime` 指定的非 Git 目录。 |
| `candidate` | `--candidate-runtime`（默认当前工作树的 `runtime/c`）。 |
| `glibc` | candidate runtime 加 `-DDAWN_NO_SLAB`。 |
| `mimalloc` | 与 `glibc` 相同，再链接 mimalloc。 |

因此典型的未提交实验直接运行：

```sh
./scripts/slab-bench/run.py --samples 8 --out /tmp/dawn-slab-2026-08-30
```

candidate 已提交时，把 eager parent 说清楚：

```sh
./scripts/slab-bench/run.py \
  --eager-ref HEAD^ --corpus-ref HEAD \
  --samples 8 --out /tmp/dawn-slab-candidate
```

没有 `.git` 的源码快照（例如 Windows worker 里的 WSL）可完全绕过 Git：

```sh
./scripts/slab-bench/run.py \
  --eager-runtime /path/to/baseline/runtime/c \
  --corpus-dir /path/to/source-snapshot \
  --candidate-runtime /path/to/source-snapshot/runtime/c \
  --samples 8 --out /tmp/dawn-slab-worker
```

`--corpus-dir` 指向同时含 `selfhost/`、`std/`、`packages/`、`compiler-plan/` 的源码根。
它与 `--corpus-ref` 互斥，正如 `--eager-runtime` 与 `--eager-ref` 互斥；使用目录 eager
时必须显式给出 corpus 的目录或 ref。两项都用目录时 runner 不调用 Git。目录里的链接会
在复制时解引用，使结果 corpus 自包含。

这仍不是原生 Windows 工具：测量依赖 Linux `/proc`。在 WSL 下给出 `/mnt/d/...` 输入路径，
但建议把 `--out` 放在 WSL 的 Linux 文件系统（例如 `/tmp`），不要把 DrvFS 抖动混入 wall
time。

默认用 `pkg-config mimalloc`，找不到时退到 `-lmimalloc`。发行版通常把开发包叫
`libmimalloc-dev`；暂不量它可写：

```sh
./scripts/slab-bench/run.py --variants eager,candidate,glibc
```

若本机的链接参数不同，用例如
`--mimalloc-link '-L/opt/mimalloc/lib -lmimalloc'` 明确传入。所有 C build 使用与
`scripts/native-fixpoint.sh` 相同的核心参数：`-std=c11 -O2 -fwrapv -fexceptions
-fno-strict-aliasing -pthread`。

## 输出与复跑

这是 **Linux-only** 工具，需要 `/proc/<pid>/status`、`VmRSS` 和 `VmHWM`；macOS/Windows
进程计数不是同一口径，runner 会直接拒绝。WSL2 虽有这些字段，仍应把 WSL/kernel 版本当作
独立环境，不与裸机样本混合。

结果目录包括：

- `samples.tsv`：warm-up 与每个新进程的原始 RSS/HWM/to-ready/checksum；
- `environment.tsv`：ref/目录输入来源及 MD5、compiler/cc/kernel/libc、CPU、page size、
  宿主 THP 模式（`transparent_hugepage`，因为 runtime 的 `MADV_NOHUGEPAGE` 只在
  THP=always 上才有事可做，宿主模式因此是 RSS 数字的一部分）与固定次数；
- `corpus-files.tsv`：复制后 corpus 每个文件的大小/MD5，以及 `environment.tsv` 中对应的稳定整树 MD5；
- `builds.tsv`：每个 workload/variant 的 runtime 来源、编译参数、C 与 binary 的字节标识；
- `logs/`：每个进程的 stderr；
- `build/`：实际测过的 C、runtime snapshot 与 executable；
- `corpus/`：本轮从 `--corpus-ref` 或 `--corpus-dir` 固定下来的 lexer/compiler 输入。

runner 先各跑一次不计入摘要的 warm-up，再以轮转顺序交错变体，避免总把某个变体放在
冷热相同的一端。sample 数应为变体数的整数倍，使每个变体在轮内各位置出现同样多次；默认
四变体 × 8 sample 已满足。它只因 build 失败、`ready` protocol 失败、退出失败或 checksum
不一致而报错；RSS/wall 的好坏永远不改变退出码。正式结论至少保存五个 sample，观察方向
不稳时增加样本，而不是挑一轮有利数字。

为免 shell 环境偷偷替换 allocator 或打开调试模式，runner 会清掉 `LD_PRELOAD`、
`GLIBC_TUNABLES`、sanitizer options，以及 `DAWN_` / `MALLOC_` / `MIMALLOC_` 前缀的变量；
同一份净化环境用于 Dawn emitter、C build 和被测进程。被清掉的**变量名**记录在
`environment.tsv`，值不写入结果。`LD_LIBRARY_PATH` 保留，便于使用非系统目录里的显式
mimalloc 链接。

完整参数见：

```sh
./scripts/slab-bench/run.py --help
```
