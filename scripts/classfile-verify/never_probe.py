#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 240
SOURCE = '''use java "java.util.Objects"

trait Bottom[T] {
  fn required(x: T) -> Never
  fn defaulted(x: T) -> Never = panic("default")
}

type Token = Token

impl Bottom[Token] {
  fn required(x: Token) -> Never = panic("impl")
}

fn direct_halt() -> Never = panic("direct")

fn via_direct(take: Bool) -> Int = if take { direct_halt() } else { 71 }

fn via_dynamic(take: Bool) -> Int = {
  let halt: fn() -> Never = direct_halt
  if take { halt() } else { 72 }
}

fn via_closure(take: Bool) -> Int = {
  let halt: fn() -> Never = () => panic("closure")
  if take { halt() } else { 73 }
}

fn via_impl(take: Bool) -> Int = if take { required(Token) } else { 74 }

fn via_default(take: Bool) -> Int = if take { defaulted(Token) } else { 75 }

fn via_trait[T: Bottom](take: Bool, value: T) -> Int =
  if take { required(value) } else { 76 }

fn via_sam(take: Bool) -> Int !io = {
  if take {
    Objects.requireNonNullElseGet("value", () => panic("sam"))
    0
  } else {
    77
  }
}

pub fn main() -> Unit !io = {
  println("${via_direct(false)}")
  println("${via_dynamic(false)}")
  println("${via_closure(false)}")
  println("${via_impl(false)}")
  println("${via_default(false)}")
  println("${via_trait(false, Token)}")
  println("${via_sam(false)}")
}
'''
EXPECTED = "71\n72\n73\n74\n75\n76\n77\n"
WIDE_SAM_SOURCE = '''use java "java.util.stream.LongStream"

fn halt() -> Never = panic("wide sam")

fn via_wide_sam(take: Bool) -> Int !io =
  if take {
    LongStream.generate(halt)
    0
  } else {
    81
  }

pub fn main() -> Unit !io = println("${via_wide_sam(false)}")
'''
WIDE_SAM_EXPECTED = "81\n"


def compiler_command(jar, *args):
    return ["java", "-Xss512m", "-Xmx2g", "-jar", str(jar), *args]


