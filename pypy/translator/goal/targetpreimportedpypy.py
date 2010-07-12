import py

import os, sys
sys.setrecursionlimit(17000)

from pypy.interpreter import gateway
from pypy.interpreter.error import OperationError
from pypy.translator.goal.ann_override import PyPyAnnotatorPolicy
from pypy.config.config import Config, to_optparse, make_dict, SUPPRESS_USAGE
from pypy.config.config import ConflictConfigError
from pypy.tool.option import make_objspace
from pypy.translator.goal.nanos import setup_nanos

EXTRA_MODULES = [
    #"os",
    #"decimal",
    #"difflib",
    #"tarfile",
    #"cookielib",
    #"optparse",
    "inspect",
    "random",
]

thisdir = py.path.local(__file__).dirpath()

try:
    this_dir = os.path.dirname(__file__)
except NameError:
    this_dir = os.path.dirname(sys.argv[0])

def debug(msg):
    os.write(2, "debug: " + msg + '\n')

# __________  Entry point  __________

def create_entry_point(space, w_dict):
    w_entry_point = space.getitem(w_dict, space.wrap('entry_point'))
    w_run_toplevel = space.getitem(w_dict, space.wrap('run_toplevel'))
    w_call_finish_gateway = space.wrap(gateway.interp2app(call_finish))
    w_call_startup_gateway = space.wrap(gateway.interp2app(call_startup))
    w_os = setup_nanos(space)

    def entry_point(argv):
        space.timer.start("Entrypoint")
        #debug("entry point starting") 
        #for arg in argv: 
        #    debug(" argv -> " + arg)
        if len(argv) > 2 and argv[1] == '--heapsize':
            # Undocumented option, handled at interp-level.
            # It has silently no effect with some GCs.
            # It works in Boehm and in the semispace or generational GCs
            # (but see comments in semispace.py:set_max_heap_size()).
            # At the moment this option exists mainly to support sandboxing.
            from pypy.rlib import rgc
            rgc.set_max_heap_size(int(argv[2]))
            argv = argv[:1] + argv[3:]
        try:
            try:
                space.timer.start("space.startup")
                space.call_function(w_run_toplevel, w_call_startup_gateway)
                space.timer.stop("space.startup")
                w_executable = space.wrap(argv[0])
                w_argv = space.newlist([space.wrap(s) for s in argv[1:]])
                space.timer.start("w_entry_point")
                w_exitcode = space.call_function(w_entry_point, w_executable, w_argv, w_os)
                space.timer.stop("w_entry_point")
                exitcode = space.int_w(w_exitcode)
                # try to pull it all in
            ##    from pypy.interpreter import main, interactive, error
            ##    con = interactive.PyPyConsole(space)
            ##    con.interact()
            except OperationError, e:
                debug("OperationError:")
                debug(" operror-type: " + e.w_type.getname(space, '?'))
                debug(" operror-value: " + space.str_w(space.str(e.get_w_value(space))))
                return 1
        finally:
            try:
                space.timer.start("space.finish")
                space.call_function(w_run_toplevel, w_call_finish_gateway)
                space.timer.stop("space.finish")
            except OperationError, e:
                debug("OperationError:")
                debug(" operror-type: " + e.w_type.getname(space, '?'))
                debug(" operror-value: " + space.str_w(space.str(e.get_w_value(space))))
                return 1
        space.timer.stop("Entrypoint")
        space.timer.dump()
        return exitcode
    return entry_point

def call_finish(space):
    space.finish()

def call_startup(space):
    space.startup()

# _____ Define and setup target ___

# for now this will do for option handling

