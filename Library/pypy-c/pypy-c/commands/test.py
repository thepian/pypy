import os
from thepian.cmdline.base import NoArgsCommand
from optparse import make_option

class Command(NoArgsCommand):
    option_list = NoArgsCommand.option_list
    help = "Runs the tests found in the current directory."

    def handle_noargs(self, **options):
        import py 
        py.test.cmdline.main()