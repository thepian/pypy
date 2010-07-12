from pypy.interpreter.error import OperationError
from pypy.objspace.std.dictmultiobject import \
     W_DictMultiObject, setitem__DictMulti_ANY_ANY, getitem__DictMulti_ANY, \
     StrDictImplementation

from pypy.objspace.std.celldict import ModuleDictImplementation
from pypy.objspace.std.sharingdict import SharedDictImplementation
from pypy.conftest import gettestobjspace


class TestW_DictObject:

    def setup_class(cls):
        cls.space = gettestobjspace()

    def test_empty(self):
        space = self.space
        d = self.space.newdict()
        assert not self.space.is_true(d)

    def test_nonempty(self):
        space = self.space
        wNone = space.w_None
        d = self.space.newdict()
        d.initialize_content([(wNone, wNone)])
        assert space.is_true(d)
        i = space.getitem(d, wNone)
        equal = space.eq(i, wNone)
        assert space.is_true(equal)

    def test_setitem(self):
        space = self.space
        wk1 = space.wrap('key')
        wone = space.wrap(1)
        d = self.space.newdict()
        d.initialize_content([(space.wrap('zero'),space.wrap(0))])
        space.setitem(d,wk1,wone)
        wback = space.getitem(d,wk1)
        assert self.space.eq_w(wback,wone)

    def test_delitem(self):
        space = self.space
        wk1 = space.wrap('key')
        d = self.space.newdict()
        d.initialize_content( [(space.wrap('zero'),space.wrap(0)),
                               (space.wrap('one'),space.wrap(1)),
                               (space.wrap('two'),space.wrap(2))])
        space.delitem(d,space.wrap('one'))
        assert self.space.eq_w(space.getitem(d,space.wrap('zero')),space.wrap(0))
        assert self.space.eq_w(space.getitem(d,space.wrap('two')),space.wrap(2))
        self.space.raises_w(self.space.w_KeyError,
                            space.getitem,d,space.wrap('one'))

    def test_wrap_dict(self):
        assert isinstance(self.space.wrap({}), W_DictMultiObject)


    def test_dict_compare(self):
        w = self.space.wrap
        w0, w1, w2, w3 = map(w, range(4))
        def wd(items):
            d = self.space.newdict()
            d.initialize_content(items)
            return d
        wd1 = wd([(w0, w1), (w2, w3)])
        wd2 = wd([(w2, w3), (w0, w1)])
        assert self.space.eq_w(wd1, wd2)
        wd3 = wd([(w2, w2), (w0, w1)])
        assert not self.space.eq_w(wd1, wd3)
        wd4 = wd([(w3, w3), (w0, w1)])
        assert not self.space.eq_w(wd1, wd4)
        wd5 = wd([(w3, w3)])
        assert not self.space.eq_w(wd1, wd4)

    def test_dict_call(self):
        space = self.space
        w = space.wrap
        def wd(items):
            d = space.newdict()
            d.initialize_content(items)
            return d
        def mydict(w_args=w(()), w_kwds=w({})):
            return space.call(space.w_dict, w_args, w_kwds)
        def deepwrap(lp):
            return [[w(a),w(b)] for a,b in lp]
        d = mydict()
        assert self.space.eq_w(d, w({}))
        args = w(([['a',2],[23,45]],))
        d = mydict(args)
        assert self.space.eq_w(d, wd(deepwrap([['a',2],[23,45]])))
        d = mydict(args, w({'a':33, 'b':44}))
        assert self.space.eq_w(d, wd(deepwrap([['a',33],['b',44],[23,45]])))
        d = mydict(w_kwds=w({'a':33, 'b':44}))
        assert self.space.eq_w(d, wd(deepwrap([['a',33],['b',44]])))
        self.space.raises_w(space.w_TypeError, mydict, w((23,)))
        self.space.raises_w(space.w_ValueError, mydict, w(([[1,2,3]],)))

    def test_dict_pop(self):
        space = self.space
        w = space.wrap
        def mydict(w_args=w(()), w_kwds=w({})):
            return space.call(space.w_dict, w_args, w_kwds)
        d = mydict(w_kwds=w({"1":2, "3":4}))
        dd = mydict(w_kwds=w({"1":2, "3":4})) # means d.copy()
        pop = space.getattr(dd, w("pop"))
        result = space.call_function(pop, w("1"))
        assert self.space.eq_w(result, w(2))
        assert self.space.eq_w(space.len(dd), w(1))

        dd = mydict(w_kwds=w({"1":2, "3":4})) # means d.copy()
        pop = space.getattr(dd, w("pop"))
        result = space.call_function(pop, w("1"), w(44))
        assert self.space.eq_w(result, w(2))
        assert self.space.eq_w(space.len(dd), w(1))
        result = space.call_function(pop, w("1"), w(44))
        assert self.space.eq_w(result, w(44))
        assert self.space.eq_w(space.len(dd), w(1))

        self.space.raises_w(space.w_KeyError, space.call_function, pop, w(33))

    def test_get(self):
        space = self.space
        w = space.wrap
        def mydict(w_args=w(()), w_kwds=w({})):
            return space.call(space.w_dict, w_args, w_kwds)
        d = mydict(w_kwds=w({"1":2, "3":4}))
        get = space.getattr(d, w("get"))
        assert self.space.eq_w(space.call_function(get, w("1")), w(2))
        assert self.space.eq_w(space.call_function(get, w("1"), w(44)), w(2))
        assert self.space.eq_w(space.call_function(get, w("33")), w(None))
        assert self.space.eq_w(space.call_function(get, w("33"), w(44)), w(44))

    def test_initialize_from_strdict_shared(self):
        space = self.space
        w = space.wrap
        d = {"a": w(1), "b": w(2)}
        w_d = space.newdict(from_strdict_shared=d)
        assert self.space.eq_w(space.getitem(w_d, w("a")), w(1))
        assert self.space.eq_w(space.getitem(w_d, w("b")), w(2))
        
    def test_initialize_from_strdict_really_shared(self):
        space = self.space
        w = space.wrap
        d = {"a": w(1), "b": w(2)}
        w_d = space.newdict(from_strdict_shared=d)
        assert self.space.eq_w(space.getitem(w_d, w("a")), w(1))
        assert self.space.eq_w(space.getitem(w_d, w("b")), w(2))
        d["c"] = w(41)
        assert self.space.eq_w(space.getitem(w_d, w("c")), w(41))



