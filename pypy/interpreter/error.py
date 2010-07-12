import os, sys
from pypy.rlib.objectmodel import we_are_translated
from pypy.rlib import jit

AUTO_DEBUG = os.getenv('PYPY_DEBUG')
RECORD_INTERPLEVEL_TRACEBACK = True


class OperationError(Exception):
    """Interpreter-level exception that signals an exception that should be
    sent to the application level.

    OperationError instances have three public attributes (and no .args),
    w_type, w_value and application_traceback, which contain the wrapped
    type and value describing the exception, and a chained list of
    PyTraceback objects making the application-level traceback.
    """

    _w_value = None
    application_traceback = None

    def __init__(self, w_type, w_value, tb=None):
        if not we_are_translated() and w_type is None:
            from pypy.tool.error import FlowingError
            raise FlowingError(w_value)
        self.setup(w_type)
        self._w_value = w_value
        self.application_traceback = tb

    def setup(self, w_type):
        self.w_type = w_type
        if not we_are_translated():
            self.debug_excs = []

    def clear(self, space):
        # for sys.exc_clear()
        self.w_type = space.w_None
        self._w_value = space.w_None
        self.application_traceback = None
        if not we_are_translated():
            del self.debug_excs[:]

    def match(self, space, w_check_class):
        "Check if this application-level exception matches 'w_check_class'."
        return space.exception_match(self.w_type, w_check_class)

    def async(self, space):
        "Check if this is an exception that should better not be caught."
        return (self.match(space, space.w_SystemExit) or
                self.match(space, space.w_KeyboardInterrupt))

    def __str__(self):
        "NOT_RPYTHON: Convenience for tracebacks."
        s = self._w_value
        if self.__class__ is not OperationError and s is None:
            s = self._compute_value()
        return '[%s: %s]' % (self.w_type, s)

    def errorstr(self, space):
        "The exception class and value, as a string."
        w_value = self.get_w_value(space)
        if space is None:
            # this part NOT_RPYTHON
            exc_typename = str(self.w_type)
            exc_value    = str(w_value)
        else:
            w = space.wrap
            if space.is_w(space.type(self.w_type), space.w_str):
                exc_typename = space.str_w(self.w_type)
            else:
                exc_typename = space.str_w(
                    space.getattr(self.w_type, w('__name__')))
            if space.is_w(w_value, space.w_None):
                exc_value = ""
            else:
                try:
                    exc_value = space.str_w(space.str(w_value))
                except OperationError:
                    # oups, cannot __str__ the exception object
                    exc_value = "<oups, exception object itself cannot be str'd>"
        if not exc_value:
            return exc_typename
        else:
            return '%s: %s' % (exc_typename, exc_value)

    def record_interpreter_traceback(self):
        """Records the current traceback inside the interpreter.
        This traceback is only useful to debug the interpreter, not the
        application."""
        if not we_are_translated():
            if RECORD_INTERPLEVEL_TRACEBACK:
                self.debug_excs.append(sys.exc_info())

    def print_application_traceback(self, space, file=None):
        "NOT_RPYTHON: Dump a standard application-level traceback."
        if file is None: file = sys.stderr
        self.print_app_tb_only(file)
        print >> file, self.errorstr(space)

    def print_app_tb_only(self, file):
        "NOT_RPYTHON"
        tb = self.application_traceback
        if tb:
            import linecache
            print >> file, "Traceback (application-level):"
            while tb is not None:
                co = tb.frame.pycode
                lineno = tb.get_lineno()
                fname = co.co_filename
                if fname.startswith('<inline>\n'):
                    lines = fname.split('\n')
                    fname = lines[0].strip()
                    try:
                        l = lines[lineno]
                    except IndexError:
                        l = ''
                else:
                    l = linecache.getline(fname, lineno)
                print >> file, "  File \"%s\"," % fname,
                print >> file, "line", lineno, "in", co.co_name
                if l:
                    if l.endswith('\n'):
                        l = l[:-1]
                    l = "    " + l.lstrip()
                    print >> file, l
                tb = tb.next

    def print_detailed_traceback(self, space=None, file=None):
        """NOT_RPYTHON: Dump a nice detailed interpreter- and
        application-level traceback, useful to debug the interpreter."""
        import traceback, cStringIO
        if file is None: file = sys.stderr
        f = cStringIO.StringIO()
        for i in range(len(self.debug_excs)-1, -1, -1):
            print >> f, "Traceback (interpreter-level):"
            traceback.print_tb(self.debug_excs[i][2], file=f)
        f.seek(0)
        debug_print(''.join(['|| ' + line for line in f.readlines()]), file)
        if self.debug_excs:
            from pypy.tool import tb_server
            tb_server.publish_exc(self.debug_excs[-1])
        self.print_app_tb_only(file)
        print >> file, '(application-level)', self.errorstr(space)
        if AUTO_DEBUG:
            import debug
            debug.fire(self)

    @jit.unroll_safe
    def normalize_exception(self, space):
        """Normalize the OperationError.  In other words, fix w_type and/or
        w_value to make sure that the __class__ of w_value is exactly w_type.
        """
        #
        # This method covers all ways in which the Python statement
        # "raise X, Y" can produce a valid exception type and instance.
        #
        # In the following table, 'Class' means a subclass of BaseException
        # and 'inst' is an instance of either 'Class' or a subclass of it.
        # Or 'Class' can also be an old-style class and 'inst' an old-style
        # instance of it.
        #
        # Note that 'space.full_exceptions' is set to False by the flow
        # object space; in this case we must assume that we are in a
        # non-advanced case, and ignore the advanced cases.  Old-style
        # classes and instances *are* advanced.
        #
        #  input (w_type, w_value)... becomes...                advanced case?
        # ---------------------------------------------------------------------
        #  (tuple, w_value)           (tuple[0], w_value)             yes
        #  (Class, None)              (Class, Class())                no
        #  (Class, inst)              (inst.__class__, inst)          no
        #  (Class, tuple)             (Class, Class(*tuple))          yes
        #  (Class, x)                 (Class, Class(x))               no
        #  ("string", ...)            ("string", ...)              deprecated
        #  (inst, None)               (inst.__class__, inst)          no
        #
        w_type  = self.w_type
        w_value = self.get_w_value(space)
        if space.full_exceptions:
            while space.is_true(space.isinstance(w_type, space.w_tuple)):
                w_type = space.getitem(w_type, space.wrap(0))

        if space.exception_is_valid_obj_as_class_w(w_type):
            # this is for all cases of the form (Class, something)
            if space.is_w(w_value, space.w_None):
                # raise Type: we assume we have to instantiate Type
                w_value = space.call_function(w_type)
                w_type = space.exception_getclass(w_value)
            else:
                w_valuetype = space.exception_getclass(w_value)
                if space.exception_issubclass_w(w_valuetype, w_type):
                    # raise Type, Instance: let etype be the exact type of value
                    w_type = w_valuetype
                else:
                    if space.full_exceptions and space.is_true(
                        space.isinstance(w_value, space.w_tuple)):
                        # raise Type, tuple: assume the tuple contains the
                        #                    constructor args
                        w_value = space.call(w_type, w_value)
                    else:
                        # raise Type, X: assume X is the constructor argument
                        w_value = space.call_function(w_type, w_value)
                    w_type = space.exception_getclass(w_value)

        elif space.full_exceptions and space.is_w(space.type(w_type),
                                                  space.w_str):
            space.warn("raising a string exception is deprecated", 
                       space.w_DeprecationWarning)

        else:
            # the only case left here is (inst, None), from a 'raise inst'.
            w_inst = w_type
            w_instclass = space.exception_getclass(w_inst)
            if not space.exception_is_valid_class_w(w_instclass):
                instclassname = w_instclass.getname(space, '?')
                msg = ("exceptions must be classes, or instances, "
                       "or strings (deprecated), not %s")
                raise operationerrfmt(space.w_TypeError, msg, instclassname)

            if not space.is_w(w_value, space.w_None):
                raise OperationError(space.w_TypeError,
                                     space.wrap("instance exception may not "
                                                "have a separate value"))
            w_value = w_inst
            w_type = w_instclass

        self.w_type   = w_type
        self._w_value = w_value

    def write_unraisable(self, space, where, w_object=None):
        if w_object is None:
            objrepr = ''
        else:
            try:
                objrepr = space.str_w(space.repr(w_object))
            except OperationError:
                objrepr = '?'
        msg = 'Exception "%s" in %s%s ignored\n' % (self.errorstr(space),
                                                    where, objrepr)
        try:
            space.call_method(space.sys.get('stderr'), 'write', space.wrap(msg))
        except OperationError:
            pass   # ignored

    def get_w_value(self, space):
        w_value = self._w_value
        if w_value is None:
            value = self._compute_value()
            self._w_value = w_value = space.wrap(value)
        return w_value

    def _compute_value(self):
        raise NotImplementedError

