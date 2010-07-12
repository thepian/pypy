"""
   logging of test results in JUnit-XML format, for use with Hudson 
   and build integration servers.  Based on initial code from Ross Lawley.
"""

import py
import time

def pytest_addoption(parser):
    group = parser.getgroup("terminal reporting")
    group.addoption('--junitxml', action="store", dest="xmlpath", 
           metavar="path", default=None,
           help="create junit-xml style report file at given path.")

def pytest_configure(config):
    xmlpath = config.option.xmlpath
    if xmlpath:
        config._xml = LogXML(xmlpath)
        config.pluginmanager.register(config._xml)

def pytest_unconfigure(config):
    xml = getattr(config, '_xml', None)
    if xml:
        del config._xml 
        config.pluginmanager.unregister(xml)

class LogXML(object):
    def __init__(self, logfile):
        self.logfile = logfile
        self.test_logs = []
        self.passed = self.skipped = 0
        self.failed = self.errors = 0
        self._durations = {}
  
    def _opentestcase(self, report):
        node = report.item 
        d = {'time': self._durations.pop(report.item, "0")}
        names = [x.replace(".py", "") for x in node.listnames() if x != "()"]
        d['classname'] = ".".join(names[:-1])
        d['name'] = names[-1]
        attrs = ['%s="%s"' % item for item in sorted(d.items())]
        self.test_logs.append("\n<testcase %s>" % " ".join(attrs))

    def _closetestcase(self):
        self.test_logs.append("</testcase>")

    def appendlog(self, fmt, *args):
        args = tuple([py.xml.escape(arg) for arg in args])
        self.test_logs.append(fmt % args)
         
    def append_pass(self, report):
        self.passed += 1
        self._opentestcase(report)
        self._closetestcase()

    def append_failure(self, report):
        self._opentestcase(report)
        #msg = str(report.longrepr.reprtraceback.extraline)
        if "xfail" in report.keywords:
            self.appendlog(
                '<skipped message="xfail-marked test passes unexpectedly"/>')
            self.skipped += 1
        else:
            self.appendlog('<failure message="test failure">%s</failure>', 
                report.longrepr)
            self.failed += 1
        self._closetestcase()

    def _opentestcase_collectfailure(self, report):
        node = report.collector
        d = {'time': '???'}
        names = [x.replace(".py", "") for x in node.listnames() if x != "()"]
        d['classname'] = ".".join(names[:-1])
        d['name'] = names[-1]
        attrs = ['%s="%s"' % item for item in sorted(d.items())]
        self.test_logs.append("\n<testcase %s>" % " ".join(attrs))

    def append_collect_failure(self, report):
        self._opentestcase_collectfailure(report)
        #msg = str(report.longrepr.reprtraceback.extraline)
        self.appendlog('<failure message="collection failure">%s</failure>', 
            report.longrepr)
        self._closetestcase()
        self.errors += 1

    def append_collect_skipped(self, report):
        self._opentestcase_collectfailure(report)
        #msg = str(report.longrepr.reprtraceback.extraline)
        self.appendlog('<skipped message="collection skipped">%s</skipped>',
            report.longrepr)
        self._closetestcase()
        self.skipped += 1

    def append_error(self, report):
        self._opentestcase(report)
        self.appendlog('<error message="test setup failure">%s</error>', 
            report.longrepr)
        self._closetestcase()
        self.errors += 1

    def append_skipped(self, report):
        self._opentestcase(report)
        if "xfail" in report.keywords:
            self.appendlog(
                '<skipped message="expected test failure">%s</skipped>', 
                report.keywords['xfail'])
        else:
            self.appendlog("<skipped/>")
        self._closetestcase()
        self.skipped += 1

    def pytest_runtest_logreport(self, report):
        if report.passed:
            self.append_pass(report)
        elif report.failed:
            if report.when != "call":
                self.append_error(report)
            else:
                self.append_failure(report)
        elif report.skipped:
            self.append_skipped(report)
        
    def pytest_runtest_call(self, item, __multicall__):
        start = time.time()
        try:
            return __multicall__.execute()
        finally:
            self._durations[item] = time.time() - start
    
    def pytest_collectreport(self, report):
        if not report.passed:
            if report.failed:
                self.append_collect_failure(report)
            else:
                self.append_collect_skipped(report)

    def pytest_internalerror(self, excrepr):
        self.errors += 1
        data = py.xml.escape(excrepr)
        self.test_logs.append(
            '\n<testcase classname="pytest" name="internal">'
            '    <error message="internal error">'
            '%s</error></testcase>' % data)

    def pytest_sessionstart(self, session):
        self.suite_start_time = time.time()

    def pytest_sessionfinish(self, session, exitstatus, __multicall__):
        if py.std.sys.version_info[0] < 3:
            logfile = py.std.codecs.open(self.logfile, 'w', encoding='utf-8')
        else:
            logfile = open(self.logfile, 'w', encoding='utf-8')
            
        suite_stop_time = time.time()
        suite_time_delta = suite_stop_time - self.suite_start_time
        numtests = self.passed + self.failed
        logfile.write('<?xml version="1.0" encoding="utf-8"?>')
        logfile.write('<testsuite ')
        logfile.write('name="" ')
        logfile.write('errors="%i" ' % self.errors)
        logfile.write('failures="%i" ' % self.failed)
        logfile.write('skips="%i" ' % self.skipped)
        logfile.write('tests="%i" ' % numtests)
        logfile.write('time="%.3f"' % suite_time_delta)
        logfile.write(' >')
        logfile.writelines(self.test_logs)
        logfile.write('</testsuite>')
        logfile.close()
        tw = session.config.pluginmanager.getplugin("terminalreporter")._tw
        tw.line()
        tw.sep("-", "generated xml file: %s" %(self.logfile))
