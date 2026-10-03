# inflate 默认解压上界

> 状态：**current**。2026-10-03 裁决刀 1：`packages/inflate` 升 3.0.0（包名 `inflate3`），
> 四个解压入口与 `zip.entries` 的 `cap` 默认从「不设上界」改为 `Some(DEFAULT_CAP)`，
> 16 MiB。字节上界不等于内存上界那一半是公开 issue #405，不在本篇范围。

## 1. 问题

inflate 2.0.0 的 `deflate.inflate`、`deflate.inflate_from`、`gzip.gunzip`、`zip.read`
都带 `cap: Option[Int] = None`，默认无上界；`zip.entries` 干脆没有 `cap` 参数。
上界机制本身是对的（写之前检查、超限返回 `Err`、gzip 多 member 共享一个总预算），
缺的是默认值。

这个包**只有一次性 API**：调用者忘了设上界，代价不是读得慢，而是进程 OOM。
DEFLATE 单流比率上限约 1032:1，`gzip -9` 实测 994 KB 展开成 1,024,000,000 B。

仓内唯一生产调用者是 `compiler-plan/src/pkgfetch.dawn`，它对 `gunzip` 与 `zip.read`
都**显式**传上界（256 MiB 总量、64 MiB 单条），不受默认值影响。web、playground、站点、
dawnop-site 后端都不经 inflate。所以改默认的仓内与下游破坏面是 0 处调用。

## 2. 做法

- `deflate.dawn`：`pub const DEFAULT_CAP: Int = 16777216`；`inflate`、`inflate_from` 默认
  `cap: Some(DEFAULT_CAP)`。`gzip.gunzip`、`zip.read` 默认 `Some(deflate.DEFAULT_CAP)`。
  `None` 是显式的「不设上界」。签名形状不变，只有省略 `cap` 的含义变了，所以是 major。
- `zip.entries(src, cap: Option[Int] = Some(DEFAULT_CAP))`：一个上界管**全部条目**的总输出，
  逐条传剩余预算，与 `gunzip` 管多 member 同一语义。中央目录可以让多条记录指向同一段压缩
  数据（Fifield，*A better zip bomb*，USENIX WOOT 2019），按条计费的上界乘以条目数等于没有上界。
- 命中默认上界的报错在原文后追加默认值与出路：

  ```
  deflate: the output exceeds the 16777216 byte limit (stopped at 16776967 bytes); the default cap is 16777216 bytes: pass cap: Some(n) for a larger limit, or cap: None for no limit
  ```

  「是不是默认」按值判断（`lim == DEFAULT_CAP`），显式传 `Some(DEFAULT_CAP)` 也带这句，
  话仍然成立。容器里第一个 member / 条目拿的是整份默认值，由 deflate 自己加注；之后的拿的是
  剩余预算（调用者没见过的数），由 gzip / zip 在外层补注，已有注的不重复加。只给上界拒绝加注，
  损坏的流不会因为放大上界而变好。
- 包内测试钉住三处文案；`scripts/inflate-contract/run.sh` 加一条腿：Java 造的 512 MB 炸弹，
  不传 `cap`，在 256 MB 堆里依次喂 `deflate.inflate`、`gzip.gunzip`（单 member 与「小 member +
  炸弹」）、`zip.entries`，四处都必须以默认上界的文案拒绝。

## 3. 数值依据

上界数的是**输出字节**，而今天 `bytes.Buf` 是 `Array[Int]`，每个输出字节占的内存远大于 1 B
（调研实测：JVM 零字节约 10 到 16 B、`0xFF` 约 16 到 30 B；native 约 32 B）。默认值的意义是
「忘了设也不崩」，所以取的是今天的内存倍数下在工具链自己的 `-Xmx2g` 里对任意输入都安全的那档：

| 默认 | JVM 峰值（实测折算） | native RSS（实测） | `-Xmx2g` 下 |
|---|---|---|---|
| 16 MiB | 约 0.25 到 0.5 GB | 约 0.56 GB | 安全 |
| 64 MiB | 约 1 到 2 GB | 约 2.1 GB | `0xFF` 输入贴边 |
| 256 MiB | 超出 | 约 8 GB | 零字节输入即 OOM |

合理负载的量级：dawn-lang 自身 tag 归档 tar 25.2 MB、zip 8.3 MB，走的是 pkgfetch 的显式上界。

## 4. 不做的（理由）

- **比率上界。** 一次性 API 开始解压时已知 `len(src)`，比率只是推导出来的绝对上界；合法的高比率
  输入（全零、稀疏数据）存在；默认值不能引用形参，写不出来。Apache `mod_deflate` 需要它是因为
  请求体流式到达。
- **流式 API。** 没有需求方，Dawn 也还没有 Bytes 流抽象；以后要做与本刀不冲突。
- **强制必填 `cap`。** 把 K3 刚收掉的噪音换个形式加回每个调用点，且挡不住人人写 `cap: None`。
- **`Limit` 枚举、哨兵 `Int`。** 前者为「一个可选的数」新造类型，`Option[Int]` 已经说清楚；
  后者复刻 Node `kMaxLength` 式的伪默认。
- **默认 64 MiB 或 256 MiB。** 见 §3，今天在 `-Xmx2g` 下不稳。`bytes.Buf` 换成真字节缓冲后
  再评（放宽上界不让任何原先成功的调用失败，minor 即可）。
- **web 请求体解压。** web 今天不解码 `Content-Encoding`，`max_body` 管的是线上字节；要开这个口子
  必须另设解压后上限，且要等内存倍数修好。
