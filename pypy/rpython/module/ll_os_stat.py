"""Annotation and rtyping support for the result of os.stat(), os.lstat()
and os.fstat().  In RPython like in plain Python the stat result can be
indexed like a tuple but also exposes the st_xxx attributes.
"""
import os, sys
from pypy.annotation import model as annmodel
from pypy.tool.pairtype import pairtype
from pypy.tool.sourcetools import func_with_new_name
from pypy.rpython import extregistry
from pypy.rpython.extfunc import register_external
from pypy.rpython.lltypesystem import rffi, lltype
from pypy.rpython.tool import rffi_platform as platform
from pypy.rpython.lltypesystem.rtupletype import TUPLE_TYPE
from pypy.rlib import rposix
from pypy.translator.tool.cbuild import ExternalCompilationInfo
from pypy.rpython.annlowlevel import hlstr

# Support for float times is here.
# - ALL_STAT_FIELDS contains Float fields if the system can retrieve
#   sub-second timestamps.
# - TIMESPEC is defined when the "struct stat" contains st_atim field.

if sys.platform == 'linux2':
    TIMESPEC = platform.Struct('struct timespec',
                               [('tv_sec', rffi.TIME_T),
                                ('tv_nsec', rffi.LONG)])
else:
    TIMESPEC = None

# all possible fields - some of them are not available on all platforms
ALL_STAT_FIELDS = [
    ("st_mode",      lltype.Signed),
    ("st_ino",       lltype.SignedLongLong),
    ("st_dev",       lltype.SignedLongLong),
    ("st_nlink",     lltype.Signed),
    ("st_uid",       lltype.Signed),
    ("st_gid",       lltype.Signed),
    ("st_size",      lltype.SignedLongLong),
    ("st_atime",     lltype.Float),
    ("st_mtime",     lltype.Float),
    ("st_ctime",     lltype.Float),
    ("st_blksize",   lltype.Signed),
    ("st_blocks",    lltype.Signed),
    ("st_rdev",      lltype.Signed),
    ("st_flags",     lltype.Signed),
    #("st_gen",       lltype.Signed),     -- new in CPy 2.5, not implemented
    #("st_birthtime", lltype.Float),      -- new in CPy 2.5, not implemented
    ]
N_INDEXABLE_FIELDS = 10

# for now, check the host Python to know which st_xxx fields exist
STAT_FIELDS = [(_name, _TYPE) for (_name, _TYPE) in ALL_STAT_FIELDS
                              if hasattr(os.stat_result, _name)]

STAT_FIELD_TYPES = dict(STAT_FIELDS)      # {'st_xxx': TYPE}

STAT_FIELD_NAMES = [_name for (_name, _TYPE) in ALL_STAT_FIELDS
                          if _name in STAT_FIELD_TYPES]

del _name, _TYPE

# For OO backends, expose only the portable fields (the first 10).
PORTABLE_STAT_FIELDS = STAT_FIELDS[:N_INDEXABLE_FIELDS]

# ____________________________________________________________
#
# Annotation support

class SomeStatResult(annmodel.SomeObject):
    knowntype = os.stat_result

    def rtyper_makerepr(self, rtyper):
        from pypy.rpython.module import r_os_stat
        return r_os_stat.StatResultRepr(rtyper)

    def rtyper_makekey_ex(self, rtyper):
        return self.__class__,

    def getattr(self, s_attr):
        assert s_attr.is_constant(), "non-constant attr name in getattr()"
        attrname = s_attr.const
        TYPE = STAT_FIELD_TYPES[attrname]
        return annmodel.lltype_to_annotation(TYPE)

    def _get_rmarshall_support_(self):     # for rlib.rmarshal
        # reduce and recreate stat_result objects from 10-tuples
        # (we ignore the extra values here for simplicity and portability)
        def stat_result_reduce(st):
            return (st[0], st[1], st[2], st[3], st[4],
                    st[5], st[6], st[7], st[8], st[9])
        def stat_result_recreate(tup):
            return make_stat_result(tup + extra_zeroes)
        s_reduced = annmodel.SomeTuple([annmodel.lltype_to_annotation(TYPE)
                                       for name, TYPE in PORTABLE_STAT_FIELDS])
        extra_zeroes = (0,) * (len(STAT_FIELDS) - len(PORTABLE_STAT_FIELDS))
        return s_reduced, stat_result_reduce, stat_result_recreate

