"""
Allows using SWI Prolog as an embedded part of an application, "like a library". Tested with SWI-Prolog 8.2.4-1 and Python 3.7.4.

`swiplserver` enables SWI Prolog queries to be executed from within your Python application as if Python had a Prolog engine running inside of it.

`swiplserver` provides:

 - The `PrologServer` class that automatically manages starting and stopping the SWI Prolog instance(s) and runs the `language_server/1` predicate which starts a JSON query server.  This predicate is defined in the `language_server.pl` Prolog program included with this library.
 - The `PrologThread` class is used to run queries on the created process. Queries are run exactly as they would be if you were interacting with the SWI Prolog "top level" (i.e. the Prolog command line).

Installation:

    1. Install SWI Prolog (www.swi-prolog.org) and ensure that "swipl" is on the system path.
    2. Copy the "swiplserver" library (the whole directory) to be a subdirectory of your Python project.
    3. From within your python project directory run the tests using "python ./swiplserver/test_prologserver.py" to ensure everything is working correctly.

Usage:

    `PrologThread` represents a thread in *Prolog* (not in Python!). A given `PrologThread` instance will always run queries on the same Prolog thread (i.e. single threaded within Prolog).

    To run a query and wait until all results are returned:

        from swiplserver import PrologServer, PrologThread

        with PrologServer() as server:
            with server.create_thread() as prolog_thread:
                result = prolog_thread.query("atom(a)")
                print(result)

        True

    To run a query that returns multiple results and retrieve them as they are available:

        from swiplserver import PrologServer, PrologThread

        with PrologServer() as server:
            with server.create_thread() as prolog_thread:
                prolog_thread.query_async("member(X, [first, second, third])",
                                          find_all=False)
                while True:
                    result = prolog_thread.query_async_result()
                    if result is None:
                        break
                    else:
                        print(result)
        first
        second
        third

    Creating two `PrologThread` instances allows queries to be run on multiple threads in Prolog:

        from swiplserver import PrologServer, PrologThread

        with PrologServer() as server:
            with server.create_thread() as prolog_thread1:
                with server.create_thread() as prolog_thread2:
                    prolog_thread1.query_async("sleep(2), writeln(first_thread(true))")
                    prolog_thread2.query_async("sleep(1), writeln(second_thread(true))")
                    thread1_answer = prolog_thread1.query_async_result()
                    thread2_answer = prolog_thread2.query_async_result()

        Prolog: second_thread(true)
        Prolog: first_thread(true)

    Output printed in Prolog using `writeln/1` or errors output by Prolog itself are written to Python's logging facility using the `swiplserver` log and shown prefixed with "Prolog:" as above.

    Answers to Prolog queries that are not simply `True` or `False` are converted to JSON using the [json_to_prolog/2](https://www.swi-prolog.org/pldoc/doc_for?object=json_to_prolog/2) predicate in Prolog. They are returned as a Python `dict` with query variables as the keys and standard JSON as the values. If there is more than one answer, it is returned as a list:

        from swiplserver import PrologServer, PrologThread

        with PrologServer() as server:
            with server.create_thread() as prolog_thread:
                result = prolog_thread.query("member(X, [color(blue), color(red)])")
                print(result)

        [{'X': {'functor': 'color', 'args': ['blue']}},
         {'X': {'functor': 'color', 'args': ['red']}}]

Exceptions in Prolog code are raised using Python's native exception facilities.

More information is provided in the module documentation below.
"""
# HTML Docs produced with https://pdoc3.github.io
# pdoc --html --config show_source_code=False swiplserver.prologserver --force --output-dir swiplserver/docs
# pdoc --html --config show_source_code=False swiplserver.prologserver --force --output-dir swiplserver/docs --http localhost:5000

import json
import logging
import os
import socket
import subprocess
import unittest
import uuid
from os.path import join
from threading import Thread


class PrologError(Exception):
    """
    Base class used for all exceptions raised by `swiplserver.prologserver`. Used directly when an exception is thrown by Prolog code itself, otherwise the subclass exceptions are used.
    """
    def __init__(self, exception_json):
        assert prolog_name(exception_json) == "exception" and len(prolog_args(exception_json)) == 1
        self._exception_json = prolog_args(exception_json)[0]
        super().__init__(self.prolog())

    def json(self):
        """
        Returns:
            A string that represents the Prolog exception in Prolog json form. See `swiplserver.prologserver` for documentation on the Prolog json format.
        """
        return self._exception_json

    def prolog(self):
        """
        Returns:
            A string that represents the Prolog exception in the Prolog native form.
        """
        return json_to_prolog(self._exception_json)

    def is_prolog_exception(self, term_name):
        """
        True if the exception thrown by Prolog code has the term name specified by term_name.

        Args:
            term_name: The name of the Prolog term to test for.
        """
        return prolog_name(self._exception_json) == term_name


