# SAM 值边界修复

> 状态：**current** —— 2026-09-07 动码前方案与实施记录，对应欠账复核 SPC-16 与 R2（#98）。

## 问题与方案

SAM 的参数推断和返回兼容性表遗漏了 `byte[]` → `Bytes`，导致合法闭包被拒。
补齐三个 checker 入口，返回兼容性仍按 Java assignability 判断（允许 Bytes 返回到
Object，但不允许 String 冒充 byte[]）；回调参数保持直接 Bytes、null fail-fast，
普通 Java 方法返回仍是 Option[Bytes]。不统一这两个方向的空值政策。

SAM 的 byte/short 返回现在只做 Int→Java int 的范围检查，因此 128 和 32768
分别静默变成 -128 和 -32768。把检查改成目标类型的 round trip：L2I 后按 byte/short
符号扩展，再 I2L 与原值比较；越界 panic，消息指明真实目标。同步规范补齐此前只
明确 int 的条款。long、float、Never 和效果快照均不改。

## 验收

真实 Java 接口夹具覆盖 Bytes 参数/返回、推断与显式类型、null 参数、普通方法的
Option 返回、Object 宽化与不兼容负控。byte/short/int 各覆盖上下边界、越界一格和
Int 极值；合法值原样返回，非法值逐字断言 panic 消息。恢复旧分支的可编译变异体
必须分别被 Bytes 和范围断言抓住，不能把编译失败误算作范围测试通过。

沿用 classfile 门运行 Java 夹具，通过支持 --cp 的 build 命令生成 jar，检查真实生成类
并执行结果（check/__emit 不支持该选项，不能靠 compiler 自身 classpath 注入依赖）。
613 项 selfhost、两个可编译旧实现变异体、原有 13 个 Never 变异体、自举固定点及
旧版差分均通过。Core 文本不变，自身哈希按惯例重录；完整文档门通过。

## 不做

不引入 char 支持、不改变普通 Java 实参转换、不重构整张 FFI 表，不改变 SAM
创建点效果快照与 Never 契约。本项不发布新版本或部署服务。
