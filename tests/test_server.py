import socket
import threading
import unittest

from communication.protocol import receive_message, send_message
from communication.server import handle_connection


class ServerTests(unittest.TestCase):
    def test_handler_exception_returns_json_error_to_client(self):
        server_socket, client_socket = socket.socketpair()

        def broken_handler(_message):
            raise ValueError("invalid test request")

        worker = threading.Thread(
            target=handle_connection,
            args=(server_socket, broken_handler),
            daemon=True,
        )
        with self.assertLogs(level="ERROR"):
            worker.start()
            with client_socket:
                send_message(client_socket, {"type": "TEST"})
                response = receive_message(client_socket)
            worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(response["type"], "ERROR")
        self.assertIn("invalid test request", response["message"])

    def test_non_dictionary_handler_response_is_replaced(self):
        server_socket, client_socket = socket.socketpair()
        worker = threading.Thread(
            target=handle_connection,
            args=(server_socket, lambda _message: "not a dictionary"),
            daemon=True,
        )
        worker.start()
        with client_socket:
            send_message(client_socket, {"type": "TEST"})
            response = receive_message(client_socket)
        worker.join(timeout=1)
        self.assertEqual(response["type"], "ERROR")


if __name__ == "__main__":
    unittest.main()
