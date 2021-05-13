
# SOUTHBOUND INTERFACE
def OPEN_CONNECT(source, destination, key_stream_ID=None, qos=None): 
    return 

def CLOSE(key_stream_ID): 
    return 

def GET_KEY(key_stream_id, index=None, metadata=None): 
    return 

def GET_KEY_ID(key_stream_id, aggregate=False):
    return 

def CHECK_ID(key_stream_ID, indexes): 
    return 

def attachToServer(qks_ip): 
    return 

# QKDM INTERFACE 
def open_stream(key_stream_ID):
    return 

def close_stream(key_stream_ID):
    return 

def exchange(key_stream_ID):
    return 