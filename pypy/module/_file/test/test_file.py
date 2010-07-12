import py

from pypy.conftest import gettestobjspace, option

def getfile(space):
    return space.appexec([], """():
        try:
            import _file
            return _file.file
        except ImportError:     # when running with py.test -A
            return file
    """)

class AppTestFile(object):
    def setup_class(cls):
        cls.space = gettestobjspace(usemodules=("_file", ))
        cls.w_temppath = cls.space.wrap(
            str(py.test.ensuretemp("fileimpl").join("foo.txt")))
        cls.w_file = getfile(cls.space)

    def test_simple(self):
        f = self.file(self.temppath, "w")
        f.write("foo")
        f.close()
        f = self.file(self.temppath, "r")
        raises(TypeError, f.read, None)
        try:
            s = f.read()
            assert s == "foo"
        finally:
            f.close()

    def test_readline(self):
        f = self.file(self.temppath, "w")
        try:
            f.write("foo\nbar\n")
        finally:
            f.close()
        f = self.file(self.temppath, "r")
        raises(TypeError, f.readline, None)
        try:
            s = f.readline()
            assert s == "foo\n"
            s = f.readline()
            assert s == "bar\n"
        finally:
            f.close()

    def test_readlines(self):
        f = self.file(self.temppath, "w")
        try:
            f.write("foo\nbar\n")
        finally:
            f.close()
        f = self.file(self.temppath, "r")
        raises(TypeError, f.readlines, None)
        try:
            s = f.readlines()
            assert s == ["foo\n", "bar\n"]
        finally:
            f.close()


    def test_fdopen(self):
        import os
        f = self.file(self.temppath, "w")
        try:
            f.write("foo\nbaz\n")
        finally:
            f.close()
        try:
            fdopen = self.file.fdopen
        except AttributeError:
            fdopen = os.fdopen      # when running with -A
        fd = os.open(self.temppath, os.O_WRONLY | os.O_CREAT)
        f2 = fdopen(fd, "a")
        f2.seek(0, 2)
        f2.write("bar\nboo")
        f2.close()
        # don't close fd, will get a whining __del__
        f = self.file(self.temppath, "r")
        try:
            s = f.read()
            assert s == "foo\nbaz\nbar\nboo"
        finally:
            f.close()

    def test_badmode(self):
        raises(ValueError, self.file, "foo", "bar")

    def test_wraposerror(self):
        raises(IOError, self.file, "hopefully/not/existant.bar")

    def test_correct_file_mode(self):
        import os
        f = self.file(self.temppath, "w")
        umask = os.umask(0)
        os.umask(umask)
        try:
            f.write("foo")
        finally:
            f.close()
        assert oct(os.stat(self.temppath).st_mode & 0777) == oct(0666 & ~umask)

    def test_newlines(self):
        import os
        f = self.file(self.temppath, "wb")
        f.write("\r\n")
        assert f.newlines is None
        f.close()
        f = self.file(self.temppath, "rU")
        res = f.read()
        assert res == "\n"
        assert f.newlines == "\r\n"

    def test_unicode(self):
        import os
        f = self.file(self.temppath, "w")
        f.write(u"hello\n")
        raises(UnicodeEncodeError, f.write, u'\xe9')
        f.close()
        f = self.file(self.temppath, "r")
        res = f.read()
        assert res == "hello\n"
        assert type(res) is str
        f.close()

    def test_oserror_has_filename(self):
        try:
            f = self.file("file that is clearly not there")
        except IOError, e:
            assert e.filename == 'file that is clearly not there'
        else:
            raise Exception("did not raise")

    def test_readline_mixed_with_read(self):
        s = '''From MAILER-DAEMON Wed Jan 14 14:42:30 2009
From: foo

0
From MAILER-DAEMON Wed Jan 14 14:42:44 2009
Return-Path: <gkj@gregorykjohnson.com>
X-Original-To: gkj+person@localhost
Delivered-To: gkj+person@localhost
Received: from localhost (localhost [127.0.0.1])
        by andy.gregorykjohnson.com (Postfix) with ESMTP id 356ED9DD17
        for <gkj+person@localhost>; Wed, 13 Jul 2005 17:23:16 -0400 (EDT)
Delivered-To: gkj@sundance.gregorykjohnson.com'''
        f = self.file(self.temppath, "w")
        f.write(s)
        f.close()
        f = self.file(self.temppath, "r")
        f.seek(0L)
        f.readline()
        pos = f.tell()
        assert f.read(12L) == 'From: foo\n\n0'
        f.seek(pos)
        assert f.read(12L) == 'From: foo\n\n0'
        f.close()

    def test_invalid_modes(self):
        raises(ValueError, self.file, self.temppath, "aU")
        raises(ValueError, self.file, self.temppath, "wU+")
        raises(ValueError, self.file, self.temppath, "")
        
