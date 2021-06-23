:- module(language_server, [language_server/1, stop_language_server/1]).

/** <module> Prolog Language Server
    Author:        Eric Zinda
    E-mail:        ericz@inductorsoftware.com
    WWW:           http://www.inductorsoftware.com
    Copyright (c)  2021, Eric Zinda

The SWI Prolog Language Server is designed to enable "embedding" SWI Prolog into just about any programming language (Python, Go, C#, etc) in a straightforward way. It is designed for scenarios that need to use SWI Prolog as a local implementation detail of another language. Think of it as running SWI Prolog "like a library". It can support any programming language that can launch processes, read their STDOUT pipe, and send and receive JSON over TCP/IP. A Python 3.x library is provided.

Key features of the server:
    - Simulates a familiar Prolog "top level" (i.e. the interactive prompt you get when running Prolog: "?-").
    - Always runs queries from a connection on a consistent, single thread for that connection. The application itself can still be multi-threaded by running queries that use the multi-threading Prolog predicates or by opening more than one connection.
    - Runs as a separate dedicated *local* Prolog process to simplify integration (vs. using the C-level SWI Prolog interface). The process is launched and managed by a specific running client (e.g. Python) program.
    - Communicates using sockets and JSON encoded as UTF-8 to allow it to work on any platform supported by SWI Prolog. For security reasons, only listens on TCP/IP localhost or Unix Domain Sockets and requires (or generates depending on the options) a password to open a connection.
    - Has a lightweight text-based message format with only 6 commands: run synchronous query, run asynchronous query, retrieve asynchronous results, cancel asynchronous query, close connection and terminate the session.
    - Communicates answers using JSON, a well-known data format supported by most languages natively or with generally available libraries.


The server can be used in two different modes:
    - *Embedded mode*: This is the main use case for the server. The user uses a library (just like any other library in their language of choice). That library integrates the language server as an implementation detail by launching the SWI Prolog process, connecting to it, and wrapping the protocol with a language specific interface.
    - *Standalone mode*: The user still uses a library as above, but launches SWI Prolog independently of the language. The client language library connects to that process. This allows the user to see, interact with, and debug the Prolog process while the library interacts with it.

Note that the language server is related to the pengines library, but where the pengines library is focused on a client/server, multi-tenet, sandboxed environment, the language server is local, single tenet and unconstrained. Thus, when the requirement is to embed Prolog within another programming language "like a library", it can be a good solution for exposing the full power of Prolog with low integration overhead.

## Installation Steps for Any Language
In order to use the language server with any programming language:

    1. Install SWI Prolog itself on the machine the application will run on.
    2. Ensure that the system path includes a path to the `swipl` executable from that installation.
    3. Make sure the application (really the user that launches the application) has permission to launch the SWI Prolog process.
    4. Install (or write!) the library you'll be using to access the language server in your language of choice.

The first two should be straightforward.

For #3, your application will need to have permission to launch the SWI Prolog process. Unless your system is unusually locked down, this should be allowed by default.  If not, you'll need to set the appropriate permissions to allow this.

## Prolog Language Differences from the Top Level

The language server is designed to act like using the "top level" prompt of SWI Prolog itself (i.e. the "?-" prompt).  If you've built the Prolog part of your application by loading code, running it and debugging it using the normal SWI Prolog top level, integrating it with your native language should be straightforward: simply run the commands you'd normally run on the top level, but now run them using the query APIs provided by the library. Those APIs will allow you to send the exact same text to Prolog and they should execute the same way.

While the query functionality of the language server does run on a thread, it will always be the *same* thread, and, if you use a single connection, it will only allow queries to be run one at a time, just like the top level. Of course, the queries you send can launch threads, just like the top level, so you are not limited to a single threaded application. There are a few differences from the top level, however:

    - Normally, the SWI Prolog top level runs all user code in the context of a built-in module called "user", as does the language server. However, the top level allows this to be changed using the module/1 predicate. This predicate has no effect in the language server.
    - Predefined streams like user_input/0 are initially bound to the standard operating system I/O streams (like STDIN) and, since the Prolog process is running invisibly, will obviously not work as expected. Those streams can be changed, however, by issuing commands using system predicates as defined in the SWI Prolog documentation.
    - Every connection to the language server runs in its own thread, so opening two connections from an application means you are running multithreaded code.

The basic rule to remember is: any predicates designed to interact with or change the default behavior of the top level itself probably won't have any effect.


## Embedding the Language Server Into a New Programming Language
The most common way to use the language server is to find a library that wraps and exposes it as a native part of another programming language such as Python. This section describes how to build one if there isn't yet a library for your language.  To do this, you'll need to familiarize yourself with the server protocol as described in the `language_server/1` documentation. However, to give an idea of the scope of work required, below is a typical interaction done (invisibly to the user) in the implementation of any programming language library:

     1. Launch the SWI Prolog process using a command like `swipl --quiet -g language_server([write_connection_values(true), halt_on_connection_failure(true), ignore_sig_int(true), run_server_on_thread(false)]) -t halt` To work, the `swipl` Prolog executable will need to be on the path or specified in the command. This launches the server and ensures that the process exits when the connections are closed (or fail).  `run_server_on_thread(false)` is required otherwise the server will run on a thread and the process will exit immediately. See documentation for all of the options in the `language_server/1` documentation.
     2. Read the SWI Prolog STDOUT to retrieve the TCP/IP port and password. They are sent in that order, delimited by '\n'.

    Now the server is started. To create a connection:

     3. Use the language's TCP/IP sockets library to open a socket on the specified port of localhost (or on the specified Unix Domain Socket) and send the password as a message (the message format is described  in the `language_server/1` documentation).
     4. Listen on the socket for a response message of `true([[threads(Comm_Thread_ID, Goal_Thread_ID)]])` indicating successful creation of the connection.  `Comm_Thread_ID` and `Goal_Thread_ID` are the two threads that are used for the connection. They are sent solely for monitoring and debugging purposes.

 Now the connection is established. To run queries and shutdown:

     5. Any of the messages described in the `language_server/1` documentation can now be sent to run queries and retrieve their answers. For example, send the message `run(atom(a), -1)` to run the synchronous query `atom(a)` with no timeout and wait for the response message. It will be `true([[]])`.
     6. Shutting down the connection is accomplished by sending the message `close`, waiting for the response message of `true([[]])`, and then closing the socket using the socket API of the language.  If the socket is closed (or fails) before the `close` message is sent, the default behavior of the servier is to terminate the SWI Prolog process using `halt(abort)` to avoid leaving the process around.  This is to support scenarios where the user is running and halting their language debugger without cleanly exiting.
     7. Shutting down the launched server is accomplished by sending the `quit` message and waiting for the response message of `true([[]])`. This will cause an orderly shutdown and exit of the process by issuing the Prolog `halt(abort)` command.

The format of messages is described in the documentation for `language_server/1`.

Other notes about creating a new library to communicate with the language server:
- Use the `debug/1` predicate described in the `language_server/1` documentation to turn on debug tracing. It can really speed up debugging.
- Read the STDOUT and STDERR output of the SWI Prolog process and output them to the debugging console of the native language to help users debug their Prolog application.

## Standalone Mode: Debugging Prolog Code Used in an Application
When using the language server from another language, debugging the Prolog code itself can often be done by viewing traces from the Prolog native `writeln/1` or `debug/3` predicates and viewing their output in the debugger of the native language used.  Sometimes an issue occurs deep in an application and a way to run the application in the native language while setting breakpoints and viewing traces in Prolog itself is the best approach. Standalone mode is designed for this scenario.

As the language server is a multithreaded application, debugging the running code requires using the multithreaded debugging features of SWI Prolog as described in the section on "Debugging Threads" in the SWI Prolog documentation. A typical flow for standalone mode is:

    1. Launch SWI Prolog and call the `language_server/1` predicate specifying a port and password. Use the `tdebug/0` predicate to set all threads to debugging mode like this: `tdebug, language_server(port(4242), password(debugnow))`.
    2. Set the port and password in the initialization API in the native language being used.
    3. Launch the application and go through the steps to reproduce the issue.


At this point, all of the multi-threaded debugging tools in SWI Prolog are available for debugging the problem. If the issue is an unhandled or unexpected exception, the exception debugging features of SWI Prolog can be used to break on the exception and examine the state of the application.  If it is a logic error, breakpoints can be set to halt at the point where the problem appears, etc.

Note that, while using a library to access Prolog will normally end and restart the process between runs of the code, running the server standalone doesn't clear state between launches of the application.  You'll either need to relaunch between runs or build your application so that it does the initialization at startup.
*/

