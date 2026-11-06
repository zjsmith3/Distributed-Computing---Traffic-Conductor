import json
import socket

#to send something through a TCP socket we have to format the data in a certain way. This function does that
def encode_message(message): 
    json_string = json.dumps(message)
    json_string += "\n" #appending the \n to mark end of string. 
    encoded_message = json_string.encode("utf-8")

    return encoded_message

#since we encode a message, we gotta decode it back to a json dictionary object. 
def decode_message(data):
    json_string = data.decode("utf-8")
    message = json.loads(json_string)

    return message

#actually sends the message. 
def send_message(connection, message):
    encoded_message = encode_message(message)
    connection.sendall(encoded_message)

#We use this function after sending a message for the response. 
def receive_message(connection):
    data = b""

    while not data.endswith(b"\n"): #TCP communication might not send the entire string at once so you loop.
        chunk = connection.recv(1024)

        if not chunk:
            raise ConnectionError("Connection closed before message completed")

        data += chunk 

    return decode_message(data)

#This combines all the functions above. 
def send_request(host, port, message):
    with socket.create_connection((host,port), timeout=5)as connection:
        send_message(connection, message)
        response = receive_message(connection)

    return response



