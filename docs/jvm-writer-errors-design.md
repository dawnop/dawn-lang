# JVM 发射错误的分类与原始异常保全

> 状态：current

通用错误诊断改进；不声称修复任何尚未定位的字节码生成缺陷。

现有 `class_bytes_from` 把所有 Java 异常渲染为类文件容量不足，只保留
message；Observed 的尺寸探针也把任意异常当作重新分区的反馈。这会把
非法参数、实现错误和真正的容量上限混在一起，并丢掉原始栈。

只对 `MethodTooLargeException` 与 `ClassTooLargeException` 保持原有容量
诊断和探针分区。其它异常立即报告，带类名、阶段、原异常类型及原始栈。
无法在公开 ASM 边界取得的方法、opcode、operand 和偏移明确记 unknown。

在已有 `AsmWriter` 子类的 `toByteArray` 边界保留原 Java cause；成功时原样
返回 superclass 的字节。通用诊断类由可审阅 Java 源码生成，只有使用 ASM 的
程序才携带。适配器登记类名；弱引用表不延长 writer 生命周期。不修改或影子
替换第三方 ASM，不声称这个外层边界能取得 private 重写入口的原始输入。

用户显式设置 `dawn.jvm.diagnostics` 系统属性时才尝试保存诊断到该已存在目录。
文件名不覆盖，权限限所有者读写；不支持该权限机制的平台保存失败，并保留
原错误。保存错误作为原 cause 的 suppressed 异常，不替换原错误。若调用者
确实提供内部输入上下文，先复制字节再保存；通常的 writer 边界没有输入，
应写 unavailable，不能把成功输出冒充失败输入。诊断可能包含源路径和常量，
由用户选择保全目录。默认不写诊断文件。

嵌入载荷由 `scripts/gen-asm-diagnostics.py --javac "$JAVA_HOME/bin/javac"`
从 Java 正本生成，适配器合同门检查载荷是否过期。只有真正可得的数值才填入
上下文，空值表示 unknown；已知的负 operand 保持原符号。

确定性回归比较合法发射与 stock ASM 的原始字节，分别验证非法 opcode、
非法 atype、空上下文、保存失败及已知容量异常原样传播。测试使用合成输入，
不收录真实用户故障现场。编译器及使用 ASM 的程序身份会变化，既有身份的
资格证据不能换标签使用；普通不依赖 ASM 的合法程序输出应保持不变。

不做的：不升级 ASM、不更改 JIT 设置、不添加内部 ASM 钩子，不推断缺失的
opcode，不以诊断改进代替原故障根因证明或完整验证。