/**
  language_server(+Options:list) is semidet.

Starts a Prolog language server using Options. The server is normally started automatically by a library built for a particular programming language, but starting manually can be useful when debugging Prolog code in some scenarios. See the documentation on "Standalone Mode" for more information.

Once started, the server listens for TCP/IP or Unix Domain Socket connections and authenticates them using the password provided (or generated) before processing any messages.  The messages processed by the server are described below.

For debugging, the server outputs traces using the `debug/3` predicate so that the server operation can be observed by using the `debug/1` predicate before starting it. Run the following commands to see them:

- `debug(prologServer(protocol))`: Traces protocol messages to show the flow of commands and connections.  It is designed to avoid filling the screen with large queries and results to make it easier to read.
- `debug(prologServer(query))`: Traces messages that involve each query and its results. Therefore it can be quite verbose depending on the query.

## Options
Options is a list containing any combination of the following options:

- unix_domain_socket(+Unix_Domain_Socket_Path_And_File)
If set, Unix Domain Sockets will be used as the way to communicate with the server. `Unix_Domain_Socket_Path_And_File` specifies the fully qualified path and filename to use for the socket.
    - If the path is not an absolute path, an exception will be thrown.
    - If the file exists when the server starts it will be deleted.
    - The Prolog process will attempt to create and, if Prolog exits cleanly, delete this file when the server closes.  This means the directory must have the appropriate permissions to allow the Prolog process to do so.
    - For security reasons, the filename should not be predictable and the directory it is contained in should have permissions set so that files created are only accessible to the current user.
    - The path must be below 92 *bytes* long (including null terminator) to be portable according to the Linux documentation


- port(?Port)
The TCP/IP socket port to bind to on localhost. This option is ignored if the `unix_domain_socket/1` option is set. Port is either a legal TCP/IP port number (integer) or a term `Port`. The port may be a variable, causing the system to select a free port and unify the variable with the selected port as in `tcp_bind/2`. If the option `write_connection_values(true)` is set, the selected port is output to STDOUT followed by `\n` on startup to allow the client language library to retrieve it.

- password(?Password)
The password required for a connection. If not specified (recommended), the server will generate one as a Prolog string type since Prolog atoms are globally visible. Be sure to not convert to an atom for this reason.  If the option `write_connection_values(true)` is set, the password is output to STDOUT followed by `\n` on startup to allow the client language library to retrieve it. This is the recommended way to integrate the server with a language as it avoids including the password as source code (which could then be discovered). This option is only included so that a known password can be supplied for when the server is running in "Standalone Mode".  `Password` may be a variable, causing the system to unify it with the created password.

- pending_connections(?Count)
Sets the number of pending connections allowed for the server as in `tcp_listen/2`. `Count` may be a variable, causing the system to unify it with the default. The default is `5`.

- query_timeout(?Seconds)
Sets the length of time a query is allowed to run before it is cancelled. `Seconds` may be a variable, causing the system to unify it with the default. The default is no timeout (`-1`).

- halt_on_connection_failure(?Halt)
Determines whether the Prolog process should halt using `halt(abort)` if there is a connection failure (i.e. the client terminates without sending a `close` message). This is so that stopping the debugger doesn't leave the process around.  However, when running as a standalone server this may not be the desired behavior. Note that this setting will also cause the Prolog process to halt if there is an unexpected exception in the threads used to communicate or run goals. This should never happen except under exceptional circumstances (out of memory, etc). `Halt` may be a variable, causing the system to unify it with the default. The default is `false`.

- run_server_on_thread(?Run_Server_On_Thread)
Determines whether `language_server/1` runs in the background on its own thread or doesn't complete until the server shuts down.  Must be set to `false` when launched by a language library so that the SWI Prolog process doesn't immediately exit.  `Run_Server_On_Thread` may be a variable, causing the system to unify it with the default. The default is `true`.

- server_thread(?Server_Thread)
Specifies or retrieves the name of the thread the server will run on if `run_server_on_thread(true)`. If `Server_Thread` is a variable, it is unified with a generated name.

- ignore_sig_int(?Ignore_Sig_Int)
Determines whether the process should the should ignore the `int` (i.e. Interrupt/SIGINT) signal. It is important to ignore this signal (`Ignore_Sig_Int == true`) when running in embedded mode because some languages (such as Python) use that signal during debugging and it will be passed to the client Prolog process and switch it into the debugger. When running in standalone mode, it is OK to leave enabled (`Ignore_Sig_Int == false`).  `Ignore_Sig_Int` may be a variable, causing the system to unify it with the default. The default is `false`.

- write_connection_values(?Write_Connection_Values)
Determines whether the server writes the port and password to STDOUT as it initializes. Used by language libraries to retrieve this information for connecting. `Write_Connection_Values` may be a variable, causing the system to unify it with the default. The default is `false`.

- writeOutputToFile(+File)
Redirects STDOUT and STDERR to the file specified.  Useful for debugging the server when it is being used in embedded mode.

## Language Server Messages
The messages the server responds to are described below. A few things are true for all of them:

- Every connection is in its own separate thread. Opening more than one connection means the code is running concurrently.
- Closing the socket without sending `close` and waiting for a response will halt the process depending on how the server was started. This is so that stopping a debugger doesn't leave the  process orphaned.
- All messages are request/response messages. After sending, there will be exactly one response from the server.
- Timeout in all of the commands is in seconds. Sending a variable (e.g. `_`) or `-1` means no timeout.
- All queries are run in the default module context of `user`. `module/1` has no effect.

### Language Server Message Format
Every language server message is a single valid Prolog term. Those that run queries have an argument which represents the query as a single term. To run several goals at once use `(goal1, goal2, ...)` as the goal term.

The format of sent and received messages is identical: =|<stringByteLength>.\n<stringBytes>.\n|=. For example: =|7.\nhello.\n|=:
 - =|<stringByteLength>|= is the number of bytes of the string to follow (including the =|.\n|=), in human readable numbers, such as `15` for a 15 byte string. It must be followed by =|.\n|=.
 - =|<stringBytes>|= is the actual message string being sent, such as =|run(atom(a), -1).\n|=. It must always end with =|.\n|=. The character encoding used to decode and encode the string is UTF-8.

To send a message to the server, send a message using the message format above to the localhost port or Unix Domain Socket that the server is listening on.  For example, to run the synchronous goal `atom(a)`, send the following message:
~~~
18.\nrun(atom(a), -1).\n<end of stream>
~~~
You will receive the response below on the receive stream of the same connection you sent on. The `run/2` and `run_async/3` messages are the only ones that send "heartbeat" characters (".") at the beginning of the response message, approximately 1 every 2 seconds. So, if the query takes 6 seconds for some reason, there will be three "." characters first:
~~~
...12\ntrue([[]]).\n
~~~

### Language Server Messages Reference

The full list of language server messages are described below.

#### run(Goal, Timeout)

Runs `Goal` on the connection's designated query thread. Stops accepting new commands until the query is finished and it has responded with the results.  If a previous query is still in progress, waits until the previous query finishes (discarding that query's results) before beginning the new query.

While it is waiting for the query to complete, sends a "." character *not* in message format, just as a single character, once every two seconds to proactively ensure that the client is alive. Those should be read and discarded by the client.

If a communication failure happens (during a heartbeat or otherwise), the connection is terminated, the query is aborted and the server optionally shuts down using `halt(abort)` (depending on Options).

When completed, sends a response message using the normal message format indicating the result.

Response:

|`true([Answer1, Answer2, ... ])` | The goal succeeded at least once. The response always includes all answers as if run with findall() (see run_async/3 below to get individual results back iteratively).  Each `Answer` is a list of the assignments of free variables in the answer. If there are no free variables, `Answer` is an empty list. |
|`false` | The goal failed. |
|`exception(time_limit_exceeded)` | The query timed out. |
|`exception(Exception)` | An arbitrary exception was not caught while running the goal. |
|`exception(connection_failed)` | The query thread unexpectedly exited. The server will no longer be listening after this exception. |

#### run_async(Goal, Timeout, Find_All)

Starts a Prolog query on the connection's designated query thread. Answers to the query, including exceptions, are retrieved afterwards by sending the `async_result/1` message (described below). The query can be cancelled by sending the `cancel_async/0` message. If a previous query is still in progress, waits until that query finishes (discarding that query's results) before responding.

If the socket closes before responding, the connection is terminated, the query is aborted and the server optionally shuts down using `halt(abort)` (depending on Options).

If it needs to wait for the previous query to complete, it will send heartbeat messages (see `run/2`) while it waits.  After it responds, however, it does not send more heartbeats. This is so that it can begin accepting new commands immediately after responding so the client.

`Find_All == true` means generate one response in `async_result/1` with all of the answers to the query (as in `run/2` above). `Find_All == false` generates a single response in `async_result/1` per answer.

Response:

|`true([[]])` | The goal was successfully parsed. |
|`exception(Exception)` | An error occurred parsing the goal. |
|`exception(connection_failed)` | The goal thread unexpectedly shut down. The server will no longer be listening after this exception. |


#### cancel_async
Attempt to cancel a query started with `run_async/3` in a way that allows further queries to be run on this Prolog thread afterwards.

If there is a goal running, injects a `throw(cancel_goal)` into the executing goal to attempt to stop the goal's execution. Begins accepting new commands immediately after responding. Does not inject `abort/0` because this would kill the connection's designated thread and the system is designed to maintain thread local data for the client. This does mean it is a "best effort" cancel since the exception can be caught.

`cancel_async` is guaranteed to either respond with an exception (if there is no query, or pending results from the last query), or safely attempt to stop the last executed query even if it has already finished.

To guaranteed that a query is cancelled, send `close` and close the socket.

It is not necessary to determine the outcome of `cancel_async/0` after sending it and receiving a response. Further queries can be immediately run. They will start after the current query stops.

However, if you do need to determine the outcome or determine when the query stops, send `async_result/1`. Using `Timeout = 0` is recommended since the query might have caught the exception or still be running.  Sending `async_result/1` will find out the "natural" result of the goal's execution. The "natural" result depends on the particulars of what the code actually did. The response could be:

|`exception(cancel_goal)` | The goal was running and did not catch the exception. I.e. the goal was cancelled. |
|`exception(time_limit_exceeded)` | The query timed out before getting cancelled. |
|`exception(Exception)` | They query hits another exception before it has a chance to be cancelled. |
| A valid answer | The query finished before being cancelled. |

Note that you will need to continue sending `async_result/1` until you receive an `exception(Exception)` message if you want to be sure the query is finished (see documentation for `async_result/1`).

Response:

| `true([[]])` | There is a query running or there are pending results for the last query. |
| `exception(no_query)` | There is no query (or pending results from a query) to cancel. |
| `exception(connection_failed)` | The connection has been unexpectedly shut down. The server will no longer be listening after this exception. |


#### async_result(Timeout)
Get results from a query that was run via `run_async/3`. Used to get results for all cases: if the query terminates normally, is cancelled by `cancel_async/0`, or times out. Each call responds with one result and, when there are no more results, responds with `exception(no_more_results)` or whatever exception stopped the query. Receiving any `exception` response except `exception(result_not_available)` means there are no more results. If `run_async/3` was run with `Find_All == false`, multiple `async_result/1` messages may be required before receiving the final exception.

Waits `Timeout` seconds for a result (`Timeout == -1` means forever). If the timeout is exceeded and no results are ready, sends `exception(result_not_available)`.

Some examples:

|If the query succeeds with N answers...                             | `async_result/1` messages 1 to N will receive each answer in order and `async_result/1` message N+1 will receive `exception(no_more_results)` |
|If the query fails (i.e. has no answers)...                         | `async_result/1` message 1 will receive `false` and `async_result/1` message 2 will receive `exception(no_more_results)` |
|If the query times out after one answer...                          | `async_result/1` message 1 will receive the first answer and `async_result/1` message 2 will receive `exception(time_limit_exceeded)` |
|If the query is cancelled after it had a chance to get 3 answers... | `async_result/1` messages 1 to 3 will receive each answer in order and `async_result/1` message 4 will receive `exception(cancel_goal)` |
|If the query throws an exception before returning any results...    | `async_result/1` message 1 will receive `exception(Exception)`|

Note that, after sending `cancel_async/0`, calling `async_result/1` will return the "natural" result of the goal's execution. The "natural" result depends on the particulars of what the code actually did since this is multi-threaded and there are race conditions. This is described more below in the response section and above in `cancel_async/0`.

Response:

|`true([Answer1, Answer2, ... ])` | The next answer from the query is a successful answer. Whether there are more than one `Answer` in the response depends on the `findall` setting. Each `Answer` is a list of the assignments of free variables in the answer. If there are no free variables, `Answer` is an empty list.|
|`false`| The query failed with no answers.|
|`exception(no_query)` | There is no query in progress.|
|`exception(result_not_available)` | There is a running query and no results were available in `Timeout` seconds.|
|`exception(no_more_results)` | There are no more answers and no other exception occurred. |
|`exception(cancel_goal)`| The next answer is an exception caused by `cancel_async/0`. Indicates no more answers. |
|`exception(time_limit_exceeded)`| The query timed out generating the next answer (possibly in a race condition before getting cancelled).  Indicates no more answers. |
|`exception(Exception)`| The next answer is an arbitrary exception. This can happen after `cancel_async/0` if the `cancel_async/0` exception is caught or the code hits another exception first.  Indicates no more answers. |
|`exception(connection_failed)`| The goal thread unexpectedly exited. The server will no longer be listening after this exception.|


#### close
Closes a connection cleanly, indicating that the subsequent socket close is not a connection failure. Thus it doesn't shutdown the server if option `halt_on_connection_failure(true)`.  The response must be processed by the client before closing the socket or it will be interpreted as a connection failure.

Any asynchronous query that is still running will be halted by using `abort/0` in the connection's query thread.

Response:
`true([[]])`


#### quit
Stops the server and ends the SWI Prolog process using `halt(abort)`, regardless of Options settings. This allows client language libraries to ask for an orderly shutdown of the Prolog process.

Response:
`true([[]])`

*/
:- use_module(library(socket)).
:- use_module(library(http/json)).
:- use_module(library(http/json_convert)).
:- use_module(library(option)).
:- use_module(library(term_to_json)).

