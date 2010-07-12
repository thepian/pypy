from pypy.jit.metainterp.history import AbstractDescr, getkind
from pypy.jit.codewriter.flatten import Register, Label, TLabel, KINDS
from pypy.jit.codewriter.flatten import ListOfKind, IndirectCallTargets
from pypy.jit.codewriter.format import format_assembler
from pypy.jit.codewriter.jitcode import SwitchDictDescr, JitCode
from pypy.jit.codewriter import heaptracker
from pypy.rlib.objectmodel import ComputedIntSymbolic
from pypy.objspace.flow.model import Constant
from pypy.rpython.lltypesystem import lltype, llmemory, rclass


class Assembler(object):

    def __init__(self):
        self.insns = {}
        self.descrs = []
        self.indirectcalltargets = set()    # set of JitCodes
        self.list_of_addr2name = []
        self._descr_dict = {}
        self._count_jitcodes = 0
        self._seen_raw_objects = set()

    def assemble(self, ssarepr, jitcode=None):
        """Take the 'ssarepr' representation of the code and assemble
        it inside the 'jitcode'.  If jitcode is None, make a new one.
        """
        self.setup()
        ssarepr._insns_pos = []
        for insn in ssarepr.insns:
            ssarepr._insns_pos.append(len(self.code))
            self.write_insn(insn)
        self.fix_labels()
        self.check_result()
        if jitcode is None:
            jitcode = JitCode(ssarepr.name)
        jitcode._ssarepr = ssarepr
        self.make_jitcode(jitcode)
        if self._count_jitcodes < 20:    # stop if we have a lot of them
            jitcode._dump = format_assembler(ssarepr)
        self._count_jitcodes += 1
        return jitcode

    def setup(self):
        self.code = []
        self.constants_dict = {}
        self.constants_i = []
        self.constants_r = []
        self.constants_f = []
        self.label_positions = {}
        self.tlabel_positions = []
        self.switchdictdescrs = []
        self.count_regs = dict.fromkeys(KINDS, 0)
        self.liveness = {}
        self.startpoints = set()
        self.alllabels = set()

    def emit_reg(self, reg):
        if reg.index >= self.count_regs[reg.kind]:
            self.count_regs[reg.kind] = reg.index + 1
        self.code.append(chr(reg.index))

    def emit_const(self, const, kind, allow_short=False):
        value = const.value
        TYPE = lltype.typeOf(value)
        if kind == 'int':
            if isinstance(TYPE, lltype.Ptr):
                assert TYPE.TO._gckind == 'raw'
                self.see_raw_object(value)
                value = llmemory.cast_ptr_to_adr(value)
                TYPE = llmemory.Address
            if TYPE == llmemory.Address:
                value = heaptracker.adr2int(value)
            elif not isinstance(value, ComputedIntSymbolic):
                value = lltype.cast_primitive(lltype.Signed, value)
                if allow_short and -128 <= value <= 127:
                    # emit the constant as a small integer
                    self.code.append(chr(value & 0xFF))
                    return True
            constants = self.constants_i
        elif kind == 'ref':
            value = lltype.cast_opaque_ptr(llmemory.GCREF, value)
            constants = self.constants_r
        elif kind == 'float':
            assert TYPE == lltype.Float
            constants = self.constants_f
        else:
            raise NotImplementedError(const)
        key = (kind, Constant(value))
        if key not in self.constants_dict:
            constants.append(value)
            self.constants_dict[key] = 256 - len(constants)
        # emit the constant normally, as one byte that is an index in the
        # list of constants
        self.code.append(chr(self.constants_dict[key]))
        return False

    def write_insn(self, insn):
        if insn[0] == '---':
            return
        if isinstance(insn[0], Label):
            self.label_positions[insn[0].name] = len(self.code)
            return
        if insn[0] == '-live-':
            key = len(self.code)
            live_i, live_r, live_f = self.liveness.get(key, ("", "", ""))
            live_i = self.get_liveness_info(live_i, insn[1:], 'int')
            live_r = self.get_liveness_info(live_r, insn[1:], 'ref')
            live_f = self.get_liveness_info(live_f, insn[1:], 'float')
            self.liveness[key] = live_i, live_r, live_f
            return
        startposition = len(self.code)
        self.code.append("temporary placeholder")
        #
        argcodes = []
        for x in insn[1:]:
            if isinstance(x, Register):
                self.emit_reg(x)
                argcodes.append(x.kind[0])
            elif isinstance(x, Constant):
                kind = getkind(x.concretetype)
                is_short = self.emit_const(x, kind, allow_short=True)
                if is_short:
                    argcodes.append('c')
                else:
                    argcodes.append(kind[0])
            elif isinstance(x, TLabel):
                self.alllabels.add(len(self.code))
                self.tlabel_positions.append((x.name, len(self.code)))
                self.code.append("temp 1")
                self.code.append("temp 2")
                argcodes.append('L')
            elif isinstance(x, ListOfKind):
                itemkind = x.kind
                lst = list(x)
                assert len(lst) <= 255, "list too long!"
                self.code.append(chr(len(lst)))
                for item in lst:
                    if isinstance(item, Register):
                        assert itemkind == item.kind
                        self.emit_reg(item)
                    elif isinstance(item, Constant):
                        assert itemkind == getkind(item.concretetype)
                        self.emit_const(item, itemkind)
                    else:
                        raise NotImplementedError("found in ListOfKind(): %r"
                                                  % (item,))
                argcodes.append(itemkind[0].upper())
            elif isinstance(x, AbstractDescr):
                if x not in self._descr_dict:
                    self._descr_dict[x] = len(self.descrs)
                    self.descrs.append(x)
                if isinstance(x, SwitchDictDescr):
                    self.switchdictdescrs.append(x)
                num = self._descr_dict[x]
                assert 0 <= num <= 0xFFFF, "too many AbstractDescrs!"
                self.code.append(chr(num & 0xFF))
                self.code.append(chr(num >> 8))
                argcodes.append('d')
            elif isinstance(x, IndirectCallTargets):
                self.indirectcalltargets.update(x.lst)
            elif x == '->':
                assert '>' not in argcodes
                argcodes.append('>')
            else:
                raise NotImplementedError(x)
        #
        opname = insn[0]
        assert '>' not in argcodes or argcodes.index('>') == len(argcodes) - 2
        key = opname + '/' + ''.join(argcodes)
        num = self.insns.setdefault(key, len(self.insns))
        self.code[startposition] = chr(num)
        self.startpoints.add(startposition)

    def get_liveness_info(self, prevlives, args, kind):
        """Return a string whose characters are register numbers.
        We sort the numbers, too, to increase the chances of duplicate
        strings (which are collapsed into a single string during translation).
        """
        lives = set(prevlives)    # set of characters
        for reg in args:
            if isinstance(reg, Register) and reg.kind == kind:
                lives.add(chr(reg.index))
        return lives

    def fix_labels(self):
        for name, pos in self.tlabel_positions:
            assert self.code[pos  ] == "temp 1"
            assert self.code[pos+1] == "temp 2"
            target = self.label_positions[name]
            assert 0 <= target <= 0xFFFF
            self.code[pos  ] = chr(target & 0xFF)
            self.code[pos+1] = chr(target >> 8)
        for descr in self.switchdictdescrs:
            descr.dict = {}
            for key, switchlabel in descr._labels:
                target = self.label_positions[switchlabel.name]
                descr.dict[key] = target

    def check_result(self):
        # Limitation of the number of registers, from the single-byte encoding
        assert self.count_regs['int'] + len(self.constants_i) <= 256
        assert self.count_regs['ref'] + len(self.constants_r) <= 256
        assert self.count_regs['float'] + len(self.constants_f) <= 256

    def make_jitcode(self, jitcode):
        jitcode.setup(''.join(self.code),
                      self.constants_i,
                      self.constants_r,
                      self.constants_f,
                      self.count_regs['int'],
                      self.count_regs['ref'],
                      self.count_regs['float'],
                      liveness=self.liveness,
                      startpoints=self.startpoints,
                      alllabels=self.alllabels)

    def see_raw_object(self, value):
        if value._obj not in self._seen_raw_objects:
            self._seen_raw_objects.add(value._obj)
            if not value:    # filter out NULL pointers
                return
            TYPE = lltype.typeOf(value).TO
            if isinstance(TYPE, lltype.FuncType):
                name = value._obj._name
            elif TYPE == rclass.OBJECT_VTABLE:
                name = ''.join(value.name).rstrip('\x00')
            else:
                return
            addr = llmemory.cast_ptr_to_adr(value)
            self.list_of_addr2name.append((addr, name))
