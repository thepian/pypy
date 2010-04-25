
from pypy.conftest import gettestobjspace


class AppTestParsing(object):
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
        
    def test_sanity(self):
        def make_path(relative):
            import os
            cwd = os.getcwd().split(os.sep)
            return os.sep.join([cwd[0],cwd[1],cwd[2],relative])

        import sys
        assert sys.product_name == "pypyexe"
        assert sys.path[0] == make_path("pypy/module/installation/test/lib")
        
    def test_find_commands(self):
        def make_path(relative):
            import os
            cwd = os.getcwd().split(os.sep)
            return os.sep.join([cwd[0],cwd[1],cwd[2],relative])

        import installation
        commands = installation.find_commands(make_path("pypy/module/installation/test/lib/pypyexe"))
        assert commands == ["test","testclass"]
        
    def test_get_default_modules(self):
        import installation, sys
        assert installation.commands.get_default_modules() == ["pypyexe","command"]
    
    def test_find(self):
        import installation, sys
        sys.argv = ["command.py","test"]
        commands = installation.commands
        assert 'test' in commands
        assert 'testclass' in commands
        assert commands['test'] is not None
        assert commands['testclass'] is not None
        
    def test_help(self):
        def make_path(relative):
            import os
            cwd = os.getcwd().split(os.sep)
            return os.sep.join([cwd[0],cwd[1],cwd[2],relative])
            
        import installation, sys
        sys.argv = ["command.py","test"]
        commands = installation.commands
        assert commands['help'].mod
        assert hasattr(commands['help'].mod,'this_is_init')
        assert commands['help'].mod.__path__[0] == make_path("pypy/module/installation/test/lib/pypyexe/commands")
        assert commands['help'].mod.__file__ == make_path("pypy/module/installation/test/lib/pypyexe/commands/__init__.pyc")
        
    def fails_test_create_parser(self):
        import installation
        wrap = installation.commands['test']
        assert wrap.mod
        assert wrap.cmd is None
        assert wrap.mod.was_called is False
        parser = wrap.create_parser('command','test')
        assert parser
        assert not isinstance(parser,installation._NoParser)
        assert parser.format_help() == "\n".join([
        'Usage: command test [options] [installation]','',
        wrap.mod.help,'',
        'Options:',
        "  --version   show program's version number and exit",
        '  -h, --help  show this help message and exit',""])

    def test_class_create_parser(self):
        import installation
        wrap = installation.commands['testclass']
        parser = wrap.create_parser('command','testclass')
        assert parser
        assert parser.format_help() == "\n".join([
        'Usage: command testclass [options] [installation]','',
        wrap.cmd.help,'',
        'Options:',
        "  --version   show program's version number and exit",
        '  -h, --help  show this help message and exit',""])