% One for every language server running
:- dynamic(language_server_thread/3).

% One for every active connection
:- dynamic(language_server_worker_threads/3).
:- dynamic(language_server_socket/5).

% Indicates that a query is in progress on the goal thread or hasn't had its results drained
% Deleted once the last result from the queue has been drained
% Only deleted by the communication thread to avoid race conditions
:- dynamic(query_in_progress/1).

% Indicates to the communication thread that we are in a place
% that can be cancelled
:- dynamic(safe_to_cancel/1).

% Password is carefully constructed to be a strong (not an atom) so that it is not
% globally visible
% Add ".\n" to the password since it will be added by the message when received
language_server(Options) :-
    option_fill_result(Connection_Count, pending_connections(Connection_Count), Options, 5),
    Encoding = utf8,
    option_fill_result(Query_Timeout, query_timeout(Query_Timeout), Options, -1),
    option_fill_result(Halt_On_Failure, halt_on_connection_failure(Halt_On_Failure), Options, false),
    option_fill_result(Port, port(Port), Options, _),
    option_fill_result(Run_Server_On_Thread, run_server_on_thread(Run_Server_On_Thread), Options, true),
    gensym(language_server, Default_Server_Thread_ID),
    option_fill_result(Server_Thread_ID, server_thread(Server_Thread_ID), Options, Default_Server_Thread_ID),
    option_fill_result(Ignore_Sig_Int, ignore_sig_int(Ignore_Sig_Int), Options, false),
    option_fill_result(Write_Connection_Values, write_connection_values(Write_Connection_Values), Options, false),
    uuid(UUID, [format(integer)]),
    format(string(Generated_Password), '~d', [UUID]),
    option_fill_result(Password, password(Password), Options, Generated_Password),
    option(unix_domain_socket(Unix_Domain_Socket_Path_And_File), Options, _),
    (   Ignore_Sig_Int
    ->  on_signal(int, _, halt)
    ;   true
    ),
    bind_socket(Server_Thread_ID, Unix_Domain_Socket_Path_And_File, Port, Socket, Client_Address),
    send_client_startup_data(Write_Connection_Values, user_output, Unix_Domain_Socket_Path_And_File, Client_Address, Password),
    option(writeOutputToFile(File), Options, _),
    (   var(File)
    ->  true
    ;   write_output_to_file(File)
    ),
    string_concat(Password, '.\n', Final_Password),
    Server_Goal = (
                    catch(server_thread(Server_Thread_ID, Socket, Client_Address, Final_Password, Connection_Count, Encoding, Query_Timeout, Halt_On_Failure), error(E1, E2), true),
                    debug(prologServer(protocol), "Stopped server on thread: ~w due to exception: ~w", [Server_Thread_ID, error(E1, E2)])
                 ),
    start_server_thread(Run_Server_On_Thread, Server_Thread_ID, Server_Goal, Unix_Domain_Socket_Path_And_File).