def run(command, **kwargs):
    return subprocess.run(
        command,
        cwd=kwargs.pop("cwd", ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=TIMEOUT,
        **kwargs,
    )


def method_body(disassembly, signature):
    lines = disassembly.splitlines()
    start = None
    for index, line in enumerate(lines):
        if signature in line:
            start = index + 1
            break
    if start is None:
        return ""
    body = []
    for line in lines[start:]:
        if re.match(r"  (public|private|protected|static)\b", line):
            break
        body.append(line)
    return "\n".join(body)


def javap(class_file):
    proc = run(["javap", "-c", "-p", str(class_file)])
    return proc.stdout if proc.returncode == 0 else ""


def terminates(body, call, discarded):
    expected = []
    if discarded:
        expected.append("pop")
    expected.extend(["aconst_null", "athrow"])
    return has_contiguous_opcodes_after(body, call, expected)


def has_contiguous_opcodes_after(body, call, expected):
    instructions = []
    for line in body.splitlines():
        match = re.match(r"\s*\d+:\s+([a-z0-9_]+)\b", line)
        if match:
            instructions.append((line, match.group(1)))
    for index, (line, _) in enumerate(instructions):
        if call in line:
            actual = [opcode for _, opcode in instructions[index + 1:index + 1 + len(expected)]]
            if actual == expected:
                return True
    return False


def core_shapes(core):
    required = [
        "call direct never_calls.direct_halt : Never",
        "call dynamic : Never",
        "call impl never_calls trait=",
        "call default never_calls trait=",
        "call method trait=",
        "closure never_calls.lambda$2 : fn() -> Never",
    ]
    return all(item in core for item in required)


def structural_results(out_dir):
    main = javap(out_dir / "never_calls.class")
    direct = terminates(
        method_body(main, "long via_direct(boolean)"),
        "Method direct_halt:()V",
        False,
    )
    dynamic = all(
        terminates(
            method_body(main, f"long {name}(boolean)"),
            "Fn0.apply:()Ljava/lang/Object;",
            True,
        )
        for name in ("via_dynamic", "via_closure")
    )
    impl = all([
        terminates(
            method_body(main, "long via_impl(boolean)"),
            "dawn$impl$Bottom$Token$required",
            False,
        ),
        terminates(
            method_body(main, "bridge$"),
            "dawn$impl$Bottom$Token$required",
            False,
        ),
    ])
    default = terminates(
        method_body(main, "long via_default(boolean)"),
        "dawn$default$Bottom$defaulted",
        False,
    )
    method = terminates(
        method_body(main, "long via_trait(boolean"),
        "Bottom.required:(Ljava/lang/Object;)V",
        False,
    )

    dict_files = list((out_dir / "dawn" / "dict").glob("never_calls$dict*.class"))
    dictionary = len(dict_files) == 1
    if dictionary:
        disassembly = javap(dict_files[0])
        dictionary = all([
            terminates(method_body(disassembly, "void required("), "invokestatic", False),
            terminates(method_body(disassembly, "void defaulted("), "invokestatic", False),
        ])

    closure_files = sorted((out_dir / "dawn" / "fn").glob("never_calls$*.class"))
    closure = len(closure_files) == 3
    if closure:
        closure = all(
            terminates(method_body(javap(path), "apply("), "invokestatic", True)
            for path in closure_files
        )

    sam_bridge = terminates(
        method_body(main, "dawn$sam$0("),
        "Fn0.apply:()Ljava/lang/Object;",
        True,
    )
    sam_files = list((out_dir / "dawn" / "sam").glob("never_calls$*.class"))
    sam_adapter = len(sam_files) == 1
    if sam_adapter:
        sam_adapter = terminates(
            method_body(javap(sam_files[0]), "java.lang.Object get()"),
            "invokestatic",
            True,
        )
    return {
        "NEVER_DIRECT_CALL_TERMINATION": direct,
        "NEVER_DYNAMIC_CALL_TERMINATION": dynamic,
        "NEVER_IMPL_CALL_TERMINATION": impl,
        "NEVER_DEFAULT_CALL_TERMINATION": default,
        "NEVER_TRAIT_CALL_TERMINATION": method,
        "NEVER_DICTIONARY_TERMINATION": dictionary,
        "NEVER_CLOSURE_TERMINATION": closure,
        "NEVER_SAM_BRIDGE_TERMINATION": sam_bridge,
        "NEVER_SAM_ADAPTER_TERMINATION": sam_adapter,
    }


def wide_core_shape(core):
    return all(item in core for item in [
        "foreign java.util.stream.LongStream.generate static",
        "closure never_wide_sam.lambda$0 : fn() -> Never",
        "call direct never_wide_sam.halt : Never",
    ])


def wide_adapter_terminates(out_dir):
    sam_files = list((out_dir / "dawn" / "sam").glob("never_wide_sam$*.class"))
    if len(sam_files) != 1:
        return False
    body = method_body(javap(sam_files[0]), "long getAsLong()")
    return has_contiguous_opcodes_after(
        body,
        "invokestatic",
        ["pop2", "aconst_null", "athrow"],
    )


def main():
    modes = {"--mutant", "--verified-mutant"}
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] not in modes):
        print(
            "usage: never_probe.py <compiler.jar> <verify-classes> "
            "[--mutant|--verified-mutant]",
            file=sys.stderr,
        )
        return 2
    jar = Path(sys.argv[1]).resolve()
    verify_classes = Path(sys.argv[2]).resolve()
    mutant = len(sys.argv) == 4
    verified_mutant = mutant and sys.argv[3] == "--verified-mutant"
    failed = []
    with tempfile.TemporaryDirectory(prefix="dawn-never-calls-") as tmp:
        work = Path(tmp)
        source = work / "never_calls.dawn"
        core_dir = work / "core"
        out_dir = work / "out"
        wide_source = work / "never_wide_sam.dawn"
        wide_core_dir = work / "wide-core"
        wide_out_dir = work / "wide-out"
        source.write_text(SOURCE)
        wide_source.write_text(WIDE_SAM_SOURCE)
        core_dir.mkdir()
        out_dir.mkdir()
        wide_core_dir.mkdir()
        wide_out_dir.mkdir()

        lower = run(compiler_command(jar, "__lower", "--dump", str(core_dir), str(source)))
        core_file = core_dir / "never_calls.core"
        core_ok = lower.returncode == 0 and core_file.is_file() and core_shapes(core_file.read_text())
        emit = run(compiler_command(jar, "__emit", str(source), "-o", str(out_dir)))
        if emit.returncode != 0:
            for marker in structural_results(out_dir):
                failed.append(marker)
        else:
            for marker, passed in structural_results(out_dir).items():
                if not passed:
                    failed.append(marker)

        wide_lower = run(compiler_command(
            jar, "__lower", "--dump", str(wide_core_dir), str(wide_source)
        ))
        wide_core_file = wide_core_dir / "never_wide_sam.core"
        wide_core_ok = (
            wide_lower.returncode == 0
            and wide_core_file.is_file()
            and wide_core_shape(wide_core_file.read_text())
        )
        wide_emit = run(compiler_command(
            jar, "__emit", str(wide_source), "-o", str(wide_out_dir)
        ))
        wide_accepts = wide_core_ok and wide_emit.returncode == 0
        if not wide_accepts:
            failed.append("NEVER_WIDE_SAM_ACCEPTANCE")
        elif not wide_adapter_terminates(wide_out_dir):
            failed.append("NEVER_WIDE_SAM_ADAPTER_TERMINATION")

        if verified_mutant:
            emitted_dirs = []
            if emit.returncode == 0:
                emitted_dirs.append(out_dir)
            if wide_emit.returncode == 0:
                emitted_dirs.append(wide_out_dir)
            for emitted_dir in emitted_dirs:
                verify = run([
                    "java",
                    "-cp",
                    f"{verify_classes}:{jar}",
                    "Verify",
                    str(emitted_dir),
                ])
                if verify.returncode != 0:
                    failed.append("NEVER_MUTANT_CLASSFILE_VERIFY")
        elif not mutant:
            if not core_ok:
                failed.append("NEVER_CORE_CALL_FORMS")
            verify = run([
                "java",
                "-cp",
                f"{verify_classes}:{jar}",
                "Verify",
                str(out_dir),
            ])
            if verify.returncode != 0:
                failed.append("NEVER_CLASSFILE_VERIFY")
            executed = run(["java", "-cp", str(out_dir), "never_calls"])
            if executed.returncode != 0 or executed.stdout != EXPECTED or executed.stderr != "":
                failed.append("NEVER_CALL_RUNTIME")
            if wide_accepts:
                wide_verify = run([
                    "java",
                    "-cp",
                    f"{verify_classes}:{jar}",
                    "Verify",
                    str(wide_out_dir),
                ])
                if wide_verify.returncode != 0:
                    failed.append("NEVER_CLASSFILE_VERIFY")
                wide_executed = run([
                    "java", "-cp", str(wide_out_dir), "never_wide_sam"
                ])
                if (
                    wide_executed.returncode != 0
                    or wide_executed.stdout != WIDE_SAM_EXPECTED
                    or wide_executed.stderr != ""
                ):
                    failed.append("NEVER_CALL_RUNTIME")

    for marker in failed:
        print(f"ASSERT: {marker}")
    if failed:
        return 1
    print("classfile Never call contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