class AppTest_DictObject:

    def test_equality(self):
        d = {1:2} 
        f = {1:2} 
        assert d == f
        assert d != {1:3}

    def test_clear(self):
        d = {1:2, 3:4}
        d.clear()
        assert len(d) == 0
                         
    def test_copy(self):
        d = {1:2, 3:4}
        dd = d.copy()
        assert d == dd
        assert not d is dd
        
    def test_get(self):
        d = {1:2, 3:4}
        assert d.get(1) == 2
        assert d.get(1,44) == 2
        assert d.get(33) == None
        assert d.get(33,44) == 44

    def test_pop(self):
        d = {1:2, 3:4}
        dd = d.copy()
        result = dd.pop(1)
        assert result == 2
        assert len(dd) == 1
        dd = d.copy()
        result = dd.pop(1, 44)
        assert result == 2
        assert len(dd) == 1
        result = dd.pop(1, 44)
        assert result == 44
        assert len(dd) == 1
        raises(KeyError, dd.pop, 33)
    
    def test_has_key(self):
        d = {1:2, 3:4}
        assert d.has_key(1)
        assert not d.has_key(33)
    
    def test_items(self):
        d = {1:2, 3:4}
        its = d.items()
        its.sort()
        assert its == [(1,2),(3,4)]
    
    def test_iteritems(self):
        d = {1:2, 3:4}
        dd = d.copy()
        for k, v in d.iteritems():
            assert v == dd[k]
            del dd[k]
        assert not dd
    
    def test_iterkeys(self):
        d = {1:2, 3:4}
        dd = d.copy()
        for k in d.iterkeys():
            del dd[k]
        assert not dd
    
    def test_itervalues(self):
        d = {1:2, 3:4}
        values = []
        for k in d.itervalues():
            values.append(k)
        assert values == d.values()
    
    def test_keys(self):
        d = {1:2, 3:4}
        kys = d.keys()
        kys.sort()
        assert kys == [1,3]
    
    def test_popitem(self):
        d = {1:2, 3:4}
        it = d.popitem()
        assert len(d) == 1
        assert it==(1,2) or it==(3,4)
        it1 = d.popitem()
        assert len(d) == 0
        assert (it!=it1) and (it1==(1,2) or it1==(3,4))
    
    def test_setdefault(self):
        d = {1:2, 3:4}
        dd = d.copy()
        x = dd.setdefault(1, 99)
        assert d == dd
        assert x == 2
        x = dd.setdefault(33, 99)
        d[33] = 99
        assert d == dd
        assert x == 99
    
    def test_update(self):
        d = {1:2, 3:4}
        dd = d.copy()
        d.update({})
        assert d == dd
        d.update({3:5, 6:7})
        assert d == {1:2, 3:5, 6:7}

    def test_update_iterable(self):
        d = {}
        d.update((('a',1),))
        assert d == {'a': 1}
        d.update([('a',2), ('c',3)])
        assert d == {'a': 2, 'c': 3}

    def test_update_nop(self):
        d = {}
        d.update()
        assert d == {}

    def test_update_kwargs(self):
        d = {}
        d.update(foo='bar', baz=1)
        assert d == {'foo': 'bar', 'baz': 1}

    def test_update_dict_and_kwargs(self):
        d = {}
        d.update({'foo': 'bar'}, baz=1)
        assert d == {'foo': 'bar', 'baz': 1}

    def test_values(self):
        d = {1:2, 3:4}
        vals = d.values()
        vals.sort()
        assert vals == [2,4]

    def test_eq(self):
        d1 = {1:2, 3:4}
        d2 = {1:2, 3:4}
        d3 = {1:2}
        bool = d1 == d2
        assert bool == True
        bool = d1 == d3
        assert bool == False
        bool = d1 != d2
        assert bool == False
        bool = d1 != d3
        assert bool == True

    def test_lt(self):
        d1 = {1:2, 3:4}
        d2 = {1:2, 3:4}
        d3 = {1:2, 3:5}
        d4 = {1:2}
        bool = d1 < d2
        assert bool == False
        bool = d1 < d3
        assert bool == True
        bool = d1 < d4
        assert bool == False

    def test_lt2(self):
        assert {'a': 1 } < { 'a': 2 }
        assert not {'a': 1 } > { 'a': 2 }
        assert not {'a': 1, 'b': 0 } > { 'a': 2, 'b': 0 }
        assert {'a': 1, 'b': 0 } < { 'a': 2, 'b': 0 }
        assert {'a': 1, 'b': 0 } < { 'a': 1, 'b': 2 }
        assert not {'a': 1, 'b': 0 } < { 'a': 1, 'b': -2 }
        assert {'a': 1 } < { 'b': 1}
        assert {'a': 1, 'x': 2 } < { 'b': 1, 'x': 2}

    def test_str_repr(self):
        assert '{}' == str({})
        assert '{1: 2}' == str({1: 2})
        assert "{'ba': 'bo'}" == str({'ba': 'bo'})
        # NOTE: the string repr depends on hash values of 1 and 'ba'!!!
        ok_reprs = ["{1: 2, 'ba': 'bo'}", "{'ba': 'bo', 1: 2}"]
        assert str({1: 2, 'ba': 'bo'}) in ok_reprs
        assert '{}' == repr({})
        assert '{1: 2}' == repr({1: 2})
        assert "{'ba': 'bo'}" == repr({'ba': 'bo'})
        assert str({1: 2, 'ba': 'bo'}) in ok_reprs

        # Now test self-containing dict
        d = {}
        d[0] = d
        assert str(d) == '{0: {...}}'

        # Mutating while repr'ing
        class Machiavelli(object):
            def __repr__(self):
                d.clear()
                return "42"
        d = {Machiavelli(): True}
        str(d)
        assert d == {}

    def test_new(self):
        d = dict()
        assert d == {}
        args = [['a',2], [23,45]]
        d = dict(args)
        assert d == {'a':2, 23:45}
        d = dict(args, a=33, b=44)
        assert d == {'a':33, 'b':44, 23:45}
        d = dict(a=33, b=44)
        assert d == {'a':33, 'b':44}
        d = dict({'a':33, 'b':44})
        assert d == {'a':33, 'b':44}        
        try: d = dict(23)
        except (TypeError, ValueError): pass
        else: self.fail("dict(23) should raise!")
        try: d = dict([[1,2,3]])
        except (TypeError, ValueError): pass
        else: self.fail("dict([[1,2,3]]) should raise!")

    def test_fromkeys(self):
        assert {}.fromkeys([1, 2], 1) == {1: 1, 2: 1}
        assert {}.fromkeys([1, 2]) == {1: None, 2: None}
        assert {}.fromkeys([]) == {}
        assert {1: 0, 2: 0, 3: 0}.fromkeys([1, '1'], 'j') == (
                          {1: 'j', '1': 'j'})
        class D(dict):
            def __new__(cls):
                return E()
        class E(dict):
            pass
        assert isinstance(D.fromkeys([1, 2]), E)

    def test_str_uses_repr(self):
        class D(dict):
            def __repr__(self):
                return 'hi'
        assert repr(D()) == 'hi'
        assert str(D()) == 'hi'

    def test_overridden_setitem(self):
        class D(dict):
            def __setitem__(self, key, value):
                dict.__setitem__(self, key, 42)
        d = D([('x', 'foo')], y = 'bar')
        assert d['x'] == 'foo'
        assert d['y'] == 'bar'

        d.setdefault('z', 'baz')
        assert d['z'] == 'baz'

        d['foo'] = 'bar'
        assert d['foo'] == 42

        d.update({'w': 'foobar'})
        assert d['w'] == 'foobar'

        d = d.copy()
        assert d['x'] == 'foo'

        d3 = D.fromkeys(['x', 'y'], 'foo')
        assert d3['x'] == 42
        assert d3['y'] == 42

    def test_overridden_setitem_customkey(self):        
        class D(dict):
            def __setitem__(self, key, value):
                dict.__setitem__(self, key, 42)
        class Foo(object):
            pass

        d = D()
        key = Foo()
        d[key] = 'bar'
        assert d[key] == 42

    def test_repr_with_overridden_items(self):
        class D(dict):
            def items(self):
                return []

        d = D([("foo", "foobar")])
        assert repr(d) == "{'foo': 'foobar'}"

    def test_popitem_with_overridden_delitem(self):
        class D(dict):
            def __delitem__(self, key):
                assert False
        d = D()
        d['a'] = 42
        item = d.popitem()
        assert item == ('a', 42)

    def test_dict_update_overridden_getitem(self):
        class D(dict):
            def __getitem__(self, key):
                return 42
        d1 = {}
        d2 = D(a='foo')
        d1.update(d2)
        assert d1['a'] == 42 # fails on CPython, d1['a'] == 'foo'

    def test_index_keyerror_unpacking(self):
        d = {}
        for v1 in ['Q', (1,)]:
            try:
                d[v1]
            except KeyError, e:
                v2 = e.args[0]
                assert v1 == v2
            else:
                assert False, 'Expected KeyError'
        
    def test_del_keyerror_unpacking(self):
        d = {}
        for v1 in ['Q', (1,)]:
            try:
                del d[v1]
            except KeyError, e:
                v2 = e.args[0]
                assert v1 == v2
            else:
                assert False, 'Expected KeyError'

    def test_pop_keyerror_unpacking(self):
        d = {}
        for v1 in ['Q', (1,)]:
            try:
                d.pop(v1)
            except KeyError, e:
                v2 = e.args[0]
                assert v1 == v2
            else:
                assert False, 'Expected KeyError'

    def test_no_len_on_dict_iter(self):
        iterable = {1: 2, 3: 4}
        raises(TypeError, len, iter(iterable))
        iterable = {"1": 2, "3": 4}
        raises(TypeError, len, iter(iterable))
        iterable = {}
        raises(TypeError, len, iter(iterable))