%! stop_language_server(+Server_Thread_ID:atom) is det.
%
% If `Server_Thread_ID` is a variable, stops all language servers and associated threads.  If `Server_Thread_ID` is an atom, then only the server with that `Server_Thread_ID` is stopped. `Server_Thread_ID` can be provided or retrieved using `Options` in `language_server/1`.
%
% Always succeeds.

% tcp_close_socket(Socket) will shut down the server thread cleanly so the socket is released and can be used again in the same session
% Closes down any pending connections using abort even if there were no matching server threads since the server thread could have died.
% At this point only threads associated with live connections (or potentially a goal thread that hasn't detected its missing communication thread)
% should be left so seeing abort warning messages in the console seems OK
stop_language_server(Server_Thread_ID) :-
    % First shut down any matching servers to stop new connections
    forall(retract(language_server_thread(Server_Thread_ID, _, Socket)),
        (
            debug(prologServer(protocol), "Found server: ~w", [Server_Thread_ID]),
            catch(tcp_close_socket(Socket), Socket_Exception, true),
            debug(prologServer(protocol), "Stopped server thread: ~w, exception(~w)", [Server_Thread_ID, Socket_Exception])
        )),
    forall(retract(language_server_worker_threads(Server_Thread_ID, Communication_Thread_ID, Goal_Thread_ID)),
        (
            abortSilentExit(Communication_Thread_ID, CommunicationException),
            debug(prologServer(protocol), "Stopped server: ~w communication thread: ~w, exception(~w)", [Server_Thread_ID, Communication_Thread_ID, CommunicationException]),
            abortSilentExit(Goal_Thread_ID, Goal_Exception),
            debug(prologServer(protocol), "Stopped server: ~w goal thread: ~w, exception(~w)", [Server_Thread_ID, Goal_Thread_ID, Goal_Exception])
        )).


option_fill_result(Final_Variable, Option_Requested, Options, Default_For_Variable) :-
    option(Option_Requested, Options, Default_For_Variable),
    (   var(Final_Variable)
    ->  Final_Variable = Default_For_Variable
    ;   true
    ).


start_server_thread(Run_Server_On_Thread, Server_Thread_ID, Server_Goal, Unix_Domain_Socket_Path_And_File) :-
    (   Run_Server_On_Thread
    ->  (   thread_create(Server_Goal, _, [ alias(Server_Thread_ID),
                                            at_exit((delete_unix_domain_socket_file(Unix_Domain_Socket_Path_And_File),
                                                     detach_if_expected(Server_Thread_ID)
                                                    ))
                                          ]),
            debug(prologServer(protocol), "Started server on thread: ~w", [Server_Thread_ID])
        )
    ;   (   Server_Goal,
            delete_unix_domain_socket_file(Unix_Domain_Socket_Path_And_File),
            debug(prologServer(protocol), "Halting.", [])
        )
    ).


% Unix domain sockets actually create a file that needs to be deleted
% or the connection cannot be reopened using the same file
delete_unix_domain_socket_file(Unix_Domain_Socket_Path_And_File) :-
    (   nonvar(Unix_Domain_Socket_Path_And_File)
    ->  catch(delete_file(Unix_Domain_Socket_Path_And_File), error(_, _), true)
    ;   true
    ).


% Always bind only to localhost for security reasons
% Delete the socket file in case it is already around so that the same name can be reused
bind_socket(Server_Thread_ID, Unix_Domain_Socket_Path_And_File, Port, Socket, Client_Address) :-
    (   nonvar(Unix_Domain_Socket_Path_And_File)
    ->  (   absolute_file_name(Unix_Domain_Socket_Path_And_File, Unix_Domain_Socket_Path_And_File)
        ->  true
        ;   throw(domain_error(not_fully_qualified, Unix_Domain_Socket_Path_And_File))
        ),
        debug(prologServer(protocol), "Using Unix domain socket name: ~w", [Unix_Domain_Socket_Path_And_File]),
        unix_domain_socket(Socket),
        catch(delete_file(Unix_Domain_Socket_Path_And_File), error(_, _), true),
        tcp_bind(Socket, Unix_Domain_Socket_Path_And_File),
        Client_Address = Unix_Domain_Socket_Path_And_File
    ;   (   tcp_socket(Socket),
            tcp_setopt(Socket, reuseaddr),
            tcp_bind(Socket, '127.0.0.1':Port),
            debug(prologServer(protocol), "Using TCP/IP port: ~w", ['127.0.0.1':Port]),
            Client_Address = Port
        )
    ),
    assert(language_server_thread(Server_Thread_ID, Unix_Domain_Socket_Path_And_File, Socket)).


% Communicates the used port and password to the client via STDOUT so the client
% language library can use them to connect
send_client_startup_data(Write_Connection_Values, Stream, Unix_Domain_Socket_Path_And_File, Port, Password) :-
    (   Write_Connection_Values
    ->  (   (  var(Unix_Domain_Socket_Path_And_File)
            ->  format(Stream, "~d\n", [Port])
            ;   true
            ),
            format(Stream, "~s\n", [Password]),
            flush_output(Stream)
        )
    ;   true
    ).


% Server thread worker predicate
% Listen for connections and create a connection for each in its own communication thread
% Uses tail recursion to ensure the stack doesn't grow
server_thread(Server_Thread_ID, Socket, Address, Password, Connection_Count, Encoding, Query_Timeout, Halt_On_Failure) :-
    stack_level(Level),
    debug(prologServer(protocol), "Listening on address: ~w, Stack = ~w", [Address, Level]),
    tcp_listen(Socket, Connection_Count),
    tcp_open_socket(Socket, AcceptFd, _),
    create_connection(Server_Thread_ID, AcceptFd, Password, Encoding, Query_Timeout, Halt_On_Failure),
    server_thread(Server_Thread_ID, Socket, Address, Password, Connection_Count, Encoding, Query_Timeout, Halt_On_Failure).


% Wait for the next connection and create communication and goal threads to support it
% Create known IDs for the threads so we can pass them along before the threads are created
% First create the goal thread to avoid a race condition where the communication
% thread tries to queue a goal before it is created
create_connection(Server_Thread_ID, AcceptFd, Password, Encoding, Query_Timeout, Halt_On_Failure) :-
    debug(prologServer(protocol), "Waiting for client connection...", []),
    tcp_accept(AcceptFd, Socket, _Peer),
    debug(prologServer(protocol), "Client connected", []),
    gensym('conn', Connection_Base),
    atomic_list_concat([Server_Thread_ID, "_", Connection_Base, '_comm'], Thread_Alias),
    atomic_list_concat([Server_Thread_ID, "_", Connection_Base, '_goal'], Goal_Alias),
    mutex_create(Goal_Alias, [alias(Goal_Alias)]),
    assert(language_server_worker_threads(Server_Thread_ID, Thread_Alias, Goal_Alias)),
    thread_create(goal_thread(Thread_Alias),
        _,
        [alias(Goal_Alias), at_exit(detach_if_expected(Goal_Alias))]),
    thread_create(communication_thread(Password, Socket, Encoding, Server_Thread_ID, Goal_Alias, Query_Timeout, Halt_On_Failure),
        _,
        [alias(Thread_Alias), at_exit(detach_if_expected(Thread_Alias))]).


% The worker predicate for the Goal thread.
% Looks for a message from the connection thread, processes it, then recurses.
%
% Goals always run in the same thread in case the user is setting thread local information.
% For each answer to the user's query (including an exception), the goal thread will queue a message
% to the communication thread of the form result(Answer, Find_All), where Find_All == true if the user wants all answers at once
% Tail recurse to avoid growing the stack
goal_thread(Respond_To_Thread_ID) :-
    thread_self(Self_ID),
    throw_if_testing(Self_ID),
    thread_get_message(Self_ID, goal(Goal, Binding_List, Query_Timeout, Find_All)),
    stack_level(Level),
    debug(prologServer(query), "Received Stack: ~w, Findall = ~w, Query_Timeout = ~w, binding list: ~w, goal: ~w", [Level, Find_All, Query_Timeout, Binding_List, Goal]),
    (   Find_All
    ->  One_Answer_Goal = findall(Binding_List, @(Goal, user), Answers)
    ;
        One_Answer_Goal = ( @(Goal, user),
                            Answers = [Binding_List],
                            send_next_result(Respond_To_Thread_ID, Answers, _, Find_All)
                          )
    ),
    All_Answers_Goal = run_cancellable_goal(Self_ID, findall(Answers, One_Answer_Goal, [Find_All_Answers | _])),
    (   Query_Timeout == -1
    ->  catch(All_Answers_Goal, Top_Exception, true)
    ;   catch(call_with_time_limit(Query_Timeout, All_Answers_Goal), Top_Exception, true)
    ),
    (
        var(Top_Exception)
    ->  (
            Find_All
        ->
            send_next_result(Respond_To_Thread_ID, Find_All_Answers, _, Find_All)
        ;
            send_next_result(Respond_To_Thread_ID, [], no_more_results, Find_All)
        )
    ;
        send_next_result(Respond_To_Thread_ID, [], Top_Exception, true)
    ),
    goal_thread(Respond_To_Thread_ID).


% Used only for testing unhandled exceptions outside of the "safe zone"
throw_if_testing(Self_ID) :-
    (   thread_peek_message(Self_ID, testThrow(Test_Exception))
    ->  (   debug(prologServer(query), "TESTING: Throwing test exception: ~w", [Test_Exception]),
            throw(Test_Exception)
        )
    ;   true
    ).


% run_cancellable_goal handles the communication
% to ensure the cancel exception from the communication thread
% is injected at a place we are prepared to handle in the goal_thread
% Before the goal is run, sets a fact to indicate we are in the "safe to cancel"
% zone for the communication thread.
% Then it doesn't exit this "safe to cancel" zone if the
% communication thread is about to cancel
run_cancellable_goal(Mutex_ID, Goal) :-
    thread_self(Self_ID),
    setup_call_cleanup(
        assert(safe_to_cancel(Self_ID), Assertion),
        Goal,
        with_mutex(Mutex_ID, erase(Assertion))
    ).


% Worker predicate for the communication thread.
% Processes messages and sends goals to the goal thread.
% Continues processing messages until communication_thread_listen() throws or ends with true/false
%
% Catches all exceptions from communication_thread_listen so that it can do an orderly shutdown of the goal
%   thread if there is a communication failure.
%
% True means user explicitly called close or there was an exception
%   only halt if there was an exception and we are supposed to Halt_On_Failure
%   otherwise just exit the session
communication_thread(Password, Socket, Encoding, Server_Thread_ID, Goal_Thread_ID, Query_Timeout, Halt_On_Failure) :-
    thread_self(Self_ID),
    (   (
            catch(communication_thread_listen(Password, Socket, Encoding, Server_Thread_ID, Goal_Thread_ID, Query_Timeout), error(Serve_Exception1, Serve_Exception2), true),
            debug(prologServer(protocol), "Session finished. Communication thread exception: ~w", [error(Serve_Exception1, Serve_Exception2)]),
            abortSilentExit(Goal_Thread_ID, _),
            retractall(language_server_worker_threads(Server_Thread_ID, Self_ID, Goal_Thread_ID))
        )
    ->  Halt = (nonvar(Serve_Exception), Halt_On_Failure)
    ;   Halt = true
    ),
    (   Halt
    ->  (   debug(prologServer(protocol), "Ending session and halting Prolog server due to thread ~w: ~w", [Self_ID, Serve_Exception]),
            halt(abort)
        )
    ;   (   debug(prologServer(protocol), "Ending session ~w", [Self_ID]),
            catch(tcp_close_socket(Socket), error(_, _), true)
        )
    ).


% Open socket and begin processing the streams for a connection using the Encoding if the password matches
% true: session ended
% exception: communication failure or an internal failure (like a thread threw or shutdown unexpectedly)
% false: halt
communication_thread_listen(Password, Socket, Encoding, Server_Thread_ID, Goal_Thread_ID, Query_Timeout) :-
    tcp_open_socket(Socket, Read_Stream, Write_Stream),
    thread_self(Communication_Thread_ID),
    assert(language_server_socket(Server_Thread_ID, Communication_Thread_ID, Socket, Read_Stream, Write_Stream)),
    set_stream(Read_Stream, encoding(Encoding)),
    set_stream(Write_Stream, encoding(Encoding)),
    read_message(Read_Stream, Sent_Password),
    (   Password == Sent_Password
    ->  (   debug(prologServer(protocol), "Password matched.", []),
            thread_self(Self_ID),
            reply(Write_Stream, true([[threads(Self_ID, Goal_Thread_ID)]]))
        )
    ;   (   debug(prologServer(protocol), "Password mismatch, failing. ~w", [Sent_Password]),
            reply_error(Write_Stream, password_mismatch),
            throw(password_mismatch)
        )
    ),
    process_language_server_messages(Read_Stream, Write_Stream, Goal_Thread_ID, Query_Timeout),
    debug(prologServer(protocol), "Session finished.", []).


% process_language_server_messages implements the main interface to the language server.
% Continuously reads a language server message from Read_Stream and writes a response to Write_Stream,
% until the connection fails or a `quit` or `close` message is sent.
%
% Read_Stream and Write_Stream can be any valid stream using any encoding.
%
% Goal_Thread_ID must be the threadID of a thread started on the goal_thread predicate
%
% uses tail recursion to ensure the stack doesn't grow
%
% true: indicates we should terminate the session (clean termination)
% false: indicates we should halt(abort)
% exception: indicates we should terminate the session (communication failure termination) or
%    thread was asked to halt
process_language_server_messages(Read_Stream, Write_Stream, Goal_Thread_ID, Query_Timeout) :-
    process_language_server_message(Read_Stream, Write_Stream, Goal_Thread_ID, Query_Timeout, Command),
    (   Command == close
    ->  (   debug(prologServer(protocol), "Command: close. Client closed the connection cleanly.", []),
            true
        )
    ;   (   Command == quit
        ->  (   debug(prologServer(protocol), "Command: quit.", []),
                false
            )
        ;
            process_language_server_messages(Read_Stream, Write_Stream, Goal_Thread_ID, Query_Timeout)
        )
    ).

% process_language_server_message manages the protocol for the connection: receive message, parse it, process it.
% - Reads a single message from Read_Stream.
% - Processes it and issues a response on Write_Stream.
% - The message will be unified with Command to allow the caller to handle it.
%
% Read_Stream and Write_Stream can be any valid stream using any encoding.
%
% True if the message understood. A response will always be sent.
% False if the message was malformed.
% Exceptions will be thrown by the underlying stream if there are communication failures writing to Write_Stream or the thread was asked to exit.
%
% state_* predicates manage the state transitions of the protocol
% They only bubble up exceptions if there is a communication failure
%
% state_process_command will never return false
% since errors should be sent to the client
% It can throw if there are communication failures, though.
process_language_server_message(Read_Stream, Write_Stream, Goal_Thread_ID, Query_Timeout, Command) :-
    stack_level(Level),
    debug(prologServer(protocol), "Waiting for next message (Stack = ~w)...", [Level]),
    (   state_receive_raw_message(Read_Stream, Message_String)
    ->  (   state_parse_command(Write_Stream, Message_String, Command, Binding_List)
        ->  state_process_command(Write_Stream, Goal_Thread_ID, Query_Timeout, Command, Binding_List)
        ;   true
        )
    ;   false
    ).


% state_receive_raw_message: receive a raw message, which is simply a string
%   true: valid message received
%   false: invalid message format
%   exception: communication failure OR thread asked to exit
state_receive_raw_message(Read, Command_String) :-
    read_message(Read, Command_String),
    debug(prologServer(protocol), "Valid message: ~w", [Command_String]).


% state_parse_command: attempt to parse the message string into a valid command
%
% Use read_term_from_atom instead of read_term(stream) so that we don't hang
% indefinitely if the caller didn't properly finish the term
% parse in the context of module 'user' to properly bind operators, do term expansion, etc
%
%   true: command could be parsed
%   false: command cannot be parsed.  An error is sent to the client in this case
%   exception: communication failure on sending a reply
state_parse_command(Write_Stream, Command_String, Parsed_Command, Binding_List) :-
    (   catch(read_term_from_atom(Command_String, Parsed_Command, [variable_names(Binding_List), module(user)]), Parse_Exception, true)
    ->  (   var(Parse_Exception)
        ->  debug(prologServer(protocol), "Parse Success: ~w", [Parsed_Command])
        ;   (   reply_error(Write_Stream, Parse_Exception),
                fail
            )
        )
    ;   (   reply_error(Write_Stream, error(couldNotParseCommand, _)),
            fail
        )
    ).


% state_process_command(): execute the requested Command
%
% First wait until we have removed all results from any previous query.
% If query_in_progress(Goal_Thread_ID) exists then there is at least one
% more result to drain, by definition. Because the predicate is
% deleted by get_next_result in the communication thread when the last result is drained
%
%   true: if the command itself succeeded, failed or threw an exception.
%         In that case, the outcome is sent to the client
%   exception: only communication or thread failures are allowed to bubble up
% See language_server(Options) documentation
state_process_command(Stream, Goal_Thread_ID, Query_Timeout, run(Goal, Timeout), Binding_List) :-
    !,
    debug(prologServer(protocol), "Command: run/1. Timeout: ~w", [Timeout]),
    repeat_until_false((
            query_in_progress(Goal_Thread_ID),
            debug(prologServer(protocol), "Draining unretrieved result for ~w", [Goal_Thread_ID]),
            heartbeat_until_result(Goal_Thread_ID, Stream, Unused_Answer),
            debug(prologServer(protocol), "Drained result for ~w", [Goal_Thread_ID]),
            debug(prologServer(query), "    Discarded answer: ~w", [Unused_Answer])
        )),
    debug(prologServer(protocol), "All previous results drained", []),
    send_goal_to_thread(Stream, Goal_Thread_ID, Query_Timeout, Timeout, Goal, Binding_List, true),
    heartbeat_until_result(Goal_Thread_ID, Stream, Answers),
    reply_with_result(Goal_Thread_ID, Stream, Answers).


% See language_server(Options) documentation for documentation
% See notes in run(Goal, Timeout) re: draining previous query
state_process_command(Stream, Goal_Thread_ID, Query_Timeout, run_async(Goal, Timeout, Find_All), Binding_List) :-
    !,
    debug(prologServer(protocol), "Command: run_async/1.", []),
    debug(prologServer(query),  "   Goal: ~w", [Goal]),
    repeat_until_false((
            query_in_progress(Goal_Thread_ID),
            debug(prologServer(protocol), "Draining unretrieved result for ~w", [Goal_Thread_ID]),
            get_next_result(Goal_Thread_ID, [], Unused_Answer),
            debug(prologServer(protocol), "Drained result for ~w", [Goal_Thread_ID]),
            debug(prologServer(query), "    Discarded answer: ~w", [Unused_Answer])
            )),
    debug(prologServer(protocol), "All previous results drained", []),
    send_goal_to_thread(Stream, Goal_Thread_ID, Query_Timeout, Timeout, Goal, Binding_List, Find_All),
    reply(Stream, true([[]])).


% See language_server(Options) documentation for documentation
state_process_command(Stream, Goal_Thread_ID, _, async_result(Timeout), _) :-
    !,
    debug(prologServer(protocol), "Command: async_result, timeout: ~w.", [Timeout]),
    (   once((var(Timeout) ; Timeout == -1))
    ->  Options = []
    ;   Options = [timeout(Timeout)]
    ),
    (   query_in_progress(Goal_Thread_ID)
    ->  (   (   debug(prologServer(protocol), "Pending query results exist for ~w", [Goal_Thread_ID]),
                get_next_result(Goal_Thread_ID, Options, Result)
            )
        ->  reply_with_result(Goal_Thread_ID, Stream, Result)
        ;   reply_error(Stream, result_not_available)
        )
   ;    (   debug(prologServer(protocol), "No pending query results for ~w", [Goal_Thread_ID]),
            reply_error(Stream, no_query)
        )
   ).


% See language_server(Options) documentation for documentation
% To ensure the goal thread is in a place it is safe to cancel,
% we lock a mutex first that the goal thread checks before exiting
% the "safe to cancel" zone.
% It is not in the safe zone: it either finished
% or was never running.
state_process_command(Stream, Goal_Thread_ID, _, cancel_async, _) :-
    !,
    debug(prologServer(protocol), "Command: cancel_async/0.", []),
    with_mutex(Goal_Thread_ID, (
        (   safe_to_cancel(Goal_Thread_ID)
        ->  (   thread_signal(Goal_Thread_ID, throw(cancel_goal)),
                reply(Stream, true([[]]))
            )
        ;   (   query_in_progress(Goal_Thread_ID)
            ->  (   debug(prologServer(protocol), "Pending query results exist for ~w", [Goal_Thread_ID]),
                    reply(Stream, true([[]]))
                )
            ;   (   debug(prologServer(protocol), "No pending query results for ~w", [Goal_Thread_ID]),
                    reply_error(Stream, no_query)
                )
            )
        )
    )).


% Used for testing how the system behaves when the goal thread is killed unexpectedly
% Needs to run a bogus command `run(true, -1)` to
% get the goal thread to process the exception
state_process_command(Stream, Goal_Thread_ID, Query_Timeout, testThrowGoalThread(Test_Exception), Binding_List) :-
    !,
    debug(prologServer(protocol), "TESTING: requested goal thread unhandled exception", []),
    thread_send_message(Goal_Thread_ID, testThrow(Test_Exception)),
    state_process_command(Stream, Goal_Thread_ID, Query_Timeout, run(true, -1), Binding_List).


state_process_command(Stream, _, _, close, _) :-
    !,
    reply(Stream, true([[]])).


state_process_command(Stream, _, _, quit, _) :-
    !,
    reply(Stream, true([[]])).


%  Send an exception if the command is not known
state_process_command(Stream, _, _, Command, _) :-
    debug(prologServer(protocol), "Unknown command ~w", [Command]),
    reply_error(Stream, unknownCommand).


% Wait for a result (and put in Answers) from the goal thread, but send a heartbeat message
% every so often until it arrives to detect if the socket is broken.
% Throws if If the heartbeat failed which will
% and then shutdown the communication thread
% Tail recurse to not grow the stack
heartbeat_until_result(Goal_Thread_ID, Stream, Answers) :-
    (   get_next_result(Goal_Thread_ID, [timeout(2)], Answers)
    ->  debug(prologServer(query), "Received answer from goal thread: ~w", [Answers])
    ;   (   debug(prologServer(protocol), "heartbeat...", []),
            write_heartbeat(Stream)
        )
    ).


% True if write succeeded, otherwise throws as that
% indicates that heartbeat failed because the other
% end of the pipe terminated
write_heartbeat(Stream) :-
    put_char(Stream, '.'),
    flush_output(Stream).


% Send a goal to the goal thread in its queue
%
% Remember that we are now running a query using assert.
%   This will be retracted once all the answers have been drained.
%
% If Goal_Thread_ID died, thread_send_message throws and, if we don't respond,
%   the client could hang so catch and give them a good message before propagating
%   the exception
send_goal_to_thread(Stream, Goal_Thread_ID, Default_Timeout, Timeout, Goal, Binding_List, Find_All) :-
    (   var(Timeout)
    ->  Timeout = Default_Timeout
    ;   true
    ),
    (   var(Binding_List)
    ->  Binding_List = []
    ;   true
    ),
    debug(prologServer(query),  "Sending to goal thread with timeout = ~w: ~w", [Timeout, Goal]),
    assert(query_in_progress(Goal_Thread_ID)),
    catch(thread_send_message(Goal_Thread_ID, goal(Goal, Binding_List, Timeout, Find_All)), Send_Message_Exception, true),
    (   var(Send_Message_Exception)
    ->  true
    ;   (   reply_error(Stream, connection_failed),
            throw(Send_Message_Exception)
        )
    ).


% Send a result from the goal thread to the communication thread in its queue
send_next_result(Respond_To_Thread_ID, Answer, Exception_In_Goal, Find_All) :-
    (   var(Exception_In_Goal)
    ->  (   (   debug(prologServer(query), "Sending result of goal to communication thread, Result: ~w", [Answer]),
                Answer == []
            )
        ->  thread_send_message(Respond_To_Thread_ID, result(false, Find_All))
        ;   thread_send_message(Respond_To_Thread_ID, result(true(Answer), Find_All))
        )
    ;   (   debug(prologServer(query), "Sending result of goal to communication thread, Exception: ~w", [Exception_In_Goal]),
            thread_send_message(Respond_To_Thread_ID, result(error(Exception_In_Goal), Find_All))
        )
    ).


% Gets the next result from the goal thread in the communication thread queue,
% and retracts query_in_progress/1 when the last result has been sent
% Find_All == true only returns one message, so delete query_in_progress
% No matter what it is
% \+ Find_All: There may be more than one result. The first one we hit with any exception
% (note that no_more_results is also returned as an exception) means we are done
get_next_result(Goal_Thread_ID, Options, Answers) :-
    thread_self(Self_ID),
    thread_get_message(Self_ID, result(Answers, Find_All), Options),
    (   Find_All
    ->  (   debug(prologServer(protocol), "Query completed and answers drained for findall ~w", [Goal_Thread_ID]),
            retractall(query_in_progress(Goal_Thread_ID))
        )
    ;   (   Answers = error(_)
        ->  (   debug(prologServer(protocol), "Query completed and answers drained for non-findall ~w", [Goal_Thread_ID]),
                retractall(query_in_progress(Goal_Thread_ID))
            )
        ;   true
        )
    ).


% reply_with_result predicates are used to consistently return
% answers for a query from either run() or run_async()
reply_with_result(_, Stream, error(Error)) :-
    !,
    reply_error(Stream, Error).
reply_with_result(_, Stream, Result) :-
    !,
    reply(Stream, Result).


% Reply with a normal term
% Convert term to an actual JSON string
reply(Stream, Term) :-
    debug(prologServer(query), "Responding with Term: ~w", [Term]),
    term_to_json_string(Term, Json_String),
    write_message(Stream, Json_String).


% Special handling for exceptions since they can have parts that are not
% "serializable". Ensures they they are always returned in an exception/1 term
reply_error(Stream, Error_Term) :-
    (   error(Error_Value, _) = Error_Term
    ->  Response = exception(Error_Value)
    ;   (   atom(Error_Term)
        ->
            Response = exception(Error_Term)
        ;   (   compound_name_arity(Error_Term, Name, _),
                Response = exception(Name)
            )
        )
    ),
    reply(Stream, Response).


% Send and receive messages are simply strings preceded by their length + ".\n"
% i.e. "<stringlength>.\n<string>"
% The desired encoding must be set on the Stream before calling this predicate


% Writes the next message.
% Throws if there is an unexpected exception
write_message(Stream, String) :-
    write_string_length(Stream, String),
    write(Stream, String),
    flush_output(Stream).


% Reads the next message.
% Throws if there is an unexpected exception or thread has been requested to quit
% the length passed must match the actual number of bytes in the stream
% in whatever encoding is being used
read_message(Stream, String) :-
    read_string_length(Stream, Length),
    read_string(Stream, Length, String).


% Terminate with '.\n' so we know that's the end of the count
write_string_length(Stream, String) :-
    stream_property(Stream, encoding(Encoding)),
    string_encoding_length(String, Encoding, Length),
    format(Stream, "~d.\n", [Length]).


% Note: read_term requires ".\n" after the length
% ... but does not consume the "\n"
read_string_length(Stream, Length) :-
    read_term(Stream, Length, []),
    get_char(Stream, _).


% converts a string to Codes using Encoding
string_encoding_length(String, Encoding, Length) :-
    setup_call_cleanup(
        open_null_stream(Out),
        (   set_stream(Out, encoding(Encoding)),
            write(Out, String),
            byte_count(Out, Length)
        ),
        close(Out)).


% Convert Prolog Term to a Prolog JSON term
term_to_json_string(Term, Json_String) :-
    term_to_json(Term, Json),
    with_output_to(string(Json_String),
        (   current_output(Stream),
            json_write(Stream, Json)
        )).


% See if the stack is growing by retrieving out the stack bytes
stack_level(Bytes) :-
    statistics(localused, Bytes).


% Execute the goal as once() without binding any variables
% and keep executing it until it returns false (or throws)
repeat_until_false(Goal) :-
    (\+ (\+ Goal)), !, repeat_until_false(Goal).
repeat_until_false(_).


% Used to kill a thread in an "expected" way so it doesn't leave around traces for debugging
% If the thread is alive OR it was aborted (expected cases): detatch it and then attempt to join
%   the thread so that no warnings are sent to the console. Other cases leave the thread for debugging.
% There are some fringe cases (like calling external code)
%   where the call might not return for a long time.  Do a timeout for those cases.
% Catch the timeout exception or cases where the thread is detached or gone.
abortSilentExit(Thread_ID, Exception) :-
    catch(thread_signal(Thread_ID, abort), error(Exception, _), true),
    debug(prologServer(protocol), "Attempting to abort thread: ~w. Goal thread exception: ~w", [Thread_ID, Exception]),
    (   once((var(Exception) ; catch(thread_property(Thread_ID, status(exception('$aborted'))), error(_, _), true)))
    ->  catch(call_with_time_limit(4, thread_join(Thread_ID)), error(_, _), true)
    ;   true
    ).


% Don't detach if it exits in an unexpected way so we can debug using thread_property afterwards
%
% The goal thread is always aborted and joined by the communication thread using abortSilentExit (if the comm thread is there to do the joining)
% to avoid the user getting warnings about aborted threads on the console when connections are shut down. This means
% we can't detect unexpected failures from the goal thread unless the comm thread died first.
% However, the comm thread is not ever joined so that any unexpected errors can be detected by examining thread properties
% later.
detach_if_expected(Thread_ID) :-
    thread_property(Thread_ID, status(Status)),
    debug(prologServer(protocol), "Thread ~w exited with status ~w", [Thread_ID, Status]),
    (   once((Status = true ; Status = false))
    ->  thread_detach(Thread_ID)
    ;   true
    ).

write_output_to_file(File) :-
    debug(prologServer(protocol), "Writing all STDOUT and STDERR to file:~w", [File]),
    catch(delete_file(File), error(_, _), true),
    open(File, write, Stream, [buffer(false)]),
    set_prolog_IO(user_input, Stream, Stream).

