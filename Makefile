macports:
	sudo port install libffi-dev libz-dev libz-dev libbz2-dev libncurses-dev libexpat1-dev libssl-dev
	
thepianpython:
	python2.5 pypy/translator/goal/translate.py --stackless pypy/translator/goal/targetcommands.py
	mv ./pypy-c ./thepianpython
	
test:
	py/bin/py.test pypy/module/installation
