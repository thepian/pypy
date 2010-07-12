import sys

try:
    import ctypes
    import ctypes.util
except ImportError:
    ctypes = None

if sys.version_info >= (2, 6):
    load_library_kwargs = {'use_errno': True}
else:
    load_library_kwargs = {}

import os
from pypy import conftest
from pypy.rpython.lltypesystem import lltype, llmemory
from pypy.rpython.extfunc import ExtRegistryEntry
from pypy.rlib.objectmodel import Symbolic, ComputedIntSymbolic
from pypy.tool.uid import fixid
from pypy.tool.tls import tlsobject
from pypy.rlib.rarithmetic import r_uint, r_singlefloat, intmask
from pypy.annotation import model as annmodel
from pypy.rpython.llinterp import LLInterpreter, LLException
from pypy.rpython.lltypesystem.rclass import OBJECT, OBJECT_VTABLE
from pypy.rpython import raddress
from pypy.translator.platform import platform

def uaddressof(obj):
    return fixid(ctypes.addressof(obj))

_ctypes_cache = {}
_eci_cache = {}

def _setup_ctypes_cache():
    from pypy.rpython.lltypesystem import rffi
    _ctypes_cache.update({
        lltype.Signed:   ctypes.c_long,
        lltype.Unsigned: ctypes.c_ulong,
        lltype.Char:     ctypes.c_ubyte,
        rffi.DOUBLE:     ctypes.c_double,
        rffi.FLOAT:      ctypes.c_float,
        rffi.SIGNEDCHAR: ctypes.c_byte,
        rffi.UCHAR:      ctypes.c_ubyte,
        rffi.SHORT:      ctypes.c_short,
        rffi.USHORT:     ctypes.c_ushort,
        rffi.INT:        ctypes.c_int,
        rffi.INT_real:   ctypes.c_int,
        rffi.UINT:       ctypes.c_uint,
        rffi.LONG:       ctypes.c_long,
        rffi.ULONG:      ctypes.c_ulong,
        rffi.LONGLONG:   ctypes.c_longlong,
        rffi.ULONGLONG:  ctypes.c_ulonglong,
        rffi.SIZE_T:     ctypes.c_size_t,
        lltype.Bool:     ctypes.c_long, # XXX
        llmemory.Address:  ctypes.c_void_p,
        llmemory.GCREF:    ctypes.c_void_p,
        llmemory.WeakRef:  ctypes.c_void_p, # XXX
        })

    # for unicode strings, do not use ctypes.c_wchar because ctypes
    # automatically converts arrays into unicode strings.
    # Pick the unsigned int that has the same size.
    if ctypes.sizeof(ctypes.c_wchar) == ctypes.sizeof(ctypes.c_uint16):
        _ctypes_cache[lltype.UniChar] = ctypes.c_uint16
    else:
        _ctypes_cache[lltype.UniChar] = ctypes.c_uint32

def build_ctypes_struct(S, delayed_builders, max_n=None):
    def builder():
        # called a bit later to fill in _fields_
        # (to handle recursive structure pointers)
        fields = []
        for fieldname in S._names:
            FIELDTYPE = S._flds[fieldname]
            if max_n is not None and fieldname == S._arrayfld:
                cls = get_ctypes_array_of_size(FIELDTYPE, max_n)
            else:
                if isinstance(FIELDTYPE, lltype.Ptr):
                    cls = get_ctypes_type(FIELDTYPE, delayed_builders)
                else:
                    cls = get_ctypes_type(FIELDTYPE)
            fields.append((fieldname, cls))
        CStruct._fields_ = fields

    class CStruct(ctypes.Structure):
        # no _fields_: filled later by builder()

        def _malloc(cls, n=None):
            if S._arrayfld is None:
                if n is not None:
                    raise TypeError("%r is not variable-sized" % (S,))
                storage = cls()
                return storage
            else:
                if n is None:
                    raise TypeError("%r is variable-sized" % (S,))
                biggercls = build_ctypes_struct(S, None, n)
                bigstruct = biggercls()
                array = getattr(bigstruct, S._arrayfld)
                if hasattr(array, 'length'):
                    array.length = n
                return bigstruct
        _malloc = classmethod(_malloc)

    CStruct.__name__ = 'ctypes_%s' % (S,)
    if max_n is not None:
        CStruct._normalized_ctype = get_ctypes_type(S)
        builder()    # no need to be lazy here
    else:
        delayed_builders.append(builder)
    return CStruct

def build_ctypes_array(A, delayed_builders, max_n=0):
    assert max_n >= 0
    ITEM = A.OF
    ctypes_item = get_ctypes_type(ITEM, delayed_builders)
    # Python 2.5 ctypes can raise OverflowError on 64-bit builds
    for n in [sys.maxint, 2**31]:
        MAX_SIZE = n/64
        try:
            PtrType = ctypes.POINTER(MAX_SIZE * ctypes_item)
        except OverflowError, e:
            pass
        else:
            break
    else:
        raise e

    class CArray(ctypes.Structure):
        if not A._hints.get('nolength'):
            _fields_ = [('length', ctypes.c_long),
                        ('items',  max_n * ctypes_item)]
        else:
            _fields_ = [('items',  max_n * ctypes_item)]

        def _malloc(cls, n=None):
            if not isinstance(n, int):
                raise TypeError, "array length must be an int"
            biggercls = get_ctypes_array_of_size(A, n)
            bigarray = biggercls()
            if hasattr(bigarray, 'length'):
                bigarray.length = n
            return bigarray
        _malloc = classmethod(_malloc)

        def _indexable(self, index):
            assert index + 1 < MAX_SIZE
            p = ctypes.cast(ctypes.pointer(self.items), PtrType)
            return p.contents

        def _getitem(self, index, boundscheck=True):
            if boundscheck:
                items = self.items
            else:
                items = self._indexable(index)
            cobj = items[index]
            if isinstance(ITEM, lltype.ContainerType):
                return ctypes2lltype(lltype.Ptr(ITEM), ctypes.pointer(cobj))
            else:
                return ctypes2lltype(ITEM, cobj)

        def _setitem(self, index, value, boundscheck=True):
            if boundscheck:
                items = self.items
            else:
                items = self._indexable(index)
            cobj = lltype2ctypes(value)
            items[index] = cobj

    CArray.__name__ = 'ctypes_%s*%d' % (A, max_n)
    if max_n > 0:
        CArray._normalized_ctype = get_ctypes_type(A)
    return CArray

