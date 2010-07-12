import _rawffi
import weakref
import sys

SIMPLE_TYPE_CHARS = "cbBhHiIlLdfuzZqQPXOv"

from _ctypes.basics import _CData, _CDataMeta, cdata_from_address,\
     CArgObject
from _ctypes.builtin import ConvMode
from _ctypes.array import Array
from _ctypes.pointer import _Pointer

class NULL(object):
    pass
NULL = NULL()

TP_TO_DEFAULT = {
        'c': 0,
        'u': 0,
        'b': 0,
        'B': 0,
        'h': 0,
        'H': 0,
        'i': 0,
        'I': 0,
        'l': 0,
        'L': 0,
        'q': 0,
        'Q': 0,
        'f': 0.0,
        'd': 0.0,
        'P': None,
        # not part of struct
        'O': NULL,
        'z': None,
        'Z': None,
}

if sys.platform == 'win32':
    TP_TO_DEFAULT['X'] = NULL
    TP_TO_DEFAULT['v'] = 0

DEFAULT_VALUE = object()

class GlobalPyobjContainer(object):
    def __init__(self):
        self.objs = []

    def add(self, obj):
        num = len(self.objs)
        self.objs.append(weakref.ref(obj))
        return num

    def get(self, num):
        return self.objs[num]()

pyobj_container = GlobalPyobjContainer()

def generic_xxx_p_from_param(cls, value):
    from _ctypes import Array, _Pointer
    if value is None:
        return cls(None)
    if isinstance(value, basestring):
        return cls(value)
    if isinstance(value, _SimpleCData) and \
           type(value)._type_ in 'zZP':
        return value
    return None # eventually raise

def from_param_char_p(cls, value):
    "used by c_char_p and c_wchar_p subclasses"
    res = generic_xxx_p_from_param(cls, value)
    if res is not None:
        return res
    if isinstance(value, (Array, _Pointer)):
        from ctypes import c_char, c_byte, c_wchar
        if type(value)._type_ in [c_char, c_byte, c_wchar]:
            return value

def from_param_void_p(cls, value):
    "used by c_void_p subclasses"
    res = generic_xxx_p_from_param(cls, value)
    if res is not None:
        return res
    if isinstance(value, Array):
        return value
    if isinstance(value, _Pointer):
        return cls.from_address(value._buffer.buffer)

FROM_PARAM_BY_TYPE = {
    'z': from_param_char_p,
    'Z': from_param_char_p,
    'P': from_param_void_p,
    }

