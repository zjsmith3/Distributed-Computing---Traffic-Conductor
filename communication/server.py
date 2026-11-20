"""Small threaded TCP server shared by the Coordinator and Road Nodes."""

import logging
import socket
import threading

from communication.protocol import receive_message, send_message


def start_server(host, port, message_handler):
    """Listen for requests and give each connection its own handler thread."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()
        print(f"Listening on {host}:{port}")

        while True:
            connection, address = server.accept()
            thread = threading.Thread(
                target=handle_connection,
                args=(connection, message_handler),
                daemon=True,
                name=f"client-{address[0]}-{address[1]}",
            )
            thread.start()


def handle_connection(connection, message_handler):
    """Handle one complete request without letting a bad client kill the thread."""
    with connection:
        try:
            message = receive_message(connection)
            response = message_handler(message)
            if not isinstance(response, dict):
                response = {"type": "ERROR", "message": "Message handler returned an invalid response."}
        except Exception as error:
            logging.exception("Error while handling a TCP request")
            response = {"type": "ERROR", "message": str(error)}

        try:
            send_message(connection, response)
        except (OSError, ConnectionError):
            logging.debug("Client disconnected before the response could be sent.")