def get_ctypes_array_of_size(FIELDTYPE, max_n):
    if max_n > 0:
        # no need to cache the results in this case, because the exact
        # type is never seen - the array instances are cast to the
        # array's _normalized_ctype, which is always the same.
        return build_ctypes_array(FIELDTYPE, None, max_n)
    else:
        return get_ctypes_type(FIELDTYPE)

def get_ctypes_type(T, delayed_builders=None):
    try:
        return _ctypes_cache[T]
    except KeyError:
        toplevel = delayed_builders is None
        if toplevel:
            delayed_builders = []
        cls = build_new_ctypes_type(T, delayed_builders)
        if T not in _ctypes_cache:
            _ctypes_cache[T] = cls
        else:
            # check for buggy recursive structure logic
            assert _ctypes_cache[T] is cls
        if toplevel:
            complete_builders(delayed_builders)
        return cls

def build_new_ctypes_type(T, delayed_builders):
    if isinstance(T, lltype.Ptr):
        if isinstance(T.TO, lltype.FuncType):
            argtypes = [get_ctypes_type(ARG) for ARG in T.TO.ARGS
                        if ARG is not lltype.Void]
            if T.TO.RESULT is lltype.Void:
                restype = None
            else:
                restype = get_ctypes_type(T.TO.RESULT)
            return ctypes.CFUNCTYPE(restype, *argtypes)
        elif isinstance(T.TO, lltype.OpaqueType):
            return ctypes.c_void_p
        else:
            return ctypes.POINTER(get_ctypes_type(T.TO, delayed_builders))
    elif T is lltype.Void:
        return ctypes.c_long # opaque pointer
    elif isinstance(T, lltype.Struct):
        return build_ctypes_struct(T, delayed_builders)
    elif isinstance(T, lltype.Array):
        return build_ctypes_array(T, delayed_builders)
    elif isinstance(T, lltype.OpaqueType):
        if T is lltype.RuntimeTypeInfo:
            return ctypes.c_char * 2
        if T.hints.get('external', None) != 'C':
            raise TypeError("%s is not external" % T)
        return ctypes.c_char * T.hints['getsize']()
    else:
        _setup_ctypes_cache()
        if T in _ctypes_cache:
            return _ctypes_cache[T]
        raise NotImplementedError(T)

def complete_builders(delayed_builders):
    while delayed_builders:
        delayed_builders.pop()()

def convert_struct(container, cstruct=None):
    STRUCT = container._TYPE
    if cstruct is None:
        # if 'container' is an inlined substructure, convert the whole
        # bigger structure at once
        parent, parentindex = lltype.parentlink(container)
        if parent is not None:
            convert_struct(parent)
            return
        # regular case: allocate a new ctypes Structure of the proper type
        cls = get_ctypes_type(STRUCT)
        if STRUCT._arrayfld is not None:
            n = getattr(container, STRUCT._arrayfld).getlength()
        else:
            n = None
        cstruct = cls._malloc(n)
    add_storage(container, _struct_mixin, cstruct)
    for field_name in STRUCT._names:
        FIELDTYPE = getattr(STRUCT, field_name)
        field_value = getattr(container, field_name)
        if not isinstance(FIELDTYPE, lltype.ContainerType):
            # regular field
            if FIELDTYPE != lltype.Void:
                setattr(cstruct, field_name, lltype2ctypes(field_value))
        else:
            # inlined substructure/subarray
            if isinstance(FIELDTYPE, lltype.Struct):
                csubstruct = getattr(cstruct, field_name)
                convert_struct(field_value, csubstruct)
                subcontainer = getattr(container, field_name)
                substorage = subcontainer._storage
            elif field_name == STRUCT._arrayfld:    # inlined var-sized part
                csubarray = getattr(cstruct, field_name)
                convert_array(field_value, csubarray)
            else:
                raise NotImplementedError('inlined field', FIELDTYPE)
    remove_regular_struct_content(container)

def remove_regular_struct_content(container):
    STRUCT = container._TYPE
    for field_name in STRUCT._names:
        FIELDTYPE = getattr(STRUCT, field_name)
        if not isinstance(FIELDTYPE, lltype.ContainerType):
            delattr(container, field_name)

def convert_array(container, carray=None):
    ARRAY = container._TYPE
    if carray is None:
        # if 'container' is an inlined substructure, convert the whole
        # bigger structure at once
        parent, parentindex = lltype.parentlink(container)
        if parent is not None:
            convert_struct(parent)
            return
        # regular case: allocate a new ctypes array of the proper type
        cls = get_ctypes_type(ARRAY)
        carray = cls._malloc(container.getlength())
    add_storage(container, _array_mixin, carray)
    if not isinstance(ARRAY.OF, lltype.ContainerType):
        # fish that we have enough space
        ctypes_array = ctypes.cast(carray.items,
                                   ctypes.POINTER(carray.items._type_))
        for i in range(container.getlength()):
            item_value = container.items[i]    # fish fish
            ctypes_array[i] = lltype2ctypes(item_value)
        remove_regular_array_content(container)
    else:
        assert isinstance(ARRAY.OF, lltype.Struct)
        for i in range(container.getlength()):
            item_ptr = container.items[i]    # fish fish
            convert_struct(item_ptr, carray.items[i])

