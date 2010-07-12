import py, os
from pypy.tool.udir import udir
from pypy.rlib.jit import JitDriver, OPTIMIZER_FULL, unroll_parameters
from pypy.rlib.jit import PARAMETERS, dont_look_inside
from pypy.jit.metainterp.jitprof import Profiler
from pypy.jit.backend.x86.runner import CPU386
from pypy.jit.backend.test.support import CCompiledMixin
from pypy.jit.codewriter.policy import StopAtXPolicy
from pypy.translator.translator import TranslationContext

class TestTranslationX86(CCompiledMixin):
    CPUClass = CPU386

    def _check_cbuilder(self, cbuilder):
        # We assume here that we have sse2.  If not, the CPUClass
        # needs to be changed to CPU386_NO_SSE2, but well.
        assert '-msse2' in cbuilder.eci.compile_extra
        assert '-mfpmath=sse' in cbuilder.eci.compile_extra

    def test_stuff_translates(self):
        # this is a basic test that tries to hit a number of features and their
        # translation:
        # - jitting of loops and bridges
        # - virtualizables
        # - set_param interface
        # - profiler
        # - full optimizer
        # - floats neg and abs

        class Frame(object):
            _virtualizable2_ = ['i']

            def __init__(self, i):
                self.i = i

        @dont_look_inside
        def myabs(x):
            return abs(x)

        jitdriver = JitDriver(greens = [],
                              reds = ['total', 'frame', 'j'],
                              virtualizables = ['frame'])
        def f(i, j):
            for param in unroll_parameters:
                defl = PARAMETERS[param]
                jitdriver.set_param(param, defl)
            jitdriver.set_param("threshold", 3)
            jitdriver.set_param("trace_eagerness", 2)
            total = 0
            frame = Frame(i)
            while frame.i > 3:
                jitdriver.can_enter_jit(frame=frame, total=total, j=j)
                jitdriver.jit_merge_point(frame=frame, total=total, j=j)
                total += frame.i
                if frame.i >= 20:
                    frame.i -= 2
                frame.i -= 1
                j *= -0.712
                if j + (-j):    raise ValueError
                k = myabs(j)
                if k - abs(j):  raise ValueError
                if k - abs(-j): raise ValueError
            return total * 10
        res = self.meta_interp(f, [40, -49])
        assert res == f(40, -49)

    def test_direct_assembler_call_translates(self):
        class Thing(object):
            def __init__(self, val):
                self.val = val
        
        class Frame(object):
            _virtualizable2_ = ['thing']
        
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'frame'],
                           virtualizables = ['frame'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)
        class SomewhereElse(object):
            pass

        somewhere_else = SomewhereElse()

        def change(newthing):
            somewhere_else.frame.thing = newthing

        def main(codeno):
            frame = Frame()
            somewhere_else.frame = frame
            frame.thing = Thing(0)
            portal(codeno, frame)
            return frame.thing.val

        def portal(codeno, frame):
            i = 0
            while i < 10:
                driver.can_enter_jit(frame=frame, codeno=codeno, i=i)
                driver.jit_merge_point(frame=frame, codeno=codeno, i=i)
                nextval = frame.thing.val
                if codeno == 0:
                    subframe = Frame()
                    subframe.thing = Thing(nextval)
                    nextval = portal(1, subframe)
                elif frame.thing.val > 40:
                    change(Thing(13))
                    nextval = 13
                frame.thing = Thing(nextval + 1)
                i += 1
            return frame.thing.val

        res = self.meta_interp(main, [0], inline=True,
                               policy=StopAtXPolicy(change))
        assert res == main(0)


class TestTranslationRemoveTypePtrX86(CCompiledMixin):
    CPUClass = CPU386

    def _get_TranslationContext(self):
        t = TranslationContext()
        t.config.translation.gc = 'hybrid'
        t.config.translation.gcrootfinder = 'asmgcc'
        t.config.translation.list_comprehension_operations = True
        t.config.translation.gcremovetypeptr = True
        return t

    def test_external_exception_handling_translates(self):
        jitdriver = JitDriver(greens = [], reds = ['n', 'total'])

        class ImDone(Exception):
            def __init__(self, resvalue):
                self.resvalue = resvalue

        @dont_look_inside
        def f(x, total):
            if x <= 3:
                raise ImDone(total * 10)
            if x > 20:
                return 2
            raise ValueError
        @dont_look_inside
        def g(x):
            if x > 15:
                raise ValueError
            return 2
        class Base:
            def meth(self):
                return 2
        class Sub(Base):
            def meth(self):
                return 1
        @dont_look_inside
        def h(x):
            if x < 2000:
                return Sub()
            else:
                return Base()
        def myportal(i):
            jitdriver.set_param("threshold", 3)
            jitdriver.set_param("trace_eagerness", 2)
            total = 0
            n = i
            while True:
                jitdriver.can_enter_jit(n=n, total=total)
                jitdriver.jit_merge_point(n=n, total=total)
                try:
                    total += f(n, total)
                except ValueError:
                    total += 1
                try:
                    total += g(n)
                except ValueError:
                    total -= 1
                n -= h(n).meth()   # this is to force a GUARD_CLASS
        def main(i):
            try:
                myportal(i)
            except ImDone, e:
                return e.resvalue

        # XXX custom fishing, depends on the exact env var and format
        logfile = udir.join('test_ztranslation.log')
        os.environ['PYPYLOG'] = 'jit-log-opt:%s' % (logfile,)
        try:
            res = self.meta_interp(main, [40])
            assert res == main(40)
        finally:
            del os.environ['PYPYLOG']

        guard_class = 0
        for line in open(str(logfile)):
            if 'guard_class' in line:
                guard_class += 1
        # if we get many more guard_classes, it means that we generate
        # guards that always fail
        assert 0 < guard_class <= 4
