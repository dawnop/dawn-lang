# 结构化任务：作用域、取消、deadline 与监督

> 状态：**proposed**。2026-10-28。C02 仅固定语义合同；Task、fiber、线程与调度器均未立项。
> 本文不是当前语言保证，也不是实现批准。精确 API、类型与效果表达仍须通过前置设计。

## 1. 问题与边界

一次性续延能保存计算，但不能单独保证任务有人等待、取消时资源得到清理、孩子失败有人观察。
当前没有公共 Task、Scope、取消树或 deadline API；已有 `ctl` 与宿主线程机制不等于任务调度器。
本提案采用普通函数直接调用的结构化库方向，由具名控制效果和 scheduler driver（下称 driver）管理续延。
scope 是承担子任务终结责任的作用域，task 是它管理的工作；这些名称与下文的 fork、checkpoint、
yield、wait、join、Timeout 都是说明性术语，不冻结函数签名，也不是新增语法或 std 模块。

合同依赖的现有设计及其边界：

| 材料 | 复用的合同与尚缺的能力 |
|---|---|
| [one-shot 与 discard](oneshot-design.md) | 动态至多消费一次、显式丢弃与不可挂起清理；driver 另须承担每张挂起票最终被消费的责任。 |
| [Clock](clock-design.md) | 单调 `Instant`、假钟与读数；现有同步 sleep 不是可取消定时器，未来等待迁入任务效果，Clock 读数保持不挂起。 |
| [native failure](native-failure-design.md) | panic/fault、失败载荷所有权与展开清理；取消不改写成可捕获失败，RC 账本清理不代替用户 release。 |
| [Mem 捕获作用域](mem-capture-scope-design.md) 与 [Mem 缓冲](mem-buffer-design.md) | 捕获依赖及控制边界仍是待实现方案；GC/RC 保活不能证明作用域正确，任务不得绕过这些约束。 |

## 2. 结构与能力

1. 用普通调用与具名效果表达可能挂起或创建工作的义务；`io` 不吸收具名标签。不增加
   async/await、隐式 Future 返回类型或第二套调用语法。
2. 每个活动 task 恰属一个存活 scope。scope 返回、传播失败或交付取消结果前，所有直接和传递
   子任务均已终止并完成约定清理。禁止 detached、fire-and-forget 与无人负责的活动句柄。
3. 正常离开时关闭该 scope 的新提交并等待已有任务，body 提前正常返回不取消孩子；失败或取消
   离开时关闭提交、取消未完成孩子并等待清理。已有子 scope 按自身生命周期收束，不用全局关闭位
   阻止它们正常收尾所需的工作。
4. scope 与活动 task 句柄不得授权域外新操作。首版可用不透明句柄及 owner/generation 动态检查
   拒绝误用；静态不可逃逸须另证。结果按普通值规则带出，别名不分散唯一终结责任。
5. 捕获资源与效果证据活到所有消费者结束。共享资源的 bracket 包在 scope 外，或由 scope 登记
   持有；孩子不得使用父 body 已关闭的资源。此合同不承诺识别任意整数 FD 的误用。Mem 捕获须
   符合作用域方案，无法证明安全的跨域或跨线程捕获首版拒绝。

共享资源的说明性伪码如下，表示生命周期嵌套，不是可编译的 Dawn API：

```text
bracket(open_resource(), close_resource, resource =>
  task_scope(scope =>
    spawn(scope, () => use_resource(resource))
  )  // 孩子完成并清理后才离开
)    // 然后关闭共享资源
```

## 3. 取消请求与交付

6. 取消是幂等、粘滞的 scope 状态请求，可记录原因；请求不等于终止，也不撤销已发生的 IO。
   父取消传播到子树，子失败是否牵连兄弟由 scope 政策决定。
7. 只在显式合作点交付：首次进入任务 body 前、checkpoint/yield、参与调度的 sleep/wait/join，
   以及明确支持取消的宿主等待。纯计算、普通函数入口、分配与普通 effect 调用不是隐式取消点；
   长计算须主动合作，不合作的循环可永久延迟取消。
8. 外部事件只记录请求并唤醒 driver，由 driver 在受控交接处消费续延。不向 C/JVM 栈异步注入
   异常，不用 pthread_cancel、Thread.stop 或 signal handler 执行 Dawn handler；首版不承诺
   外部线程直接调用 Dawn 闭包。
9. 已在可取消等待中的任务由 driver 撤销注册并消费续延，不依赖 IO 最终到来。就绪、到期、
   取消竞争同一完成票，只有一个胜出，其余注销或识别为过期，不能再次 resume/discard。
