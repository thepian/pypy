import sys, py
from pypy.rpython.lltypesystem import lltype, llmemory, rclass, rstr
from pypy.rpython.ootypesystem import ootype
from pypy.rpython.annlowlevel import llhelper, MixLevelHelperAnnotator,\
     cast_base_ptr_to_instance, hlstr
from pypy.annotation import model as annmodel
from pypy.rpython.llinterp import LLException
from pypy.rpython.test.test_llinterp import get_interpreter, clear_tcache
from pypy.objspace.flow.model import SpaceOperation, Variable, Constant
from pypy.objspace.flow.model import checkgraph, Link, copygraph
from pypy.rlib.objectmodel import we_are_translated
from pypy.rlib.unroll import unrolling_iterable
from pypy.rlib.rarithmetic import r_uint, intmask
from pypy.rlib.debug import debug_print, fatalerror
from pypy.rpython.lltypesystem.lloperation import llop
from pypy.translator.simplify import get_funcobj, get_functype
from pypy.translator.unsimplify import call_final_function

from pypy.jit.metainterp import history, pyjitpl, gc
from pypy.jit.metainterp.pyjitpl import MetaInterpStaticData, MetaInterp
from pypy.jit.metainterp.typesystem import LLTypeHelper, OOTypeHelper
from pypy.jit.metainterp.jitprof import Profiler, EmptyProfiler
from pypy.jit.metainterp.jitexc import JitException
from pypy.jit.metainterp.jitdriver import JitDriverStaticData
from pypy.jit.codewriter import support, codewriter
from pypy.jit.codewriter.policy import JitPolicy
from pypy.rlib.jit import DEBUG_STEPS, DEBUG_DETAILED, DEBUG_OFF, DEBUG_PROFILE

# ____________________________________________________________
# Bootstrapping

def apply_jit(translator, backend_name="auto", debug_level=DEBUG_STEPS,
              inline=False,
              **kwds):
    if 'CPUClass' not in kwds:
        from pypy.jit.backend.detect_cpu import getcpuclass
        kwds['CPUClass'] = getcpuclass(backend_name)
    if debug_level > DEBUG_OFF:
        ProfilerClass = Profiler
    else:
        ProfilerClass = EmptyProfiler
    warmrunnerdesc = WarmRunnerDesc(translator,
                                    translate_support_code=True,
                                    listops=True,
                                    no_stats = True,
                                    ProfilerClass = ProfilerClass,
                                    **kwds)
    for jd in warmrunnerdesc.jitdrivers_sd:
        jd.warmstate.set_param_inlining(inline)
        jd.warmstate.set_param_debug(debug_level)
    warmrunnerdesc.finish()
    translator.warmrunnerdesc = warmrunnerdesc    # for later debugging

def ll_meta_interp(function, args, backendopt=False, type_system='lltype',
                   listcomp=False, **kwds):
    if listcomp:
        extraconfigopts = {'translation.list_comprehension_operations': True}
    else:
        extraconfigopts = {}
    interp, graph = get_interpreter(function, args,
                                    backendopt=False,  # will be done below
                                    type_system=type_system,
                                    **extraconfigopts)
    clear_tcache()
    return jittify_and_run(interp, graph, args, backendopt=backendopt, **kwds)

def jittify_and_run(interp, graph, args, repeat=1,
                    backendopt=False, trace_limit=sys.maxint,
                    debug_level=DEBUG_STEPS, inline=False, **kwds):
    translator = interp.typer.annotator.translator
    translator.config.translation.gc = "boehm"
    translator.config.translation.list_comprehension_operations = True
    warmrunnerdesc = WarmRunnerDesc(translator, backendopt=backendopt, **kwds)
    for jd in warmrunnerdesc.jitdrivers_sd:
        jd.warmstate.set_param_threshold(3)          # for tests
        jd.warmstate.set_param_trace_eagerness(2)    # for tests
        jd.warmstate.set_param_trace_limit(trace_limit)
        jd.warmstate.set_param_inlining(inline)
        jd.warmstate.set_param_debug(debug_level)
    warmrunnerdesc.finish()
    res = interp.eval_graph(graph, args)
    if not kwds.get('translate_support_code', False):
        warmrunnerdesc.metainterp_sd.profiler.finish()
        warmrunnerdesc.metainterp_sd.cpu.finish_once()
    print '~~~ return value:', res
    while repeat > 1:
        print '~' * 79
        res1 = interp.eval_graph(graph, args)
        if isinstance(res, int):
            assert res1 == res
        repeat -= 1
    return res

