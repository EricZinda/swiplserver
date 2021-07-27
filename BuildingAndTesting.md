# How to test
1. Create a new directory
2. Copy test_prologserver.py into the directory
3. Open a command window
2. cd to the directory you created and:
~~~
python3 -m venv ./env
source env/bin/activate
pip install swiplserver
python test_prologserver.py
~~~
 
# How to build for `pip install`
~~~
python3 -m build
~~~
For testing:
~~~
python3 -m twine upload --repository testpypi dist/*
~~~

For release:
~~~
python3 -m twine upload dist/*
~~~

# How to build the Python documentation
HTML Docs produced with https://pdoc3.github.io

~~~
pip install pdoc3
pdoc --html --force --output-dir docs --config show_source_code=False swiplserver.prologserver
~~~

# How to build the Prolog documentation
1. Open SWI Prolog
~~~
consult("/.../swiplserver/language_server/language_server.pl")
doc_save("/.../swiplserver/language_server/language_server.pl", [doc_root("/.../swiplserver/docs/language_server")]).
consult("/.../swiplserver/language_server/language_server_overview_doc.pl")
doc_save("/.../swiplserver/language_server/language_server_overview_doc.pl", [doc_root("/.../swiplserver/docs/language_server")]).
~~~
