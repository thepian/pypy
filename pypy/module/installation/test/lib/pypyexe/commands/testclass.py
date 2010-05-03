from optparse import make_option, OptionParser

class Command(object):
    
    was_called = False
    
    help = 'This is the testclass command bla.bla.'
    args = '[installation]'
    option_list = ()
    
    call_args = None
    call_options = None
    
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
        self.call_args = args
        self.call_options = options
        self.was_called = True
        return "test class command"
                
