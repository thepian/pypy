import py
import sys

builtin_repr = repr

repr = py.builtin._tryimport('repr', 'reprlib')

class Code(object):
    """ wrapper around Python code objects """
    def __init__(self, rawcode):
        rawcode = py.code.getrawcode(rawcode)
        self.raw = rawcode 
        try:
            self.filename = rawcode.co_filename
            self.firstlineno = rawcode.co_firstlineno - 1
            self.name = rawcode.co_name
        except AttributeError: 
            raise TypeError("not a code object: %r" %(rawcode,))
        
    def __eq__(self, other): 
        return self.raw == other.raw

    def __ne__(self, other):
        return not self == other

    def new(self, rec=False, **kwargs): 
        """ return new code object with modified attributes. 
            if rec-cursive is true then dive into code 
            objects contained in co_consts. 
        """ 
        if sys.platform.startswith("java"):
            # XXX jython does not support the below co_filename hack
            return self.raw 
        names = [x for x in dir(self.raw) if x[:3] == 'co_']
        for name in kwargs: 
            if name not in names: 
                raise TypeError("unknown code attribute: %r" %(name, ))
        if rec and hasattr(self.raw, 'co_consts'):  # jython 
            newconstlist = []
            co = self.raw
            cotype = type(co)
            for c in co.co_consts:
                if isinstance(c, cotype):
                    c = self.__class__(c).new(rec=True, **kwargs) 
                newconstlist.append(c)
            return self.new(rec=False, co_consts=tuple(newconstlist), **kwargs) 
        for name in names:
            if name not in kwargs:
                kwargs[name] = getattr(self.raw, name)
        arglist = [
                 kwargs['co_argcount'],
                 kwargs['co_nlocals'],
                 kwargs.get('co_stacksize', 0), # jython
                 kwargs.get('co_flags', 0), # jython
                 kwargs.get('co_code', ''), # jython
                 kwargs.get('co_consts', ()), # jython
                 kwargs.get('co_names', []), # 
                 kwargs['co_varnames'],
                 kwargs['co_filename'],
                 kwargs['co_name'],
                 kwargs['co_firstlineno'],
                 kwargs.get('co_lnotab', ''), #jython
                 kwargs.get('co_freevars', None), #jython
                 kwargs.get('co_cellvars', None), # jython
        ]
        if sys.version_info >= (3,0):
            arglist.insert(1, kwargs['co_kwonlyargcount'])
            return self.raw.__class__(*arglist)
        else:
            return py.std.new.code(*arglist)

    def path(self):
        """ return a py.path.local object pointing to the source code """
        fn = self.raw.co_filename 
        try:
            return fn.__path__
        except AttributeError:
            p = py.path.local(self.raw.co_filename)
            if not p.check(file=1):
                # XXX maybe try harder like the weird logic 
                # in the standard lib [linecache.updatecache] does? 
                p = self.raw.co_filename
            return p
                
    path = property(path, None, None, "path of this code object")

    def fullsource(self):
        """ return a py.code.Source object for the full source file of the code
        """
        from py.impl.code import source
        full, _ = source.findsource(self.raw)
        return full
    fullsource = property(fullsource, None, None,
                          "full source containing this code object")
    
    def source(self):
        """ return a py.code.Source object for the code object's source only
        """
        # return source only for that part of code
        return py.code.Source(self.raw)

    def getargs(self):
        """ return a tuple with the argument names for the code object
        """
        # handfull shortcut for getting args
        raw = self.raw
        return raw.co_varnames[:raw.co_argcount]

