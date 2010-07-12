"""A compatibility wrapper reimplementing the 'readline' standard module
on top of pyrepl.  Not all functionalities are supported.  Contains
extensions for multiline input.
"""

import sys, os
from pyrepl import commands
from pyrepl.historical_reader import HistoricalReader
from pyrepl.completing_reader import CompletingReader
from pyrepl.unix_console import UnixConsole


ENCODING = 'latin1'     # XXX hard-coded

__all__ = ['add_history',
           'clear_history',
           'get_begidx',
           'get_completer',
           'get_completer_delims',
           'get_current_history_length',
           'get_endidx',
           'get_history_item',
           'get_history_length',
           'get_line_buffer',
           'insert_text',
           'parse_and_bind',
           'read_history_file',
           'read_init_file',
           'redisplay',
           'remove_history_item',
           'replace_history_item',
           'set_completer',
           'set_completer_delims',
           'set_history_length',
           'set_pre_input_hook',
           'set_startup_hook',
           'write_history_file',
           # ---- multiline extensions ----
           'multiline_input',
           ]

# ____________________________________________________________

class ReadlineConfig(object):
    readline_completer = None
    completer_delims = dict.fromkeys(' \t\n`~!@#$%^&*()-=+[{]}\\|;:\'",<>/?')

class ReadlineAlikeReader(HistoricalReader, CompletingReader):

    def error(self, msg="none"):
        pass    # don't show error messages by default

    def get_stem(self):
        b = self.buffer
        p = self.pos - 1
        completer_delims = self.config.completer_delims
        while p >= 0 and b[p] not in completer_delims:
            p -= 1
        return ''.join(b[p+1:self.pos])

    def get_completions(self, stem):
        result = []
        function = self.config.readline_completer
        if function is not None:
            try:
                stem = str(stem)   # rlcompleter.py seems to not like unicode
            except UnicodeEncodeError:
                pass   # but feed unicode anyway if we have no choice
            state = 0
            while True:
                next = function(stem, state)
                if not isinstance(next, str):
                    break
                result.append(next)
                state += 1
            # emulate the behavior of the standard readline that sorts
            # the completions before displaying them.  Note that the
            # screen order is still a bit different because pyrepl
            # displays them in this order:   and readline in this one:
            #                     [A][B][C]                       A C E
            #                     [D][E][F]                       B D F
            result.sort()
        return result

    def get_trimmed_history(self, maxlength):
        if maxlength >= 0:
            cut = len(self.history) - maxlength
            if cut < 0:
                cut = 0
        else:
            cut = 0
        return self.history[cut:]

    # --- simplified support for reading multiline Python statements ---

    # This duplicates small parts of pyrepl.python_reader.  I'm not
    # reusing the PythonicReader class directly for two reasons.  One is
    # to try to keep as close as possible to CPython's prompt.  The
    # other is that it is the readline module that we are ultimately
    # implementing here, and I don't want the built-in raw_input() to
    # start trying to read multiline inputs just because what the user
    # typed look like valid but incomplete Python code.  So we get the
    # multiline feature only when using the multiline_input() function
    # directly (see _pypy_interact.py).

    more_lines = None

    def collect_keymap(self):
        return super(ReadlineAlikeReader, self).collect_keymap() + (
            (r'\n', 'maybe-accept'),)

    def __init__(self, console):
        super(ReadlineAlikeReader, self).__init__(console)
        self.commands['maybe_accept'] = maybe_accept
        self.commands['maybe-accept'] = maybe_accept

    def after_command(self, cmd):
        super(ReadlineAlikeReader, self).after_command(cmd)
        if self.more_lines is None:
            # Force single-line input if we are in raw_input() mode.
            # Although there is no direct way to add a \n in this mode,
            # multiline buffers can still show up using various
            # commands, e.g. navigating the history.
            try:
                index = self.buffer.index("\n")
            except ValueError:
                pass
            else:
                self.buffer = self.buffer[:index]
                if self.pos > len(self.buffer):
                    self.pos = len(self.buffer)

class maybe_accept(commands.Command):
    def do(self):
        r = self.reader
        # if there are already several lines and the cursor
        # is not on the last one, always insert a new \n.
        text = r.get_unicode()
        if "\n" in r.buffer[r.pos:]:
            r.insert("\n")
        elif r.more_lines is not None and r.more_lines(text):
            r.insert("\n")
        else:
            self.finish = 1

# ____________________________________________________________

