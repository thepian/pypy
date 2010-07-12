import py, sys, random, os, struct, operator
from pypy.jit.metainterp.history import (AbstractFailDescr,
                                         BasicFailDescr,
                                         BoxInt, Box, BoxPtr,
                                         LoopToken,
                                         ConstInt, ConstPtr,
                                         BoxObj, Const,
                                         ConstObj, BoxFloat, ConstFloat)
from pypy.jit.metainterp.resoperation import ResOperation, rop
from pypy.jit.metainterp.typesystem import deref
from pypy.jit.metainterp.test.oparser import parse
from pypy.rpython.lltypesystem import lltype, llmemory, rstr, rffi, rclass
from pypy.rpython.ootypesystem import ootype
from pypy.rpython.annlowlevel import llhelper
from pypy.rpython.llinterp import LLException
from pypy.jit.codewriter import heaptracker


class Runner(object):

    def execute_operation(self, opname, valueboxes, result_type, descr=None):
        inputargs, operations = self._get_single_operation_list(opname,
                                                                result_type,
                                                                valueboxes,
                                                                descr)
        looptoken = LoopToken()
        self.cpu.compile_loop(inputargs, operations, looptoken)
        j = 0
        for box in inputargs:
            if isinstance(box, BoxInt):
                self.cpu.set_future_value_int(j, box.getint())
                j += 1
            elif isinstance(box, (BoxPtr, BoxObj)):
                self.cpu.set_future_value_ref(j, box.getref_base())
                j += 1
            elif isinstance(box, BoxFloat):
                self.cpu.set_future_value_float(j, box.getfloat())
                j += 1
            else:
                raise NotImplementedError(box)
        res = self.cpu.execute_token(looptoken)
        if res is operations[-1].descr:
            self.guard_failed = False
        else:
            self.guard_failed = True
        if result_type == 'int':
            return BoxInt(self.cpu.get_latest_value_int(0))
        elif result_type == 'ref':
            return BoxPtr(self.cpu.get_latest_value_ref(0))
        elif result_type == 'float':
            return BoxFloat(self.cpu.get_latest_value_float(0))
        elif result_type == 'void':
            return None
        else:
            assert False

    def _get_single_operation_list(self, opnum, result_type, valueboxes,
                                   descr):
        if result_type == 'void':
            result = None
        elif result_type == 'int':
            result = BoxInt()
        elif result_type == 'ref':
            result = BoxPtr()
        elif result_type == 'float':
            result = BoxFloat()
        else:
            raise ValueError(result_type)
        if result is None:
            results = []
        else:
            results = [result]
        operations = [ResOperation(opnum, valueboxes, result),
                      ResOperation(rop.FINISH, results, None,
                                   descr=BasicFailDescr(0))]
        if operations[0].is_guard():
            operations[0].fail_args = []
            if not descr:
                descr = BasicFailDescr(1)
        operations[0].descr = descr
        inputargs = []
        for box in valueboxes:
            if isinstance(box, Box) and box not in inputargs:
                inputargs.append(box)
        return inputargs, operations

