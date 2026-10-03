<!-- doc-check: translation-of site/pages/packages.md @ 65a474a822db7b87 -->
# 包页文案，中文，译本

`packages.html` 的全部文字。生成器按名字读这些小节（`site/src/gen/packages.dawn`），
做法与 cuTile 页读 `gpu.md` 相同，缺一节就构建失败。正本是 `packages.md`，
两边的键相同，本文件记着正本的摘要。

这里没有任何具体某个包的内容：名字、版本、依赖与模块在建站时从各包的 `dawn.toml`
与 `dawn doc` 读出，一句话简介取自各包 `README.md` 的首段。`{archive}` 是生成器
放入发布版源码归档链接的位置。

## title

包

## lede

与编译器同住本仓库的 Dawn 源码包。每个包都是带自己 `dawn.toml` 的工程，可以按路径依赖引用，也可以从发布版的源码归档引用。

## chip-packages

个包

## chip-source

取自 `dawn.toml`、`README.md` 与 `dawn doc`

## th-package

包

## th-name

manifest 名

## th-version

版本

## th-summary

简介

## th-deps

依赖

## th-use

引用写法

## deps-none

只依赖 std

## use-path

路径

## use-archive

归档

## use-note

`<dawn-lang>` 是本仓库的一份检出，路径相对于使用方的 `dawn.toml`。`<archive>` 是某个发布版的源码归档，例如 {archive}；`dawn add` 会抓取它，并在 `[deps.<alias>]` 下写好 `url`、`version`、`hash` 与 `subdir`。

## name-note

主版本 2 及以上的包，manifest 名以主版本号结尾（`json2`、`web6`）。第一列的别名是 `use` 行里写的名字，所以升主版本不用改它们。
