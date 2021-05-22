import requests
#import QKD

# SOUTHBOUND INTERFACE
# TODO
def OPEN_CONNECT(source:str, destination:str, key_stream_ID:str=None, qos=None) -> tuple: 
    
    key_stream_ID = 0
    status = 0  
    return status, key_stream_ID

# TODO
def CLOSE(key_stream_ID:str) -> int: 
    status = 0
    return status

# TODO
def GET_KEY(key_stream_ID:str, index:int=None, metadata=None) -> tuple: 
    status = 0
    index, key = "", ""
    return (status, index, key)

# TODO
def GET_KEY_ID(key_stream_ID:str) -> tuple:
    status = 0
    list = []
    return status, list 

# TODO
def CHECK_ID(key_stream_ID:str, indexes:list) -> int: 
    status = 0, 
    return status 

# TODO
def attachToServer(qks_ip:str) -> int: 
    return 0

# QKDM INTERFACE 
# TODO
def open_stream(key_stream_ID:str) -> int:
    return 0

# TODO
def close_stream(key_stream_ID:str) -> int:
    return 0
    
# TODO
def exchange(key_stream_ID:str) -> int:
    return 0


def main():
    # check everything
    return

if __name__ == "__main__":
	main()