def remove_regular_array_content(container):
    for i in range(container.getlength()):
        container.items[i] = None

def struct_use_ctypes_storage(container, ctypes_storage):
    STRUCT = container._TYPE
    assert isinstance(STRUCT, lltype.Struct)
    add_storage(container, _struct_mixin, ctypes_storage)
    remove_regular_struct_content(container)
    for field_name in STRUCT._names:
        FIELDTYPE = getattr(STRUCT, field_name)
        if isinstance(FIELDTYPE, lltype.ContainerType):
            if isinstance(FIELDTYPE, lltype.Struct):
                struct_container = getattr(container, field_name)
                struct_storage = getattr(ctypes_storage, field_name)
                struct_use_ctypes_storage(struct_container, struct_storage)
                struct_container._setparentstructure(container, field_name)
            elif isinstance(FIELDTYPE, lltype.Array):
                assert FIELDTYPE._hints.get('nolength', False) == False
                arraycontainer = _array_of_known_length(FIELDTYPE)
                arraycontainer._storage = getattr(ctypes_storage, field_name)
                arraycontainer._setparentstructure(container, field_name)
                object.__setattr__(container, field_name, arraycontainer)
            else:
                raise NotImplementedError(FIELDTYPE)

# ____________________________________________________________
# Ctypes-aware subclasses of the _parentable classes

ALLOCATED = {}     # mapping {address: _container}

def get_common_subclass(cls1, cls2, cache={}):
    """Return a unique subclass with (cls1, cls2) as bases."""
    try:
        return cache[cls1, cls2]
    except KeyError:
        subcls = type('_ctypes_%s' % (cls1.__name__,),
                      (cls1, cls2),
                      {'__slots__': ()})
        cache[cls1, cls2] = subcls
        return subcls

def add_storage(instance, mixin_cls, ctypes_storage):
    """Put ctypes_storage on the instance, changing its __class__ so that it
    sees the methods of the given mixin class."""
    assert not isinstance(instance, _parentable_mixin)  # not yet
    subcls = get_common_subclass(mixin_cls, instance.__class__)
    instance.__class__ = subcls
    instance._storage = ctypes_storage

class _parentable_mixin(object):
    """Mixin added to _parentable containers when they become ctypes-based.
    (This is done by changing the __class__ of the instance to reference
    a subclass of both its original class and of this mixin class.)
    """
    __slots__ = ()

    def _ctypes_storage_was_allocated(self):
        addr = ctypes.addressof(self._storage)
        if addr in ALLOCATED:
            raise Exception("internal ll2ctypes error - "
                            "double conversion from lltype to ctypes?")
        # XXX don't store here immortal structures
        ALLOCATED[addr] = self

    def _free(self):
        self._check()   # no double-frees
        # allow the ctypes object to go away now
        addr = ctypes.addressof(self._storage)
        try:
            del ALLOCATED[addr]
        except KeyError:
            raise Exception("invalid free() - data already freed or "
                            "not allocated from RPython at all")
        self._storage = None

    def __eq__(self, other):
        if isinstance(other, _llgcopaque):
            addressof_other = other.intval
        else:
            if not isinstance(other, lltype._parentable):
                return False
            if self._storage is None or other._storage is None:
                raise RuntimeError("pointer comparison with a freed structure")
            if other._storage is True:
                return False    # the other container is not ctypes-based
            addressof_other = ctypes.addressof(other._storage)
        # both containers are ctypes-based, compare by address
        return (ctypes.addressof(self._storage) == addressof_other)

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        if self._storage is not None:
            return ctypes.addressof(self._storage)
        else:
            return object.__hash__(self)

    def __repr__(self):
        if self._storage is None:
            return '<freed C object %s>' % (self._TYPE,)
        else:
            return '<C object %s at 0x%x>' % (self._TYPE,
                                              uaddressof(self._storage),)

    def __str__(self):
        return repr(self)

class _struct_mixin(_parentable_mixin):
    """Mixin added to _struct containers when they become ctypes-based."""
    __slots__ = ()

    def __getattr__(self, field_name):
        T = getattr(self._TYPE, field_name)
        cobj = getattr(self._storage, field_name)
        return ctypes2lltype(T, cobj)

    def __setattr__(self, field_name, value):
        if field_name.startswith('_'):
            object.__setattr__(self, field_name, value)  # '_xxx' attributes
        else:
            cobj = lltype2ctypes(value)
            setattr(self._storage, field_name, cobj)

class _array_mixin(_parentable_mixin):
    """Mixin added to _array containers when they become ctypes-based."""
    __slots__ = ()

    def getitem(self, index, uninitialized_ok=False):
        return self._storage._getitem(index)

    def setitem(self, index, value):
        self._storage._setitem(index, value)

class _array_of_unknown_length(_parentable_mixin, lltype._parentable):
    _kind = "array"
    __slots__ = ()

    def getbounds(self):
        # we have no clue, so we allow whatever index
        return 0, sys.maxint

    def getitem(self, index, uninitialized_ok=False):
        return self._storage._getitem(index, boundscheck=False)

    def setitem(self, index, value):
        self._storage._setitem(index, value, boundscheck=False)

    def getitems(self):
        if self._TYPE.OF != lltype.Char:
            raise Exception("cannot get all items of an unknown-length "
                            "array of %r" % self._TYPE.OF)
        _items = []
        i = 0
        while 1:
            nextitem = self.getitem(i)
            if nextitem == '\x00':
                _items.append('\x00')
                return _items
            _items.append(nextitem)
            i += 1
        
    items = property(getitems)