# ____________________________________________________________
# optimization only: avoid the slowest operation -- the string
# formatting with '%' -- in the common case were we don't
# actually need the message.  Only supports %s and %d.

_fmtcache = {}
_fmtcache2 = {}

def decompose_valuefmt(valuefmt):
    """Returns a tuple of string parts extracted from valuefmt,
    and a tuple of format characters."""
    formats = []
    parts = valuefmt.split('%')
    i = 1
    while i < len(parts):
        if parts[i].startswith('s') or parts[i].startswith('d'):
            formats.append(parts[i][0])
            parts[i] = parts[i][1:]
            i += 1
        elif parts[i] == '':    # support for '%%'
            parts[i-1] += '%' + parts[i+1]
            del parts[i:i+2]
        else:
            raise ValueError("invalid format string (only %s or %d supported)")
    assert len(formats) > 0, "unsupported: no % command found"
    return tuple(parts), tuple(formats)

def get_operrcls2(valuefmt):
    strings, formats = decompose_valuefmt(valuefmt)
    assert len(strings) == len(formats) + 1
    try:
        OpErrFmt = _fmtcache2[formats]
    except KeyError:
        from pypy.rlib.unroll import unrolling_iterable
        attrs = ['x%d' % i for i in range(len(formats))]
        entries = unrolling_iterable(enumerate(attrs))
        #
        class OpErrFmt(OperationError):
            def __init__(self, w_type, strings, *args):
                self.setup(w_type)
                assert len(args) == len(strings) - 1
                self.xstrings = strings
                for i, attr in entries:
                    setattr(self, attr, args[i])
                if not we_are_translated() and w_type is None:
                    from pypy.tool.error import FlowingError
                    raise FlowingError(self._compute_value())
            def _compute_value(self):
                lst = [None] * (len(formats) + len(formats) + 1)
                for i, attr in entries:
                    string = self.xstrings[i]
                    value = getattr(self, attr)
                    lst[i+i] = string
                    lst[i+i+1] = str(value)
                lst[-1] = self.xstrings[-1]
                return ''.join(lst)
        #
        _fmtcache2[formats] = OpErrFmt
    return OpErrFmt, strings

