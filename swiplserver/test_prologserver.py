import json
import logging
import os
import sys
import unittest
import threading
from time import sleep
from prologserver import *


# From: https://eli.thegreenplace.net/2011/08/02/python-unit-testing-parametrized-test-cases/
class ParametrizedTestCase(unittest.TestCase):
    """ TestCase classes that want to be parametrized should
        inherit from this class.
    """
    def __init__(self, methodName='runTest', launchServer = True, useUnixDomainSocket = None, serverPort= None, password= None):
        super(ParametrizedTestCase, self).__init__(methodName)
        self.launchServer = launchServer
        self.useUnixDomainSocket = useUnixDomainSocket
        self.serverPort = serverPort
        self.password = password

    @staticmethod
    def parametrize(testcase_klass, launchServer = True, useUnixDomainSocket = None, serverPort= None, password= None):
        """ Create a suite containing all tests taken from the given
            subclass, passing them the parameter 'param'.
        """
        testloader = unittest.TestLoader()
        testnames = testloader.getTestCaseNames(testcase_klass)
        suite = unittest.TestSuite()
        for name in testnames:
            suite.addTest(testcase_klass(name, launchServer = launchServer, useUnixDomainSocket = useUnixDomainSocket, serverPort= serverPort, password= password))
        return suite


