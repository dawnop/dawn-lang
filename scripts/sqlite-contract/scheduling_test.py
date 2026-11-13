import concurrent.futures
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import run as contract

class CompilerLogOwnership(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.common=self.root/'common.jsonl';self.common.write_text('parent log remains\n')
        self.env={'F3_CC_LOG':str(self.common)}
    def row(self,env):
        return ['-c',str(self.root/'sqlite_stub.c')]+(['-DDAWN_RT_INLINE_RC']if env['DAWN_NO_INLINE_RC']==''else [])
    def compile(self,args,*,env):
        Path(env['F3_CC_LOG']).write_text(json.dumps(self.row(env))+'\n')
    def test_one_build_keeps_its_parent_log(self):
        with patch.object(contract,'run',side_effect=self.compile):
            actual=contract.build('driver',self.root,self.root/'program',self.env,sanitized=True)
        self.assertEqual(self.common.read_text(),'parent log remains\n')
        self.assertNotEqual(actual['F3_CC_LOG'],self.env['F3_CC_LOG'])
    def test_two_overlapping_builds_keep_exact_own_stub_flags(self):
        entered=threading.Barrier(2);written=threading.Barrier(2)
        def compile(args,*,env):
            entered.wait(timeout=5)
            with Path(env['F3_CC_LOG']).open('a')as f:f.write(json.dumps(self.row(env))+'\n')
            written.wait(timeout=5)
        def one(inline):
            return contract.build('driver',self.root,self.root/('inline'if inline else'plain'),self.env,inline=inline,sanitized=True)
        with patch.object(contract,'run',side_effect=compile),concurrent.futures.ThreadPoolExecutor(max_workers=2)as pool:
            results=list(pool.map(one,[False,True]))
        self.assertEqual(len({r['F3_CC_LOG']for r in results}),2)
        self.assertEqual(self.common.read_text(),'parent log remains\n')
    def refusal(self,rows,inline=False):
        def compile(args,*,env):Path(env['F3_CC_LOG']).write_text(''.join(json.dumps(row)+'\n'for row in rows))
        with patch.object(contract,'run',side_effect=compile),self.assertRaises(AssertionError):
            contract.build('driver',self.root,self.root/'refusal',self.env,inline=inline)
    def test_missing_stub_is_refused(self):self.refusal([])
    def test_repeated_stub_is_refused(self):
        row=['-c','sqlite_stub.c'];self.refusal([row,row])
    def test_wrong_inline_flag_is_refused(self):self.refusal([['-c','sqlite_stub.c','-DDAWN_RT_INLINE_RC']])

class OrderedPrivateCases(unittest.TestCase):
    def test_two_workers_are_bounded_complete_and_ordered(self):
        lock=threading.Lock();entered=threading.Barrier(2);active=0;maximum=0;seen=[]
        def worker(item):
            nonlocal active,maximum
            with lock:active+=1;maximum=max(maximum,active);seen.append(item)
            try:
                if item<2:entered.wait(timeout=5)
                if item==0:
                    import time
                    time.sleep(.01)
                return item
            finally:
                with lock:active-=1
        self.assertEqual(list(contract.ordered_cases(range(8),2,worker)),list(range(8)))
        self.assertEqual(sorted(seen),list(range(8)));self.assertEqual(maximum,2)
    def test_default_one_worker_preserves_the_serial_dispatch(self):
        seen=[]
        def worker(item):seen.append(item);return item
        with patch.object(contract,'ThreadPoolExecutor',side_effect=AssertionError('serial path created workers')):
            self.assertEqual(list(contract.ordered_cases(range(5),1,worker)),list(range(5)))
        self.assertEqual(seen,list(range(5)))
    def test_failed_private_case_stops_further_submissions(self):
        entered=threading.Barrier(2);seen=[]
        def worker(item):
            seen.append(item)
            if item<2:entered.wait(timeout=5)
            if item==0:raise AssertionError('owning oracle failed')
            return item
        with self.assertRaisesRegex(AssertionError,'owning oracle failed'):
            list(contract.ordered_cases(range(8),2,worker))
        self.assertEqual(set(seen),{0,1})
    def test_invalid_worker_counts_are_refused(self):
        for jobs in (0,3):
            with self.subTest(jobs=jobs),self.assertRaises(ValueError):list(contract.ordered_cases([1],jobs,lambda x:x))
    def test_invalid_cli_stops_before_any_compiler(self):
        import contextlib,io,sys
        for args in (['--native-jobs','0'],['--native','--backends']):
            with self.subTest(args=args),patch.object(sys,'argv',['runner',*args]),patch.object(contract,'run')as child,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):contract.main()
                child.assert_not_called()

if __name__=='__main__':unittest.main()
