# For external projects that want a "svn:externals" link
# to greenlets, please use the following svn:externals:
#
#     greenlet http://codespeak.net/svn/greenlet/trunk/c
#
# This file is here to have such a case work transparently
# with auto-compilation of the .c file.  It requires the
# py lib, however. (the need could be factored out though)

from greenlet.buildcmodule import make_module_from_c
import py as _py
_path = _py.path.local(__file__).dirpath().join('_greenlet.c')
_module = make_module_from_c(_path)
globals().update(_module.__dict__)
