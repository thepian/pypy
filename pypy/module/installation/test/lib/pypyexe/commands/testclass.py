class Command(object):
    options = ()
    help = ''
    args = ''
    
    was_called = False
    
    def __call__(self, *args, **options):
        self.was_called = True