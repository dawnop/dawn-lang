#!/usr/bin/env python3
"""Require each broken static contract to fail its owning executed test.

Each mutant compiler must build and start successfully. A parse, bootstrap
or test-compilation failure is not a semantic kill. Compile whitebox tests
with the unmutated driver so the mutation executes inside its owning test,
rather than altering the driver that admits the test program and its std.
Source strings keep new syntax outside the compiler's seed-readable
bootstrap inputs.

Disjoint control shards bound each gate's wall time. The source matrix stays
whole in its own invocation so both frontends use one native compiler build.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

# mutate.py owns every exactly-once source edit below.
from mutate import MUTATIONS, apply
from summary_cases import matrix, observe

ROOT = Path(__file__).resolve().parents[2]
TEST = "selfhost/src/check/trait_capture_test.dawn"
PROBE = Path(__file__).with_name("subwitness.dawn")
CALLS = Path(__file__).with_name("calls.dawn")
OWNERS = {
    'drop-staged-method-application': 'staged applications solve callback Scope equations before finalizing Item',
    'erase-staged-callback-environment': 'staged associated outputs and callback rows retain their declared application',
    'skip-staged-scope-equation': 'staged applications solve callback Scope equations before finalizing Item',
    'forget-local-value-edge': 'local value edges retain unknown origins and real resources without a type projection',
    'reuse-template-module-owner': 'shared prelude templates keep call identities and module declarations independent',
    'reuse-template-scope-identities': 'shared prelude templates keep call identities and module declarations independent',
    'reuse-template-capture-identities': 'shared prelude templates keep call identities and module declarations independent',
    'value-bound-is-full-support': 'ordinary value bounds cannot prove complete support without a witness premise',
    'forget-support-premise': 'ordinary value bounds cannot prove complete support without a witness premise',
    'skip-type-application-obligations': 'explicit data and alias bounds apply before expansion on every kind path',
    'skip-call-type-bounds': 'computation defaults reject values while explicit capture bounds remain open',
    'skip-constructor-type-bounds': 'constructor introduction inherits bounds and all parent axes when used as a value',
    'erase-parent-constructor-axes': 'constructor introduction inherits bounds and all parent axes when used as a value',
    'block-opaque-function-conversion': 'opaque owner conversion checks the full function representation contract',
    "erase-call-value-bounds": "concrete calls infer declared value Capture bounds before selecting witnesses",
    "erase-item-scope-instantiation": "concrete Item reduction substitutes the witness Scope before comparing results",
    "erase-effect-scope-instantiation": "associated Mem bindings retain the impl Scope in exported metadata",
    "erase-dictionary-argument-support": "dictionary support includes Scope arguments outside the subject",
    "erase-scoped-bridge-evidence": "associated Mem bridge selects its scoped evidence from the projection pack",
    "erase-trait-binders": "trait Capture syntax retains arguments bounds and formatting",
    "erase-bound-arguments": "complete trait applications survive interface export and reload",
    "erase-projection-upper": "associated Item upper bounds are independent of subject captures",
    "erase-forwarded-application": "trait default forwards the declared complete application",
    "erase-default-environment": "trait default checks rigid environments at the definition",
    "ignore-subject-support": "impl application support and private Scope checks precede members",
    "ignore-item-upper": "associated Item upper bounds are independent of subject captures",
    "widen-invariant-arguments": "witness checking keeps Capture arguments invariant",
    "erase-associated-scope": "associated Mem bindings retain the impl Scope in exported metadata",
    "ignore-subwitness-support": "impl dependency checks retain subwitness and member type support",
}
MODULES = {'value-bound-is-full-support': 'check/data_capture', 'forget-support-premise': 'check/data_capture', 'skip-type-application-obligations': 'check/data_capture_test', 'skip-call-type-bounds': 'check/data_capture_test', 'skip-constructor-type-bounds': 'check/data_capture_test', 'erase-parent-constructor-axes': 'check/data_capture_test', 'block-opaque-function-conversion': 'check/data_capture_test'}
CASE_OWNERS = {'env-use-S': [('closure_phantom', 1, 'escapes its scoped callback'), ('closed_bind_phantom', 1, 'cannot prove the captured value environment')], 'function-args-in-env': [('wrapped_function', 1, 'capture bound')], 'effect-in-env': [('uncalled_effect_function', 1, 'capture bound')], 'exit-use-V': [('direct_phantom', 0, '')], 'arrow-free-empty': [('direct_function', 0, '')], 'phantom-is-capability': [('phantom_recreate', 1, 'capture')], 'scope-id-collapse': [('function_relabel_buffer', 0, '')], 'dictionary-drop-W': [('dictionary_forwarded', 0, '')], 'eta-drop-W': [('dictionary_eta', 0, '')], 'direct-drop-W': [('dictionary_direct_phantom', 0, '')], 'operation-drop-env': [('handler_store_buffer', 0, '')], 'empty-list-value': [('aggregate_list', 0, '')], 'skip-synthetic-env': [('staged_defer_buffer', 0, '')]}
OWNERS['erase-value-parameter'] = 'data summaries distinguish phantom support from reachable values'
MODULES['erase-value-parameter'] = 'check/data_capture'
OWNERS['erase-support-parameter'] = 'data summaries distinguish phantom support from reachable values'
MODULES['erase-support-parameter'] = 'check/data_capture'
OWNERS['stop-before-fixed-point'] = 'mutual summaries retain growing arguments through their least fixed point'
MODULES['stop-before-fixed-point'] = 'check/data_capture'
OWNERS['client-open-target'] = 'opaque value contracts use the public head instead of its hidden target'
MODULES['client-open-target'] = 'check/data_capture'
OWNERS['empty-unrestricted-data-parameter'] = 'data summaries distinguish phantom support from reachable values'
MODULES['empty-unrestricted-data-parameter'] = 'check/data_capture'
OWNERS['empty-missing-summary'] = 'a missing nominal summary remains unknown rather than empty'
MODULES['empty-missing-summary'] = 'check/data_capture'
OWNERS['erase-function-parameter-support'] = 'function fields separate empty environments from parameter and row support'
MODULES['erase-function-parameter-support'] = 'check/data_capture'
OWNERS['erase-scope-substitution'] = 'mutual summaries retain growing arguments through their least fixed point'
MODULES['erase-scope-substitution'] = 'check/data_capture'
OWNERS['drop-latent-effect'] = 'function_regain_mem'
CASE_OWNERS['drop-latent-effect'] = [('function_regain_mem', 0, ''),
    ('function_regain_mem_without_witness', 0, ''),
    ('phantom_regain_mem', 0, ''),
    ('phantom_regain_mem_without_witness', 0, '')]
MODULES['drop-latent-effect'] = 'check/data_capture'
OWNERS['abstract-effect-is-support'] = 'an abstract calling row is not a complete support proof'
MODULES['abstract-effect-is-support'] = 'check/data_capture'
OWNERS['forget-header-premise'] = 'complete witness premises validate header obligations across an interface'
MODULES['forget-header-premise'] = 'check/data_capture_test'
OWNERS['drop-recursive-value-edges'] = 'recursive value components retain the resource behind a late edge'
MODULES['drop-recursive-value-edges'] = 'check/environment'
OWNERS['missing-envelope-empty'] = 'opaque imports refuse a missing declaration envelope'
MODULES['missing-envelope-empty'] = 'check/data_capture_test'
OWNERS['env-use-S'] = 'closure_phantom'
OWNERS['function-args-in-env'] = 'wrapped_function'
OWNERS['effect-in-env'] = 'uncalled_effect_function'
OWNERS['exit-use-V'] = 'direct_phantom'
OWNERS['arrow-free-empty'] = 'direct_function'
OWNERS['phantom-is-capability'] = 'phantom_recreate'
OWNERS['scope-id-collapse'] = 'function_relabel_buffer'
OWNERS['dictionary-drop-W'] = 'dictionary_forwarded'
OWNERS['eta-drop-W'] = 'dictionary_eta'
OWNERS['direct-drop-W'] = 'dictionary_direct_phantom'
OWNERS['operation-drop-env'] = 'handler_store_buffer'
OWNERS['cell-content-V-only'] = 'staged_var_phantom'
OWNERS['empty-list-value'] = 'aggregate_list'
OWNERS['skip-synthetic-env'] = 'staged_defer_buffer'

OWNERS['skip-opaque-representation-proof'] = 'opaque definitions prove both components against their public head'
MODULES['skip-opaque-representation-proof'] = 'check/data_capture'

OWNERS['ignore-installation-support'] = 'storage writes retain the original lifetime through aliases'
MODULES['ignore-installation-support'] = 'check/value_capture'

OWNERS['erase-constructor-context'] = 'constructor contexts retain complete Capture equations before field inference'
MODULES['erase-constructor-context'] = 'check/data_capture_test'

# The retained CLI source owns its complete witness and Scope refusal.
# Value flow executes the production checker without loading std bodies.
BASELINE_CASES = {'forget-value-bound-flow': ['k3_generic']}
OWNERS['forget-value-bound-flow'] = 'k3_generic'
CASE_OWNERS['erase-passed-environment'] = [('k3_stored_effect', 0, '')]
OWNERS['erase-passed-environment'] = 'k3_stored_effect'
EXTRA_CASES = {'erase-default-environment': [
    'k3_direct', 'k3_list', 'k3_record', 'k3_repro', 'k3_stored', 'k3_len_capture']}

CASE_OWNERS['close-list-map-environment'] = [('list_map_buffer', 1, 'argument type mismatch')]
OWNERS['close-list-map-environment'] = 'list_map_buffer'
EXTRA_CASES['erase-default-environment'].append('list_map_escape')

CASE_OWNERS['close-list-filter-environment'] = [('list_filter_buffer', 1, 'argument type mismatch')]
OWNERS['close-list-filter-environment'] = 'list_filter_buffer'

CASE_OWNERS['erase-scalar-subject-contract'] = [('staged_closed_witness', 1, 'cannot prove the captured value environment')]
OWNERS['erase-scalar-subject-contract'] = 'staged_closed_witness'
MODULES['cell-content-V-only'] = 'check/checker'
EXTRA_ASSERTIONS = {'forget-support-premise': [
    ('staged_closed_witness', 1, 'cannot prove the captured value environment')],
    'ignore-item-upper': [('n9_item', 0, '')],
    'erase-forwarded-application': [('p0_iter', 1, '`measure` requires `Measure[T]`')],
    'direct-drop-W': [('function_regain_mem', 1, 'argument type mismatch: expected fn[@s_0]() -> (fn() -> Int) !Mem[s_0] ^{}, got fn[@s]() -> fn() -> Int !Mem[s]')]}
# These retained sources now refuse at protocol admission. Their refusal
# must not substitute for the whitebox content-support ownership assertions.
EXTRA_ASSERTIONS['cell-content-V-only'] = [
    ('staged_var_phantom', 1, 'trait `StagedVar` requires 1 Capture argument(s), got 0'),
    ('staged_result_phantom', 1, 'trait `StagedResult` requires 1 Capture argument(s), got 0'),
    ('staged_value_bound_only', 1, 'trait `StagedVar` requires 1 Capture argument(s), got 0'),
]
EXTRA_ASSERTIONS['direct-drop-W'].append(
    ('phantom_regain_mem_without_witness', 1, 'argument type mismatch'))
CASE_OWNERS['empty-list-value'].append(('aggregate_list_without_witness', 0, ''))
EXTRA_ASSERTIONS['direct-drop-W'].extend([
    ('aggregate_list', 1, 'declares return type fn() -> Int'),
    ('aggregate_list_without_witness', 1, 'declares return type fn() -> Int'),
])
CASE_OWNERS['operation-drop-env'].append(('n6_park', 0, ''))
CASE_OWNERS['scope-id-collapse'].append(('n11_generic_relabel', 0, ''))

OWNERS['erase-unknown-support-origin'] = 'unknown support explanations follow finite value dependencies'
MODULES['erase-unknown-support-origin'] = 'check/environment'

OWNERS.update({
    'skip-quantified-scope-renaming': 'Mem scope substitution renames a binder before capturing a replacement',
    'skip-function-defaults': 'ordinary function defaults reject domain values without changing data introduction',
    'skip-impl-defaults': 'impl Type defaults constrain application arguments independently of witness support',
    'skip-trait-defaults': 'trait subject defaults stay empty when the witness Capture axis is open',
})
for name in ['skip-function-defaults', 'skip-impl-defaults', 'skip-trait-defaults']:
    MODULES[name] = 'check/data_capture_test'
EXTRA_CASES['skip-function-defaults'] = ['default_function_closed']
EXTRA_CASES['skip-impl-defaults'] = ['default_impl_closed']
EXTRA_CASES['skip-trait-defaults'] = ['default_trait_closed']

MODULES['skip-quantified-scope-renaming'] = 'check/mem_scope_test'
MODULES['forget-local-value-edge'] = 'check/value_capture'
MODULES['reuse-template-module-owner'] = 'check/checker'
MODULES['reuse-template-scope-identities'] = 'check/checker'
MODULES['reuse-template-capture-identities'] = 'check/checker'

for name in ['drop-staged-method-application', 'erase-staged-callback-environment', 'skip-staged-scope-equation']:
    MODULES[name] = 'check/staged_capture_test'

for name, owner in {
    'drop-staged-runtime-witness-use': 'staged calls retain runtime dictionaries of conditional cell witnesses',
    'erase-exported-application': 'staged interfaces retain complete applications across module boundaries',
    'erase-staged-associated-upper': 'staged associated outputs and callback rows retain their declared application',
    'select-staged-first-arm': 'staged condition applications combine both arm environments',
    'widen-fixed-staged-application': 'fixed staged applications cannot widen to callback support',
}.items():
    OWNERS[name] = owner
    MODULES[name] = 'check/staged_capture_test'

LOWER_OWNERS = {"erase-dictionary-argument-support", "erase-scoped-bridge-evidence"}


def run(args, output, expected=0, env=None):
    start = time.monotonic()
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    output.write_text(result.stdout)
    if expected is not None and result.returncode != expected:
        raise RuntimeError(f"command exited {result.returncode}: {args}\n{result.stdout[-6000:]}")
    return result, time.monotonic() - start


def controls(out, names, jobs):
    # Warm the shared launcher before workers build independent compiler trees.
    run([ROOT / "bin/dawn", "--version"], out / "compiler-version.log")
    env = {**os.environ, "DAWN_LAUNCHER_PRINT_JAVA": "1"}
    java = subprocess.check_output([ROOT / "bin/dawn"], cwd=ROOT, env=env, text=True).strip()
    jvm = [java, "-XX:-UsePerfData", "-Xss512m", "-Xmx2g", "-XX:+UseSerialGC", "-jar"]

    def control(name):
        work = out / name
        work.mkdir()
        tree = work / "tree"
        for part in ["selfhost", "compiler-plan", "std"]:
            shutil.copytree(ROOT / part, tree / part,
                ignore=shutil.ignore_patterns("build", ".dawn", "__pycache__"))
        (tree / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        apply(name, tree)
        # Compiler faults use the ordinary embedded std path, which prunes
        # unrelated modules. A std source fault needs its edited directory.
        embedded = not any(path.startswith("std/") for path, _, _ in MUTATIONS[name])
        jar = work / "compiler.jar"
        _, build_time = run([ROOT / "bin/dawn", "build", tree / "selfhost", "-o", jar], work / "build.log")
        run([*jvm, jar, "--version"], work / "version.log")
        if name == "ignore-subwitness-support":
            # This declaration has no other refusal. Removing the support
            # check must actually admit it, independently of diagnostic text.
            run([*jvm, jar, "check", "--std", tree / "std", PROBE], work / "subwitness.log")
        if name in CASE_OWNERS:
            test_time = 0
            for case, expected, diagnostic in CASE_OWNERS[name]:
                begin = time.monotonic()
                observe(run, [*jvm, jar], case, work / (case + ".log"),
                        expected=expected, diagnostic=diagnostic, std=tree / "std",
                        embedded=embedded)
                test_time += time.monotonic() - begin
        else:
            module = MODULES.get(name, "ir/lower" if name in LOWER_OWNERS else "check/trait_capture_test")
            # The test program imports the mutated implementation. Keep its
            # compilation independent of that implementation's fault; all CLI
            # controls above and below still use the built mutant compiler.
            result, test_time = run([ROOT / "bin/dawn", "test", "--std", tree / "std", tree / "selfhost/src" / (module + ".dawn")], work / "test.log", expected=None)
            marker = "FAIL  " + module + " :: " + OWNERS[name]
            if result.returncode != 1 or marker not in result.stdout:
                raise RuntimeError(f"{name}: owning executed test did not fail:\n{result.stdout[-6000:]}")
            if name == "cell-content-V-only":
                for companion in ["staged_result_phantom", "staged_value_bound_only"]:
                    if "FAIL  check/checker :: " + companion not in result.stdout:
                        raise RuntimeError("the content mutation must fail both cell paths and the unknown-support oracle")
                if "PASS  check/checker :: carried contents preserve ordinary scalars and real resource support" not in result.stdout:
                    raise RuntimeError("the content mutation must retain the ordinary and resource controls")
            if name == "widen-invariant-arguments":
                parameterized = "FAIL  check/trait_capture_test :: parameterized witness checking keeps Capture arguments invariant"
                if parameterized not in result.stdout:
                    raise RuntimeError("the invariant mutation must fail both constant and parameterized witness tests")
        for case in EXTRA_CASES.get(name, []):
            observe(run, [*jvm, jar], case, work / (case + ".log"), expected=0,
                    std=tree / "std", embedded=embedded)
        for case, expected, diagnostic in EXTRA_ASSERTIONS.get(name, []):
            observe(run, [*jvm, jar], case, work / (case + ".log"), expected=expected,
                    diagnostic=diagnostic, std=tree / "std", embedded=embedded)
        shutil.rmtree(tree)
        return dict(name=name, compiler_built=True, owning_test_failed=True,
            build_seconds=build_time, test_seconds=test_time)

    # Each worker owns its source tree, compiler and logs. Publish results in
    # declaration order only after its owning executed test has failed.
    rows = []
    with ThreadPoolExecutor(max_workers=jobs) as workers:
        for row in workers.map(control, names):
            rows.append(row)
            (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(f"PASS mutant {row['name']}: compiler built, owning test red", flush=True)
    # Check the unmutated implementation after proving that the oracles fail.
    run([ROOT / "bin/dawn", "test", ROOT / TEST], out / "baseline.log")
    run([ROOT / "bin/dawn", "test", ROOT / "selfhost/src/check/data_capture_test.dawn"], out / "data-baseline.log")
    run([ROOT / "bin/dawn", "test", ROOT / "selfhost/src/ir/lower.dawn"], out / "lower-baseline.log")
    result, _ = run([ROOT / "bin/dawn", "check", PROBE], out / "subwitness-baseline.log", expected=1)
    if result.stdout.count("error:") != 1 or "impl subwitness support is not covered" not in result.stdout:
        raise RuntimeError("the subwitness probe must isolate exactly one contract refusal")
    cases = set()
    for name in names:
        cases.update(BASELINE_CASES.get(name, []))
        cases.update(case for case, _, _ in CASE_OWNERS.get(name, []))
        cases.update(EXTRA_CASES.get(name, []))
        cases.update(case for case, _, _ in EXTRA_ASSERTIONS.get(name, []))
    original = out / "case-baseline"
    original.mkdir()
    for case in sorted(cases):
        observe(run, [*jvm, ROOT / "build/dawn-selfhost.jar"], case, original / (case + ".log"))
    embedded_cases = set()
    for name in names:
        cases.update(BASELINE_CASES.get(name, []))
        if not any(path.startswith("std/") for path, _, _ in MUTATIONS[name]):
            embedded_cases.update(BASELINE_CASES.get(name, []))
            embedded_cases.update(case for case, _, _ in CASE_OWNERS.get(name, []))
            embedded_cases.update(EXTRA_CASES.get(name, []))
            embedded_cases.update(case for case, _, _ in EXTRA_ASSERTIONS.get(name, []))
    for case in sorted(embedded_cases):
        observe(run, [*jvm, ROOT / "build/dawn-selfhost.jar"], case,
                original / (case + "-embedded.log"), embedded=True)
    print("PASS trait Capture contracts: unmutated tests green", flush=True)


def calls(out, backend=None):
    """Build this tree's native compiler before using its checker and runner."""
    compilers = []
    if backend != "native":
        for action in ("check", "run"):
            result, _ = run([ROOT / "bin/dawn", action, CALLS], out / f"calls-jvm-{action}.log")
            if action == "run" and result.stdout != "trait capture calls\n":
                raise RuntimeError("the JVM call fixture did not execute every assertion")
        java = subprocess.check_output([ROOT / "bin/dawn"], cwd=ROOT,
            env={**os.environ, "DAWN_LAUNCHER_PRINT_JAVA": "1"}, text=True).strip()
        jvm = [java, "-XX:-UsePerfData", "-Xss512m", "-Xmx2g", "-XX:+UseSerialGC", "-jar", ROOT / "build/dawn-selfhost.jar"]
        compilers.append(("jvm", jvm))
    if backend != "jvm":
        units = out / "native-units"
        native = out / "dawnc"
        run([ROOT / "bin/dawn", "__emitc", ROOT / "selfhost/src/nmain.dawn", "--split", units], out / "native-emit.log")
        run([ROOT / "scripts/cc-units.sh", "-o", native, units], out / "native-build.log")
        for action in ("check", "run"):
            result, _ = run([native, action, "--std", ROOT / "std", CALLS], out / f"calls-native-{action}.log")
            if action == "run" and result.stdout != "trait capture calls\n":
                raise RuntimeError("the native call fixture did not execute every assertion")
        entry = Path(subprocess.check_output([
            sys.executable, ROOT / "scripts/native-source-tree.py", out / "native-source"
        ], text=True).strip())
        native_test = entry.parent / Path(TEST).relative_to("selfhost/src")
        run([native, "test", "--std", ROOT / "std", native_test], out / "native-trait-tests.log")
        compilers.append(("native", [native]))
    matrix(run, compilers, out)
    print("PASS trait Capture calls: " + " and ".join(name for name, _ in compilers) + " check and run", flush=True)


