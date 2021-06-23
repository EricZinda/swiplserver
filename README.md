# swiplserver
#### A library that integrates SWI Prolog with Python.

`swiplserver` is a Python module designed for developers that want to use SWI Prolog in the implementation of a Python application. It allows running any query you could run from the SWI Prolog console (i.e. the "top level") from within your Python code. Answers to Prolog queries are returned as JSON.

The library integrates SWI Prolog by launching it and connecting to a special server running inside Prolog called the [Prolog Language Server](https://blog.inductorsoftware.com/swiplserver/language_server/language_server.html). Queries are run using the Python library. The library manages launching and shutting down the server automatically, making the process management invisible to the developer.  The whole process should feel just like using any other library.

~~~
from swiplserver import PrologServer, PrologThread

with PrologServer() as server:
    with server.create_thread() as prolog_thread:
        result = prolog_thread.query("member(X, [color(blue), color(red)])")
        print(result)

[{'X': {'functor': 'color', 'args': ['blue']}},
 {'X': {'functor': 'color', 'args': ['red']}}]
~~~

To install and learn how to use the swiplserver Python library, see [the docs](https://blog.inductorsoftware.com/swiplserver/swiplserver/prologserver.html).

While `swiplserver` automatically manages dealing with the Language Server in SWI Prolog, documentation for it is provided since it is intended to be used for integrating other programming languages with SWI Prolog as well. The code is available in this repository: `swiplserver/language_server.pl`  Read more in [the Prolog Language Server docs](https://blog.inductorsoftware.com/swiplserver/language_server/language_server.html).