class _array_of_known_length(_array_of_unknown_length):
    __slots__ = ()

    def getlength(self):
        return self._storage.length

    def getbounds(self):
        return 0, self.getlength()

# ____________________________________________________________

def _find_parent(llobj):
    parent, parentindex = lltype.parentlink(llobj)
    if parent is None:
        return llobj, 0
    next_p, next_i = _find_parent(parent)
    if isinstance(parentindex, int):
        c_tp = get_ctypes_type(lltype.typeOf(parent))
        sizeof = ctypes.sizeof(get_ctypes_type(lltype.typeOf(parent).OF))
        ofs = c_tp.items.offset + parentindex * sizeof
        return next_p, next_i + ofs
    else:
        c_tp = get_ctypes_type(lltype.typeOf(parent))
        ofs = getattr(c_tp, parentindex).offset
        return next_p, next_i + ofs

# ____________________________________________________________

# XXX THIS IS A HACK XXX
# ctypes does not keep callback arguments alive. So we do. Forever
# we need to think deeper how to approach this problem
# additionally, this adds mess to __del__ "semantics"
_all_callbacks = {}
_all_callbacks_results = []
_int2obj = {}
_callback_exc_info = None

def get_rtyper():
    llinterp = LLInterpreter.current_interpreter
    if llinterp is not None:
        return llinterp.typer
    else:
        return None

def lltype2ctypes(llobj, normalize=True):
    """Convert the lltype object 'llobj' to its ctypes equivalent.
    'normalize' should only be False in tests, where we want to
    inspect the resulting ctypes object manually.
    """
    if isinstance(llobj, lltype._uninitialized):
        return uninitialized2ctypes(llobj.TYPE)
    if isinstance(llobj, llmemory.AddressAsInt):
        cobj = ctypes.cast(lltype2ctypes(llobj.adr), ctypes.c_void_p)
        res = intmask(cobj.value)
        _int2obj[res] = llobj.adr.ptr._obj
        return res
    if isinstance(llobj, llmemory.fakeaddress):
        llobj = llobj.ptr or 0

    T = lltype.typeOf(llobj)

    if isinstance(T, lltype.Ptr):
        if not llobj:   # NULL pointer
            if T == llmemory.GCREF:
                return ctypes.c_void_p(0)
            return get_ctypes_type(T)()

        if T == llmemory.GCREF:
            if isinstance(llobj._obj, _llgcopaque):
                return ctypes.c_void_p(llobj._obj.intval)
            container = llobj._obj.container
            T = lltype.Ptr(lltype.typeOf(container))
            # otherwise it came from integer and we want a c_void_p with
            # the same valu
        else:
            container = llobj._obj
        if isinstance(T.TO, lltype.FuncType):
            # XXX a temporary workaround for comparison of lltype.FuncType
            key = llobj._obj.__dict__.copy()
            key['_TYPE'] = repr(key['_TYPE'])
            items = key.items()
            items.sort()
            key = tuple(items)
            if key in _all_callbacks:
                return _all_callbacks[key]
            v1voidlist = [(i, getattr(container, '_void' + str(i), None))
                             for i in range(len(T.TO.ARGS))
                                 if T.TO.ARGS[i] is lltype.Void]
            def callback_internal(*cargs):
                cargs = list(cargs)
                for v1 in v1voidlist:
                    cargs.insert(v1[0], v1[1])
                assert len(cargs) == len(T.TO.ARGS)
                llargs = []
                for ARG, carg in zip(T.TO.ARGS, cargs):
                    if ARG is lltype.Void:
                        llargs.append(carg)
                    else:
                        llargs.append(ctypes2lltype(ARG, carg))
                if hasattr(container, 'graph'):
                    if LLInterpreter.current_interpreter is None:
                        raise AssertionError
                    llinterp = LLInterpreter.current_interpreter
                    try:
                        llres = llinterp.eval_graph(container.graph, llargs)
                    except LLException, lle:
                        llinterp._store_exception(lle)
                        return 0
                    #except:
                    #    import pdb
                    #    pdb.set_trace()
                else:
                    try:
                        llres = container._callable(*llargs)
                    except LLException, lle:
                        llinterp = LLInterpreter.current_interpreter
                        llinterp._store_exception(lle)
                        return 0
                assert lltype.typeOf(llres) == T.TO.RESULT
                if T.TO.RESULT is lltype.Void:
                    return None
                res = lltype2ctypes(llres)
                if isinstance(T.TO.RESULT, lltype.Ptr):
                    _all_callbacks_results.append(res)
                    res = ctypes.cast(res, ctypes.c_void_p).value
                    if res is None:
                        return 0
                return res

            def callback(*cargs):
                try:
                    return callback_internal(*cargs)
                except:
                    import sys
                    #if conftest.option.usepdb:
                    #    import pdb; pdb.post_mortem(sys.exc_traceback)
                    global _callback_exc_info
                    _callback_exc_info = sys.exc_info()
                    raise

            if isinstance(T.TO.RESULT, lltype.Ptr):
                TMod = lltype.Ptr(lltype.FuncType(T.TO.ARGS,
                                                  lltype.Signed))
                ctypes_func_type = get_ctypes_type(TMod)
                res = ctypes_func_type(callback)
                ctypes_func_type = get_ctypes_type(T)
                res = ctypes.cast(res, ctypes_func_type)
            else:
                ctypes_func_type = get_ctypes_type(T)
                res = ctypes_func_type(callback)
            _all_callbacks[key] = res
            key2 = intmask(ctypes.cast(res, ctypes.c_void_p).value)
            _int2obj[key2] = container
            return res

        index = 0
        if isinstance(container, lltype._subarray):
            topmost, index = _find_parent(container)
            container = topmost
            T = lltype.Ptr(lltype.typeOf(container))

        if container._storage is None:
            raise RuntimeError("attempting to pass a freed structure to C")
        if container._storage is True:
            # container has regular lltype storage, convert it to ctypes
            if isinstance(T.TO, lltype.Struct):
                convert_struct(container)
            elif isinstance(T.TO, lltype.Array):
                convert_array(container)
            elif isinstance(T.TO, lltype.OpaqueType):
                if T.TO != lltype.RuntimeTypeInfo:
                    cbuf = ctypes.create_string_buffer(T.TO.hints['getsize']())
                else:
                    cbuf = ctypes.create_string_buffer("\x00")
                cbuf = ctypes.cast(cbuf, ctypes.c_void_p)
                add_storage(container, _parentable_mixin, cbuf)
            else:
                raise NotImplementedError(T)
            container._ctypes_storage_was_allocated()

        if isinstance(T.TO, lltype.OpaqueType):
            return container._storage

        storage = container._storage
        p = ctypes.pointer(storage)
        if index:
            p = ctypes.cast(p, ctypes.c_void_p)
            p = ctypes.c_void_p(p.value + index)
            c_tp = get_ctypes_type(T.TO)
            storage._normalized_ctype = c_tp
        if normalize and hasattr(storage, '_normalized_ctype'):
            p = ctypes.cast(p, ctypes.POINTER(storage._normalized_ctype))
        if lltype.typeOf(llobj) == llmemory.GCREF:
            p = ctypes.cast(p, ctypes.c_void_p)
        return p

    if isinstance(llobj, Symbolic):
        if isinstance(llobj, llmemory.ItemOffset):
            llobj = ctypes.sizeof(get_ctypes_type(llobj.TYPE)) * llobj.repeat
        elif isinstance(llobj, ComputedIntSymbolic):
            llobj = llobj.compute_fn()
        else:
            raise NotImplementedError(llobj)  # don't know about symbolic value

    if T is lltype.Char or T is lltype.UniChar:
        return ord(llobj)

    if T is lltype.SingleFloat:
        return ctypes.c_float(float(llobj))

    return llobj