def main():
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--only", choices=tuple(MUTATIONS))
    selection.add_argument("--controls-shard", metavar="I/N",
                           help="run one disjoint shard of the mutation controls")
    selection.add_argument("--calls-only", action="store_true",
                           help="run the complete JVM and native source matrix")
    selection.add_argument("--calls-backend", choices=("jvm", "native"),
                           help="run the complete source matrix on one frontend")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if set(OWNERS) != set(MUTATIONS):
        raise RuntimeError("each mutation must have exactly one owning test")
    names = [args.only] if args.only else list(MUTATIONS)
    if args.controls_shard:
        try:
            index, total = map(int, args.controls_shard.split("/"))
            if not 1 <= index <= total <= len(names):
                raise ValueError()
        except ValueError:
            parser.error("--controls-shard must be I/N with 1 <= I <= N <= the mutation count")
        names = names[index - 1::total]
    with tempfile.TemporaryDirectory(prefix="trait-capture-contract-") as temporary:
        out = (args.out or Path(temporary)).resolve()
        out.mkdir(parents=True, exist_ok=True)
        timings = {}
        if not args.calls_only and args.calls_backend is None:
            start = time.monotonic()
            controls(out, names, args.jobs)
            timings["controls_seconds"] = time.monotonic() - start
        if args.only is None and args.controls_shard is None:
            start = time.monotonic()
            calls(out, args.calls_backend)
            timings["calls_seconds"] = time.monotonic() - start
        (out / "timings.json").write_text(json.dumps(timings, indent=2) + "\n")


if __name__ == "__main__":
    main()
