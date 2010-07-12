from pypy.interpreter.error import OperationError
from pypy.interpreter import function, pycode, pyframe
from pypy.interpreter.baseobjspace import Wrappable
from pypy.interpreter.mixedmodule import MixedModule
from pypy.rlib import jit
from pypy.tool.uid import uid

class Cell(Wrappable):
    "A simple container for a wrapped value."
    
    def __init__(self, w_value=None):
        self.w_value = w_value

    def clone(self):
        return self.__class__(self.w_value)

    def empty(self):
        return self.w_value is None

    def get(self):
        if self.w_value is None:
            raise ValueError, "get() from an empty cell"
        return self.w_value

    def set(self, w_value):
        self.w_value = w_value

    def delete(self):
        if self.w_value is None:
            raise ValueError, "delete() on an empty cell"
        self.w_value = None
  
    def descr__eq__(self, space, w_other):
        other = space.interpclass_w(w_other)
        if not isinstance(other, Cell):
            return space.w_False
        return space.eq(self.w_value, other.w_value)    
        
    def descr__reduce__(self, space):
        w_mod    = space.getbuiltinmodule('_pickle_support')
        mod      = space.interp_w(MixedModule, w_mod)
        new_inst = mod.get('cell_new')
        if self.w_value is None:    #when would this happen?
            return space.newtuple([new_inst, space.newtuple([])])
        tup = [self.w_value]
        return space.newtuple([new_inst, space.newtuple([]),
                               space.newtuple(tup)])

    def descr__setstate__(self, space, w_state):
        self.w_value = space.getitem(w_state, space.wrap(0))
        
    def __repr__(self):
        """ representation for debugging purposes """
        if self.w_value is None:
            content = ""
        else:
            content = repr(self.w_value)
        return "<%s(%s) at 0x%x>" % (self.__class__.__name__,
                                     content, uid(self))

    def descr__cell_contents(space, self):
        try:
            return self.get()
        except ValueError:
            raise OperationError(space.w_ValueError, space.wrap("Cell is empty"))



super_initialize_frame_scopes = pyframe.PyFrame.initialize_frame_scopes
super_fast2locals             = pyframe.PyFrame.fast2locals
super_locals2fast             = pyframe.PyFrame.locals2fast


class __extend__(pyframe.PyFrame):
    """This class enhances a standard frame with nested scope abilities,
    i.e. handling of cell/free variables."""

    # Cell Vars:
    #     my local variables that are exposed to my inner functions
    # Free Vars:
    #     variables coming from a parent function in which i'm nested
    # 'closure' is a list of Cell instances: the received free vars.

    cells = None

    @jit.unroll_safe
    def initialize_frame_scopes(self, closure, code):
        super_initialize_frame_scopes(self, closure, code)
        ncellvars = len(code.co_cellvars)
        nfreevars = len(code.co_freevars)
        if not nfreevars:
            if not ncellvars:
                return            # no self.cells needed - fast path
            if closure is None:
                closure = []
        elif closure is None:
            space = self.space
            raise OperationError(space.w_TypeError,
                                 space.wrap("directly executed code object "
                                            "may not contain free variables"))
        if len(closure) != nfreevars:
            raise ValueError("code object received a closure with "
                                 "an unexpected number of free variables")
        self.cells = [None] * (ncellvars + nfreevars)
        for i in range(ncellvars):
            self.cells[i] = Cell()
        for i in range(nfreevars):
            self.cells[i + ncellvars] = closure[i]
    
    def _getcells(self):
        return self.cells

    def _setcellvars(self, cellvars):
        ncellvars = len(self.pycode.co_cellvars)
        if len(cellvars) != ncellvars:
            raise OperationError(self.space.w_TypeError,
                                 self.space.wrap("bad cellvars"))
        if self.cells is not None:
            self.cells[:ncellvars] = cellvars

    def fast2locals(self):
        super_fast2locals(self)
        # cellvars are values exported to inner scopes
        # freevars are values coming from outer scopes 
        freevarnames = self.pycode.co_cellvars + self.pycode.co_freevars
        for i in range(len(freevarnames)):
            name = freevarnames[i]
            cell = self.cells[i]
            try:
                w_value = cell.get()
            except ValueError:
                pass
            else:
                w_name = self.space.wrap(name)
                self.space.setitem(self.w_locals, w_name, w_value)

    def locals2fast(self):
        super_locals2fast(self)
        freevarnames = self.pycode.co_cellvars + self.pycode.co_freevars
        for i in range(len(freevarnames)):
            name = freevarnames[i]
            cell = self.cells[i]
            w_name = self.space.wrap(name)
            try:
                w_value = self.space.getitem(self.w_locals, w_name)
            except OperationError, e:
                if not e.match(self.space, self.space.w_KeyError):
                    raise
            else:
                cell.set(w_value)

    @jit.unroll_safe
    def init_cells(self):
        if self.cells is None:
            return
        args_to_copy = self.pycode._args_as_cellvars
        for i in range(len(args_to_copy)):
            argnum = args_to_copy[i]
            if argnum >= 0:
                self.cells[i].set(self.fastlocals_w[argnum])

    def getfreevarname(self, index):
        freevarnames = self.pycode.co_cellvars + self.pycode.co_freevars
        return freevarnames[index]

    def iscellvar(self, index):
        # is the variable given by index a cell or a free var?
        return index < len(self.pycode.co_cellvars)

    ### extra opcodes ###

    def LOAD_CLOSURE(self, varindex, next_instr):
        # nested scopes: access the cell object
        cell = self.cells[varindex]
        w_value = self.space.wrap(cell)
        self.pushvalue(w_value)

    def LOAD_DEREF(self, varindex, next_instr):
        # nested scopes: access a variable through its cell object
        cell = self.cells[varindex]
        try:
            w_value = cell.get()
        except ValueError:
            varname = self.getfreevarname(varindex)
            if self.iscellvar(varindex):
                message = "local variable '%s' referenced before assignment"%varname
                w_exc_type = self.space.w_UnboundLocalError
            else:
                message = ("free variable '%s' referenced before assignment"
                           " in enclosing scope"%varname)
                w_exc_type = self.space.w_NameError
            raise OperationError(w_exc_type, self.space.wrap(message))
        else:
            self.pushvalue(w_value)

    def STORE_DEREF(self, varindex, next_instr):
        # nested scopes: access a variable through its cell object
        w_newvalue = self.popvalue()
        cell = self.cells[varindex]
        cell.set(w_newvalue)

    @jit.unroll_safe
    def MAKE_CLOSURE(self, numdefaults, next_instr):
        w_codeobj = self.popvalue()
        codeobj = self.space.interp_w(pycode.PyCode, w_codeobj)
        if codeobj.magic >= 0xa0df281:    # CPython 2.5 AST branch merge
            w_freevarstuple = self.popvalue()
            freevars = [self.space.interp_w(Cell, cell)
                        for cell in self.space.fixedview(w_freevarstuple)]
        else:
            nfreevars = len(codeobj.co_freevars)
            freevars = [self.space.interp_w(Cell, self.popvalue())
                        for i in range(nfreevars)]
            freevars.reverse()
        defaultarguments = [self.popvalue() for i in range(numdefaults)]
        defaultarguments.reverse()
        fn = function.Function(self.space, codeobj, self.w_globals,
                               defaultarguments, freevars)
        self.pushvalue(self.space.wrap(fn))