def ctypes2lltype(T, cobj):
    """Convert the ctypes object 'cobj' to its lltype equivalent.
    'T' is the expected lltype type.
    """
    if T is lltype.Void:
        return None
    if isinstance(T, lltype.Ptr):
        if not cobj or not ctypes.cast(cobj, ctypes.c_void_p).value:   # NULL pointer
            # CFunctionType.__nonzero__ is broken before Python 2.6
            return lltype.nullptr(T.TO)
        if isinstance(T.TO, lltype.Struct):
            REAL_TYPE = T.TO
            if T.TO._arrayfld is not None:
                carray = getattr(cobj.contents, T.TO._arrayfld)
                container = lltype._struct(T.TO, carray.length)
            else:
                # special treatment of 'OBJECT' subclasses
                if get_rtyper() and lltype._castdepth(REAL_TYPE, OBJECT) >= 0:
                    # figure out the real type of the object
                    containerheader = lltype._struct(OBJECT)
                    cobjheader = ctypes.cast(cobj,
                                       get_ctypes_type(lltype.Ptr(OBJECT)))
                    struct_use_ctypes_storage(containerheader,
                                              cobjheader.contents)
                    REAL_TYPE = get_rtyper().get_type_for_typeptr(
                        containerheader.typeptr)
                    REAL_T = lltype.Ptr(REAL_TYPE)
                    cobj = ctypes.cast(cobj, get_ctypes_type(REAL_T))
                container = lltype._struct(REAL_TYPE)
            struct_use_ctypes_storage(container, cobj.contents)
            if REAL_TYPE != T.TO:
                p = container._as_ptr()
                container = lltype.cast_pointer(T, p)._as_obj()
            # special treatment of 'OBJECT_VTABLE' subclasses
            if get_rtyper() and lltype._castdepth(REAL_TYPE,
                                                  OBJECT_VTABLE) >= 0:
                # figure out the real object that this vtable points to,
                # and just return that
                p = get_rtyper().get_real_typeptr_for_typeptr(
                    container._as_ptr())
                container = lltype.cast_pointer(T, p)._as_obj()
        elif isinstance(T.TO, lltype.Array):
            if T.TO._hints.get('nolength', False):
                container = _array_of_unknown_length(T.TO)
                container._storage = cobj.contents
            else:
                container = _array_of_known_length(T.TO)
                container._storage = cobj.contents
        elif isinstance(T.TO, lltype.FuncType):
            cobjkey = intmask(ctypes.cast(cobj, ctypes.c_void_p).value)
            if cobjkey in _int2obj:
                container = _int2obj[cobjkey]
            else:
                _callable = get_ctypes_trampoline(T.TO, cobj)
                return lltype.functionptr(T.TO, getattr(cobj, '__name__', '?'),
                                          _callable=_callable)
        elif isinstance(T.TO, lltype.OpaqueType):
            if T == llmemory.GCREF:
                container = _llgcopaque(cobj)
            else:
                container = lltype._opaque(T.TO)
                container._storage = ctypes.cast(cobj, ctypes.c_void_p)
        else:
            raise NotImplementedError(T)
        llobj = lltype._ptr(T, container, solid=True)
    elif T is llmemory.Address:
        if cobj is None:
            llobj = llmemory.NULL
        else:
            llobj = _lladdress(cobj)
    elif T is lltype.Char:
        llobj = chr(cobj)
    elif T is lltype.UniChar:
        llobj = unichr(cobj)
    elif T is lltype.Signed:
        llobj = cobj
    elif T is lltype.Bool:
        assert cobj == True or cobj == False    # 0 and 1 work too
        llobj = bool(cobj)
    elif T is lltype.SingleFloat:
        if isinstance(cobj, ctypes.c_float):
            cobj = cobj.value
        llobj = r_singlefloat(cobj)
    elif T is lltype.Void:
        llobj = cobj
    else:
        from pypy.rpython.lltypesystem import rffi
        try:
            inttype = rffi.platform.numbertype_to_rclass[T]
        except KeyError:
            llobj = cobj
        else:
            llobj = inttype(cobj)

    assert lltype.typeOf(llobj) == T
    return llobj