class Frame(object):
    """Wrapper around a Python frame holding f_locals and f_globals
    in which expressions can be evaluated."""

    def __init__(self, frame):
        self.code = py.code.Code(frame.f_code)
        self.lineno = frame.f_lineno - 1
        self.f_globals = frame.f_globals
        self.f_locals = frame.f_locals
        self.raw = frame

    def statement(self):
        if self.code.fullsource is None:
            return py.code.Source("")
        return self.code.fullsource.getstatement(self.lineno)
    statement = property(statement, None, None,
                         "statement this frame is at")

    def eval(self, code, **vars):
        """ evaluate 'code' in the frame

            'vars' are optional additional local variables

            returns the result of the evaluation
        """
        f_locals = self.f_locals.copy() 
        f_locals.update(vars)
        return eval(code, self.f_globals, f_locals)

    def exec_(self, code, **vars):
        """ exec 'code' in the frame

            'vars' are optiona; additional local variables
        """
        f_locals = self.f_locals.copy() 
        f_locals.update(vars)
        py.builtin.exec_(code, self.f_globals, f_locals )

    def repr(self, object):
        """ return a 'safe' (non-recursive, one-line) string repr for 'object'
        """
        return safe_repr(object)

    def is_true(self, object):
        return object

    def getargs(self):
        """ return a list of tuples (name, value) for all arguments
        """
        retval = []
        for arg in self.code.getargs():
            try:
                retval.append((arg, self.f_locals[arg]))
            except KeyError:
                pass     # this can occur when using Psyco
        return retval

class TracebackEntry(object):
    """ a single entry in a traceback """
    
    exprinfo = None 

    def __init__(self, rawentry):
        self._rawentry = rawentry
        self.frame = py.code.Frame(rawentry.tb_frame)
        # Ugh. 2.4 and 2.5 differs here when encountering
        # multi-line statements. Not sure about the solution, but
        # should be portable
        self.lineno = rawentry.tb_lineno - 1
        self.relline = self.lineno - self.frame.code.firstlineno

    def __repr__(self):
        return "<TracebackEntry %s:%d>" %(self.frame.code.path, self.lineno+1)

    def statement(self):
        """ return a py.code.Source object for the current statement """
        source = self.frame.code.fullsource
        return source.getstatement(self.lineno)
    statement = property(statement, None, None,
                         "statement of this traceback entry.")

    def path(self):
        return self.frame.code.path
    path = property(path, None, None, "path to the full source code")

    def getlocals(self):
        return self.frame.f_locals
    locals = property(getlocals, None, None, "locals of underlaying frame")

    def reinterpret(self):
        """Reinterpret the failing statement and returns a detailed information
           about what operations are performed."""
        if self.exprinfo is None:
            from py.impl.code import assertion 
            source = str(self.statement).strip()
            x = assertion.interpret(source, self.frame, should_fail=True)
            if not isinstance(x, str):
                raise TypeError("interpret returned non-string %r" % (x,))
            self.exprinfo = x 
        return self.exprinfo

    def getfirstlinesource(self):
        return self.frame.code.firstlineno

    def getsource(self): 
        """ return failing source code. """
        source = self.frame.code.fullsource
        if source is None:
            return None
        start = self.getfirstlinesource()
        end = self.lineno
        try:
            _, end = source.getstatementrange(end) 
        except IndexError: 
            end = self.lineno + 1 
        # heuristic to stop displaying source on e.g. 
        #   if something:  # assume this causes a NameError
        #      # _this_ lines and the one 
               #        below we don't want from entry.getsource() 
        for i in range(self.lineno, end): 
            if source[i].rstrip().endswith(':'): 
                end = i + 1
                break 
        return source[start:end]
    source = property(getsource)

    def ishidden(self):
        """ return True if the current frame has a var __tracebackhide__ 
            resolving to True
            
            mostly for internal use
        """
        try: 
            return self.frame.eval("__tracebackhide__") 
        except (SystemExit, KeyboardInterrupt): 
            raise
        except:
            return False 

    def __str__(self): 
        try: 
            fn = str(self.path) 
        except py.error.Error: 
            fn = '???'
        name = self.frame.code.name 
        try: 
            line = str(self.statement).lstrip()
        except KeyboardInterrupt:
            raise
        except:
            line = "???"
        return "  File %r:%d in %s\n  %s\n" %(fn, self.lineno+1, name, line) 

    def name(self):
        return self.frame.code.raw.co_name
    name = property(name, None, None, "co_name of underlaying code")