10. 无资源的 checkpoint/yield 可在恢复用户代码前检查取消。产生资源或已完成副作用的操作采用
    **提交交付规则**：开始前检查；成功被 driver 接受并承诺交付后，不在交付与调用方安装保护
    之间追投取消；取消先胜则 adapter 回收未交付资源。不得在 bracket 实参取得资源后、保护
    安装前新增取消点。若 release/body 实参表达式自身会 checkpoint，须预先求值或采用明确
    屏蔽的 acquire-and-register 组合器；用户取得资源后主动 yield 的空隙不在保护保证内。
11. 非参与式同步 Fs/Proc/FFI 调用只能在调用前检查，返回后等下一显式合作点，不承诺在内核或
    C 桩内及时取消。adapter 须逐操作说明如何中止底层工作，不能只结束等待并遗留后台工作。

## 4. 挂起续延的所有者

12. 原始 k 不公开给任务使用者。挂起时唯一消费权交给 driver 的任务记录；队列、timer、IO waiter
    只持 task ID + generation 或受控索引，不各自持可独立消费的 k。
13. 每张挂起票仅能 `Held → Resumed` 或 `Held → Discarded`，恰选一次；再次挂起产生新票。
    现有动态至多一次之外，driver 必须保证每张持有票最终被消费。
14. driver 独立于所保存的 handler 激活，不得把自身续延放回自身状态形成 RC 环；私有 handler
    state 也须证明无回边并有 teardown。恢复保留原激活的状态、证据、失败载荷与任务局部上下文，
    不能以当前宿主线程状态替代，也不能以 JVM 会 GC 作为所有权证明。
15. fork 使用提交调用处选定的证据，不是闭包创建点的 handler 或稍后 driver 的环境。证据借用与
    拥有范围随 scope 证明；有状态 handler 的重入规则须明确。首版只开放已证明安全的单执行者
    共享或每任务独立实例，不隐式复制状态或假定可跨线程。

## 5. 清理与关闭顺序

16. 受管任务取消显式展开，复用 discard 的不可捕获终止语义，不转成可被 catch 吞掉的 panic/fault，
    不靠裸丢 k、GC 或 RC 归零执行用户 release；到拥有它的 scope 边界才转换为可观察取消状态。
17. 已安装 bracket 的 release 从内到外恰好一次；catch 不截住取消，release 失败不阻止其余清理。
    沿用 discard 仅交付第一条清理失败的规则，不承诺恢复已被现行规则丢掉的错误。
18. 首版清理是不挂起的受保护区间：允许同步 close/release，禁止 yield、spawn、join、调度 sleep
    与 ctl；效果未知时须有动态 guard。保护只延迟交付，不清除请求；阻塞 release 可拖延退出。
19. 等待孩子由 scope driver 负责，不由 finalizer 负责。driver 关闭提交、处理后代后，才释放共享
    资源并交付结果；不能在 bracket release 里 join。嵌套取消按资源依赖先处理后代，再 discard
    仍承载祖先资源的续延，由 driver 树保证顺序。
20. panic/fault 也须在 scope 边界内截获终止原因，排空后代再向外传播，不得先释放孩子依赖的
    外部资源。短生命资源不能借给更长的子任务；不能保证次序就不开放该 spawn 形状。
21. 不新增 defer/finalizer 语法。将来若需可挂起清理，应另设计活动阶段的关闭协议加最终同步
    release，或重新裁定 discard 展开机，不能直接移植可挂起的 NonCancellable 清理。

## 6. deadline 组合

22. deadline 是取消请求的时间条件，不是停止时刻或副作用回滚边界。timeout 返回仍须等待孩子与
    清理，不合作任务可使它永久等待；硬上限依赖进程隔离，杀进程不保证用户清理。
23. 使用同一调度域的单调 `Instant`。相对 timeout 在进入 scope 时转换一次，嵌套取父与本地较早者，
    不延长祖先预算；无 deadline 用显式 None/Infinite，不占整数最大值。duration ≤ 0 在进入 body
    前请求取消，重试使用剩余预算。
24. 较早按单调时间顺序判断，不对裸 Int 直接取 min。须规定可比较跨度严格小于有符号半周期，
    检查 duration 溢出并在同一钟域比较剩余量；`instant_at_ns` 不证明跨进程或假钟域可比较。
25. 首版 deadline 创建后不延长，不开放任意业务 shield。清理屏蔽自动且仅限不挂起区间，父到期
    仍记录；未来若加嵌套 shield，须另定传播边界和本地 deadline 规则。
26. deadline、显式 cancel、失败均保留来源 scope ID；只有创建 deadline 的边界能把自己的到期
    转为 Timeout，不把父取消吞成子 timeout。正常完成已提交后 cancel 无效；完成与到期由同一
    driver 事件顺序裁定，并覆盖假钟同刻场景。