class AppTest_DictMultiObject(AppTest_DictObject):

    def test_emptydict_unhashable(self):
        raises(TypeError, "{}[['x']]")

    def test_string_subclass_via_setattr(self):
        class A(object):
            pass
        class S(str):
            def __hash__(self):
                return 123
        a = A()
        s = S("abc")
        setattr(a, s, 42)
        key = a.__dict__.keys()[0]
        assert key == s
        assert type(key) is str
        assert getattr(a, s) == 42


class TestW_DictSharing(TestW_DictObject):
    def setup_class(cls):
        cls.space = gettestobjspace(**{"objspace.std.withsharingdict": True})

class AppTest_DictSharing(AppTest_DictObject):
    def setup_class(cls):
        cls.space = gettestobjspace(**{"objspace.std.withsharingdict": True})

    def test_values_does_not_share(self):
        class A(object):
            pass
        a = A()
        a.abc = 12
        l = a.__dict__.values()
        assert l == [12]
        l[0] = 24
        assert a.abc == 12

    def test_items(self):
        class A(object):
            pass
        a = A()
        a.abc = 12
        a.__dict__.items() == [("abc", 12)]


class AppTestModuleDict(object):
    def setup_class(cls):
        cls.space = gettestobjspace(**{"objspace.std.withcelldict": True})
        cls.w_impl_used = cls.space.appexec([], """():
            import __pypy__
            def impl_used(obj):
                assert "ModuleDictImplementation" in __pypy__.internal_repr(obj)
            return impl_used
        """)


    def test_check_module_uses_module_dict(self):
        m = type(__builtins__)("abc")
        self.impl_used(m.__dict__)

    def test_key_not_there(self):
        d = type(__builtins__)("abc").__dict__
        raises(KeyError, "d['def']")



