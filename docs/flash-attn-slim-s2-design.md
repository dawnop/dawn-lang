# FlashAttention 几何瘦身 S2

> 状态：**current**，实现完成；基线为 S1 合入的 a112a84860b497f4d0dfd8d34bd22765bbfd07f7。

## 设计契约

普通 MHA 的 head 由三维存储和 grid axis 2 表达。Q/O 使用
`cells([heads,n,d],[1,bq,d],along=[2,0,1],squeeze=[0])`，K/V 使用
`along=[2,FREE_AXIS,1]`，grid 为 `[n/bq,1,heads]`。单头同样走三维布局。
共享算法与五参闭包工厂只捕获 dtype 见证和具名数值实例；删除算法侧
FaShape/FaTiles、fa_kv_index、单头分支及 acc_from_out 初始化开关。
录制侧保留 S1 的正数、M=N、整块与 I32 元素偏移检查，以及原 plan/hints。

`cells(...,squeeze=[])` 按原 storage 维度指定 tile 长度为 1 的轴，extent
可以大于 1。列表按集合解释，允许无序，重复、负数、越界和非单例轴在 body
运行前拒绝，并保留 caller 和 argument 身份。剩余值维度保持 storage 原顺序；
全轴投影得到 rank-0。空投影不改变旧 TileProg、lower、MLIR 或 tilebc。

storage extent/tile/pad/along、EntryArg、grid、reach、alias、In 跟随及 Out
单射证明均使用完整几何。extent_of/blocks_of 和 load_at 的 FREE_AXIS
下标保持 storage 编号。投影不修复非法 Out 或 along。
load 在原 view load 后通过现有 reshape 投影，zeros/fill 直接生成值形状常量。
store_cell 先精确验证值形状，保留 scalar 广播，再逆投影并走原 view store
和 Out 所有权路径。同元素数的错误形状也拒绝。store_sub 的 piece 使用值维度，
逆投影在被删轴插 shape=1、piece=0，再复用原块内证明。

`tile_shape[D](Tile[D],at=caller())->List[Int] !Dev` 复用 t_shape_of，只查询
记录期静态值形状，不分配 handle，不发 opcode，保留零 IR 调用来源。
新内部 cells 形状查询迁移全部 handler/mock；Grid ADT 一次迁移所有构造与 match。

算法保留 m/l/acc 声明、carry 和更新顺序、两次 MMA 数据流、运行期 scale、
五参 ABI、只读 token 和 A2 F32 输出。两个私有 fa_exp/fa_divide helper 仅表达
原有两种具名策略；f64 精确 exp/div，bf16 保留 exp2/FTZ、未收窄 p 求和、
第二 MMA 前 nearest-even 收窄和 approx/FTZ div。统一 acc=zeros(o)，不读取旧 O。

样例展示字面 bq=32/bk=16、heads=1 三维布局，保留独立 plain attention
与 1e-12 断言。doc-check 全文固定共享体、工厂、实际 helper 和必要类型。
xmap 的 TileCall 保留录制 id/parent，公开记录改形状按 0.x 升至 0.2.0。
map 严格核对真实 trace、parser span、compiler Loc、父子调用树及唯一行归属；
同名 helper 的两个调用分别配对，tile_shape 等零 IR 来源不能丢失。

## 验收与产物

允许有因果解释地更新六个 flash golden 及新增投影资产。其它已有 golden
必须逐字节保持。先比较库投影和显式 reshape 对照，再逐条解释 storage view、
stride/dim_map、三轴索引、四个边界 reshape、常量、carry/SSA/token。
shape 查询不得新增 IR。独立参考、解释器和设备覆盖两 dtype、d32/64/128、
heads1/2、多 query/key block、bq≠bk、两个 scale 及后续最大值上升。
负控须先成功编译/录制，再由指定 oracle 拒绝。

三本设备账只追加最终 inputs 的真实运行，顺序 sm100→sm90→sm86。
历史 P4/A2 时间仍属于旧展平布局，新布局只沿用启动 plan。有限同配置测时
另存完整资源、cubin/SASS 和数值结果；回退报告协调者，不更换 tiles/hints，
不提高容差、不重扫配置。最终外部门包含 tree-policy 内部发布自测，
complete=true；不执行实际证据发布。

## 不做的（理由）

不扩 M≠N、尾 query/key、有效域或 mask；这些需要独立算法契约。不加入 GQA、
Grouped/CellAxis、六参入口、新语言、新 opcode 或任意布局代数。不改 matmul、
MMA/transpose 的 rank 限制、数值策略、调优网格或历史性能账。不部署或发版。


## 实施验收记录

库实现采用 store_sub 的窄逆投影，无延期限制；tileir 公开 Grid 变更升为
0.27.0。tileir 290、tileinterp 197、xmap 35 项覆盖投影、存储保护、rank-0、
同元素数错误形状、哨兵、零 IR 查询及重复 helper 调用来源。
36 组旧新录制的 TileProg/lower/MLIR/tilebc 共 288 个文件在最终 source
再次完整比较；六个允许入口的正式资产单独审核，其余 466 个资产保持不变。
解释器两 scale 全量独立参考覆盖 4,128,768 lanes，旧新 neq=0。

样例使用真正运行期误差 guard，普通输出保持原样；错误 scale 的可执行变体
由 1e-12 检查拒绝。严格 map 为 45 calls/55 ops，Tile pane 32 calls，
C/JVM 样例 83 个唯一来源 span 相等；六类新鲜源负控均先成功编译录制再红。

有限同配置测量发现 sm100 f64 d64 回退：heads1 约 7.9%，heads2 约 5%，
重复轮相近。frame/min-stack 从 1176 增至 1208 字节，寄存器仍为 255；
该关联不证明唯一根因。保留所有 SASS、ELF section 与不透明执行产物，
sm90 f64 d64 的重复测量另见约 8.7% 至 8.8% 回退，BF16 d64/heads2
约 2.3% 至 2.8%；
各架构的重复测量与完整结果交协调者依据报告决定。未修改 plan/hints 或放宽
容差，新布局不声称性能等价。
最终三卡、完整门禁与 PR CI 的精确身份和墙钟见交付报告。
