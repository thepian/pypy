
import py, os
from pypy.translator.platform import _run_subprocess
from pypy.translator.platform.posix import BasePosix

class Linux(BasePosix):
    name = "linux"
    
    link_flags = ['-pthread', '-lrt']
    cflags = ['-O3', '-pthread', '-fomit-frame-pointer', '-Wall', '-Wno-unused']
    standalone_only = []
    shared_only = ['-fPIC']
    so_ext = 'so'
    so_prefixes = ['lib', '']
    
    def _args_for_shared(self, args):
        return ['-shared'] + args

    def include_dirs_for_libffi(self):
        return self._pkg_config("libffi", "--cflags-only-I",
                                ['/usr/include/libffi'])

    def library_dirs_for_libffi(self):
        return self._pkg_config("libffi", "--libs-only-L",
                                ['/usr/lib/libffi'])

    def library_dirs_for_libffi_a(self):
        # places where we need to look for libffi.a
        return self.library_dirs_for_libffi() + ['/usr/lib']


class Linux64(Linux):
    shared_only = ['-fPIC']
