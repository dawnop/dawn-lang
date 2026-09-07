#!/usr/bin/env python3
"""Check accepted callback values by executing verified classes, not only linking."""
import sys
import shutil
import tempfile
import zipfile
from pathlib import Path

from never_probe import ADD_EXPORTS, ROOT, compiler_command, run


def require(command, label, expected=None):
    result = run(command)
    if result.returncode or (expected is not None and result.stdout != expected):
        raise RuntimeError(f"ASSERT: {label}\n{result.stdout}\n{result.stderr}")
    return result


def main():
    jar, verifier = map(lambda p: Path(p).resolve(), sys.argv[1:3])
    with tempfile.TemporaryDirectory(prefix="sam-values-") as tmp:
        work = Path(tmp)
        require(["javac", "-d", str(work), str(ROOT / "scripts/classfile-verify/SamValues.java")], "SAM_FIXTURE")
        fixture = work / "fixture.jar"
        require(["jar", "cf", str(fixture), "-C", str(work), "fixture"], "SAM_FIXTURE")
        for name in ("bytes", "narrow"):
            source = ROOT / f"scripts/classfile-verify/sam_{name}.dawn"
            label = f"SAM_{name.upper()}"
            out = work / name
            program = work / f"{name}.jar"
            require(compiler_command(jar, "build", "--cp", str(fixture), str(source), "-o", str(program)), label + "_BUILD")
            with zipfile.ZipFile(program) as archive:
                archive.extractall(out)
            require(["java", *ADD_EXPORTS, "-cp", f"{verifier}:{fixture}:{jar}", "Verify", str(out)], label + "_VERIFY")
            require(["java", "-jar", str(program)], label + "_VALUE", label + "_OK\n")
        invalid = work / "bad.dawn"
        invalid.write_text('use java "fixture.SamValues"\npub fn main() -> Unit !io = { let _ = SamValues.bytesValue(() => "not bytes") }\n')
        rejected = run(compiler_command(jar, "build", "--cp", str(fixture), str(invalid), "-o", str(work / "bad.jar")))
        if rejected.returncode == 0 or "error" not in rejected.stdout + rejected.stderr:
            raise RuntimeError("ASSERT: SAM_BYTES_REJECT_STRING\n" + rejected.stdout + rejected.stderr)
    print("OK: SAM Bytes mapping, null boundary and signed return ranges")
    if "--mutants" in sys.argv[3:]:
        mutants(jar, verifier)


def mutants(jar, verifier):
    variants = [
        ("bytes", "check/checker.dawn", [
            ('  } else if p == "[B" {\n    Some(TyBytes)\n', ''),
            ('  } else if r == "[B" {\n    Some(TyBytes)\n', ''),
            ('      TyBytes -> js.is_assignable(j, "[B")\n', ''),
        ], "SAM_BYTES_BUILD"),
        ("narrow", "jvm/emit.dawn", [
            ('    if rc == "byte" { m.visitInsn(OP_I2B) }\n', ''),
            ('    if rc == "short" { m.visitInsn(OP_I2S) }\n', ''),
        ], "SAM_NARROW_VALUE"),
    ]
    for name, relative, edits, marker in variants:
        with tempfile.TemporaryDirectory(prefix=f"sam-mutant-{name}-") as tmp:
            work = Path(tmp)
            for directory in ("selfhost", "compiler-plan"):
                shutil.copytree(ROOT / directory, work / directory)
            (work / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
            source = work / "selfhost/src" / relative
            text = source.read_text()
            for old, new in edits:
                if text.count(old) != 1:
                    raise RuntimeError(f"mutation anchor drifted: {relative}: {old!r}")
                text = text.replace(old, new)
            source.write_text(text)
            mutant = work / "compiler.jar"
            require(compiler_command(jar, "build", str(work / "selfhost"), "-o", str(mutant)), "SAM_MUTANT_COMPILE")
            result = run([sys.executable, str(Path(__file__).resolve()), str(mutant), str(verifier)])
            if result.returncode == 0 or f"RuntimeError: ASSERT: {marker}\n" not in result.stderr:
                raise RuntimeError(f"{name} mutant missed owning assertion\n{result.stdout}\n{result.stderr}")
            print(f"PASS: compiling {name} mutant triggers only {marker}")


if __name__ == "__main__":
    main()
