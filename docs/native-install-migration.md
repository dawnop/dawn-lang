# 原生安装入口发布迁移说明

> 状态 **current**，供下一次发布使用的安装迁移说明。

## 生效版本与安装输入

README 的原生安装块依赖 `dawn-toolchain.json` 和 `install-native.py`。
这两个资产从合入原生安装入口改动后的下一次发布起提供。
已有的 v0.104.0 发布早于该改动，其资产集合缺少这两个文件。
README 中固定 tag 的写法须选用实际包含它们的新发布。

准备下一次发布说明时，填入实际 tag，并逐名核对同一 tag 下的
`dawnc-linux-x86_64`、`dawnc-linux-x86_64.sha256`、
`dawn-toolchain.json` 和 `install-native.py`。
安装器核对元数据、SHA-256、静态 ELF 架构、版本与完整源码清单摘要，
然后原子替换所选 prefix 下的 `bin/dawn`。
离线安装使用已下载的同 tag 文件，并显式传入 `--tag` 与 `--from-dir`。
在线安装省略 `--tag` 时，安装器先解析一次 latest，再固定该 tag 获取各项输入。
安装步骤见仓库 README 的安装章节。[安装说明](../README.zh-CN.md#安装)

## 命令名与工具链选择

安装器生成的命令为 `dawn`，文件本体就是原生编译器。
新安装只提供 `bin/dawn`，旧命令名 `dawnc` 不再安装。
使用旧命令名的脚本与编辑器配置需要改为 `dawn`。
原有手工安装的 `dawnc` 可按原安装位置清理。
下载资产名为 `dawnc-linux-x86_64`，版本输出为
`dawnc <version> (native) b1:<digest>`，可据此核对实际运行的制品。
将所选 prefix 的 `bin` 放入 PATH 后，用 `command -v dawn` 和
`dawn --version` 核对命令位置与身份。

首期原生发布支持 Linux x86_64。`run`、`build` 与 `test` 需要 C 编译器，
WebAssembly 输出需要 clang 和 WASI，获取远程源码包需要 curl。
其他操作系统与 CPU 架构各自需要发布资格验证。

Java 项目、根或传递依赖中的 `[java-deps]`、`--cp`、`--closure`、
`build --native`、`lock` 与 JAR 清单读取使用所选版本的 JVM 工具链。
安装版对这些语义能力给出显式拒绝，JVM 用户通过 JDK 21 或更新版本运行
同 tag 且已核对 checksum 的 JAR。JDK 参数放在 `-jar` 前。

```bash
java -Xss512m -jar /absolute/versioned/dawn-selfhost.jar check project/
java -Xss512m -jar /absolute/versioned/dawn-selfhost.jar lsp
```

源码 checkout 的 `./bin/dawn` 是 JVM 自举入口。
从源码开发、使用安装版和运行指定版本 JAR 时，各自使用明确的入口路径。

## 进程与终端

`run`、`build` 与 `test` 在编译或运行子进程期间，将 SIGINT/SIGTERM
传递给子进程组。`run` 保留程序退出码，stdout 与 stderr 分别传递。
交互程序支持终端输入、Ctrl-C，以及 Ctrl-Z 后的 `fg`/`bg` 作业控制。
外层 shell 的暂停原因可能显示为 SIGSTOP。

## 编辑器配置

VS Code 默认 `dawn.lspPath` 为 `dawn`，`dawn.lspArgs` 为空数组。
默认启动安装版 `dawn lsp`。Java 用户显式配置 executable 与参数数组。

```json
{
  "dawn.lspPath": "java",
  "dawn.lspArgs": ["-Xss512m", "-jar", "/absolute/versioned/dawn-selfhost.jar"]
}
```

扩展按 `lspArgs + ["lsp"]` 传递 argv，数组中的路径、空格与空串逐元素保留。
修改任一启动配置会重启服务。Output 中的实际 executable、argv 和服务版本
用于确认所选工具链。其他编辑器同样使用明确的 executable 与 argv 数组。
详细配置见编辑器说明。[编辑器配置](../editors/README.md)