def uninitialized2ctypes(T):
    "For debugging, create a ctypes object filled with 0xDD."
    ctype = get_ctypes_type(T)
    cobj = ctype()
    size = ctypes.sizeof(cobj)
    p = ctypes.cast(ctypes.pointer(cobj),
                    ctypes.POINTER(ctypes.c_ubyte * size))
    for i in range(size):
        p.contents[i] = 0xDD
    if isinstance(T, lltype.Primitive):
        return cobj.value
    else:
        return cobj

# __________ the standard C library __________

if ctypes:
    def get_libc_name():
        if sys.platform == 'win32':
            # Parses sys.version and deduces the version of the compiler
            import distutils.msvccompiler
            version = distutils.msvccompiler.get_build_version()
            if version is None:
                # This logic works with official builds of Python.
                if sys.version_info < (2, 4):
                    clibname = 'msvcrt'
                else:
                    clibname = 'msvcr71'
            else:
                if version <= 6:
                    clibname = 'msvcrt'
                else:
                    clibname = 'msvcr%d' % (version * 10)

            # If python was built with in debug mode
            import imp
            if imp.get_suffixes()[0][0] == '_d.pyd':
                clibname += 'd'

            return clibname+'.dll'
        else:
            return ctypes.util.find_library('c')
        
    libc_name = get_libc_name()     # Make sure the name is determined during import, not at runtime
    # XXX is this always correct???
    standard_c_lib = ctypes.CDLL(get_libc_name(), **load_library_kwargs)

# ____________________________________________

# xxx from ctypes.util, this code is a useful fallback on darwin too
if sys.platform == 'darwin':
    # Andreas Degert's find function using gcc
    import re, tempfile, errno

    def _findLib_gcc_fallback(name):
        expr = r'[^\(\)\s]*lib%s\.[^\(\)\s]*' % re.escape(name)
        fdout, ccout = tempfile.mkstemp()
        os.close(fdout)
        cmd = 'if type gcc >/dev/null 2>&1; then CC=gcc; else CC=cc; fi;' \
              '$CC -Wl,-t -o ' + ccout + ' 2>&1 -l' + name
        try:
            f = os.popen(cmd)
            trace = f.read()
            f.close()
        finally:
            try:
                os.unlink(ccout)
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise
        res = re.search(expr, trace)
        if not res:
            return None
        return res.group(0)
else:
    _findLib_gcc_fallback = lambda name: None

def get_ctypes_callable(funcptr, calling_conv):
    if not ctypes:
        raise ImportError("ctypes is needed to use ll2ctypes")

    def get_on_lib(lib, elem):
        """ Wrapper to always use lib[func] instead of lib.func
        """
        try:
            return lib[elem]
        except AttributeError:
            pass
    
    old_eci = funcptr._obj.compilation_info
    funcname = funcptr._obj._name
    if hasattr(old_eci, '_with_ctypes'):
        eci = old_eci._with_ctypes
    else:
        try:
            eci = _eci_cache[old_eci]
        except KeyError:
            eci = old_eci.compile_shared_lib()
            _eci_cache[old_eci] = eci

    libraries = eci.testonly_libraries + eci.libraries + eci.frameworks

    FUNCTYPE = lltype.typeOf(funcptr).TO
    if not libraries:
        cfunc = get_on_lib(standard_c_lib, funcname)
        # XXX magic: on Windows try to load the function from 'kernel32' too
        if cfunc is None and hasattr(ctypes, 'windll'):
            cfunc = get_on_lib(ctypes.windll.kernel32, funcname)
    else:
        cfunc = None
        not_found = []
        for libname in libraries:
            libpath = None
            ext = platform.so_ext
            prefixes = platform.so_prefixes
            for dir in eci.library_dirs:
                if libpath:
                    break
                for prefix in prefixes:
                    tryfile = os.path.join(dir, prefix + libname + '.' + ext)
                    if os.path.isfile(tryfile):
                        libpath = tryfile
                        break
            if not libpath:
                libpath = ctypes.util.find_library(libname)
                if not libpath:
                    libpath = _findLib_gcc_fallback(libname)
                if not libpath and os.path.isabs(libname):
                    libpath = libname
            if libpath:
                dllclass = getattr(ctypes, calling_conv + 'dll')
                # on ie slackware there was need for RTLD_GLOBAL here.
                # this breaks a lot of things, since passing RTLD_GLOBAL
                # creates symbol conflicts on C level.
                clib = dllclass._dlltype(libpath, **load_library_kwargs)
                cfunc = get_on_lib(clib, funcname)
                if cfunc is not None:
                    break
            else:
                not_found.append(libname)

    if cfunc is None:
        # function name not found in any of the libraries
        if not libraries:
            place = 'the standard C library (missing libraries=...?)'
        elif len(not_found) == len(libraries):
            if len(not_found) == 1:
                raise NotImplementedError(
                    'cannot find the library %r' % (not_found[0],))
            else:
                raise NotImplementedError(
                    'cannot find any of the libraries %r' % (not_found,))
        elif len(libraries) == 1:
            place = 'library %r' % (libraries[0],)
        else:
            place = 'any of the libraries %r' % (libraries,)
            if not_found:
                place += ' (did not find %r)' % (not_found,)
        raise NotImplementedError("function %r not found in %s" % (
            funcname, place))

    # get_ctypes_type() can raise NotImplementedError too
    cfunc.argtypes = [get_ctypes_type(T) for T in FUNCTYPE.ARGS
                      if not T is lltype.Void]
    if FUNCTYPE.RESULT is lltype.Void:
        cfunc.restype = None
    else:
        cfunc.restype = get_ctypes_type(FUNCTYPE.RESULT)
    return cfunc

