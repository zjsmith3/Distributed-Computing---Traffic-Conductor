import socket
import threading
from communication.protocol import receive_message, send_message

#This will start a server if given the host, port, and it's message handler argument, which is how the 
#server will differ between different types of nodes. 
def start_server(host, port, message_handler):
    #This little section creates a socket object named server then binds the host and port and then 
    #will have the server start listening for connections. 
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server: 
        server.bind((host, port))
        server.listen()

        #a print statement if needed for debugging. 
        #print(f"Listening on {host}:{port}")

        #We use a while loop so when it accepts a client it'll start listening again till we stop it. 
        while True:
            connection, address = server.accept()
            print(f"Connection received from {address}")    

            #above is where we essentially catch the connection, below is creating a thread to handle it.
            #
            thread = threading.Thread(target=handle_connection, args=(connection, message_handler), daemon=True)
            thread.start()

#This is where the thread with the message is handled. 
#Each node type will need a list of ways they handle different messages and replies in an object called "message handler"
#and this uses the connection and message handler and the send & recieve message functions from protocol. to enable communicaiton
def handle_connection(connection, message_handler):
    with connection:
        message = receive_message(connection)
        response = message_handler(message)
        send_message(connection, response)

            