class Traceback(list):
    """ Traceback objects encapsulate and offer higher level 
        access to Traceback entries.  
    """
    Entry = TracebackEntry 
    def __init__(self, tb):
        """ initialize from given python traceback object. """
        if hasattr(tb, 'tb_next'):
            def f(cur): 
                while cur is not None: 
                    yield self.Entry(cur)
                    cur = cur.tb_next 
            list.__init__(self, f(tb)) 
        else:
            list.__init__(self, tb)

    def cut(self, path=None, lineno=None, firstlineno=None, excludepath=None):
        """ return a Traceback instance wrapping part of this Traceback

            by provding any combination of path, lineno and firstlineno, the
            first frame to start the to-be-returned traceback is determined

            this allows cutting the first part of a Traceback instance e.g.
            for formatting reasons (removing some uninteresting bits that deal
            with handling of the exception/traceback)
        """
        for x in self:
            code = x.frame.code
            codepath = code.path
            if ((path is None or codepath == path) and
                (excludepath is None or (hasattr(codepath, 'relto') and
                 not codepath.relto(excludepath))) and 
                (lineno is None or x.lineno == lineno) and
                (firstlineno is None or x.frame.code.firstlineno == firstlineno)):
                return Traceback(x._rawentry)
        return self

    def __getitem__(self, key):
        val = super(Traceback, self).__getitem__(key)
        if isinstance(key, type(slice(0))):
            val = self.__class__(val)
        return val

    def filter(self, fn=lambda x: not x.ishidden()):
        """ return a Traceback instance with certain items removed

            fn is a function that gets a single argument, a TracebackItem
            instance, and should return True when the item should be added
            to the Traceback, False when not

            by default this removes all the TracebackItems which are hidden
            (see ishidden() above)
        """
        return Traceback(filter(fn, self))

    def getcrashentry(self):
        """ return last non-hidden traceback entry that lead
        to the exception of a traceback. 
        """
        tb = self.filter()
        if not tb:
            tb = self
        return tb[-1]

    def recursionindex(self):
        """ return the index of the frame/TracebackItem where recursion
            originates if appropriate, None if no recursion occurred
        """
        cache = {}
        for i, entry in enumerate(self):
            key = entry.frame.code.path, entry.lineno 
            #print "checking for recursion at", key
            l = cache.setdefault(key, [])
            if l: 
                f = entry.frame
                loc = f.f_locals
                for otherloc in l: 
                    if f.is_true(f.eval(co_equal, 
                        __recursioncache_locals_1=loc,
                        __recursioncache_locals_2=otherloc)):
                        return i 
            l.append(entry.frame.f_locals)
        return None

co_equal = compile('__recursioncache_locals_1 == __recursioncache_locals_2',
                   '?', 'eval')

class ExceptionInfo(object):
    """ wraps sys.exc_info() objects and offers
        help for navigating the traceback.
    """
    _striptext = '' 
    def __init__(self, tup=None, exprinfo=None):
        # NB. all attributes are private!  Subclasses or other
        #     ExceptionInfo-like classes may have different attributes.
        if tup is None:
            tup = sys.exc_info()
            if exprinfo is None and isinstance(tup[1], py.code._AssertionError):
                exprinfo = getattr(tup[1], 'msg', None)
                if exprinfo is None:
                    exprinfo = str(tup[1])
                if exprinfo and exprinfo.startswith('assert '):
                    self._striptext = 'AssertionError: '
        self._excinfo = tup
        self.type, self.value, tb = self._excinfo
        self.typename = self.type.__name__
        self.traceback = py.code.Traceback(tb) 

    def __repr__(self):
        return "<ExceptionInfo %s tblen=%d>" % (self.typename, len(self.traceback))

    def exconly(self, tryshort=False): 
        """ return the exception as a string
        
            when 'tryshort' resolves to True, and the exception is a
            py.code._AssertionError, only the actual exception part of
            the exception representation is returned (so 'AssertionError: ' is
            removed from the beginning)
        """
        lines = py.std.traceback.format_exception_only(self.type, self.value)
        text = ''.join(lines)
        text = text.rstrip()
        if tryshort: 
            if text.startswith(self._striptext): 
                text = text[len(self._striptext):]
        return text

    def errisinstance(self, exc): 
        """ return True if the exception is an instance of exc """
        return isinstance(self.value, exc) 

    def _getreprcrash(self):
        exconly = self.exconly(tryshort=True)
        entry = self.traceback.getcrashentry()
        path, lineno = entry.path, entry.lineno
        reprcrash = ReprFileLocation(path, lineno+1, exconly)
        return reprcrash

    def getrepr(self, showlocals=False, style="long", 
            abspath=False, tbfilter=True, funcargs=False):
        """ return str()able representation of this exception info.
            showlocals: show locals per traceback entry 
            style: long|short|no traceback style 
            tbfilter: hide entries (where __tracebackhide__ is true)
        """
        fmt = FormattedExcinfo(showlocals=showlocals, style=style, 
            abspath=abspath, tbfilter=tbfilter, funcargs=funcargs)
        return fmt.repr_excinfo(self)

    def __str__(self):
        entry = self.traceback[-1]
        loc = ReprFileLocation(entry.path, entry.lineno + 1, self.exconly())
        return str(loc)

