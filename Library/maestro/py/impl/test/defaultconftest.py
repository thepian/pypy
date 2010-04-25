import py

Module = py.test.collect.Module
Directory = py.test.collect.Directory
File = py.test.collect.File

# python collectors 
Class = py.test.collect.Class
Generator = py.test.collect.Generator
Function = py.test.collect.Function
Instance = py.test.collect.Instance

pytest_plugins = "default runner capture terminal mark skipping tmpdir monkeypatch recwarn pdb pastebin unittest helpconfig nose assertion".split()

