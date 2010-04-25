from optparse import make_option, OptionParser

was_called = False

help = 'This is the test command bla.bla.'
args = '[installation]'
option_list = ()

def get_version():
    return 0.1
    
def create_parser(prog_name, subcommand):
    usage = '%%prog %s [options] %s' % (subcommand, args)
    usage = '%s\n\n%s' % (usage, help)
    return OptionParser(prog=prog_name, usage=usage, version=get_version(), option_list=option_list)

def handle(*args,**options):
    was_called = True
    return 'hey there'
                
