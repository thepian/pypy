from pypy.interpreter.error import OperationError
from pypy.interpreter.gateway import app2interp_temp
from pypy.interpreter.argument import Arguments
from pypy.interpreter.pycode import PyCode
from pypy.interpreter.pyframe import PyFrame
from pypy.tool.pytest.appsupport import AppFrame, build_pytest_assertion, AppExceptionInfo
import py
from pypy.tool.udir import udir
import os
import sys
import pypy
conftestpath = py.path.local(pypy.__file__).dirpath("conftest.py")

pytest_plugins = "pytest_pytester"

def somefunc(x):
    print x

def test_AppFrame(space):
    import sys
    co = PyCode._from_code(space, somefunc.func_code)
    pyframe = PyFrame(space, co, space.newdict(), None)
    runner = AppFrame(space, pyframe)
    py.code._reinterpret_old("f = lambda x: x+1", runner, should_fail=False)
    msg = py.code._reinterpret_old("assert isinstance(f(2), float)", runner)
    assert msg.startswith("assert isinstance(3, float)\n"
                          " +  where 3 = ")


def test_myexception(space):
    def app_test_func():
        x = 6*7
        assert x == 43
    t = app2interp_temp(app_test_func)
    f = t.get_function(space)
    space.setitem(space.builtin.w_dict, space.wrap('AssertionError'), 
                  build_pytest_assertion(space))
    try:
        f.call_args(Arguments(None, []))
    except OperationError, e:
        assert e.match(space, space.w_AssertionError)
        assert space.unwrap(space.str(e.get_w_value(space))) == 'assert 42 == 43'
    else:
        assert False, "got no exception!"

def app_test_exception(): 
    try: 
        raise AssertionError("42")
    except AssertionError: 
        pass 
    else: 
        raise AssertionError, "app level AssertionError mixup!"
    
def app_test_exception_with_message():
    try:
        assert 0, "Failed"
    except AssertionError, e:
        assert e.msg == "Failed"


def test_appexecinfo(space): 
    try: 
        space.appexec([], "(): raise ValueError") 
    except OperationError, e: 
        appex = AppExceptionInfo(space, e)
    else: 
        py.test.fail("did not raise!") 
    assert appex.exconly().find('ValueError') != -1 
    assert appex.exconly(tryshort=True).find('ValueError') != -1 
    assert appex.errisinstance(ValueError) 
    assert not appex.errisinstance(RuntimeError) 
    class A: 
        pass
    assert not appex.errisinstance(A) 


def test_fakedexception(space):
    from cPickle import PicklingError
    def raise_error():
        raise PicklingError("SomeMessage")
    space.setitem(space.builtin.w_dict, space.wrap('raise_error'),
                  space.wrap(raise_error))
    
    try:
        space.appexec([], "(): raise_error()")
    except OperationError, e:
        appex = AppExceptionInfo(space, e)
    else:
        py.test.fail("did not raise!")
    assert "PicklingError" in appex.exconly()

class AppTestWithWrappedInterplevelAttributes: 
    def setup_class(cls): 
        space = cls.space
        cls.w_some1 = space.wrap(42) 

    def setup_method(self, meth): 
        self.w_some2 = self.space.wrap(23)

    def test_values_arrive(self): 
        assert self.some1 == 42  
        assert self.some2 == 23 

    def test_values_arrive2(self): 
        assert self.some1 == 42

def test_expectcollect(testdir):
    py.test.importorskip("pexpect")
    conftestpath.copy(testdir.tmpdir)
    sorter = testdir.inline_runsource("""
        class ExpectTestOne:
            def test_one(self):
                pass
    """)
    passed, skipped, failed = sorter.countoutcomes()
    assert passed == 1

def test_safename():
    from pypy.conftest import ExpectTestMethod

    safe_name = ExpectTestMethod.safe_name
    assert safe_name(['pypy', 'tool', 'test', 'test_pytestsupport.py',
                      'ExpectTest', '()', 'test_one']) == \
           'pypy_tool_test_test_pytestsupport_ExpectTest_paren_test_one'

def test_safe_filename(testdir):
    py.test.importorskip("pexpect")
    conftestpath.copy(testdir.tmpdir)
    sorter = testdir.inline_runsource("""
        class ExpectTestOne:
            def test_one(self):
                pass
    """)
    ev, = sorter.getreports("pytest_runtest_logreport")
    assert ev.passed 
    sfn = ev.item.safe_filename()
    print sfn
    assert sfn == 'test_safe_filename_test_safe_filename_ExpectTestOne_paren_test_one_1.py'

class ExpectTest:
    def test_one(self):
        import os
        import sys
        assert os.ttyname(sys.stdin.fileno())

    def test_two(self):
        import pypy

def test_app_test_blow(testdir):
    conftestpath.copy(testdir.tmpdir)
    sorter = testdir.inline_runsource("""class AppTestBlow:
    def test_one(self): exec 'blow'
    """)

    ev, = sorter.getreports("pytest_runtest_logreport")
    assert ev.failed
    assert 'NameError' in ev.longrepr.reprcrash.message
    assert 'blow' in ev.longrepr.reprcrash.message    
