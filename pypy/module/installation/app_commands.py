# NOT_RPYTHON
import sys,imp,os,os.path
from optparse import make_option, OptionParser

from pypy.module.installation.app_terminal import color_style

def find_commands(base_dir):
    """
    Given a path to a base directory, returns a list of all the command
    names that are available.

    Returns an empty list if no commands are defined.
    """
    command_dir = os.path.join(base_dir, 'commands')
    try:
        return [f[:-3] for f in os.listdir(command_dir)
                if not f.startswith('_') and f.endswith('.py')]
    except OSError:
        return []

class CommandError(Exception):
    pass

COMMAND_DEFAULTS = dict(
    option_list = (
        make_option('--cluster', dest="cluster", help='The name of the active cluster'),
        make_option('--settings',
            help='The Python path to a settings module, e.g. "myproject.settings.main". If this isn\'t provided, the MAESTRO_SETTINGS_MODULE environment variable will be used.'),
        make_option('--pythonpath',
            help='A directory to add to the Python path, e.g. "/home/djangoprojects/myproject".'),
        make_option('--traceback', action='store_true',
            help='Print traceback on exception'),
    ),
    help = '',
    args = ''
)

class CommandWrapper(object):
    """Wraps a Command class or a module in the commands directory of an executable package"""

    def __init__(self,mod=None,cmd=None,base=None,name=None):
        self._cmd = cmd
        self._mod = mod
        self._set_defaults()
        self.base = base
        self.name = name

    def _load(self):
        if not self._mod and not self._cmd:
            try:
                self._mod = __import__('%s.commands.%s' % (self.base, self.name),
                    {}, {}, [])
                self._set_defaults()
                self._cmd = getattr(__import__('%s.commands.%s' % (self.base, self.name),
                    {}, {}, ['Command']), 'Command')()
            except AttributeError,e:
                pass
            
    def _set_defaults(self):
        try:
            BaseCommand = getattr(self._mod,'BaseCommand')
            self.command_defaults = {}
            for attr in COMMAND_DEFAULTS:
                self.command_defaults[attr] = getattr(BaseCommand,attr,COMMAND_DEFAULTS[attr])
        except AttributeError,e:
            self.command_defaults = COMMAND_DEFAULTS
        
    def get_mod(self):
        """
        Instantiate the module if not yet loaded. All errors raised by the import process
        (ImportError, AttributeError) are allowed to propagate.
        """
        self._load()
        return self._mod
    mod = property(get_mod)

    def get_cmd(self):
        """
        Instantiate the command if not yet loade. All errors raised by the import process
        (ImportError, AttributeError) are allowed to propagate.
        """
        self._load()
        return self._cmd
    cmd = property(get_cmd)

    def get_option_list(self):
        return getattr(self.cmd or self.mod,'option_list',self.command_defaults['option_list'])
    option_list = property(get_option_list)

    def get_help(self):
        return getattr(self.cmd or self.mod,'help',self.command_defaults['help'])
    help = property(get_help)

    def get_args(self):
        return getattr(self.cmd or self.mod,'args',self.command_defaults['args'])
    args = property(get_args)

    def get_style(self):
        return getattr(self.cmd or self.mod,'style',color_style())
    style = property(get_style)


    def get_version(self):
        if hasattr(self.cmd,'get_version') and callable(self.cmd.get_version):
            return self.cmd.get_version()
        if hasattr(self.mod,'get_version') and callable(self.mod.get_version):
            return self.mod.get_version()
        #import thepian
        #return thepian.VERSION
        return "1.0"

    def usage(self, subcommand):
        if hasattr(self.cmd,'usage') and callable(self.cmd.usage):
            return self.cmd.usage(subcommand)
        if hasattr(self.mod,'usage') and callable(self.mod.usage):
            return self.mod.usage(subcommand)

        usage = self.style.HEADING('%%prog %s [options] %s' % (subcommand, self.args))
        if self.help:
            return '%s\n\n%s' % (usage, self.style.HIGHLIGHT(self.help))
        else:
            return usage

    def create_parser(self, prog_name, subcommand):
        if hasattr(self.cmd,'create_parser'):
            return self.cmd.create_parser(prog_name,subcommand)
        if hasattr(self.mod,'create_parser'):
            return self.mod.create_parser(prog_name,subcommand)

        return OptionParser(prog=prog_name,
                            usage=self.usage(subcommand),
                            version=self.get_version(),
                            option_list=self.option_list)

    def print_help(self, prog_name, subcommand):
        if hasattr(self.cmd,'print_help'):
            return self.cmd.print_help(prog_name,subcommand)

        parser = self.create_parser(prog_name, subcommand)
        parser.print_help()

    def run_from_argv(self, argv):
        """Run directly from command line arg list, ignores run_from_argv on the command to handle default options properly"""
        parser = self.create_parser(argv[0] or sys.executable_name, argv[1])
        options, args = parser.parse_args(argv[2:])
        self(*args, **options.__dict__)

    def __call__(self, *args, **options):
        if hasattr(self.cmd,'__call__'):
            return self.cmd(*args,**options)    
        if hasattr(self.cmd,'execute'):
            return self.cmd.execute(*args,**options)    
        if hasattr(self.cmd,'handle'):
            return self.cmd.handle(*args,**options)    
        print 'cannot execute command' #TODO raise?

