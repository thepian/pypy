
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
        
    def test_class_command(self):
        import installation
        cmd = installation.commands['testclass'].cmd
        assert cmd and callable(cmd)
        installation.commands['testclass']()
        assert cmd.was_called

    def test_execute(self):
        import installation
        installation.commands['test']()

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
