
from pypy.rpython.ootypesystem import ootype
from pypy.objspace.flow.model import Constant, Variable
from pypy.rlib.objectmodel import we_are_translated
from pypy.rlib.debug import debug_start, debug_stop
from pypy.conftest import option
from pypy.tool.sourcetools import func_with_new_name

from pypy.jit.metainterp.resoperation import ResOperation, rop
from pypy.jit.metainterp.history import TreeLoop, Box, History, LoopToken
from pypy.jit.metainterp.history import AbstractFailDescr, BoxInt
from pypy.jit.metainterp.history import BoxPtr, BoxObj, BoxFloat, Const
from pypy.jit.metainterp import history
from pypy.jit.metainterp.specnode import NotSpecNode, more_general_specnodes
from pypy.jit.metainterp.typesystem import llhelper, oohelper
from pypy.jit.metainterp.optimizeutil import InvalidLoop

def giveup():
    from pypy.jit.metainterp.pyjitpl import SwitchToBlackhole
    from pypy.jit.metainterp.jitprof import ABORT_BRIDGE
    raise SwitchToBlackhole(ABORT_BRIDGE)

def show_loop(metainterp_sd, loop=None, error=None):
    # debugging
    if option.view or option.viewloops:
        if error:
            errmsg = error.__class__.__name__
            if str(error):
                errmsg += ': ' + str(error)
        else:
            errmsg = None
        if loop is None: # or type(loop) is TerminatingLoop:
            extraloops = []
        else:
            extraloops = [loop]
        metainterp_sd.stats.view(errmsg=errmsg, extraloops=extraloops)

def create_empty_loop(metainterp):
    name = metainterp.staticdata.stats.name_for_new_loop()
    return TreeLoop(name)

def make_loop_token(nb_args, jitdriver_sd):
    loop_token = LoopToken()
    loop_token.specnodes = [prebuiltNotSpecNode] * nb_args
    loop_token.outermost_jitdriver_sd = jitdriver_sd
    return loop_token

# ____________________________________________________________

def compile_new_loop(metainterp, old_loop_tokens, greenkey, start):
    """Try to compile a new loop by closing the current history back
    to the first operation.
    """    
    history = metainterp.history
    loop = create_empty_loop(metainterp)
    loop.greenkey = greenkey
    loop.inputargs = history.inputargs
    for box in loop.inputargs:
        assert isinstance(box, Box)
    if start > 0:
        ops = history.operations[start:]
    else:
        ops = history.operations
    # make a copy, because optimize_loop can mutate the ops and descrs
    loop.operations = [op.clone() for op in ops]
    metainterp_sd = metainterp.staticdata
    jitdriver_sd = metainterp.jitdriver_sd
    loop_token = make_loop_token(len(loop.inputargs), jitdriver_sd)
    loop.token = loop_token
    loop.operations[-1].descr = loop_token     # patch the target of the JUMP
    try:
        old_loop_token = jitdriver_sd.warmstate.optimize_loop(
            metainterp_sd, old_loop_tokens, loop)
    except InvalidLoop:
        return None
    if old_loop_token is not None:
        metainterp.staticdata.log("reusing old loop")
        return old_loop_token
    send_loop_to_backend(metainterp_sd, loop, "loop")
    insert_loop_token(old_loop_tokens, loop_token)
    return loop_token

def insert_loop_token(old_loop_tokens, loop_token):
    # Find where in old_loop_tokens we should insert this new loop_token.
    # The following algo means "as late as possible, but before another
    # loop token that would be more general and so completely mask off
    # the new loop_token".
    for i in range(len(old_loop_tokens)):
        if more_general_specnodes(old_loop_tokens[i].specnodes,
                                  loop_token.specnodes):
            old_loop_tokens.insert(i, loop_token)
            break
    else:
        old_loop_tokens.append(loop_token)

def send_loop_to_backend(metainterp_sd, loop, type):
    globaldata = metainterp_sd.globaldata
    loop_token = loop.token
    loop_token.number = n = globaldata.loopnumbering
    globaldata.loopnumbering += 1

    metainterp_sd.logger_ops.log_loop(loop.inputargs, loop.operations, n, type)
    if not we_are_translated():
        show_loop(metainterp_sd, loop)
        loop.check_consistency()
    metainterp_sd.profiler.start_backend()
    debug_start("jit-backend")
    try:
        metainterp_sd.cpu.compile_loop(loop.inputargs, loop.operations,
                                       loop.token)
    finally:
        debug_stop("jit-backend")
    metainterp_sd.profiler.end_backend()
    metainterp_sd.stats.add_new_loop(loop)
    if not we_are_translated():
        if type != "entry bridge":
            metainterp_sd.stats.compiled()
        else:
            loop._ignore_during_counting = True
    metainterp_sd.log("compiled new " + type)