class FakeString(str):
    def unwrap(self, space):
        self.unwrapped = True
        return str(self)

# the minimal 'space' needed to use a W_DictMultiObject
class FakeSpace:
    def hash_w(self, obj):
        return hash(obj)
    def unwrap(self, x):
        return x
    def is_true(self, x):
        return x
    def is_(self, x, y):
        return x is y
    is_w = is_
    def eq(self, x, y):
        return x == y
    eq_w = eq
    def newlist(self, l):
        return []
    DictObjectCls = W_DictMultiObject
    def type(self, w_obj):
        return type(w_obj)
    w_str = str
    def str_w(self, string):
        assert isinstance(string, str)
        return string

    def wrap(self, obj):
        return obj

    def isinstance(self, obj, klass):
        return isinstance(obj, klass)

    def newtuple(self, l):
        return tuple(l)

    def newdict(self, module=False, instance=False, classofinstance=None,
                from_strdict_shared=None):
        return W_DictMultiObject.allocate_and_init_instance(
                self, module=module, instance=instance,
                classofinstance=classofinstance,
                from_strdict_shared=from_strdict_shared)

    def allocate_instance(self, cls, type):
        return object.__new__(cls)

    def fromcache(self, cls):
        return cls(self)

    w_StopIteration = StopIteration
    w_None = None
    StringObjectCls = FakeString
    w_dict = None
    iter = iter
    fixedview = list
    listview  = list

