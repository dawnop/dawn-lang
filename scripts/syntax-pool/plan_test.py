#!/usr/bin/env python3
"""Fixed plans, receipts and workers; never build a compiler."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('syntax_plan',HERE/'plan.py')
plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
checks=0

def check(value,label):
    global checks
    if not value:raise AssertionError(label)
    checks+=1

def rejects(call,label):
    try:call()
    except (ValueError,OSError,KeyError,TypeError):check(True,label)
    else:raise AssertionError('accepted '+label)

clean_env=dict(os.environ)
clean_env.pop('MUTANT_COVERAGE_DIR',None)

with tempfile.TemporaryDirectory(prefix='syntax-pool-fixtures-') as temp:
    fixture_tree=Path(temp);helpers=fixture_tree/'scripts/syntax-pool';helpers.mkdir(parents=True)
    for name in ('plan.py','pool.sh','phase.sh','run.sh','plan.tsv','drop-opaque-anchor.reds','drop-rbracket-return-boundary.reds'):
        shutil.copy(HERE/name,helpers/name)
    entries=[f for s in (helpers/'plan.tsv').read_text().splitlines() if len(f:=s.split('\t'))==4 and f[0] in plan.HARNESSES]
    for h in plan.HARNESSES:
        here=fixture_tree/('scripts/'+h);here.mkdir();names=[n for kind,n,_,_ in entries if kind==h]
        (here/'matrix.txt').write_text('\n'.join(names)+'\n')
        (here/'mutate.py').write_text('# fixed producer fixture\n')
    (fixture_tree/'selfhost').mkdir();(fixture_tree/'selfhost/fixture.dawn').write_text('fn fixture() -> Int = 1\n')
    (fixture_tree/'scripts/spike-native').mkdir();golden=fixture_tree/'scripts/spike-native/iter_for.expect';golden.write_text('value=1\n')
    subprocess.run(['git','init','-q','-b','main'],cwd=fixture_tree,check=True)
    subprocess.run(['git','add','.'],cwd=fixture_tree,check=True)
    subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Add fixed inputs'],cwd=fixture_tree,check=True)
    # These exact failure sets come from complete successful baseline test runs.
    # An extra or repeated failure must fail even when the old owner still fails.
    for mutant in ('drop-opaque-anchor','drop-rbracket-return-boundary'):
        expected=(helpers/(mutant+'.reds')).read_text();rows=expected.splitlines()
        for label,actual,success in (
            ('complete',expected,True),
            ('missing','\n'.join(rows[:-1])+'\n',False),
            ('extra',expected+'FAIL  unrelated additional test\n',False),
            ('duplicate',expected+rows[0]+'\n',False),
            ('wrong','FAIL  wrong owning test\n',False),
        ):
            mdir=fixture_tree/'red-fixture';mdir.mkdir(exist_ok=True);(mdir/'test.out').write_text('PASS  fixed success\n'+actual)
            script='set -euo pipefail; root=$1; mdir=$2; source "$root/scripts/syntax-pool/phase.sh"; syntax_phase=case; syntax_case_name=$3; syntax_phase_end syntax-small-contract; echo VERIFIED'
            r=subprocess.run(['bash','-c',script,'fixture',str(fixture_tree),str(mdir),mutant],env=clean_env,capture_output=True,text=True,timeout=10)
            check((r.returncode==0)==success,mutant+' '+label+' full red set')
            check(('VERIFIED' in r.stdout)==success,mutant+' '+label+' cannot hide failure')
    original=(helpers/'plan.tsv').read_text();lines=original.splitlines()
    check(len(plan.load(fixture_tree))==47,'all complete cases')
    products=('drop-opaque-anchor','drop-rbracket-return-boundary')
    # Keep every matrix item, harness shard and worker lane present, and give
    # each full product its own lane. Only job isolation is wrong here.
    co_located=[]
    ordinary_lanes=[(1,2),(1,3)]+[(j,l) for j in (2,3,4) for l in range(4)]
    small_index=0
    for h,name,shard,lane in entries:
        if name in products:
            destination=(1,products.index(name))
        elif h=='syntax-small-contract':
            destination=((2,0),(3,0),(4,0))[small_index]
            small_index+=1
        else:
            position=sum(row[0]==h for row in co_located)
            destination=ordinary_lanes[position % len(ordinary_lanes)]
        co_located.append((h,name,str(destination[0]),str(destination[1])))
    co_located_text='\n'.join(lines[:2]+['\t'.join(row) for row in co_located])+'\n'
    # This mutation changes only lane isolation; the donor lane stays nonempty.
    product=next(row for row in entries if row[1]==products[0])
    donor=next(row for row in entries if row[2]==product[2] and row[3]!=product[3]
               and sum(other[2:]==row[2:] for other in entries)>1)
    shared_lane_text=original.replace('\t'.join(donor)+'\n',
                                      '\t'.join(donor[:3]+[product[3]])+'\n',1)
    for label,edited in (
        ('missing case','\n'.join(lines[:-1])+'\n'),
        ('duplicate case',original+lines[-1]+'\n'),
        ('wrong shard',original.replace('\t1\t0\n','\t5\t0\n',1)),
        ('wrong lane',original.replace('\t1\t0\n','\t1\t4\n',1)),
        ('wrong workers',original.replace('workers\t4','workers\t5',1)),
        ('unknown harness',original.replace('syntax-small-contract\t','unknown-contract\t',1)),
        ('empty piece','\n'.join('\t'.join(f[:2]+['1',f[3]]) if len(f:=s.split('\t'))==4 and f[0] in plan.HARNESSES else s for s in lines)+'\n'),
        ('shared full-test fixtures',co_located_text),
        ('shared full-test lane',shared_lane_text),
        ('empty lane','\n'.join('\t'.join(f[:3]+['0']) if len(f:=s.split('\t'))==4 and f[0] in plan.HARNESSES else s for s in lines)+'\n'),
    ):
        (helpers/'plan.tsv').write_text(edited);rejects(lambda:plan.load(fixture_tree),label)
    (helpers/'plan.tsv').write_text(original)
    coverage=fixture_tree/'coverage';coverage.mkdir();receipts={}
    for shard in (1,2,3,4):
        value,_=plan.expected_receipt(fixture_tree,shard);path=coverage/f'syntax-pool-{shard}.json';path.write_text(json.dumps(value));receipts[path]=value
    plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES);check(True,'complete global receipts')
    target=next(iter(receipts));good=receipts[target]
    for label,edit in (
        ('wrong schema',lambda d:d.update(schema=1)),
        ('wrong input',lambda d:d.update(input='0'*40)),
        ('wrong producer',lambda d:d.update(producers='0'*64)),
        ('wrong plan',lambda d:d.update(plan='0'*64)),
        ('wrong piece',lambda d:d.update(shard=5)),
        ('boolean piece',lambda d:d.update(shard=True)),
        ('floating piece',lambda d:d.update(shard=1.0)),
        ('wrong worker bound',lambda d:d.update(workers=5)),
        ('missing public',lambda d:d['public'].pop()),
        ('duplicate public',lambda d:d['public'].append(d['public'][0])),
        ('missing completion',lambda d:d['completed'].pop()),
        ('duplicate completion',lambda d:d['completed'].append(d['completed'][0])),
        ('unknown completion',lambda d:d['completed'].append('unknown')),
    ):
        altered=copy.deepcopy(good);edit(altered);target.write_text(json.dumps(altered))
        rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),label)
    private=coverage/'syntax-pool-4.json';private_good=receipts[private]
    check(private_good['public']==[],'private piece does not claim public execution')
    altered=copy.deepcopy(private_good);altered['public']=list(plan.HARNESSES);private.write_text(json.dumps(altered))
    rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),'wrong public role')
    private.write_text(json.dumps(private_good))
    target.write_text(json.dumps(good));target.unlink();rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),'missing piece')
    target.write_text(json.dumps(good));extra=coverage/'syntax-pool-extra.json';extra.write_text(json.dumps(good));rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),'duplicate piece');extra.unlink()
    for path in (golden,fixture_tree/'scripts/pattern-or-contract/mutate.py'):
        saved=path.read_bytes();path.write_bytes(saved+b'# changed\n');rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),'changed golden or producer');path.write_bytes(saved)
    producer=fixture_tree/'scripts/pattern-or-contract/mutate.py';mode=producer.stat().st_mode
    producer.chmod(mode ^ 0o111);rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),'changed producer execute mode');producer.chmod(mode)
    saved=golden.read_bytes();mode=golden.stat().st_mode;link_target=fixture_tree/'golden-target';link_target.write_bytes(saved)
    golden.unlink();golden.symlink_to(link_target)
    rejects(lambda:plan.verify_coverage(fixture_tree,coverage,plan.HARNESSES),'same-byte symlink golden')
    golden.unlink();golden.write_bytes(saved);golden.chmod(mode)
    unexpected=fixture_tree/'selfhost/untracked.dawn';unexpected.write_text('fn unexpected() -> Int = 1\n')
    rejects(lambda:plan.identity(fixture_tree),'untracked compiler input');unexpected.unlink()
    staged=fixture_tree/'selfhost/fixture.dawn';saved=staged.read_bytes();staged.write_bytes(saved+b'# staged\n')
    subprocess.run(['git','add','selfhost/fixture.dawn'],cwd=fixture_tree,check=True)
    rejects(lambda:plan.identity(fixture_tree),'staged compiler input')
    staged.write_bytes(saved);subprocess.run(['git','add','selfhost/fixture.dawn'],cwd=fixture_tree,check=True)
    shell=r'''set -euo pipefail
root=$1
scenario=$2
work=$(mktemp -d "$root/worker.XXXXXX")
source "$root/scripts/syntax-pool/pool.sh"
shard_index=1
shard_total=4
shard_plan=
shard_begin() { shard_harness=$1; shard_ran=0; }
shard_record() { shard_ran=$((shard_ran+1)); printf 'RECORDED %s/%s\n' "$shard_harness" "$1"; }
cleanup() {
  status=$?
  syntax_pool_cleanup "$status" || status=$?
  printf 'CLEANUP status=%s remaining=%s\n' "$status" "${#syntax_pool_pids[@]}"
  exit "$status"
}
trap cleanup EXIT
plan_id=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$root/scripts/syntax-pool/plan.tsv")
syntax_pool_prepare "$work" "$plan_id"
printf '%s\n' syntax-small-contract pattern-or-contract for-pattern-contract > "$syntax_pool_dir/public"
callback() {
  if [ "$scenario" = failure ]; then false; fi
  printf 'finished %s/%s\n' "$1" "$2"
}
if [ "$scenario" = missing ]; then
  for lane in 0 1 2 3; do : > "$syntax_pool_dir/queue-$lane"; done
fi
if [ "$scenario" = duplicate ]; then head -1 "$syntax_pool_dir/queue-0" >> "$syntax_pool_dir/queue-0"; fi
if [ "$scenario" = no-public ]; then : > "$syntax_pool_dir/public"; fi
syntax_pool_run callback
printf 'VERDICT complete\n'
'''
    for scenario,success in [('success',True),('failure',False),('missing',False),('duplicate',False),('no-public',False)]:
        r=subprocess.run(['bash','-c',shell,'fixture',str(fixture_tree),scenario],env=clean_env,capture_output=True,text=True,timeout=10)
        check((r.returncode==0)==success,scenario+' exit');check(('VERDICT complete' in r.stdout)==success,scenario+' verdict');check('remaining=0' in r.stdout,scenario+' reaped')
        if scenario=='failure':check('RECORDED ' not in r.stdout,'failed plain callback cannot complete')
    helper=helpers/'pool.sh';saved=helper.read_text()
    for label,injection,status in [('registration signal','    kill -TERM "$BASHPID"\n    syntax_pool_pids+=("$!")',143),('registration HUP','    kill -HUP "$BASHPID"\n    syntax_pool_pids+=("$!")',129),('registration INT','    kill -INT "$BASHPID"\n    syntax_pool_pids+=("$!")',130),('foreground failure','    syntax_pool_pids+=("$!")\n    exit 7',7)]:
        helper.write_text(saved.replace('    syntax_pool_pids+=("$!")',injection,1))
        subprocess.run(['git','add','scripts/syntax-pool/pool.sh'],cwd=fixture_tree,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Instrument fixed signal boundary'],cwd=fixture_tree,check=True)
        r=subprocess.run(['bash','-c',shell,'fixture',str(fixture_tree),label],env=clean_env,capture_output=True,text=True,timeout=10)
        check(r.returncode==status,label+' status');check('remaining=0' in r.stdout and 'VERDICT complete' not in r.stdout,label+' waits before cleanup');check('RECORDED ' not in r.stdout,label+' no complete result')
        helper.write_text(saved)
        subprocess.run(['git','add','scripts/syntax-pool/pool.sh'],cwd=fixture_tree,check=True)
        subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Restore fixed signal boundary'],cwd=fixture_tree,check=True)
    # Exercise the required dispatcher itself with fixed public/case scripts.
    shared=fixture_tree/'scripts/mutant-coverage';shared.mkdir()
    shutil.copyfile(HERE.parent/'mutant-coverage/shard.sh',shared/'shard.sh')
    mock=r'''#!/usr/bin/env bash
set -euo pipefail
harness=$(basename "$(dirname "$0")")
expected_root=$(cd "$(dirname "$0")/../.." && pwd)
[ "$PWD" = "$expected_root" ] || exit 9
case "$1" in
  --fixtures-only)
    [ "${FIXTURE_FAIL_PUBLIC:-}" != "$harness" ] || exit 8
    echo "PUBLIC $harness"
    ;;
  --case-only)
    echo "PRIVATE $harness/$2"
    ;;
  *) exit 2 ;;
esac
'''
    for h in plan.HARNESSES:
        path=fixture_tree/('scripts/'+h)/'run.sh';path.write_text(mock);path.chmod(0o755)
    subprocess.run(['git','add','.'],cwd=fixture_tree,check=True)
    subprocess.run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Add fixed dispatcher'],cwd=fixture_tree,check=True)
    dispatched=fixture_tree/'dispatched'
    plan_id=hashlib.sha256((helpers/'plan.tsv').read_bytes()).hexdigest()
    for shard in (1,2,3,4):
        env=dict(clean_env,MUTANT_COVERAGE_DIR=str(dispatched))
        r=subprocess.run(['bash',str(helpers/'run.sh'),'--shard',f'{shard}/4','--plan-id',plan_id],env=env,capture_output=True,text=True,timeout=10)
        check(r.returncode==0,'complete dispatcher piece')
        check(r.stdout.count('PUBLIC ')==(3 if shard in plan.PUBLIC_SHARDS else 0),'declared public phases once')
        check('PASS  complete syntax piece' in r.stdout,'complete dispatcher verdict')
        check(r.stdout.count(f'(piece {shard}/4)')==3,'correct completed-piece summaries')
    plan.verify_coverage(fixture_tree,dispatched,plan.HARNESSES);check(True,'actual dispatcher receipts complete')
    cases=[]
    for path in dispatched.glob('*.coverage'):
        cases.extend(s[4:] for s in path.read_text().splitlines() if s.startswith('ran='))
    check(len(cases)==47 and len(set(cases))==47,'actual generic coverage has no missing or repeated case')
    for args in ([],['--shard','1/4'],['--shard','5/4'],['--shard','1/4','--only','case'],['--shard','1/4','--plan-id','0'*64],['--shard','1/4','--plan-id']):
        r=subprocess.run(['bash',str(helpers/'run.sh'),*args],env=clean_env,capture_output=True,text=True,timeout=10)
        check(r.returncode==2,'dispatcher refuses incomplete mode or wrong index')
    r=subprocess.run(['bash',str(helpers/'run.sh'),'--shard','1/4','--plan-id',plan_id],env=dict(clean_env,FIXTURE_FAIL_PUBLIC='pattern-or-contract'),capture_output=True,text=True,timeout=10)
    check(r.returncode==8 and 'BEGIN syntax case ' not in r.stdout,'public failure prevents private work and verdict')
print(f'PASS: {checks} fixed syntax plan, receipt and worker checks')