class BaseBackendTest(Runner):

    avoid_instances = False

    def test_compile_linear_loop(self):
        i0 = BoxInt()
        i1 = BoxInt()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.FINISH, [i1], None, descr=BasicFailDescr(1))
            ]
        inputargs = [i0]
        looptoken = LoopToken()
        self.cpu.compile_loop(inputargs, operations, looptoken)
        self.cpu.set_future_value_int(0, 2)
        fail = self.cpu.execute_token(looptoken)
        res = self.cpu.get_latest_value_int(0)
        assert res == 3        
        assert fail.identifier == 1

    def test_compile_loop(self):
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.INT_LE, [i1, ConstInt(9)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=BasicFailDescr(2)),
            ResOperation(rop.JUMP, [i1], None, descr=looptoken),
            ]
        inputargs = [i0]
        operations[2].fail_args = [i1]
        
        self.cpu.compile_loop(inputargs, operations, looptoken)
        self.cpu.set_future_value_int(0, 2)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 2
        res = self.cpu.get_latest_value_int(0)
        assert res == 10

    def test_compile_with_holes_in_fail_args(self):
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.INT_LE, [i1, ConstInt(9)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=BasicFailDescr(2)),
            ResOperation(rop.JUMP, [i1], None, descr=looptoken),
            ]
        inputargs = [i0]
        operations[2].fail_args = [None, None, i1, None]
        
        self.cpu.compile_loop(inputargs, operations, looptoken)
        self.cpu.set_future_value_int(0, 2)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 2
        res = self.cpu.get_latest_value_int(2)
        assert res == 10

    def test_backends_dont_keep_loops_alive(self):
        import weakref, gc
        self.cpu.dont_keepalive_stuff = True
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.INT_LE, [i1, ConstInt(9)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=BasicFailDescr()),
            ResOperation(rop.JUMP, [i1], None, descr=looptoken),
            ]
        inputargs = [i0]
        operations[2].fail_args = [i1]
        wr_i1 = weakref.ref(i1)
        wr_guard = weakref.ref(operations[2])
        self.cpu.compile_loop(inputargs, operations, looptoken)
        del i0, i1, i2
        del inputargs
        del operations
        gc.collect()
        assert not wr_i1() and not wr_guard()

    def test_compile_bridge(self):
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        faildescr1 = BasicFailDescr(1)
        faildescr2 = BasicFailDescr(2)
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.INT_LE, [i1, ConstInt(9)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=faildescr1),
            ResOperation(rop.JUMP, [i1], None, descr=looptoken),
            ]
        inputargs = [i0]
        operations[2].fail_args = [i1]
        self.cpu.compile_loop(inputargs, operations, looptoken)

        i1b = BoxInt()
        i3 = BoxInt()
        bridge = [
            ResOperation(rop.INT_LE, [i1b, ConstInt(19)], i3),
            ResOperation(rop.GUARD_TRUE, [i3], None, descr=faildescr2),
            ResOperation(rop.JUMP, [i1b], None, descr=looptoken),
        ]
        bridge[1].fail_args = [i1b]

        self.cpu.compile_bridge(faildescr1, [i1b], bridge)        

        self.cpu.set_future_value_int(0, 2)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 2
        res = self.cpu.get_latest_value_int(0)
        assert res == 20

    def test_compile_bridge_with_holes(self):
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        faildescr1 = BasicFailDescr(1)
        faildescr2 = BasicFailDescr(2)
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.INT_LE, [i1, ConstInt(9)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=faildescr1),
            ResOperation(rop.JUMP, [i1], None, descr=looptoken),
            ]
        inputargs = [i0]
        operations[2].fail_args = [None, i1, None]
        self.cpu.compile_loop(inputargs, operations, looptoken)

        i1b = BoxInt()
        i3 = BoxInt()
        bridge = [
            ResOperation(rop.INT_LE, [i1b, ConstInt(19)], i3),
            ResOperation(rop.GUARD_TRUE, [i3], None, descr=faildescr2),
            ResOperation(rop.JUMP, [i1b], None, descr=looptoken),
        ]
        bridge[1].fail_args = [i1b]

        self.cpu.compile_bridge(faildescr1, [i1b], bridge)        

        self.cpu.set_future_value_int(0, 2)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 2
        res = self.cpu.get_latest_value_int(0)
        assert res == 20

    def test_get_latest_value_count(self):
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        faildescr1 = BasicFailDescr(1)
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [i0, ConstInt(1)], i1),
            ResOperation(rop.INT_LE, [i1, ConstInt(9)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=faildescr1),
            ResOperation(rop.JUMP, [i1], None, descr=looptoken),
            ]
        inputargs = [i0]
        operations[2].fail_args = [None, i1, None]
        self.cpu.compile_loop(inputargs, operations, looptoken)

        self.cpu.set_future_value_int(0, 2)
        fail = self.cpu.execute_token(looptoken)
        assert fail is faildescr1

        count = self.cpu.get_latest_value_count()
        assert count == 3
        assert self.cpu.get_latest_value_int(1) == 10
        assert self.cpu.get_latest_value_int(1) == 10   # multiple reads ok
        self.cpu.clear_latest_values(3)

    def test_finish(self):
        i0 = BoxInt()
        class UntouchableFailDescr(AbstractFailDescr):
            def __setattr__(self, name, value):
                if name == 'index':
                    return AbstractFailDescr.__setattr__(self, name, value)
                py.test.fail("finish descrs should not be touched")
        faildescr = UntouchableFailDescr() # to check that is not touched
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.FINISH, [i0], None, descr=faildescr)
            ]
        self.cpu.compile_loop([i0], operations, looptoken)
        self.cpu.set_future_value_int(0, 99)
        fail = self.cpu.execute_token(looptoken)
        assert fail is faildescr
        res = self.cpu.get_latest_value_int(0)
        assert res == 99

        looptoken = LoopToken()
        operations = [
            ResOperation(rop.FINISH, [ConstInt(42)], None, descr=faildescr)
            ]
        self.cpu.compile_loop([], operations, looptoken)
        fail = self.cpu.execute_token(looptoken)
        assert fail is faildescr
        res = self.cpu.get_latest_value_int(0)
        assert res == 42

        looptoken = LoopToken()
        operations = [
            ResOperation(rop.FINISH, [], None, descr=faildescr)
            ]
        self.cpu.compile_loop([], operations, looptoken)
        fail = self.cpu.execute_token(looptoken)
        assert fail is faildescr

    def test_execute_operations_in_env(self):
        cpu = self.cpu
        x = BoxInt(123)
        y = BoxInt(456)
        z = BoxInt(579)
        t = BoxInt(455)
        u = BoxInt(0)    # False
        looptoken = LoopToken()
        operations = [
            ResOperation(rop.INT_ADD, [x, y], z),
            ResOperation(rop.INT_SUB, [y, ConstInt(1)], t),
            ResOperation(rop.INT_EQ, [t, ConstInt(0)], u),
            ResOperation(rop.GUARD_FALSE, [u], None,
                         descr=BasicFailDescr()),
            ResOperation(rop.JUMP, [z, t], None, descr=looptoken),
            ]
        operations[-2].fail_args = [t, z]
        cpu.compile_loop([x, y], operations, looptoken)
        self.cpu.set_future_value_int(0, 0)
        self.cpu.set_future_value_int(1, 10)
        res = self.cpu.execute_token(looptoken)
        assert self.cpu.get_latest_value_int(0) == 0
        assert self.cpu.get_latest_value_int(1) == 55

    def test_int_operations(self):
        from pypy.jit.metainterp.test.test_executor import get_int_tests
        for opnum, boxargs, retvalue in get_int_tests():
            res = self.execute_operation(opnum, boxargs, 'int')
            assert res.value == retvalue
        
    def test_float_operations(self):
        from pypy.jit.metainterp.test.test_executor import get_float_tests
        for opnum, boxargs, rettype, retvalue in get_float_tests(self.cpu):
            res = self.execute_operation(opnum, boxargs, rettype)
            assert res.value == retvalue

    def test_ovf_operations(self, reversed=False):
        minint = -sys.maxint-1
        boom = 'boom'
        for opnum, testcases in [
            (rop.INT_ADD_OVF, [(10, -2, 8),
                               (-1, minint, boom),
                               (sys.maxint//2, sys.maxint//2+2, boom)]),
            (rop.INT_SUB_OVF, [(-20, -23, 3),
                               (-2, sys.maxint, boom),
                               (sys.maxint//2, -(sys.maxint//2+2), boom)]),
            (rop.INT_MUL_OVF, [(minint/2, 2, minint),
                               (-2, -(minint/2), minint),
                               (minint/2, -2, boom)]),
            ]:
            v1 = BoxInt(testcases[0][0])
            v2 = BoxInt(testcases[0][1])
            v_res = BoxInt()
            #
            if not reversed:
                ops = [
                    ResOperation(opnum, [v1, v2], v_res),
                    ResOperation(rop.GUARD_NO_OVERFLOW, [], None,
                                 descr=BasicFailDescr(1)),
                    ResOperation(rop.FINISH, [v_res], None,
                                 descr=BasicFailDescr(2)),
                    ]
                ops[1].fail_args = []
            else:
                v_exc = self.cpu.ts.BoxRef()
                ops = [
                    ResOperation(opnum, [v1, v2], v_res),
                    ResOperation(rop.GUARD_OVERFLOW, [], None,
                                 descr=BasicFailDescr(1)),
                    ResOperation(rop.FINISH, [], None, descr=BasicFailDescr(2)),
                    ]
                ops[1].fail_args = [v_res]
            #
            looptoken = LoopToken()
            self.cpu.compile_loop([v1, v2], ops, looptoken)
            for x, y, z in testcases:
                excvalue = self.cpu.grab_exc_value()
                assert not excvalue
                self.cpu.set_future_value_int(0, x)
                self.cpu.set_future_value_int(1, y)
                fail = self.cpu.execute_token(looptoken)
                if (z == boom) ^ reversed:
                    assert fail.identifier == 1
                else:
                    assert fail.identifier == 2
                if z != boom:
                    assert self.cpu.get_latest_value_int(0) == z
                excvalue = self.cpu.grab_exc_value()
                assert not excvalue

    def test_ovf_operations_reversed(self):
        self.test_ovf_operations(reversed=True)
        
    def test_bh_call(self):
        cpu = self.cpu
        #
        def func(c):
            return chr(ord(c) + 1)
        FPTR = self.Ptr(self.FuncType([lltype.Char], lltype.Char))
        func_ptr = llhelper(FPTR, func)
        calldescr = cpu.calldescrof(deref(FPTR), (lltype.Char,), lltype.Char)
        x = cpu.bh_call_i(self.get_funcbox(cpu, func_ptr).value,
                          calldescr, [ord('A')], None, None)
        assert x == ord('B')
        if cpu.supports_floats:
            def func(f, i):
                return f - float(i)
            FPTR = self.Ptr(self.FuncType([lltype.Float, lltype.Signed],
                                          lltype.Float))
            func_ptr = llhelper(FPTR, func)
            FTP = deref(FPTR)
            calldescr = cpu.calldescrof(FTP, FTP.ARGS, FTP.RESULT)
            x = cpu.bh_call_f(self.get_funcbox(cpu, func_ptr).value,
                              calldescr,
                              [42], None, [3.5])
            assert x == 3.5 - 42

    def test_call(self):

        def func_int(a, b):
            return a + b
        def func_char(c, c1):
            return chr(ord(c) + ord(c1))

        functions = [
            (func_int, lltype.Signed, 655360),
            (func_int, rffi.SHORT, 1213),
            (func_char, lltype.Char, 12)
            ]

        for func, TP, num in functions:
            cpu = self.cpu
            #
            FPTR = self.Ptr(self.FuncType([TP, TP], TP))
            func_ptr = llhelper(FPTR, func)
            FUNC = deref(FPTR)
            calldescr = cpu.calldescrof(FUNC, FUNC.ARGS, FUNC.RESULT)
            funcbox = self.get_funcbox(cpu, func_ptr)
            res = self.execute_operation(rop.CALL,
                                         [funcbox, BoxInt(num), BoxInt(num)],
                                         'int', descr=calldescr)
            assert res.value == 2 * num

        if cpu.supports_floats:
            def func(f0, f1, f2, f3, f4, f5, f6, i0, i1, f7, f8, f9):
                return f0 + f1 + f2 + f3 + f4 + f5 + f6 + float(i0 + i1) + f7 + f8 + f9
            F = lltype.Float
            I = lltype.Signed
            FUNC = self.FuncType([F] * 7 + [I] * 2 + [F] * 3, F)
            FPTR = self.Ptr(FUNC)
            func_ptr = llhelper(FPTR, func)
            calldescr = cpu.calldescrof(FUNC, FUNC.ARGS, FUNC.RESULT)
            funcbox = self.get_funcbox(cpu, func_ptr)
            args = ([BoxFloat(.1) for i in range(7)] +
                    [BoxInt(1), BoxInt(2), BoxFloat(.2), BoxFloat(.3),
                     BoxFloat(.4)])
            res = self.execute_operation(rop.CALL,
                                         [funcbox] + args,
                                         'float', descr=calldescr)
            assert abs(res.value - 4.6) < 0.0001
        
    def test_call_stack_alignment(self):
        # test stack alignment issues, notably for Mac OS/X.
        # also test the ordering of the arguments.

        def func_ints(*ints):
            s = str(ints) + '\n'
            os.write(1, s)   # don't remove -- crash if the stack is misaligned
            return sum([(10+i)*(5+j) for i, j in enumerate(ints)])

        for nb_args in range(0, 35):
            cpu = self.cpu
            TP = lltype.Signed
            #
            FPTR = self.Ptr(self.FuncType([TP] * nb_args, TP))
            func_ptr = llhelper(FPTR, func_ints)
            FUNC = deref(FPTR)
            calldescr = cpu.calldescrof(FUNC, FUNC.ARGS, FUNC.RESULT)
            funcbox = self.get_funcbox(cpu, func_ptr)
            args = [280-24*i for i in range(nb_args)]
            res = self.execute_operation(rop.CALL,
                                         [funcbox] + map(BoxInt, args),
                                         'int', descr=calldescr)
            assert res.value == func_ints(*args)

    def test_field_basic(self):
        t_box, T_box = self.alloc_instance(self.T)
        fielddescr = self.cpu.fielddescrof(self.S, 'value')
        assert not fielddescr.is_pointer_field()
        #
        res = self.execute_operation(rop.SETFIELD_GC, [t_box, BoxInt(39082)],
                                     'void', descr=fielddescr)
        assert res is None
        res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                     'int', descr=fielddescr)
        assert res.value == 39082
        #
        fielddescr1 = self.cpu.fielddescrof(self.S, 'chr1')
        fielddescr2 = self.cpu.fielddescrof(self.S, 'chr2')
        shortdescr = self.cpu.fielddescrof(self.S, 'short')
        self.execute_operation(rop.SETFIELD_GC, [t_box, BoxInt(250)],
                               'void', descr=fielddescr2)
        self.execute_operation(rop.SETFIELD_GC, [t_box, BoxInt(133)],
                               'void', descr=fielddescr1)
        self.execute_operation(rop.SETFIELD_GC, [t_box, BoxInt(1331)],
                               'void', descr=shortdescr)
        res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                     'int', descr=fielddescr2)
        assert res.value == 250
        res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                     'int', descr=fielddescr1)
        assert res.value == 133
        res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                     'int', descr=shortdescr)
        assert res.value == 1331
        
        #
        u_box, U_box = self.alloc_instance(self.U)
        fielddescr2 = self.cpu.fielddescrof(self.S, 'next')
        assert fielddescr2.is_pointer_field()
        res = self.execute_operation(rop.SETFIELD_GC, [t_box, u_box],
                                     'void', descr=fielddescr2)
        assert res is None
        res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                     'ref', descr=fielddescr2)
        assert res.value == u_box.value
        #
        null_const = self.null_instance().constbox()
        res = self.execute_operation(rop.SETFIELD_GC, [t_box, null_const],
                                     'void', descr=fielddescr2)
        assert res is None
        res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                     'ref', descr=fielddescr2)
        assert res.value == null_const.value
        if self.cpu.supports_floats:
            floatdescr = self.cpu.fielddescrof(self.S, 'float')
            self.execute_operation(rop.SETFIELD_GC, [t_box, BoxFloat(3.4)],
                                   'void', descr=floatdescr)
            res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                         'float', descr=floatdescr)
            assert res.value == 3.4
            #
            self.execute_operation(rop.SETFIELD_GC, [t_box, ConstFloat(-3.6)],
                                   'void', descr=floatdescr)
            res = self.execute_operation(rop.GETFIELD_GC, [t_box],
                                         'float', descr=floatdescr)
            assert res.value == -3.6


    def test_passing_guards(self):
        t_box, T_box = self.alloc_instance(self.T)
        nullbox = self.null_instance()
        all = [(rop.GUARD_TRUE, [BoxInt(1)]),
               (rop.GUARD_FALSE, [BoxInt(0)]),
               (rop.GUARD_VALUE, [BoxInt(42), ConstInt(42)]),
               ]
        if not self.avoid_instances:
            all.extend([
               (rop.GUARD_NONNULL, [t_box]),
               (rop.GUARD_ISNULL, [nullbox])
               ])
        if self.cpu.supports_floats:
            all.append((rop.GUARD_VALUE, [BoxFloat(3.5), ConstFloat(3.5)]))
        for (opname, args) in all:
            assert self.execute_operation(opname, args, 'void') == None
            assert not self.guard_failed


    def test_passing_guard_class(self):
        t_box, T_box = self.alloc_instance(self.T)
        #null_box = ConstPtr(lltype.cast_opaque_ptr(llmemory.GCREF, lltype.nullptr(T)))
        self.execute_operation(rop.GUARD_CLASS, [t_box, T_box], 'void')
        assert not self.guard_failed
        self.execute_operation(rop.GUARD_NONNULL_CLASS, [t_box, T_box], 'void')
        assert not self.guard_failed

    def test_failing_guards(self):
        t_box, T_box = self.alloc_instance(self.T)
        nullbox = self.null_instance()
        all = [(rop.GUARD_TRUE, [BoxInt(0)]),
               (rop.GUARD_FALSE, [BoxInt(1)]),
               (rop.GUARD_VALUE, [BoxInt(42), ConstInt(41)]),
               ]
        if not self.avoid_instances:
            all.extend([
               (rop.GUARD_NONNULL, [nullbox]),
               (rop.GUARD_ISNULL, [t_box])])
        if self.cpu.supports_floats:
            all.append((rop.GUARD_VALUE, [BoxFloat(-1.0), ConstFloat(1.0)]))
        for opname, args in all:
            assert self.execute_operation(opname, args, 'void') == None
            assert self.guard_failed

    def test_failing_guard_class(self):
        t_box, T_box = self.alloc_instance(self.T)
        u_box, U_box = self.alloc_instance(self.U)        
        null_box = self.null_instance()
        for opname, args in [(rop.GUARD_CLASS, [t_box, U_box]),
                             (rop.GUARD_CLASS, [u_box, T_box]),
                             (rop.GUARD_NONNULL_CLASS, [t_box, U_box]),
                             (rop.GUARD_NONNULL_CLASS, [u_box, T_box]),
                             (rop.GUARD_NONNULL_CLASS, [null_box, T_box]),
                             ]:
            assert self.execute_operation(opname, args, 'void') == None
            assert self.guard_failed

    def test_ooops(self):
        u1_box, U_box = self.alloc_instance(self.U)
        u2_box, U_box = self.alloc_instance(self.U)
        r = self.execute_operation(rop.PTR_EQ, [u1_box,
                                                u1_box.clonebox()], 'int')
        assert r.value == 1
        r = self.execute_operation(rop.PTR_NE, [u2_box,
                                                u2_box.clonebox()], 'int')
        assert r.value == 0
        r = self.execute_operation(rop.PTR_EQ, [u1_box, u2_box], 'int')
        assert r.value == 0
        r = self.execute_operation(rop.PTR_NE, [u2_box, u1_box], 'int')
        assert r.value == 1
        #
        null_box = self.null_instance()
        r = self.execute_operation(rop.PTR_EQ, [null_box,
                                                null_box.clonebox()], 'int')
        assert r.value == 1
        r = self.execute_operation(rop.PTR_EQ, [u1_box, null_box], 'int')
        assert r.value == 0
        r = self.execute_operation(rop.PTR_EQ, [null_box, u2_box], 'int')
        assert r.value == 0
        r = self.execute_operation(rop.PTR_NE, [null_box,
                                                null_box.clonebox()], 'int')
        assert r.value == 0
        r = self.execute_operation(rop.PTR_NE, [u2_box, null_box], 'int')
        assert r.value == 1
        r = self.execute_operation(rop.PTR_NE, [null_box, u1_box], 'int')
        assert r.value == 1

    def test_array_basic(self):
        a_box, A = self.alloc_array_of(lltype.Signed, 342)
        arraydescr = self.cpu.arraydescrof(A)
        assert not arraydescr.is_array_of_pointers()
        #
        r = self.execute_operation(rop.ARRAYLEN_GC, [a_box],
                                   'int', descr=arraydescr)
        assert r.value == 342
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(310),
                                                         BoxInt(7441)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(310)],
                                   'int', descr=arraydescr)
        assert r.value == 7441
        #
        a_box, A = self.alloc_array_of(lltype.Char, 11)
        arraydescr = self.cpu.arraydescrof(A)
        assert not arraydescr.is_array_of_pointers()
        r = self.execute_operation(rop.ARRAYLEN_GC, [a_box],
                                   'int', descr=arraydescr)
        assert r.value == 11
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(4),
                                                         BoxInt(150)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(3),
                                                         BoxInt(160)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(4)],
                                   'int', descr=arraydescr)
        assert r.value == 150
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(3)],
                                   'int', descr=arraydescr)
        assert r.value == 160
        
        #
        if isinstance(A, lltype.GcArray):
            A = lltype.Ptr(A)
        b_box, B = self.alloc_array_of(A, 3)
        arraydescr = self.cpu.arraydescrof(B)
        assert arraydescr.is_array_of_pointers()
        r = self.execute_operation(rop.ARRAYLEN_GC, [b_box],
                                   'int', descr=arraydescr)
        assert r.value == 3
        r = self.execute_operation(rop.SETARRAYITEM_GC, [b_box, BoxInt(1),
                                                         a_box],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.GETARRAYITEM_GC, [b_box, BoxInt(1)],
                                   'ref', descr=arraydescr)
        assert r.value == a_box.value
        #
        # Unsigned should work the same as Signed
        a_box, A = self.alloc_array_of(lltype.Unsigned, 342)
        arraydescr = self.cpu.arraydescrof(A)
        assert not arraydescr.is_array_of_pointers()
        r = self.execute_operation(rop.ARRAYLEN_GC, [a_box],
                                   'int', descr=arraydescr)
        assert r.value == 342
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(310),
                                                         BoxInt(7441)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(310)],
                                   'int', descr=arraydescr)
        assert r.value == 7441
        #
        # Bool should work the same as Char
        a_box, A = self.alloc_array_of(lltype.Bool, 311)
        arraydescr = self.cpu.arraydescrof(A)
        assert not arraydescr.is_array_of_pointers()
        r = self.execute_operation(rop.ARRAYLEN_GC, [a_box],
                                   'int', descr=arraydescr)
        assert r.value == 311
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(304),
                                                         BoxInt(1)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(303),
                                                         BoxInt(0)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(302),
                                                         BoxInt(1)],
                                   'void', descr=arraydescr)
        assert r is None
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(304)],
                                   'int', descr=arraydescr)
        assert r.value == 1
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(303)],
                                   'int', descr=arraydescr)
        assert r.value == 0
        r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(302)],
                                   'int', descr=arraydescr)
        assert r.value == 1

        if self.cpu.supports_floats:
            a_box, A = self.alloc_array_of(lltype.Float, 31)
            arraydescr = self.cpu.arraydescrof(A)
            self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(1),
                                                         BoxFloat(3.5)],
                                   'void', descr=arraydescr)
            self.execute_operation(rop.SETARRAYITEM_GC, [a_box, BoxInt(2),
                                                         ConstFloat(4.5)],
                                   'void', descr=arraydescr)
            r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(1)],
                                       'float', descr=arraydescr)
            assert r.value == 3.5
            r = self.execute_operation(rop.GETARRAYITEM_GC, [a_box, BoxInt(2)],
                                       'float', descr=arraydescr)
            assert r.value == 4.5


    def test_string_basic(self):
        s_box = self.alloc_string("hello\xfe")
        r = self.execute_operation(rop.STRLEN, [s_box], 'int')
        assert r.value == 6
        r = self.execute_operation(rop.STRGETITEM, [s_box, BoxInt(5)], 'int')
        assert r.value == 254
        r = self.execute_operation(rop.STRSETITEM, [s_box, BoxInt(4),
                                                    BoxInt(153)], 'void')
        assert r is None
        r = self.execute_operation(rop.STRGETITEM, [s_box, BoxInt(5)], 'int')
        assert r.value == 254
        r = self.execute_operation(rop.STRGETITEM, [s_box, BoxInt(4)], 'int')
        assert r.value == 153

    def test_do_unicode_basic(self):
        u = self.cpu.bh_newunicode(5)
        self.cpu.bh_unicodesetitem(u, 4, 123)
        r = self.cpu.bh_unicodegetitem(u, 4)
        assert r == 123

    def test_unicode_basic(self):
        u_box = self.alloc_unicode(u"hello\u1234")
        r = self.execute_operation(rop.UNICODELEN, [u_box], 'int')
        assert r.value == 6
        r = self.execute_operation(rop.UNICODEGETITEM, [u_box, BoxInt(5)],
                                   'int')
        assert r.value == 0x1234
        r = self.execute_operation(rop.UNICODESETITEM, [u_box, BoxInt(4),
                                                        BoxInt(31313)], 'void')
        assert r is None
        r = self.execute_operation(rop.UNICODEGETITEM, [u_box, BoxInt(5)],
                                   'int')
        assert r.value == 0x1234
        r = self.execute_operation(rop.UNICODEGETITEM, [u_box, BoxInt(4)],
                                   'int')
        assert r.value == 31313

    def test_same_as(self):
        r = self.execute_operation(rop.SAME_AS, [ConstInt(5)], 'int')
        assert r.value == 5
        r = self.execute_operation(rop.SAME_AS, [BoxInt(5)], 'int')
        assert r.value == 5
        u_box = self.alloc_unicode(u"hello\u1234")
        r = self.execute_operation(rop.SAME_AS, [u_box.constbox()], 'ref')
        assert r.value == u_box.value
        r = self.execute_operation(rop.SAME_AS, [u_box], 'ref')
        assert r.value == u_box.value

        if self.cpu.supports_floats:
            r = self.execute_operation(rop.SAME_AS, [ConstFloat(5.5)], 'float')
            assert r.value == 5.5
            r = self.execute_operation(rop.SAME_AS, [BoxFloat(5.5)], 'float')
            assert r.value == 5.5

    def test_virtual_ref(self):
        pass   # VIRTUAL_REF must not reach the backend nowadays

    def test_virtual_ref_finish(self):
        pass   # VIRTUAL_REF_FINISH must not reach the backend nowadays

    def test_jump(self):
        # this test generates small loops where the JUMP passes many
        # arguments of various types, shuffling them around.
        if self.cpu.supports_floats:
            numkinds = 3
        else:
            numkinds = 2
        seed = random.randrange(0, 10000)
        print 'Seed is', seed    # or choose it by changing the previous line
        r = random.Random()
        r.seed(seed)
        for nb_args in range(50):
            print 'Passing %d arguments around...' % nb_args
            #
            inputargs = []
            for k in range(nb_args):
                kind = r.randrange(0, numkinds)
                if kind == 0:
                    inputargs.append(BoxInt())
                elif kind == 1:
                    inputargs.append(BoxPtr())
                else:
                    inputargs.append(BoxFloat())
            jumpargs = []
            remixing = []
            for srcbox in inputargs:
                n = r.randrange(0, len(inputargs))
                otherbox = inputargs[n]
                if otherbox.type == srcbox.type:
                    remixing.append((srcbox, otherbox))
                else:
                    otherbox = srcbox
                jumpargs.append(otherbox)
            #
            index_counter = r.randrange(0, len(inputargs)+1)
            i0 = BoxInt()
            i1 = BoxInt()
            i2 = BoxInt()
            inputargs.insert(index_counter, i0)
            jumpargs.insert(index_counter, i1)
            #
            looptoken = LoopToken()
            faildescr = BasicFailDescr(15)
            operations = [
                ResOperation(rop.INT_SUB, [i0, ConstInt(1)], i1),
                ResOperation(rop.INT_GE, [i1, ConstInt(0)], i2),
                ResOperation(rop.GUARD_TRUE, [i2], None),
                ResOperation(rop.JUMP, jumpargs, None, descr=looptoken),
                ]
            operations[2].fail_args = inputargs[:]
            operations[2].descr = faildescr
            #
            self.cpu.compile_loop(inputargs, operations, looptoken)
            #
            values = []
            S = lltype.GcStruct('S')
            for box in inputargs:
                if isinstance(box, BoxInt):
                    values.append(r.randrange(-10000, 10000))
                elif isinstance(box, BoxPtr):
                    p = lltype.malloc(S)
                    values.append(lltype.cast_opaque_ptr(llmemory.GCREF, p))
                elif isinstance(box, BoxFloat):
                    values.append(r.random())
                else:
                    assert 0
            values[index_counter] = 11
            #
            for i, (box, val) in enumerate(zip(inputargs, values)):
                if isinstance(box, BoxInt):
                    self.cpu.set_future_value_int(i, val)
                elif isinstance(box, BoxPtr):
                    self.cpu.set_future_value_ref(i, val)
                elif isinstance(box, BoxFloat):
                    self.cpu.set_future_value_float(i, val)
                else:
                    assert 0
            #
            fail = self.cpu.execute_token(looptoken)
            assert fail.identifier == 15
            #
            dstvalues = values[:]
            for _ in range(11):
                expected = dstvalues[:]
                for tgtbox, srcbox in remixing:
                    v = dstvalues[inputargs.index(srcbox)]
                    expected[inputargs.index(tgtbox)] = v
                dstvalues = expected
            #
            assert dstvalues[index_counter] == 11
            dstvalues[index_counter] = 0
            for i, (box, val) in enumerate(zip(inputargs, dstvalues)):
                if isinstance(box, BoxInt):
                    got = self.cpu.get_latest_value_int(i)
                elif isinstance(box, BoxPtr):
                    got = self.cpu.get_latest_value_ref(i)
                elif isinstance(box, BoxFloat):
                    got = self.cpu.get_latest_value_float(i)
                else:
                    assert 0
                assert type(got) == type(val)
                assert got == val

    def test_compile_bridge_float(self):
        if not self.cpu.supports_floats:
            py.test.skip("requires floats")
        fboxes = [BoxFloat() for i in range(12)]
        i2 = BoxInt()
        faildescr1 = BasicFailDescr(1)
        faildescr2 = BasicFailDescr(2)
        operations = [
            ResOperation(rop.FLOAT_LE, [fboxes[0], ConstFloat(9.2)], i2),
            ResOperation(rop.GUARD_TRUE, [i2], None, descr=faildescr1),
            ResOperation(rop.FINISH, fboxes, None, descr=faildescr2),
            ]
        operations[-2].fail_args = fboxes
        looptoken = LoopToken()
        self.cpu.compile_loop(fboxes, operations, looptoken)

        fboxes2 = [BoxFloat() for i in range(12)]
        f3 = BoxFloat()
        bridge = [
            ResOperation(rop.FLOAT_SUB, [fboxes2[0], ConstFloat(1.0)], f3),
            ResOperation(rop.JUMP, [f3] + fboxes2[1:], None, descr=looptoken),
        ]

        self.cpu.compile_bridge(faildescr1, fboxes2, bridge)

        for i in range(len(fboxes)):
            self.cpu.set_future_value_float(i, 13.5 + 6.73 * i)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 2
        res = self.cpu.get_latest_value_float(0)
        assert res == 8.5
        for i in range(1, len(fboxes)):
            assert self.cpu.get_latest_value_float(i) == 13.5 + 6.73 * i

    def test_unused_result_int(self):
        # test pure operations on integers whose result is not used
        from pypy.jit.metainterp.test.test_executor import get_int_tests
        int_tests = list(get_int_tests())
        int_tests = [(opnum, boxargs, 'int', retvalue)
                     for opnum, boxargs, retvalue in int_tests]
        self._test_unused_result(int_tests)

    def test_unused_result_float(self):
        # same as test_unused_result_int, for float operations
        from pypy.jit.metainterp.test.test_executor import get_float_tests
        float_tests = list(get_float_tests(self.cpu))
        self._test_unused_result(float_tests)

    def _test_unused_result(self, tests):
        while len(tests) > 50:     # only up to 50 tests at once
            self._test_unused_result(tests[:50])
            tests = tests[50:]
        inputargs = []
        operations = []
        for opnum, boxargs, rettype, retvalue in tests:
            inputargs += [box for box in boxargs if isinstance(box, Box)]
            if rettype == 'int':
                boxres = BoxInt()
            elif rettype == 'float':
                boxres = BoxFloat()
            else:
                assert 0
            operations.append(ResOperation(opnum, boxargs, boxres))
        faildescr = BasicFailDescr(1)
        operations.append(ResOperation(rop.FINISH, [], None,
                                       descr=faildescr))
        looptoken = LoopToken()
        #
        self.cpu.compile_loop(inputargs, operations, looptoken)
        #
        for i, box in enumerate(inputargs):
            if isinstance(box, BoxInt):
                self.cpu.set_future_value_int(i, box.getint())
            elif isinstance(box, BoxFloat):
                self.cpu.set_future_value_float(i, box.getfloat())
            else:
                assert 0
        #
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 1

    def test_nan_and_infinity(self):
        if not self.cpu.supports_floats:
            py.test.skip("requires floats")

        from pypy.rlib.rarithmetic import INFINITY, NAN, isinf, isnan
        from pypy.jit.metainterp.resoperation import opname

        fzer = BoxFloat(0.0)
        fone = BoxFloat(1.0)
        fmqr = BoxFloat(-0.25)
        finf = BoxFloat(INFINITY)
        fmnf = BoxFloat(-INFINITY)
        fnan = BoxFloat(NAN)

        all_cases_unary =  [(a,)   for a in [fzer,fone,fmqr,finf,fmnf,fnan]]
        all_cases_binary = [(a, b) for a in [fzer,fone,fmqr,finf,fmnf,fnan]
                                   for b in [fzer,fone,fmqr,finf,fmnf,fnan]]
        no_zero_divison  = [(a, b) for a in [fzer,fone,fmqr,finf,fmnf,fnan]
                                   for b in [     fone,fmqr,finf,fmnf,fnan]]

        def nan_and_infinity(opnum, realoperation, testcases):
            for testcase in testcases:
                realvalues = [b.value for b in testcase]
                expected = realoperation(*realvalues)
                if isinstance(expected, float):
                    expectedtype = 'float'
                else:
                    expectedtype = 'int'
                got = self.execute_operation(opnum, list(testcase),
                                             expectedtype)
                if isnan(expected):
                    ok = isnan(got.value)
                elif isinf(expected):
                    ok = isinf(got.value)
                else:
                    ok = (got.value == expected)
                if not ok:
                    raise AssertionError("%s(%s): got %r, expected %r" % (
                        opname[opnum], ', '.join(map(repr, realvalues)),
                        got.value, expected))
                # if we expect a boolean, also check the combination with
                # a GUARD_TRUE or GUARD_FALSE
                if isinstance(expected, bool):
                    for guard_opnum, expected_id in [(rop.GUARD_TRUE, 1),
                                                     (rop.GUARD_FALSE, 0)]:
                        box = BoxInt()
                        operations = [
                            ResOperation(opnum, list(testcase), box),
                            ResOperation(guard_opnum, [box], None,
                                         descr=BasicFailDescr(4)),
                            ResOperation(rop.FINISH, [], None,
                                         descr=BasicFailDescr(5))]
                        operations[1].fail_args = []
                        looptoken = LoopToken()
                        self.cpu.compile_loop(list(testcase), operations,
                                              looptoken)
                        for i, box in enumerate(testcase):
                            self.cpu.set_future_value_float(i, box.value)
                        fail = self.cpu.execute_token(looptoken)
                        if fail.identifier != 5 - (expected_id^expected):
                            if fail.identifier == 4:
                                msg = "was taken"
                            else:
                                msg = "was not taken"
                            raise AssertionError(
                                "%s(%s)/%s took the wrong path: "
                                "the failure path of the guard %s" % (
                                    opname[opnum],
                                    ', '.join(map(repr, realvalues)),
                                    opname[guard_opnum], msg))

        yield nan_and_infinity, rop.FLOAT_ADD, operator.add, all_cases_binary
        yield nan_and_infinity, rop.FLOAT_SUB, operator.sub, all_cases_binary
        yield nan_and_infinity, rop.FLOAT_MUL, operator.mul, all_cases_binary
        yield nan_and_infinity, rop.FLOAT_TRUEDIV, \
                                           operator.truediv, no_zero_divison
        yield nan_and_infinity, rop.FLOAT_NEG, operator.neg, all_cases_unary
        yield nan_and_infinity, rop.FLOAT_ABS, abs,          all_cases_unary
        yield nan_and_infinity, rop.FLOAT_LT,  operator.lt,  all_cases_binary
        yield nan_and_infinity, rop.FLOAT_LE,  operator.le,  all_cases_binary
        yield nan_and_infinity, rop.FLOAT_EQ,  operator.eq,  all_cases_binary
        yield nan_and_infinity, rop.FLOAT_NE,  operator.ne,  all_cases_binary
        yield nan_and_infinity, rop.FLOAT_GT,  operator.gt,  all_cases_binary
        yield nan_and_infinity, rop.FLOAT_GE,  operator.ge,  all_cases_binary


