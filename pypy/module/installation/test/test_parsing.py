
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
        
        # prepend sys.path
        # sys.path.insert(0,lib_path)
        w_path = space.sys.get('path')
        path_0 = space.unwrap(w_path.wrappeditems[0])
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
        assert commands == ["help","test","testclass"]
        
    def test_get_default_modules(self):
        import installation, sys
        sys.argv = ["command.py","test"]
        assert installation.commands.get_default_modules() == ["pypyexe","command"]
    
    def test_find(self):
        import installation, sys
        sys.argv = ["command.py","test"]
        commands = installation.commands
        assert 'help' in commands
        assert 'test' in commands
        assert commands['help'] is not None
        assert commands['test'] is not None
        
    def test_create_parser(self):
        import installation
        wrap = installation.commands['testclass']
        parser = wrap.create_parser('command','testclass')
        assert parser
        
    def test_class_command(self):
        import installation
        cmd = installation.commands['testclass'].cmd
        assert cmd and callable(cmd)
        installation.commands.execute(['command.py','testclass'])
        assert cmd.was_called

    def test_execute(self):
        import installation
        installation.commands.execute(['command.py','test'])
