macports:
	sudo port install libffi-dev libz-dev libz-dev libbz2-dev libncurses-dev libexpat1-dev libssl-dev
	
thepianpython:
	rm -f ./thepianpython
	python2.5 pypy/translator/goal/translate.py --stackless pypy/translator/goal/targetcommands.py
	mv ./pypy-c ./thepianpython
	
thepianpython-release:
	# rm -f ./thepianpython
	python2.5 pypy/translator/goal/translate.py --no-debug --output=thepianpython-release --stackless pypy/translator/goal/targetcommands.py
	# mv ./pypy-c ./thepianpython
	strip thepianpython-release

maestrolib:
	mkdir Library/maestro
	cp -pLR lib-python/2.5.2/* Library/maestro
	cp -pLR lib-python/modified-2.5.2/* Library/maestro
	cp -pLR pypy/lib/* Library/maestro
	
test:
	py/bin/py.test pypy/module/installation
	
thepiantest:
	./thepianpython test Library/thepianpython