def get_operationerr_class(valuefmt):
    try:
        result = _fmtcache[valuefmt]
    except KeyError:
        result = _fmtcache[valuefmt] = get_operrcls2(valuefmt)
    return result
get_operationerr_class._annspecialcase_ = 'specialize:memo'

def operationerrfmt(w_type, valuefmt, *args):
    """Equivalent to OperationError(w_type, space.wrap(valuefmt % args)).
    More efficient in the (common) case where the value is not actually
    needed."""
    OpErrFmt, strings = get_operationerr_class(valuefmt)
    return OpErrFmt(w_type, strings, *args)
operationerrfmt._annspecialcase_ = 'specialize:arg(1)'

# ____________________________________________________________

# Utilities
from pypy.tool.ansi_print import ansi_print

def debug_print(text, file=None, newline=True):
    # 31: ANSI color code "red"
    ansi_print(text, esc="31", file=file, newline=newline)

try:
    WindowsError
except NameError:
    _WINDOWS = False
else:
    _WINDOWS = True

    def wrap_windowserror(space, e, filename=None):
        from pypy.rlib import rwin32

        winerror = e.winerror
        try:
            msg = rwin32.FormatError(winerror)
        except ValueError:
            msg = 'Windows Error %d' % winerror
        exc = space.w_WindowsError
        if filename is not None:
            w_error = space.call_function(exc, space.wrap(winerror),
                                          space.wrap(msg), space.wrap(filename))
        else:
            w_error = space.call_function(exc, space.wrap(winerror),
                                          space.wrap(msg))
        return OperationError(exc, w_error)

def wrap_oserror(space, e, filename=None, exception_name='w_OSError'): 
    assert isinstance(e, OSError)

    if _WINDOWS and isinstance(e, WindowsError):
        return wrap_windowserror(space, e, filename)

    errno = e.errno
    try:
        msg = os.strerror(errno)
    except ValueError:
        msg = 'error %d' % errno
    exc = getattr(space, exception_name)
    if filename is not None:
        w_error = space.call_function(exc, space.wrap(errno),
                                      space.wrap(msg), space.wrap(filename))
    else:
        w_error = space.call_function(exc, space.wrap(errno), space.wrap(msg))
    return OperationError(exc, w_error)
wrap_oserror._annspecialcase_ = 'specialize:arg(3)'
