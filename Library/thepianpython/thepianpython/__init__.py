from optparse import make_option, OptionParser

help = 'status help'
args = '[installation]'
option_list = ()
    
def get_version(self):
    return 0.1

def create_parser(self, prog_name, subcommand):
    usage = '%%prog %s [options] %s' % (subcommand, args)
    usage = '%s\n\n%s' % (usage, help)
    return OptionParser(prog=prog_name,
                        usage=usage,
                        version=get_version(),
                        option_list=option_list)
