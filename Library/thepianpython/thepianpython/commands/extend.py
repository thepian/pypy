from optparse import make_option, OptionParser
import os
from pip.req import InstallRequirement, RequirementSet
from pip.req import parse_requirements
from pip.log import logger
from pip.locations import build_prefix, src_prefix
from pip.basecommand import Command
from pip.index import PackageFinder


class Command(object):
    
    help = 'Extend the runtime library by adding a package from PYPI or a Source Repository'
    args = 'PACKAGE-URL'
    option_list = ()
    
    def get_version(self):
        return 0.1
        
    def create_parser(self, prog_name, subcommand):
        usage = '%%prog %s [options] %s' % (subcommand, self.args)
        usage = '%s\n\n%s' % (usage, self.help)
        return OptionParser(prog=prog_name,
                            usage=usage,
                            version=self.get_version(),
                            option_list=self.option_list)

    def __call__(self,*args,**options):
        return 'Bundle command run\n'
