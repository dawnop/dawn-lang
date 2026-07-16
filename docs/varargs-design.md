# 传可变实参 —— 设计草案（动码前定稿）

> M7 序 5.5。补上 spec §9.3 明确记录的 v0.1 缺口：**变长参数方法只支持不传可变部分的调用；
> 传可变实参 v0.1 不支持**。

## 1. 为什么现在做

流式请求体那轮撞上了它：JDK 的 `BodyPublishers.concat(head, filePart, tail)` 能一步拼出
「头部字节 + 磁盘文件 + 尾部字节」的 multipart 体，是标准答案。它是变参方法，Dawn 调不了，
于是 `qiniu_rs.upload_file` 只好**先把三段在磁盘上装配成一个完整文件、再 `ofFile` 上传**——
内存仍是 O(1)，但白白多了一次磁盘拷贝。

这不是孤例。变参在 JDK 里是主干而非边角：`List.of` / `Set.of` / `Map.ofEntries`、
`Path.of`、`String.format`、`String.join`、`Arrays.asList`、`CompletableFuture.allOf`、
`ProcessBuilder.new`。**Dawn 现在一个都调不了**（只能调"省掉可变部分"的退化形式，
如 `Path.of(p)`、`List.of()`）。补上它解锁的是一整类 API，而不是一个方法。

## 2. 语法：内联铺开，不是传 List

```dawn
let p = BodyPublishers.concat(head, filePart, tail)!   # 三个实参 → BodyPublisher[]
let l = List.of("a", "b", "c")!
let e = List.of()!                                     # 空可变部分，今天就支持，语义不变
```

**不采用「传一个 `List[T]` 当可变部分」**（`concat([head, file, tail])`）。三条理由：

1. **读者对不上签名**。Java 侧签名写的是 `concat(BodyPublisher...)`，调用方看到 `[...]`
   要在脑子里做一次转换；内联铺开与 Java、与所有读过 JDK 文档的人的预期一字不差。
2. **它会和 §9.6 的 List 桥打架**。`List[T]` 实参现在**已经**有含义——桥到
   `List`/`Collection`/`Iterable` 形参（零拷贝不可变视图）。再让它同时表示"可变部分展开"，
   就得在 `f(List...)` 这种签名上二选一，是自找的歧义。
3. **它更弱**。内联铺开不要求元素能跨界（§9.6 的 `bridgeableElem` 限制），
   `BodyPublisher` 这种 Java 引用本来就在 List 桥的白名单里，但函数值、嵌套容器不在——
   而变参数组是逐个实参独立打分的，不受这条限制。

代价：传一个**已有数组**当可变部分（Java 允许 `String.format(fmt, argsArray)`）走的是另一条路——
见 §3 的相位 1，实参数与形参数相等且类型可赋值时，数组**原样传入**，不重新打包。这与 JLS 一致。

## 3. 重载消解：引入相位，替掉 `-1` 罚分

JLS 分两相消解：**先不考虑变参**试一轮（相位 1），**全部失败**才按变参试（相位 2）。
Dawn 今天用「变参候选减 1 分」近似它。这个近似在只有"空可变部分"一种形式时碰巧成立
（固定部分相同，减 1 就够分胜负），**推广到传实参就会错**：分数是逐参求和、随实参数增长，

```
foo(String, String)             精确匹配 → 1 + 1 = 2
foo(String, Object...) 打包 1 个 → 2 + 2 - 1 = 3   ← 赢了，但按 JLS 应该输
```

所以打分改成**字典序的二元组 `(phase, score)`**：`phase` 1 = 不打包，0 = 打包；同相位内再比
`score`。空可变部分那种形式随之落进相位 0，结果与今天一致——**改的是理由，不是行为**。

- **相位 1**：`params.size == args.size`，逐参 `paramScore`。数组形参照旧由
  `TBytes`/`TJava` 分支消化（`byte[]` 精确匹配、不透明 `Object` 下转），故"传现成数组"落这里。
- **相位 2**：仅当方法 `isVarArgs` 且 `args.size >= params.size - 1`。固定部分逐参打分，
  **尾部每个实参对 `componentType` 打分**（复用同一个 `paramScore`，它按下标取实参类型）。
  任一参不匹配 → 整个候选出局。

## 4. AST 与 codegen：空数组是打包的 count==0 特例

检查器在选中相位 2 时记 `e.varargsPack = params.size - 1`（开始打包的下标）。
分量类型不必另存——`javaMethod/javaCtorRef.parameterTypes.last().componentType` 就是。

于是今天的 `pushEmptyVarargs` **不再是特例**：它就是 `varargsPack != null` 且尾部 0 个实参。
两处调用点（`genJavaNew` / `genJavaCall`）合并成一条路径：

```
固定部分逐个 genExpr + adaptJavaArg
push count; NEWARRAY/ANEWARRAY component
每个尾部实参: DUP, push idx, genExpr, adaptJavaArg(component), xASTORE
```

`xASTORE` 按分量类型选（`AASTORE`/`IASTORE`/`LASTORE`/`DASTORE`/`FASTORE`/`BASTORE`/
`CASTORE`/`SASTORE`）；`adaptJavaArg` 原样复用，Dawn `Int`→`int` 分量的 `L2I` 白拿。

`finalizeSams` 里的 `if (i >= params.size) break` 换成"取第 i 个形参"的小函数
（打包时下标 ≥ 固定数就返回分量类型），于是 **SAM 转换与 List 桥在可变部分里自动可用**，
不需要额外代码。

## 5. 明确不做

- **装箱**。`Object...` 收不了 Dawn 的 `Int`/`Float`/`Bool`——`paramScore` 里标量只匹配
  对应的 Java **基本类型**，`Object` 形参一律 null。所以 `String.format("%s", 1)` 仍然编不过，
  `String.format("%s", "x")` 可以。这是 §9.2「基本类型不装箱」的既有边界，**与变参正交**，
  要动是另一道题（影响所有形参位置，不该塞进这一轮）。文档里如实写明。
- **`char` 分量**：`char` 出入参 v0.1 本就不支持（§9.2），`char...` 随之不支持。
  `NEWARRAY T_CHAR` 的分支保留（空数组形式要用），但没有实参能填进去。

## 6. 验收

1. `BodyPublishers.concat(head, file, tail)` 编得过、跑得对 → 回头删掉 `upload_file`
   的磁盘装配，multipart 三段直接流出（**这是本轮的实证**：省一次全量磁盘拷贝）。
2. 单测：`List.of(a,b,c)` 元素与顺序正确；`Path.of("a","b")` 拼出 `a/b`；
   空可变部分行为不变（回归）；相位 1 优先于相位 2（`foo(String,String)` vs `foo(String,Object...)`）；
   传现成数组走相位 1 不重新打包；分量类型不匹配时报错且列出候选。
3. 全量 1135+ 测试绿；backend-dawn 59 测试绿；100MB PUT 生产复验内存仍平。