def rpython_ll_meta_interp(function, args, backendopt=True,
                           loops='not used right now', **kwds):
    return ll_meta_interp(function, args, backendopt=backendopt,
                          translate_support_code=True, **kwds)

def _find_jit_marker(graphs, marker_name):
    results = []
    for graph in graphs:
        for block in graph.iterblocks():
            for i in range(len(block.operations)):
                op = block.operations[i]
                if (op.opname == 'jit_marker' and
                    op.args[0].value == marker_name):
                    results.append((graph, block, i))
    return results

def find_can_enter_jit(graphs):
    results = _find_jit_marker(graphs, 'can_enter_jit')
    if not results:
        raise Exception("no can_enter_jit found!")
    return results

def find_jit_merge_points(graphs):
    results = _find_jit_marker(graphs, 'jit_merge_point')
    if not results:
        raise Exception("no jit_merge_point found!")
    return results

def find_set_param(graphs):
    return _find_jit_marker(graphs, 'set_param')

def get_stats():
    return pyjitpl._warmrunnerdesc.stats

def get_translator():
    return pyjitpl._warmrunnerdesc.translator

def debug_checks():
    stats = get_stats()
    stats.maybe_view()
    stats.check_consistency()

class ContinueRunningNormallyBase(JitException):
    pass

class CannotInlineCanEnterJit(JitException):
    pass

# ____________________________________________________________

