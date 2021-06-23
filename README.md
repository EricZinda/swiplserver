# swiplserver
A library that integrates SWI Prolog with Python.

`swiplserver` is a Python module designed for developers that want to use SWI Prolog in the implementation of a Python application. It allows running any query you could run from the SWI Prolog console (i.e. the "top level") from within your Python code. Answers to Prolog queries are returned as JSON.

The library integrates SWI Prolog by launching it and connecting to a special server called the "Prolog Language Server" inside of it. Queries are run using the library, and the library manages launching and shutting down the server automatically, making the process management invisible to the developer.  The whole process should feel just like using any other library.

Read more about the [swiplserver Python library](swiplserver/docs/swiplserver/prologserver.html).

Read more about the [Prolog Language Server](swiplserver/docs/language_server/language_server.html).