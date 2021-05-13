from flask import request, Flask 
import requests
import json
import sys 

app = Flask(__name__)
serverPort = 5000
prefix = "/api/v1/qkdm/actions"

# SOUTHBOUND INTERFACE 
@app.route(prefix+"/open_connect", methods=['POST'])
def open_connect() :
    content = request.get_json()
    if (type(content) is dict) : 
        source = content['source'] if 'source' in content else None 
        destination = content['destination'] if 'destination' in content else None 
        key_stream_ID = content['key_stream_ID'] if 'key_stream_ID' in content else None 
        qos_parameters = content['qos_parameters'] if 'qos_parameters' in content else None 

        # call function 
        return "ok", 200
    else: 
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 500 

@app.route(prefix+"close", methods=['POST'])
def close() : 
    content = request.get_json()
    if (type(content) is dict) and ('key_stream_ID' in content): 
        key_stream_ID = content['key_stream_ID']
        # call function
        return "ok", 200
    else : 
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 500 

@app.route(prefix+"get_key", methods=['POST'])
def get_key(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content): 
        key_stream_ID = content['key_stream_ID']
        index = content['index'] if 'index' in content else None 
        metadata = content['metadata'] if 'metadata' in content else None 

        # call function
        ind = index if index is not None else 1
        value = {'key' : "key1", 
                'index' : ind,
                'status' : 1, 
                'metadata' : metadata 
            }       
        return value, 200
    else : 
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 500 

@app.route(prefix+"get_id/<key_stream_ID>", methods=['GET'])
def get_key_id(key_stream_ID): 
    key_stream_ID = str(key_stream_ID)
    # call function 
    value = {'key_stream_ID' : key_stream_ID, 
            'indexes' : []}
    return value, 200

@app.route(prefix+"check_id", methods=['POST'])
def check_id(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content) and ('indexes' in content):
        if (type(content['indexes']) is list): 
            key_stream_ID =  content['key_stream_ID']
            indexes = content['indexes']
            # call function
            return True, 200
    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 500

@app.route(prefix+"attach", methods=['POST'])
def attachToServer() :
    content = request.get_json() 
    if (type(content) is dict) and ('qks_IP' in content):
        qks_ip = str(content['qks_IP'])
        return "ok", 200


# QKDM INTERFACE
@app.route(prefix+"open_stream", methods=['POST'])
def open_stream(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = str(content['key_stream_ID'])
        return "ok", 200

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 500

@app.route(prefix+"close_stream", methods=['POST'])
def close_stream(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = str(content['key_stream_ID'])
        return "ok", 200

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 500

@app.route(prefix+"exchange", methods=['POST'])
def exchange(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = str(content['key_stream_ID'])
        return "ok", 200

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 500
