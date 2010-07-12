import py
from pypy.module.sys.state import getinitialpath
from pypy.module.sys.version import PYPY_VERSION, CPYTHON_VERSION

def build_hierarchy(prefix):
    dirname = '%d.%d.%d' % (CPYTHON_VERSION[0],
                            CPYTHON_VERSION[1],
                            CPYTHON_VERSION[2])
    a = prefix.join('lib_pypy').ensure(dir=1)
    b = prefix.join('lib-python', 'modified-%s' % dirname).ensure(dir=1)
    c = prefix.join('lib-python', dirname).ensure(dir=1)
    return a, b, c


def test_stdlib_in_prefix(tmpdir):
    dirs = build_hierarchy(tmpdir)
    path = getinitialpath(str(tmpdir))
    assert path == map(str, dirs)