class _ReadlineWrapper(object):
    f_in = 0
    f_out = 1
    reader = None
    saved_history_length = -1
    startup_hook = None
    config = ReadlineConfig()

    def get_reader(self):
        if self.reader is None:
            console = UnixConsole(self.f_in, self.f_out, encoding=ENCODING)
            self.reader = ReadlineAlikeReader(console)
            self.reader.config = self.config
        return self.reader

    def raw_input(self, prompt=''):
        reader = self.get_reader()
        if self.startup_hook is not None:
            self.startup_hook()
        reader.ps1 = prompt
        return reader.readline()

    def multiline_input(self, more_lines, ps1, ps2):
        """Read an input on possibly multiple lines, asking for more
        lines as long as 'more_lines(unicodetext)' returns an object whose
        boolean value is true.
        """
        reader = self.get_reader()
        saved = reader.more_lines
        try:
            reader.more_lines = more_lines
            reader.ps1 = reader.ps2 = ps1
            reader.ps3 = reader.ps4 = ps2
            return reader.readline()
        finally:
            reader.more_lines = saved

    def parse_and_bind(self, string):
        pass  # XXX we don't support parsing GNU-readline-style init files

    def set_completer(self, function=None):
        self.config.readline_completer = function

    def get_completer(self):
        return self.config.readline_completer

    def set_completer_delims(self, string):
        self.config.completer_delims = dict.fromkeys(string)

    def get_completer_delims(self):
        chars = self.config.completer_delims.keys()
        chars.sort()
        return ''.join(chars)

    def _histline(self, line):
        return unicode(line.rstrip('\n'), ENCODING)

    def get_history_length(self):
        return self.saved_history_length

    def set_history_length(self, length):
        self.saved_history_length = length

    def get_current_history_length(self):
        return len(self.get_reader().history)

    def read_history_file(self, filename='~/.history'):
        # multiline extension (really a hack) for the end of lines that
        # are actually continuations inside a single multiline_input()
        # history item: we use \r\n instead of just \n.  If the history
        # file is passed to GNU readline, the extra \r are just ignored.
        history = self.get_reader().history
        f = open(os.path.expanduser(filename), 'r')
        buffer = []
        for line in f:
            if line.endswith('\r\n'):
                buffer.append(line)
            else:
                line = self._histline(line)
                if buffer:
                    line = ''.join(buffer).replace('\r', '') + line
                    del buffer[:]
                if line:
                    history.append(line)
        f.close()

    def write_history_file(self, filename='~/.history'):
        maxlength = self.saved_history_length
        history = self.get_reader().get_trimmed_history(maxlength)
        f = open(os.path.expanduser(filename), 'w')
        for entry in history:
            if isinstance(entry, unicode):
                entry = entry.encode(ENCODING)
            entry = entry.replace('\n', '\r\n')   # multiline history support
            f.write(entry + '\n')
        f.close()

    def clear_history(self):
        del self.get_reader().history[:]

    def get_history_item(self, index):
        history = self.get_reader().history
        if 1 <= index <= len(history):
            return history[index-1]
        else:
            return None        # blame readline.c for not raising

    def remove_history_item(self, pos):
        history = self.get_reader().history
        if 1 <= index <= len(history):
            del history[index-1]
        else:
            raise ValueError("No history item at position %d" % index)
            # blame readline.c for raising ValueError

    def replace_history_item(self, pos, line):
        history = self.get_reader().history
        if 1 <= index <= len(history):
            history[index-1] = self._histline(line)
        else:
            raise ValueError("No history item at position %d" % index)
            # blame readline.c for raising ValueError

    def add_history(self, line):
        self.get_reader().history.append(self._histline(line))

    def set_startup_hook(self, function=None):
        self.startup_hook = function

_wrapper = _ReadlineWrapper()

# ____________________________________________________________
# Public API

parse_and_bind = _wrapper.parse_and_bind
set_completer = _wrapper.set_completer
get_completer = _wrapper.get_completer
set_completer_delims = _wrapper.set_completer_delims
get_completer_delims = _wrapper.get_completer_delims
get_history_length = _wrapper.get_history_length
set_history_length = _wrapper.set_history_length
get_current_history_length = _wrapper.get_current_history_length
read_history_file = _wrapper.read_history_file
write_history_file = _wrapper.write_history_file
clear_history = _wrapper.clear_history
get_history_item = _wrapper.get_history_item
remove_history_item = _wrapper.remove_history_item
replace_history_item = _wrapper.replace_history_item
add_history = _wrapper.add_history
set_startup_hook = _wrapper.set_startup_hook

# Extension
multiline_input = _wrapper.multiline_input

# Internal hook
_get_reader = _wrapper.get_reader

# ____________________________________________________________
# Stubs

def _make_stub(_name, _ret):
    def stub(*args, **kwds):
        import warnings
        warnings.warn("readline.%s() not implemented" % _name, stacklevel=2)
    stub.func_name = _name
    globals()[_name] = stub

for _name, _ret in [
    ('get_line_buffer', ''),
    ('insert_text', None),
    ('read_init_file', None),
    ('redisplay', None),
    ('set_pre_input_hook', None),
    ('get_begidx', 0),
    ('get_endidx', 0),
    ]:
    assert _name not in globals(), _name
    _make_stub(_name, _ret)

# ____________________________________________________________

def _setup():
    try:
        f_in = sys.stdin.fileno()
        f_out = sys.stdout.fileno()
    except (AttributeError, ValueError):
        return
    if not os.isatty(f_in) or not os.isatty(f_out):
        return

    _wrapper.f_in = f_in
    _wrapper.f_out = f_out

    if hasattr(sys, '__raw_input__'):    # PyPy
        sys.__raw_input__ = _wrapper.raw_input
    else:
        # this is not really what readline.c does.  Better than nothing I guess
        import __builtin__
        __builtin__.raw_input = _wrapper.raw_input

_setup()