class HelpWrapper(CommandWrapper):
    """Not sure if this should replace the special help handling"""
    #TODO
    pass


class Cmds(object):
    cache = None
    _default_modules = None
    
    def get_default_modules(self):
        if self._default_modules is None:
            self._default_modules = [sys.product_name]
            if len(sys.argv) > 0:                
                argv0 = sys.argv[0]
                if argv0.endswith(".py"):
                    argv0 = argv0[:-3]
                self._default_modules.append(argv0)    
        return self._default_modules
        
    default_modules = property(get_default_modules)

    def _add_wrappers(self,modules):
        for mod in modules:
            try:
                f, pathname, description = imp.find_module(mod)
                try:
                    cmd_and_wrapper = [(name,CommandWrapper(base=mod,name=name)) for name in find_commands(pathname)]
                    self.cache.update(dict(cmd_and_wrapper))
                except ImportError,e:
                    print "Error while checking module '%s'" % mod, e
                if f:
                    f.close()
            except ImportError, ie:
                pass
            
        
    def get_commands(self):
        """
        Returns a dictionary mapping command names to their command wrappers noting the base module.
    
        This works by looking for a commands package in executable modules, and
        any additional modules added with _add_wrappers.
    
        The dictionary is cached on the first call and reused on subsequent
        calls.
        """
        if self.cache is None:
            self.cache = { 'help' : HelpWrapper() }
            self._add_wrappers(self.default_modules)
                
        return self.cache
    
    def __getitem__(self,name):
        try:
            cmds = self.get_commands()
            return cmds[name]
        except KeyError:
            raise CommandError, "Unknown command: %r" % name
            
    def __contains__(self,name):
        cmds = self.get_commands()
        return name in cmds
        
    def main_help_text(self,argv=None):
        """
        Returns the script's main help text, as a string.
        """
        import thepian
        prog_name = os.path.basename(argv[0])
        style = color_style()
        usage = [
            style.HEADING('%s <subcommand> [options] [args]' % prog_name),
            'Thepian command line tool, version %s' % thepian.get_version(),
            "Type '%s help <subcommand>' for help on a specific subcommand." % prog_name,
            'Available subcommands:',
        ]
        commands = self.get_commands().keys()
        commands.sort()
        return '\n'.join(usage + ['  %s' % cmd for cmd in commands])

    def execute(self,argv=None):
        """
        Given the command-line arguments, this figures out which subcommand is
        being run, creates a parser appropriate to that command, and runs it.
        """
        argv = argv or sys.argv[:]
        prog_name = os.path.basename(argv[0])
        
        try:
            subcommand = argv[1]
        except IndexError:
            sys.stderr.write("Type '%s help' for usage.\n" % prog_name)
            sys.exit(1)
        
        try:
            if subcommand == 'help':
                import thepian
                parser = LaxOptionParser(version=thepian.get_version(), option_list=BaseCommand.option_list)
                options, args = parser.parse_args(argv)
                if len(args) > 2:
                    self[args[2]].print_help(prog_name, args[2])
                else:
                    sys.stderr.write(self.main_help_text(argv) + '\n')
                    sys.exit(1)
            else:
                wrapper = self[subcommand]
                if getattr(wrapper.cmd,'requires_machine',False):
                    from thepian.conf import structure
                    if not structure.machine.known:
                        sys.stderr.write('Machine is not known (mac %s), cannot execute %s\n' % (structure.machine['mac'],repr(wrapper.cmd)))
                        return
                        #TODO return error code
                wrapper.run_from_argv(argv)

        except CommandError, e:
            sys.stderr.write("%s\nType '%s help' for usage\n" % (e.message,os.path.basename(argv[0])))
            #TODO return error code


        
    
COMMANDS = Cmds()