class WarmRunnerDesc(object):

    def __init__(self, translator, policy=None, backendopt=True, CPUClass=None,
                 optimizer=None, ProfilerClass=EmptyProfiler, **kwds):
        pyjitpl._warmrunnerdesc = self   # this is a global for debugging only!
        self.set_translator(translator)
        self.build_cpu(CPUClass, **kwds)
        self.find_portals()
        self.codewriter = codewriter.CodeWriter(self.cpu, self.jitdrivers_sd)
        if policy is None:
            policy = JitPolicy()
        policy.set_supports_floats(self.cpu.supports_floats)
        graphs = self.codewriter.find_all_graphs(policy)
        policy.dump_unsafe_loops()
        self.check_access_directly_sanity(graphs)
        if backendopt:
            self.prejit_optimizations(policy, graphs)

        self.build_meta_interp(ProfilerClass)
        self.make_args_specifications()
        #
        from pypy.jit.metainterp.virtualref import VirtualRefInfo
        vrefinfo = VirtualRefInfo(self)
        self.codewriter.setup_vrefinfo(vrefinfo)
        #
        self.make_virtualizable_infos()
        self.make_exception_classes()
        self.make_driverhook_graphs()
        self.make_enter_functions()
        self.rewrite_jit_merge_points(policy)

        verbose = not self.cpu.translate_support_code
        self.codewriter.make_jitcodes(verbose=verbose)
        self.rewrite_can_enter_jits()
        self.rewrite_set_param()
        self.rewrite_force_virtual(vrefinfo)
        self.add_finish()
        self.metainterp_sd.finish_setup(self.codewriter, optimizer=optimizer)

    def finish(self):
        vinfos = set([jd.virtualizable_info for jd in self.jitdrivers_sd])
        for vinfo in vinfos:
            if vinfo is not None:
                vinfo.finish()
        if self.cpu.translate_support_code:
            self.annhelper.finish()

    def _freeze_(self):
        return True

    def set_translator(self, translator):
        self.translator = translator
        self.rtyper = translator.rtyper
        self.gcdescr = gc.get_description(translator.config)

    def find_portals(self):
        self.jitdrivers_sd = []
        graphs = self.translator.graphs
        for jit_merge_point_pos in find_jit_merge_points(graphs):
            self.split_graph_and_record_jitdriver(*jit_merge_point_pos)
        #
        assert (len(set([jd.jitdriver for jd in self.jitdrivers_sd])) ==
                len(self.jitdrivers_sd)), \
                "there are multiple jit_merge_points with the same jitdriver"

    def split_graph_and_record_jitdriver(self, graph, block, pos):
        jd = JitDriverStaticData()
        jd._jit_merge_point_pos = (graph, block, pos)
        op = block.operations[pos]
        args = op.args[2:]
        s_binding = self.translator.annotator.binding
        jd._portal_args_s = [s_binding(v) for v in args]
        graph = copygraph(graph)
        graph.startblock.isstartblock = False
        [jmpp] = find_jit_merge_points([graph])
        graph.startblock = support.split_before_jit_merge_point(*jmpp)
        graph.startblock.isstartblock = True
        # a crash in the following checkgraph() means that you forgot
        # to list some variable in greens=[] or reds=[] in JitDriver.
        checkgraph(graph)
        for v in graph.getargs():
            assert isinstance(v, Variable)
        assert len(dict.fromkeys(graph.getargs())) == len(graph.getargs())
        self.translator.graphs.append(graph)
        jd.portal_graph = graph
        # it's a bit unbelievable to have a portal without func
        assert hasattr(graph, "func")
        graph.func._dont_inline_ = True
        graph.func._jit_unroll_safe_ = True
        jd.jitdriver = block.operations[pos].args[1].value
        jd.portal_runner_ptr = "<not set so far>"
        jd.result_type = history.getkind(jd.portal_graph.getreturnvar()
                                         .concretetype)[0]
        self.jitdrivers_sd.append(jd)

    def check_access_directly_sanity(self, graphs):
        from pypy.translator.backendopt.inline import collect_called_graphs
        jit_graphs = set(graphs)
        for graph in collect_called_graphs(self.translator.entry_point_graph,
                                           self.translator):
            if graph in jit_graphs:
                continue
            assert not getattr(graph, 'access_directly', False)

    def prejit_optimizations(self, policy, graphs):
        from pypy.translator.backendopt.all import backend_optimizations
        backend_optimizations(self.translator,
                              graphs=graphs,
                              merge_if_blocks=True,
                              constfold=True,
                              raisingop2direct_call=False,
                              remove_asserts=True,
                              really_remove_asserts=True)

    def build_cpu(self, CPUClass, translate_support_code=False,
                  no_stats=False, **kwds):
        assert CPUClass is not None
        self.opt = history.Options(**kwds)
        if no_stats:
            stats = history.NoStats()
        else:
            stats = history.Stats()
        self.stats = stats 
        if translate_support_code:
            self.annhelper = MixLevelHelperAnnotator(self.translator.rtyper)
            annhelper = self.annhelper
        else:
            annhelper = None
        cpu = CPUClass(self.translator.rtyper, self.stats, self.opt,
                       translate_support_code, gcdescr=self.gcdescr)
        self.cpu = cpu

    def build_meta_interp(self, ProfilerClass):
        self.metainterp_sd = MetaInterpStaticData(self.cpu,
                                                  self.opt,
                                                  ProfilerClass=ProfilerClass,
                                                  warmrunnerdesc=self)

    def make_virtualizable_infos(self):
        vinfos = {}
        for jd in self.jitdrivers_sd:
            if not jd.jitdriver.virtualizables:
                jd.virtualizable_info = None
                jd.index_of_virtualizable = -1
                continue
            #
            jitdriver = jd.jitdriver
            assert len(jitdriver.virtualizables) == 1    # for now
            [vname] = jitdriver.virtualizables
            # XXX skip the Voids here too
            jd.index_of_virtualizable = jitdriver.reds.index(vname)
            #
            index = jd.num_green_args + jd.index_of_virtualizable
            VTYPEPTR = jd._JIT_ENTER_FUNCTYPE.ARGS[index]
            if VTYPEPTR not in vinfos:
                from pypy.jit.metainterp.virtualizable import VirtualizableInfo
                vinfos[VTYPEPTR] = VirtualizableInfo(self, VTYPEPTR)
            jd.virtualizable_info = vinfos[VTYPEPTR]

    def make_exception_classes(self):

        class DoneWithThisFrameVoid(JitException):
            def __str__(self):
                return 'DoneWithThisFrameVoid()'

        class DoneWithThisFrameInt(JitException):
            def __init__(self, result):
                assert lltype.typeOf(result) is lltype.Signed
                self.result = result
            def __str__(self):
                return 'DoneWithThisFrameInt(%s)' % (self.result,)

        class DoneWithThisFrameRef(JitException):
            def __init__(self, cpu, result):
                assert lltype.typeOf(result) == cpu.ts.BASETYPE
                self.result = result
            def __str__(self):
                return 'DoneWithThisFrameRef(%s)' % (self.result,)

        class DoneWithThisFrameFloat(JitException):
            def __init__(self, result):
                assert lltype.typeOf(result) is lltype.Float
                self.result = result
            def __str__(self):
                return 'DoneWithThisFrameFloat(%s)' % (self.result,)

        class ExitFrameWithExceptionRef(JitException):
            def __init__(self, cpu, value):
                assert lltype.typeOf(value) == cpu.ts.BASETYPE
                self.value = value
            def __str__(self):
                return 'ExitFrameWithExceptionRef(%s)' % (self.value,)

        class ContinueRunningNormally(ContinueRunningNormallyBase):
            def __init__(self, gi, gr, gf, ri, rr, rf):
                # the six arguments are: lists of green ints, greens refs,
                # green floats, red ints, red refs, and red floats.
                self.green_int = gi
                self.green_ref = gr
                self.green_float = gf
                self.red_int = ri
                self.red_ref = rr
                self.red_float = rf
            def __str__(self):
                return 'ContinueRunningNormally(%s, %s, %s, %s, %s, %s)' % (
                    self.green_int, self.green_ref, self.green_float,
                    self.red_int, self.red_ref, self.red_float)

        # XXX there is no point any more to not just have the exceptions
        # as globals
        self.DoneWithThisFrameVoid = DoneWithThisFrameVoid
        self.DoneWithThisFrameInt = DoneWithThisFrameInt
        self.DoneWithThisFrameRef = DoneWithThisFrameRef
        self.DoneWithThisFrameFloat = DoneWithThisFrameFloat
        self.ExitFrameWithExceptionRef = ExitFrameWithExceptionRef
        self.ContinueRunningNormally = ContinueRunningNormally
        self.metainterp_sd.DoneWithThisFrameVoid = DoneWithThisFrameVoid
        self.metainterp_sd.DoneWithThisFrameInt = DoneWithThisFrameInt
        self.metainterp_sd.DoneWithThisFrameRef = DoneWithThisFrameRef
        self.metainterp_sd.DoneWithThisFrameFloat = DoneWithThisFrameFloat
        self.metainterp_sd.ExitFrameWithExceptionRef = ExitFrameWithExceptionRef
        self.metainterp_sd.ContinueRunningNormally = ContinueRunningNormally

    def make_enter_functions(self):
        for jd in self.jitdrivers_sd:
            self.make_enter_function(jd)

    def make_enter_function(self, jd):
        from pypy.jit.metainterp.warmstate import WarmEnterState
        state = WarmEnterState(self, jd)
        maybe_compile_and_run = state.make_entry_point()
        jd.warmstate = state

        def crash_in_jit(e):
            if not we_are_translated():
                print "~~~ Crash in JIT!"
                print '~~~ %s: %s' % (e.__class__, e)
                if sys.stdout == sys.__stdout__:
                    import pdb; pdb.post_mortem(sys.exc_info()[2])
                raise
            fatalerror('~~~ Crash in JIT! %s' % (e,), traceback=True)
        crash_in_jit._dont_inline_ = True

        if self.translator.rtyper.type_system.name == 'lltypesystem':
            def maybe_enter_jit(*args):
                try:
                    maybe_compile_and_run(*args)
                except JitException:
                    raise     # go through
                except Exception, e:
                    crash_in_jit(e)
            maybe_enter_jit._always_inline_ = True
        else:
            def maybe_enter_jit(*args):
                maybe_compile_and_run(*args)
            maybe_enter_jit._always_inline_ = True
        jd._maybe_enter_jit_fn = maybe_enter_jit

        can_inline = state.can_inline_greenargs
        num_green_args = jd.num_green_args
        def maybe_enter_from_start(*args):
            if can_inline is not None and not can_inline(*args[:num_green_args]):
                maybe_compile_and_run(*args)
        maybe_enter_from_start._always_inline_ = True
        jd._maybe_enter_from_start_fn = maybe_enter_from_start

    def make_driverhook_graphs(self):
        from pypy.rlib.jit import BaseJitCell
        bk = self.rtyper.annotator.bookkeeper
        classdef = bk.getuniqueclassdef(BaseJitCell)
        s_BaseJitCell_or_None = annmodel.SomeInstance(classdef,
                                                      can_be_None=True)
        s_BaseJitCell_not_None = annmodel.SomeInstance(classdef)
        s_Str = annmodel.SomeString()
        #
        annhelper = MixLevelHelperAnnotator(self.translator.rtyper)
        for jd in self.jitdrivers_sd:
            jd._set_jitcell_at_ptr = self._make_hook_graph(jd,
                annhelper, jd.jitdriver.set_jitcell_at, annmodel.s_None,
                s_BaseJitCell_not_None)
            jd._get_jitcell_at_ptr = self._make_hook_graph(jd,
                annhelper, jd.jitdriver.get_jitcell_at, s_BaseJitCell_or_None)
            jd._can_inline_ptr = self._make_hook_graph(jd,
                annhelper, jd.jitdriver.can_inline, annmodel.s_Bool)
            jd._get_printable_location_ptr = self._make_hook_graph(jd,
                annhelper, jd.jitdriver.get_printable_location, s_Str)
            jd._confirm_enter_jit_ptr = self._make_hook_graph(jd,
                annhelper, jd.jitdriver.confirm_enter_jit, annmodel.s_Bool,
                onlygreens=False)
        annhelper.finish()

    def _make_hook_graph(self, jitdriver_sd, annhelper, func,
                         s_result, s_first_arg=None, onlygreens=True):
        if func is None:
            return None
        #
        extra_args_s = []
        if s_first_arg is not None:
            extra_args_s.append(s_first_arg)
        #
        args_s = jitdriver_sd._portal_args_s
        if onlygreens:
            args_s = args_s[:len(jitdriver_sd._green_args_spec)]
        graph = annhelper.getgraph(func, extra_args_s + args_s, s_result)
        funcptr = annhelper.graph2delayed(graph)
        return funcptr

    def make_args_specifications(self):
        for jd in self.jitdrivers_sd:
            self.make_args_specification(jd)

    def make_args_specification(self, jd):
        graph, block, index = jd._jit_merge_point_pos
        op = block.operations[index]
        greens_v, reds_v = support.decode_hp_hint_args(op)
        ALLARGS = [v.concretetype for v in (greens_v + reds_v)]
        jd._green_args_spec = [v.concretetype for v in greens_v]
        jd._red_args_types = [history.getkind(v.concretetype) for v in reds_v]
        jd.num_green_args = len(jd._green_args_spec)
        RESTYPE = graph.getreturnvar().concretetype
        (jd._JIT_ENTER_FUNCTYPE,
         jd._PTR_JIT_ENTER_FUNCTYPE) = self.cpu.ts.get_FuncType(ALLARGS, lltype.Void)
        (jd._PORTAL_FUNCTYPE,
         jd._PTR_PORTAL_FUNCTYPE) = self.cpu.ts.get_FuncType(ALLARGS, RESTYPE)
        (_, jd._PTR_ASSEMBLER_HELPER_FUNCTYPE) = self.cpu.ts.get_FuncType(
            [lltype.Signed, llmemory.GCREF], RESTYPE)

    def rewrite_can_enter_jits(self):
        can_enter_jits = find_can_enter_jit(self.translator.graphs)
        sublists = {}
        for jd in self.jitdrivers_sd:
            sublists[jd.jitdriver] = []
        for graph, block, index in can_enter_jits:
            op = block.operations[index]
            jitdriver = op.args[1].value
            assert jitdriver in sublists, \
                   "can_enter_jit with no matching jit_merge_point"
            sublists[jitdriver].append((graph, block, index))
        for jd in self.jitdrivers_sd:
            sublist = sublists[jd.jitdriver]
            assert len(sublist) > 0, \
                   "found no can_enter_jit for %r" % (jd.jitdriver,)
            self.rewrite_can_enter_jit(jd, sublist)

    def rewrite_can_enter_jit(self, jd, can_enter_jits):
        FUNC = jd._JIT_ENTER_FUNCTYPE
        FUNCPTR = jd._PTR_JIT_ENTER_FUNCTYPE
        jit_enter_fnptr = self.helper_func(FUNCPTR, jd._maybe_enter_jit_fn)

        for graph, block, index in can_enter_jits:
            if graph is jd._jit_merge_point_pos[0]:
                continue

            op = block.operations[index]
            greens_v, reds_v = support.decode_hp_hint_args(op)
            args_v = greens_v + reds_v

            vlist = [Constant(jit_enter_fnptr, FUNCPTR)] + args_v

            v_result = Variable()
            v_result.concretetype = lltype.Void
            newop = SpaceOperation('direct_call', vlist, v_result)
            block.operations[index] = newop

    def helper_func(self, FUNCPTR, func):
        if not self.cpu.translate_support_code:
            return llhelper(FUNCPTR, func)
        FUNC = get_functype(FUNCPTR)
        args_s = [annmodel.lltype_to_annotation(ARG) for ARG in FUNC.ARGS]
        s_result = annmodel.lltype_to_annotation(FUNC.RESULT)
        graph = self.annhelper.getgraph(func, args_s, s_result)
        return self.annhelper.graph2delayed(graph, FUNC)

    def rewrite_jit_merge_points(self, policy):
        for jd in self.jitdrivers_sd:
            self.rewrite_jit_merge_point(jd, policy)

    def rewrite_jit_merge_point(self, jd, policy):
        #
        # Mutate the original portal graph from this:
        #
        #       def original_portal(..):
        #           stuff
        #           while 1:
        #               jit_merge_point(*args)
        #               more stuff
        #
        # to that:
        #
        #       def original_portal(..):
        #           stuff
        #           return portal_runner(*args)
        #
        #       def portal_runner(*args):
        #           while 1:
        #               try:
        #                   return portal(*args)
        #               except ContinueRunningNormally, e:
        #                   *args = *e.new_args
        #               except DoneWithThisFrame, e:
        #                   return e.return
        #               except ExitFrameWithException, e:
        #                   raise Exception, e.value
        #
        #       def portal(*args):
        #           while 1:
        #               more stuff
        #
        origportalgraph = jd._jit_merge_point_pos[0]
        portalgraph = jd.portal_graph
        PORTALFUNC = jd._PORTAL_FUNCTYPE

        # ____________________________________________________________
        # Prepare the portal_runner() helper
        #
        from pypy.jit.metainterp.warmstate import specialize_value
        portal_ptr = self.cpu.ts.functionptr(PORTALFUNC, 'portal',
                                         graph = portalgraph)
        jd._portal_ptr = portal_ptr
        #
        portalfunc_ARGS = []
        nums = {}
        for i, ARG in enumerate(PORTALFUNC.ARGS):
            if i < len(jd.jitdriver.greens):
                color = 'green'
            else:
                color = 'red'
            attrname = '%s_%s' % (color, history.getkind(ARG))
            count = nums.get(attrname, 0)
            nums[attrname] = count + 1
            portalfunc_ARGS.append((ARG, attrname, count))
        portalfunc_ARGS = unrolling_iterable(portalfunc_ARGS)
        #
        rtyper = self.translator.rtyper
        RESULT = PORTALFUNC.RESULT
        result_kind = history.getkind(RESULT)
        ts = self.cpu.ts

        def ll_portal_runner(*args):
            while 1:
                try:
                    jd._maybe_enter_from_start_fn(*args)
                    return support.maybe_on_top_of_llinterp(rtyper,
                                                      portal_ptr)(*args)
                except self.ContinueRunningNormally, e:
                    args = ()
                    for ARGTYPE, attrname, count in portalfunc_ARGS:
                        x = getattr(e, attrname)[count]
                        x = specialize_value(ARGTYPE, x)
                        args = args + (x,)
                except self.DoneWithThisFrameVoid:
                    assert result_kind == 'void'
                    return
                except self.DoneWithThisFrameInt, e:
                    assert result_kind == 'int'
                    return specialize_value(RESULT, e.result)
                except self.DoneWithThisFrameRef, e:
                    assert result_kind == 'ref'
                    return specialize_value(RESULT, e.result)
                except self.DoneWithThisFrameFloat, e:
                    assert result_kind == 'float'
                    return specialize_value(RESULT, e.result)
                except self.ExitFrameWithExceptionRef, e:
                    value = ts.cast_to_baseclass(e.value)
                    if not we_are_translated():
                        raise LLException(ts.get_typeptr(value), value)
                    else:
                        value = cast_base_ptr_to_instance(Exception, value)
                        raise Exception, value

        jd._ll_portal_runner = ll_portal_runner # for debugging
        jd.portal_runner_ptr = self.helper_func(jd._PTR_PORTAL_FUNCTYPE,
                                                ll_portal_runner)
        jd.portal_runner_adr = llmemory.cast_ptr_to_adr(jd.portal_runner_ptr)
        self.cpu.portal_calldescr = self.cpu.calldescrof(
            jd._PTR_PORTAL_FUNCTYPE.TO,
            jd._PTR_PORTAL_FUNCTYPE.TO.ARGS,
            jd._PTR_PORTAL_FUNCTYPE.TO.RESULT)

        vinfo = jd.virtualizable_info

        def assembler_call_helper(failindex, virtualizableref):
            fail_descr = self.cpu.get_fail_descr_from_number(failindex)
            while True:
                if vinfo is not None:
                    virtualizable = lltype.cast_opaque_ptr(
                        vinfo.VTYPEPTR, virtualizableref)
                    vinfo.reset_vable_token(virtualizable)
                try:
                    loop_token = fail_descr.handle_fail(self.metainterp_sd, jd)
                except self.ContinueRunningNormally, e:
                    args = ()
                    for ARGTYPE, attrname, count in portalfunc_ARGS:
                        x = getattr(e, attrname)[count]
                        x = specialize_value(ARGTYPE, x)
                        args = args + (x,)
                    return ll_portal_runner(*args)
                except self.DoneWithThisFrameVoid:
                    assert result_kind == 'void'
                    return
                except self.DoneWithThisFrameInt, e:
                    assert result_kind == 'int'
                    return specialize_value(RESULT, e.result)
                except self.DoneWithThisFrameRef, e:
                    assert result_kind == 'ref'
                    return specialize_value(RESULT, e.result)
                except self.DoneWithThisFrameFloat, e:
                    assert result_kind == 'float'
                    return specialize_value(RESULT, e.result)
                except self.ExitFrameWithExceptionRef, e:
                    value = ts.cast_to_baseclass(e.value)
                    if not we_are_translated():
                        raise LLException(ts.get_typeptr(value), value)
                    else:
                        value = cast_base_ptr_to_instance(Exception, value)
                        raise Exception, value
                fail_descr = self.cpu.execute_token(loop_token)

        jd._assembler_call_helper = assembler_call_helper # for debugging
        jd._assembler_helper_ptr = self.helper_func(
            jd._PTR_ASSEMBLER_HELPER_FUNCTYPE,
            assembler_call_helper)
        jd.assembler_helper_adr = llmemory.cast_ptr_to_adr(
            jd._assembler_helper_ptr)
        if vinfo is not None:
            jd.vable_token_descr = vinfo.vable_token_descr

        # ____________________________________________________________
        # Now mutate origportalgraph to end with a call to portal_runner_ptr
        #
        _, origblock, origindex = jd._jit_merge_point_pos
        op = origblock.operations[origindex]
        assert op.opname == 'jit_marker'
        assert op.args[0].value == 'jit_merge_point'
        greens_v, reds_v = support.decode_hp_hint_args(op)
        vlist = [Constant(jd.portal_runner_ptr, jd._PTR_PORTAL_FUNCTYPE)]
        vlist += greens_v
        vlist += reds_v
        v_result = Variable()
        v_result.concretetype = PORTALFUNC.RESULT
        newop = SpaceOperation('direct_call', vlist, v_result)
        del origblock.operations[origindex:]
        origblock.operations.append(newop)
        origblock.exitswitch = None
        origblock.recloseblock(Link([v_result], origportalgraph.returnblock))
        #
        # Also kill any can_enter_jit left behind (example: see
        # test_jitdriver.test_simple, which has a can_enter_jit in
        # loop1's origportalgraph)
        can_enter_jits = _find_jit_marker([origportalgraph], 'can_enter_jit')
        for _, block, i in can_enter_jits:
            op = block.operations[i]
            assert op.opname == 'jit_marker'
            block.operations[i] = SpaceOperation('same_as',
                                                 [Constant(None, lltype.Void)],
                                                 op.result)
        #
        checkgraph(origportalgraph)

    def add_finish(self):
        def finish():
            if self.metainterp_sd.profiler.initialized:
                self.metainterp_sd.profiler.finish()
            self.metainterp_sd.cpu.finish_once()
        
        if self.cpu.translate_support_code:
            call_final_function(self.translator, finish,
                                annhelper = self.annhelper)

    def rewrite_set_param(self):
        closures = {}
        graphs = self.translator.graphs
        _, PTR_SET_PARAM_FUNCTYPE = self.cpu.ts.get_FuncType([lltype.Signed],
                                                             lltype.Void)
        def make_closure(jd, fullfuncname):
            state = jd.warmstate
            def closure(i):
                getattr(state, fullfuncname)(i)
            funcptr = self.helper_func(PTR_SET_PARAM_FUNCTYPE, closure)
            return Constant(funcptr, PTR_SET_PARAM_FUNCTYPE)
        #
        for graph, block, i in find_set_param(graphs):
            op = block.operations[i]
            for jd in self.jitdrivers_sd:
                if jd.jitdriver is op.args[1].value:
                    break
            else:
                assert 0, "jitdriver of set_param() not found"
            funcname = op.args[2].value
            key = jd, funcname
            if key not in closures:
                closures[key] = make_closure(jd, 'set_param_' + funcname)
            op.opname = 'direct_call'
            op.args[:3] = [closures[key]]

    def rewrite_force_virtual(self, vrefinfo):
        if self.cpu.ts.name != 'lltype':
            py.test.skip("rewrite_force_virtual: port it to ootype")
        all_graphs = self.translator.graphs
        vrefinfo.replace_force_virtual_with_call(all_graphs)
