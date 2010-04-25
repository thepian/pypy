"""
Python related collection nodes.  Here is an example of 
a tree of collectors and test items that this modules provides:: 

        Module                  # File
            Class 
                Instance   
                    Function  
                    Generator 
                        ... 
            Function 
            Generator 
                Function 

        DoctestFile              # File
            DoctestFileContent   # acts as Item 

""" 
import py
import inspect
from py.impl.test.collect import configproperty, warnoldcollect
from py.impl.test import funcargs

class PyobjMixin(object):
    def obj(): 
        def fget(self):
            try: 
                return self._obj   
            except AttributeError: 
                self._obj = obj = self._getobj() 
                return obj 
        def fset(self, value): 
            self._obj = value 
        return property(fget, fset, None, "underlying python object") 
    obj = obj()

    def _getobj(self):
        return getattr(self.parent.obj, self.name)

    def getmodpath(self, stopatmodule=True, includemodule=False):
        """ return python path relative to the containing module. """
        chain = self.listchain()
        chain.reverse()
        parts = []
        for node in chain:
            if isinstance(node, Instance):
                continue
            name = node.name 
            if isinstance(node, Module):
                assert name.endswith(".py")
                name = name[:-3]
                if stopatmodule:
                    if includemodule:
                        parts.append(name)
                    break
            parts.append(name)
        parts.reverse()
        s = ".".join(parts)
        return s.replace(".[", "[")

    def _getfslineno(self):
        try:
            return self._fslineno
        except AttributeError:
            pass
        obj = self.obj
        # xxx let decorators etc specify a sane ordering
        if hasattr(obj, 'place_as'):
            obj = obj.place_as

        self._fslineno = py.code.getfslineno(obj)
        return self._fslineno

    def reportinfo(self):
        fspath, lineno = self._getfslineno()
        modpath = self.getmodpath()
        return fspath, lineno, modpath 

class PyCollectorMixin(PyobjMixin, py.test.collect.Collector): 
    Class = configproperty('Class')
    Instance = configproperty('Instance')
    Function = configproperty('Function')
    Generator = configproperty('Generator')
    
    def funcnamefilter(self, name): 
        return name.startswith('test') 
    def classnamefilter(self, name): 
        return name.startswith('Test')

    def collect(self):
        l = self._deprecated_collect()
        if l is not None:
            return l
        name2items = self._buildname2items()
        colitems = list(name2items.values())
        colitems.sort(key=lambda item: item.reportinfo()[:2])
        return colitems

    def _buildname2items(self): 
        # NB. we avoid random getattrs and peek in the __dict__ instead
        d = {}
        dicts = [getattr(self.obj, '__dict__', {})]
        for basecls in inspect.getmro(self.obj.__class__):
            dicts.append(basecls.__dict__)
        seen = {}
        for dic in dicts:
            for name, obj in dic.items():
                if name in seen:
                    continue
                seen[name] = True
                if name[0] != "_":
                    res = self.makeitem(name, obj)
                    if res is not None:
                        d[name] = res 
        return d

    def _deprecated_join(self, name):
        if self.__class__.join != py.test.collect.Collector.join:
            warnoldcollect()
            return self.join(name)

    def makeitem(self, name, obj):
        return self.config.hook.pytest_pycollect_makeitem(
            collector=self, name=name, obj=obj)

    def _istestclasscandidate(self, name, obj):
        if self.classnamefilter(name) and \
           inspect.isclass(obj):
            if hasinit(obj):
                # XXX WARN 
                return False
            return True

    def _genfunctions(self, name, funcobj):
        module = self.getparent(Module).obj
        clscol = self.getparent(Class)
        cls = clscol and clscol.obj or None
        metafunc = funcargs.Metafunc(funcobj, config=self.config, 
            cls=cls, module=module)
        gentesthook = self.config.hook._makecall(
            "pytest_generate_tests", extralookup=module)
        gentesthook(metafunc=metafunc)
        if not metafunc._calls:
            return self.Function(name, parent=self)
        return funcargs.FunctionCollector(name=name, 
            parent=self, calls=metafunc._calls)

        
class Module(py.test.collect.File, PyCollectorMixin):
    def _getobj(self):
        return self._memoizedcall('_obj', self._importtestmodule)

    def _importtestmodule(self):
        # we assume we are only called once per module 
        mod = self.fspath.pyimport()
        #print "imported test module", mod
        self.config.pluginmanager.consider_module(mod)
        return mod

    def setup(self): 
        if getattr(self.obj, 'disabled', 0):
            py.test.skip("%r is disabled" %(self.obj,))
        if hasattr(self.obj, 'setup_module'): 
            #XXX: nose compat hack, move to nose plugin
            # if it takes a positional arg, its probably a py.test style one
            # so we pass the current module object
            if inspect.getargspec(self.obj.setup_module)[0]:
                self.obj.setup_module(self.obj)
            else:
                self.obj.setup_module()

    def teardown(self): 
        if hasattr(self.obj, 'teardown_module'): 
            #XXX: nose compat hack, move to nose plugin
            # if it takes a positional arg, its probably a py.test style one
            # so we pass the current module object
            if inspect.getargspec(self.obj.teardown_module)[0]:
                self.obj.teardown_module(self.obj)
            else:
                self.obj.teardown_module()