class FormattedExcinfo(object):
    """ presenting information about failing Functions and Generators. """ 
    # for traceback entries 
    flow_marker = ">"    
    fail_marker = "E"
    
    def __init__(self, showlocals=False, style="long", abspath=True, tbfilter=True, funcargs=False):
        self.showlocals = showlocals
        self.style = style
        self.tbfilter = tbfilter
        self.funcargs = funcargs
        self.abspath = abspath 

    def _getindent(self, source):
        # figure out indent for given source 
        try:
            s = str(source.getstatement(len(source)-1))
        except KeyboardInterrupt: 
            raise 
        except:
            try:
                s = str(source[-1])
            except KeyboardInterrupt:
                raise
            except:
                return 0
        return 4 + (len(s) - len(s.lstrip()))

    def _getentrysource(self, entry):
        source = entry.getsource()
        if source is not None:
            source = source.deindent()
        return source
    
    def _saferepr(self, obj):
        return safe_repr(obj)

    def repr_args(self, entry):
        if self.funcargs:
            args = []
            for argname, argvalue in entry.frame.getargs():
                args.append((argname, self._saferepr(argvalue)))
            return ReprFuncArgs(args)

    def get_source(self, source, line_index=-1, excinfo=None):
        """ return formatted and marked up source lines. """
        lines = []
        if source is None:
            source = py.code.Source("???")
            line_index = 0 
        if line_index < 0:
            line_index += len(source)
        for i in range(len(source)):
            if i == line_index:
                prefix = self.flow_marker + "   "
            else:
                prefix = "    "
            line = prefix + source[i]
            lines.append(line)
        if excinfo is not None:
            indent = self._getindent(source)
            lines.extend(self.get_exconly(excinfo, indent=indent, markall=True))
        return lines

    def get_exconly(self, excinfo, indent=4, markall=False):
        lines = []
        indent = " " * indent 
        # get the real exception information out 
        exlines = excinfo.exconly(tryshort=True).split('\n')
        failindent = self.fail_marker + indent[1:]
        for line in exlines:
            lines.append(failindent + line)
            if not markall:
                failindent = indent 
        return lines

    def repr_locals(self, locals):
        if self.showlocals: 
            lines = []
            keys = list(locals)
            keys.sort()
            for name in keys:
                value = locals[name]
                if name == '__builtins__': 
                    lines.append("__builtins__ = <builtins>")
                else:
                    # This formatting could all be handled by the
                    # _repr() function, which is only repr.Repr in
                    # disguise, so is very configurable.
                    str_repr = self._saferepr(value)
                    #if len(str_repr) < 70 or not isinstance(value,
                    #                            (list, tuple, dict)):
                    lines.append("%-10s = %s" %(name, str_repr))
                    #else:
                    #    self._line("%-10s =\\" % (name,))
                    #    # XXX
                    #    py.std.pprint.pprint(value, stream=self.excinfowriter)
            return ReprLocals(lines)

    def repr_traceback_entry(self, entry, excinfo=None):
        # excinfo is not None if this is the last tb entry 
        source = self._getentrysource(entry)
        if source is None:
            source = py.code.Source("???")
            line_index = 0
        else:
            line_index = entry.lineno - entry.getfirstlinesource()

        lines = []
        if self.style == "long":
            reprargs = self.repr_args(entry) 
            lines.extend(self.get_source(source, line_index, excinfo))
            message = excinfo and excinfo.typename or ""
            path = self._makepath(entry.path)
            filelocrepr = ReprFileLocation(path, entry.lineno+1, message)
            localsrepr =  self.repr_locals(entry.locals)
            return ReprEntry(lines, reprargs, localsrepr, filelocrepr)
        else: 
            if self.style == "short":
                line = source[line_index].lstrip()
                lines.append('  File "%s", line %d, in %s' % (
                    entry.path.basename, entry.lineno+1, entry.name))
                lines.append("    " + line) 
            if excinfo: 
                lines.extend(self.get_exconly(excinfo, indent=4))
            return ReprEntry(lines, None, None, None)

    def _makepath(self, path):
        if not self.abspath:
            np = py.path.local().bestrelpath(path)
            if len(np) < len(str(path)):
                path = np
        return path

    def repr_traceback(self, excinfo): 
        traceback = excinfo.traceback 
        if self.tbfilter:
            traceback = traceback.filter()
        recursionindex = None
        if excinfo.errisinstance(RuntimeError):
            recursionindex = traceback.recursionindex()
        last = traceback[-1]
        entries = []
        extraline = None
        for index, entry in enumerate(traceback): 
            einfo = (last == entry) and excinfo or None
            reprentry = self.repr_traceback_entry(entry, einfo)
            entries.append(reprentry)
            if index == recursionindex:
                extraline = "!!! Recursion detected (same locals & position)"
                break
        return ReprTraceback(entries, extraline, style=self.style)

    def repr_excinfo(self, excinfo):
        reprtraceback = self.repr_traceback(excinfo)
        reprcrash = excinfo._getreprcrash()
        return ReprExceptionInfo(reprtraceback, reprcrash)

