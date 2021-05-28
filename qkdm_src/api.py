import requests
import qkd_device.QKD
from uuid import uuid4
from vaultClient import VaultClient 
from pymongo import MongoClient, ReturnDocument
import yaml

vault_client : VaultClient = None 
mongo_client : MongoClient = None 
supported_protocols = ["bb84", "fake"]

config_file_name = "qkdm_src/config.yaml"
config_file = open(config_file_name, 'r') 
config = yaml.safe_load(config_file) 
config_file.close() 

'''
if config['qkdm']['protocol'] == "bb84":
    from qkd_device.BB84 import BB84 as QKDCore 
elif config['qkdm']['protocol'] == "fake":
    from qkd_device.fakeKE import fakeKE as QKDCore
'''

# SOUTHBOUND INTERFACE
def OPEN_CONNECT(source:str, destination:str, key_stream_ID:str=None, qos=None) -> tuple[int, str]: 
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return (11, "")

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
    if key_stream_ID is not None: 
        key_stream = key_streams_collection.find_one({"_id" : key_stream_ID}) 
    else: 
        key_stream = None 


    if key_stream is None: # open new stream 
        if key_stream_ID is None: 
            key_stream_ID = str(uuid4()) 
        
        key_stream = {
            "_id" : key_stream_ID, 
            "available_keys" : [], 
            "src_id" : source, 
            "dest_id" : destination, 
            "qos" : qos, 
            "status" : "waiting"
        }
        
        try: 
            post_data = {
                'key_stream_ID' : key_stream_ID,
                'source' : source,
                'destination' : destination
            }
            res = requests.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/open_stream", json=post_data)
            if res.status_code == 200:
                key_streams_collection.insert_one(key_stream)
                return (0, key_stream_ID)
            else: 
                status = res.json()['status']
                return (status, key_stream_ID)
        except Exception: 
            return (1, key_stream_ID)

    else: # key_stream not none 
        if key_stream['status'] == "waiting" and key_stream['src_id'] == source and key_stream['dest_id'] == destination: # ok 
            try: 
                post_data = {"key_stream_ID" : key_stream_ID}
                res = requests.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/exchange", json=post_data)
                if res.status_code == 200: 
                    key_streams_collection.update_one({"_id" : key_stream_ID},{"$set" : {"status" : "exchanging", "qos" : qos}})
                    return (0, key_stream_ID)
                else: 
                    status = res.json()['status']
                    return (status, key_stream_ID)
            except Exception: 
                return (1, key_stream_ID)
        else: # found a ksid in use 
            return (5, key_stream_ID)
 

def CLOSE(key_stream_ID:str) -> int: 
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11

    stream_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    stream = stream_collection.find_one({"_id" : key_stream_ID})
    if stream is None: 
        return 9
    
    try: 
        data = {'key_stream_ID' : key_stream_ID}
        res = requests.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/close_stream", json=data)
        if res.status_code == 200: 
            stream_collection.delete_one({"_id" : key_stream_ID})
            return 0
        else: 
            return 9
    except Exception: 
        return 1


def GET_KEY(key_stream_ID:str, indexes: list, metadata=None) -> tuple[int, dict]: 
    
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11, {}

    stream_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    stream = stream_collection.find_one({"_id" : key_stream_ID})
    if stream is None: 
        return (9, {})

    res = stream_collection.find_one_and_update({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}}, {"$pull" : {"available_keys", indexes}})
    keys = {}
    if res is not None: 
        for index in indexes:
            path = key_stream_ID + index
            ret = vault_client.readAndRemove(mount=config['vault']['secret_engine'], path=path, id=index)
            keys[index] = ret[index]
        return (0, keys)
    
    return (2, {})
            

def GET_KEY_ID(key_stream_ID:str, count:int = -1) -> tuple[int, list]:
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11, []
        
    stream_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 

    res = stream_collection.find_one({"_id" : key_stream_ID})
    if res is not None: 
        c = count if count != -1 else len(res['available_keys'])
        l = res['available_keys'][:c] 
        return 0, l 
    else : 
        return 9, []
    

def CHECK_ID(key_stream_ID:str, indexes:list) -> int: 
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11

    stream_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 

    res = stream_collection.find_one({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}})
    status = 0 if res is not None else 10
    return status 

def attachToServer(qks_src_ip:str, qks_src_port:int, qks_src_id:str, qks_dest_id:str) -> int: 
    global config
    if check_init() == 0: 
        return 12
    
    qks_data = {
        'src_id' : qks_src_id, 
        'src_ip' : qks_src_ip,
        'src_port' : qks_src_port,
        'dest_id' : qks_dest_id
    }

    post_data = { 
        'QKDM_ID' : config['qkdm']['ID'], 
        'protocol' : config['qkdm']['protocol'],
        'QKDM_IP' : config['qkdm']['IP'],
        'QKDM_port' : 0, 
        'reachable_QKS' : "", 
        'reachable_QKDM' : "",
        'max_key_count' : 0, 
        'key_size' : 0
    }

    response = requests.post(f"http://{qks_src_ip}:{qks_src_port}/api/v1/qkdms", json=post_data)
    
    if response.status_code != 200 : 
        return 13

    res_data = response.json() 

    ret = register_data(res_data['vault_data'], res_data['database_data'], qks_data)
    if ret == 0: 
        ret, _ = init_module(server=True, reset=False)    
    return ret 
    