def send_bridge_to_backend(metainterp_sd, faildescr, inputargs, operations):
    n = metainterp_sd.cpu.get_fail_descr_number(faildescr)
    metainterp_sd.logger_ops.log_bridge(inputargs, operations, n)
    if not we_are_translated():
        show_loop(metainterp_sd)
        TreeLoop.check_consistency_of(inputargs, operations)
        pass
    metainterp_sd.profiler.start_backend()
    debug_start("jit-backend")
    try:
        metainterp_sd.cpu.compile_bridge(faildescr, inputargs, operations)
    finally:
        debug_stop("jit-backend")
    metainterp_sd.profiler.end_backend()
    if not we_are_translated():
        metainterp_sd.stats.compiled()
    metainterp_sd.log("compiled new bridge")            

# ____________________________________________________________

class _DoneWithThisFrameDescr(AbstractFailDescr):
    pass

class DoneWithThisFrameDescrVoid(_DoneWithThisFrameDescr):
    def handle_fail(self, metainterp_sd, jitdriver_sd):
        assert jitdriver_sd.result_type == history.VOID
        raise metainterp_sd.DoneWithThisFrameVoid()

class DoneWithThisFrameDescrInt(_DoneWithThisFrameDescr):
    def handle_fail(self, metainterp_sd, jitdriver_sd):
        assert jitdriver_sd.result_type == history.INT
        result = metainterp_sd.cpu.get_latest_value_int(0)
        raise metainterp_sd.DoneWithThisFrameInt(result)

class DoneWithThisFrameDescrRef(_DoneWithThisFrameDescr):
    def handle_fail(self, metainterp_sd, jitdriver_sd):
        assert jitdriver_sd.result_type == history.REF
        cpu = metainterp_sd.cpu
        result = cpu.get_latest_value_ref(0)
        cpu.clear_latest_values(1)
        raise metainterp_sd.DoneWithThisFrameRef(cpu, result)

class DoneWithThisFrameDescrFloat(_DoneWithThisFrameDescr):
    def handle_fail(self, metainterp_sd, jitdriver_sd):
        assert jitdriver_sd.result_type == history.FLOAT
        result = metainterp_sd.cpu.get_latest_value_float(0)
        raise metainterp_sd.DoneWithThisFrameFloat(result)

class ExitFrameWithExceptionDescrRef(_DoneWithThisFrameDescr):
    def handle_fail(self, metainterp_sd, jitdriver_sd):
        cpu = metainterp_sd.cpu
        value = cpu.get_latest_value_ref(0)
        cpu.clear_latest_values(1)
        raise metainterp_sd.ExitFrameWithExceptionRef(cpu, value)


prebuiltNotSpecNode = NotSpecNode()

class TerminatingLoopToken(LoopToken):
    terminating = True
    
    def __init__(self, nargs, finishdescr):
        self.specnodes = [prebuiltNotSpecNode]*nargs
        self.finishdescr = finishdescr

def make_done_loop_tokens():
    done_with_this_frame_descr_void = DoneWithThisFrameDescrVoid()
    done_with_this_frame_descr_int = DoneWithThisFrameDescrInt()
    done_with_this_frame_descr_ref = DoneWithThisFrameDescrRef()
    done_with_this_frame_descr_float = DoneWithThisFrameDescrFloat()
    exit_frame_with_exception_descr_ref = ExitFrameWithExceptionDescrRef()

    # pseudo loop tokens to make the life of optimize.py easier
    return {'loop_tokens_done_with_this_frame_int': [
                TerminatingLoopToken(1, done_with_this_frame_descr_int)
                ],
            'loop_tokens_done_with_this_frame_ref': [
                TerminatingLoopToken(1, done_with_this_frame_descr_ref)
                ],
            'loop_tokens_done_with_this_frame_float': [
                TerminatingLoopToken(1, done_with_this_frame_descr_float)
                ],
            'loop_tokens_done_with_this_frame_void': [
                TerminatingLoopToken(0, done_with_this_frame_descr_void)
                ],
            'loop_tokens_exit_frame_with_exception_ref': [
                TerminatingLoopToken(1, exit_frame_with_exception_descr_ref)
                ],
            }