class TerminalRepr:
    def __str__(self):
        tw = py.io.TerminalWriter(stringio=True)
        self.toterminal(tw)
        return tw.stringio.getvalue().strip()

    def __repr__(self):
        return "<%s instance at %0x>" %(self.__class__, id(self))

class ReprExceptionInfo(TerminalRepr):
    def __init__(self, reprtraceback, reprcrash):
        self.reprtraceback = reprtraceback
        self.reprcrash = reprcrash 
        self.sections = []

    def addsection(self, name, content, sep="-"):
        self.sections.append((name, content, sep))

    def toterminal(self, tw):
        self.reprtraceback.toterminal(tw)
        for name, content, sep in self.sections:
            tw.sep(sep, name)
            tw.line(content)
    
class ReprTraceback(TerminalRepr):
    entrysep = "_ "

    def __init__(self, reprentries, extraline, style):
        self.reprentries = reprentries
        self.extraline = extraline
        self.style = style

    def toterminal(self, tw):
        sepok = False 
        for entry in self.reprentries:
            if self.style == "long":
                if sepok:
                    tw.sep(self.entrysep)
                tw.line("")
            sepok = True
            entry.toterminal(tw)
        if self.extraline:
            tw.line(self.extraline)

class ReprEntry(TerminalRepr):
    localssep = "_ "

    def __init__(self, lines, reprfuncargs, reprlocals, filelocrepr):
        self.lines = lines
        self.reprfuncargs = reprfuncargs
        self.reprlocals = reprlocals 
        self.reprfileloc = filelocrepr

    def toterminal(self, tw):
        if self.reprfuncargs:
            self.reprfuncargs.toterminal(tw)
        for line in self.lines:
            red = line.startswith("E   ") 
            tw.line(line, bold=True, red=red)
        if self.reprlocals:
            #tw.sep(self.localssep, "Locals")
            tw.line("")
            self.reprlocals.toterminal(tw)
        if self.reprfileloc:
            tw.line("")
            self.reprfileloc.toterminal(tw)

    def __str__(self):
        return "%s\n%s\n%s" % ("\n".join(self.lines), 
                               self.reprlocals, 
                               self.reprfileloc)