class __extend__(pairtype(SomeStatResult, annmodel.SomeInteger)):
    def getitem((s_sta, s_int)):
        assert s_int.is_constant(), "os.stat()[index]: index must be constant"
        index = s_int.const
        assert 0 <= index < N_INDEXABLE_FIELDS, "os.stat()[index] out of range"
        name, TYPE = STAT_FIELDS[index]
        return annmodel.lltype_to_annotation(TYPE)

s_StatResult = SomeStatResult()

def make_stat_result(tup):
    """Turn a tuple into an os.stat_result object."""
    positional = tup[:N_INDEXABLE_FIELDS]
    kwds = {}
    for i, name in enumerate(STAT_FIELD_NAMES[N_INDEXABLE_FIELDS:]):
        kwds[name] = tup[N_INDEXABLE_FIELDS + i]
    return os.stat_result(positional, kwds)

class MakeStatResultEntry(extregistry.ExtRegistryEntry):
    _about_ = make_stat_result

    def compute_result_annotation(self, s_tup):
        return s_StatResult

    def specialize_call(self, hop):
        from pypy.rpython.module import r_os_stat
        return r_os_stat.specialize_make_stat_result(hop)

# ____________________________________________________________
#
# RFFI support

if sys.platform.startswith('win'):
    _name_struct_stat = '_stati64'
    INCLUDES = ['sys/types.h', 'sys/stat.h']
else:
    _name_struct_stat = 'stat'
    INCLUDES = ['sys/types.h', 'sys/stat.h', 'unistd.h']

compilation_info = ExternalCompilationInfo(
    # This must be set to 64 on some systems to enable large file support.
    #pre_include_bits = ['#define _FILE_OFFSET_BITS 64'],
    # ^^^ nowadays it's always set in all C files we produce.
    includes = INCLUDES
)

if sys.platform != 'win32':

    LL_STAT_FIELDS = STAT_FIELDS[:]
    
    if TIMESPEC is not None:
        class CConfig_for_timespec:
            _compilation_info_ = compilation_info
            TIMESPEC = TIMESPEC

        TIMESPEC = lltype.Ptr(
            platform.configure(CConfig_for_timespec)['TIMESPEC'])

        def _expand(lst, originalname, timespecname):
            for i, (_name, _TYPE) in enumerate(lst):
                if _name == originalname:
                    # replace the 'st_atime' field of type rffi.DOUBLE
                    # with a field 'st_atim' of type 'struct timespec'
                    lst[i] = (timespecname, TIMESPEC.TO)
                    break

        _expand(LL_STAT_FIELDS, 'st_atime', 'st_atim')
        _expand(LL_STAT_FIELDS, 'st_mtime', 'st_mtim')
        _expand(LL_STAT_FIELDS, 'st_ctime', 'st_ctim')

        del _expand
    else:
        # Replace float fields with integers
        for name in ('st_atime', 'st_mtime', 'st_ctime', 'st_birthtime'):
            for i, (_name, _TYPE) in enumerate(LL_STAT_FIELDS):
                if _name == name:
                    LL_STAT_FIELDS[i] = (_name, lltype.Signed)
                    break

    class CConfig:
        _compilation_info_ = compilation_info
        STAT_STRUCT = platform.Struct('struct %s' % _name_struct_stat, LL_STAT_FIELDS)
    config = platform.configure(CConfig)

    STAT_STRUCT = lltype.Ptr(config['STAT_STRUCT'])

def build_stat_result(st):
    # only for LL backends
    if TIMESPEC is not None:
        atim = st.c_st_atim; atime = atim.c_tv_sec + 1E-9 * atim.c_tv_nsec
        mtim = st.c_st_mtim; mtime = mtim.c_tv_sec + 1E-9 * mtim.c_tv_nsec
        ctim = st.c_st_ctim; ctime = ctim.c_tv_sec + 1E-9 * ctim.c_tv_nsec
    else:
        atime = st.c_st_atime
        mtime = st.c_st_mtime
        ctime = st.c_st_ctime

    result = (st.c_st_mode,
              st.c_st_ino,
              st.c_st_dev,
              st.c_st_nlink,
              st.c_st_uid,
              st.c_st_gid,
              st.c_st_size,
              atime,
              mtime,
              ctime)

    if "st_blksize" in STAT_FIELD_TYPES: result += (st.c_st_blksize,)
    if "st_blocks"  in STAT_FIELD_TYPES: result += (st.c_st_blocks,)
    if "st_rdev"    in STAT_FIELD_TYPES: result += (st.c_st_rdev,)
    if "st_flags"   in STAT_FIELD_TYPES: result += (st.c_st_flags,)

    return make_stat_result(result)


