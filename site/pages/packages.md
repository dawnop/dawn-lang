# Packages page copy, English, the original

Everything `packages.html` says in words. The generator reads these sections
by name (`site/src/gen/packages.dawn`), the way the cuTile page reads
`gpu.md`, so a missing section fails the build. The Chinese translation is
`packages.zh.md`, with the same keys and a digest of this file.

What is not here: anything about a particular package. Names, versions,
dependencies and modules are read from each package's `dawn.toml` and from
`dawn doc`, and the one-line summary is the first paragraph of its
`README.md`, when the site is built. `{archive}` marks where the generator
puts the release's source archive.

## title

Packages

## lede

Dawn source packages kept in this repository beside the compiler. Each is a project with its own `dawn.toml`, used as a path dependency or from a release's source archive.

## chip-packages

packages

## chip-source

read from `dawn.toml`, `README.md` and `dawn doc`

## th-package

package

## th-name

manifest name

## th-version

version

## th-summary

summary

## th-deps

depends on

## th-use

dependency

## deps-none

std only

## use-path

path

## use-archive

archive

## use-note

`<dawn-lang>` is a checkout of this repository, relative to the consumer's `dawn.toml`. `<archive>` is a release's source archive, such as {archive}; `dawn add` fetches it and writes `url`, `version`, `hash` and `subdir` under `[deps.<alias>]`.

## name-note

A package at major version 2 or later carries the major at the end of its manifest name (`json2`, `web6`). The alias in the first column is the name `use` lines spell, so a major bump does not move them.
