# 集合 spike：纯 Dawn 集合值不值得做

回答一个问题:如果按 [`docs/collections-dejava-research.md`](../../docs/collections-dejava-research.md)
的 D 计划把 Map/List 换成纯 Dawn 实现,**自举总时长**要付多少代价。结论与数据见该文 §9。

四组实验,互相独立。

## 实验一：纯 Dawn HAMT vs 手写 Java HAMT

```bash
./bin/dawn run scripts/spike-hamt/hamt.dawn
```

`hamt.dawn` 用今天的语言写了一个 32 叉路径复制的持久哈希表(泛型 ADT,节点孩子放 ≤32 宽的 List 当
`Array` 的替身),对着 builtin Map 量插入/查找/三种「编译器真实形态」。开头自带正确性自检。

读数时记住两处**已知的偏悲观**:节点更新用 `slice ++ [x] ++ slice`(约 3 次分配)近似 `Array.with` 的
一次 `arraycopy`;以及每层返回 `(Node, Bool)` 元组——因为纯 Dawn 没有引用相等,无法像 DawnMap 那样用
`n == m` 判断子树没变。

## 实验二：集合慢 20× 对自举的真实影响

不外推,直接模拟:把 vendored 的 `DawnMap`/`DawnList` 换成「每次操作内部干 20 遍」的版本(20× 正是实验一
量到的倍数),放在种子 jar **前面**的 classpath 上,量同一条编译命令。

```bash
# 1. 取源码(工作树只有 .class,源在 kotlin-final tag)
git show kotlin-final:compiler/src/main/java/dawn/rt/DawnMap.java  > /tmp/DawnMap.java
git show kotlin-final:compiler/src/main/java/dawn/rt/DawnList.java > /tmp/DawnList.java

# 2. 改成干 20 遍,结果存进一个 volatile static 防止被优化掉,javac -d /tmp/patched
# 3. 量(种子路径按 scripts/seed-release.txt)
SEED=.dawn/seeds/v0.11.0/seed.jar
ARGS="build selfhost --std std --embed-std std --vendor dawn/tool \
      --vendor org/objectweb/asm --vendor coursierapi"
/usr/bin/time -f "base  wall=%e user=%U" java -Xss512m -cp "$SEED"          main $ARGS -o /tmp/a.jar
/usr/bin/time -f "patch wall=%e user=%U" java -Xss512m -cp "/tmp/patched:$SEED" main $ARGS -o /tmp/b.jar
```

占比按 `T' = T(1 + 19·S)` 反推。

## 实验三：纯 Dawn 持久向量(严格 RB)

```bash
./bin/dawn run scripts/spike-hamt/vec.dawn
```

`vec.dawn` 是 Clojure 式 PersistentVector(32 叉 trie + 尾块)。**别把实验一的倍数套到 List 上**——HAMT
插入和 List 追加是完全不同的操作,这就是这个文件存在的原因。

它同时量两个变体,差别只在尾块怎么更新,而这正是后端原语 `array_with` 的语义:

- `push` 用 `copy_push`(每次真复制)→ 模拟**没有**唯一性追踪的 `array_with`;
- `push_owned` 用 `tail ++ [x]`(继承 DawnList 的 owned-tail 技巧)→ 模拟**有**唯一性就地写的 `array_with`
  (native 的 Perceus,或一个保留该技巧的 JVM `Array`)。

两者相差约 12 倍,**这就是 D3 可不可行的开关**。

## 实验四：编译器的 list 用法计数

给 `DawnList.concat` 加 `AtomicLong` 计数器 + 一个 shutdown hook 打印,量一次完整编译走快路径还是复制路径。
结果见主文 §9.5(快路径命中 99.1%,一次编译 7,700 万次追加)。

## 坑,别重踩

**测量方法上的:**

- **别把 `DawnList.concat` 整个跑 20 遍。** 重复调用会自己和自己抢 owned-tail 的 CAS,后 19 次落到 O(n)
  复制路径,累积重新变成 O(n²)——编译 10 分钟都跑不完,量到的不是「慢 20×」而是另一个实验。要把倍率加在
  **不碰 `used`** 的 O(add) 忙等上。
- **`main` 线程在 park,活在别的线程上**;而且编译器递归极深,JFR 默认 `stackdepth=64` 会把采样全丢掉
  (5 秒只采到 13 个)。所以这里用扰动法而不是采样法。