class PyPyTarget(object):

    usage = SUPPRESS_USAGE

    take_options = True

    def opt_parser(self, config):
        parser = to_optparse(config, useoptions=["objspace.*"],
                             parserkwargs={'usage': self.usage})
        return parser

    def handle_config(self, config, translateconfig):
        self.translateconfig = translateconfig
        # set up the objspace optimizations based on the --opt argument
        from pypy.config.pypyoption import set_pypy_opt_level
        set_pypy_opt_level(config, translateconfig.opt)

        # as of revision 27081, multimethod.py uses the InstallerVersion1 by default
        # because it is much faster both to initialize and run on top of CPython.
        # The InstallerVersion2 is optimized for making a translator-friendly
        # structure for low level backends. However, InstallerVersion1 is still
        # preferable for high level backends, so we patch here.

        from pypy.objspace.std import multimethod
        if config.objspace.std.multimethods == 'mrd':
            assert multimethod.InstallerVersion1.instance_counter == 0,\
                   'The wrong Installer version has already been instatiated'
            multimethod.Installer = multimethod.InstallerVersion2
        elif config.objspace.std.multimethods == 'doubledispatch':
            # don't rely on the default, set again here
            assert multimethod.InstallerVersion2.instance_counter == 0,\
                   'The wrong Installer version has already been instatiated'
            multimethod.Installer = multimethod.InstallerVersion1

    def print_help(self, config):
        self.opt_parser(config).print_help()

    def get_additional_config_options(self):
        from pypy.config.pypyoption import pypy_optiondescription
        return pypy_optiondescription

    def target(self, driver, args):
        driver.exe_name = 'pypy-%(backend)s'

        config = driver.config
        parser = self.opt_parser(config)

        parser.parse_args(args)

        # expose the following variables to ease debugging
        global space, entry_point

        if config.objspace.allworkingmodules:
            from pypy.config.pypyoption import enable_allworkingmodules
            enable_allworkingmodules(config)

        if config.translation.thread:
            config.objspace.usemodules.thread = True
        elif config.objspace.usemodules.thread:
            try:
                config.translation.thread = True
            except ConflictConfigError:
                # If --allworkingmodules is given, we reach this point
                # if threads cannot be enabled (e.g. they conflict with
                # something else).  In this case, we can try setting the
                # usemodules.thread option to False again.  It will
                # cleanly fail if that option was set to True by the
                # command-line directly instead of via --allworkingmodules.
                config.objspace.usemodules.thread = False

        if config.translation.stackless:
            config.objspace.usemodules._stackless = True
        elif config.objspace.usemodules._stackless:
            try:
                config.translation.stackless = True
            except ConflictConfigError:
                raise ConflictConfigError("please use the --stackless option "
                                          "to translate.py instead of "
                                          "--withmod-_stackless directly")

        if not config.translation.rweakref:
            config.objspace.usemodules._weakref = False

        if self.translateconfig.goal_options.jit:
            config.objspace.usemodules.pypyjit = True
        elif config.objspace.usemodules.pypyjit:
            self.translateconfig.goal_options.jit = True

        if config.translation.backend == "cli":
            config.objspace.usemodules.clr = True
        # XXX did it ever work?
        #elif config.objspace.usemodules.clr:
        #    config.translation.backend == "cli"

        config.objspace.nofaking = True
        config.objspace.compiler = "ast"
        config.translating = True

        import translate
        translate.log_config(config.objspace, "PyPy config object")
 
        # obscure hack to stuff the translation options into the translated PyPy
        import pypy.module.sys
        options = make_dict(config)
        wrapstr = 'space.wrap(%r)' % (options)
        pypy.module.sys.Module.interpleveldefs['pypy_translation_info'] = wrapstr

        return self.get_entry_point(config)

    def portal(self, driver):
        from pypy.module.pypyjit.portal import get_portal
        return get_portal(driver)
    
    def get_entry_point(self, config):
        space = make_objspace(config)

        # manually imports app_main.py
        filename = os.path.join(this_dir, 'app_main.py')
        w_dict = space.newdict()
        space.exec_(open(filename).read(), w_dict, w_dict)
        for modulename in EXTRA_MODULES:
            print 'pre-importing', modulename
            space.exec_("import " + modulename, w_dict, w_dict)
        print 'phew, ready'
        entry_point = create_entry_point(space, w_dict)

        return entry_point, None, PyPyAnnotatorPolicy(single_space = space)

    def interface(self, ns):
        for name in ['take_options', 'handle_config', 'print_help', 'target',
                     'portal',
                     'get_additional_config_options']:
            ns[name] = getattr(self, name)


PyPyTarget().interface(globals())

