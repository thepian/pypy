"""
Fundamental Command definitions
Taken from the Django core
"""
from __future__ import with_statement
import sys, os, re
from optparse import make_option, OptionParser

class ImproperlyConfigured(Exception):
    pass
    
class CommandError(Exception):
    pass

class BaseCommand(object):
    # Metadata about this command.
    option_list = (
        make_option('--cluster', dest="cluster", help='The name of the active cluster'),
        make_option('--settings',
            help='The Python path to a settings module, e.g. "myproject.settings.main". If this isn\'t provided, the THEPIANPYTHON_SETTINGS_MODULE environment variable will be used.'),
        make_option('--pythonpath',
            help='A directory to add to the Python path, e.g. "~/myproject".'),
        make_option('--traceback', action='store_true',
            help='Print traceback on exception'),
    )
    help = ''
    args = ''

    def __init__(self):
        self.style = color_style()

    def get_version(self):
        return 0.1
        
    def create_parser(self, prog_name, subcommand):
        usage = '%%prog %s [options] %s' % (subcommand, self.args)
        usage = '%s\n\n%s' % (usage, self.help)
        return OptionParser(prog=prog_name,
                            usage=usage,
                            version=self.get_version(),
                            option_list=self.option_list)

    def print_help(self, prog_name, subcommand):
        parser = self.create_parser(prog_name, subcommand)
        parser.print_help()

    def __call__(self, *args, **options):
        try:
            if len(args) and len(self.args)==0:
                raise CommandError("Command doesn't accept any arguments")
            if len(args)==0 and len(self.args) and not re.compile('\[.+\]').match(self.args):
                raise CommandError("Command requires arguments (%s)" % self.args)
            output = self.handle(*args, **options)
            if output:
                print output
        except CommandError, e:
            sys.stderr.write(self.style.ERROR(str('Error: %s\n' % e)))
            sys.exit(1)

    def handle(self, *args, **options):
        raise NotImplementedError()

class NoArgsCommand(BaseCommand):
    args = ''

    def handle(self, *args, **options):
        if args:
            raise CommandError("Command doesn't accept any arguments")
        return self.handle_noargs(**options)

    def handle_noargs(self, **options):
        raise NotImplementedError()


def supports_color():
    """
    Returns True if the running system's terminal supports color, and False
    otherwise.
    """
    unsupported_platform = (sys.platform in ('win32', 'Pocket PC')
                            or sys.platform.startswith('java'))
    # isatty is not always implemented, #6223.
    is_a_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
    if unsupported_platform or not is_a_tty:
        return False
    return True

def color_style():
    """Returns a Style object with the Django color scheme."""
    if not supports_color():
        return no_style()
    class dummy: pass
    style = dummy()
    style.ERROR = make_style(fg='red', opts=('bold',))
    style.ERROR_OUTPUT = make_style(fg='red', opts=('bold',))
    style.NOTICE = make_style(fg='red')
    style.HEADING = make_style(fg='cyan', opts=('bold',))
    style.HIGHLIGHT = make_style(opts=('bold',))
    style.SQL_FIELD = make_style(fg='green', opts=('bold',))
    style.SQL_COLTYPE = make_style(fg='green')
    style.SQL_KEYWORD = make_style(fg='yellow')
    style.SQL_TABLE = make_style(opts=('bold',))
    return style

def no_style():
    """Returns a Style object that has no colors."""
    class dummy:
        def __getattr__(self, attr):
            return lambda x: x
    return dummy()

color_names = ('black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white')
foreground = dict([(color_names[x], '3%s' % x) for x in range(8)])
background = dict([(color_names[x], '4%s' % x) for x in range(8)])
del color_names

RESET = '0'
opt_dict = {'bold': '1', 'underscore': '4', 'blink': '5', 'reverse': '7', 'conceal': '8'}

def colorize(text='', opts=(), **kwargs):
    """
    Returns your text, enclosed in ANSI graphics codes.

    Depends on the keyword arguments 'fg' and 'bg', and the contents of
    the opts tuple/list.

    Returns the RESET code if no parameters are given.

    Valid colors:
        'black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'

    Valid options:
        'bold'
        'underscore'
        'blink'
        'reverse'
        'conceal'
        'noreset' - string will not be auto-terminated with the RESET code

    Examples:
        colorize('hello', fg='red', bg='blue', opts=('blink',))
        colorize()
        colorize('goodbye', opts=('underscore',))
        print colorize('first line', fg='red', opts=('noreset',))
        print 'this should be red too'
        print colorize('and so should this')
        print 'this should not be red'
    """
    text = str(text)
    code_list = []
    if text == '' and len(opts) == 1 and opts[0] == 'reset':
        return '\x1b[%sm' % RESET
    for k, v in kwargs.iteritems():
        if k == 'fg':
            code_list.append(foreground[v])
        elif k == 'bg':
            code_list.append(background[v])
    for o in opts:
        if o in opt_dict:
            code_list.append(opt_dict[o])
    if 'noreset' not in opts:
        text = text + '\x1b[%sm' % RESET
    return ('\x1b[%sm' % ';'.join(code_list)) + text

def make_style(opts=(), **kwargs):
    """
    Returns a function with default parameters for colorize()

    Example:
        bold_red = make_style(opts=('bold',), fg='red')
        print bold_red('hello')
        KEYWORD = make_style(fg='yellow')
        COMMENT = make_style(fg='blue', opts=('bold',))
    """
    return lambda text: colorize(text, opts, **kwargs)
    