class LL2CtypesCallable(object):
    # a special '_callable' object that invokes ctypes

    def __init__(self, FUNCTYPE, calling_conv):
        self.FUNCTYPE = FUNCTYPE
        self.calling_conv = calling_conv
        self.trampoline = None
        #self.funcptr = ...  set later

    def __call__(self, *argvalues):
        if self.trampoline is None:
            # lazily build the corresponding ctypes function object
            cfunc = get_ctypes_callable(self.funcptr, self.calling_conv)
            self.trampoline = get_ctypes_trampoline(self.FUNCTYPE, cfunc)
        # perform the call
        return self.trampoline(*argvalues)

def get_ctypes_trampoline(FUNCTYPE, cfunc):
    RESULT = FUNCTYPE.RESULT
    container_arguments = []
    for i in range(len(FUNCTYPE.ARGS)):
        if isinstance(FUNCTYPE.ARGS[i], lltype.ContainerType):
            container_arguments.append(i)
    void_arguments = []
    for i in range(len(FUNCTYPE.ARGS)):
        if FUNCTYPE.ARGS[i] is lltype.Void:
            void_arguments.append(i)
    def invoke_via_ctypes(*argvalues):
        global _callback_exc_info
        cargs = []
        for i in range(len(argvalues)):
            if i not in void_arguments:
                cvalue = lltype2ctypes(argvalues[i])
                if i in container_arguments:
                    cvalue = cvalue.contents
                cargs.append(cvalue)
        _callback_exc_info = None
        _restore_c_errno()
        cres = cfunc(*cargs)
        _save_c_errno()
        if _callback_exc_info:
            etype, evalue, etb = _callback_exc_info
            _callback_exc_info = None
            raise etype, evalue, etb
        return ctypes2lltype(RESULT, cres)
    return invoke_via_ctypes

def force_cast(RESTYPE, value):
    """Cast a value to a result type, trying to use the same rules as C."""
    if not isinstance(RESTYPE, lltype.LowLevelType):
        raise TypeError("rffi.cast() first arg should be a TYPE")
    if isinstance(value, llmemory.AddressAsInt):
        value = value.adr
    if isinstance(value, llmemory.fakeaddress):
        value = value.ptr or 0
    TYPE1 = lltype.typeOf(value)
    cvalue = lltype2ctypes(value)
    cresulttype = get_ctypes_type(RESTYPE)
    if isinstance(TYPE1, lltype.Ptr):
        if isinstance(RESTYPE, lltype.Ptr):
            # shortcut: ptr->ptr cast
            cptr = ctypes.cast(cvalue, cresulttype)
            return ctypes2lltype(RESTYPE, cptr)
        # first cast the input pointer to an integer
        cvalue = ctypes.cast(cvalue, ctypes.c_void_p).value
        if cvalue is None:
            cvalue = 0
    elif isinstance(cvalue, (str, unicode)):
        cvalue = ord(cvalue)     # character -> integer

    if not isinstance(cvalue, (int, long, float)):
        raise NotImplementedError("casting %r to %r" % (TYPE1, RESTYPE))

    if isinstance(RESTYPE, lltype.Ptr):
        # upgrade to a more recent ctypes (e.g. 1.0.2) if you get
        # an OverflowError on the following line.
        cvalue = ctypes.cast(ctypes.c_void_p(cvalue), cresulttype)
    else:
        cvalue = cresulttype(cvalue).value   # mask high bits off if needed
    return ctypes2lltype(RESTYPE, cvalue)

class ForceCastEntry(ExtRegistryEntry):
    _about_ = force_cast

    def compute_result_annotation(self, s_RESTYPE, s_value):
        assert s_RESTYPE.is_constant()
        RESTYPE = s_RESTYPE.const
        return annmodel.lltype_to_annotation(RESTYPE)

    def specialize_call(self, hop):
        hop.exception_cannot_occur()
        s_RESTYPE = hop.args_s[0]
        assert s_RESTYPE.is_constant()
        RESTYPE = s_RESTYPE.const
        v_arg = hop.inputarg(hop.args_r[1], arg=1)
        return hop.genop('force_cast', [v_arg], resulttype = RESTYPE)

def typecheck_ptradd(T):
    # --- ptradd() is only for pointers to non-GC, no-length arrays.
    assert isinstance(T, lltype.Ptr)
    assert isinstance(T.TO, lltype.Array)
    assert T.TO._hints.get('nolength')