# QKDM INTERFACE 
def open_stream(key_stream_ID:str, source:str, destination:str) -> int:
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
    key_stream = key_streams_collection.find_one({"_id" : key_stream_ID}) 

    if key_stream is None: 
        key_stream = {
            "_id" : key_stream_ID, 
            "available_keys" : [], 
            "src_id" : source, 
            "dest_id" : destination, 
            "qos" : None, 
            "status" : "waiting"
        } 

        key_streams_collection.insert_one(key_stream)
        return 0 
    else: 
        return 9 


def close_stream(key_stream_ID:str) -> int:
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11

    stream_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    res = stream_collection.delete_one({"_id" : key_stream_ID})
    # if res.deleted_count == 1:  
    return 0 # return ok even if the stream has already beed closed in this peer to keep consistency
    
    
# TODO
def exchange(key_stream_ID:str) -> int:
    global mongo_client, config
    init = check_init() 
    if init != 0: 
        return 11

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
    key_stream = key_streams_collection.find_one({"_id" : key_stream_ID}) 

    if key_stream is None: 
        return 9 
    else: 
        key_streams_collection.update_one({"_id" : key_stream_ID}, {"$set" : {"status" : "exchanging"}})
        # TODO: START QKDM CORE ON ANOTHER THREAD 
        return 0

# MANAGMENT FUNCTIONS 
def register_data(vault_data : dict, db_data : dict, qks_data: dict) -> int:
    global vault_client, config
    
    vault_client = VaultClient(vault_data['host'],vault_data['port'])
    res = vault_client.approle_login(vault_data['role_id'], vault_data['secret_id'])
    
    if not res: 
        return 11

    config['vault'] = {
        'host' : vault_data['host'],
        'port' : vault_data['port'], 
        'token' : vault_client.client.token,
        'secret_engine' : vault_data['secret_engine']
    } 

    config['mongo_db'] = {
        'host' : db_data['host'],
        'port' : db_data['port'], 
        'user' : db_data['username'],
        'password' : db_data['password'],
        'auth_src' : db_data['auth_src'],
        'db' : db_data['db_name']
    }

    config['qks'] = {
        'src_id' : qks_data['src_id'],
        'src_ip' : qks_data['src_ip'],
        'src_port' : qks_data['src_port'],
        'dest_id' :  qks_data['dest_id']
    }

    config_file = open(config_file_name, 'r+') 
    yaml.safe_dump(config, config_file, default_flow_style=False)
    config_file.close() 
    return 0

def check_init() -> int : # return 1 if everything is ok 
    global config
    if config['qkdm']['init'] is True:
        return 0 
     
    config_file = open(config_file_name, 'r') 
    prefs = yaml.safe_load(config_file) 
    config_file.close() 

    config['qkdm']['init'] = prefs['qkdm']['init']
    if not config['qkdm']['init']: 
        return 1
    return init_module()[0]

def init_module(server : bool = False , reset : bool = False ) -> tuple[int, str]:
    global vault_client, mongo_client, config, supported_protocols

    if config['qkdm']['protocol'] not in supported_protocols: 
        return (4, "ERROR: UNSUPPORTED QKD PROTOCOL")

    if not server or (server and not reset): 
        config_file = open(config_file_name, 'r+') 
        config = yaml.safe_load(config_file) 

        if not server :
            config.pop("qks", None)

        vault_client = VaultClient(config['vault']['host'], config['vault']['port'], config['vault']['token']) 
        if not vault_client.connect() :
            config_file.close()
            return (11, "ERROR: unable to connect to Vault")

        try: 
            mongo_client = MongoClient(f"mongodb://{config['mongo_db']['user']}:{config['mongo_db']['password']}@{config['mongo_db']['host']}:{config['mongo_db']['port']}/{config['mongo_db']['db']}?authSource={config['mongo_db']['auth_src']}")
            mongo_client[config['mongo_db']['db']].list_collection_names()
        except Exception: 
            config_file.close()
            return (11, "ERROR: unable to connect to MongoDB")

        
        config['qkdm']['init'] = True 
        config_file.seek(0, 0)
        yaml.safe_dump(config, config_file, default_flow_style=False)
        config_file.close()

        message =  "QKDM initialized as standalone component" if not server else "QKDM initialized with QKS data from previous registration"
        return (0, message)
    else: 
        return (1, "QKDM is waiting for registration to a QKS")