def register_stat_variant(name):
    if sys.platform.startswith('win'):
        _functions = {'stat':  '_stati64',
                      'fstat': '_fstati64',
                      'lstat': '_stati64'}    # no lstat on Windows
        c_func_name = _functions[name]
    elif sys.platform.startswith('linux'):
        # because we always use _FILE_OFFSET_BITS 64 - this helps things work that are not a c compiler 
        _functions = {'stat':  'stat64',
                      'fstat': 'fstat64',
                      'lstat': 'lstat64'}
        c_func_name = _functions[name]
    else:
        c_func_name = name

    arg_is_path = (name != 'fstat')

    def posix_stat_llimpl(arg):
        stresult = lltype.malloc(STAT_STRUCT.TO, flavor='raw')
        try:
            if arg_is_path:
                arg = rffi.str2charp(arg)
            error = rffi.cast(rffi.LONG, posix_mystat(arg, stresult))
            if arg_is_path:
                rffi.free_charp(arg)
            if error != 0:
                raise OSError(rposix.get_errno(), "os_?stat failed")
            return build_stat_result(stresult)
        finally:
            lltype.free(stresult, flavor='raw')

    def posix_fakeimpl(arg):
        if s_arg == str:
            arg = hlstr(arg)
        st = getattr(os, name)(arg)
        fields = [TYPE for fieldname, TYPE in STAT_FIELDS]
        TP = TUPLE_TYPE(fields)
        ll_tup = lltype.malloc(TP.TO)
        for i, (fieldname, TYPE) in enumerate(STAT_FIELDS):
            val = getattr(st, fieldname)
            if isinstance(TYPE, lltype.Number):
                rffi.setintfield(ll_tup, 'item%d' % i, int(val))
            elif TYPE is lltype.Float:
                setattr(ll_tup, 'item%d' % i, float(val))
            else:
                setattr(ll_tup, 'item%d' % i, val)
        return ll_tup

    if arg_is_path:
        s_arg = str
        ARG1 = rffi.CCHARP
    else:
        s_arg = int
        ARG1 = rffi.INT

    if sys.platform != 'win32':
        posix_mystat = rffi.llexternal(c_func_name,
                                       [ARG1, STAT_STRUCT], rffi.INT,
                                       compilation_info=compilation_info)

        register_external(
            getattr(os, name), [s_arg], s_StatResult,
            "ll_os.ll_os_%s" % (name,),
            llimpl=func_with_new_name(posix_stat_llimpl,
                                      'os_%s_llimpl' % (name,)),
            llfakeimpl=func_with_new_name(posix_fakeimpl,
                                          'os_%s_fake' % (name,)),
            )
    else:
        # See Win32 implementation below
        register_external(
            getattr(os, name), [s_arg], s_StatResult,
            "ll_os.ll_os_%s" % (name,),
            llimpl=func_with_new_name(globals()['win32_%s_llimpl' % (name,)],
                                      'os_%s_llimpl' % (name,)),
            )

