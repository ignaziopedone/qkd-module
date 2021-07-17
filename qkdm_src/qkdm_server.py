from quart import request, Quart 
import asyncio
import api
import argparse

import nest_asyncio
nest_asyncio.apply()

app = Quart(__name__)
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
async def open_connect() :
    content = await request.get_json()
    try: 
        source = str(content['source'])
        destination = str(content['destination'])
        key_stream_ID = content['key_stream_ID'] if 'key_stream_ID' in content else None 
        qos_parameters = content['qos_parameters'] if 'qos_parameters' in content else None 

        # TODO: CHECK THAT SOURCE == AUTH_SOURCE

        status, key_stream_ID = await api.OPEN_CONNECT(source, destination, key_stream_ID, qos_parameters)
        if status == 0: 
            value = {'status' : status, 'key_stream_ID' : key_stream_ID}
            return value, 200
        else: 
            value = {'status' : status, 'message' : messages[status]}
            return value, 503
    except Exception:
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400 

@app.route(prefix+"/close", methods=['POST'])
async def close() : 
    content = await request.get_json()
    try: 
        key_stream_ID = str(content['key_stream_ID'] )
        status = await api.CLOSE(key_stream_ID)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0:
            return value, 200
        else: 
            return value, 503
    except Exception:
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400 

@app.route(prefix+"/get_key", methods=['POST'])
async def get_key(): 
    content = await request.get_json() 
    try:
        key_stream_ID = str(content['key_stream_ID'] )
        indexes = list(content['indexes']) 
        metadata = content['metadata'] if 'metadata' in content else None 

        status, indexes, keys = await api.GET_KEY(key_stream_ID, indexes, metadata) 
        if status == 0: 
            value = {'status' : status, 'indexes' : indexes, 'keys' : keys}
            return value, 200
        else :
            value = {'status' : status, 'message' : messages[status]}
            return value, 503
    except:
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400 

@app.route(prefix+"/get_id/<key_stream_ID>", methods=['GET'])
async def get_key_id(key_stream_ID): 
    param = request.args.get('count') # n -> list[n:], -1 -> list[::], None -> len(list[::])
    key_stream_ID = str(key_stream_ID)
    try: 
        count = -1 if param is None else int(param)
        status, index_list = await api.GET_KEY_ID(key_stream_ID, count)
        if status == 0: 
            value = {'status' : status, 
                'available_indexes' : len(index_list) if param == None else index_list}
            return value, 200
        else: 
            value = {'status' : status, 'message' : messages[status]}
            return value, 503

    except Exception: 
        value = {'message' : "bad request: request does not contains a valid argument"}
        return value, 400 


@app.route(prefix+"/check_id", methods=['POST'])
async def check_id(): 
    content = await request.get_json() 
    try:
        key_stream_ID =  str(content['key_stream_ID'])
        indexes = list(content['indexes'])
        
        status = await api.CHECK_ID(key_stream_ID, indexes)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503

    except Exception:
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400

@app.route(prefix+"/attach", methods=['POST'])
async def attachToServer() :
    content = await request.get_json() 
    try:
        qks_src_ip = str(content['qks_src_IP']) 
        qks_src_port = int(content['qks_src_port']) 
        qks_src_id = str(content['qks_src_ID']) 
        qks_dest_id = str(content['qks_dest_ID']) 

        status = await api.attachToServer(qks_src_ip, qks_src_port, qks_src_id, qks_dest_id)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503
    except Exception as e: 
        print(e)
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400


# QKDM INTERFACE
@app.route(prefix+"/open_stream", methods=['POST'])
async def open_stream(): 
    content = await request.get_json() 
    try:
        key_stream_ID = str(content['key_stream_ID']) 
        source = str(content['source'])
        destination = str(content['destination'])
        status = await api.open_stream(key_stream_ID, source, destination)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503
    except Exception:
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400


@app.route(prefix+"/exchange", methods=['POST'])
async def exchange(): 
    content = await request.get_json() 
    try:    
        key_stream_ID = str(content['key_stream_ID'] )
        status = await api.exchange(key_stream_ID)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503
    except Exception:
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400


async def main():
    global app, serverPort

    parser = argparse.ArgumentParser()
    parser.add_argument('-server', type=str, choices=['true', 'false'], help="defines QKS presence. If not specified QKDM will run as standalone module, if specified as 'true' qkdm will require for an 'attach_to_server' request for configuration")
    parser.add_argument('-reset', type=str, choices=['true', 'false'], help="forcethe reset of information received from a QKS registration")
    parser.add_argument('-config', type=str, help="name of the custom config file", default=None)
    args = parser.parse_args()
    server = True #if args.server == 'true' else False 
    reset = True #if args.reset == 'true' else False 
    config_file = args.config 

    try: 
        res, message, serverPort = await api.init_module(server, reset, config_file)

        if res != 0 and res != 1  : 
            print("ABORT: unable to init the module due to this error: \n", message )
            return 
        print(message)
    except Exception as e: 
        print("ABORT: unable to init the module due to an exception")
        print(e)
        return

    print("QKDM SERVER: starting on port", serverPort)
    app.run(host='0.0.0.0', port=serverPort, loop = asyncio.get_event_loop())



if __name__ == "__main__":
	asyncio.run(main())