class LLtypeBackendTest(BaseBackendTest):

    type_system = 'lltype'
    Ptr = lltype.Ptr
    FuncType = lltype.FuncType
    malloc = staticmethod(lltype.malloc)
    nullptr = staticmethod(lltype.nullptr)

    @classmethod
    def get_funcbox(cls, cpu, func_ptr):
        addr = llmemory.cast_ptr_to_adr(func_ptr)
        return ConstInt(heaptracker.adr2int(addr))

    
    MY_VTABLE = rclass.OBJECT_VTABLE    # for tests only

    S = lltype.GcForwardReference()
    S.become(lltype.GcStruct('S', ('parent', rclass.OBJECT),
                                  ('value', lltype.Signed),
                                  ('chr1', lltype.Char),
                                  ('chr2', lltype.Char),
                                  ('short', rffi.SHORT),
                                  ('next', lltype.Ptr(S)),
                                  ('float', lltype.Float)))
    T = lltype.GcStruct('T', ('parent', S),
                             ('next', lltype.Ptr(S)))
    U = lltype.GcStruct('U', ('parent', T),
                             ('next', lltype.Ptr(S)))


    def alloc_instance(self, T):
        vtable_for_T = lltype.malloc(self.MY_VTABLE, immortal=True)
        vtable_for_T_addr = llmemory.cast_ptr_to_adr(vtable_for_T)
        cpu = self.cpu
        if not hasattr(cpu, '_cache_gcstruct2vtable'):
            cpu._cache_gcstruct2vtable = {}
        cpu._cache_gcstruct2vtable.update({T: vtable_for_T})
        t = lltype.malloc(T)
        if T == self.T:
            t.parent.parent.typeptr = vtable_for_T
        elif T == self.U:
            t.parent.parent.parent.typeptr = vtable_for_T
        t_box = BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, t))
        T_box = ConstInt(heaptracker.adr2int(vtable_for_T_addr))
        return t_box, T_box

    def null_instance(self):
        return BoxPtr(lltype.nullptr(llmemory.GCREF.TO))

    def alloc_array_of(self, ITEM, length):
        cpu = self.cpu
        A = lltype.GcArray(ITEM)
        a = lltype.malloc(A, length)
        a_box = BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, a))
        return a_box, A

    def alloc_string(self, string):
        s = rstr.mallocstr(len(string))
        for i in range(len(string)):
            s.chars[i] = string[i]
        s_box = BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, s))
        return s_box

    def alloc_unicode(self, unicode):
        u = rstr.mallocunicode(len(unicode))
        for i in range(len(unicode)):
            u.chars[i] = unicode[i]
        u_box = BoxPtr(lltype.cast_opaque_ptr(llmemory.GCREF, u))
        return u_box


    def test_casts(self):
        py.test.skip("xxx fix or kill")
        from pypy.rpython.lltypesystem import lltype, llmemory
        TP = lltype.GcStruct('x')
        x = lltype.malloc(TP)        
        x = lltype.cast_opaque_ptr(llmemory.GCREF, x)
        res = self.execute_operation(rop.CAST_PTR_TO_INT,
                                     [BoxPtr(x)],  'int').value
        expected = self.cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(x))
        assert rffi.get_real_int(res) == rffi.get_real_int(expected)
        res = self.execute_operation(rop.CAST_PTR_TO_INT,
                                     [ConstPtr(x)],  'int').value
        expected = self.cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(x))
        assert rffi.get_real_int(res) == rffi.get_real_int(expected)

    def test_ooops_non_gc(self):
        x = lltype.malloc(lltype.Struct('x'), flavor='raw')
        v = heaptracker.adr2int(llmemory.cast_ptr_to_adr(x))
        r = self.execute_operation(rop.PTR_EQ, [BoxInt(v), BoxInt(v)], 'int')
        assert r.value == 1
        r = self.execute_operation(rop.PTR_NE, [BoxInt(v), BoxInt(v)], 'int')
        assert r.value == 0
        lltype.free(x, flavor='raw')

    def test_new_plain_struct(self):
        cpu = self.cpu
        S = lltype.GcStruct('S', ('x', lltype.Char), ('y', lltype.Char))
        sizedescr = cpu.sizeof(S)
        r1 = self.execute_operation(rop.NEW, [], 'ref', descr=sizedescr)
        r2 = self.execute_operation(rop.NEW, [], 'ref', descr=sizedescr)
        assert r1.value != r2.value
        xdescr = cpu.fielddescrof(S, 'x')
        ydescr = cpu.fielddescrof(S, 'y')
        self.execute_operation(rop.SETFIELD_GC, [r1, BoxInt(150)],
                               'void', descr=ydescr)
        self.execute_operation(rop.SETFIELD_GC, [r1, BoxInt(190)],
                               'void', descr=xdescr)
        s = lltype.cast_opaque_ptr(lltype.Ptr(S), r1.value)
        assert s.x == chr(190)
        assert s.y == chr(150)

    def test_field_raw_pure(self):
        # This is really testing the same thing as test_field_basic but can't
        # hurt...
        S = lltype.Struct('S', ('x', lltype.Signed))
        s = lltype.malloc(S, flavor='raw')
        sa = llmemory.cast_ptr_to_adr(s)
        s_box = BoxInt(heaptracker.adr2int(sa))
        for get_op, set_op in ((rop.GETFIELD_RAW, rop.SETFIELD_RAW),
                               (rop.GETFIELD_RAW_PURE, rop.SETFIELD_RAW)):
            fd = self.cpu.fielddescrof(S, 'x')
            self.execute_operation(set_op, [s_box, BoxInt(32)], 'void',
                                   descr=fd)
            res = self.execute_operation(get_op, [s_box], 'int', descr=fd)
            assert res.getint()  == 32

    def test_new_with_vtable(self):
        cpu = self.cpu
        t_box, T_box = self.alloc_instance(self.T)
        vtable = llmemory.cast_adr_to_ptr(
            llmemory.cast_int_to_adr(T_box.value), heaptracker.VTABLETYPE)
        heaptracker.register_known_gctype(cpu, vtable, self.T)
        r1 = self.execute_operation(rop.NEW_WITH_VTABLE, [T_box], 'ref')
        r2 = self.execute_operation(rop.NEW_WITH_VTABLE, [T_box], 'ref')
        assert r1.value != r2.value
        descr1 = cpu.fielddescrof(self.S, 'chr1')
        descr2 = cpu.fielddescrof(self.S, 'chr2')
        descrshort = cpu.fielddescrof(self.S, 'short')
        self.execute_operation(rop.SETFIELD_GC, [r1, BoxInt(150)],
                               'void', descr=descr2)
        self.execute_operation(rop.SETFIELD_GC, [r1, BoxInt(190)],
                               'void', descr=descr1)
        self.execute_operation(rop.SETFIELD_GC, [r1, BoxInt(1313)],
                               'void', descr=descrshort)
        s = lltype.cast_opaque_ptr(lltype.Ptr(self.T), r1.value)
        assert s.parent.chr1 == chr(190)
        assert s.parent.chr2 == chr(150)
        r = self.cpu.bh_getfield_gc_i(r1.value, descrshort)
        assert r == 1313
        self.cpu.bh_setfield_gc_i(r1.value, descrshort, 1333)
        r = self.cpu.bh_getfield_gc_i(r1.value, descrshort)
        assert r == 1333
        r = self.execute_operation(rop.GETFIELD_GC, [r1], 'int',
                                   descr=descrshort)
        assert r.value == 1333
        t = lltype.cast_opaque_ptr(lltype.Ptr(self.T), t_box.value)
        assert s.parent.parent.typeptr == t.parent.parent.typeptr

    def test_new_array(self):
        A = lltype.GcArray(lltype.Signed)
        arraydescr = self.cpu.arraydescrof(A)
        r1 = self.execute_operation(rop.NEW_ARRAY, [BoxInt(342)],
                                    'ref', descr=arraydescr)
        r2 = self.execute_operation(rop.NEW_ARRAY, [BoxInt(342)],
                                    'ref', descr=arraydescr)
        assert r1.value != r2.value
        a = lltype.cast_opaque_ptr(lltype.Ptr(A), r1.value)
        assert a[0] == 0
        assert len(a) == 342

    def test_new_string(self):
        r1 = self.execute_operation(rop.NEWSTR, [BoxInt(342)], 'ref')
        r2 = self.execute_operation(rop.NEWSTR, [BoxInt(342)], 'ref')
        assert r1.value != r2.value
        a = lltype.cast_opaque_ptr(lltype.Ptr(rstr.STR), r1.value)
        assert len(a.chars) == 342

    def test_new_unicode(self):
        r1 = self.execute_operation(rop.NEWUNICODE, [BoxInt(342)], 'ref')
        r2 = self.execute_operation(rop.NEWUNICODE, [BoxInt(342)], 'ref')
        assert r1.value != r2.value
        a = lltype.cast_opaque_ptr(lltype.Ptr(rstr.UNICODE), r1.value)
        assert len(a.chars) == 342

    def test_exceptions(self):
        exc_tp = None
        exc_ptr = None
        def func(i):
            if i:
                raise LLException(exc_tp, exc_ptr)

        ops = '''
        [i0]
        i1 = same_as(1)
        call(ConstClass(fptr), i0, descr=calldescr)
        p0 = guard_exception(ConstClass(xtp)) [i1]
        finish(0, p0)
        '''
        FPTR = lltype.Ptr(lltype.FuncType([lltype.Signed], lltype.Void))
        fptr = llhelper(FPTR, func)
        calldescr = self.cpu.calldescrof(FPTR.TO, FPTR.TO.ARGS, FPTR.TO.RESULT)

        xtp = lltype.malloc(rclass.OBJECT_VTABLE, immortal=True)
        xtp.subclassrange_min = 1
        xtp.subclassrange_max = 3
        X = lltype.GcStruct('X', ('parent', rclass.OBJECT),
                            hints={'vtable':  xtp._obj})
        xptr = lltype.cast_opaque_ptr(llmemory.GCREF, lltype.malloc(X))


        exc_tp = xtp
        exc_ptr = xptr
        loop = parse(ops, self.cpu, namespace=locals())
        self.cpu.compile_loop(loop.inputargs, loop.operations, loop.token)
        self.cpu.set_future_value_int(0, 1)
        self.cpu.execute_token(loop.token)
        assert self.cpu.get_latest_value_int(0) == 0
        assert self.cpu.get_latest_value_ref(1) == xptr
        excvalue = self.cpu.grab_exc_value()
        assert not excvalue
        self.cpu.set_future_value_int(0, 0)
        self.cpu.execute_token(loop.token)
        assert self.cpu.get_latest_value_int(0) == 1
        excvalue = self.cpu.grab_exc_value()
        assert not excvalue

        ytp = lltype.malloc(rclass.OBJECT_VTABLE, immortal=True)
        ytp.subclassrange_min = 2
        ytp.subclassrange_max = 2
        assert rclass.ll_issubclass(ytp, xtp)
        Y = lltype.GcStruct('Y', ('parent', rclass.OBJECT),
                            hints={'vtable':  ytp._obj})
        yptr = lltype.cast_opaque_ptr(llmemory.GCREF, lltype.malloc(Y))

        # guard_exception uses an exact match
        exc_tp = ytp
        exc_ptr = yptr
        loop = parse(ops, self.cpu, namespace=locals())
        self.cpu.compile_loop(loop.inputargs, loop.operations, loop.token)
        self.cpu.set_future_value_int(0, 1)
        self.cpu.execute_token(loop.token)
        assert self.cpu.get_latest_value_int(0) == 1
        excvalue = self.cpu.grab_exc_value()
        assert excvalue == yptr
        assert not self.cpu.grab_exc_value()   # cleared

        exc_tp = xtp
        exc_ptr = xptr
        ops = '''
        [i0]
        i1 = same_as(1)
        call(ConstClass(fptr), i0, descr=calldescr)
        guard_no_exception() [i1]
        finish(0)
        '''
        loop = parse(ops, self.cpu, namespace=locals())
        self.cpu.compile_loop(loop.inputargs, loop.operations, loop.token)
        self.cpu.set_future_value_int(0, 1)
        self.cpu.execute_token(loop.token)
        assert self.cpu.get_latest_value_int(0) == 1
        excvalue = self.cpu.grab_exc_value()
        assert excvalue == xptr
        self.cpu.set_future_value_int(0, 0)
        self.cpu.execute_token(loop.token)
        assert self.cpu.get_latest_value_int(0) == 0
        excvalue = self.cpu.grab_exc_value()
        assert not excvalue

    def test_cond_call_gc_wb(self):
        def func_void(a, b):
            record.append((a, b))
        record = []
        #
        S = lltype.GcStruct('S', ('tid', lltype.Signed))
        FUNC = self.FuncType([lltype.Ptr(S), lltype.Signed], lltype.Void)
        func_ptr = llhelper(lltype.Ptr(FUNC), func_void)
        funcbox = self.get_funcbox(self.cpu, func_ptr)
        class WriteBarrierDescr:
            jit_wb_if_flag = 4096
            jit_wb_if_flag_byteofs = struct.pack("i", 4096).index('\x10')
            jit_wb_if_flag_singlebyte = 0x10
            def get_write_barrier_fn(self, cpu):
                return funcbox.getint()
        #
        for cond in [False, True]:
            value = random.randrange(-sys.maxint, sys.maxint)
            if cond:
                value |= 4096
            else:
                value &= ~4096
            s = lltype.malloc(S)
            s.tid = value
            sgcref = lltype.cast_opaque_ptr(llmemory.GCREF, s)
            del record[:]
            self.execute_operation(rop.COND_CALL_GC_WB,
                                   [BoxPtr(sgcref), ConstInt(-2121)],
                                   'void', descr=WriteBarrierDescr())
            if cond:
                assert record == [(s, -2121)]
            else:
                assert record == []

    def test_force_operations_returning_void(self):
        values = []
        def maybe_force(token, flag):
            if flag:
                descr = self.cpu.force(token)
                values.append(descr)
                values.append(self.cpu.get_latest_value_int(0))
                values.append(self.cpu.get_latest_value_int(1))

        FUNC = self.FuncType([lltype.Signed, lltype.Signed], lltype.Void)
        func_ptr = llhelper(lltype.Ptr(FUNC), maybe_force)
        funcbox = self.get_funcbox(self.cpu, func_ptr).constbox()
        calldescr = self.cpu.calldescrof(FUNC, FUNC.ARGS, FUNC.RESULT)
        cpu = self.cpu
        i0 = BoxInt()
        i1 = BoxInt()
        tok = BoxInt()
        faildescr = BasicFailDescr(1)
        ops = [
        ResOperation(rop.FORCE_TOKEN, [], tok),
        ResOperation(rop.CALL_MAY_FORCE, [funcbox, tok, i1], None,
                     descr=calldescr),
        ResOperation(rop.GUARD_NOT_FORCED, [], None, descr=faildescr),
        ResOperation(rop.FINISH, [i0], None, descr=BasicFailDescr(0))
        ]
        ops[2].fail_args = [i1, i0]
        looptoken = LoopToken()
        self.cpu.compile_loop([i0, i1], ops, looptoken)
        self.cpu.set_future_value_int(0, 20)
        self.cpu.set_future_value_int(1, 0)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 0
        assert self.cpu.get_latest_value_int(0) == 20
        assert values == []

        self.cpu.set_future_value_int(0, 10)
        self.cpu.set_future_value_int(1, 1)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 1
        assert self.cpu.get_latest_value_int(0) == 1
        assert self.cpu.get_latest_value_int(1) == 10
        assert values == [faildescr, 1, 10]

    def test_force_operations_returning_int(self):
        values = []
        def maybe_force(token, flag):
            if flag:
               self.cpu.force(token)
               values.append(self.cpu.get_latest_value_int(0))
               values.append(self.cpu.get_latest_value_int(2))
            return 42

        FUNC = self.FuncType([lltype.Signed, lltype.Signed], lltype.Signed)
        func_ptr = llhelper(lltype.Ptr(FUNC), maybe_force)
        funcbox = self.get_funcbox(self.cpu, func_ptr).constbox()
        calldescr = self.cpu.calldescrof(FUNC, FUNC.ARGS, FUNC.RESULT)
        cpu = self.cpu
        i0 = BoxInt()
        i1 = BoxInt()
        i2 = BoxInt()
        tok = BoxInt()
        faildescr = BasicFailDescr(1)
        ops = [
        ResOperation(rop.FORCE_TOKEN, [], tok),
        ResOperation(rop.CALL_MAY_FORCE, [funcbox, tok, i1], i2,
                     descr=calldescr),
        ResOperation(rop.GUARD_NOT_FORCED, [], None, descr=faildescr),
        ResOperation(rop.FINISH, [i2], None, descr=BasicFailDescr(0))
        ]
        ops[2].fail_args = [i1, i2, i0]
        looptoken = LoopToken()
        self.cpu.compile_loop([i0, i1], ops, looptoken)
        self.cpu.set_future_value_int(0, 20)
        self.cpu.set_future_value_int(1, 0)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 0
        assert self.cpu.get_latest_value_int(0) == 42
        assert values == []

        self.cpu.set_future_value_int(0, 10)
        self.cpu.set_future_value_int(1, 1)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 1
        assert self.cpu.get_latest_value_int(0) == 1
        assert self.cpu.get_latest_value_int(1) == 42
        assert self.cpu.get_latest_value_int(2) == 10
        assert values == [1, 10]

    def test_force_operations_returning_float(self):
        values = []
        def maybe_force(token, flag):
            if flag:
               self.cpu.force(token)
               values.append(self.cpu.get_latest_value_int(0))
               values.append(self.cpu.get_latest_value_int(2))
            return 42.5

        FUNC = self.FuncType([lltype.Signed, lltype.Signed], lltype.Float)
        func_ptr = llhelper(lltype.Ptr(FUNC), maybe_force)
        funcbox = self.get_funcbox(self.cpu, func_ptr).constbox()
        calldescr = self.cpu.calldescrof(FUNC, FUNC.ARGS, FUNC.RESULT)
        cpu = self.cpu
        i0 = BoxInt()
        i1 = BoxInt()
        f2 = BoxFloat()
        tok = BoxInt()
        faildescr = BasicFailDescr(1)
        ops = [
        ResOperation(rop.FORCE_TOKEN, [], tok),
        ResOperation(rop.CALL_MAY_FORCE, [funcbox, tok, i1], f2,
                     descr=calldescr),
        ResOperation(rop.GUARD_NOT_FORCED, [], None, descr=faildescr),
        ResOperation(rop.FINISH, [f2], None, descr=BasicFailDescr(0))
        ]
        ops[2].fail_args = [i1, f2, i0]
        looptoken = LoopToken()
        self.cpu.compile_loop([i0, i1], ops, looptoken)
        self.cpu.set_future_value_int(0, 20)
        self.cpu.set_future_value_int(1, 0)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 0
        assert self.cpu.get_latest_value_float(0) == 42.5
        assert values == []

        self.cpu.set_future_value_int(0, 10)
        self.cpu.set_future_value_int(1, 1)
        fail = self.cpu.execute_token(looptoken)
        assert fail.identifier == 1
        assert self.cpu.get_latest_value_int(0) == 1
        assert self.cpu.get_latest_value_float(1) == 42.5
        assert self.cpu.get_latest_value_int(2) == 10
        assert values == [1, 10]

    # pure do_ / descr features

    def test_do_operations(self):
        cpu = self.cpu
        #
        A = lltype.GcArray(lltype.Char)
        descr_A = cpu.arraydescrof(A)
        a = lltype.malloc(A, 5)
        x = cpu.bh_arraylen_gc(descr_A,
                               lltype.cast_opaque_ptr(llmemory.GCREF, a))
        assert x == 5
        #
        a[2] = 'Y'
        x = cpu.bh_getarrayitem_gc_i(
            descr_A, lltype.cast_opaque_ptr(llmemory.GCREF, a), 2)
        assert x == ord('Y')
        #
        B = lltype.GcArray(lltype.Ptr(A))
        descr_B = cpu.arraydescrof(B)
        b = lltype.malloc(B, 4)
        b[3] = a
        x = cpu.bh_getarrayitem_gc_r(
            descr_B, lltype.cast_opaque_ptr(llmemory.GCREF, b), 3)
        assert lltype.cast_opaque_ptr(lltype.Ptr(A), x) == a
        if self.cpu.supports_floats:
            C = lltype.GcArray(lltype.Float)
            c = lltype.malloc(C, 6)
            c[3] = 3.5
            descr_C = cpu.arraydescrof(C)
            x = cpu.bh_getarrayitem_gc_f(
                descr_C, lltype.cast_opaque_ptr(llmemory.GCREF, c), 3)
            assert x == 3.5
            cpu.bh_setarrayitem_gc_f(
                descr_C, lltype.cast_opaque_ptr(llmemory.GCREF, c), 4, 4.5)
            assert c[4] == 4.5
        s = rstr.mallocstr(6)
        x = cpu.bh_strlen(lltype.cast_opaque_ptr(llmemory.GCREF, s))
        assert x == 6
        #
        s.chars[3] = 'X'
        x = cpu.bh_strgetitem(lltype.cast_opaque_ptr(llmemory.GCREF, s), 3)
        assert x == ord('X')
        #
        S = lltype.GcStruct('S', ('x', lltype.Char), ('y', lltype.Ptr(A)),
                            ('z', lltype.Float))
        descrfld_x = cpu.fielddescrof(S, 'x')
        s = lltype.malloc(S)
        s.x = 'Z'
        x = cpu.bh_getfield_gc_i(lltype.cast_opaque_ptr(llmemory.GCREF, s),
                                 descrfld_x)
        assert x == ord('Z')
        #
        cpu.bh_setfield_gc_i(lltype.cast_opaque_ptr(llmemory.GCREF, s),
                             descrfld_x,
                             ord('4'))
        assert s.x == '4'
        #
        descrfld_y = cpu.fielddescrof(S, 'y')
        s.y = a
        x = cpu.bh_getfield_gc_r(lltype.cast_opaque_ptr(llmemory.GCREF, s),
                                 descrfld_y)
        assert lltype.cast_opaque_ptr(lltype.Ptr(A), x) == a
        #
        s.y = lltype.nullptr(A)
        cpu.bh_setfield_gc_r(lltype.cast_opaque_ptr(llmemory.GCREF, s),
                             descrfld_y, x)
        assert s.y == a
        #
        RS = lltype.Struct('S', ('x', lltype.Char))  #, ('y', lltype.Ptr(A)))
        descrfld_rx = cpu.fielddescrof(RS, 'x')
        rs = lltype.malloc(RS, immortal=True)
        rs.x = '?'
        x = cpu.bh_getfield_raw_i(
            heaptracker.adr2int(llmemory.cast_ptr_to_adr(rs)),
            descrfld_rx)
        assert x == ord('?')
        #
        cpu.bh_setfield_raw_i(
            heaptracker.adr2int(llmemory.cast_ptr_to_adr(rs)),
            descrfld_rx, ord('!'))
        assert rs.x == '!'
        #

        if self.cpu.supports_floats:
            descrfld_z = cpu.fielddescrof(S, 'z')
            cpu.bh_setfield_gc_f(
                lltype.cast_opaque_ptr(llmemory.GCREF, s),
                descrfld_z, 3.5)
            assert s.z == 3.5
            s.z = 3.2
            x = cpu.bh_getfield_gc_f(
                lltype.cast_opaque_ptr(llmemory.GCREF, s),
                descrfld_z)
            assert x == 3.2
        ### we don't support in the JIT for now GC pointers
        ### stored inside non-GC structs.
        #descrfld_ry = cpu.fielddescrof(RS, 'y')
        #rs.y = a
        #x = cpu.do_getfield_raw(
        #    BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(rs))),
        #    descrfld_ry)
        #assert isinstance(x, BoxPtr)
        #assert x.getref(lltype.Ptr(A)) == a
        #
        #rs.y = lltype.nullptr(A)
        #cpu.do_setfield_raw(
        #    BoxInt(cpu.cast_adr_to_int(llmemory.cast_ptr_to_adr(rs))), x,
        #    descrfld_ry)
        #assert rs.y == a
        #
        descrsize = cpu.sizeof(S)
        x = cpu.bh_new(descrsize)
        lltype.cast_opaque_ptr(lltype.Ptr(S), x)    # type check
        #
        descrsize2 = cpu.sizeof(rclass.OBJECT)
        vtable2 = lltype.malloc(rclass.OBJECT_VTABLE, immortal=True)
        vtable2_int = heaptracker.adr2int(llmemory.cast_ptr_to_adr(vtable2))
        heaptracker.register_known_gctype(cpu, vtable2, rclass.OBJECT)
        x = cpu.bh_new_with_vtable(descrsize2, vtable2_int)
        lltype.cast_opaque_ptr(lltype.Ptr(rclass.OBJECT), x)    # type check
        # well...
        #assert x.getref(rclass.OBJECTPTR).typeptr == vtable2
        #
        arraydescr = cpu.arraydescrof(A)
        x = cpu.bh_new_array(arraydescr, 7)
        array = lltype.cast_opaque_ptr(lltype.Ptr(A), x)
        assert len(array) == 7
        #
        cpu.bh_setarrayitem_gc_i(descr_A, x, 5, ord('*'))
        assert array[5] == '*'
        #
        cpu.bh_setarrayitem_gc_r(
            descr_B, lltype.cast_opaque_ptr(llmemory.GCREF, b), 1, x)
        assert b[1] == array
        #
        x = cpu.bh_newstr(5)
        str = lltype.cast_opaque_ptr(lltype.Ptr(rstr.STR), x)
        assert len(str.chars) == 5
        #
        cpu.bh_strsetitem(x, 4, ord('/'))
        assert str.chars[4] == '/'
        #
