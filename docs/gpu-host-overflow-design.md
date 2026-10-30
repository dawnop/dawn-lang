# GPU 宿主尺寸与几何溢出拒绝

> 状态：**current**。已实现，宿主边界测试与三架构全录已验收。

## 问题与旧方案

修前 `std/gpu.dawn` 的 `alloc` 只拒绝非正元素数，handler 随后计算字节数。
Int 按语言规范环绕，因此 F64 的 `2^61+1` 个元素会变为 8 字节。
`cell_count` 的 `(extent+tile-1)/tile` 在合法正数上也会先溢出。
`reach` 直接计算动态 `grid*tile` 和 extent 连乘，`2^32*2^32` 会变成 0。
手工构造 Entry 的静态 Free 维同样走这条路径，不能依赖 recorder 的限制。
上述算式来自当前源码；第一步用只接受元数据的 mock handler 与纯计划测试验证，
不分配极值内存，也不提交极值设备请求。

## 方案与落点

- `alloc` 在 effect 之前按已知格式宽度用 `len > IntMax / width` 拒绝，沿用
  `gpu.bad_length`。非正数仍先拒绝，未知格式仍交给 handler。
- 正 extent 的 ceil-div 使用 `(extent-1)/tile+1`，保留动态哨兵。
- `reach` 返回检查结果，在每次正数乘法前用除法判断上界，分别指出动态维的
  grid 与 tile 乘积、以及跨维 extent 乘积。溢出沿用 `gpu.short_tensor`，因为
  没有任何 Int 长度的 buffer 能覆盖该 reach。
- 保持 entry、参数种类、alias、grid、follow、逐参数 buffer 容量的检查顺序。
  不在 entry_grid 提前拒绝乘积，以免改变既有几何/别名拒绝优先序。
- 回归测试进入 `std/gpu.dawn`，涵盖手工 Free 维、动态维、合法商边界和拒绝
  优先序；每项检查单独去掉后必须被语义断言抓住。
- 更新 `packages/tileir/ERRORS.md` 与 public API 文档，从本分支 std 生成 stdsrc。

## 验收与预算

修前 `dawn test std/gpu.dawn` 为 4/54 失败，四组新增测试全部按断言失败；
修后 54/54 通过。四个单项变异分别去掉 alloc 字节检查、恢复加法 ceil-div、
去掉动态 grid×tile 检查、去掉 extent 连乘检查，各由对应测试断言捕获。
动态乘法变异特意选择环绕为正数的因子，避免把后续除零崩溃误算为有效负控。
修前源码、日志、变异补丁与 SHA-256 均留存于验收记录。
相关本机门与最终提交完整外部门执行，不调整预算或黄金文件。
`std/gpu.dawn` 属于 tile inputs，所以需要 sm100、sm90、sm86 串行全录，
每轮完成并取得原始日志与收据后才开始下一轮。极值不进入设备，全录只用现有合法语料。

实现提交 `002111b0` 的 inputs 为 `1f1547599e94`，按 sm100、sm90、sm86
顺序完成全录，全部退出 0；适用的设备负控分别有 99、98、92 项通过。
sm90 与 sm86 的不支持项保留明确 SKIP，不计为 PASS。三本 ledger 只追加，
保留实际运行的源码提交，不改写历史或重标来源。完整外部门按最终提交执行。

## 不做的（理由）

不改变 Int 的环绕语义，不引入大整数，不改 recorder 的形状域、GPU kernel、
架构输入集合或 runtime ABI。直接 effect 调用的格式/长度策略仍是 handler 的
契约；本次封住 typed alloc 与 typed entry 的宿主验证边界。
