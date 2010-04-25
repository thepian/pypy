import py
import sys

#
# main entry point
#

def main(args=None):
    if args is None:
        args = sys.argv[1:]
    config = py.test.config
    try:
        config.parse(args) 
        config.pluginmanager.do_configure(config)
        session = config.initsession()
        exitstatus = session.main()
        config.pluginmanager.do_unconfigure(config)
        raise SystemExit(exitstatus)
    except config.Error:
        e = sys.exc_info()[1]
        sys.stderr.write("ERROR: %s\n" %(e.args[0],))
        raise SystemExit(3)