class TestPrologServer(ParametrizedTestCase):
    def setUp(self):
        pass

    def tearDown(self):
        # If we're using a Unix Domain Socket, make sure the file was cleaned up
        self.assertTrue(self.useUnixDomainSocket is None or not os.path.exists(self.useUnixDomainSocket))

    def thread_failure_reason(self, client, threadID, secondsTimeout):
        count = 0
        while True:
            assert count < secondsTimeout
            # Thread has exited if thread_property(GoalID, status(PropertyGoal)) and PropertyGoal \== running OR if we get an exception (meaning the thread is gone)
            result = client.query(
                "GoalID = {}, once((\\+ is_thread(GoalID) ; catch(thread_property(GoalID, status(PropertyGoal)), Exception, true), once(((var(Exception), PropertyGoal \\== running) ; nonvar(Exception)))))".format
                    (threadID))
            if result is False:
                count += 1
                sleep(1)
            else:
                # If the thread was aborted keep trying since it will spuriously appear and then disappear
                reason = result[0]["PropertyGoal"]
                if prolog_name(reason) == "exception" and prolog_args(reason)[0] == "$aborted":
                    continue
                else:
                    return reason

    # Wait for the threads to exit and return the reason for exit
    # will be "_" if they exited in an expected way
    def thread_failure_reasons(self, client, threadIDList, secondsTimeout):
        reasons = []
        for threadID in threadIDList:
            reason = self.thread_failure_reason(client, threadID, secondsTimeout)
            reasons.append(reason)

        return reasons

    def assertThreadExitExpected(self, client, threadIDList, timeout):
        reasonList = self.thread_failure_reasons(client, threadIDList, timeout)
        for reason in reasonList:
            # They should exit in an expected way
            self.assertEqual(reason, "_")

    def thread_list(self, prologThread):
        result = prologThread.query("thread_property(ThreadID, status(Status))")
        testThreads = []
        for item in result:
            testThreads.append(item["ThreadID"] + ":" + item["Status"])

        return testThreads

    def round_trip_prolog(self, client, testTerm, expectedText = None):
        if expectedText is None:
            expectedText = testTerm
        result = client.query("X = {}".format(testTerm))
        term = result[0]["X"]
        convertedTerm = json_to_prolog(term)
        assert convertedTerm == expectedText

    def sync_query_timeout(self, prologThread, sleepForSeconds, queryTimeout):
        # Query that times out")
        caughtException = False
        try:
            result = prologThread.query("sleep({})".format(sleepForSeconds), query_timeout_seconds=queryTimeout)
        except PrologQueryTimeoutError as error:
            caughtException = True
        assert caughtException

    def async_query_timeout(self, prologThread, sleepForSeconds, queryTimeout):
        # async query with all results that times out on second of three results")
        prologThread.query_async("(member(X, [Y=a, sleep({}), Y=b]), X)".format(sleepForSeconds),
                                 query_timeout_seconds=queryTimeout)
        try:
            result = prologThread.query_async_result()
        except PrologQueryTimeoutError as error:
            caughtException = True
        assert caughtException

        # Calling cancel after the goal times out after one successful iteration")
        prologThread.query_async("(member(X, [Y=a, sleep({}), Y=b]), X)".format(sleepForSeconds),
                                 query_timeout_seconds=queryTimeout, find_all=False)
        sleep(sleepForSeconds + 1)
        prologThread.cancel_query_async()
        results = []
        while True:
            try:
                result = prologThread.query_async_result()
            except PrologQueryTimeoutError as error:
                results.append('time_limit_exceeded')
                break
            if result is None:
                break
            results.append(result)
        self.assertEqual([[{'X': {'args': ['a', 'a'], 'functor': '='}, 'Y': 'a'}], 'time_limit_exceeded'], results)

    def test_json_to_prolog(self):
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as client:
                # Test non-quoted terms
                self.round_trip_prolog(client, "a")
                self.round_trip_prolog(client, "1")
                self.round_trip_prolog(client, "1.1")
                self.round_trip_prolog(client, "a(b)")
                self.round_trip_prolog(client, "a(b, c)")
                self.round_trip_prolog(client, "[a(b)]")
                self.round_trip_prolog(client, "[a(b), b(c)]")
                self.round_trip_prolog(client, "[a(b(d)), b(c)]")
                self.round_trip_prolog(client, "[2, 1.1]")

                # Test variables
                self.round_trip_prolog(client, "[_1, _a, Auto]", "[A, B, C]")
                self.round_trip_prolog(client, "_")
                self.round_trip_prolog(client, "_1", "A")
                self.round_trip_prolog(client, "_1a", "A")

                # Test quoting terms
                # Terms that do not need to be quoted round trip without quoting")
                self.round_trip_prolog(client, "a('b')", "a(b)")
                self.round_trip_prolog(client, "a('_')", "a(_)")
                # These terms all need quoting
                self.round_trip_prolog(client, "a('b A')")
                self.round_trip_prolog(client, "a('1b')")
                self.round_trip_prolog(client, "'a b'(['1b', 'a b'])")

    def test_sync_query(self):
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as client:
                # Most basic query with single answer and no free variables
                result = client.query("atom(a)")
                assert True == result

                # Most basic query with multiple answers and no free variables
                client.query \
                    ("(retractall(noFreeVariablesMultipleResults), assert((noFreeVariablesMultipleResults :- member(_, [1, 2, 3]))))")
                result = client.query("noFreeVariablesMultipleResults")
                assert [True, True, True] == result

                # Most basic query with single answer and two free variables
                client.query \
                    ("(retractall(twoFreeVariablesOneResult(X, Y)), assert((twoFreeVariablesOneResult(X, Y) :- X = 1, Y = 1)))")
                result = client.query("twoFreeVariablesOneResult(X, Y)")
                assert [{'X': 1, 'Y': 1}] == result

                # Most basic query with multiple answers and two free variables
                client.query \
                    ("(retractall(twoFreeVariablesMultipleResults(X, Y)), assert((twoFreeVariablesMultipleResults(X, Y) :- member(X-Y, [1-1, 2-2, 3-3]))))")
                result = client.query("twoFreeVariablesMultipleResults(X, Y)")
                assert [{'X': 1, 'Y': 1}, {'X': 2, 'Y': 2}, {'X': 3, 'Y': 3}] == result

                # Query that that has a parse error
                caughtException = False
                try:
                    result = client.query("member(X, [first, second, third]")
                except PrologError as error:
                    assert error.is_prolog_exception("syntax_error")
                    caughtException = True
                assert caughtException

                self.sync_query_timeout(client, sleepForSeconds=3, queryTimeout=1)

                # Query that throws
                caughtException = False
                try:
                    result = client.query("throw(test)")
                except PrologError as error:
                    assert error.is_prolog_exception("test")
                    caughtException = True
                assert caughtException

    def test_async_query(self):
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as client:
                # Cancelling while nothing is happening should throw
                caughtException = False
                try:
                    client.cancel_query_async()
                except PrologNoQueryError as error:
                    assert error.is_prolog_exception("no_query")
                    caughtException = True
                assert caughtException

                # Getting a result when no query running should throw
                caughtException = False
                try:
                    client.query_async_result()
                except PrologNoQueryError as error:
                    assert error.is_prolog_exception("no_query")
                    caughtException = True
                assert caughtException

                ##########
                # Async queries with all results
                ##########

                # Most basic async query with all results and no free variables
                client.query_async("atom(a)", find_all=True)
                result = client.query_async_result()
                assert True == result

                # async query with all results and free variables
                client.query_async("member(X, [first, second, third])")
                result = client.query_async_result()
                assert [{'X': 'first'}, {'X': 'second'}, {'X': 'third'}] == result

                # async query with all results that gets cancelled while goal is executing
                client.query_async("(member(X, [Y=a, sleep(3), Y=b]), X)")
                client.cancel_query_async()
                try:
                    result = client.query_async_result()
                except PrologQueryCancelledError as error:
                    assert error.is_prolog_exception("cancel_goal")
                    caughtException = True
                assert caughtException

                # async query with all results that throws
                client.query_async("throw(test)")
                try:
                    result = client.query_async_result()
                except PrologError as error:
                    assert error.is_prolog_exception("test")
                    caughtException = True
                assert caughtException

                ##########
                # Async queries with individual results
                ##########

                # async query that has a parse error
                query = "member(X, [first, second, third]"
                caughtException = False
                try:
                    client.query_async(query)
                except PrologError as error:
                    assert error.is_prolog_exception("syntax_error")
                    caughtException = True
                assert caughtException

                # an async query with multiple results as individual results
                client.query_async("member(X, [first, second, third])", find_all=False)
                results = []
                while True:
                    result = client.query_async_result()
                    if result is None:
                        break
                    results.append(result[0])
                assert [{'X': 'first'}, {'X': 'second'}, {'X': 'third'}] == results

                # Async query with individual results that times out on second of three results
                client.query_async("(member(X, [Y=a, sleep(3), Y=b]), X)", query_timeout_seconds= 1, find_all=False)
                results = []
                while True:
                    try:
                        result = client.query_async_result()
                    except PrologError as error:
                        results.append(error.prolog())
                        break
                    if result is None:
                        break
                    results.append(result[0])
                assert [{'X': {'args': ['a', 'a'], 'functor': '='}, 'Y': 'a'}, 'time_limit_exceeded'] == results

                # Async query that checks for second result before it is available
                client.query_async("(member(X, [Y=a, sleep(3), Y=b]), X)", query_timeout_seconds= 10, find_all=False)
                results = []
                resultNotAvailable = False
                while True:
                    try:
                        result = client.query_async_result(0)
                        if result is None:
                            break
                        else:
                            results.append(result[0])
                    except PrologResultNotAvailableError as error:
                        resultNotAvailable = True

                assert resultNotAvailable and [{'X': {'args': ['a', 'a'], 'functor': '='}, 'Y': 'a'}, {'X': {'args': [3], 'functor': 'sleep'}, 'Y': '_'}, {'X': {'args': ['b', 'b'], 'functor': '='}, 'Y': 'b'}] == results

                # Async query that is cancelled after retrieving first result but while the query is running
                client.query_async("(member(X, [Y=a, sleep(3), Y=b]), X)", find_all=False)
                result = client.query_async_result()
                assert [{'X': {'args': ['a', 'a'], 'functor': '='}, 'Y': 'a'}] == result
                client.cancel_query_async()
                try:
                    result = client.query_async_result()
                except PrologQueryCancelledError as error:
                    assert error.is_prolog_exception("cancel_goal")
                    caughtException = True
                assert caughtException

                # Calling cancel after the goal is finished and results have been retrieved
                client.query_async("(member(X, [Y=a, Y=b, Y=c]), X)", find_all=True)
                sleep(1)
                result = client.query_async_result()
                assert [{'X': {'args': ['a', 'a'], 'functor': '='}, 'Y': 'a'}, {'X': {'args': ['b', 'b'], 'functor': '='}, 'Y': 'b'}, {'X': {'args': ['c', 'c'], 'functor': '='}, 'Y': 'c'}] == result
                caughtException = False
                try:
                    client.cancel_query_async()
                except PrologNoQueryError as error:
                    assert error.is_prolog_exception("no_query")
                    caughtException = True
                assert caughtException

                # async query with separate results that throws
                client.query_async("throw(test)", find_all=False)
                try:
                    result = client.query_async_result()
                except PrologError as error:
                    assert error.is_prolog_exception("test")
                    caughtException = True
                assert caughtException

                self.async_query_timeout(client, 3, 1)

    def test_protocol_edge_cases(self):
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as client:
                # Call two async queries in a row. Should work and return the second results
                client.query_async("(member(X, [Y=a, Y=b, Y=c]), X), sleep(3)", find_all=False)
                client.query_async("(member(X, [Y=d, Y=e, Y=f]), X)", find_all=False)
                results = []
                while True:
                    result = client.query_async_result()
                    if result is None:
                        break
                    results.append(result[0])
                assert [{'X': {'args': ['d', 'd'], 'functor': '='}, 'Y': 'd'}, {'X': {'args': ['e', 'e'], 'functor': '='}, 'Y': 'e'}, {'X': {'args': ['f', 'f'], 'functor': '='}, 'Y': 'f'}] == results

                # Call sync while async is pending, should work and return sync call results
                client.query_async("(member(X, [Y=a, Y=b, Y=c]), X)", find_all=False)
                results = client.query("(member(X, [Y=d, Y=e, Y=f]), X)")
                assert [{'X': {'args': ['d', 'd'], 'functor': '='}, 'Y': 'd'}, {'X': {'args': ['e', 'e'], 'functor': '='}, 'Y': 'e'}, {'X': {'args': ['f', 'f'], 'functor': '='}, 'Y': 'f'}] == results

    def test_connection_failures(self):
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as monitorThread:
                # Closing a connection with an synchronous query running should abort the query and terminate the threads expectedly
                with server.create_thread() as prologThread:
                    # Run query in a thread since it is synchronous and we want to cancel before finished
                    def TestThread(prologThread):
                        try:
                            prologThread.query("(sleep(10), assert(closeConnectionTestFinished)")
                        except Exception:
                            pass

                    thread = threading.Thread(target=TestThread, args=(prologThread, ))
                    thread.start()
                    # Give it time to start
                    sleep(1)
                    # Close the connection unexpectedly while running
                    prologThread.stop()
                    thread.join()
                    self.assertThreadExitExpected(monitorThread, [prologThread.goal_thread_id, prologThread.communication_thread_id], 5)
                    # Make sure it didn't finish
                    exceptionCaught = False
                    try:
                        monitorThread.query("closeConnectionTestFinished")
                    except PrologError as error:
                        exceptionCaught = True
                        assert error.is_prolog_exception("existence_error")

                # Closing a connection with an asynchronous query running should abort the query and terminate the threads expectedly
                with server.create_thread() as prologThread:
                    prologThread.query_async("(sleep(10), assert(closeConnectionTestFinished))")
                    # Give it time to start the goal
                    sleep(1)

                # left "with" clause so connection is closed, query should be cancelled
                self.assertThreadExitExpected(monitorThread, [prologThread.goal_thread_id, prologThread.communication_thread_id], 5)
                # Make sure it didn't finish
                exceptionCaught = False
                try:
                    monitorThread.query("closeConnectionTestFinished")
                except PrologError as error:
                    exceptionCaught = True
                    assert error.is_prolog_exception("existence_error")

    # To prove that threads are running concurrently have them all assert something then wait
    # Then release the mutex
    # then check to see if they all finished
    def test_multiple_connections(self):
        threadCount = 5
        # Multiple connections can run concurrently")
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as monitorThread:
                with server.create_thread() as controlThread:
                    # Will keep the mutex since the thread is kept alive
                    try:
                        controlThread.query("mutex_create(test), mutex_lock(test), assert(started(-1)), assert(ended(-1))")
                        prologThreads = []
                        for index in range(0, 5):
                            prologThread = server.create_thread()
                            prologThread.start()
                            prologThread.query_async("assert({}), with_mutex(test, assert({}))".format("started(" + str(index) + ")", "ended(" + str(index) + ")"))
                            prologThreads.append(prologThread)

                        # Give time to get to mutex
                        sleep(3)

                        # now make sure they all started but didn't end since the mutex hasn't been released
                        startResult = monitorThread.query \
                            ("findall(Value, started(Value), StartedList), findall(Value, ended(Value), EndedList)")
                        startedList = startResult[0]["StartedList"]
                        endedList = startResult[0]["EndedList"]
                        self.assertEqual(startedList.sort(), [-1, 0, 1, 2, 3, 4].sort())
                        self.assertEqual(endedList, [-1])

                        # release the mutex and delete the data
                        controlThread.query("mutex_unlock(test)")

                        # They should have ended now
                        startResult = monitorThread.query("findall(Value, ended(Value), EndedList)")
                        endedList = startResult[0]["EndedList"]
                        self.assertEqual(endedList.sort(), [-1, 0, 1, 2, 3, 4].sort())
                    finally:
                        # and destroy it
                        controlThread.query("mutex_destroy(test), retractall(ended(_)), retractall(started(_))")

    def test_multiple_serial_connections(self):
        # Multiple connections can run serially
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as prologThread:
                result = prologThread.query("true")
                self.assertEqual(result, True)
            sleep(1)
            with server.create_thread() as prologThread:
                result = prologThread.query("true")
                self.assertEqual(result, True)
            sleep(1)
            with server.create_thread() as prologThread:
                result = prologThread.query("true")
                self.assertEqual(result, True)

    def test_goal_thread_failure(self):
        # If the goal thread fails, we should get a specific exception and the thread should be left for inspection
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as prologThread:
                # Force the goal thread to throw outside of the "safe zone" and shutdown unexpectedly
                prologThread._send("testThrowGoalThread(test_exception).\n")
                result = prologThread._receive()
                # give it time to process
                sleep(2)

                # The next query should get a final exception
                exceptionHandled = False
                try:
                    result = prologThread.query("true")
                except PrologConnectionFailedError as error:
                    assert error.is_prolog_exception("connection_failed")
                    exceptionHandled = True
                assert exceptionHandled

            # At this point the server communication thread has failed and stopped the server since we launched with
            # haltOnCommunicationFailure(true), so this should fail.  Finding a reliable way to detect if the process is gone
            # that works cross platform was very hard.  The alternative which is to try to connect and fail after a timeout
            # was surprisingly also hard.  So, for now, we're not verifying that.

    def test_quit(self):
        # Sending quit should shutdown the server")
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as prologThread:
                prologThread.halt_server()
                # Finding a reliable way to detect if the process is gone
                # that works cross platform was very hard.  The alternative which is to try to connect and fail after a timeout
                # was surprisingly also hard.  So, for now, we're not verifying that.

    def test_unknown_command(self):
        # Sending an unknown command should throw")
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as prologThread:
                # Force the goal thread to throw outside of the "safe zone" and shutdown unexpectedly
                prologThread._send("foo.\n")
                result = json.loads(prologThread._receive())
                assert prolog_name(result) == "exception" and prolog_name(prolog_args(result)[0]) == "unknownCommand"

    def test_server_options_and_shutdown(self):
        with PrologServer(self.launchServer, self.serverPort, self.password, self.useUnixDomainSocket) as server:
            with server.create_thread() as monitorThread:
                # Record the threads that are running
                initialThreads = self.thread_list(monitorThread)

                # When starting a server, all variables should be filled in with defaults and only the server thread should be created
                # Launch the new server with all options specified with variables to make sure they get filled in
                result = monitorThread.query("language_server([pending_connections(ConnectionCount), query_timeout(QueryTimeout), halt_on_connection_failure(HaltOnConnectionFailure), port(Port), run_server_on_thread(RunServerOnThread), server_thread(ServerThreadID), ignore_sig_int(true), write_connection_values(WriteConnectionValues), password(Password)])")
                optionsDict = result[0]
                assert optionsDict["ConnectionCount"] == 5 and optionsDict["QueryTimeout"] == -1 and optionsDict["HaltOnConnectionFailure"] == "false" and "Port" in optionsDict and optionsDict["RunServerOnThread"] == "true" and "ServerThreadID" in optionsDict and optionsDict["WriteConnectionValues"] == "false" and "Password" in optionsDict

                # Get the new threadlist
                result = monitorThread.query("thread_property(ThreadID, status(Status))")
                testThreads = self.thread_list(monitorThread)

                # Only a server thread should have been started
                assert len(testThreads) - len(initialThreads) == 1

                # stop_language_server should remove all (and only) created threads and the Unix Domain File
                result = monitorThread.query("stop_language_server({})".format(optionsDict["ServerThreadID"]))
                afterShutdownThreads = self.thread_list(monitorThread)
                assert afterShutdownThreads == initialThreads

                # queryTimeout() supplied at startup should apply to queries by default. password() and port() should be used if supplied.
                socketPort = 4250
                result = monitorThread.query \
                    ("language_server([query_timeout(1), port({}), password(testpassword), server_thread(ServerThreadID)])".format
                        (socketPort))
                serverThreadID = result[0]["ServerThreadID"]
                with PrologServer(launch_server=False, port=socketPort, password="testpassword") as newServer:
                    with newServer.create_thread() as prologThread:
                        self.sync_query_timeout(prologThread, sleepForSeconds=2, queryTimeout=None)
                        self.async_query_timeout(prologThread, sleepForSeconds=2, queryTimeout=None)
                result = monitorThread.query("stop_language_server({})".format(serverThreadID))
                self.assertEqual(result, True)
                afterShutdownThreads = self.thread_list(monitorThread)
                assert afterShutdownThreads == initialThreads

                # Shutting down a server with an active query should abort it and close all threads properly.
                socketPort = 4250
                result = monitorThread.query \
                    ("language_server([port({}), password(testpassword), server_thread(ServerThreadID)])".format
                        (socketPort))
                serverThreadID = result[0]["ServerThreadID"]
                with PrologServer(launch_server=False, port=socketPort, password="testpassword") as newServer:
                    with newServer.create_thread() as prologThread:
                        prologThread.query_async("sleep(20)")
                # Wait for query to start running
                sleep(2)
                result = monitorThread.query("stop_language_server({})".format(serverThreadID))
                assert result is True
                afterShutdownThreads = self.thread_list(monitorThread)
                assert afterShutdownThreads == initialThreads

                # password() and unixDomainSocket() should be used if supplied.
                socketPath = os.path.dirname(os.path.realpath(__file__))
                unixDomainSocket = PrologServer.unix_domain_socket_file(socketPath)
                result = monitorThread.query \
                    ("language_server([unix_domain_socket('{}'), password(testpassword), server_thread(ServerThreadID)])".format
                        (unixDomainSocket))
                serverThreadID = result[0]["ServerThreadID"]
                with PrologServer(launch_server=False, unix_domain_socket=unixDomainSocket, password="testpassword") as newServer:
                    with newServer.create_thread() as prologThread:
                        result = prologThread.query("true")
                        self.assertEqual(result, True)
                result = monitorThread.query("stop_language_server({})".format(serverThreadID))
                self.assertEqual(result, True)
                afterShutdownThreads = self.thread_list(monitorThread)
                self.assertEqual(afterShutdownThreads, initialThreads)
                assert not os.path.exists(unixDomainSocket)

                # runServerOnThread(false) should block until the server is shutdown.
                # Create a new connection that we block starting a new server
                with server.create_thread() as blockedThread:
                    blockedThread.query_async \
                        ("language_server([port({}), password(testpassword), run_server_on_thread(false), server_thread(testServerThread)])".format
                            (socketPort))
                    # Wait for the server to start
                    sleep(1)

                    # Make sure we are still blocked
                    exceptionCaught = False
                    try:
                        blockedThread.query_async_result(wait_timeout_seconds=0)
                    except PrologResultNotAvailableError:
                        exceptionCaught = True
                    assert exceptionCaught

                    # Ensure the server started by sending it a query
                    with PrologServer(launch_server=False, port=socketPort, password="testpassword") as newServer:
                        with newServer.create_thread() as prologThread:
                            result = prologThread.query("true")
                            self.assertEqual(result, True)
                    # Make sure we are still blocked
                    exceptionCaught = False
                    try:
                        blockedThread.query_async_result(wait_timeout_seconds=0)
                    except PrologResultNotAvailableError:
                        exceptionCaught = True
                    assert exceptionCaught

                    # Now shut it down
                    result = monitorThread.query("stop_language_server(testServerThread)")
                    self.assertEqual(result, True)
                    # Give it time to stop the server
                    sleep(1)
                    result = blockedThread.query_async_result()
                    # The server thread catches all exceptions so it will return true
                    self.assertEqual(result, True)

                # And make sure all the threads went away
                count = 0
                while count < 5:
                    afterShutdownThreads = self.thread_list(monitorThread)
                    if afterShutdownThreads == initialThreads:
                        break
                    else:
                        count += 1
                if count == 5:
                    print(initialThreads)
                    print(afterShutdownThreads)
                    assert False

                # Launching this library itself and stopping in the debugger tests writeConnectionValues(), ignoreSigint() and haltOnConnectionFailure()

    def test_class_common_errors(self):
        # Using a thread without starting it should start the server
        with PrologServer() as server:
            prolog_thread = PrologThread(server)
            self.assertTrue(prolog_thread.query("true"))
            pid = server.process_id()

        with PrologServer() as server:
            prolog_thread = PrologThread(server)
            self.assertIsNone(prolog_thread.query_async("true"))
            pid = server.process_id()

        # Start a thread twice is ignored
        with PrologServer() as server:
            with PrologThread(server) as prolog_thread:
                prolog_thread.start()
                self.assertTrue(prolog_thread.query("true"))


