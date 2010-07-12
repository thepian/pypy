"""
submit failure or test session information to a pastebin service. 

Usage
----------

**Creating a URL for each test failure**::

    py.test --pastebin=failed 

This will submit test run information to a remote Paste service and
provide a URL for each failure.  You may select tests as usual or add
for example ``-x`` if you only want to send one particular failure. 

**Creating a URL for a whole test session log**::

    py.test --pastebin=all 

Currently only pasting to the http://paste.pocoo.org service is implemented.  

"""
import py, sys

class url:
    base = "http://paste.pocoo.org"
    xmlrpc = base + "/xmlrpc/"
    show = base + "/show/"

def pytest_addoption(parser):
    group = parser.getgroup("terminal reporting")
    group._addoption('--pastebin', metavar="mode",
        action='store', dest="pastebin", default=None, 
        type="choice", choices=['failed', 'all'], 
        help="send failed|all info to Pocoo pastebin service.")

def pytest_configure(__multicall__, config):
    import tempfile
    __multicall__.execute()
    if config.option.pastebin == "all":
        config._pastebinfile = tempfile.TemporaryFile('w+')
        tr = config.pluginmanager.getplugin('terminalreporter')
        oldwrite = tr._tw.write 
        def tee_write(s, **kwargs):
            oldwrite(s, **kwargs)
            config._pastebinfile.write(str(s))
        tr._tw.write = tee_write 

def pytest_unconfigure(config): 
    if hasattr(config, '_pastebinfile'):
        config._pastebinfile.seek(0)
        sessionlog = config._pastebinfile.read()
        config._pastebinfile.close()
        del config._pastebinfile
        proxyid = getproxy().newPaste("python", sessionlog)
        pastebinurl = "%s%s" % (url.show, proxyid)
        sys.stderr.write("pastebin session-log: %s\n" % pastebinurl)
        tr = config.pluginmanager.getplugin('terminalreporter')
        del tr._tw.__dict__['write']
        
def getproxy():
    return py.std.xmlrpclib.ServerProxy(url.xmlrpc).pastes

def pytest_terminal_summary(terminalreporter):
    if terminalreporter.config.option.pastebin != "failed":
        return
    tr = terminalreporter
    if 'failed' in tr.stats:
        terminalreporter.write_sep("=", "Sending information to Paste Service")
        if tr.config.option.debug:
            terminalreporter.write_line("xmlrpcurl: %s" %(url.xmlrpc,))
        serverproxy = getproxy()
        for rep in terminalreporter.stats.get('failed'):
            try:
                msg = rep.longrepr.reprtraceback.reprentries[-1].reprfileloc
            except AttributeError:
                msg = tr._getfailureheadline(rep)
            tw = py.io.TerminalWriter(stringio=True)
            rep.toterminal(tw)
            s = tw.stringio.getvalue()
            assert len(s)
            proxyid = serverproxy.newPaste("python", s)
            pastebinurl = "%s%s" % (url.show, proxyid)
            tr.write_line("%s --> %s" %(msg, pastebinurl))
