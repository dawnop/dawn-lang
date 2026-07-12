# Dawn

一门小而完整的静态类型语言：编译到 **JVM 字节码**，同一份代码经 GraalVM
native-image 直接产出**独立原生二进制**。两级效果系统把「纯」写进签名；
没有 null、没有异常、没有继承。

```dawn
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)
  derive Show

fn area(s: Shape) -> Float =
  match s {
    Circle(r) -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }

pub fn main() -> Unit !io =
  println(to_string(area(Circle(2.0))))
```

- **ADT + 穷尽性检查**——漏一个分支，编译器告诉你漏了哪个
- **效果系统**——`!io` 写进签名，纯函数是承诺不是注释
- **`?` 传播 + `Result`/`Option`**——错误是值，不是控制流
- **模块系统、Map/Set、字符串插值（`$name`/`${expr}`）、raw string、comptime**
- **内建 `test` 块与 `dawn fmt`**——测试和格式化不是第三方件
- **LSP + VS Code 扩展**——诊断、悬停、跨文件跳转、格式化随语言同步演进

从[教程](tutorial/index.html)开始上手；语言细节的权威定义在[规范](spec.html)；
[示例](examples/index.html)可以直接 `dawn run`；内建函数一览见[标准库](api.html)；
每个设计取舍的「为什么」写在[设计笔记](design.html)。