class Class(PyCollectorMixin, py.test.collect.Collector): 

    def collect(self):
        l = self._deprecated_collect()
        if l is not None:
            return l
        return [self.Instance(name="()", parent=self)]

    def setup(self): 
        if getattr(self.obj, 'disabled', 0):
            py.test.skip("%r is disabled" %(self.obj,))
        setup_class = getattr(self.obj, 'setup_class', None)
        if setup_class is not None: 
            setup_class = getattr(setup_class, 'im_func', setup_class) 
            setup_class(self.obj) 

    def teardown(self): 
        teardown_class = getattr(self.obj, 'teardown_class', None) 
        if teardown_class is not None: 
            teardown_class = getattr(teardown_class, 'im_func', teardown_class) 
            teardown_class(self.obj) 

class Instance(PyCollectorMixin, py.test.collect.Collector): 
    def _getobj(self): 
        return self.parent.obj()  
    def Function(self): 
        return getattr(self.obj, 'Function', 
                       PyCollectorMixin.Function.__get__(self)) # XXX for python 2.2
    def _keywords(self):
        return []
    Function = property(Function)

    #def __repr__(self):
    #    return "<%s of '%s'>" %(self.__class__.__name__, 
    #                         self.parent.obj.__name__)

    def newinstance(self):  
        self.obj = self._getobj()
        return self.obj

class FunctionMixin(PyobjMixin):
    """ mixin for the code common to Function and Generator.
    """

    def setup(self): 
        """ perform setup for this test function. """
        if inspect.ismethod(self.obj):
            name = 'setup_method' 
        else: 
            name = 'setup_function' 
        if isinstance(self.parent, Instance):
            obj = self.parent.newinstance()
            self.obj = self._getobj()
        else:
            obj = self.parent.obj 
        setup_func_or_method = getattr(obj, name, None)
        if setup_func_or_method is not None: 
            setup_func_or_method(self.obj) 

    def teardown(self): 
        """ perform teardown for this test function. """
        if inspect.ismethod(self.obj):
            name = 'teardown_method' 
        else: 
            name = 'teardown_function' 
        obj = self.parent.obj 
        teardown_func_or_meth = getattr(obj, name, None)
        if teardown_func_or_meth is not None: 
            teardown_func_or_meth(self.obj) 

    def _prunetraceback(self, traceback):
        if hasattr(self, '_obj') and not self.config.option.fulltrace: 
            code = py.code.Code(self.obj) 
            path, firstlineno = code.path, code.firstlineno 
            ntraceback = traceback.cut(path=path, firstlineno=firstlineno)
            if ntraceback == traceback:
                ntraceback = ntraceback.cut(path=path)
                if ntraceback == traceback:
                    ntraceback = ntraceback.cut(excludepath=py._dir)
            traceback = ntraceback.filter()
        return traceback 

    def repr_failure(self, excinfo, outerr=None):
        assert outerr is None, "XXX outerr usage is deprecated"
        return self._repr_failure_py(excinfo)

    shortfailurerepr = "F"

class Generator(FunctionMixin, PyCollectorMixin, py.test.collect.Collector): 
    def collect(self):
        # test generators are seen as collectors but they also 
        # invoke setup/teardown on popular request 
        # (induced by the common "test_*" naming shared with normal tests)
        self.config._setupstate.prepare(self) 
        l = []
        seen = {}
        for i, x in enumerate(self.obj()): 
            name, call, args = self.getcallargs(x)
            if not py.builtin.callable(call): 
                raise TypeError("%r yielded non callable test %r" %(self.obj, call,))
            if name is None:
                name = "[%d]" % i
            else:
                name = "['%s']" % name
            if name in seen:
                raise ValueError("%r generated tests with non-unique name %r" %(self, name))
            seen[name] = True
            l.append(self.Function(name, self, args=args, callobj=call))
        return l
        
    def getcallargs(self, obj):
        if not isinstance(obj, (tuple, list)):
            obj = (obj,)
        # explict naming
        if isinstance(obj[0], py.builtin._basestring):
            name = obj[0]
            obj = obj[1:]
        else:
            name = None
        call, args = obj[0], obj[1:]
        return name, call, args 
    

#
#  Test Items 
#
_dummy = object()
class Function(FunctionMixin, py.test.collect.Item): 
    """ a Function Item is responsible for setting up  
        and executing a Python callable test object.
    """
    _genid = None
    def __init__(self, name, parent=None, args=None, 
                 callspec=None, callobj=_dummy):
        super(Function, self).__init__(name, parent)
        self._args = args 
        if self._isyieldedfunction():
            assert not callspec, "yielded functions (deprecated) cannot have funcargs" 
        else:
            if callspec is not None:
                self.funcargs = callspec.funcargs or {}
                self._genid = callspec.id 
                if hasattr(callspec, "param"):
                    self._requestparam = callspec.param
            else:
                self.funcargs = {}
        if callobj is not _dummy: 
            self._obj = callobj 

    def _isyieldedfunction(self):
        return self._args is not None

    def readkeywords(self):
        d = super(Function, self).readkeywords()
        d.update(py.builtin._getfuncdict(self.obj))
        return d

    def runtest(self):
        """ execute the underlying test function. """
        self.config.hook.pytest_pyfunc_call(pyfuncitem=self)

    def setup(self):
        super(Function, self).setup()
        if hasattr(self, 'funcargs'): 
            funcargs.fillfuncargs(self)

    def __eq__(self, other):
        try:
            return (self.name == other.name and 
                    self._args == other._args and
                    self.parent == other.parent and
                    self.obj == other.obj and 
                    getattr(self, '_genid', None) == 
                    getattr(other, '_genid', None) 
            )
        except AttributeError:
            pass
        return False

    def __ne__(self, other):
        return not self == other
    
    def __hash__(self):
        return hash((self.parent, self.name))

def hasinit(obj):
    init = getattr(obj, '__init__', None)
    if init:
        if not isinstance(init, type(object.__init__)):
            return True
