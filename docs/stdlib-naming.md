# stdlib 命名：破坏性重组为模块限定式（P0.7）

> 2026-07-22 初版曾定「平铺名永久有效、永不改名」，同日被否决：**要优雅，
> 可以做破坏性更新**。本文改写为破坏性路线的设计定稿；实施排为 P0.7（自举 P1 之前）。
>
> **状态：已实施。** v0.4.0 落地 §一/§二全部三处语义与双拼写过渡（平铺名逐处
> 警告），本仓与 backend-dawn 全量迁移；v0.5.0 删平铺名。规范表述见 spec §10.6/§11。

## 一、目标拼写（端态）

```dawn
use std/map                     # 整模块：限定访问
use std/list.{map, filter}      # 选择性：热名直呼（Gleam 模型）

let m = map.insert(map.empty(), "k", 1)
let v = map.get(m, "k")
xs |> filter(fn(x) => x > 0)    # 选择性引入的短名进管道，零摩擦
```

- std 收进**真模块**：`std/list`、`std/map`、`std/set`、`std/str`、`std/bytes`、
  `std/cursor`、`std/io`。短名 API（`insert/get/has/keys/…`、`len/at/slice/…`）。
- **平铺前缀名（`map_insert`/`byte_len`/`cursor_next`…）整体退役**：迁移完成后从
  全局命名空间删除。编译器内建保留**内部**实现（intrinsic），但公开拼写只有模块名。
- prelude 收缩到真正的高频核：`println`、`map/filter/fold/range/len/get`、
  `Option`/`Result` 构造器、`to_string`、`panic`/`todo`、`java_try`/`catch_panic` 等
  一屏以内；其余一律 `use`。

## 二、要动的三处语义（P0.7 的实现清单）

1. **捆绑 std 的可引入性**：`use std/x` 命中 classpath 资源 `std/x.dawn`（磁盘同名
   路径优先报冲突而非静默遮蔽）。std 模块经正常 ModuleExports 走 §10.3 的限定访问
   与选择性引入，LSP 跳转/补全免费获得。
2. **顶层声明遮蔽内建改为合法**（Rust 式）：注册期「`map` is a builtin and cannot
   be redefined」的错误删除；解析顺序本就是本模块声明 → std → 内建，遮蔽自然生效。
   design.md D10 的相应条目作废、就地修订。std 模块自身正是第一批受益者
   （`std/list` 里的 `pub fn len` 不再非法）。
3. **键类型合法性检查（§2.2）改挂 `TMap`/`TSSet` 实例化处**，不再按内建函数名点名
   （KEYED_CREATORS），使 wrapper/转发天然穿透、报错落在用户代码的实例化点。

## 三、迁移（破坏性，两仓一次结清）

- v0.4.0：std 模块 + 短名落地，平铺名保留但**弃用警告**；本仓（std 内部、examples、
  site、playground、golden、教程）与 backend-dawn 全量迁移到新拼写。
- v0.5.0：平铺名删除。两版之间不接受新的平铺名用法。
- 自举编译器（M7 四刀）直接用新拼写书写。

## 四、不做的

- 不做 `m.insert(k, v)` 式方法调用（UFCS 只认非限定名，无重载消解可依）——限定
  `map.insert(m, k, v)`、选择性引入短名、管道三条路已够优雅。
- 不为 `x |> map.insert(k, v)`（限定名进管道）扩语法：需要时选择性引入即可。
