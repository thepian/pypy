from pypy.conftest import gettestobjspace


class AppTestExecute(object):
    
    def test2_myoutput(capsys):
        import sys #, capsys
        print ("hello")
        sys.stderr.write("world\n")
        out, err = capsys.readouterr()
        assert out == "hello\n"
        assert err == "world\n"
        print "next"
        out, err = capsys.readouterr()
        assert out == "next\n"

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

