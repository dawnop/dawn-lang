# 包的完整性：cache 校验与 Maven lock

> 状态：**已落地（proposed → done）** —— §2.1 与 §2.2 均已实现，偏离处见文首。
>
> **2026-07-30：§2.1 已落地**（`ensure_cached` 命中即重算 d1 对比目录名 +
> `dawn cache verify` 全量扫描；内容寻址使 marker 文件可省——目录名就是声明，
> 重算即全部校验。实测 7MB 树 ~0.9s、典型源码包毫秒级，默认校验成立）。
> **2026-08-07 更正**：「命中即重算」只对 `ensure_cached` 成立，而构建路径热命中
> 不经过它（`analyze.url_pkg_root` 直接 return），所以每次构建的自动校验实际不存在，
> 只剩 `dawn cache verify` 手动扫描。详见 codebase-audit.md 的 PKG-02 更正条。
> **§2.2 也已落地（同日）**，但形状与本文所写有一处诚实的偏离：lock 记录的是
> **整个解析闭包的字节**（`artifact <sha256>  <basename>` + 直依赖坐标），不是
> 每条 artifact 的 coord/url——coursier 的 `Fetch` 交回文件而不是坐标，从缓存路径
> 反推坐标是猜。行为也随之改为「照旧解析，然后拒绝与 lock 不符的任何东西」而不是
> 「按 lock 装、不解析」：coursier 才是下载方，成本更高、安全性等价（传递版本变动、
> 镜像换字节、缓存损坏三者都改变 basename 或 hash，三者都停下构建）。`dawn lock` /
> `dawn lock --check`（后者进 CI）如本文。第 5 个反例（上游删除）仍解决不了，
> 已写进模块头注释——本文自己叮嘱过别重犯这类夸大。
>
> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **PKG-02（P1，源码包那一半）** 与 **PKG-04（P2）**。
> （种子 jar 的 checksum、下载与解压的资源上限已于 2026-07-25 落地。）
> 写作当时的状态是「proposed，两半都可做，PKG-02 优先于 PKG-04」，理由见下；
> 两半都已落地，现状以文首那行为准。
>
> [`../native-backend-plan.md`](../native-backend-plan.md) §1 定了 native 上
> `[java-deps]`/coursier **直接报不支持**，拉包 shell 出去调 `curl`。两个后果：
> §2.2 的 `dawn.lock` 是**JVM 后端专属**的设施（native 上 `[[java-dep]]` 是死条目），
> 而 §2.1 的 d1 marker 在 native 上**是唯一的完整性手段**（那边没有 JDK 的 HTTP 栈、
> 没有 `MessageDigest`、没有 coursier 的校验）。所以先做 §2.1。
> 撞车登记见 [native-plan-overlap.md](native-plan-overlap.md) §3.9。

## 一、问题

### 1.1 cache 命中就信任（PKG-02）

`selfhost/src/pkgfetch.dawn` 的策略是明说的：**fetch 时验证一次，之后信任本地副本**。
目录存在就直接返回，不再看内容。

于是用户手改、磁盘损坏、并发抓取留下的半成品，都能改变 cache 内容而不被发现。

**对照**：种子 jar 的同一个病 2026-07-25 已经治了——
`scripts/seedjar.sh` 现在每次使用前校验，不只是下载后。源码包该走同一条路。

好消息是**材料已经有了**：`pkgfetch.dawn` 已经实现了 d1 canonical tree hash
（`d1:` + SHA-256 over `relpath \0 size \0 bytes` 的排序文件树），
fetch 时就是用它验证的。缺的只是「把它记下来，下次再算一遍比对」。

### 1.2 无 lockfile 的可复现论证过强（PKG-04）

`docs/package-design.md` 的论证是：精确直依赖 + Maven Central release 不可变
⇒ 可复现。五个反例：

1. 传递 POM 可以含版本区间或动态 metadata——直依赖精确不代表闭包精确；
2. mirror（`$DAWN_MAVEN_MIRROR`）可以返回不同内容；
3. 没有 artifact checksum；
4. highest-wins 的解析结果没有固化——依赖树变了，选出的版本会变；
5. 仓库或依赖被删除，重建直接失败。

审查那句对比很准：**源码包的 d1 hash 做得更好**。
同一个仓库里两套依赖各有一套可复现性论证，弱的那套却没标明自己更弱。

## 二、方案

### 2.1 源码包：marker + 每次校验 + 原子发布（PKG-02）

cache 目录里放一个 marker：

```
.dawn/pkgs/<name>/<hash>/.dawn-pkg
```

内容（一行一个字段，好读好比对）：

