"""
Fundamental Command definitions
Taken from the Django core
"""
from __future__ import with_statement
import sys, os, re
from optparse import make_option, OptionParser

#TODO from thepian.cmdline.color import color_style

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
        return OptionParser(prog=prog_name,
                            usage=self.usage(subcommand),
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
    