## 7. 子错误与监督

27. 区分普通值、领域失败、panic、foreign fault、取消、deadline 与清理失败。`Result.Err` 仍是值，
    只有显式理解 Result 的任务组合器才将它视为失败，不反射搜索任意结果中的 Err。
28. 默认遇错收束：选定失败渠道向 driver 报告后，记录原因、关闭提交、取消兄弟及相应 body 工作，
    等待后代清理再交付。未 join 的孩子也必须有人观察错误。
29. 清理后才发布最终 outcome。记录触发原因及已交付 driver 的后续失败，保留 task ID、阶段和
    panic/fault 区别；派生取消不算重复业务错误。列表按稳定 task ID 呈现，首个触发取决于事件顺序。
30. 保持现行 bracket 的 release 失败可替换 body 失败、discard 只交付首次清理失败的规则。scope
    仅归集收到的结果，不能恢复已覆盖的失败；完整 suppressed 树须另改错误模型。
31. 默认先收束，再按原渠道传播 panic/fault，不降级为可忽略 Err 或改名为取消。精确 API 须明确
    多渠道报告与选择规则；建议 panic、fault、领域失败、纯取消依次优先，同渠道首个观察为主，
    其余留在报告。具体报告类型尚未冻结，缺报告不能成为漏清理或吞 panic 的理由。
32. 监督只改变失败传播，不等于重启。首版可显式把孩子领域失败 Result 化并收集，使健康兄弟继续；
    scope 仍等待，父取消仍下传，panic/fault 默认仍使全组收束，隔离它们须有显式故障边界。
    不默认打印错误后当成功，不提供无限重启或脱离父寿命的 supervisor。
33. 自动重试与 restart policy 属上层库，须受父 deadline 和次数预算约束，说明副作用可否重复；
    生命周期与监督政策相互独立，不隐含退避或重试预算。

## 8. 后端合同

34. 首版限定单一逻辑执行者的合作式并发，不承诺 CPU 并行或跨线程迁移。JVM 与 native 对相同
    确定性输入、假钟和调度事件流给出相同任务结果、取消原因、release 次数与顺序；真实 IO
    完成顺序不要求跨后端一致。
35. 冻结栈、carrier、poller、RC/GC 是可替换机制，不能使用户清理依赖不可预测的 GC 或 RC 时机，
    也不能用 JVM interrupt 替代 Dawn 完成票。单逻辑执行者不表示只有一条 OS 线程。
36. 纯 fork-join `std/par` 方向独立，按从左到右顺序求值的语义，不进任务效果。多工作线程、共享
    RC、线程安全 allocator/handler/Mem/FFI 另立验证边界；GPU 设备并行不自动批准宿主任务。

## 9. 重开实施与验收条件

实施必须同时满足以下条件：

- 有具名 native 消费者和具体失败断言，证明顺序调用、一请求一进程或现有子进程工具不能满足需要。
- GPU 与 dejava 优先工作不缺实施和验证资源，且维护者明确重裁 fiber/线程的不实施决定。
- fork 的类型与效果证据、driver 队列所有权、Mem 捕获都有可检查设计，不靠 unsafe cast 或 io 擦除。
- native 载体的资源上限、失败方式及消费者并发规模经独立测量被接受；若换栈机制，先复审展开、
  ASan/LSan 与 Perceus 每帧恰一次清理，不预支性能结论。

将来的验收要证明：父 scope 在正常、失败、取消三条路径均不遗留孩子、等待注册或未消费票；
资源不早于最后消费者释放且只释放一次；完成与取消竞态只消费一次续延；假钟同刻、嵌套 deadline、
清理失败及多个孩子失败在双后端给出约定结果。删除显式 discard 必须使清理记录或活跃票计数失败，
裸丢续延不能通过。任务交替打印的演示不构成这些不变量的证据。

## 不做的（理由）

- 不实现 Task、fiber、线程、调度器、关键字或 std 模块，也不把本提案写进规范保证；前置尚未满足。
- async/await 永久不做；直接调用与具名效果是既定方向。JVM StructuredTaskScope 薄封装、裸 context
  均不足以定义双后端的任务树、消费票与清理责任，不作为替代方案。
- 不做强杀线程、GC finalizer 取消或可挂起 release；它们不满足受控交付与现行 discard 合同。
- 不把 C02 作为 dejava 前置，不要求先有 native Net 或线程池，也不为复用 JVM 任务 API 引回 Java。
- 不扩为任意异步 FFI callback。现有 [extern 设计](ffi-extern-design.md) 的借用参数与 owned 返回不等于
  后台任务协议；异步 adapter 将来还须单独证明注销、借用结束、资源回收及完成票。
