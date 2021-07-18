from qkd_devices.QKD import QKD 
from random import randbytes, getrandbits
import asyncio

default_dim = 128


class fakeKE(QKD) : 
    def __init__(self, role:str, port:int, address:str, max_key_count:int, dimension:int=default_dim): 
        if role != 'sender' and role != 'receiver': 
            raise Exception
        
        self.role : str = role 
        self.port : int = port
        self.address : str = address 
        self.dimension : int = int(dimension/8) # from bit to bytes 
        self.key_queue : asyncio.Queue = asyncio.Queue(max_key_count)
        self.stop = [True]
        self.server_task = None 
        self.sender_rw = {'r' : None, 'w' : None }

    
    async def begin(self) -> int: 
        exc = None
        if self.stop[0] == False: 
            return 0
        self.stop[0] = False
        if self.role == 'receiver' : 
            try: 
                server = await asyncio.start_server(self.receive, '0.0.0.0', self.port)
                self.server_task = asyncio.create_task(server.serve_forever())
                return 0
            except Exception as e: 
                print(e)
                return 1

        if self.role == 'sender' : 
            
            for i in range(10) : 
                try: 
                    reader, writer = await asyncio.open_connection(self.address, self.port)
                    self.sender_rw['r'] = reader
                    self.sender_rw['w'] = writer
                    print("QKD DEVICE: sender started")
                    return 0 
                except Exception as e:
                    exc = e
                    await asyncio.sleep(2) # wait and then retry 
        print(exc)
        return 1 # after 10 times fail 
        
    async def receive(self, reader : asyncio.StreamReader, writer : asyncio.StreamWriter) : 
        print("FAKE KE: RECEIVED A CONNECTION")
        while (not self.stop[0]): 
            data = await reader.read(self.dimension+int(32/8)) 
            key = data[0:self.dimension] 
            id = int.from_bytes(data[self.dimension:], 'big')
            data = (id, key)
            await self.key_queue.put(data)
            print("FAKE KE: PUSHING DATA")

        writer.close()
        await writer.wait_closed()

    async def exchangeKey(self) -> tuple[bytes,int,int]: 
        if self.stop[0]:
            return None, -1, 1 

        data = b''
        try: 
            if self.role == 'sender' : 
                print("FAKE KE: SENDER READY TO SEND")
                writer : asyncio.StreamWriter = self.sender_rw['w']
                id : int = getrandbits(32) 
                key : bytes = randbytes(self.dimension)
                data = key + id.to_bytes(int(32/8), 'big')
                writer.write(data)
                print("FAKE KE: WRITING DATA")
                return key, id, 0
            elif self.role == 'receiver': 
                print("FAKE KE: RECEIVER READY TO POP")
                id, key = await self.key_queue.get()
                print("FAKE KE: popping data")
                return key, id, 0
        except Exception as e:
            print(e) 
            return None, -1, 1 

    async def end(self): 
        self.stop[0] = True
        if self.role == 'receiver':
            self.server_task.cancel()


 



        