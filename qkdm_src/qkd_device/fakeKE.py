from qkd_device.QKD import QKD 
from threading import Thread, Event
from queue import Queue
from socket import socket 
from random import randbytes
from time import sleep

default_dim = 128

def receive(socket:socket, dimension:int, stop:list, key_queue:Queue) : 
    socket.listen(5)
    client, addr = socket.accept()
    print("RECEIVER: server started")
    while (not stop[0]): 
        key = b''
        while len(key) < dimension:
            key += client.recv(dimension)
            key_queue.put(key)
    client.close()


class fakeKE(QKD) : 
    def __init__(self, role:str, port:int, address:str, max_key_count:int, dimension:int=default_dim): 
        self.role : str = role 
        self.port : int = port
        self.address : str = address 
        self.dimension : int = int(dimension/8) # from bit to bytes 
        self.key_queue : Queue = Queue(max_key_count)
        self.listener : Thread = None 
        self.stop = [True]
        self.socket =  socket()  

    
    def begin(self) -> int: 
        if self.stop[0] == False: 
            return 
        self.stop[0] = False
        try: 
            if self.role == 'receiver' : 
                self.socket.bind((self.address, self.port))
                self.listener = Thread(target=receive, args=(self.socket, self.dimension, self.stop, self.key_queue)).start() 
            if self.role == 'sender' : 
                self.socket.connect((self.address, self.port))
                sleep(2) # wait the other peer to start
            return 0 
        except Exception: 
            return 1

    def exchangeKey(self) -> tuple[bytes,int]: 
        if self.stop[0]: 
            return None, 1 

        try: 
            if self.role == 'sender' : 
                data = randbytes(self.dimension)
                sleep(0.1)
                self.socket.sendall(data)
                return data, 0
            elif self.role == 'receiver': 
                key = self.key_queue.get()
                return key, 0
        except Exception: 
            return None, 1 

    def end(self): 
        if self.listener is not None: 
            self.stop[0] = True
            self.listener.join()


 



        