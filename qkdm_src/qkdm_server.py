from flask import request, Flask 
import requests
import api
import json
import sys 

app = Flask(__name__)
serverPort = 5000
prefix = "/api/v1/qkdm/actions"

messages = {0: "successfull",
            1: "Successful connection, but peer not connected",
            2: "GET_KEY failed because insufficient key available",
            3: "GET_KEY failed because peer application is not yet connected",
            4: "No QKD connection available", 
            5: "OPEN_CONNECT failed because the KSID is already in use",
            6: "TIMEOUT_ERROR The call failed because the specified TIMEOUT",
            7: "OPEN failed because requested QoS settings could not be met", 
            8: "GET_KEY failed because metadata field size insufficient",
            9: "Failed because KSID is not valid", # Not in ETSI standard
            10: "CHECK_ID failed because some ids are not available" } # Not in ETSI standard

# SOUTHBOUND INTERFACE 
@app.route(prefix+"/open_connect", methods=['POST'])
def open_connect() :
    content = request.get_json()
    if (type(content) is dict) and 'source' in content and 'destination' in content: 
        source = content['source'] if type(content['source']) is str else None
        destination = content['destination'] if type(content['destination']) is str else None
        key_stream_ID = content['key_stream_ID'] if 'key_stream_ID' in content and type(content['key_stream_ID']) is str else None 
        qos_parameters = content['qos_parameters'] if 'qos_parameters' in content else None 

        if source is not None and destination is not None: 
            status, key_stream_ID = api.OPEN_CONNECT(source, destination, key_stream_ID, qos_parameters)
            if status == 0: 
                value = {'status' : status, 'key_stream_ID' : key_stream_ID}
                return value, 200
            else: 
                value = {'status' : status, 'message' : messages[status]}
                return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400 

@app.route(prefix+"close", methods=['POST'])
def close() : 
    content = request.get_json()
    if (type(content) is dict) and ('key_stream_ID' in content): 
        key_stream_ID = content['key_stream_ID'] if type(content['key_stream_ID']) is str else None
        if key_stream_ID is not None: 
            status = api.CLOSE(key_stream_ID)
            value = {'status' : status, 'message' : messages[status]}
            if status == 0:
                return value, 200
            else: 
                return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400 

@app.route(prefix+"get_key", methods=['POST'])
def get_key(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content): 
        key_stream_ID = content['key_stream_ID'] if type(content['key_stream_ID']) is str else None
        index = content['index'] if 'index' and type(content['key_stream_ID']) is int in content else None 
        metadata = content['metadata'] if 'metadata' in content else None 

        if key_stream_ID is not None: 
            status, index, key = api.GET_KEY(key_stream_ID, index, metadata) 
            if status == 0: 
                value = {'status' : status, 'index' : index, 'key' : key}
                return value, 200
            else :
                value = {'status' : status, 'message' : messages[status]}
                return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400 

@app.route(prefix+"get_id/<key_stream_ID>", methods=['GET'])
def get_key_id(key_stream_ID): 
    aggregate = request.args.get('aggregate')
    key_stream_ID = str(key_stream_ID)
    if aggregate == 'true' or aggregate is None: 
        status, index_list = api.GET_KEY_ID(key_stream_ID)
        if status == 0: 
            value = {'status' : status, 
                'available_indexes' : len(index_list) if aggregate is not None else index_list}
            return value, 200
        else: 
            value = {'status' : status, 'message' : messages[status]}
            return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400 


@app.route(prefix+"check_id", methods=['POST'])
def check_id(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content) and ('indexes' in content):
        if (type(content['indexes']) is list): 
            key_stream_ID =  content['key_stream_ID']
            indexes = content['indexes']
            
            status = api.CHECK_ID(key_stream_ID, indexes)
            value = {'status' : status, 'message' : messages[status]}
            if status == 0: 
                return value, 200
            else: 
                return value, 503
    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400

@app.route(prefix+"attach", methods=['POST'])
def attachToServer() :
    content = request.get_json() 
    if (type(content) is dict) and ('qks_IP' in content):
        qks_ip = str(content['qks_IP'])
        status = api.attachToServer(qks_ip)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400


# QKDM INTERFACE
@app.route(prefix+"open_stream", methods=['POST'])
def open_stream(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = str(content['key_stream_ID'])
        status = api.open_stream(key_stream_ID)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400

@app.route(prefix+"close_stream", methods=['POST'])
def close_stream(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = str(content['key_stream_ID'])
        status = api.close_stream(key_stream_ID)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400

@app.route(prefix+"exchange", methods=['POST'])
def exchange(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = str(content['key_stream_ID'])
        status = api.exchange(key_stream_ID)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400


def main():
    global app, serverPort

    if (len(sys.argv) > 1) : 
        try: 
            serverPort = int(sys.argv[1])
            if (serverPort < 0 or serverPort > 2**16 - 1):
                raise Exception
        except Exception: 
            print("ERROR: use 'python3 appname <port>', port must be a valid port number")

    res, message = api.init_module()
    print(message)

    app.run(host='0.0.0.0', port=serverPort)
    return

if __name__ == "__main__":
	main()