class ResumeDescr(AbstractFailDescr):
    def __init__(self, original_greenkey):
        self.original_greenkey = original_greenkey

class ResumeGuardDescr(ResumeDescr):
    _counter = 0        # if < 0, there is one counter per value;
    _counters = None    # they get stored in _counters then.

    # this class also gets the following attributes stored by resume.py code
    rd_snapshot = None
    rd_frame_info_list = None
    rd_numb = None
    rd_consts = None
    rd_virtuals = None
    rd_pendingfields = None

    CNT_INT   = -0x20000000
    CNT_REF   = -0x40000000
    CNT_FLOAT = -0x60000000
    CNT_MASK  =  0x1FFFFFFF

    def __init__(self, metainterp_sd, original_greenkey):
        ResumeDescr.__init__(self, original_greenkey)
        self.metainterp_sd = metainterp_sd

    def store_final_boxes(self, guard_op, boxes):
        guard_op.fail_args = boxes
        self.guard_opnum = guard_op.opnum

    def make_a_counter_per_value(self, guard_value_op):
        assert guard_value_op.opnum == rop.GUARD_VALUE
        box = guard_value_op.args[0]
        try:
            i = guard_value_op.fail_args.index(box)
        except ValueError:
            return     # xxx probably very rare
        else:
            if box.type == history.INT:
                cnt = self.CNT_INT
            elif box.type == history.REF:
                cnt = self.CNT_REF
            elif box.type == history.FLOAT:
                cnt = self.CNT_FLOAT
            else:
                assert 0, box.type
            # we build the following value for _counter, which is always
            # a negative value
            self._counter = cnt | i

    def handle_fail(self, metainterp_sd, jitdriver_sd):
        if self.must_compile(metainterp_sd, jitdriver_sd):
            return self._trace_and_compile_from_bridge(metainterp_sd,
                                                       jitdriver_sd)
        else:
            from pypy.jit.metainterp.blackhole import resume_in_blackhole
            resume_in_blackhole(metainterp_sd, jitdriver_sd, self)
            assert 0, "unreachable"

    def _trace_and_compile_from_bridge(self, metainterp_sd, jitdriver_sd):
        # 'jitdriver_sd' corresponds to the outermost one, i.e. the one
        # of the jit_merge_point where we started the loop, even if the
        # loop itself may contain temporarily recursion into other
        # jitdrivers.
        from pypy.jit.metainterp.pyjitpl import MetaInterp
        metainterp = MetaInterp(metainterp_sd, jitdriver_sd)
        return metainterp.handle_guard_failure(self)
    _trace_and_compile_from_bridge._dont_inline_ = True

    def must_compile(self, metainterp_sd, jitdriver_sd):
        trace_eagerness = jitdriver_sd.warmstate.trace_eagerness
        if self._counter >= 0:
            self._counter += 1
            return self._counter >= trace_eagerness
        else:
            index = self._counter & self.CNT_MASK
            typetag = self._counter & ~ self.CNT_MASK
            counters = self._counters
            if typetag == self.CNT_INT:
                intvalue = metainterp_sd.cpu.get_latest_value_int(index)
                if counters is None:
                    self._counters = counters = ResumeGuardCountersInt()
                else:
                    assert isinstance(counters, ResumeGuardCountersInt)
                counter = counters.see_int(intvalue)
            elif typetag == self.CNT_REF:
                refvalue = metainterp_sd.cpu.get_latest_value_ref(index)
                if counters is None:
                    self._counters = counters = ResumeGuardCountersRef()
                else:
                    assert isinstance(counters, ResumeGuardCountersRef)
                counter = counters.see_ref(refvalue)
            elif typetag == self.CNT_FLOAT:
                floatvalue = metainterp_sd.cpu.get_latest_value_float(index)
                if counters is None:
                    self._counters = counters = ResumeGuardCountersFloat()
                else:
                    assert isinstance(counters, ResumeGuardCountersFloat)
                counter = counters.see_float(floatvalue)
            else:
                assert 0, typetag
            return counter >= trace_eagerness

    def reset_counter_from_failure(self):
        if self._counter >= 0:
            self._counter = 0
        self._counters = None

    def compile_and_attach(self, metainterp, new_loop):
        # We managed to create a bridge.  Attach the new operations
        # to the corrsponding guard_op and compile from there
        inputargs = metainterp.history.inputargs
        if not we_are_translated():
            self._debug_suboperations = new_loop.operations
        send_bridge_to_backend(metainterp.staticdata, self, inputargs,
                               new_loop.operations)

    def copy_all_attrbutes_into(self, res):
        # XXX a bit ugly to have to list them all here
        res.rd_snapshot = self.rd_snapshot
        res.rd_frame_info_list = self.rd_frame_info_list
        res.rd_numb = self.rd_numb
        res.rd_consts = self.rd_consts
        res.rd_virtuals = self.rd_virtuals
        res.rd_pendingfields = self.rd_pendingfields

    def _clone_if_mutable(self):
        res = ResumeGuardDescr(self.metainterp_sd, self.original_greenkey)
        self.copy_all_attrbutes_into(res)
        return res

