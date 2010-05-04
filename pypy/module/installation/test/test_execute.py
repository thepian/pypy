from pypy.conftest import gettestobjspace


class AppTestExecute(object):

    def test_command_call(self):
        import installation
        wrap = installation.commands['testclass']
        assert wrap.cmd and callable(wrap.cmd)
        r = wrap.run_from_argv(['','testclass','abc']) 
        text, level = r
        assert wrap.cmd.call_args == ('abc',)
        assert text == "test class command"
        assert level == 0

        wrap = installation.commands['test']
        assert not wrap.cmd
        assert wrap.mod
        assert hasattr(wrap.mod,'handle')
        assert callable(wrap.mod.handle)
        text, level = wrap.run_from_argv(['','test','abc']) 
        assert wrap.mod.call_args == ('abc',)
        assert text == "hey there"
        assert level == 0
    
    def test_main_help(self):
        import installation
        test_wrap = installation.commands['test']
        wrap = installation.commands['help']
        text, level = wrap.run_from_argv(['','help','test'])
        assert level == 1
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
        text, level = wrap.run_from_argv(['','help','testclass'])
        # assert wrap.cmd.call_args ==
        assert text == "\n".join([
        'Usage: pypyexe testclass [options] [installation]','',
        testclass_wrap.cmd.help,'',
        'Options:',
        "  --version   show program's version number and exit",
        '  -h, --help  show this help message and exit',""])
        
        test_wrap = installation.commands['test']
        wrap = installation.commands['help']
        text, level = wrap.run_from_argv(['','help','test'])
        assert text == "\n".join([
        'Usage: pypyexe test [options] [installation]','',
        test_wrap.mod.help,'',
        'Options:',
        "  --version   show program's version number and exit",
        '  -h, --help  show this help message and exit',""])

