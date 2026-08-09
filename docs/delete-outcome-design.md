# `io.delete` 结果建模

> 状态：**current** —— LIB-07 的定稿与落地契约，并收口其发现的 C-string NUL 边界；不扩展
> 其他 IO API。

> LIB-07 的已裁方案与实施边界。本文记录为什么选这个形状，不重开裁决。

## 问题

旧 `io.delete(path) -> Bool !io` 把三件不同的事放进一个位：成功删除为 `true`，路径不存在、
非空目录、权限拒绝和其他 host error 都为 `false`。调用方既不能把幂等的“不存在”当正常分支，
也不能可靠发现资源释放失败。

## 选项

1. 保留 `Bool`：兼容，但继续 blind。
2. 改为 `Result[Bool, ForeignError]`：能分 host error，但 `true` / `false` 的含义仍靠记忆。
3. 改为 `Result[DeleteOutcome, ForeignError]`，其中 `DeleteOutcome = Deleted | NotFound`。

## 裁决

选择第三项。`Deleted` 与 `NotFound` 是调用方必须处理的两个正常结果；非空目录、权限、busy
等其他 host refusal 是 `Err`。删除只处理一个文件或一个空目录，从不递归。

公开 wrapper 还在接触后端前拒绝两个有歧义的拼法：空串与以 `/` 结尾的 path。两者都回
`ForeignError { kind: "io.invalid_delete_path", ... }`，message 也由规范固定。JVM 会把这些
拼法交给 `Path` 规范化，C `remove` 则按原字节解释；试图让某一端模仿另一端，等于允许删除
API 在后端边界悄悄改变调用方命名的对象。故这里选择拒绝，不做后端规范化。

底层 `io_delete` 保留 `Bool` ABI：`true` 只表示已删除，`false` 只表示不存在，其他失败 raise
fault。`std/io` 以 `catch_fault` 把 fault 变成 `ForeignError`，再给两个 Bool 值命名。这样运行时
边界不携带 Dawn ADT，同时公开 API 不泄漏 Bool blindness。

当前标准库没有 `Path` 类型，所有文件 API 都以 `String` 表示路径；只为 `delete` 引入一个
别名或包装会让同一模块出现两套路径货币。因此本次签名沿用
`delete(path: String) -> Result[DeleteOutcome, ForeignError] !io`。若未来引入真正的 `Path`，应把
整组文件 API 一次迁移，而不是让 `delete` 单独特殊化。

## 后端落点

- JVM 调用 `Files.deleteIfExists`：仅不存在返回 `false`，其余异常由 `catch_fault` 接住。
- native C 调用 `remove`：成功返回 `true`，保存 `errno` 后释放路径缓冲；仅 `ENOENT` 返回
  `false`，其他值走既有 fault 机制。
- native 抽出共享 `dawn_has_nul`。`exists` / `is_dir` / `is_symlink` 这三个 Bool 查询先用它
  判断，含 NUL 直接回 `false`；其余会读取、修改或以 `Result` 报错的路径操作仍进入
  `dawn_cpath`，并在分配 C 字符串前 fault。C API 无法表示 NUL 后的后缀，截断不是容错而是
  改指另一个目标，因此两类接口都 fail closed，只按各自公开返回形状选择 `false` 或 fault。
- `dawn_cpath` 还服务环境变量名与子进程参数。全调用点复核后，唯一遗漏的无错误通道是
  `getenv -> Option`：native 在进入共享桥前对 NUL 回 `None`，与 JVM 一致。其余调用者要么是
  上述三个 Bool 查询，要么经 `Result` / `catch_fault` 暴露失败：`mkdirs`、文本/字节读写、
  `list_dir`、`delete`、`rename`、`temp_dir`，以及 `run` 的 argv/stdout/stderr；这些继续由共享桥
  拒绝 NUL，不能截断。源码中共有 18 个调用表达式，分属这 14 个 owner function，没有第二个
  Bool/Option 接口遗漏。
- JVM 对三个 Bool 查询也显式生成同一 NUL preflight；尤其 `Files.isSymbolicLink` 在构造
  `Path` 时原本会抛 `InvalidPathException`，不能靠 `File.exists` / `isDirectory` 的偶然行为
  推断它也会回 `false`。

`packages/web` 是 N−1 ecosystem differential 的语料；前一 release 捆绑的 std 仍把
`io.delete` 定义为 Bool，因此它不能在同一破坏窗口引用新构造器。该包在本 release 过渡期
直接调用同一个 `Files.deleteIfExists` 并立即把 Bool 分成成功/缺失、把异常交给
`catch_fault`，不再使用会吞异常的 `File.delete`。种子推进后才能改成 `io.delete`，否则
`selfhost-prev-diff` 会把“旧 std 编不动当前生态”误当作允许的 emit 差异。

## 验收

同一行为合同覆盖文件、空目录、缺失、非空目录、重复删除、内嵌 NUL、空串与尾 `/`，并在
JVM/native 两端比较书面预期及目标仍存在。NUL 合同还逐项固定 `exists` / `is_dir` /
`is_symlink` 均回 `false` 而非 fault，`getenv` 回 `None`。合同常驻七组可运行 mutant：JVM
恢复 `File.delete`，C 恢复“所有失败都 false”，C 删除 `dawn_cpath` 的 NUL 检查，std 删除
公开 preflight，C 逐一删除三个 Bool 查询 guard，JVM 删除 `is_symlink` guard，以及 C 删除
`getenv` 的 Option guard。每个 mutant 都必须成功编译运行，再由对应行为用例打红。

## 不做的（记录理由）

- 不顺手给 `exists` / `is_dir` / `is_symlink` 增加 checked 版本：三者按既有 Bool 契约把
  invalid path 与“不匹配”一起回答为 `false`；是否新增 checked 孪生是另一组 IO API 裁决。
- 不以权限作为唯一合同：CI 身份和文件系统会改变权限结果；非空目录是稳定的 host refusal。
- 不把 `DeleteOutcome` 放进 prelude：它只属于 `std/io`，全局构造器会污染普通程序命名空间。
- 不定义 Windows 反斜杠的尾分隔符策略：当前任务只收口 `/` 的确定跨后端分歧；若 Dawn
  正式承诺 Windows 路径语义，应和整组 String-path API 一起裁决，不能由 `delete` 单独猜测。