class PrologLaunchError(PrologError):
    """
    Raised when the SWI Prolog process was unable to be launched for any reason.
    """
    pass


class PrologQueryTimeoutError(PrologError):
    """
    Raised when a Prolog query times out when calling `PrologThread.query()` or `PrologThread.query_async()` with a timeout.
    """
    def __init__(self, exception_json):
        super().__init__(exception_json)


class PrologConnectionFailedError(PrologError):
    """
    Raised when the connection used by a `PrologThread` fails. Indicates that the server will no longer respond.
    """
    def __init__(self, exception_json):
        super().__init__(exception_json)


class PrologNoQueryError(PrologError):
    """
    Raised by `PrologThread.cancel_query_async()` and `PrologThread.query_async_result()` if there is no query running and no results to retrieve.
    """
    def __init__(self, exception_json):
        super().__init__(exception_json)


class PrologQueryCancelledError(PrologError):
    """
    Raised by `PrologThread.query_async_result()` when the query has been cancelled.
    """
    def __init__(self, exception_json):
        super().__init__(exception_json)


class PrologResultNotAvailableError(PrologError):
    """
    Raised by `PrologThread.query_async_result()` when the next result to a query is not yet available.
    """
    def __init__(self, exception_json):
        super().__init__(exception_json)


class PrologServer:
    def __init__(self,
                 launch_server: bool = True,
                 port: int = None,
                 password: str = None,
                 unix_domain_socket: str = None,
                 query_timeout_seconds: float = None,
                 pending_connection_count: int = None,
                 halt_on_connection_failure: bool = True,
                 output_file_name: str = None,
                 server_traces: bool = False):
        """
        Initialize a PrologServer class that manages a SWI Prolog process associated with your application process. `PrologServer.start()` actually launches the process if launch_server is True.

        This class is designed to allow Prolog to be used "like a normal Python library" -- not as a central server that multiple applications connect to. Thus, all communication is done using protocols that only work on the same machine as your application (localhost TCP/IP or Unix Domain Sockets), and the implementation is designed to make sure the process doesn't hang around even if the application is terminated unexpectedly (as with halting a debugger).

        All arguments are optional and the defaults are set to the recommended settings that work best on all platforms during development. In production on Unix systems, consider using unix_domain_socket to further decrease security attack surface area.

        For debugging scenarios, SWI Prolog can be launched manually and this class can be configured to (locally) connect to it using launch_server = False. This allows for inspection of the server state and using the SWI Prolog debugging tools while your application is running. See the documentation for the Prolog `language_server/1` predicate for more information on how to run the language server in this mode.

        Examples:
            To automatically launch a SWI Prolog process using TCP/IP localhost to communicate with an automatically chosen port and password (the default):

                with PrologServer() as server:
                    # your code here

            To connect to an existing SWI Prolog process that has already started the language_server/1 predicate and is using the Unix Domain Socket '/temp/mysocket' and a password of '8UIDSSDXLPOI':

                with PrologServer(launch_server = False,
                                  unix_domain_socket = '/temp/mysocket',
                                  password = '8UIDSSDXLPOI') as server:
                    # your code here

        Args:
            launch_server: True (default) launch a SWI Prolog process on `PrologServer.start()` and shuts it down automatically on `PrologServer.stop()` (or after a resource manager like the Python "with" statement exits). False connects to an existing SWI Prolog process that is running the language_server/1 predicate. When False, password and one of port or unix_domain_socket must be specified to match the options provided to `language_server/1` in the separate SWI Prolog process.

            port: The TCP/IP localhost port to use for communication with the SWI Prolog process. Ignored if unix_domain_socket is not None.
                When launch_server is True, None (default) automatically picks an open port that the server and this class both use.
                When launch_server is False, must be set to match the port specified in language_server/1 of the running SWI Prolog process.

            password: The password to use for connecting to the SWI Prolog process. This is to prevent malicious users from connecting to the server since it can run arbitrary code.  Allowing the server to generate a strong password by using None is recommended.
                When launch_server is True, None (default) automatically generates a strong password using a uuid. Other values specify the password to use.
                When launch_server is False, must be set to match the password specified in language_server/1 of the running SWI Prolog process.

            unix_domain_socket: None (default) use localhost TCP/IP for communication with the SWI Prolog process. Otherwise (only on Unix) is the fully qualified path and filename of the Unix Domain Socket to use. If the file exists when the server is launched, it will be deleted. Some considerations when choosing the value to use:

                - The directory containing the file must grant the user (and ideally only that user) running the application the ability to create and delete files created within it.
                - For security reasons, the filename should not be predictable.
                - The path must be below 92 *bytes* long (including null terminator) to be portable according to the Linux documentation.
                - If neither the Python process or the Prolog process exit cleanly (e.g. they are killed by the debugger) the socket file will be left on disk.

            query_timeout_seconds: None (default) set the default timeout for all queries to be infinite (this can be changed on a per query basis). Other values set the default timeout in seconds.

            pending_connection_count: Set the default number of pending connections allowed on the server. Since the server is only connected to by your application and is not a server, this value should probably never be changed unless your application is creating new PrologThread objects at a very high rate.
                When launch_server is True, None uses the default (5) and other values set the count.
                When launch_server is False, ignored.

            halt_on_connection_failure: True (default) halt the launched server (i.e. execute prolog `halt(abort).` and kill the process) if a started `PrologThread` class or a thread running in the server terminates unexpectedly. In both cases, halting the server is a good course of action since the system is in an unstable state or your application Python process has been killed. Setting this value to False is only recommended for testing or unusual debugging scenarios.  Ignored if launch_server is False.

            output_file_name: Provide the file name for a file to redirect all Prolog output (STDOUT and STDERR) to. Used for debugging or gathering a log of Prolog output. None outputs all Prolog output to the Python logging infrastructure using the 'swiplserver' log.

            server_traces: Only used in unusual debugging circumstances. True turns on all tracing output from Prolog `language_server/1` server (i.e. runs `debug(prologServer(_)).` in Prolog). Since these are Prolog traces, where they go is determined by output_file_name.
        """
        self._port = port
        self._password = password
        self._process = None
        self._stderr_reader = None
        self._stdout_reader = None
        self._query_timeout = query_timeout_seconds
        self.pending_connections = pending_connection_count
        self._halt_on_connection_failure = halt_on_connection_failure
        self._output_file = output_file_name
        self._unix_domain_socket = unix_domain_socket
        self._server_traces = server_traces
        self._launch_server = launch_server

        # Becomes true if a PrologThread class encounters a situation
        # where the server is clearly shutdown and thus more communication
        # will not work and probably hang.
        self.connection_failed = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.stop()

    def __del__(self):
        self.stop()

    def stop(self, kill=False):
        """
        Stop the SWI Prolog process and wait for it to exit if it has been launched by using launch_server = True on `PrologServer` creation.

        Does nothing if launch_server is False.

        Args:
            kill: False (default) connect to the server and ask it to halt (i.e. Prolog `halt(abort)`) which will execute an orderly shutdown of Prolog.  True uses the Python subprocess.kill() command which will terminate it immediately. Note that if PrologServer.connection_failed is set to true (due to a failure that indicates the server will not respond), subprocess.kill() will be used regardless of this setting.
        """
        if self._process:
            if kill is True or self.connection_failed:
                _log.debug("Killing Prolog process...")
                self._process.kill()
                _log.debug("Killed Prolog process.")
            else:
                with self.create_thread() as prologThread:
                    prologThread.halt_server()

            result = self._process.wait()

            # Need to get rid of the unix domain socket file
            if self._unix_domain_socket:
                try:
                    os.remove(self._unix_domain_socket)
                except Exception as error:
                    pass
            self._process = None

    def start(self):
        """
        Start a new SWI Prolog process associated with this class using the settings from `PrologServer.__init__()`. If launch_server is False, does nothing..

        To create the SWI Prolog process, 'swipl' must be on the system path. Manages the lifetime of the process it creates, ending it on `PrologServer.close()`.

        Raises:
             PrologLaunchError: The SWI Prolog process was unable to be launched. Often indicates that `swipl` is not in the system path.
        """
        if self._launch_server:
            prologPath = join(os.path.dirname(os.path.realpath(__file__)), "language_server.pl")
            options = ["halt_on_connection_failure({})".format("true" if self._halt_on_connection_failure else "false")]
            if self.pending_connections is not None:
                options.append("pending_connections({})".format(str(self.pending_connections)))
            if self._query_timeout is not None:
                options.append("query_timeout({})".format(str(self._query_timeout)))
            if self._password is not None:
                options.append("password('{}')".format(str(self._password)))
            if self._output_file is not None:
                options.append("write_output_to_file('{}')".format(self._output_file))
                _log.debug("Writing all Prolog output to file: %s", self._output_file)
            if self._port is not None:
                options.append("port({})".format(str(self._port)))
            if self._unix_domain_socket is not None:
                options.append("unix_domain_socket('{}')".format(self._unix_domain_socket))

            launchArgs = ["swipl", "--quiet", "-s", prologPath, "-g",
                          "language_server([write_connection_values(true), run_server_on_thread(false), ignore_sig_int(true), {}])".format(",".join(options)),
                          "-t", "halt"]
            _log.debug("PrologServer launching swipl: %s", launchArgs)
            self._process = subprocess.Popen(launchArgs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Add STDERR reader immediately so we can see errors printed out
            self._stderr_reader = _NonBlockingStreamReader(self._process.stderr)

            # Now read the data that Prolog sends about how to connect
            if self._unix_domain_socket is None:
                portString = self._process.stdout.readline().decode()
                if portString == '':
                    raise PrologLaunchError("no port found in stdout")
                else:
                    serverPortString = portString.rstrip('\n')
                    self._port = int(serverPortString)
                    _log.debug("Prolog server port: %s", self._port)

            passwordString = self._process.stdout.readline().decode()
            if passwordString == '':
                raise PrologLaunchError("no password found in stdout")
            else:
                self._password = passwordString.rstrip('\n')

            # Now that we are done reading, we can add the STDOUT Reader
            self._stdout_reader = _NonBlockingStreamReader(self._process.stdout)

            if self._server_traces:
                with self.create_thread() as prologThread:
                    prologThread.query("debug(prologServer(_))")

    def create_thread(self):
        """
        Create a new `PrologThread` instance for this server.


        Examples:
            Using with the Python `with` statement is recommended:

                with PrologServer() as server:
                    with server.create_thread() as prolog_thread:
                        # Your code here

        Returns:
            A `PrologThread` instance.
        """
        return PrologThread(self)

    def process_id(self):
        """Retrieve the operating system process id of the SWI Prolog process that was launched by this class.

        Returns:
             None if the value of launch_server passed to `PrologServer` is False or if `PrologServer.start()` has not yet been called. Otherwise return the operating system process id.
        """
        if self._process is not None:
            return self._process.pid
        else:
            return None

    @staticmethod
    def unix_domain_socket_file(directory: str):
        """
        Creates a non-predictable Filename 36 bytes long suitable for using in the unix_domain_socket argument of the `PrologServer` constructor. Appends it to directory.

        Note that Python's gettempdir() function generates paths which are often quite large on some platforms and thus (at the time of this writing) is not suitable for use as the directory. The recommendation is to create a custom directory in a suitably short path (see notes below on length) in the filesystem and use that as directory. Ensure that the permissions for this folder are set as described below.
        Args:
            directory: The fully qualified directory the file name will be appended to. Note that:

                - The directory containing the file must grant the user running the application (and ideally only that user) the ability to create and delete files created within it.
                - The total path (including the 36 bytes used by the file) must be below 92 *bytes* long (including null terminator) to be portable according to the Linux documentation.
        Returns:
            A fully qualified path to a file in directory.
        """
        filename = "sock" + str(uuid.uuid4().hex)
        return os.path.join(directory, filename)


class PrologThread:
    def __init__(self, prolog_server: PrologServer):
        """
        Initialize a PrologThread instance for running Prolog queries on a single, consistent thread in prolog_server (does not create a thread in Python).

        Each `PrologThread` class represents a single, consistent thread in prolog_server that can run queries using `PrologThread.query()` or `PrologThread.query_async()`. Queries on a single `PrologThread` will never run concurrently.

        However, running queries on more than one `PrologThread` instance will run concurrent Prolog queries and all the multithreading considerations that that implies.

        Usage:
            All of these are equivalent and automatically start the server:

            PrologThread instances can be created and started manually:

                server = PrologServer()
                prolog_thread = PrologThread(server)
                prolog_thread.start()
                # Your code here

            Or (recommended) started automatically using the Python `with` statement:

                with PrologServer() as server:
                    with PrologThread(server) as prolog_thread:
                        # Your code here

            Or using the handy helper function:

                with PrologServer() as server:
                    with server.create_thread() as prolog_thread:
                        # Your code here
        """
        self._prolog_server = prolog_server
        self._socket = None
        self.communication_thread_id = None
        self.goal_thread_id = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exception_type, exception_value, exception_traceback):
        self.stop()

    def __del__(self):
        self.stop()

    def start(self):
        """
        Connect to the `prolog_server` specified in `PrologThread` and start a new thread in it. Launch the server if `launch_server` is `True` on that object. Does not start a Python thread.

        Does nothing if the thread is already started.

        Raises:
            `PrologLaunchError` if `launch_server` is `False` and the password does not match the server.

            Various socket errors if the server is not running or responding.
        """
        if self._socket is not None:
            return

        if self._prolog_server.process_id() is None:
            self._prolog_server.start()

        # create an ipv4 (AF_INET) socket object using the tcp protocol (SOCK_STREAM)
        if self._prolog_server._unix_domain_socket:
            prologAddress = self._prolog_server._unix_domain_socket
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        else:
            prologAddress = ('127.0.0.1', self._prolog_server._port)
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        _log.debug("PrologServer connecting to Prolog at: %s", prologAddress)
        self._socket.connect(prologAddress)

        # Send the password as the first message
        self._send("{}".format(self._prolog_server._password))
        result = self._receive()
        jsonResult = json.loads(result)
        if prolog_name(jsonResult) != "true":
            raise PrologLaunchError("Failed to accept password: {}".format(json_to_prolog(jsonResult)))
        else:
            threadTerm = prolog_args(jsonResult)[0][0][0]
            self.communication_thread_id = prolog_args(threadTerm)[0]
            self.goal_thread_id = prolog_args(threadTerm)[1]

    def stop(self):
        """
        Do an orderly stop of the thread running in the Prolog process associated with this object and close the connection to the `prolog_server` specified in `PrologThread`.

        If an asynchronous query is running on that thread, it is halted using Prolog's `abort`.
        """
        if self._socket:
            if not self._prolog_server.connection_failed:
                try:
                    # attempt a clean exit so the server doesn't shutdown
                    self._send("close.\n")
                    self._return_prolog_response()
                except OSError as error:
                    pass

            self._socket.close()
            self._socket = None

    def query(self, value: str, query_timeout_seconds: float = None):
        """
        Run a Prolog query and wait to return all results (as if run using Prolog `findall/3`) or optionally time out.

        Calls `PrologServer.start()` and `PrologThread.start()` if either is not already started.

        The query is run on the same Prolog thread every time, emulating the Prolog top level. Other than using a timeout, closing the connection is the only way to cancel the goal.  To run a cancellable goal that keeps the thread alive, use `PrologThread.query_async()`.

        Args:
            value: A Prolog query to execute as a string, just like you would run on the Prolog top level. e.g. `"member(X, [1, 2]), X = 2"`.
            query_timeout_seconds: `None` uses the query_timeout_seconds set in the prolog_server object passed to `PrologThread`.

        Raises:
            `PrologQueryTimeoutError` if the query timed out.

            `PrologConnectionFailedError` if the query thread has unexpectedly exited. The server will no longer be listening after this exception.

            `PrologError` for all other exceptions that occurred when running the query in Prolog.

        Returns:
            False: The query failed.
            True: The query succeeded once with no free variables.
            list: The query succeeded once with free variables or more than once with no free variables. There will be an item in the list for every answer. Each item will be:

                - `True` if there were no free variables
                - A `dict` if there were free variables. Each key will be the name of a variable, each value will be the JSON representing the term it was unified with.
        """
        if self._socket is None:
            self.start()
        value = value.strip()
        value = value.rstrip("\n.")
        timeoutString = "_" if query_timeout_seconds is None else str(query_timeout_seconds)
        self._send("run(({}), {}).\n".format(value, timeoutString))
        return self._return_prolog_response()

    def query_async(self, value: str, find_all: bool = True, query_timeout_seconds: float = None):
        """ Start a Prolog query and return immediately unless a previous query is still running. In that case, wait until the previous query finishes before returning.

        Calls `PrologServer.start()` and `PrologThread.start()` if either is not already started.

        Answers are retrieved using `PrologThread.query_async_result()`. The query can be cancelled by calling `PrologThread.cancel_query_async()`. The query is run on the same Prolog thread every time, emulating the Prolog top level.

        Args:
            value: A Prolog query to execute as a string, just like you would run on the Prolog top level. e.g. `"member(X, [1, 2]), X = 2"`.
            find_all: `True` (default) will run the query using Prolog's `findall/3` to return a single answer when `PrologThread.query_async_result()` is called. `False` will return one answer per `PrologThread.query_async_result()` call.
            query_timeout_seconds: `None` uses the `query_timeout_seconds` set in the `prolog_server` object passed to `PrologThread`.

        Raises:
            `PrologConnectionFailedError` if the query thread has unexpectedly exited. The server will no longer be listening after this exception.

            `PrologError` if an exception occurs in Prolog when parsing the goal.

            Any exception that happens when running the query is raised when calling `PrologThread.query_async_result()`

        Returns:
            `True`
        """
        if self._socket is None:
            self.start()

        value = value.strip()
        value = value.rstrip("\n.")
        timeoutString = "_" if query_timeout_seconds is None else str(query_timeout_seconds)
        findallResultsString = "true" if find_all else "false"
        self._send("run_async(({}), {}, {}).\n".format(value, timeoutString, findallResultsString))
        self._return_prolog_response()

    def cancel_query_async(self):
        """
        Attempt to cancel a query started with `PrologThread.query_async()` in a way that allows further queries to be run on this `PrologThread` afterwards.

        If there is a query running, injects a Prolog `throw(cancel_goal)` into the thread the query is running on. Does not inject Prolog `abort/0` because this would kill the thread and we want to keep the thread alive for future queries.  This means it is a "best effort" cancel since the exception can be caught by your Prolog code. `cancel_query_async()` is guaranteed to either raise an exception (if there is no query or pending results from the last query), or safely attempt to stop the last executed query.

        To guaranteed that a query is cancelled, call `PrologThread.stop()` instead.

        It is not necessary to determine the outcome of `cancel_query_async()` after calling it. Further queries can be immediately run after calling `cancel_query_async()`. They will be run after the current query stops for whatever reason.

        If you do need to determine the outcome or determine when the query stops, call `PrologThread.async_query_result(wait_timeout_seconds = 0)`. Using `wait_timeout_seconds = 0` is recommended since the query might have caught the exception or still be running.  Calling `PrologThread.async_query_result()` will return the "natural" result of the goal's execution. The "natural" result depends on the particulars of what the code actually did. The return value could be one of:

        - Raise `PrologQueryCancelledError` if the goal was running and did not catch the exception. I.e. the goal was cancelled.
        - Raise `PrologQueryTimeoutError` if the query timed out before getting cancelled.
        - Raise `PrologError` (i.e. an arbitrary exception) if query hits another exception before it has a chance to be cancelled.
        - A valid answer if the query finished before being cancelled.

        Note that you will need to continue calling `PrologThread.async_query_result()` until you receive `None` or an exception to be sure the query is finished (see documentation for `PrologThread.async_query_result()`).

        Raises:
            `PrologNoQueryError` if there was no query running and no results that haven't been retrieved yet from the last query.

            `PrologConnectionFailedError` if the query thread has unexpectedly exited. The server will no longer be listening after this exception.

        Returns:
            `True`. Note that this does not mean the query was successfully cancelled (see notes above).
        """
        self._send("cancel_async.\n")
        self._return_prolog_response()

    def query_async_result(self, wait_timeout_seconds: float = None):
        """ Get results from a query that was run using `PrologThread.query_async()`.

        Used to get results for all cases: if the query terminates normally, is cancelled by `PrologThread.cancel_query_async()`, or times out. Each call to `query_async_result()` returns one result and either `None` or raises an exception when there are no more results.  Any raised exception except for `PrologResultNotAvailableError` indicates there are no more results. If `PrologThread.query_async()` was run with `find_all == False`, multiple `query_async_result()` calls may be required before receiving the final None or raised exception.

        Examples:
            - If the query succeeds with N answers: `query_async_result()` calls 1 to N will receive each answer, in order, and `query_async_result()` call N+1 will return `None`.
            - If the query fails (i.e. has no answers): `query_async_result()` call 1 will return False and `query_async_result()` ` call 2 will return `None`.
            - If the query times out after one answer, `query_async_result()` call 1 will return the first answer and `query_async_result()` call 2 will raise `PrologQueryTimeoutError`.
            - If the query is cancelled after it had a chance to get 3 answers: `query_async_result()` calls 1 to 3 will receive each answer, in order, and `query_async_result()` call 4 will raise `PrologQueryCancelledError`.
            - If the query throws an exception before returning any results, `query_async_result()` call 1 will raise `PrologError`.

        Note that, after calling `PrologThread.cancel_query_async()`, calling `query_async_result()` will return the "natural" result of the goal's execution. See documentation for `PrologThread.cancel_query_async()` for more information.

        Args:
            wait_timeout_seconds: Wait `wait_timeout_seconds` seconds for a result, or forever if `None`. If the wait timeout is exceeded before a result is available, raises `PrologResultNotAvailableError`.

        Raises:
            `PrologNoQueryError` if there is no query in progress.

            `PrologResultNotAvailableError` if there is a running query and no results were available in `wait_timeout_seconds`.

            `PrologQueryCancelledError` if the next answer was the exception caused by `PrologThread.cancel_query_async()`. Indicates no more answers.

            `PrologQueryTimeoutError` if the query timed out generating the next answer (possibly in a race condition before getting cancelled).  Indicates no more answers.

            `PrologError` if the next answer is an arbitrary exception thrown when the query was generating the next answer. This can happen after `PrologThread.cancel_query_async()` is called if the exception for cancelling the query is caught or the code hits another exception first.  Indicates no more answers.

            `PrologConnectionFailedError` if the query thread unexpectedly exited. The server will no longer be listening after this exception.

        Returns:
            False: The query failed.
            True: The next answer is success with no free variables.
            list: The query succeeded once with free variables or more than once with no free variables. There will be an item in the list for every answer. Each item will be:

                - `True` if there were no free variables
                - A `dict` if there were free variables. Each key will be the name of a variable, each value will be the JSON representing the term it was unified with.
        """
        timeoutString = "-1" if wait_timeout_seconds is None else str(wait_timeout_seconds)
        self._send("async_result({}).\n".format(timeoutString))
        return self._return_prolog_response()

    def halt_server(self):
        """
        Perform an orderly shutdown of the server using Prolog `halt(abort)` and end the Prolog process.

        This is called automatically by `PrologServer.close()` and when a `PrologServer` instance is used in a Python `with` statement.
        """
        self._send("quit.\n")
        # wait for the answer to make sure it was processed
        result = self._return_prolog_response()
        # Set this so the thread doesn't try to close down cleanly since the server is gone
        self._prolog_server.connection_failed = True

    # Returns:
    #   false/0: False
    #   true[[]]: True
    #   true[[], [], ...]: [True, True, ...]
    #   true[[...], [...], ...]: [{"var1": <json>}, {"var1": <json>}, {"var1": <json>}, {"var1": <json>}, ...]
    #   exception(no_more_results): None
    #
    # Raises:
    #   PrologConnectionFailedError if the connection failed
    #   PrologQueryTimeoutError if the query timed out
    #   PrologError if an exception not above is returned
    #   PrologNoQueryError if the user attempted to cancel and there was no query
    #   PrologQueryCancelledError if a query was cancelled and goals are trying to be retrieved
    #   PrologResultNotAvailableError if query_async_result is called with a timeout and the result is not available
    def _return_prolog_response(self):
        result = self._receive()
        jsonResult = json.loads(result)
        if prolog_name(jsonResult) == "exception":
            if jsonResult["args"][0] == "no_more_results":
                return None
            elif jsonResult["args"][0] == "connection_failed":
                self._prolog_server.connection_failed = True
                raise PrologConnectionFailedError(jsonResult)
            elif jsonResult["args"][0] == "time_limit_exceeded":
                raise PrologQueryTimeoutError(jsonResult)
            elif jsonResult["args"][0] == "no_query":
                raise PrologNoQueryError(jsonResult)
            elif jsonResult["args"][0] == "cancel_goal":
                raise PrologQueryCancelledError(jsonResult)
            elif jsonResult["args"][0] == "result_not_available":
                raise PrologResultNotAvailableError(jsonResult)
            else:
                raise PrologError(jsonResult)
        else:
            if prolog_name(jsonResult) == "false":
                return False
            elif prolog_name(jsonResult) == "true":
                answerList = []
                for answer in prolog_args(jsonResult)[0]:
                    if len(answer) == 0:
                        answerList.append(True)
                    else:
                        answerDict = {}
                        for answerAssignment in answer:
                            # These will all be =(Variable, Term) terms
                            answerDict[prolog_args(answerAssignment)[0]] = prolog_args(answerAssignment)[1]
                        answerList.append(answerDict)
                if answerList == [True]:
                    return True
                else:
                    return answerList

            return jsonResult

    def _send(self, value):
        value = value.strip()
        value = value.rstrip("\n.")
        value += ".\n"
        _log.debug("PrologServer send: %s", value)
        utf8Value = value.encode("utf-8")
        msgHeader = "{}.\n".format(str(len(utf8Value))).encode("utf-8")
        self._socket.sendall(msgHeader)
        self._socket.sendall(utf8Value)

    #  The format of sent and received messages is identical: `<stringByteLength>.\n<stringBytes>.\n`. For example: `7.\nhello.\n`:
    #  - `<stringByteLength>` is the number of bytes of the string to follow (including the `.\n`), in human readable numbers, such as `15` for a 15 byte string. It must be followed by `.\n`.
    #  - `<stringBytes>` is the actual message string being sent, such as `run(atom(a), -1).\n`. It must always end with `.\n`. The character encoding used to decode and encode the string is UTF-8.
    # heartbeats (the "." character) can be sent by some commands to ensure the client is still listening.  These are discarded.
    def _receive(self):
        # Look for the response
        amount_received = 0
        amount_expected = None
        bytesReceived = bytearray()
        sizeBytes = bytearray()

        data = None
        while amount_expected is None or amount_received < amount_expected:
            headerData = self._socket.recv(4096)
            if amount_expected is None:
                # Start / continue reading the string length
                # Ignore any leading "." characters because those are heartbeats
                for index in range(0, len(headerData)):
                    item = headerData[index]
                    # String length ends with '.\n' characters
                    if item == 46:
                        # ignore "."
                        continue
                    if item == 10:
                        # convert all the characters we've received so far to a number
                        stringLength = ""
                        for code in sizeBytes:
                            stringLength += chr(code)
                        amount_expected = int(stringLength)
                        # And consume the rest of the stream
                        data = bytearray(headerData[index + 1:])
                        break
                    else:
                        sizeBytes.append(item)
                if data is None:
                    continue
            else:
                data = headerData

            amount_received += len(data)
            bytesReceived += data

        finalValue = bytesReceived.decode("utf-8")
        _log.debug("PrologServer receive: %s", finalValue)
        return finalValue