class Config:
    class objspace:
        class std:
            withdictmeasurement = False
            withsharingdict = False
            withsmalldicts = False
            withcelldict = False
            withshadowtracking = False
        class opcodes:
            CALL_LIKELY_BUILTIN = False

FakeSpace.config = Config()


class TestDictImplementation:
    def setup_method(self,method):
        self.space = FakeSpace()

    def test_stressdict(self):
        from random import randint
        d = self.space.newdict()
        N = 10000
        pydict = {}
        for i in range(N):
            x = randint(-N, N)
            setitem__DictMulti_ANY_ANY(self.space, d, x, i)
            pydict[x] = i
        for key, value in pydict.iteritems():
            assert value == getitem__DictMulti_ANY(self.space, d, key)

class BaseTestRDictImplementation:

    def setup_method(self,method):
        self.fakespace = FakeSpace()
        self.string = self.fakespace.wrap("fish")
        self.string2 = self.fakespace.wrap("fish2")
        self.impl = self.get_impl()

    def get_impl(self):
        return self.ImplementionClass(self.fakespace)

    def fill_impl(self):
        self.impl.setitem(self.string, 1000)
        self.impl.setitem(self.string2, 2000)

    def check_not_devolved(self):
        assert self.impl.r_dict_content is None

    def test_setitem(self):
        self.impl.setitem(self.string, 1000)
        assert self.impl.length() == 1
        assert self.impl.getitem(self.string) == 1000
        assert self.impl.getitem_str(self.string) == 1000
        self.check_not_devolved()

    def test_setitem_str(self):
        self.impl.setitem_str(self.fakespace.str_w(self.string), 1000)
        assert self.impl.length() == 1
        assert self.impl.getitem(self.string) == 1000
        assert self.impl.getitem_str(self.string) == 1000
        self.check_not_devolved()

    def test_delitem(self):
        self.fill_impl()
        assert self.impl.length() == 2
        self.impl.delitem(self.string2)
        assert self.impl.length() == 1
        self.impl.delitem(self.string)
        assert self.impl.length() == 0
        self.check_not_devolved()

    def test_keys(self):
        self.fill_impl()
        keys = self.impl.keys()
        keys.sort()
        assert keys == [self.string, self.string2]
        self.check_not_devolved()

    def test_values(self):
        self.fill_impl()
        values = self.impl.values()
        values.sort()
        assert values == [1000, 2000]
        self.check_not_devolved()

    def test_items(self):
        self.fill_impl()
        items = self.impl.items()
        items.sort()
        assert items == zip([self.string, self.string2], [1000, 2000])
        self.check_not_devolved()

    def test_iter(self):
        self.fill_impl()
        iteratorimplementation = self.impl.iter()
        items = []
        while 1:
            item = iteratorimplementation.next()
            if item == (None, None):
                break
            items.append(item)
        items.sort()
        assert items == zip([self.string, self.string2], [1000, 2000])
        self.check_not_devolved()

    def test_devolve(self):
        impl = self.impl
        for x in xrange(100):
            impl.setitem(self.fakespace.str_w(str(x)), x)
            impl.setitem(x, x)
        assert impl.r_dict_content is not None

