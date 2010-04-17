
from pypy.conftest import gettestobjspace

class AppTestParsing(object):
    def setup_class(cls):
        space = cls.space = gettestobjspace(usemodules=('installation','sys',))
        import sys
        from os.path import dirname,join
        # sys.executable_name = "pypy-c"
        space.setattr(space.sys, space.wrap("executable_name"), space.wrap("pypy-c"))
        # sys.product_name = "pypy"
        space.setattr(space.sys, space.wrap("product_name"), space.wrap("pypy"))
        
        # prepend sys.path
        # sys.path.insert(0,lib_path)
        w_path = space.sys.get('path')
        path_0 = space.unwrap(w_path.wrappeditems[0])
        lib_path = join(dirname(path_0),'module','installation','test','lib')
        space.call_method(w_path, "insert", space.wrap(0), space.wrap(lib_path))
        
    def test_sanity(self):
        import sys
        assert sys.product_name == "pypy"
        assert sys.path[0] == "/repositories/pypy/pypy/module/installation/test/lib"
        
    def test_find_commands(self):
        import installation
        commands = installation.find_commands("/repositories/pypy/pypy/module/installation/test/lib/pypy")
        assert commands == ["test"]
        
    def test_get_default_modules(self):
        import installation, sys
        sys.argv = ["command.py","test"]
        assert installation.commands.get_default_modules() == ["pypy","command"]
    
    def test_find(self):
        import installation, sys
        sys.argv = ["command.py","test"]
        commands = installation.commands
        assert 'help' in commands
        assert 'test' in commands
        assert commands['help'] is not None
        assert commands['test'] is not None

    def test_execute(self):
        import installation
        installation.commands.execute(['test','test'])
