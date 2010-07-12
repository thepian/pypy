import sys
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.objspace.std.intobject import W_IntObject
from pypy.objspace.std.longobject import W_LongObject
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase


class TestLongObject(BaseApiTest):
    def test_FromLong(self, space, api):
        value = api.PyLong_FromLong(3)
        assert isinstance(value, W_LongObject)
        assert space.unwrap(value) == 3

        value = api.PyLong_FromLong(sys.maxint + 1)
        assert isinstance(value, W_LongObject)
        assert space.unwrap(value) == sys.maxint + 1 # should obviously fail but doesnt

    def test_aslong(self, space, api):
        w_value = api.PyLong_FromLong((sys.maxint - 1) / 2)

        w_value = space.mul(w_value, space.wrap(2))
        value = api.PyLong_AsLong(w_value)
        assert value == (sys.maxint - 1)

        w_value = space.mul(w_value, space.wrap(2))

        value = api.PyLong_AsLong(w_value)
        assert value == -1 and api.PyErr_Occurred() is space.w_OverflowError
        api.PyErr_Clear()
        value = api.PyLong_AsUnsignedLong(w_value)
        assert value == (sys.maxint - 1) * 2

    def test_fromdouble(self, space, api):
        w_value = api.PyLong_FromDouble(-12.74)
        assert space.unwrap(w_value) == -12
        assert api.PyLong_AsDouble(w_value) == -12

    def test_type_check(self, space, api):
        w_l = space.wrap(sys.maxint + 1)
        assert api.PyLong_Check(w_l)
        assert api.PyLong_CheckExact(w_l)
        
        w_i = space.wrap(sys.maxint)
        assert not api.PyLong_Check(w_i)
        assert not api.PyLong_CheckExact(w_i)
        
        L = space.appexec([], """():
            class L(long):
                pass
            return L
        """)
        l = space.call_function(L)
        assert api.PyLong_Check(l)
        assert not api.PyLong_CheckExact(l)

    def test_as_longlong(self, space, api):
        assert api.PyLong_AsLongLong(space.wrap(1<<62)) == 1<<62
        assert api.PyLong_AsLongLong(space.wrap(1<<63)) == -1
        api.PyErr_Clear()

        assert api.PyLong_AsUnsignedLongLong(space.wrap(1<<63)) == 1<<63
        assert api.PyLong_AsUnsignedLongLong(space.wrap(1<<64)) == (1<<64) - 1
        assert api.PyErr_Occurred()
        api.PyErr_Clear()

    def test_as_voidptr(self, space, api):
        w_l = api.PyLong_FromVoidPtr(lltype.nullptr(rffi.VOIDP.TO))
        assert space.unwrap(w_l) == 0L
        assert api.PyLong_AsVoidPtr(w_l) == lltype.nullptr(rffi.VOIDP_real.TO)

class AppTestLongObject(AppTestCpythonExtensionBase):
    def test_fromunsignedlong(self):
        module = self.import_extension('foo', [
            ("from_unsignedlong", "METH_NOARGS",
             """
                 return PyLong_FromUnsignedLong((unsigned long)-1);
             """)])
        import sys
        assert module.from_unsignedlong() == 2 * sys.maxint + 1

    def test_fromlonglong(self):
        module = self.import_extension('foo', [
            ("from_longlong", "METH_NOARGS",
             """
                 return PyLong_FromLongLong((long long)-1);
             """),
            ("from_unsignedlonglong", "METH_NOARGS",
             """
                 return PyLong_FromUnsignedLongLong((unsigned long long)-1);
             """)])
        assert module.from_longlong() == -1
        assert module.from_unsignedlonglong() == (1<<64) - 1

    def test_fromstring(self):
        module = self.import_extension('foo', [
            ("from_string", "METH_NOARGS",
             """
                 return PyLong_FromString("0x1234", NULL, 0);
             """),
            ])
        assert module.from_string() == 0x1234