def load_tests(loader, standard_tests, pattern):
    suite = unittest.TestSuite()

    # Tests a specific test
    # suite.addTest(TestPrologServer('test_server_options_and_shutdown'))

    # Run checkin tests
    socketPath = os.path.dirname(os.path.realpath(__file__))
    # suite.addTest(ParametrizedTestCase.parametrize(TestPrologServer, launchServer = False, useUnixDomainSocket = None, serverPort= 4242, password= "test"))
    suite.addTest(ParametrizedTestCase.parametrize(TestPrologServer, launchServer = True, useUnixDomainSocket = None, serverPort= None, password= None))
    suite.addTest(ParametrizedTestCase.parametrize(TestPrologServer, launchServer = True, useUnixDomainSocket = PrologServer.unix_domain_socket_file(socketPath), serverPort= None, password= None))

    return suite


if __name__ == '__main__':
    print("**** Note that some builds of Prolog will print out 'foreign predicate system:>/2 did not clear exception...' when running tests.  Just ignore it.")

    # perfLogger = logging.getLogger("swiplserver")
    # perfLogger.setLevel(logging.DEBUG)
    # formatter = logging.Formatter('%(name)s %(asctime)s: %(message)s')
    # file_handler = logging.StreamHandler(sys.stdout)
    # file_handler.setFormatter(formatter)
    # perfLogger.addHandler(file_handler)

    unittest.main(verbosity=2, module="test_prologserver")
