from optparse import make_option, OptionParser

print 'import status'

class Command(object):
    
    help = 'status help'
    args = '[installation]'
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
        return 'Status command run\n'
        