"""
interactive debugging with the Python Debugger.
"""
import py
import pdb, sys, linecache

def pytest_addoption(parser):
    group = parser.getgroup("general") 
    group._addoption('--pdb',
               action="store_true", dest="usepdb", default=False,
               help="start the interactive Python debugger on errors.")

def pytest_configure(config):
    if config.getvalue("usepdb"):
        config.pluginmanager.register(PdbInvoke(), 'pdb')

class PdbInvoke:
    def pytest_runtest_makereport(self, item, call):
        if call.excinfo and not \
           call.excinfo.errisinstance(py.test.skip.Exception): 
            # play well with capturing, slightly hackish
            capman = item.config.pluginmanager.getplugin('capturemanager')
            capman.suspendcapture() 

            tw = py.io.TerminalWriter()
            repr = call.excinfo.getrepr()
            repr.toterminal(tw) 
            post_mortem(call.excinfo._excinfo[2])

            capman.resumecapture_item(item)

class Pdb(py.std.pdb.Pdb):
    def do_list(self, arg):
        self.lastcmd = 'list'
        last = None
        if arg:
            try:
                x = eval(arg, {}, {})
                if type(x) == type(()):
                    first, last = x
                    first = int(first)
                    last = int(last)
                    if last < first:
                        # Assume it's a count
                        last = first + last
                else:
                    first = max(1, int(x) - 5)
            except:
                print ('*** Error in argument: %s' % repr(arg))
                return
        elif self.lineno is None:
            first = max(1, self.curframe.f_lineno - 5)
        else:
            first = self.lineno + 1
        if last is None:
            last = first + 10
        filename = self.curframe.f_code.co_filename
        breaklist = self.get_file_breaks(filename)
        try:
            for lineno in range(first, last+1):
                # start difference from normal do_line
                line = self._getline(filename, lineno)
                # end difference from normal do_line
                if not line:
                    print ('[EOF]')
                    break
                else:
                    s = repr(lineno).rjust(3)
                    if len(s) < 4: s = s + ' '
                    if lineno in breaklist: s = s + 'B'
                    else: s = s + ' '
                    if lineno == self.curframe.f_lineno:
                        s = s + '->'
                    sys.stdout.write(s + '\t' + line)
                    self.lineno = lineno
        except KeyboardInterrupt:
            pass
    do_l = do_list

    def _getline(self, filename, lineno):
        if hasattr(filename, "__source__"):
            try:
                return filename.__source__.lines[lineno - 1] + "\n"
            except IndexError:
                return None
        return linecache.getline(filename, lineno)

    def get_stack(self, f, t):
        # Modified from bdb.py to be able to walk the stack beyond generators,
        # which does not work in the normal pdb :-(
        stack, i = pdb.Pdb.get_stack(self, f, t)
        if f is None:
            i = max(0, len(stack) - 1)
            while i and stack[i][0].f_locals.get("__tracebackhide__", False):
                i-=1
        return stack, i

def post_mortem(t):
    p = Pdb()
    p.reset()
    p.interaction(None, t)

def set_trace():
    # again, a copy of the version in pdb.py
    Pdb().set_trace(sys._getframe().f_back)
