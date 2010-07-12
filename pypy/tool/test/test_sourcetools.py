from pypy.tool.sourcetools import func_with_new_name, func_renamer

def test_rename():
    def f(x, y=5):
        return x + y
    f.prop = int

    g = func_with_new_name(f, "g")
    assert g(4, 5) == 9
    assert g.func_name == "g"
    assert f.func_defaults == (5,)
    assert g.prop is int

def test_rename_decorator():
    @func_renamer("g")
    def f(x, y=5):
        return x + y
    f.prop = int

    assert f(4, 5) == 9

    assert f.func_name == "g"
    assert f.func_defaults == (5,)
    assert f.prop is int