def force_ptradd(ptr, n):
    """'ptr' must be a pointer to an array.  Equivalent of 'ptr + n' in
    C, i.e. gives a pointer to the n'th item of the array.  The type of
    the result is again a pointer to an array, the same as the type of
    'ptr'.
    """
    T = lltype.typeOf(ptr)
    typecheck_ptradd(T)
    ctypes_item_type = get_ctypes_type(T.TO.OF)
    ctypes_arrayptr_type = get_ctypes_type(T)
    cptr = lltype2ctypes(ptr)
    baseaddr = ctypes.addressof(cptr.contents.items)
    addr = baseaddr + n * ctypes.sizeof(ctypes_item_type)
    cptr = ctypes.cast(ctypes.c_void_p(addr), ctypes_arrayptr_type)
    return ctypes2lltype(T, cptr)

class ForcePtrAddEntry(ExtRegistryEntry):
    _about_ = force_ptradd

    def compute_result_annotation(self, s_ptr, s_n):
        assert isinstance(s_n, annmodel.SomeInteger)
        assert isinstance(s_ptr, annmodel.SomePtr)
        typecheck_ptradd(s_ptr.ll_ptrtype)
        return annmodel.lltype_to_annotation(s_ptr.ll_ptrtype)

    def specialize_call(self, hop):
        hop.exception_cannot_occur()
        v_ptr, v_n = hop.inputargs(hop.args_r[0], lltype.Signed)
        return hop.genop('direct_ptradd', [v_ptr, v_n],
                         resulttype = v_ptr.concretetype)

class _lladdress(long):
    _TYPE = llmemory.Address

    def __new__(cls, void_p):
        if isinstance(void_p, (int, long)):
            void_p = ctypes.c_void_p(void_p)
        self = long.__new__(cls, void_p.value)
        self.void_p = void_p
        self.intval = intmask(void_p.value)
        return self

    def _cast_to_ptr(self, TP):
        return force_cast(TP, self.intval)

    def __repr__(self):
        return '<_lladdress %s>' % (self.void_p,)

    def __eq__(self, other):
        if not isinstance(other, (int, long)):
            other = cast_adr_to_int(other)
        return intmask(other) == self.intval

    def __ne__(self, other):
        return not self == other

class _llgcopaque(lltype._container):
    _TYPE = llmemory.GCREF.TO
    _name = "_llgcopaque"

    def __init__(self, void_p):
        if isinstance(void_p, (int, long)):
            self.intval = intmask(void_p)
        else:
            self.intval = intmask(void_p.value)

    def __eq__(self, other):
        if isinstance(other, _llgcopaque):
            return self.intval == other.intval
        storage = object()
        if hasattr(other, 'container'):
            storage = other.container._storage
        else:
            storage = other._storage

        if storage in (None, True):
            return False
        return force_cast(lltype.Signed, other._as_ptr()) == self.intval

    def __ne__(self, other):
        return not self == other

    def _cast_to_ptr(self, PTRTYPE):
         return force_cast(PTRTYPE, self.intval)

##     def _cast_to_int(self):
##         return self.intval

##     def _cast_to_adr(self):
##         return _lladdress(self.intval)

def cast_adr_to_int(addr):
    if isinstance(addr, llmemory.fakeaddress):
        # use ll2ctypes to obtain a real ctypes-based representation of
        # the memory, and cast that address as an integer
        if addr.ptr is None:
            res = 0
        else:
            res = force_cast(lltype.Signed, addr.ptr)
    else:
        res = addr._cast_to_int()
    if res > sys.maxint:
        res = res - 2*(sys.maxint + 1)
        assert int(res) == res
        return int(res)
    return res

class CastAdrToIntEntry(ExtRegistryEntry):
    _about_ = cast_adr_to_int

    def compute_result_annotation(self, s_addr):
        return annmodel.SomeInteger()

    def specialize_call(self, hop):
        assert isinstance(hop.args_r[0], raddress.AddressRepr)
        adr, = hop.inputargs(hop.args_r[0])
        hop.exception_cannot_occur()
        return hop.genop('cast_adr_to_int', [adr],
                         resulttype = lltype.Signed)

# ____________________________________________________________
# errno

# this saves in a thread-local way the "current" value that errno
# should have in C.  We have to save it away from one external C function
# call to the next.  Otherwise a non-zero value left behind will confuse
# CPython itself a bit later, and/or CPython will stamp on it before we
# try to inspect it via rposix.get_errno().
TLS = tlsobject()

# helpers to save/restore the C-level errno -- platform-specific because
# ctypes doesn't just do the right thing and expose it directly :-(

# on 2.6 ctypes does it right, use it

if sys.version_info >= (2, 6):
    def _save_c_errno():
        TLS.errno = ctypes.get_errno()

    def _restore_c_errno():
        pass

else:
    def _where_is_errno():
        raise NotImplementedError("don't know how to get the C-level errno!")

    def _save_c_errno():
        errno_p = _where_is_errno()
        TLS.errno = errno_p.contents.value
        errno_p.contents.value = 0

    def _restore_c_errno():
        if hasattr(TLS, 'errno'):
            _where_is_errno().contents.value = TLS.errno

    if ctypes:
        if sys.platform == 'win32':
            standard_c_lib._errno.restype = ctypes.POINTER(ctypes.c_int)
            def _where_is_errno():
                return standard_c_lib._errno()

        elif sys.platform in ('linux2', 'freebsd6'):
            standard_c_lib.__errno_location.restype = ctypes.POINTER(ctypes.c_int)
            def _where_is_errno():
                return standard_c_lib.__errno_location()

        elif sys.platform in ('darwin', 'freebsd7'):
            standard_c_lib.__error.restype = ctypes.POINTER(ctypes.c_int)
            def _where_is_errno():
                return standard_c_lib.__error()
