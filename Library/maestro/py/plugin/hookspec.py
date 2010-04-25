"""
hook specifications for py.test plugins 
"""

# -------------------------------------------------------------------------
# Command line and configuration 
# -------------------------------------------------------------------------

def pytest_addoption(parser):
    """ called before commandline parsing.  """

def pytest_namespace():
    """ return dict of name->object which will get stored at py.test. namespace"""

def pytest_configure(config):
    """ called after command line options have been parsed. 
        and all plugins and initial conftest files been loaded. 
    """

def pytest_unconfigure(config):
    """ called before test process is exited.  """

# -------------------------------------------------------------------------
# collection hooks
# -------------------------------------------------------------------------

def pytest_collect_directory(path, parent):
    """ return Collection node or None for the given path. """

def pytest_collect_file(path, parent):
    """ return Collection node or None for the given path. """

def pytest_collectstart(collector):
    """ collector starts collecting. """

def pytest_collectreport(report):
    """ collector finished collecting. """

def pytest_deselected(items):
    """ called for test items deselected by keyword. """

def pytest_make_collect_report(collector):
    """ perform a collection and return a collection. """ 
pytest_make_collect_report.firstresult = True

# XXX rename to item_collected()?  meaning in distribution context? 
def pytest_itemstart(item, node=None):
    """ test item gets collected. """

# -------------------------------------------------------------------------
# Python test function related hooks
# -------------------------------------------------------------------------

def pytest_pycollect_makeitem(collector, name, obj):
    """ return custom item/collector for a python object in a module, or None.  """
pytest_pycollect_makeitem.firstresult = True

def pytest_pyfunc_call(pyfuncitem):
    """ perform function call to the with the given function arguments. """ 
pytest_pyfunc_call.firstresult = True

def pytest_generate_tests(metafunc):
    """ generate (multiple) parametrized calls to a test function."""

# -------------------------------------------------------------------------
# generic runtest related hooks 
# -------------------------------------------------------------------------

def pytest_runtest_protocol(item):
    """ implement fixture, run and report protocol. """
pytest_runtest_protocol.firstresult = True

def pytest_runtest_setup(item):
    """ called before pytest_runtest_call(). """ 

def pytest_runtest_call(item):
    """ execute test item. """ 

def pytest_runtest_teardown(item):
    """ called after pytest_runtest_call(). """ 

def pytest_runtest_makereport(item, call):
    """ make ItemTestReport for the given item and call outcome. """ 
pytest_runtest_makereport.firstresult = True

def pytest_runtest_logreport(report):
    """ process item test report. """ 

# special handling for final teardown - somewhat internal for now
def pytest__teardown_final(session):
    """ called before test session finishes. """
pytest__teardown_final.firstresult = True

def pytest__teardown_final_logerror(report):
    """ called if runtest_teardown_final failed. """ 

# -------------------------------------------------------------------------
# test session related hooks 
# -------------------------------------------------------------------------

def pytest_sessionstart(session):
    """ before session.main() is called. """

def pytest_sessionfinish(session, exitstatus):
    """ whole test run finishes. """

# -------------------------------------------------------------------------
# hooks for influencing reporting (invoked from pytest_terminal)
# -------------------------------------------------------------------------

def pytest_report_teststatus(report):
    """ return result-category, shortletter and verbose word for reporting."""
pytest_report_teststatus.firstresult = True

def pytest_terminal_summary(terminalreporter):
    """ add additional section in terminal summary reporting. """

def pytest_report_iteminfo(item):
    """ return (fspath, lineno, name) for the item.
        the information is used for result display and to sort tests
    """
pytest_report_iteminfo.firstresult = True

# -------------------------------------------------------------------------
# doctest hooks 
# -------------------------------------------------------------------------

def pytest_doctest_prepare_content(content):
    """ return processed content for a given doctest"""
pytest_doctest_prepare_content.firstresult = True

# -------------------------------------------------------------------------
# distributed testing 
# -------------------------------------------------------------------------

def pytest_gwmanage_newgateway(gateway, platinfo):
    """ called on new raw gateway creation. """ 

def pytest_gwmanage_rsyncstart(source, gateways):
    """ called before rsyncing a directory to remote gateways takes place. """

def pytest_gwmanage_rsyncfinish(source, gateways):
    """ called after rsyncing a directory to remote gateways takes place. """

def pytest_testnodeready(node):
    """ Test Node is ready to operate. """

def pytest_testnodedown(node, error):
    """ Test Node is down. """

def pytest_rescheduleitems(items):
    """ reschedule Items from a node that went down. """

def pytest_looponfailinfo(failreports, rootdirs):
    """ info for repeating failing tests. """


# -------------------------------------------------------------------------
# error handling and internal debugging hooks 
# -------------------------------------------------------------------------

def pytest_plugin_registered(plugin):
    """ a new py lib plugin got registered. """

def pytest_plugin_unregistered(plugin):
    """ a py lib plugin got unregistered. """

def pytest_internalerror(excrepr):
    """ called for internal errors. """

def pytest_keyboard_interrupt(excinfo):
    """ called for keyboard interrupt. """

def pytest_trace(category, msg):
    """ called for debug info. """ 