class AppTestConcurrency(object):
    # these tests only really make sense on top of a translated pypy-c,
    # because on top of py.py the inner calls to os.write() don't
    # release our object space's GIL.
    def setup_class(cls):
        if not option.runappdirect:
            py.test.skip("likely to deadlock when interpreted by py.py")
        cls.space = gettestobjspace(usemodules=("_file", "thread"))
        cls.w_temppath = cls.space.wrap(
            str(py.test.ensuretemp("fileimpl").join("concurrency.txt")))
        cls.w_file = getfile(cls.space)

    def test_concurrent_writes(self):
        # check that f.write() is atomic
        import thread, time
        f = self.file(self.temppath, "w+b")
        def writer(i):
            for j in range(150):
                f.write('%3d %3d\n' % (i, j))
            locks[i].release()
        locks = []
        for i in range(10):
            lock = thread.allocate_lock()
            lock.acquire()
            locks.append(lock)
        for i in range(10):
            thread.start_new_thread(writer, (i,))
        # wait until all threads are done
        for i in range(10):
            locks[i].acquire()
        f.seek(0)
        lines = f.readlines()
        lines.sort()
        assert lines == ['%3d %3d\n' % (i, j) for i in range(10)
                                              for j in range(150)]
        f.close()

    def test_parallel_writes_and_reads(self):
        # Warning: a test like the one below deadlocks CPython
        # http://bugs.python.org/issue1164
        # It also deadlocks on py.py because the space GIL is not
        # released.
        import thread, sys, os
        try:
            fdopen = self.file.fdopen
        except AttributeError:
            # when running with -A
            skip("deadlocks on top of CPython")
        read_fd, write_fd = os.pipe()
        fread = fdopen(read_fd, 'rb', 200)
        fwrite = fdopen(write_fd, 'wb', 200)
        run = True
        readers_done = [0]

        def writer():
            f = 0.1
            while run:
                print >> fwrite, f,
                f = 4*f - 3*f*f
            print >> fwrite, "X"
            fwrite.flush()
            sys.stdout.write('writer ends\n')

        def reader(j):
            while True:
                data = fread.read(1)
                #sys.stdout.write('%d%r ' % (j, data))
                if data == "X":
                    break
            sys.stdout.write('reader ends\n')
            readers_done[0] += 1

        for j in range(3):
            thread.start_new_thread(reader, (j,))
            thread.start_new_thread(writer, ())

        import time
        t = time.time() + 5
        print "start of test"
        while time.time() < t:
            time.sleep(1)
        print "end of test"

        assert readers_done[0] == 0
        run = False    # end the writers
        for i in range(600):
            time.sleep(0.4)
            sys.stdout.flush()
            x = readers_done[0]
            if x == 3:
                break
            print 'readers_done == %d, still waiting...' % (x,)
        else:
            raise Exception("time out")
        print 'Passed.'


class AppTestFile25:
    def setup_class(cls):
        cls.space = gettestobjspace(usemodules=("_file", ))
        cls.w_temppath = cls.space.wrap(
            str(py.test.ensuretemp("fileimpl").join("foo.txt")))
        cls.w_file = getfile(cls.space)

    def test___enter__(self):
        f = self.file(self.temppath, 'w')
        assert f.__enter__() is f

    def test___exit__(self):
        f = self.file(self.temppath, 'w')
        assert f.__exit__() is None
        assert f.closed

    def test_file_and_with_statement(self):
        s1 = """from __future__ import with_statement
with self.file(self.temppath, 'w') as f:
    f.write('foo')
"""
        exec s1
        assert f.closed
        
        s2 = """from __future__ import with_statement
with self.file(self.temppath, 'r') as f:
    s = f.readline()
"""
    
        exec s2
        assert s == "foo"
        assert f.closed

def test_flush_at_exit():
    from pypy import conftest
    from pypy.tool.option import make_config, make_objspace
    from pypy.tool.udir import udir

    tmpfile = udir.join('test_flush_at_exit')
    config = make_config(conftest.option)
    space = make_objspace(config)
    space.appexec([space.wrap(str(tmpfile))], """(tmpfile):
        f = open(tmpfile, 'w')
        f.write('42')
        # no flush() and no close()
        import sys; sys._keepalivesomewhereobscure = f
    """)
    space.finish()
    assert tmpfile.read() == '42'