class TestStrDictImplementation(BaseTestRDictImplementation):
    ImplementionClass = StrDictImplementation

    def test_str_shortcut(self):
        self.fill_impl()
        s = FakeString(self.string)
        assert self.impl.getitem(s) == 1000
        assert s.unwrapped

## class TestMeasuringDictImplementation(BaseTestRDictImplementation):
##     ImplementionClass = MeasuringDictImplementation
##     DevolvedClass = MeasuringDictImplementation

class TestModuleDictImplementation(BaseTestRDictImplementation):
    ImplementionClass = ModuleDictImplementation

class TestModuleDictImplementationWithBuiltinNames(BaseTestRDictImplementation):
    ImplementionClass = ModuleDictImplementation

    string = "int"
    string2 = "isinstance"

class TestSharedDictImplementation(BaseTestRDictImplementation):
    ImplementionClass = SharedDictImplementation


class BaseTestDevolvedDictImplementation(BaseTestRDictImplementation):
    def fill_impl(self):
        BaseTestRDictImplementation.fill_impl(self)
        self.impl._as_rdict()

    def check_not_devolved(self):
        pass

class TestDevolvedStrDictImplementation(BaseTestDevolvedDictImplementation):
    ImplementionClass = StrDictImplementation

class TestDevolvedModuleDictImplementation(BaseTestDevolvedDictImplementation):
    ImplementionClass = ModuleDictImplementation

class TestDevolvedModuleDictImplementationWithBuiltinNames(BaseTestDevolvedDictImplementation):
    ImplementionClass = ModuleDictImplementation

    string = "int"
    string2 = "isinstance"

class TestDevolvedSharedDictImplementation(BaseTestDevolvedDictImplementation):
    ImplementionClass = SharedDictImplementation

def test_module_uses_strdict():
    fakespace = FakeSpace()
    d = fakespace.newdict(module=True)
    assert isinstance(d, StrDictImplementation)

