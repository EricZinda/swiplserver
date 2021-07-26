# swiplserver
#### A library that integrates SWI Prolog with Python.

`swiplserver` is a Python module designed for developers that want to use SWI Prolog in the implementation of a Python application. It allows running any query you could run from the SWI Prolog console (i.e. the "top level") from within your Python code. Answers to Prolog queries are returned as JSON.

The library integrates SWI Prolog by launching it and connecting to a special server running inside Prolog called the Prolog Language Server. Queries are run using the Python library. The library manages launching and shutting down the server automatically, making the process management invisible to the developer.  The whole process should feel just like using any other library.

~~~
from swiplserver import PrologServer, PrologThread

with PrologServer() as server:
    with server.create_thread() as prolog_thread:
        result = prolog_thread.query("member(X, [color(blue), color(red)])")
        print(result)

[{'X': {'functor': 'color', 'args': ['blue']}},
 {'X': {'functor': 'color', 'args': ['red']}}]
~~~

### Installation
To install and learn how to use the swiplserver Python library, see [the docs](https://blog.inductorsoftware.com/swiplserver/swiplserver/prologserver.html).

### Using the Language Server with Other Languages
While `swiplserver` automatically manages dealing with the Language Server in SWI Prolog, documentation for it is provided since it is intended to be used for integrating other programming languages with SWI Prolog as well. The code is available in this repository at: `swiplserver/language_server.pl`  Read more in:
- [Prolog Language Server Overview](https://blog.inductorsoftware.com/swiplserver/language_server/language_server_overview_doc.html)
- [language_server Predicates Reference](https://blog.inductorsoftware.com/swiplserver/language_server/language_server.html)

### Supported Configurations
Should work on:
- SWI Prolog 8.2.2 or greater (may work on older builds, untested)
- Any Mac, Linux Variants or Windows that are supported by SWI Prolog
- Python 3.7 or later (may work on older builds, untested)

Has been tested with:
- Ubuntu 20.04.2 + SWI Prolog 8.3.22 + Python 3.7.8
- Windows 10 Pro 64 bit + SWI Prolog 8.3.27 + Python 3.7.0
- Windows 8.1 Pro 64 bit + SWI Prolog 8.2.4 + Python 3.8.1
- MacOS Catalina/Big Sur + SWI Prolog 8.3.24 + Python 3.7.4

### Performance
If you're interested in rough performance overhead of the approach this library takes.  On a late 2013 macbook pro the per call overhead of the library for running a Prolog query is about:
- 170 uSec per call using TCP/IP localhost
- 145 uSec per call using Unix Domain Sockets

### Known issues
A [known issue](https://github.com/SWI-Prolog/swipl-devel/issues/852) in SWI Prolog means that server threads from closed connections will leave a record in `thread_property/2` that shows them as exited but `$aborted` inside of Prolog. This is inert. The bug has been fixed in the development branch of Prolog.
