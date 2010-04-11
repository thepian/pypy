# NOT_RPYTHON
import sys,os,os.path

def find_commands(management_dir):
    """
    Given a path to a management directory, returns a list of all the command
    names that are available.

    Returns an empty list if no commands are defined.
    """
    command_dir = os.path.join(management_dir, 'commands')
    try:
        return [f[:-3] for f in os.listdir(command_dir)
                if not f.startswith('_') and f.endswith('.py')]
    except OSError:
        return []

exe_mappings = {
    '': 'pypy-c',
    'py.py':'pypy-c',
}

def find_executable_command_modules():
    exename = os.path.split(sys.executable)[1]
    exename = exename in exe_mappings and exe_mappings[exename] or exename
    r = []
    for syspath in sys.path:
        if os.path.isdir(syspath):
            path0 = os.path.join(syspath,exename)
            commands_path = os.path.join(syspath,exename,'commands')
            print commands_path
            if os.path.isdir(path0) and os.path.isdir(commands_path):
                r.append(commands_path)
    return r
                    
def find_command_modules():
    r = []
    for p in sys.path:
        if os.path.isdir(p):
            for pp in os.listdir(p):
                cp = os.path.join(p,pp,'commands')
                if os.path.isdir(cp): r.append(pp)
    return r

def get_mod_path(name):
    i = __import__(name,{},{},[])
    return i.__path__[0]

class CommandError(Exception):
    pass

class CommandWrapper(object):

    def __init__(self,cmd=None,base=None,name=None):
        self._cmd = cmd
        self.base = base
        self.name = name

    def get_cmd(self):
        """
        Instantiate the command if not yet loade. All errors raised by the import process
        (ImportError, AttributeError) are allowed to propagate.
        """
        if not self._cmd:
            self._cmd = getattr(__import__('%s.commands.%s' % (self.base, self.name),
                {}, {}, ['Command']), 'Command')()
        return self._cmd
    cmd = property(get_cmd)

    def get_option_list(self):
        return getattr(self.cmd,'option_list',BaseCommand.option_list)
    option_list = property(get_option_list)

    def get_help(self):
        return getattr(self.cmd,'help',BaseCommand.help)
    help = property(get_help)

    def get_args(self):
        return getattr(self.cmd,'args',BaseCommand.args)
    args = property(get_args)

    def get_style(self):
        return getattr(self.cmd,'style',color_style())
    style = property(get_style)


    def get_version(self):
        if hasattr(self.cmd,'get_version'):
            return self.cmd.get_version()
        import thepian
        return thepian.VERSION

    def usage(self, subcommand):
        if hasattr(self.cmd,'usage'):
            return self.cmd.usage(subcommand)

        usage = self.style.HEADING('%%prog %s [options] %s' % (subcommand, self.args))
        if self.help:
            return '%s\n\n%s' % (usage, self.style.HIGHLIGHT(self.help))
        else:
            return usage

    def create_parser(self, prog_name, subcommand):
        if hasattr(self.cmd,'create_parser'):
            return self.cmd.create_parser(prog_name,subcommand)

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
        parser = self.create_parser(argv[0], argv[1])
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
    
    def get_commands(self):
        """
        Returns a dictionary mapping command names to their command wrappers noting the base module.
    
        This works by looking for a commands package in thepian.cmdline, and
        in each top level package -- if a commands package exists, all commands
        in that package are registered.
    
        If a specific version of a command must be loaded (e.g., with the
        startapp command), the instantiated module can be placed in the
        dictionary in place of the application name.
    
        The dictionary is cached on the first call and reused on subsequent
        calls.
        """
        if self.cache is None:
            self.cache = { 'help' : HelpWrapper() }
            # Add any top level packages with commands submodules
            for mod in find_executable_command_modules():
                try:
                    cmd_and_wrapper = [(name,CommandWrapper(base=mod,name=name)) for name in find_commands(get_mod_path(mod))]
                    self.cache.update(dict(cmd_and_wrapper))
                except ImportError,e:
                    print "Error while checking module '%s'" % mod, e
                
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
