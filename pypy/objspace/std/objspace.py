import __builtin__
import types
from pypy.interpreter import pyframe, function, special
from pypy.interpreter.baseobjspace import ObjSpace, Wrappable
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.interpreter.typedef import get_unique_interplevel_subclass
from pypy.objspace.std import (builtinshortcut, stdtypedef, frame, model,
                               transparent, callmethod, proxyobject)
from pypy.objspace.descroperation import DescrOperation, raiseattrerror
from pypy.rlib.objectmodel import instantiate, r_dict
from pypy.rlib.debug import make_sure_not_resized
from pypy.rlib.rarithmetic import base_int
from pypy.rlib.objectmodel import we_are_translated
from pypy.rlib.jit import hint
from pypy.tool.sourcetools import func_with_new_name

# Object imports
from pypy.objspace.std.boolobject import W_BoolObject
from pypy.objspace.std.complexobject import W_ComplexObject
from pypy.objspace.std.dictmultiobject import W_DictMultiObject
from pypy.objspace.std.floatobject import W_FloatObject
from pypy.objspace.std.intobject import W_IntObject
from pypy.objspace.std.listobject import W_ListObject
from pypy.objspace.std.longobject import W_LongObject
from pypy.objspace.std.noneobject import W_NoneObject
from pypy.objspace.std.ropeobject import W_RopeObject
from pypy.objspace.std.iterobject import W_SeqIterObject
from pypy.objspace.std.setobject import W_SetObject, W_FrozensetObject
from pypy.objspace.std.sliceobject import W_SliceObject
from pypy.objspace.std.smallintobject import W_SmallIntObject
from pypy.objspace.std.stringobject import W_StringObject
from pypy.objspace.std.tupleobject import W_TupleObject
from pypy.objspace.std.typeobject import W_TypeObject

# types
from pypy.objspace.std.inttype import wrapint
from pypy.objspace.std.stringtype import wrapstr
from pypy.objspace.std.unicodetype import wrapunicode