class ResumeGuardForcedDescr(ResumeGuardDescr):

    def __init__(self, metainterp_sd, original_greenkey, jitdriver_sd):
        ResumeGuardDescr.__init__(self, metainterp_sd, original_greenkey)
        self.jitdriver_sd = jitdriver_sd

    def handle_fail(self, metainterp_sd, jitdriver_sd):
        # Failures of a GUARD_NOT_FORCED are never compiled, but
        # always just blackholed.  First fish for the data saved when
        # the virtualrefs and virtualizable have been forced by
        # handle_async_forcing() just a moment ago.
        from pypy.jit.metainterp.blackhole import resume_in_blackhole
        token = metainterp_sd.cpu.get_latest_force_token()
        all_virtuals = self.fetch_data(token)
        if all_virtuals is None:
            all_virtuals = []
        assert jitdriver_sd is self.jitdriver_sd
        resume_in_blackhole(metainterp_sd, jitdriver_sd, self, all_virtuals)
        assert 0, "unreachable"

    @staticmethod
    def force_now(cpu, token):
        # Called during a residual call from the assembler, if the code
        # actually needs to force one of the virtualrefs or the virtualizable.
        # Implemented by forcing *all* virtualrefs and the virtualizable.
        faildescr = cpu.force(token)
        assert isinstance(faildescr, ResumeGuardForcedDescr)
        faildescr.handle_async_forcing(token)

    def handle_async_forcing(self, force_token):
        from pypy.jit.metainterp.resume import force_from_resumedata
        metainterp_sd = self.metainterp_sd
        vinfo = self.jitdriver_sd.virtualizable_info
        all_virtuals = force_from_resumedata(metainterp_sd, self, vinfo)
        # The virtualizable data was stored on the real virtualizable above.
        # Handle all_virtuals: keep them for later blackholing from the
        # future failure of the GUARD_NOT_FORCED
        self.save_data(force_token, all_virtuals)

    def save_data(self, key, value):
        globaldata = self.metainterp_sd.globaldata
        if we_are_translated():
            assert key not in globaldata.resume_virtuals
            globaldata.resume_virtuals[key] = value
        else:
            rv = globaldata.resume_virtuals_not_translated
            for key1, value1 in rv:
                assert key1 != key
            rv.append((key, value))

    def fetch_data(self, key):
        globaldata = self.metainterp_sd.globaldata
        if we_are_translated():
            assert key in globaldata.resume_virtuals
            data = globaldata.resume_virtuals[key]
            del globaldata.resume_virtuals[key]
        else:
            rv = globaldata.resume_virtuals_not_translated
            for i in range(len(rv)):
                if rv[i][0] == key:
                    data = rv[i][1]
                    del rv[i]
                    break
            else:
                assert 0, "not found: %r" % (key,)
        return data

    def _clone_if_mutable(self):
        res = ResumeGuardForcedDescr(self.metainterp_sd,
                                     self.original_greenkey,
                                     self.jitdriver_sd)
        self.copy_all_attrbutes_into(res)
        return res


class AbstractResumeGuardCounters(object):
    # Completely custom algorithm for now: keep 5 pairs (value, counter),
    # and when we need more, we discard the middle pair (middle in the
    # current value of the counter).  That way, we tend to keep the
    # values with a high counter, but also we avoid always throwing away
    # the most recently added value.  **THIS ALGO MUST GO AWAY AT SOME POINT**
    pass

def _see(self, newvalue):
    # find and update an existing counter
    unused = -1
    for i in range(5):
        cnt = self.counters[i]
        if cnt:
            if self.values[i] == newvalue:
                cnt += 1
                self.counters[i] = cnt
                return cnt
        else:
            unused = i
    # not found.  Use a previously unused entry, if there is one
    if unused >= 0:
        self.counters[unused] = 1
        self.values[unused] = newvalue
        return 1
    # no unused entry.  Overwrite the middle one.  Computed with indices
    # a, b, c meaning the highest, second highest, and third highest
    # entries.
    a = 0
    b = c = -1
    for i in range(1, 5):
        if self.counters[i] > self.counters[a]:
            c = b; b = a; a = i
        elif b < 0 or self.counters[i] > self.counters[b]:
            c = b; b = i
        elif c < 0 or self.counters[i] > self.counters[c]:
            c = i
    self.counters[c] = 1
    self.values[c] = newvalue
    return 1

