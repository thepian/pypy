"""
Various flags used during the compilation process.
"""

CO_OPTIMIZED = 0x0001
CO_NEWLOCALS = 0x0002
CO_VARARGS = 0x0004
CO_VARKEYWORDS = 0x0008
CO_NESTED = 0x0010
CO_GENERATOR = 0x0020
CO_NOFREE = 0x0040
CO_CONTAINSLOOP = 0x0080
CO_CONTAINSGLOBALS = 0x0800
CO_GENERATOR_ALLOWED = 0x1000
CO_FUTURE_DIVISION = 0x2000
CO_FUTURE_ABSOLUTE_IMPORT = 0x4000
CO_FUTURE_WITH_STATEMENT = 0x8000

PyCF_SOURCE_IS_UTF8 = 0x0100
PyCF_DONT_IMPLY_DEDENT = 0x0200
PyCF_AST_ONLY = 0x0400