# ____________________________________________________________
if sys.platform == 'win32':
    # The CRT of Windows has a number of flaws wrt. its stat() implementation:
    # - for when we implement subsecond resolution in RPython, time stamps
    #   would be restricted to second resolution
    # - file modification times suffer from forth-and-back conversions between
    #   UTC and local time
    # Therefore, we implement our own stat, based on the Win32 API directly.
    from pypy.rpython.tool import rffi_platform as platform
    from pypy.translator.tool.cbuild import ExternalCompilationInfo
    from pypy.rlib import rwin32

    assert len(STAT_FIELDS) == 10    # no extra fields on Windows

    class CConfig:
        _compilation_info_ = ExternalCompilationInfo(
            includes = ['windows.h', 'winbase.h', 'sys/stat.h'],
            )

        GetFileExInfoStandard = platform.ConstantInteger(
            'GetFileExInfoStandard')
        FILE_ATTRIBUTE_DIRECTORY = platform.ConstantInteger(
            'FILE_ATTRIBUTE_DIRECTORY')
        FILE_ATTRIBUTE_READONLY = platform.ConstantInteger(
            'FILE_ATTRIBUTE_READONLY')
        ERROR_SHARING_VIOLATION = platform.ConstantInteger(
            'ERROR_SHARING_VIOLATION')
        _S_IFDIR = platform.ConstantInteger('_S_IFDIR')
        _S_IFREG = platform.ConstantInteger('_S_IFREG')
        _S_IFCHR = platform.ConstantInteger('_S_IFCHR')
        _S_IFIFO = platform.ConstantInteger('_S_IFIFO')
        FILE_TYPE_UNKNOWN = platform.ConstantInteger('FILE_TYPE_UNKNOWN')
        FILE_TYPE_CHAR = platform.ConstantInteger('FILE_TYPE_CHAR')
        FILE_TYPE_PIPE = platform.ConstantInteger('FILE_TYPE_PIPE')

        WIN32_FILE_ATTRIBUTE_DATA = platform.Struct(
            'WIN32_FILE_ATTRIBUTE_DATA',
            [('dwFileAttributes', rwin32.DWORD),
             ('nFileSizeHigh', rwin32.DWORD),
             ('nFileSizeLow', rwin32.DWORD),
             ('ftCreationTime', rwin32.FILETIME),
             ('ftLastAccessTime', rwin32.FILETIME),
             ('ftLastWriteTime', rwin32.FILETIME)])

        BY_HANDLE_FILE_INFORMATION = platform.Struct(
            'BY_HANDLE_FILE_INFORMATION',
            [('dwFileAttributes', rwin32.DWORD),
             ('nFileSizeHigh', rwin32.DWORD),
             ('nFileSizeLow', rwin32.DWORD),
             ('nNumberOfLinks', rwin32.DWORD),
             ('nFileIndexHigh', rwin32.DWORD),
             ('nFileIndexLow', rwin32.DWORD),
             ('ftCreationTime', rwin32.FILETIME),
             ('ftLastAccessTime', rwin32.FILETIME),
             ('ftLastWriteTime', rwin32.FILETIME)])

        WIN32_FIND_DATA = platform.Struct(
            'WIN32_FIND_DATAA',
            # Only interesting fields
            [('dwFileAttributes', rwin32.DWORD),
             ('nFileSizeHigh', rwin32.DWORD),
             ('nFileSizeLow', rwin32.DWORD),
             ('ftCreationTime', rwin32.FILETIME),
             ('ftLastAccessTime', rwin32.FILETIME),
             ('ftLastWriteTime', rwin32.FILETIME)])

    globals().update(platform.configure(CConfig))
    GET_FILEEX_INFO_LEVELS = rffi.ULONG # an enumeration

    GetFileAttributesEx = rffi.llexternal(
        'GetFileAttributesExA',
        [rffi.CCHARP, GET_FILEEX_INFO_LEVELS,
         lltype.Ptr(WIN32_FILE_ATTRIBUTE_DATA)],
        rwin32.BOOL,
        calling_conv='win')

    GetFileInformationByHandle = rffi.llexternal(
        'GetFileInformationByHandle',
        [rwin32.HANDLE, lltype.Ptr(BY_HANDLE_FILE_INFORMATION)],
        rwin32.BOOL,
        calling_conv='win')

    GetFileType = rffi.llexternal(
        'GetFileType',
        [rwin32.HANDLE],
        rwin32.DWORD,
        calling_conv='win')

    FindFirstFile = rffi.llexternal(
        'FindFirstFileA',
        [rffi.CCHARP, lltype.Ptr(WIN32_FIND_DATA)],
        rwin32.HANDLE,
        calling_conv='win')

    FindClose = rffi.llexternal(
        'FindClose',
        [rwin32.HANDLE],
        rwin32.BOOL,
        calling_conv='win')

    def attributes_to_mode(attributes):
        m = 0
        if attributes & FILE_ATTRIBUTE_DIRECTORY:
            m |= _S_IFDIR | 0111 # IFEXEC for user,group,other
        else:
            m |= _S_IFREG
        if attributes & FILE_ATTRIBUTE_READONLY:
            m |= 0444
        else:
            m |= 0666
        return m

    def make_longlong(high, low):
        return (lltype.r_longlong(high) << 32) + lltype.r_longlong(low)

    # Seconds between 1.1.1601 and 1.1.1970
    secs_between_epochs = lltype.r_longlong(11644473600)

    def FILE_TIME_to_time_t_nsec(filetime):
        ft = make_longlong(filetime.c_dwHighDateTime, filetime.c_dwLowDateTime)
        # FILETIME is in units of 100 nsec
        nsec = (ft % 10000000) * 100
        time = (ft / 10000000) - secs_between_epochs
        return time, nsec

    def time_t_to_FILE_TIME(time, filetime):
        ft = lltype.r_longlong((time + secs_between_epochs) * 10000000)
        filetime.c_dwHighDateTime = lltype.r_uint(ft >> 32)
        filetime.c_dwLowDateTime = lltype.r_uint(ft & ((1 << 32) - 1))
        
    def attribute_data_to_stat(info):
        st_mode = attributes_to_mode(info.c_dwFileAttributes)
        st_size = make_longlong(info.c_nFileSizeHigh, info.c_nFileSizeLow)
        ctime, ctime_ns = FILE_TIME_to_time_t_nsec(info.c_ftCreationTime)
        mtime, mtime_ns = FILE_TIME_to_time_t_nsec(info.c_ftLastWriteTime)
        atime, atime_ns = FILE_TIME_to_time_t_nsec(info.c_ftLastAccessTime)

        result = (st_mode,
                  0, 0, 0, 0, 0,
                  st_size,
                  float(atime) + atime_ns * 1e-9,
                  float(mtime) + mtime_ns * 1e-9,
                  float(ctime) + ctime_ns * 1e-9)

        return make_stat_result(result)

    def by_handle_info_to_stat(info):
        # similar to the one above
        st_mode = attributes_to_mode(info.c_dwFileAttributes)
        st_size = make_longlong(info.c_nFileSizeHigh, info.c_nFileSizeLow)
        ctime, ctime_ns = FILE_TIME_to_time_t_nsec(info.c_ftCreationTime)
        mtime, mtime_ns = FILE_TIME_to_time_t_nsec(info.c_ftLastWriteTime)
        atime, atime_ns = FILE_TIME_to_time_t_nsec(info.c_ftLastAccessTime)

        # specific to fstat()
        st_ino = make_longlong(info.c_nFileIndexHigh, info.c_nFileIndexLow)
        st_nlink = info.c_nNumberOfLinks

        result = (st_mode,
                  st_ino, 0, st_nlink, 0, 0,
                  st_size,
                  atime + atime_ns * 1e-9,
                  mtime + mtime_ns * 1e-9,
                  ctime + ctime_ns * 1e-9)

        return make_stat_result(result)

    def attributes_from_dir(l_path, data):
        filedata = lltype.malloc(WIN32_FIND_DATA, flavor='raw')
        hFindFile = FindFirstFile(l_path, filedata)
        if hFindFile == rwin32.INVALID_HANDLE_VALUE:
            return 0
        FindClose(hFindFile)
        data.c_dwFileAttributes = filedata.c_dwFileAttributes
        rffi.structcopy(data.c_ftCreationTime, filedata.c_ftCreationTime)
        rffi.structcopy(data.c_ftLastAccessTime, filedata.c_ftLastAccessTime)
        rffi.structcopy(data.c_ftLastWriteTime, filedata.c_ftLastWriteTime)
        data.c_nFileSizeHigh    = filedata.c_nFileSizeHigh
        data.c_nFileSizeLow     = filedata.c_nFileSizeLow
        return 1

    def win32_stat_llimpl(path):
        data = lltype.malloc(WIN32_FILE_ATTRIBUTE_DATA, flavor='raw')
        try:
            l_path = rffi.str2charp(path)
            res = GetFileAttributesEx(l_path, GetFileExInfoStandard, data)
            errcode = rwin32.GetLastError()
            if res == 0:
                if errcode == ERROR_SHARING_VIOLATION:
                    res = attributes_from_dir(l_path, data)
                    errcode = rwin32.GetLastError()
            rffi.free_charp(l_path)
            if res == 0:
                raise WindowsError(errcode, "os_stat failed")
            return attribute_data_to_stat(data)
        finally:
            lltype.free(data, flavor='raw')
    win32_lstat_llimpl = win32_stat_llimpl

    def win32_fstat_llimpl(fd):
        handle = rwin32._get_osfhandle(fd)

        filetype = GetFileType(handle)
        if filetype == FILE_TYPE_CHAR:
            # console or LPT device
            return make_stat_result((_S_IFCHR,
                                     0, 0, 0, 0, 0,
                                     0, 0, 0, 0))
        elif filetype == FILE_TYPE_PIPE:
            # socket or named pipe
            return make_stat_result((_S_IFIFO,
                                     0, 0, 0, 0, 0,
                                     0, 0, 0, 0))
        elif filetype == FILE_TYPE_UNKNOWN:
            error = rwin32.GetLastError()
            if error != 0:
                raise WindowsError(error, "os_fstat failed")
            # else: unknown but valid file

        # normal disk file (FILE_TYPE_DISK)
        info = lltype.malloc(BY_HANDLE_FILE_INFORMATION, flavor='raw',
                             zero=True)
        try:
            res = GetFileInformationByHandle(handle, info)
            if res == 0:
                raise WindowsError(rwin32.GetLastError(), "os_fstat failed")
            return by_handle_info_to_stat(info)
        finally:
            lltype.free(info, flavor='raw')

