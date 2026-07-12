# site/ — Dawn 语言网站（M5）

静态站点，**生成器用 Dawn 写**（dogfood M4 的模块系统 / Map / 字符串 API）。
产物纯 HTML + CSS，**零 JS**（代码高亮在构建期完成）；nginx 托管，零后端。

- 域名：`https://dawn-lang.dawnop.com`（与 GitHub 仓库名一致）
- 验收：站点上线，且生成它的程序是 Dawn 写的；生成器 JVM 与 native 跑出的
  `dist/` **逐字节一致**（项目传统）。

## 目录

```
site/
├── src/            # 生成器（纯 Dawn，dawn run site 直接跑）
│   ├── main.dawn   # 组装：读 docs/ + examples/ → 写 dist/
│   ├── md/         # Markdown 子集解析器
│   ├── hl/         # Dawn 语法高亮 tokenizer（构建期）
│   └── html/       # 转义、模板壳、TOC、slug
├── assets/         # style.css 等文本资产（原样拷入 dist/assets/）
├── pages/          # 站点专属内容（index.md 等）
├── sample/         # 手写验收样张 —— 渲染以此为准绳（验收样例先行）
└── dist/           # 产物（gitignore）
```

内容单一来源 = 仓库根的 `docs/*.md` 与 `examples/**`，**不复制不搬家**。

## 信息架构（URL 映射）

| 路径 | 内容 | 来源 |
|------|------|------|
| `/` | 首页：定位一句话 + 高亮样例 + 特性栏 + 各区入口 | `site/pages/index.md` |
| `/tutorial/{01..14}.html` | 教程 14 章，每章一页，带上一章 / 下一章 | `docs/tutorial.md` 按 `##` 切分 |
| `/tutorial/index.html` | 教程目录页 | 同上（章标题清单） |
| `/spec.html` | 语言规范单页 + 侧栏 TOC | `docs/spec.md` |
| `/design.html` | 设计笔记（D1–D7 决策 + 里程碑） | `docs/design.md` |
| `/examples/index.html` | 示例陈列页 | `examples/**` |
| `/examples/{name}.html` | 每例一页：高亮源码（+ 多文件项目按模块列出） | 同上 |
| `/api.html` | 标准库参考：内建函数按类分组，签名 + 描述 | `dawn doc --builtins --json` |
| `/playground.html` | 占位页（「二期开发中」） | 模板 |

## 渲染约定

- **Markdown 子集**（docs 实际用量驱动，遇到解析不了的语法**报错退出**，
  生成器兼任 docs 的 lint）：
  - 块级：`#`/`##`/`###` 标题、段落、围栏代码（带语言标记）、无序列表（嵌套）、
    有序列表、表格、引用、`---` hr。
  - 行内：`` `code` ``、`**bold**`、`*em*`、`[text](url)`。行内码优先于表格分列
    （单元格里的 `|` 在反引号内不作分隔）。
- **围栏语言**：`dawn` → 构建期高亮；`dawn skip-check` → 同 `dawn`（剥掉标记）；
  `output` → 输出块（CSS 加「输出」角标）；其余（`bash`、裸块）→ 只转义不高亮。
- **锚点**：标题用编号 id（`#s2-3` = 第 2 节第 3 小节），不做中文 slug。
- **高亮类名**（GitHub Light 配色）：`k` 关键字、`t` 类型/构造器（大写首字母）、
  `f` 定义名（`fn` 后的标识符）、`s` 字符串、`i` 字符串内 `$` 插值、`n` 数字/布尔、
  `c` 注释。函数**调用**不着色（tokenizer 保持行级简单）。
- **资产全文本**：CSS/SVG 用 `read_file`/`write_file` 原样搬运，站点不放光栅图
  （不给 String IO 开二进制洞）。
- 生成后扫一遍内部 `href`，断链即失败退出。

## 分刀进度

- [x] 刀 0：验收样张（`sample/tutorial-04.html`、`sample/spec-excerpt.html`）+ 本 README
- [x] 刀 1：stdlib IO 补齐（`list_dir` / `is_dir`；`write_file` 自动建父目录）
- [x] 刀 2：`dawn doc`（`##` 文档注释提取 + `--builtins` JSON）
- [ ] 刀 3：Markdown 子集解析器（Dawn）
- [ ] 刀 4：Dawn 语法高亮器（Dawn）
- [ ] 刀 5：HTML 渲染 + 模板 + CSS（Dawn）
- [ ] 刀 6：main 组装 + 全量生成 + 断链自检
- [ ] 刀 7：验证（`dawn test` / `fmt --check` / JVM=native 逐字节）
- [ ] 刀 8：部署 `dawn-lang.dawnop.com`（nginx + 通配符证书 + redeploy.sh）

## 构建与部署（占位，刀 6/8 补全）

```bash
dawn run site          # 生成 site/dist/
site/redeploy.sh       # 本地生成 + rsync 上服务器（刀 8）
```