##        x = cpu.bh_newstr(5)
##        y = cpu.bh_cast_ptr_to_int(x)
##        z = cpu.bh_cast_ptr_to_int(x)
##        y = rffi.get_real_int(y)
##        z = rffi.get_real_int(z)
##        assert type(y) == type(z) == int and y == z

    def test_sorting_of_fields(self):
        S = self.S
        value = self.cpu.fielddescrof(S, 'value').sort_key()
        chr1 = self.cpu.fielddescrof(S, 'chr1').sort_key()
        chr2 = self.cpu.fielddescrof(S, 'chr2').sort_key()
        assert (sorted([chr2, chr1, value]) ==
                [value, chr1, chr2])
        assert len(dict.fromkeys([value, chr1, chr2]).keys()) == 3

    def test_guards_nongc(self):
        x = lltype.malloc(lltype.Struct('x'), flavor='raw')
        v = heaptracker.adr2int(llmemory.cast_ptr_to_adr(x))
        vbox = BoxInt(v)
        ops = [
            (rop.GUARD_NONNULL, vbox, False),
            (rop.GUARD_ISNULL, vbox, True),
            (rop.GUARD_NONNULL, BoxInt(0), True),
            (rop.GUARD_ISNULL, BoxInt(0), False),
            ]
        for opname, arg, res in ops:
            self.execute_operation(opname, [arg], 'void')
            assert self.guard_failed == res
        
        lltype.free(x, flavor='raw')

    def test_assembler_call(self):
        called = []
        def assembler_helper(failindex, virtualizable):
            assert self.cpu.get_latest_value_int(0) == 10
            called.append(failindex)
            return 4 + 9

        FUNCPTR = lltype.Ptr(lltype.FuncType([lltype.Signed, llmemory.GCREF],
                                             lltype.Signed))
        class FakeJitDriverSD:
            index_of_virtualizable = -1
            _assembler_helper_ptr = llhelper(FUNCPTR, assembler_helper)
            assembler_helper_adr = llmemory.cast_ptr_to_adr(
                _assembler_helper_ptr)

        ops = '''
        [i0, i1]
        i2 = int_add(i0, i1)
        finish(i2)'''
        loop = parse(ops)
        looptoken = LoopToken()
        looptoken.outermost_jitdriver_sd = FakeJitDriverSD()
        self.cpu.compile_loop(loop.inputargs, loop.operations, looptoken)
        ARGS = [lltype.Signed, lltype.Signed]
        RES = lltype.Signed
        self.cpu.portal_calldescr = self.cpu.calldescrof(
            lltype.Ptr(lltype.FuncType(ARGS, RES)), ARGS, RES)
        self.cpu.set_future_value_int(0, 1)
        self.cpu.set_future_value_int(1, 2)
        res = self.cpu.execute_token(looptoken)
        assert self.cpu.get_latest_value_int(0) == 3
        ops = '''
        [i4, i5]
        i6 = int_add(i4, 1)
        i3 = call_assembler(i6, i5, descr=looptoken)
        guard_not_forced()[]
        finish(i3)
        '''
        loop = parse(ops, namespace=locals())
        othertoken = LoopToken()
        self.cpu.compile_loop(loop.inputargs, loop.operations, othertoken)
        self.cpu.set_future_value_int(0, 4)
        self.cpu.set_future_value_int(1, 5)
        res = self.cpu.execute_token(othertoken)
        assert self.cpu.get_latest_value_int(0) == 13
        assert called

    def test_assembler_call_float(self):
        called = []
        def assembler_helper(failindex, virtualizable):
            assert self.cpu.get_latest_value_float(0) == 1.2 + 3.2
            called.append(failindex)
            return 13.5

        FUNCPTR = lltype.Ptr(lltype.FuncType([lltype.Signed, llmemory.GCREF],
                                             lltype.Float))
        class FakeJitDriverSD:
            index_of_virtualizable = -1
            _assembler_helper_ptr = llhelper(FUNCPTR, assembler_helper)
            assembler_helper_adr = llmemory.cast_ptr_to_adr(
                _assembler_helper_ptr)

        ARGS = [lltype.Float, lltype.Float]
        RES = lltype.Float
        self.cpu.portal_calldescr = self.cpu.calldescrof(
            lltype.Ptr(lltype.FuncType(ARGS, RES)), ARGS, RES)
        
        ops = '''
        [f0, f1]
        f2 = float_add(f0, f1)
        finish(f2)'''
        loop = parse(ops)
        looptoken = LoopToken()
        looptoken.outermost_jitdriver_sd = FakeJitDriverSD()
        self.cpu.compile_loop(loop.inputargs, loop.operations, looptoken)
        self.cpu.set_future_value_float(0, 1.2)
        self.cpu.set_future_value_float(1, 2.3)
        res = self.cpu.execute_token(looptoken)
        assert self.cpu.get_latest_value_float(0) == 1.2 + 2.3
        ops = '''
        [f4, f5]
        f3 = call_assembler(f4, f5, descr=looptoken)
        guard_not_forced()[]
        finish(f3)
        '''
        loop = parse(ops, namespace=locals())
        othertoken = LoopToken()
        self.cpu.compile_loop(loop.inputargs, loop.operations, othertoken)
        self.cpu.set_future_value_float(0, 1.2)
        self.cpu.set_future_value_float(1, 3.2)
        res = self.cpu.execute_token(othertoken)
        assert self.cpu.get_latest_value_float(0) == 13.5
        assert called

