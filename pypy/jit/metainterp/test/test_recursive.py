import py
from pypy.rlib.jit import JitDriver, we_are_jitted, OPTIMIZER_SIMPLE, hint
from pypy.rlib.jit import unroll_safe, dont_look_inside
from pypy.rlib.objectmodel import we_are_translated
from pypy.jit.metainterp.test.test_basic import LLJitMixin, OOJitMixin
from pypy.jit.codewriter.policy import StopAtXPolicy
from pypy.rpython.annlowlevel import hlstr
from pypy.jit.metainterp.warmspot import CannotInlineCanEnterJit, get_stats

class RecursiveTests:

    def test_simple_recursion(self):
        myjitdriver = JitDriver(greens=[], reds=['n', 'm'])
        def f(n):
            m = n - 2
            while True:
                myjitdriver.jit_merge_point(n=n, m=m)
                n -= 1
                if m == n:
                    return main(n) * 2
                myjitdriver.can_enter_jit(n=n, m=m)
        def main(n):
            if n > 0:
                return f(n+1)
            else:
                return 1
        res = self.meta_interp(main, [20], optimizer=OPTIMIZER_SIMPLE)
        assert res == main(20)
        self.check_history(call=0)

    def test_simple_recursion_with_exc(self):
        myjitdriver = JitDriver(greens=[], reds=['n', 'm'])
        class Error(Exception):
            pass
        
        def f(n):
            m = n - 2
            while True:
                myjitdriver.jit_merge_point(n=n, m=m)
                n -= 1
                if n == 10:
                    raise Error
                if m == n:
                    try:
                        return main(n) * 2
                    except Error:
                        return 2
                myjitdriver.can_enter_jit(n=n, m=m)
        def main(n):
            if n > 0:
                return f(n+1)
            else:
                return 1
        res = self.meta_interp(main, [20], optimizer=OPTIMIZER_SIMPLE)
        assert res == main(20)

    def test_recursion_three_times(self):
        myjitdriver = JitDriver(greens=[], reds=['n', 'm', 'total'])
        def f(n):
            m = n - 3
            total = 0
            while True:
                myjitdriver.jit_merge_point(n=n, m=m, total=total)
                n -= 1
                total += main(n)
                if m == n:
                    return total + 5
                myjitdriver.can_enter_jit(n=n, m=m, total=total)
        def main(n):
            if n > 0:
                return f(n)
            else:
                return 1
        print
        for i in range(1, 11):
            print '%3d %9d' % (i, f(i))
        res = self.meta_interp(main, [10], optimizer=OPTIMIZER_SIMPLE)
        assert res == main(10)
        self.check_enter_count_at_most(11)

    def test_bug_1(self):
        myjitdriver = JitDriver(greens=[], reds=['n', 'i', 'stack'])
        def opaque(n, i):
            if n == 1 and i == 19:
                for j in range(20):
                    res = f(0)      # recurse repeatedly, 20 times
                    assert res == 0
        def f(n):
            stack = [n]
            i = 0
            while i < 20:
                myjitdriver.can_enter_jit(n=n, i=i, stack=stack)
                myjitdriver.jit_merge_point(n=n, i=i, stack=stack)
                opaque(n, i)
                i += 1
            return stack.pop()
        res = self.meta_interp(f, [1], optimizer=OPTIMIZER_SIMPLE, repeat=2,
                               policy=StopAtXPolicy(opaque))
        assert res == 1

    def get_interpreter(self, codes, always_inline=False):
        ADD = "0"
        JUMP_BACK = "1"
        CALL = "2"
        EXIT = "3"

        if always_inline:
            def can_inline(*args):
                return True
        else:
            def can_inline(i, code):
                code = hlstr(code)
                return not JUMP_BACK in code

        jitdriver = JitDriver(greens = ['i', 'code'], reds = ['n'],
                              can_inline = can_inline)
 
        def interpret(codenum, n, i):
            code = codes[codenum]
            while i < len(code):
                jitdriver.jit_merge_point(n=n, i=i, code=code)
                op = code[i]
                if op == ADD:
                    n += 1
                    i += 1
                elif op == CALL:
                    n = interpret(1, n, 1)
                    i += 1
                elif op == JUMP_BACK:
                    if n > 20:
                        return 42
                    i -= 2
                    jitdriver.can_enter_jit(n=n, i=i, code=code)
                elif op == EXIT:
                    return n
                else:
                    raise NotImplementedError
            return n

        return interpret

    def test_inline(self):
        code = "021"
        subcode = "00"

        codes = [code, subcode]
        f = self.get_interpreter(codes)

        assert self.meta_interp(f, [0, 0, 0], optimizer=OPTIMIZER_SIMPLE) == 42
        self.check_loops(int_add = 1, call_may_force = 1, call = 0)
        assert self.meta_interp(f, [0, 0, 0], optimizer=OPTIMIZER_SIMPLE,
                                inline=True) == 42
        self.check_loops(int_add = 2, call_may_force = 0, call = 0,
                         guard_no_exception = 0)

    def test_inline_jitdriver_check(self):
        code = "021"
        subcode = "100"
        codes = [code, subcode]

        f = self.get_interpreter(codes)

        assert self.meta_interp(f, [0, 0, 0], optimizer=OPTIMIZER_SIMPLE,
                                inline=True) == 42
        self.check_loops(call_may_force = 1, call = 0)

    def test_inline_faulty_can_inline(self):
        code = "021"
        subcode = "301"
        codes = [code, subcode]

        f = self.get_interpreter(codes, always_inline=True)

        try:
            self.meta_interp(f, [0, 0, 0], optimizer=OPTIMIZER_SIMPLE,
                             inline=True)
        except CannotInlineCanEnterJit:
            pass
        else:
            py.test.fail("DID NOT RAISE")

    def test_guard_failure_in_inlined_function(self):
        def p(pc, code):
            code = hlstr(code)
            return "%s %d %s" % (code, pc, code[pc])
        def c(pc, code):
            return "l" not in hlstr(code)
        myjitdriver = JitDriver(greens=['pc', 'code'], reds=['n'],
                                get_printable_location=p, can_inline=c)
        def f(code, n):
            pc = 0
            while pc < len(code):

                myjitdriver.jit_merge_point(n=n, code=code, pc=pc)
                op = code[pc]
                if op == "-":
                    n -= 1
                elif op == "c":
                    n = f("---i---", n)
                elif op == "i":
                    if n % 5 == 1:
                        return n
                elif op == "l":
                    if n > 0:
                        myjitdriver.can_enter_jit(n=n, code=code, pc=0)
                        pc = 0
                        continue
                else:
                    assert 0
                pc += 1
            return n
        def main(n):
            return f("c-l", n)
        print main(100)
        res = self.meta_interp(main, [100], optimizer=OPTIMIZER_SIMPLE, inline=True)
        assert res == 0

    def test_guard_failure_and_then_exception_in_inlined_function(self):
        def p(pc, code):
            code = hlstr(code)
            return "%s %d %s" % (code, pc, code[pc])
        def c(pc, code):
            return "l" not in hlstr(code)
        myjitdriver = JitDriver(greens=['pc', 'code'], reds=['n', 'flag'],
                                get_printable_location=p, can_inline=c)
        def f(code, n):
            pc = 0
            flag = False
            while pc < len(code):

                myjitdriver.jit_merge_point(n=n, code=code, pc=pc, flag=flag)
                op = code[pc]
                if op == "-":
                    n -= 1
                elif op == "c":
                    try:
                        n = f("---ir---", n)
                    except Exception:
                        return n
                elif op == "i":
                    if n < 200:
                        flag = True
                elif op == "r":
                    if flag:
                        raise Exception
                elif op == "l":
                    if n > 0:
                        myjitdriver.can_enter_jit(n=n, code=code, pc=0, flag=flag)
                        pc = 0
                        continue
                else:
                    assert 0
                pc += 1
            return n
        def main(n):
            return f("c-l", n)
        print main(1000)
        res = self.meta_interp(main, [1000], optimizer=OPTIMIZER_SIMPLE, inline=True)
        assert res == main(1000)

    def test_exception_in_inlined_function(self):
        def p(pc, code):
            code = hlstr(code)
            return "%s %d %s" % (code, pc, code[pc])
        def c(pc, code):
            return "l" not in hlstr(code)
        myjitdriver = JitDriver(greens=['pc', 'code'], reds=['n'],
                                get_printable_location=p, can_inline=c)

        class Exc(Exception):
            pass
        
        def f(code, n):
            pc = 0
            while pc < len(code):

                myjitdriver.jit_merge_point(n=n, code=code, pc=pc)
                op = code[pc]
                if op == "-":
                    n -= 1
                elif op == "c":
                    try:
                        n = f("---i---", n)
                    except Exc:
                        pass
                elif op == "i":
                    if n % 5 == 1:
                        raise Exc
                elif op == "l":
                    if n > 0:
                        myjitdriver.can_enter_jit(n=n, code=code, pc=0)
                        pc = 0
                        continue
                else:
                    assert 0
                pc += 1
            return n
        def main(n):
            return f("c-l", n)
        res = self.meta_interp(main, [100], optimizer=OPTIMIZER_SIMPLE, inline=True)
        assert res == main(100)

    def test_recurse_during_blackholing(self):
        # this passes, if the blackholing shortcut for calls is turned off
        # it fails, it is very delicate in terms of parameters,
        # bridge/loop creation order
        def p(pc, code):
            code = hlstr(code)
            return "%s %d %s" % (code, pc, code[pc])
        def c(pc, code):
            return "l" not in hlstr(code)
        myjitdriver = JitDriver(greens=['pc', 'code'], reds=['n'],
                                get_printable_location=p, can_inline=c)
        
        def f(code, n):
            pc = 0
            while pc < len(code):

                myjitdriver.jit_merge_point(n=n, code=code, pc=pc)
                op = code[pc]
                if op == "-":
                    n -= 1
                elif op == "c":
                    if n < 70 and n % 3 == 1:
                        n = f("--", n)
                elif op == "l":
                    if n > 0:
                        myjitdriver.can_enter_jit(n=n, code=code, pc=0)
                        pc = 0
                        continue
                else:
                    assert 0
                pc += 1
            return n
        def main(n):
            myjitdriver.set_param('threshold', 3)
            myjitdriver.set_param('trace_eagerness', 5)            
            return f("c-l", n)
        expected = main(100)
        res = self.meta_interp(main, [100], optimizer=OPTIMIZER_SIMPLE, inline=True)
        assert res == expected

    def check_max_trace_length(self, length):
        for loop in get_stats().loops:
            assert len(loop.operations) <= length + 5 # because we only check once per metainterp bytecode
            for op in loop.operations:
                if op.is_guard() and hasattr(op.descr, '_debug_suboperations'):
                    assert len(op.descr._debug_suboperations) <= length + 5

    def test_inline_trace_limit(self):
        myjitdriver = JitDriver(greens=[], reds=['n'])
        def recursive(n):
            if n > 0:
                return recursive(n - 1) + 1
            return 0
        def loop(n):            
            myjitdriver.set_param("threshold", 10)
            pc = 0
            while n:
                myjitdriver.can_enter_jit(n=n)
                myjitdriver.jit_merge_point(n=n)
                n = recursive(n)
                n -= 1
            return n
        TRACE_LIMIT = 66
        res = self.meta_interp(loop, [100], optimizer=OPTIMIZER_SIMPLE, inline=True, trace_limit=TRACE_LIMIT)
        assert res == 0
        self.check_max_trace_length(TRACE_LIMIT)
        self.check_enter_count_at_most(10) # maybe
        self.check_aborted_count(7)

    def test_trace_limit_bridge(self):
        def recursive(n):
            if n > 0:
                return recursive(n - 1) + 1
            return 0
        myjitdriver = JitDriver(greens=[], reds=['n'])
        def loop(n):
            myjitdriver.set_param("threshold", 4)
            myjitdriver.set_param("trace_eagerness", 2)
            while n:
                myjitdriver.can_enter_jit(n=n)
                myjitdriver.jit_merge_point(n=n)
                if n % 5 == 0:
                    n -= 1
                if n < 50:
                    n = recursive(n)
                n -= 1
            return n
        TRACE_LIMIT = 20
        res = self.meta_interp(loop, [100], optimizer=OPTIMIZER_SIMPLE, inline=True, trace_limit=TRACE_LIMIT)
        self.check_max_trace_length(TRACE_LIMIT)
        self.check_aborted_count(8)
        self.check_enter_count_at_most(30)

    def test_trace_limit_with_exception_bug(self):
        myjitdriver = JitDriver(greens=[], reds=['n'])
        @unroll_safe
        def do_stuff(n):
            while n > 0:
                n -= 1
            raise ValueError
        def loop(n):
            pc = 0
            while n > 80:
                myjitdriver.can_enter_jit(n=n)
                myjitdriver.jit_merge_point(n=n)
                try:
                    do_stuff(n)
                except ValueError:
                    # the trace limit is checked when we arrive here, and we
                    # have the exception still in last_exc_value_box at this
                    # point -- so when we abort because of a trace too long,
                    # the exception is passed to the blackhole interp and
                    # incorrectly re-raised from here
                    pass
                n -= 1
            return n
        TRACE_LIMIT = 66
        res = self.meta_interp(loop, [100], trace_limit=TRACE_LIMIT)
        assert res == 80

    def test_max_failure_args(self):
        FAILARGS_LIMIT = 10
        jitdriver = JitDriver(greens = [], reds = ['i', 'n', 'o'])

        class A(object):
            def __init__(self, i0, i1, i2, i3, i4, i5, i6, i7, i8, i9):
                self.i0 = i0
                self.i1 = i1
                self.i2 = i2
                self.i3 = i3
                self.i4 = i4
                self.i5 = i5
                self.i6 = i6
                self.i7 = i7
                self.i8 = i8
                self.i9 = i9
                
        
        def loop(n):
            i = 0
            o = A(0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
            while i < n:
                jitdriver.can_enter_jit(o=o, i=i, n=n)
                jitdriver.jit_merge_point(o=o, i=i, n=n)
                o = A(i, i + 1, i + 2, i + 3, i + 4, i + 5,
                      i + 6, i + 7, i + 8, i + 9)
                i += 1
            return o

        res = self.meta_interp(loop, [20], failargs_limit=FAILARGS_LIMIT,
                               listops=True)
        self.check_aborted_count(5)

    def test_max_failure_args_exc(self):
        FAILARGS_LIMIT = 10
        jitdriver = JitDriver(greens = [], reds = ['i', 'n', 'o'])

        class A(object):
            def __init__(self, i0, i1, i2, i3, i4, i5, i6, i7, i8, i9):
                self.i0 = i0
                self.i1 = i1
                self.i2 = i2
                self.i3 = i3
                self.i4 = i4
                self.i5 = i5
                self.i6 = i6
                self.i7 = i7
                self.i8 = i8
                self.i9 = i9
                
        
        def loop(n):
            i = 0
            o = A(0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
            while i < n:
                jitdriver.can_enter_jit(o=o, i=i, n=n)
                jitdriver.jit_merge_point(o=o, i=i, n=n)
                o = A(i, i + 1, i + 2, i + 3, i + 4, i + 5,
                      i + 6, i + 7, i + 8, i + 9)
                i += 1
            raise ValueError

        def main(n):
            try:
                loop(n)
                return 1
            except ValueError:
                return 0

        res = self.meta_interp(main, [20], failargs_limit=FAILARGS_LIMIT,
                               listops=True)
        assert not res
        self.check_aborted_count(5)        

    def test_set_param_inlining(self):
        myjitdriver = JitDriver(greens=[], reds=['n', 'recurse'])
        def loop(n, recurse=False):
            while n:
                myjitdriver.jit_merge_point(n=n, recurse=recurse)
                n -= 1
                if not recurse:
                    loop(10, True)
                    myjitdriver.can_enter_jit(n=n, recurse=recurse)
            return n
        TRACE_LIMIT = 66
 
        def main(inline):
            myjitdriver.set_param("threshold", 10)
            if inline:
                myjitdriver.set_param('inlining', True)
            else:
                myjitdriver.set_param('inlining', False)
            return loop(100)

        res = self.meta_interp(main, [0], optimizer=OPTIMIZER_SIMPLE, trace_limit=TRACE_LIMIT)
        self.check_loops(call_may_force=1, call=0)

        res = self.meta_interp(main, [1], optimizer=OPTIMIZER_SIMPLE, trace_limit=TRACE_LIMIT)
        self.check_loops(call_may_force=0, call=0)

    def test_trace_from_start(self):
        def p(pc, code):
            code = hlstr(code)
            return "'%s' at %d: %s" % (code, pc, code[pc])
        def c(pc, code):
            return "l" not in hlstr(code)
        myjitdriver = JitDriver(greens=['pc', 'code'], reds=['n'],
                                get_printable_location=p, can_inline=c)
        
        def f(code, n):
            pc = 0
            while pc < len(code):

                myjitdriver.jit_merge_point(n=n, code=code, pc=pc)
                op = code[pc]
                if op == "+":
                    n += 7
                elif op == "-":
                    n -= 1
                elif op == "c":
                    n = f('---', n)
                elif op == "l":
                    if n > 0:
                        myjitdriver.can_enter_jit(n=n, code=code, pc=1)
                        pc = 1
                        continue
                else:
                    assert 0
                pc += 1
            return n
        def g(m):
            if m > 1000000:
                f('', 0)
            result = 0
            for i in range(m):
                result += f('+-cl--', i)
        g(50)
        self.meta_interp(g, [50], backendopt=True)
        self.check_tree_loop_count(3)
        self.check_history(int_add=1)

    def test_dont_inline_huge_stuff(self):
        def p(pc, code):
            code = hlstr(code)
            return "%s %d %s" % (code, pc, code[pc])
        def c(pc, code):
            return "l" not in hlstr(code)
        myjitdriver = JitDriver(greens=['pc', 'code'], reds=['n'],
                                get_printable_location=p, can_inline=c)
        
        def f(code, n):
            pc = 0
            while pc < len(code):

                myjitdriver.jit_merge_point(n=n, code=code, pc=pc)
                op = code[pc]
                if op == "-":
                    n -= 1
                elif op == "c":
                    f('--------------------', n)
                elif op == "l":
                    if n > 0:
                        myjitdriver.can_enter_jit(n=n, code=code, pc=0)
                        pc = 0
                        continue
                else:
                    assert 0
                pc += 1
            return n
        def g(m):
            myjitdriver.set_param('inlining', True)
            # carefully chosen threshold to make sure that the inner function
            # cannot be inlined, but the inner function on its own is small
            # enough
            myjitdriver.set_param('trace_limit', 40)
            if m > 1000000:
                f('', 0)
            result = 0
            for i in range(m):
                result += f('-c-----------l-', i+100)
        self.meta_interp(g, [10], backendopt=True)
        self.check_aborted_count(1)
        self.check_history(call_assembler=1, call=0)
        self.check_tree_loop_count(3)

    def test_directly_call_assembler(self):
        driver = JitDriver(greens = ['codeno'], reds = ['i'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def portal(codeno):
            i = 0
            while i < 10:
                driver.can_enter_jit(codeno = codeno, i = i)
                driver.jit_merge_point(codeno = codeno, i = i)
                if codeno == 2:
                    portal(1)
                i += 1

        self.meta_interp(portal, [2], inline=True)
        self.check_history(call_assembler=1)

    def test_recursion_cant_call_assembler_directly(self):
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'j'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def portal(codeno, j):
            i = 0
            while i < 1:
                driver.can_enter_jit(codeno=codeno, i=i, j=j)
                driver.jit_merge_point(codeno=codeno, i=i, j=j)
                i += 1
                if j == 0:
                    return
                portal(2, j - 1)

        portal(2, 50)
        self.meta_interp(portal, [2, 20], inline=True)
        self.check_history(call_assembler=0, call_may_force=1)
        self.check_enter_count_at_most(1)

    def test_directly_call_assembler_return(self):
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'k'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def portal(codeno):
            i = 0
            k = codeno
            while i < 10:
                driver.can_enter_jit(codeno = codeno, i = i, k = k)
                driver.jit_merge_point(codeno = codeno, i = i, k = k)
                if codeno == 2:
                    k = portal(1)
                i += 1
            return k

        self.meta_interp(portal, [2], inline=True)
        self.check_history(call_assembler=1)

    def test_directly_call_assembler_raise(self):

        class MyException(Exception):
            def __init__(self, x):
                self.x = x
        
        driver = JitDriver(greens = ['codeno'], reds = ['i'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def portal(codeno):
            i = 0
            while i < 10:
                driver.can_enter_jit(codeno = codeno, i = i)
                driver.jit_merge_point(codeno = codeno, i = i)
                if codeno == 2:
                    try:
                        portal(1)
                    except MyException, me:
                        i += me.x
                i += 1
            if codeno == 1:
                raise MyException(1)

        self.meta_interp(portal, [2], inline=True)
        self.check_history(call_assembler=1)        

    def test_directly_call_assembler_fail_guard(self):
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'k'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def portal(codeno, k):
            i = 0
            while i < 10:
                driver.can_enter_jit(codeno=codeno, i=i, k=k)
                driver.jit_merge_point(codeno=codeno, i=i, k=k)
                if codeno == 2:
                    k += portal(1, k)
                elif k > 40:
                    if i % 2:
                        k += 1
                    else:
                        k += 2
                k += 1
                i += 1
            return k

        res = self.meta_interp(portal, [2, 0], inline=True)
        assert res == 13542

    def test_directly_call_assembler_virtualizable(self):
        class Thing(object):
            def __init__(self, val):
                self.val = val
        
        class Frame(object):
            _virtualizable2_ = ['thing']
        
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'frame'],
                           virtualizables = ['frame'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def main(codeno):
            frame = Frame()
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
                frame.thing = Thing(nextval + 1)
                i += 1
            return frame.thing.val

        res = self.meta_interp(main, [0], inline=True)
        assert res == main(0)

    def test_directly_call_assembler_virtualizable_reset_token(self):
        from pypy.rpython.lltypesystem import lltype
        from pypy.rlib.debug import llinterpcall

        class Thing(object):
            def __init__(self, val):
                self.val = val
        
        class Frame(object):
            _virtualizable2_ = ['thing']
        
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'frame'],
                           virtualizables = ['frame'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        @dont_look_inside
        def check_frame(subframe):
            if we_are_translated():
                llinterpcall(lltype.Void, check_ll_frame, subframe)
        def check_ll_frame(ll_subframe):
            # This is called with the low-level Struct that is the frame.
            # Check that the vable_token was correctly reset to zero.
            # Note that in order for that test to catch failures, it needs
            # three levels of recursion: the vable_token of the subframe
            # at the level 2 is set to a non-zero value when doing the
            # call to the level 3 only.  This used to fail when the test
            # is run via pypy.jit.backend.x86.test.test_recursive.
            assert ll_subframe.vable_token == 0

        def main(codeno):
            frame = Frame()
            frame.thing = Thing(0)
            portal(codeno, frame)
            return frame.thing.val

        def portal(codeno, frame):
            i = 0
            while i < 5:
                driver.can_enter_jit(frame=frame, codeno=codeno, i=i)
                driver.jit_merge_point(frame=frame, codeno=codeno, i=i)
                nextval = frame.thing.val
                if codeno < 2:
                    subframe = Frame()
                    subframe.thing = Thing(nextval)
                    nextval = portal(codeno + 1, subframe)
                    check_frame(subframe)
                frame.thing = Thing(nextval + 1)
                i += 1
            return frame.thing.val

        res = self.meta_interp(main, [0], inline=True)
        assert res == main(0)

    def test_directly_call_assembler_virtualizable_force(self):
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

    def test_directly_call_assembler_virtualizable_with_array(self):
        myjitdriver = JitDriver(greens = ['codeno'], reds = ['n', 'x', 'frame'],
                                virtualizables = ['frame'],
                                can_inline = lambda codeno : False)

        class Frame(object):
            _virtualizable2_ = ['l[*]', 's']

            def __init__(self, l, s):
                self = hint(self, access_directly=True,
                            fresh_virtualizable=True)
                self.l = l
                self.s = s

        def main(codeno, n, a):
            frame = Frame([a, a+1, a+2, a+3], 0)
            return f(codeno, n, a, frame)
        
        def f(codeno, n, a, frame):
            x = 0
            while n > 0:
                myjitdriver.can_enter_jit(codeno=codeno, frame=frame, n=n, x=x)
                myjitdriver.jit_merge_point(codeno=codeno, frame=frame, n=n,
                                            x=x)
                frame.s = hint(frame.s, promote=True)
                n -= 1
                x += frame.l[frame.s]
                frame.s += 1
                if codeno == 0:
                    subframe = Frame([n, n+1, n+2, n+3], 0)
                    x += f(1, 10, 1, subframe)
                x += frame.l[frame.s]
                x += len(frame.l)
                frame.s -= 1
            return x

        res = self.meta_interp(main, [0, 10, 1], listops=True, inline=True)
        assert res == main(0, 10, 1)

    def test_directly_call_assembler_virtualizable_force_blackhole(self):
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

        def change(newthing, arg):
            print arg
            if arg > 30:
                somewhere_else.frame.thing = newthing
                arg = 13
            return arg

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
                else:
                    nextval = change(Thing(13), frame.thing.val)
                frame.thing = Thing(nextval + 1)
                i += 1
            return frame.thing.val

        res = self.meta_interp(main, [0], inline=True,
                               policy=StopAtXPolicy(change))
        assert res == main(0)

    def test_assembler_call_red_args(self):
        driver = JitDriver(greens = ['codeno'], reds = ['i', 'k'],
                           get_printable_location = lambda codeno : str(codeno),
                           can_inline = lambda codeno : False)

        def residual(k):
            if k > 40:
                return 0
            return 1

        def portal(codeno, k):
            i = 0
            while i < 10:
                driver.can_enter_jit(codeno=codeno, i=i, k=k)
                driver.jit_merge_point(codeno=codeno, i=i, k=k)
                if codeno == 2:
                    k += portal(residual(k), k)
                if codeno == 0:
                    k += 2
                elif codeno == 1:
                    k += 1
                i += 1
            return k

        res = self.meta_interp(portal, [2, 0], inline=True,
                               policy=StopAtXPolicy(residual))
        assert res == portal(2, 0)
        self.check_loops(call_assembler=2)

    # There is a test which I fail to write.
    #   * what happens if we call recursive_call while blackholing
    #     this seems to be completely corner case and not really happening
    #     in the wild

class TestLLtype(RecursiveTests, LLJitMixin):
    pass

class TestOOtype(RecursiveTests, OOJitMixin):
    pass
