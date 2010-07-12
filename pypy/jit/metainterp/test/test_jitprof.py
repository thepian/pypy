
from pypy.jit.metainterp.warmspot import ll_meta_interp
from pypy.rlib.jit import JitDriver, dont_look_inside, purefunction
from pypy.jit.metainterp.test.test_basic import LLJitMixin
from pypy.jit.metainterp import pyjitpl
from pypy.jit.metainterp.jitprof import *

class FakeProfiler(Profiler):
    def start(self):
        self.counter = 123456
        Profiler.start(self)
        self.events = []
        self.times = [0, 0, 0, 0]
    
    def timer(self):
        self.counter += 1
        return self.counter - 1

    def _start(self, event):
        Profiler._start(self, event)
        self.events.append(event)

    def _end(self, event):
        Profiler._end(self, event)
        self.events.append(~event)

    def start_running(self):   self._start(RUNNING)
    def end_running(self):     self._end(RUNNING)

    def start_blackhole(self): self._start(BLACKHOLE)
    def end_blackhole(self):   self._end(BLACKHOLE)

class ProfilerMixin(LLJitMixin):
    def meta_interp(self, *args, **kwds):
        kwds = kwds.copy()
        kwds['ProfilerClass'] = FakeProfiler
        return LLJitMixin.meta_interp(self, *args, **kwds)

class TestProfile(ProfilerMixin):

    def test_simple_loop(self):
        myjitdriver = JitDriver(greens = [], reds = ['x', 'y', 'res'])
        def f(x, y):
            res = 0
            while y > 0:
                myjitdriver.can_enter_jit(x=x, y=y, res=res)
                myjitdriver.jit_merge_point(x=x, y=y, res=res)
                res += x
                y -= 1
            return res * 2
        res = self.meta_interp(f, [6, 7])
        assert res == 84
        profiler = pyjitpl._warmrunnerdesc.metainterp_sd.profiler
        expected = [
            TRACING,
            BACKEND,
            ~ BACKEND,
            ~ TRACING,
            RUNNING,
            ~ RUNNING,
            BLACKHOLE,
            ~ BLACKHOLE
            ]
        assert profiler.events == expected
        assert profiler.times == [2, 1, 1, 1]
        assert profiler.counters == [1, 1, 1, 1, 3, 3, 1, 7, 1, 0, 0, 0,
                                     0, 0, 0, 0]

    def test_simple_loop_with_call(self):
        @dont_look_inside
        def g(n):
            pass
        
        myjitdriver = JitDriver(greens = [], reds = ['x', 'y', 'res'])
        def f(x, y):
            res = 0
            while y > 0:
                myjitdriver.can_enter_jit(x=x, y=y, res=res)
                myjitdriver.jit_merge_point(x=x, y=y, res=res)
                res += x
                g(x)
                y -= 1
            return res * 2
        res = self.meta_interp(f, [6, 7])
        assert res == 84
        profiler = pyjitpl._warmrunnerdesc.metainterp_sd.profiler
        assert profiler.calls == 1

    def test_blackhole_pure(self):
        @purefunction
        def g(n):
            return n+1
        
        myjitdriver = JitDriver(greens = ['z'], reds = ['y', 'x','res'])
        def f(x, y, z):
            res = 0
            while y > 0:
                myjitdriver.can_enter_jit(x=x, y=y, res=res, z=z)
                myjitdriver.jit_merge_point(x=x, y=y, res=res, z=z)
                res += x
                res += g(z)
                y -= 1
            return res * 2
        res = self.meta_interp(f, [6, 7, 2])
        assert res == f(6, 7, 2)
        profiler = pyjitpl._warmrunnerdesc.metainterp_sd.profiler
        assert profiler.calls == 1
