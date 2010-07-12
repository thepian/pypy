from pypy.rpython.lltypesystem import rffi, lltype
from pypy.interpreter.error import OperationError
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext import sequence
import py.test

class TestSequence(BaseApiTest):
    def test_sequence(self, space, api):
        w_t = space.wrap((1, 2, 3, 4))
        assert api.PySequence_Fast(w_t, "message") is w_t
        w_l = space.wrap([1, 2, 3, 4])
        assert api.PySequence_Fast(w_l, "message") is w_l

        assert space.int_w(api.PySequence_Fast_GET_ITEM(w_l, 1)) == 2
        assert api.PySequence_Fast_GET_SIZE(w_l) == 4

        w_set = space.wrap(set((1, 2, 3, 4)))
        w_seq = api.PySequence_Fast(w_set, "message")
        assert space.type(w_seq) is space.w_tuple
        assert space.int_w(space.len(w_seq)) == 4

        w_seq = api.PySequence_Tuple(w_set)
        assert space.type(w_seq) is space.w_tuple
        assert sorted(space.unwrap(w_seq)) == [1, 2, 3, 4]

        w_seq = api.PySequence_List(w_set)
        assert space.type(w_seq) is space.w_list
        assert sorted(space.unwrap(w_seq)) == [1, 2, 3, 4]

    def test_repeat(self, space, api):
        def test(seq, count):
            w_seq = space.wrap(seq)
            w_repeated = api.PySequence_Repeat(w_seq, count)
            assert space.eq_w(w_repeated, space.wrap(seq * count))

        test((1, 2, 3, 4), 3)
        test([1, 2, 3, 4], 3)

    def test_concat(self, space, api):
        w_t1 = space.wrap(range(4))
        w_t2 = space.wrap(range(4, 8))
        assert space.unwrap(api.PySequence_Concat(w_t1, w_t2)) == range(8)

    def test_exception(self, space, api):
        message = rffi.str2charp("message")
        assert not api.PySequence_Fast(space.wrap(3), message)
        assert api.PyErr_Occurred() is space.w_TypeError
        api.PyErr_Clear()

        exc = raises(OperationError, sequence.PySequence_Fast,
                     space, space.wrap(3), message)
        assert exc.value.match(space, space.w_TypeError)
        assert space.str_w(exc.value.get_w_value(space)) == "message"
        rffi.free_charp(message)
    
    def test_get_slice(self, space, api):
        w_t = space.wrap([1, 2, 3, 4, 5])
        assert space.unwrap(api.PySequence_GetSlice(w_t, 2, 4)) == [3, 4]
        assert space.unwrap(api.PySequence_GetSlice(w_t, 1, -1)) == [2, 3, 4]

        assert api.PySequence_DelSlice(w_t, 1, 4) == 0
        assert space.eq_w(w_t, space.wrap([1, 5]))
        assert api.PySequence_SetSlice(w_t, 1, 1, space.wrap((3,))) == 0
        assert space.eq_w(w_t, space.wrap([1, 3, 5]))

    def test_iter(self, space, api):
        w_t = space.wrap((1, 2))
        w_iter = api.PySeqIter_New(w_t)
        assert space.unwrap(space.next(w_iter)) == 1
        assert space.unwrap(space.next(w_iter)) == 2
        exc = raises(OperationError, space.next, w_iter)
        assert exc.value.match(space, space.w_StopIteration)