class ReprFileLocation(TerminalRepr):
    def __init__(self, path, lineno, message):
        self.path = str(path)
        self.lineno = lineno
        self.message = message

    def toterminal(self, tw):
        # filename and lineno output for each entry,
        # using an output format that most editors unterstand
        msg = self.message 
        i = msg.find("\n")
        if i != -1:
            msg = msg[:i] 
        tw.line("%s:%s: %s" %(self.path, self.lineno, msg))

class ReprLocals(TerminalRepr):
    def __init__(self, lines):
        self.lines = lines 

    def toterminal(self, tw):
        for line in self.lines:
            tw.line(line)

class ReprFuncArgs(TerminalRepr):
    def __init__(self, args):
        self.args = args

    def toterminal(self, tw):
        if self.args:
            linesofar = ""
            for name, value in self.args:
                ns = "%s = %s" %(name, value)
                if len(ns) + len(linesofar) + 2 > tw.fullwidth:
                    if linesofar:
                        tw.line(linesofar)
                    linesofar =  ns 
                else:
                    if linesofar:
                        linesofar += ", " + ns
                    else:
                        linesofar = ns
            if linesofar:
                tw.line(linesofar)
            tw.line("")



class SafeRepr(repr.Repr):
    """ subclass of repr.Repr that limits the resulting size of repr() 
        and includes information on exceptions raised during the call. 
    """ 
    def __init__(self, *args, **kwargs):
        repr.Repr.__init__(self, *args, **kwargs)
        self.maxstring = 240   # 3 * 80 chars
        self.maxother = 160    # 2 * 80 chars

    def repr(self, x):
        return self._callhelper(repr.Repr.repr, self, x)

    def repr_instance(self, x, level):
        return self._callhelper(builtin_repr, x)
        
    def _callhelper(self, call, x, *args):
        try:
            # Try the vanilla repr and make sure that the result is a string
            s = call(x, *args)
        except (KeyboardInterrupt, MemoryError, SystemExit):
            raise
        except:
            cls, e, tb = sys.exc_info()
            try:
                exc_name = cls.__name__
            except:
                exc_name = 'unknown'
            try:
                exc_info = str(e)
            except:
                exc_info = 'unknown'
            return '<[%s("%s") raised in repr()] %s object at 0x%x>' % (
                exc_name, exc_info, x.__class__.__name__, id(x))
        else:
            if len(s) > self.maxstring:
                i = max(0, (self.maxstring-3)//2)
                j = max(0, self.maxstring-3-i)
                s = s[:i] + '...' + s[len(s)-j:]
            return s

safe_repr = SafeRepr().repr

oldbuiltins = {}

def patch_builtins(assertion=True, compile=True):
    """ put compile and AssertionError builtins to Python's builtins. """
    if assertion:
        from py.impl.code import assertion
        l = oldbuiltins.setdefault('AssertionError', [])
        l.append(py.builtin.builtins.AssertionError)
        py.builtin.builtins.AssertionError = assertion.AssertionError
    if compile: 
        l = oldbuiltins.setdefault('compile', [])
        l.append(py.builtin.builtins.compile)
        py.builtin.builtins.compile = py.code.compile

def unpatch_builtins(assertion=True, compile=True):
    """ remove compile and AssertionError builtins from Python builtins. """
    if assertion:
        py.builtin.builtins.AssertionError = oldbuiltins['AssertionError'].pop()
    if compile: 
        py.builtin.builtins.compile = oldbuiltins['compile'].pop()

def getrawcode(obj):
    """ return code object for given function. """ 
    obj = getattr(obj, 'im_func', obj)
    obj = getattr(obj, 'func_code', obj)
    obj = getattr(obj, 'f_code', obj)
    obj = getattr(obj, '__code__', obj)
    return obj
    
