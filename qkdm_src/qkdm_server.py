from flask import request, Flask 
import requests
import api
import argparse

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
            9: "Request failed because KSID not found", # Not in ETSI standard
            10: "CHECK_ID failed because some ids are not available" , # Not in ETSI standard
            11: "Error during QKDM or component initialization", # Not in ETSI standard
            12: "Module already initialized : restart it and force reset if you want to attatch to a new server", # Not in ETSI standard
            13: "Unable to complete registration to requested QKS"} # Not in ETSI standard

# SOUTHBOUND INTERFACE 
@app.route(prefix+"/open_connect", methods=['POST'])
def open_connect() :
    content = request.get_json()
    if (type(content) is dict) and 'source' in content and 'destination' in content: 
        source = content['source'] if type(content['source']) is str else None
        destination = content['destination'] if type(content['destination']) is str else None
        key_stream_ID = content['key_stream_ID'] if 'key_stream_ID' in content and type(content['key_stream_ID']) is str else None 
        qos_parameters = content['qos_parameters'] if 'qos_parameters' in content else None 

        # TODO: CHECK THAT SOURCE == AUTH_SOURCE
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

@app.route(prefix+"/close", methods=['POST'])
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

@app.route(prefix+"/get_key", methods=['POST'])
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

@app.route(prefix+"/get_id/<key_stream_ID>", methods=['GET'])
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


@app.route(prefix+"/check_id", methods=['POST'])
def check_id(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content) and ('indexes' in content):
        if (type(content['indexes']) is list) and (type(content['key_stream_ID']) is str): 
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

@app.route(prefix+"/attach", methods=['POST'])
def attachToServer() :
    content = request.get_json() 
    if (type(content) is dict) and all (k in content for k in ('qks_src_IP', 'qks_src_port', 'qks_src_ID', 'qks_dest_ID')) :
        qks_src_ip = str(content['qks_src_IP']) if type(content['qks_src_IP']) is str else None
        qks_src_port = int(content['qks_src_port']) if type(content['qks_src_port']) is int else None
        qks_src_id = str(content['qks_src_ID']) if type(content['qks_src_ID']) is str else None
        qks_dest_id = str(content['qks_dest_ID']) if type(content['qks_dest_ID']) is str else None

        if all (el is not None for el in [qks_src_ip, qks_src_port, qks_src_id, qks_dest_id]):
            status = api.attachToServer(qks_src_ip, qks_src_port, qks_src_id, qks_dest_id)
            value = {'status' : status, 'message' : messages[status]}
            if status == 0: 
                return value, 200
            else: 
                return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400


# QKDM INTERFACE
@app.route(prefix+"/open_stream", methods=['POST'])
def open_stream(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content) and ('source' in content) and ('destination' in content):
        key_stream_ID = content['key_stream_ID'] if type(content['key_stream_ID']) is str else None
        source = content['source'] if type(content['source']) is str else None
        destination = content['destination'] if type(content['destination']) is str else None
        if  all (el is not None for el in [key_stream_ID, source, destination]) : 
            status = api.open_stream(key_stream_ID, source, destination)
            value = {'status' : status, 'message' : messages[status]}
            if status == 0: 
                return value, 200
            else: 
                return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400

@app.route(prefix+"/close_stream", methods=['POST'])
def close_stream(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = content['key_stream_ID'] if type(content['key_stream_ID']) else None
        if key_stream_ID is not None : 
            status = api.close_stream(key_stream_ID)
            value = {'status' : status, 'message' : messages[status]}
            if status == 0: 
                return value, 200
            else: 
                return value, 503

    value = {'message' : "bad request: request does not contains a valid json object"}
    return value, 400

@app.route(prefix+"/exchange", methods=['POST'])
def exchange(): 
    content = request.get_json() 
    if (type(content) is dict) and ('key_stream_ID' in content):
        key_stream_ID = content['key_stream_ID'] if type(content['key_stream_ID']) else None
        if key_stream_ID is not None : 
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

    parser = argparse.ArgumentParser(usage= '''
    python file_name <port> <standalone> 
    NOTE: python version >= 3.9 is required.  ''')
    parser.add_argument('-port', type=int, help="defines the port number. If not specified Flask will listen on port 5000")
    parser.add_argument('-server', type=str, choices=['true', 'false'], help="defines QKS presence. If not specified QKDM will run as standalone module, if specified as 'true' qkdm will require for an 'attach_to_server' request for configuration")
    parser.add_argument('-reset', type=str, choices=['true', 'false'], help="forcethe reset of information received from a QKS registration")
    args = parser.parse_args()
    if args.port : 
        serverPort = args.port 
    server = True if args.server == 'true' else False 
    reset = True if args.reset == 'true' else False 
    
    try: 
        res, message = api.init_module(server, reset)

        if res != 0 and res != 1  : 
            print("ABORT: unable to init the module due to this error: \n", message )
            return 
        print(message)
    except Exception: 
        print("ABORT: unable to init the module due to an exception")
        return

    app.run(host='0.0.0.0', port=serverPort)
    return


if __name__ == "__main__":
	main()