class SimpleType(_CDataMeta):
    def __new__(self, name, bases, dct):
        try:
            tp = dct['_type_']
        except KeyError:
            for base in bases:
                if hasattr(base, '_type_'):
                    tp = base._type_
                    break
            else:
                raise AttributeError("cannot find _type_ attribute")
        if (not isinstance(tp, str) or
            not len(tp) == 1 or
            tp not in SIMPLE_TYPE_CHARS):
            raise ValueError('%s is not a type character' % (tp))
        default = TP_TO_DEFAULT[tp]
        ffiarray = _rawffi.Array(tp)
        result = type.__new__(self, name, bases, dct)
        result._ffiargshape = tp
        result._ffishape = tp
        result._fficompositesize = None
        result._ffiarray = ffiarray
        if tp == 'z':
            # c_char_p
            from _ctypes import Array, _Pointer

            def _getvalue(self):
                addr = self._buffer[0]
                if addr == 0:
                    return None
                else:
                    return _rawffi.charp2string(addr)

            def _setvalue(self, value):
                if isinstance(value, basestring):
                    if isinstance(value, unicode):
                        value = value.encode(ConvMode.encoding,
                                             ConvMode.errors)
                    #self._objects = value
                    array = _rawffi.Array('c')(len(value)+1, value)
                    value = array.buffer
                    self._objects = {'0': CArgObject(array)}
                elif value is None:
                    value = 0
                self._buffer[0] = value
            result.value = property(_getvalue, _setvalue)
        elif tp == 'Z':
            # c_wchar_p
            from _ctypes import Array, _Pointer, _wstring_at_addr
            def _getvalue(self):
                addr = self._buffer[0]
                if addr == 0:
                    return None
                else:
                    return _wstring_at_addr(addr, -1)

            def _setvalue(self, value):
                if isinstance(value, basestring):
                    if isinstance(value, str):
                        value = value.decode(ConvMode.encoding,
                                             ConvMode.errors)
                    #self._objects = value
                    array = _rawffi.Array('u')(len(value)+1, value)
                    value = array.buffer
                    self._objects = {'0': CArgObject(array)}
                elif value is None:
                    value = 0
                self._buffer[0] = value
            result.value = property(_getvalue, _setvalue)

        elif tp == 'P':
            # c_void_p

            def _getvalue(self):
                addr = self._buffer[0]
                if addr == 0:
                    return None
                return addr

            def _setvalue(self, value):
                if isinstance(value, str):
                    array = _rawffi.Array('c')(len(value)+1, value)
                    value = array.buffer
                    self._objects = {'0': CArgObject(array)}
                elif value is None:
                    value = 0
                self._buffer[0] = value
            result.value = property(_getvalue, _setvalue)            
        
        elif tp == 'u':
            def _setvalue(self, val):
                if isinstance(val, str):
                    val = val.decode(ConvMode.encoding, ConvMode.errors)
                # possible if we use 'ignore'
                if val:
                    self._buffer[0] = val
            def _getvalue(self):
                return self._buffer[0]
            result.value = property(_getvalue, _setvalue)

        elif tp == 'c':
            def _setvalue(self, val):
                if isinstance(val, unicode):
                    val = val.encode(ConvMode.encoding, ConvMode.errors)
                if val:
                    self._buffer[0] = val
            def _getvalue(self):
                return self._buffer[0]
            result.value = property(_getvalue, _setvalue)

        elif tp == 'O':
            def _setvalue(self, val):
                num = pyobj_container.add(val)
                self._buffer[0] = num
            def _getvalue(self):
                return pyobj_container.get(self._buffer[0])
            result.value = property(_getvalue, _setvalue)

        elif tp == 'X':
            from ctypes import windll
            SysAllocStringLen = windll.oleaut32.SysAllocStringLen
            SysStringLen = windll.oleaut32.SysStringLen
            SysFreeString = windll.oleaut32.SysFreeString
            from _ctypes import _wstring_at_addr
            def _getvalue(self):
                addr = self._buffer[0]
                if addr == 0:
                    return None
                else:
                    size = SysStringLen(addr)
                    return _wstring_at_addr(addr, size)

            def _setvalue(self, value):
                if isinstance(value, basestring):
                    if isinstance(value, str):
                        value = value.decode(ConvMode.encoding,
                                             ConvMode.errors)
                    array = _rawffi.Array('u')(len(value)+1, value)
                    value = SysAllocStringLen(array.buffer, len(value))
                elif value is None:
                    value = 0
                if self._buffer[0]:
                    SysFreeString(self._buffer[0])
                self._buffer[0] = value
            result.value = property(_getvalue, _setvalue)

        elif tp == 'v': # VARIANT_BOOL type
            def _getvalue(self):
                return bool(self._buffer[0])
            def _setvalue(self, value):
                if value:
                    self._buffer[0] = -1 # VARIANT_TRUE
                else:
                    self._buffer[0] = 0  # VARIANT_FALSE
            result.value = property(_getvalue, _setvalue)

        return result

    from_address = cdata_from_address

    def from_param(self, value):
        from_param_f = FROM_PARAM_BY_TYPE.get(self._type_)
        if from_param_f:
            res = from_param_f(self, value)
            if res is not None:
                return res
            
        if isinstance(value, self):
            return value
        try:
            return self(value)
        except (TypeError, ValueError):
            return super(SimpleType, self).from_param(value)

    def _CData_output(self, resbuffer, base=None, index=-1):
        output = super(SimpleType, self)._CData_output(resbuffer, base, index)
        return output.value
    
    def _sizeofinstances(self):
        return _rawffi.sizeof(self._type_)

    def _alignmentofinstances(self):
        return _rawffi.alignment(self._type_)

    def _is_pointer_like(self):
        return self._type_ in "sPzUZXO"

class _SimpleCData(_CData):
    __metaclass__ = SimpleType
    _type_ = 'i'

    def __init__(self, value=DEFAULT_VALUE):
        self._buffer = self._ffiarray(1, autofree=True)
        if value is not DEFAULT_VALUE:
            self.value = value

    def _ensure_objects(self):
        if self._type_ in 'zZ':
            return self._objects
        return None

    def _getvalue(self):
        return self._buffer[0]

    def _setvalue(self, value):
        self._buffer[0] = value
    value = property(_getvalue, _setvalue)
    del _getvalue, _setvalue

    def __ctypes_from_outparam__(self):
        meta = type(type(self))
        if issubclass(meta, SimpleType) and meta != SimpleType:
            return self

        return self.value

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.value)

    def __nonzero__(self):
        return self._buffer[0] not in (0, '\x00')