def is_prolog_functor(json_term):
    """
    True if json_term is Prolog json representing a Prolog functor (i.e. a term with zero or more arguments).  See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    return isinstance(json_term, dict) and "functor" in json_term and "args" in json_term


def is_prolog_list(json_term):
    """
    True if json_term is Prolog json representing a Prolog list.  See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    return isinstance(json_term, list)


def is_prolog_variable(json_term):
    """
    True if json_term is Prolog json representing a Prolog variable.  See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    return isinstance(json_term, str) and (json_term[0].isupper() or json_term[0] == "_")


def is_prolog_atom(json_term):
    """
    True if json_term is Prolog json representing a Prolog atom.  See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    return isinstance(json_term, str) and not is_prolog_variable(json_term)


def prolog_name(json_term):
    """
    Return the atom (if json_term is an atom), variable (if a variable) or functor name of json_term.  json_term must be in the Prolog json format. See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    if is_prolog_atom(json_term) or is_prolog_variable(json_term):
        return json_term
    else:
        return json_term["functor"]


def prolog_args(json_term):
    """
    Return the arguments from json_term if json_term is in the Prolog json format. See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    return json_term["args"]


def quote_prolog_identifier(identifier: str):
    """
    Surround a Prolog identifier with '' if Prolog rules require it.
    """
    if not is_prolog_atom(identifier):
        return identifier
    else:
        mustQuote = is_prolog_atom(identifier) and \
                    (
                        len(identifier) == 0 or
                        not identifier[0].isalpha() or
                        # characters like _ are allowed without quoting
                        not identifier.translate({ord(c): '' for c in '_'}).isalnum()
                        )

        if mustQuote:
            return "'{}'".format(identifier)
        else:
            return identifier