```
schema 1
url https://github.com/x/y/archive/refs/tags/v1.0.0.tar.gz
d1 d1:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

`fetch` 的流程改为：

| 情况 | 行为 |
|---|---|
| 目录不存在 | 下载 → 解压到**临时目录** → 算 d1 → 比对声明 → 写 marker → **原子 rename** 进 cache |
| 目录存在、marker 缺失或 schema 不认识 | 当作损坏：删掉重抓 |
| 目录存在、marker 在 | **重算 d1 并比对**；不匹配 → 报错，指明 cache 路径与两个 hash |

三点说明：

- **原子 rename**：现在也是先解压到 work 目录再 `strip_single_top_dir`，
  但 marker 要在 rename **之前**写进临时目录里，否则会出现「目录在、marker 不在」
  的中间态被并发的另一个进程看到。
- **每次重算 d1 的代价**：要读一遍整个包的字节。源码包很小
  （`packages/json` 是 4 个文件、~450 行），但没有实测。落地时要量，
  如果确实明显，退到「只在 `dawn build` 时校验，`dawn run` 信任」——
  但**默认是校验**，不是相反。
- **只读权限**（审查建议）：`chmod -R a-w` 能挡住手滑，挡不住恶意。
  做，但当作卫生措施不当作安全边界。

新增 `dawn cache verify`：遍历 cache，逐个重算并报告。这是审查明确点名的。

### 2.2 Maven：生成 lock（PKG-04）

新增 `dawn.lock`（跟踪进仓库，与 `dawn.toml` 同级）：

```toml
schema = 1

# 每个条目是解析后的坐标 + 拿到它的地方 + 它的字节
[[java-dep]]
coord = "org.ow2.asm:asm:9.7.1"
url = "https://repo1.maven.org/maven2/org/ow2/asm/asm/9.7.1/asm-9.7.1.jar"
sha256 = "..."
direct = true              # 是不是 dawn.toml 里直接写的

[[java-dep]]
coord = "org.ow2.asm:asm-tree:9.7.1"
url = "..."
sha256 = "..."
direct = false             # 传递依赖，highest-wins 之后选中的版本
```

行为：

- `dawn run|test|build`：**有 lock 就按 lock 装，不重新解析**；
  校验每个 jar 的 sha256。lock 与 `dawn.toml` 的直依赖不一致 → 报错，
  提示跑 `dawn lock`。
- `dawn lock`：重新解析、写 lock。这是唯一会改 lock 的命令。
- `dawn lock --check`：CI 用，lock 过期就红。

这一次性解决五个反例里的 1、2、3、4。第 5 个（上游删除）**解决不了**——
lock 让你知道要什么，不让它凭空出现。文档里要写明这一点，不要让 lock 看起来
比它实际能做的更强（这正是 PKG-04 批评原论证的方式，别在新特性上重犯）。

## 三、为什么不顺手把 X 也改了

- **不做 vendoring**（把 jar 提交进仓库）。那是「上游删除」的唯一真解，
  但它把仓库体积和许可证责任一起接过来。要做的话是独立决策。
- **不改 highest-wins 的解析算法**。它今天的问题是**结果没固化**，不是算法错。
  lock 固化结果之后，算法只在 `dawn lock` 时跑。
- **不给源码包也做 lock**。源码包的 `[deps]` 已经在 `dawn.toml` 里带 d1 hash——
  它本来就是自己的 lock。这是它比 Maven 那半做得好的地方。

## 四、不做的（记录理由）

- **给 cache 加签名验证**。签名要有信任根（谁的公钥、怎么分发）。
  d1/sha256 能挡篡改与损坏，签名要挡的是「上游作者被冒充」——
  那需要一整套 PKI 决策，与 BOOT-02 的种子签名是同一个未决问题，
  该一起做而不是在这里做一半。
- **让 lock 记录完整依赖图（谁引入了谁）**。诊断时有用，但会让 lock 随
  解析器的实现细节变化而变化——lock 应该只记录**结论**。
  要看图跑 `dawn deps --tree`（另一个特性）。
- **默认在 `dawn run` 时也校验 Maven jar 的 sha256**。会做，但如果实测显示
  每次启动多出可观的开销，退到「`build` 校验、`run` 信任」——
  与 §2.1 同一条纪律：先量再退，不预先妥协。
- **把 marker 做成二进制格式**。文本格式能 `cat`、能 diff、能手工修，
  对一个用来诊断「cache 怎么坏的」的文件，这些比几十字节重要。

## 五、落地点

| 步 | 文件 | 测试 |
|---|---|---|
| 1 | `selfhost/src/pkgfetch.dawn`：marker 写入 + 原子 rename | 「rename 前 marker 已在临时目录」 |
| 2 | 同上：cache 命中重算 d1 | 「手改 cache 里一个字节 → 报错并给出两个 hash」 |
| 3 | `selfhost/src/main.dawn`：`dawn cache verify` | 遍历并报告 |
| 4 | `selfhost/src/maven.dawn` + `manifestv.dawn`：`dawn.lock` 读写 | 「lock 与 toml 直依赖不一致 → 报错」「sha256 不匹配 → 报错」 |
| 5 | `selfhost/src/main.dawn`：`dawn lock` / `dawn lock --check` | CI 用 `--check` |
| 6 | `docs/package-design.md`：改掉过强的可复现论证，写明 lock 覆盖什么、不覆盖什么 | — |

步骤 1–3 无破坏性（cache 是本地状态）。
步骤 4–5 新增文件与子命令，也不破坏——**没有 lock 的项目按老路走**，
`dawn lock` 是显式动作。这是这份文档整体成本较低的原因。
