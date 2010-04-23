
class Command(object):
    
    help = 'status help'
    args = '[installation]'
    option_list = ()
    
    def __call__(self,*args,**options):
        print 'Status'