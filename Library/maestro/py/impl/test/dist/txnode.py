"""
    Manage setup, running and local representation of remote nodes/processes. 
"""
import py
from py.impl.test.dist.mypickle import PickleChannel

class TXNode(object):
    """ Represents a Test Execution environment in the controlling process. 
        - sets up a slave node through an execnet gateway 
        - manages sending of test-items and receival of results and events
        - creates events when the remote side crashes 
    """
    ENDMARK = -1

    def __init__(self, gateway, config, putevent, slaveready=None):
        self.config = config 
        self.putevent = putevent 
        self.gateway = gateway
        self.channel = install_slave(gateway, config)
        self._sendslaveready = slaveready
        self.channel.setcallback(self.callback, endmarker=self.ENDMARK)
        self._down = False

    def __repr__(self):
        id = self.gateway.id
        status = self._down and 'true' or 'false'
        return "<TXNode %r down=%s>" %(id, status)

    def notify(self, eventname, *args, **kwargs):
        assert not args
        self.putevent((eventname, args, kwargs))
      
    def callback(self, eventcall):
        """ this gets called for each object we receive from 
            the other side and if the channel closes. 

            Note that channel callbacks run in the receiver
            thread of execnet gateways - we need to 
            avoid raising exceptions or doing heavy work.
        """
        try:
            if eventcall == self.ENDMARK:
                err = self.channel._getremoteerror()
                if not self._down:
                    if not err:
                        err = "Not properly terminated"
                    self.notify("pytest_testnodedown", node=self, error=err)
                    self._down = True
                return
            eventname, args, kwargs = eventcall 
            if eventname == "slaveready":
                if self._sendslaveready:
                    self._sendslaveready(self)
                self.notify("pytest_testnodeready", node=self)
            elif eventname == "slavefinished":
                self._down = True
                self.notify("pytest_testnodedown", error=None, node=self)
            elif eventname == "pytest_runtest_logreport":
                rep = kwargs['report']
                rep.node = self
                self.notify("pytest_runtest_logreport", report=rep)
            else:
                self.notify(eventname, *args, **kwargs)
        except KeyboardInterrupt: 
            # should not land in receiver-thread
            raise 
        except:
            excinfo = py.code.ExceptionInfo()
            py.builtin.print_("!" * 20, excinfo)
            self.config.pluginmanager.notify_exception(excinfo)

    def send(self, item):
        assert item is not None
        self.channel.send(item)

    def sendlist(self, itemlist):
        self.channel.send(itemlist)

    def shutdown(self):
        self.channel.send(None)

# setting up slave code 
def install_slave(gateway, config):
    channel = gateway.remote_exec(source="""
        import os, sys 
        sys.path.insert(0, os.getcwd()) 
        from py.impl.test.dist.mypickle import PickleChannel
        from py.impl.test.dist.txnode import SlaveNode
        channel = PickleChannel(channel)
        slavenode = SlaveNode(channel)
        slavenode.run()
    """)
    channel = PickleChannel(channel)
    basetemp = None
    if gateway.spec.popen:
        popenbase = config.ensuretemp("popen")
        basetemp = py.path.local.make_numbered_dir(prefix="slave-", 
            keep=0, rootdir=popenbase)
        basetemp = str(basetemp)
    channel.send((config, basetemp))
    return channel

class SlaveNode(object):
    def __init__(self, channel):
        self.channel = channel

    def __repr__(self):
        return "<%s channel=%s>" %(self.__class__.__name__, self.channel)

    def sendevent(self, eventname, *args, **kwargs):
        self.channel.send((eventname, args, kwargs))

    def pytest_runtest_logreport(self, report):
        self.sendevent("pytest_runtest_logreport", report=report)

    def run(self):
        channel = self.channel
        self.config, basetemp = channel.receive()
        if basetemp:
            self.config.basetemp = py.path.local(basetemp)
        self.config.pluginmanager.do_configure(self.config)
        self.config.pluginmanager.register(self)
        self.runner = self.config.pluginmanager.getplugin("pytest_runner")
        self.sendevent("slaveready")
        try:
            while 1:
                task = channel.receive()
                if task is None: 
                    self.sendevent("slavefinished")
                    break
                if isinstance(task, list):
                    for item in task:
                        self.run_single(item=item)
                else:
                    self.run_single(item=task)
        except KeyboardInterrupt:
            raise
        except:
            er = py.code.ExceptionInfo().getrepr(funcargs=True, showlocals=True)
            self.sendevent("pytest_internalerror", excrepr=er)
            raise

    def run_single(self, item):
        call = self.runner.CallInfo(item._checkcollectable, when='setup')
        if call.excinfo:
            # likely it is not collectable here because of
            # platform/import-dependency induced skips 
            # we fake a setup-error report with the obtained exception
            # and do not care about capturing or non-runner hooks 
            rep = self.runner.pytest_runtest_makereport(item=item, call=call)
            self.pytest_runtest_logreport(rep)
            return
        item.config.hook.pytest_runtest_protocol(item=item) 
