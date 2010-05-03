import os, sys
from optparse import make_option
from _base import *

class Command(BaseCommand):
    option_list = ()
    args = "module"
    help = "Runs the tests found in the current directory."

    def __call__(self, *args, **options):
        import py 
        print sys.path, args
        args = ['Library/thepianpython/thepianpython']
        py.test.cmdline.main(args)