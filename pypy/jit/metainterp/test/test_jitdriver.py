"""Tests for multiple JitDrivers."""
from pypy.rlib.jit import JitDriver
from pypy.jit.metainterp.test.test_basic import LLJitMixin, OOJitMixin


def getloc1():
    return "in jitdriver1"

def getloc2(g):
    return "in jitdriver2, with g=%d" % g


class MultipleJitDriversTests:

    def test_simple(self):
        myjitdriver1 = JitDriver(greens=[], reds=['n', 'm'],
                                 can_inline = lambda *args: False,
                                 get_printable_location = getloc1)
        myjitdriver2 = JitDriver(greens=['g'], reds=['r'],
                                 get_printable_location = getloc2)
        #
        def loop1(n, m):
            while n > 0:
                myjitdriver1.can_enter_jit(n=n, m=m)
                myjitdriver1.jit_merge_point(n=n, m=m)
                n -= m
            return n
        #
        def loop2(g, r):
            while r > 0:
                myjitdriver2.can_enter_jit(g=g, r=r)
                myjitdriver2.jit_merge_point(g=g, r=r)
                r += loop1(r, g) - 1
            return r
        #
        res = self.meta_interp(loop2, [4, 40], repeat=7, inline=True)
        assert res == loop2(4, 40)
        # the following numbers are not really expectations of the test
        # itself, but just the numbers that we got after looking carefully
        # at the generated machine code
        self.check_loop_count(5)
        self.check_tree_loop_count(4)    # 2 x loop, 2 x enter bridge
        self.check_enter_count(7)

    def test_simple_inline(self):
        # this is not an example of reasonable code: loop1() is unrolled
        # 'n/m' times, where n and m are given as red arguments.
        myjitdriver1 = JitDriver(greens=[], reds=['n', 'm'],
                                 can_inline = lambda *args: True,
                                 get_printable_location = getloc1)
        myjitdriver2 = JitDriver(greens=['g'], reds=['r'],
                                 get_printable_location = getloc2)
        #
        def loop1(n, m):
            while n > 0:
                if n > 1000:
                    myjitdriver1.can_enter_jit(n=n, m=m)
                myjitdriver1.jit_merge_point(n=n, m=m)
                n -= m
            return n
        #
        def loop2(g, r):
            while r > 0:
                myjitdriver2.can_enter_jit(g=g, r=r)
                myjitdriver2.jit_merge_point(g=g, r=r)
                r += loop1(r, g) - 1
            return r
        #
        res = self.meta_interp(loop2, [4, 40], repeat=7, inline=True)
        assert res == loop2(4, 40)
        # we expect no loop at all for 'loop1': it should always be inlined
        self.check_tree_loop_count(2)    # 1 x loop, 1 x enter bridge


class TestLLtype(MultipleJitDriversTests, LLJitMixin):
    pass

class TestOOtype(MultipleJitDriversTests, OOJitMixin):
    pass
