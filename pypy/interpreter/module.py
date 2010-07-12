"""
Module objects.
"""

from pypy.interpreter.baseobjspace import Wrappable
from pypy.interpreter.error import OperationError

class Module(Wrappable):
    """A module."""

    def __init__(self, space, w_name, w_dict=None):
        self.space = space
        if w_dict is None: 
            w_dict = space.newdict(module=True)
        self.w_dict = w_dict 
        self.w_name = w_name 
        if w_name is not None:
            space.setitem(w_dict, space.new_interned_str('__name__'), w_name)
        self.startup_called = False

    def setup_after_space_initialization(self):
        """NOT_RPYTHON: to allow built-in modules to do some more setup
        after the space is fully initialized."""

    def init(self, space):
        """This is called each time the module is imported or reloaded
        """
        if not self.startup_called:
            self.startup_called = True
            self.startup(space)

    def startup(self, space):
        """This is called at runtime on import to allow the module to
        do initialization when it is imported for the first time.
        """

    def shutdown(self, space):
        """This is called when the space is shut down, just after
        sys.exitfunc(), if the module has been imported.
        """

    def getdict(self):
        return self.w_dict

    def descr_module__new__(space, w_subtype, __args__):
        module = space.allocate_instance(Module, w_subtype)
        Module.__init__(module, space, None)
        return space.wrap(module)

    def descr_module__init__(self, w_name, w_doc=None):
        space = self.space
        self.w_name = w_name
        if w_doc is None:  
            w_doc = space.w_None
        space.setitem(self.w_dict, space.new_interned_str('__name__'), w_name)
        space.setitem(self.w_dict, space.new_interned_str('__doc__'), w_doc)

    def descr__reduce__(self, space):
        w_name = space.finditem(self.w_dict, space.wrap('__name__'))
        if (w_name is None or 
            not space.is_true(space.isinstance(w_name, space.w_str))):
            # maybe raise exception here (XXX this path is untested)
            return space.w_None
        w_modules = space.sys.get('modules')
        if space.finditem(w_modules, w_name) is None:
            #not imported case
            from pypy.interpreter.mixedmodule import MixedModule
            w_mod    = space.getbuiltinmodule('_pickle_support')
            mod      = space.interp_w(MixedModule, w_mod)
            new_inst = mod.get('module_new')            
            return space.newtuple([new_inst, space.newtuple([w_name,
                                    self.getdict()]), 
                                  ])
        #already imported case
        w_import = space.builtin.get('__import__')
        tup_return = [
            w_import,
            space.newtuple([
                w_name,
                space.w_None,
                space.w_None,
                space.newtuple([space.wrap('')])
            ])
        ]

        return space.newtuple(tup_return)

    def descr_module__repr__(self, space):
        from pypy.interpreter.mixedmodule import MixedModule
        if self.w_name is not None:
            name = space.str_w(space.repr(self.w_name))
        else:
            name = "'?'"
        if isinstance(self, MixedModule):
            return space.wrap("<module %s (built-in)>" % name)
        try:
            w___file__ = space.getattr(self, space.wrap('__file__'))
            __file__ = space.str_w(space.repr(w___file__))
        except OperationError:
            __file__ = '?'
        return space.wrap("<module %s from %s>" % (name, __file__))
