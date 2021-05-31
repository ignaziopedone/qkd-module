from qkd_device.QKD import QKD 
from threading import Thread, Event
from queue import Queue
from socket import socket 
from random import randbytes, getrandbits
from time import sleep

default_dim = 128

def receive(socket:socket, dimension:int, stop:list, key_queue:Queue) : 
    socket.listen(5)
    print("QKD DEVICE: receiver started")
    client, addr = socket.accept()
    while (not stop[0]): 
        data = client.recv(dimension+int(32/8)) 
        key = data[0:dimension] 
        id = int.from_bytes(data[dimension:], 'big')
        data = (id, key)
        key_queue.put(data)

    client.close()


class fakeKE(QKD) : 
    def __init__(self, role:str, port:int, address:str, max_key_count:int, dimension:int=default_dim): 
        if role != 'sender' and role != 'receiver': 
            raise Exception
        
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
            return 0
        self.stop[0] = False
        if self.role == 'receiver' : 
            try: 
                self.socket.bind((self.address, self.port))
                self.listener = Thread(target=receive, args=(self.socket, self.dimension, self.stop, self.key_queue)).start() 
                return 0
            except Exception: 
                return 1

        if self.role == 'sender' : 
            for i in range(10) : 
                try: 
                    self.socket.connect((self.address, self.port))
                    print("QKD DEVICE: sender started")
                    return 0 
                except Exception: 
                    sleep(2) # wait and then retry 
        return 1 # after 10 times fail 
        

    def exchangeKey(self) -> tuple[bytes,int,int]: 
        if self.stop[0]: 
            return None, -1, 1 

        data = b''
        try: 
            if self.role == 'sender' : 
                id : int = getrandbits(32) 
                key : bytes = randbytes(self.dimension)
                data = key + id.to_bytes(int(32/8), 'big')
                sleep(0.1)
                self.socket.sendall(data)
                return key, id, 0
            elif self.role == 'receiver': 
                id, key = self.key_queue.get()
                return key, id, 0
        except Exception: 
            return None, -1, 1 

    def end(self): 
        if self.listener is not None: 
            self.stop[0] = True
            self.listener.join()


 



        