class OOtypeBackendTest(BaseBackendTest):

    type_system = 'ootype'
    Ptr = staticmethod(lambda x: x)
    FuncType = ootype.StaticMethod
    malloc = staticmethod(ootype.new)
    nullptr = staticmethod(ootype.null)

    def setup_class(cls):
        py.test.skip("ootype tests skipped")

    @classmethod
    def get_funcbox(cls, cpu, func_ptr):
        return BoxObj(ootype.cast_to_object(func_ptr))

    S = ootype.Instance('S', ootype.ROOT, {'value': ootype.Signed,
                                           'chr1': ootype.Char,
                                           'chr2': ootype.Char})
    S._add_fields({'next': S})
    T = ootype.Instance('T', S)
    U = ootype.Instance('U', T)

    def alloc_instance(self, T):
        t = ootype.new(T)
        cls = ootype.classof(t)
        t_box = BoxObj(ootype.cast_to_object(t))
        T_box = ConstObj(ootype.cast_to_object(cls))
        return t_box, T_box

    def null_instance(self):
        return BoxObj(ootype.NULL)

    def alloc_array_of(self, ITEM, length):
        py.test.skip("implement me")

    def alloc_string(self, string):
        py.test.skip("implement me")

    def alloc_unicode(self, unicode):
        py.test.skip("implement me")
    