def json_to_prolog(json_term):
    """
    Convert json_term from the Prolog json format to a string that represents the term in the Prolog language. See `swiplserver.prologserver` for documentation on the Prolog json format.
    """
    if is_prolog_functor(json_term):
        argsString = [json_to_prolog(item) for item in prolog_args(json_term)]
        return "{}({})".format(quote_prolog_identifier(prolog_name(json_term)), ", ".join(argsString))
    elif is_prolog_list(json_term):
        listString = [json_to_prolog(item) for item in json_term]
        return "[{}]".format(", ".join(listString))
    else:
        # must be an atom, number or variable
        return str(quote_prolog_identifier(json_term))


# Helper to print all data from STDERR and STDOUT as it gets printed
# Code inspired by http://eyalarubas.com/python-subproc-nonblock.html
class _NonBlockingStreamReader:
    def __init__(self, stream):
        def _print_output(stream):
            while True:
                line = stream.readline()
                if line:
                    _log.critical("Prolog: {}".format(line.decode().rstrip()))

        self._stream = stream
        self._thread = Thread(target = _print_output, args = (self._stream, ))
        self._thread.daemon = True
        self._thread.start()


_log = logging.getLogger("swiplserver")


if __name__ == '__main__':
    # This is not guaranteed to create a socket that is portable, but since
    # we are testing we are OK with it.
    socketPath = os.path.dirname(os.path.realpath(__file__))