class ResumeGuardCountersInt(AbstractResumeGuardCounters):
    def __init__(self):
        self.counters = [0] * 5
        self.values = [0] * 5
    see_int = func_with_new_name(_see, 'see_int')

class ResumeGuardCountersRef(AbstractResumeGuardCounters):
    def __init__(self):
        self.counters = [0] * 5
        self.values = [history.ConstPtr.value] * 5
    see_ref = func_with_new_name(_see, 'see_ref')

class ResumeGuardCountersFloat(AbstractResumeGuardCounters):
    def __init__(self):
        self.counters = [0] * 5
        self.values = [0.0] * 5
    see_float = func_with_new_name(_see, 'see_float')


class ResumeFromInterpDescr(ResumeDescr):
    def __init__(self, original_greenkey, redkey):
        ResumeDescr.__init__(self, original_greenkey)
        self.redkey = redkey

    def compile_and_attach(self, metainterp, new_loop):
        # We managed to create a bridge going from the interpreter
        # to previously-compiled code.  We keep 'new_loop', which is not
        # a loop at all but ends in a jump to the target loop.  It starts
        # with completely unoptimized arguments, as in the interpreter.
        metainterp_sd = metainterp.staticdata
        jitdriver_sd = metainterp.jitdriver_sd
        metainterp.history.inputargs = self.redkey
        new_loop_token = make_loop_token(len(self.redkey), jitdriver_sd)
        new_loop.greenkey = self.original_greenkey
        new_loop.inputargs = self.redkey
        new_loop.token = new_loop_token
        send_loop_to_backend(metainterp_sd, new_loop, "entry bridge")
        # send the new_loop to warmspot.py, to be called directly the next time
        jitdriver_sd.warmstate.attach_unoptimized_bridge_from_interp(
            self.original_greenkey,
            new_loop_token)
        # store the new loop in compiled_merge_points too
        old_loop_tokens = metainterp.get_compiled_merge_points(
            self.original_greenkey)
        # it always goes at the end of the list, as it is the most
        # general loop token
        old_loop_tokens.append(new_loop_token)

    def reset_counter_from_failure(self):
        pass


def compile_new_bridge(metainterp, old_loop_tokens, resumekey):
    """Try to compile a new bridge leading from the beginning of the history
    to some existing place.
    """    
    # The history contains new operations to attach as the code for the
    # failure of 'resumekey.guard_op'.
    #
    # Attempt to use optimize_bridge().  This may return None in case
    # it does not work -- i.e. none of the existing old_loop_tokens match.
    new_loop = create_empty_loop(metainterp)
    new_loop.inputargs = metainterp.history.inputargs
    # clone ops, as optimize_bridge can mutate the ops
    new_loop.operations = [op.clone() for op in metainterp.history.operations]
    metainterp_sd = metainterp.staticdata
    state = metainterp.jitdriver_sd.warmstate
    try:
        target_loop_token = state.optimize_bridge(metainterp_sd,
                                                  old_loop_tokens,
                                                  new_loop)
    except InvalidLoop:
        # XXX I am fairly convinced that optimize_bridge cannot actually raise
        # InvalidLoop
        return None
    # Did it work?
    if target_loop_token is not None:
        # Yes, we managed to create a bridge.  Dispatch to resumekey to
        # know exactly what we must do (ResumeGuardDescr/ResumeFromInterpDescr)
        prepare_last_operation(new_loop, target_loop_token)
        resumekey.compile_and_attach(metainterp, new_loop)
    return target_loop_token

def prepare_last_operation(new_loop, target_loop_token):
    op = new_loop.operations[-1]
    if not isinstance(target_loop_token, TerminatingLoopToken):
        # normal case
        op.descr = target_loop_token     # patch the jump target
    else:
        # The target_loop_token is a pseudo loop token,
        # e.g. loop_tokens_done_with_this_frame_void[0]
        # Replace the operation with the real operation we want, i.e. a FINISH
        descr = target_loop_token.finishdescr
        new_op = ResOperation(rop.FINISH, op.args, None, descr=descr)
        new_loop.operations[-1] = new_op
