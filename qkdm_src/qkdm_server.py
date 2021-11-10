from quart import request, Quart 
import asyncio
import api
import argparse
import logging

import nest_asyncio
nest_asyncio.apply()

app = Quart(__name__)
serverPort = 5000
prefix = "/api/v1/qkdm/actions"

logging.basicConfig(filename='qkdm.log', filemode='w', level=logging.INFO)

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
            13: "Unable to complete registration to requested QKS", # Not in ETSI standard
            14: "OIDC error : unable to authenticate" } # Not in ETSI standard

# SOUTHBOUND INTERFACE 
@app.route(prefix+"/open_connect", methods=['POST'])
async def open_connect() :
    content = await request.get_json()
    try: 
        source = str(content['source'])
        destination = str(content['destination'])
        key_stream_ID = content['key_stream_ID'] if 'key_stream_ID' in content else None 
        qos_parameters = content['qos_parameters'] if 'qos_parameters' in content else None 

        status, key_stream_ID = await api.OPEN_CONNECT(source, destination, key_stream_ID, qos_parameters)
        app.logger.info(f"open_connect returning: status = {status} , key_stream_ID = {key_stream_ID}")
        if status == 0: 
            value = {'status' : status, 'key_stream_ID' : key_stream_ID}
            return value, 200
        else: 
            value = {'status' : status, 'message' : messages[status]}
            return value, 503
    except Exception as e:
        app.logger.warning(f"open_connect EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400 

@app.route(prefix+"/close", methods=['POST'])
async def close() : 
    content = await request.get_json()
    try: 
        key_stream_ID = str(content['key_stream_ID'] )
        status = await api.CLOSE(key_stream_ID)
        value = {'status' : status, 'message' : messages[status]}
        app.logger.info(f"close returning: status = {status} , key_stream_ID = {key_stream_ID}")
        if status == 0:
            return value, 200
        else: 
            return value, 503
    except Exception as e:
        app.logger.warning(f"close EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400 

@app.route(prefix+"/get_key", methods=['POST'])
async def get_key(): 
    content = await request.get_json() 
    try:
        key_stream_ID = str(content['key_stream_ID'] )
        req_indexes = list(content['indexes']) 
        metadata = content['metadata'] if 'metadata' in content else None 

        status, indexes, keys = await api.GET_KEY(key_stream_ID, req_indexes, metadata) 
        app.logger.info(f"get_key returning: status = {status} , key_stream_ID = {key_stream_ID}, indexes = {req_indexes}")
        if status == 0: 
            value = {'status' : status, 'indexes' : indexes, 'keys' : keys}
            return value, 200
        else :
            value = {'status' : status, 'message' : messages[status]}
            return value, 503
    except Exception as e:
        app.logger.warning(f"get_key EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400 

@app.route(prefix+"/get_id/<key_stream_ID>", methods=['GET'])
async def get_key_id(key_stream_ID): 
    param = request.args.get('count') # n -> list[n:], -1 -> list[::], None -> len(list[::])
    key_stream_ID = str(key_stream_ID)
    try: 
        count = -1 if param is None else int(param)
        status, index_list = await api.GET_KEY_ID(key_stream_ID, count)
        app.logger.info(f"get_key_id returning: status = {status} , key_stream_ID = {key_stream_ID}, query_param = {param}, len = {len(index_list)}")
        if status == 0: 
            value = {'status' : status, 
                'available_indexes' : len(index_list) if param == None else index_list}
            return value, 200
        else: 
            value = {'status' : status, 'message' : messages[status]}
            return value, 503

    except Exception as e: 
        app.logger.warning(f"get_key_id EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid argument"}
        return value, 400 


@app.route(prefix+"/check_id", methods=['POST'])
async def check_id(): 
    content = await request.get_json() 
    try:
        key_stream_ID =  str(content['key_stream_ID'])
        indexes = list(content['indexes'])
        
        status = await api.CHECK_ID(key_stream_ID, indexes)
        app.logger.info(f"check_id returning: status = {status} , key_stream_ID = {key_stream_ID}, indexes = {indexes}")
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            return value, 200
        else: 
            return value, 503

    except Exception as e:
        app.logger.warning(f"check_id EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400

@app.route(prefix+"/attach", methods=['POST'])
async def attach_to_server() :
    content = await request.get_json() 
    try:
        qks_src_ip = str(content['qks_src_IP']) 
        qks_src_port = int(content['qks_src_port']) 
        qks_src_id = str(content['qks_src_ID']) 
        qks_dest_id = str(content['qks_dest_ID']) 

        status = await api.attachToServer(qks_src_ip, qks_src_port, qks_src_id, qks_dest_id)
        value = {'status' : status, 'message' : messages[status]}
        if status == 0: 
            app.logger.info(f"attach_to_server returning: status = {status} , qks_src_id = {qks_src_id}")
            return value, 200
        else: 
            app.logger.warning(f"attach_to_server error: status = {status} , qks_src_id = {qks_src_id}")
            return value, 503
    except Exception as e: 
        app.logger.warning(f"attach_to_server EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400


# SYNC INTERFACE
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
            app.logger.info(f"open_stream returning: status = {status} , key_stream_ID = {key_stream_ID}, destination = {destination}")
            return value, 200
        else: 
            app.logger.warning(f"open_stream error: status = {status} , key_stream_ID = {key_stream_ID}, destination = {destination}")
            return value, 503
    except Exception as e:
        app.logger.warning(f"open_stream EXCEPTION: {e}")
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
            app.logger.info(f"exchange returning: status = {status} , key_stream_ID = {key_stream_ID}")
            return value, 200
        else: 
            app.logger.warning(f"exchange error: status = {status} , key_stream_ID = {key_stream_ID}")
            return value, 503
    except Exception as e:
        app.logger.warning(f"exchange EXCEPTION: {e}")
        value = {'message' : "bad request: request does not contains a valid json object"}
        return value, 400


async def main():
    global app, serverPort
    try: 
        parser = argparse.ArgumentParser()
        parser.add_argument('-server', type=str, choices=['true', 'false'], help="defines QKS presence. If not specified QKDM will run as standalone module, if specified as 'true' qkdm will require for an 'attach_to_server' request for configuration")
        parser.add_argument('-reset', type=str, choices=['true', 'false'], help="forcethe reset of information received from a QKS registration")
        parser.add_argument('-config', type=str, help="name of the custom config file", default=None)
        args = parser.parse_args()
        server = True if args.server == 'true' else False 
        reset = True if args.reset == 'true' else False 
        config_file = args.config 
        app.logger.info(f"QKDM starting with: server : {server} - reset : {reset} - config: {config_file}")
    except:
        app.logger.error(f"QKDM ERROR: unable to parse arguments")
        return
    
    try: 
        app.logger.info("Init process started")
        res, message, serverPort = await api.init_module(server, reset, config_file)

        if res != 0 and res != 1  : 
            app.logger.error(f"ABORT: unable to init the module - ERROR {message}")
            return 
        else: 
            app.logger.info(f"INIT module - {message}")
    except Exception as e: 
        app.logger.error(f"ABORT: unable to init the module - EXCEPTION {e}")
        return

    app.run(host='0.0.0.0', port=serverPort, loop = asyncio.get_event_loop())



if __name__ == "__main__":
	asyncio.run(main())
