
from pypy.conftest import gettestobjspace


class AppTestCall(object):
    def setup_class(cls):
        space = cls.space = gettestobjspace(usemodules=('installation','sys',))
        import sys
        from os.path import dirname,join
        # sys.executable_name = "pypy-c"
        space.setattr(space.sys, space.wrap("executable_name"), space.wrap("pypy-c"))
        # sys.product_name = "pypy"
        space.setattr(space.sys, space.wrap("product_name"), space.wrap("pypyexe"))

        # sys.argv = ["command.py","test"]
        space.setattr(space.sys, space.wrap("argv"), space.wrap(["command.py","test"]))
        
        # prepend sys.path
        # sys.path.insert(0,lib_path)
        w_path = space.sys.get('path')
        path_0 = space.unwrap(w_path.wrappeditems[0])
        if not path_0.endswith("pypy/module/installation/test/lib"):
            lib_path = join(dirname(path_0),'module','installation','test','lib')
            space.call_method(w_path, "insert", space.wrap(0), space.wrap(lib_path))
        
    def test_main_help(self):
        import installation
        wrap = installation.commands['help']
        text,level = wrap()
        assert text == """\
pypyexe <subcommand> [options] [args]
Thepian command line tool, version 0.1
Type 'pypyexe help <subcommand>' for help on a specific subcommand.
Available subcommands:
  help
  test
  testclass
"""

    def test_command_help(self):
        import installation
        testclass_wrap = installation.commands['testclass']
        wrap = installation.commands['help']
        text, level = wrap('testclass') 
        assert text == "\n".join([
        'Usage: pypyexe testclass [options] [installation]','',
        testclass_wrap.cmd.help,'',
        'Options:',
        "  --version   show program's version number and exit",
        '  -h, --help  show this help message and exit',""])

        test_wrap = installation.commands['test']
        wrap = installation.commands['help']
        text, level = wrap('test') 
        assert text == "\n".join([
        'Usage: pypyexe test [options] [installation]','',
        test_wrap.mod.help,'',
        'Options:',
        "  --version   show program's version number and exit",
        '  -h, --help  show this help message and exit',""])

    def test_command_call(self):
        import installation
        wrap = installation.commands['testclass']
        assert wrap.cmd and callable(wrap.cmd)
        text, level = wrap() 
        assert text == "test class command"
        assert level == 0

        wrap = installation.commands['test']
        assert wrap.mod
        assert hasattr(wrap.mod,'handle')
        assert callable(wrap.mod.handle)
        text, level = wrap() 
        assert text == "hey there"
        assert level == 0