class StdObjSpace(ObjSpace, DescrOperation):
    """The standard object space, implementing a general-purpose object
    library in Restricted Python."""

    def initialize(self):
        "NOT_RPYTHON: only for initializing the space."
        # setup all the object types and implementations
        self.model = model.StdTypeModel(self.config)

        self.FrameClass = frame.build_frame(self)

        if self.config.objspace.std.withrope:
            self.StringObjectCls = W_RopeObject
        else:
            self.StringObjectCls = W_StringObject

        self._install_multimethods()

        # singletons
        self.w_None = W_NoneObject.w_None
        self.w_False = W_BoolObject.w_False
        self.w_True = W_BoolObject.w_True
        self.w_NotImplemented = self.wrap(special.NotImplemented(self))
        self.w_Ellipsis = self.wrap(special.Ellipsis(self))

        # types
        self.builtin_types = {}
        for typedef in self.model.pythontypes:
            w_type = self.gettypeobject(typedef)
            self.builtin_types[typedef.name] = w_type
            setattr(self, 'w_' + typedef.name, w_type)
        self.builtin_types["NotImplemented"] = self.w_NotImplemented
        self.builtin_types["Ellipsis"] = self.w_Ellipsis

        # exceptions & builtins
        self.make_builtins()

        # the type of old-style classes
        self.w_classobj = self.builtin.get('__metaclass__')

        # final setup
        self.setup_builtin_modules()
        # Adding transparent proxy call
        if self.config.objspace.std.withtproxy:
            transparent.setup(self)

    def get_builtin_types(self):
        return self.builtin_types

    def _install_multimethods(self):
        """Install all the MultiMethods into the space instance."""
        for name, mm in model.MM.__dict__.items():
            if not isinstance(mm, model.StdObjSpaceMultiMethod):
                continue
            if not hasattr(self, name):
                # int_w, str_w...: these do not return a wrapped object
                if name.endswith('_w'):
                    func = mm.install_not_sliced(self.model.typeorder,
                                                 baked_perform_call=True)
                else:
                    unsliced = mm.install_not_sliced(self.model.typeorder,
                                                     baked_perform_call=False)
                    exprargs, expr, miniglobals, fallback = unsliced
                    func = stdtypedef.make_perform_trampoline('__mm_'+name,
                                                              exprargs, expr,
                                                              miniglobals, mm)

                boundmethod = types.MethodType(func, self, self.__class__)
                setattr(self, name, boundmethod)  # store into 'space' instance
            elif self.config.objspace.std.builtinshortcut:
                if name.startswith('inplace_'):
                    fallback_name = name[len('inplace_'):]
                    if fallback_name in ('or', 'and'):
                        fallback_name += '_'
                    fallback_mm = model.MM.__dict__[fallback_name]
                else:
                    fallback_mm = None
                builtinshortcut.install(self, mm, fallback_mm)
        if self.config.objspace.std.builtinshortcut:
            builtinshortcut.install_is_true(self, model.MM.nonzero,
                                            model.MM.len)

    def createexecutioncontext(self):
        # add space specific fields to execution context
        # note that this method must not call space methods that might need an
        # execution context themselves (e.g. nearly all space methods)
        ec = ObjSpace.createexecutioncontext(self)
        ec._py_repr = None
        return ec

    def createframe(self, code, w_globals, closure=None):
        from pypy.objspace.std.fake import CPythonFakeCode, CPythonFakeFrame
        if not we_are_translated() and isinstance(code, CPythonFakeCode):
            return CPythonFakeFrame(self, code, w_globals)
        else:
            return ObjSpace.createframe(self, code, w_globals, closure)

    def gettypefor(self, cls):
        return self.gettypeobject(cls.typedef)

    def gettypeobject(self, typedef):
        # stdtypedef.TypeCache maps each StdTypeDef instance to its
        # unique-for-this-space W_TypeObject instance
        assert typedef is not None
        return self.fromcache(stdtypedef.TypeCache).getorbuild(typedef)

    def wrap(self, x):
        "Wraps the Python value 'x' into one of the wrapper classes."
        # You might notice that this function is rather conspicuously
        # not RPython.  We can get away with this because the function
        # is specialized (see after the function body).  Also worth
        # noting is that the isinstance's involving integer types
        # behave rather differently to how you might expect during
        # annotation (see pypy/annotation/builtin.py)
        if x is None:
            return self.w_None
        if isinstance(x, model.W_Object):
            raise TypeError, "attempt to wrap already wrapped object: %s"%(x,)
        if isinstance(x, OperationError):
            raise TypeError, ("attempt to wrap already wrapped exception: %s"%
                              (x,))
        if isinstance(x, int):
            if isinstance(x, bool):
                return self.newbool(x)
            else:
                return self.newint(x)
        if isinstance(x, str):
            return wrapstr(self, x)
        if isinstance(x, unicode):
            return wrapunicode(self, x)
        if isinstance(x, float):
            return W_FloatObject(x)
        if isinstance(x, Wrappable):
            w_result = x.__spacebind__(self)
            #print 'wrapping', x, '->', w_result
            return w_result
        if isinstance(x, base_int):
            return W_LongObject.fromrarith_int(x)

        # _____ below here is where the annotator should not get _____

        # wrap() of a container works on CPython, but the code is
        # not RPython.  Don't use -- it is kept around mostly for tests.
        # Use instead newdict(), newlist(), newtuple().
        if isinstance(x, dict):
            items_w = [(self.wrap(k), self.wrap(v)) for (k, v) in x.iteritems()]
            r = self.newdict()
            r.initialize_content(items_w)
            return r
        if isinstance(x, tuple):
            wrappeditems = [self.wrap(item) for item in list(x)]
            return self.newtuple(wrappeditems)
        if isinstance(x, list):
            wrappeditems = [self.wrap(item) for item in x]
            return self.newlist(wrappeditems)

        # The following cases are even stranger.
        # Really really only for tests.
        if type(x) is long:
            return W_LongObject.fromlong(x)
        if isinstance(x, slice):
            return W_SliceObject(self.wrap(x.start),
                                 self.wrap(x.stop),
                                 self.wrap(x.step))
        if isinstance(x, complex):
            return W_ComplexObject(x.real, x.imag)

        if isinstance(x, set):
            rdict_w = r_dict(self.eq_w, self.hash_w)
            for item in x:
                rdict_w[self.wrap(item)] = None
            res = W_SetObject(self, rdict_w)
            return res

        if isinstance(x, frozenset):
            wrappeditems = [self.wrap(item) for item in x]
            return W_FrozensetObject(self, wrappeditems)

        if x is __builtin__.Ellipsis:
            # '__builtin__.Ellipsis' avoids confusion with special.Ellipsis
            return self.w_Ellipsis

        if self.config.objspace.nofaking:
            # annotation should actually not get here.  If it does, you get
            # an error during rtyping because '%r' is not supported.  It tells
            # you that there was a space.wrap() on a strange object.
            raise OperationError(self.w_RuntimeError,
                                 self.wrap("nofaking enabled: refusing "
                                           "to wrap cpython value %r" %(x,)))
        if isinstance(x, type(Exception)) and issubclass(x, Exception):
            w_result = self.wrap_exception_cls(x)
            if w_result is not None:
                return w_result
        from fake import fake_object
        return fake_object(self, x)

    wrap._annspecialcase_ = "specialize:wrap"

    def wrap_exception_cls(self, x):
        """NOT_RPYTHON"""
        if hasattr(self, 'w_' + x.__name__):
            w_result = getattr(self, 'w_' + x.__name__)
            return w_result
        return None
    wrap_exception_cls._annspecialcase_ = "override:wrap_exception_cls"

    def unwrap(self, w_obj):
        if isinstance(w_obj, Wrappable):
            return w_obj
        if isinstance(w_obj, model.W_Object):
            return w_obj.unwrap(self)
        raise model.UnwrapError, "cannot unwrap: %r" % w_obj

    def newint(self, intval):
        return wrapint(self, intval)

    def newfloat(self, floatval):
        return W_FloatObject(floatval)

    def newcomplex(self, realval, imagval):
        return W_ComplexObject(realval, imagval)

    def newlong(self, val): # val is an int
        return W_LongObject.fromint(self, val)

    def newtuple(self, list_w):
        assert isinstance(list_w, list)
        make_sure_not_resized(list_w)
        return W_TupleObject(list_w)

    def newlist(self, list_w):
        return W_ListObject(list_w)

    def newdict(self, module=False, instance=False, classofinstance=None,
                from_strdict_shared=None, strdict=False):
        return W_DictMultiObject.allocate_and_init_instance(
                self, module=module, instance=instance,
                classofinstance=classofinstance,
                from_strdict_shared=from_strdict_shared,
                strdict=strdict)

    def newslice(self, w_start, w_end, w_step):
        return W_SliceObject(w_start, w_end, w_step)

    def newseqiter(self, w_obj):
        return W_SeqIterObject(w_obj)

    def type(self, w_obj):
        hint(w_obj.__class__, promote=True)
        return w_obj.getclass(self)

    def lookup(self, w_obj, name):
        w_type = self.type(w_obj)
        return w_type.lookup(name)
    lookup._annspecialcase_ = 'specialize:lookup'

    def lookup_in_type_where(self, w_type, name):
        return w_type.lookup_where(name)
    lookup_in_type_where._annspecialcase_ = 'specialize:lookup_in_type_where'

    def lookup_in_type_starting_at(self, w_type, w_starttype, name):
        """ Only supposed to be used to implement super, w_starttype
        and w_type are the same as for super(starttype, type)
        """
        assert isinstance(w_type, W_TypeObject)
        assert isinstance(w_starttype, W_TypeObject)
        return w_type.lookup_starting_at(w_starttype, name)

    def allocate_instance(self, cls, w_subtype):
        """Allocate the memory needed for an instance of an internal or
        user-defined type, without actually __init__ializing the instance."""
        w_type = self.gettypeobject(cls.typedef)
        if self.is_w(w_type, w_subtype):
            instance = instantiate(cls)
        elif cls.typedef.acceptable_as_base_class:
            # the purpose of the above check is to avoid the code below
            # to be annotated at all for 'cls' if it is not necessary
            w_subtype = w_type.check_user_subclass(w_subtype)
            if cls.typedef.applevel_subclasses_base is not None:
                cls = cls.typedef.applevel_subclasses_base
            subcls = get_unique_interplevel_subclass(
                    self.config, cls, w_subtype.hasdict, w_subtype.nslots != 0,
                    w_subtype.needsdel, w_subtype.weakrefable)
            instance = instantiate(subcls)
            assert isinstance(instance, cls)
            instance.user_setup(self, w_subtype)
        else:
            raise operationerrfmt(self.w_TypeError,
                "%s.__new__(%s): only for the type %s",
                w_type.name, w_subtype.getname(self, '?'), w_type.name)
        return instance
    allocate_instance._annspecialcase_ = "specialize:arg(1)"

    # two following functions are almost identical, but in fact they
    # have different return type. First one is a resizable list, second
    # one is not

    def _wrap_expected_length(self, expected, got):
        return OperationError(self.w_ValueError,
                self.wrap("Expected length %d, got %d" % (expected, got)))

    def unpackiterable(self, w_obj, expected_length=-1):
        if isinstance(w_obj, W_TupleObject):
            t = w_obj.wrappeditems[:]
        elif isinstance(w_obj, W_ListObject):
            t = w_obj.wrappeditems[:]
        else:
            return ObjSpace.unpackiterable(self, w_obj, expected_length)
        if expected_length != -1 and len(t) != expected_length:
            raise self._wrap_expected_length(expected_length, len(t))
        return t

    def fixedview(self, w_obj, expected_length=-1):
        """ Fast paths
        """
        if isinstance(w_obj, W_TupleObject):
            t = w_obj.wrappeditems
        elif isinstance(w_obj, W_ListObject):
            t = w_obj.wrappeditems[:]
        else:
            return ObjSpace.fixedview(self, w_obj, expected_length)
        if expected_length != -1 and len(t) != expected_length:
            raise self._wrap_expected_length(expected_length, len(t))
        return t

    def listview(self, w_obj, expected_length=-1):
        if isinstance(w_obj, W_ListObject):
            t = w_obj.wrappeditems
        elif isinstance(w_obj, W_TupleObject):
            t = w_obj.wrappeditems[:]
        else:
            return ObjSpace.listview(self, w_obj, expected_length)
        if expected_length != -1 and len(t) != expected_length:
            raise self._wrap_expected_length(expected_length, len(t))
        return t

    def sliceindices(self, w_slice, w_length):
        if isinstance(w_slice, W_SliceObject):
            a, b, c = w_slice.indices3(self, self.int_w(w_length))
            return (a, b, c)
        w_indices = self.getattr(w_slice, self.wrap('indices'))
        w_tup = self.call_function(w_indices, w_length)
        l_w = self.unpackiterable(w_tup)
        if not len(l_w) == 3:
            raise OperationError(self.w_ValueError,
                                 self.wrap("Expected tuple of length 3"))
        return self.int_w(l_w[0]), self.int_w(l_w[1]), self.int_w(l_w[2])

    def is_(self, w_one, w_two):
        if w_one is w_two:
            return self.w_True
        return self.w_False

    # short-cut
    def is_w(self, w_one, w_two):
        return w_one is w_two

    def is_true(self, w_obj):
        # a shortcut for performance
        # NOTE! this method is typically overridden by builtinshortcut.py.
        if type(w_obj) is W_BoolObject:
            return w_obj.boolval
        return DescrOperation.is_true(self, w_obj)

    def getattr(self, w_obj, w_name):
        if not self.config.objspace.std.getattributeshortcut:
            return DescrOperation.getattr(self, w_obj, w_name)

        # an optional shortcut for performance
        w_type = self.type(w_obj)
        w_descr = w_type.getattribute_if_not_from_object()
        if w_descr is not None:
            return self._handle_getattribute(w_descr, w_obj, w_name)

        # fast path: XXX this is duplicating most of the logic
        # from the default __getattribute__ and the getattr() method...
        name = self.str_w(w_name)
        w_descr = w_type.lookup(name)
        e = None
        if w_descr is not None:
            w_get = None
            is_data = self.is_data_descr(w_descr)
            if is_data:
                w_get = self.lookup(w_descr, "__get__")
            if w_get is None:
                w_value = w_obj.getdictvalue_attr_is_in_class(self, name)
                if w_value is not None:
                    return w_value
                if not is_data:
                    w_get = self.lookup(w_descr, "__get__")
            if w_get is not None:
                # __get__ is allowed to raise an AttributeError to trigger
                # use of __getattr__.
                try:
                    return self.get_and_call_function(w_get, w_descr, w_obj,
                                                      w_type)
                except OperationError, e:
                    if not e.match(self, self.w_AttributeError):
                        raise
            else:
                return w_descr
        else:
            w_value = w_obj.getdictvalue(self, name)
            if w_value is not None:
                return w_value

        w_descr = self.lookup(w_obj, '__getattr__')
        if w_descr is not None:
            return self.get_and_call_function(w_descr, w_obj, w_name)
        elif e is not None:
            raise e
        else:
            raiseattrerror(self, w_obj, name)

    def finditem_str(self, w_obj, key):
        """ Perform a getitem on w_obj with key (string). Returns found
        element or None on element not found.

        performance shortcut to avoid creating the OperationError(KeyError)
        and allocating W_StringObject
        """
        if (isinstance(w_obj, W_DictMultiObject) and
                not w_obj.user_overridden_class):
            return w_obj.getitem_str(key)
        return ObjSpace.finditem_str(self, w_obj, key)

    def finditem(self, w_obj, w_key):
        """ Perform a getitem on w_obj with w_key (any object). Returns found
        element or None on element not found.

        performance shortcut to avoid creating the OperationError(KeyError).
        """
        if (isinstance(w_obj, W_DictMultiObject) and
                not w_obj.user_overridden_class):
            return w_obj.getitem(w_key)
        return ObjSpace.finditem(self, w_obj, w_key)

    def setitem_str(self, w_obj, key, w_value, shadows_type=True):
        """ Same as setitem, but takes string instead of any wrapped object

        XXX what shadows_type means???
        """
        if (isinstance(w_obj, W_DictMultiObject) and
                not w_obj.user_overridden_class):
            w_obj.setitem_str(key, w_value, shadows_type)
        else:
            self.setitem(w_obj, self.wrap(key), w_value)

    def getindex_w(self, w_obj, w_exception, objdescr=None):
        # Performance shortcut for the common case of w_obj being an int.
        # If withsmallint is disabled, we check for W_IntObject.
        # If withsmallint is enabled, we only check for W_SmallIntObject - it's
        # probably not useful to have a shortcut for W_IntObject at all then.
        if self.config.objspace.std.withsmallint:
            if type(w_obj) is W_SmallIntObject:
                return w_obj.intval
        else:
            if type(w_obj) is W_IntObject:
                return w_obj.intval
        return ObjSpace.getindex_w(self, w_obj, w_exception, objdescr)

    def call_method(self, w_obj, methname, *arg_w):
        if self.config.objspace.opcodes.CALL_METHOD:
            return callmethod.call_method_opt(self, w_obj, methname, *arg_w)
        else:
            return ObjSpace.call_method(self, w_obj, methname, *arg_w)

    def raise_key_error(self, w_key):
        e = self.call_function(self.w_KeyError, w_key)
        raise OperationError(self.w_KeyError, e)
