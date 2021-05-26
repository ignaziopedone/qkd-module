import requests
import qkd_device.QKD
from uuid import uuid4
from vaultClient import Client as VaultClient 
from pymongo import MongoClient
import yaml

vault_client : VaultClient = None 
mongo_client : MongoClient = None 

mongo_db = {}
vault = {} 


config_file = open("qkdm_src/config.yaml", 'r') 
prefs = yaml.safe_load(config_file) 
config_file.close() 

qkdm = {
    'id' : prefs['qkdm']['QKDM_ID'],
    'max_key_count' : prefs['qkdm']['MAX_KEY_COUNT'],
    'key_size' : prefs['qkdm']['KEY_SIZE'],
    'protocol' :  prefs['qkdm']['protocol'],
    'destination_QKS' : prefs['qkdm']['destination_QKS'],
    'init' : prefs['qkdm']['init']
}



# SOUTHBOUND INTERFACE
# TODO
def OPEN_CONNECT(source:str, destination:str, key_stream_ID:str=None, qos=None) -> tuple[int, str]: 
    
    key_stream_ID = 0
    status = 0  
    return status, key_stream_ID

# TODO
def CLOSE(key_stream_ID:str) -> int: 
    status = 0
    return status

# TODO
def GET_KEY(key_stream_ID:str, index:int=None, metadata=None) -> tuple[int, int, str]: 
    status = 0
    index, key = "", ""
    return (status, index, key)


def GET_KEY_ID(key_stream_ID:str) -> tuple[int, list]:
    global mongo_client
    init = check_init() 
    if init != 0: 
        return 11
        
    if mongo_client is None:
        mongo_client = MongoClient(f"mongodb://{mongodb['user']}:{mongodb['password']}@{mongodb['host']}:{mongodb['port']}/{mongodb['db']}?authSource={mongodb['auth_src']}")
    stream_collection = mongo_client[mongodb['db']]['key_streams'] 

    res = stream_collection.find_one({"_id" : key_stream_ID})
    if res is not None: 
        l = res['available_keys']
        return 0, l 
    else : 
        return 9, []
    

def CHECK_ID(key_stream_ID:str, indexes:list) -> int: 
    global mongo_client
    init = check_init() 
    if init != 0: 
        return 11

    if mongo_client is None:
        mongo_client = MongoClient(f"mongodb://{mongodb['user']}:{mongodb['password']}@{mongodb['host']}:{mongodb['port']}/{mongodb['db']}?authSource={mongodb['auth_src']}")
    stream_collection = mongo_client[mongodb['db']]['key_streams'] 

    res = stream_collection.find_one({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}})
    status = 0 if res is not None else 10
    return status 

# TODO
def attachToServer(qks_src_ip:str, qks_src_id:str, qks_dest_id:str) -> int: 
    # WRITE 'init' : true on config file
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

# MANAGMENT FUNCTIONS 
def register_data(vault_data : dict, db_data : dict) -> tuple[int, str]:
    global vault_client, mongo_client, vault, mongodb

    config_file = open("qkdm_src/config.yaml", 'r') 
    prefs = yaml.safe_load(config_file) 
    config_file.close()

    vault_client = VaultClient(vault_data['host'],vault_data['port'])
    res = vault_client.approle_login(vault_data['role_id'], vault_data['secret_id'])
    token = vault_client.client.token

    if not res: 
        return (-1, "ERROR in received data")

    vault = {
        'host' : vault_data['host'],
        'port' : vault_data['port'], 
        'token' : token
    } 

    mongodb = {
        'host' : db_data['host'],
        'port' : db_data['port'], 
        'user' : db_data['user'],
        'password' : db_data['password'],
        'auth_src' : db_data['auth_src'],
        'db' : db_data['db_name']
    }

    prefs['mongo_db']['host'] = db_data['host']
    prefs['mongo_db']['port'] = db_data['port']
    prefs['mongo_db']['user'] = db_data['user']
    prefs['mongo_db']['password'] = db_data['password']
    prefs['mongo_db']['auth_src'] = db_data['auth_src']
    prefs['mongo_db']['db'] = db_data['db']
    prefs['vault']['host'] = vault_data['host']
    prefs['vault']['port'] = vault_data['port']
    prefs['vault']['token'] = token

    config_file = open("qkdm_src/config.yaml", 'r+') 
    yaml.safe_dump(prefs, config_file, default_flow_style=False)
    config_file.close() 
    return (0, "received data are valid")

def check_init() -> int : # return 1 if everything is ok 
    global qkdm
    if qkdm['init'] is True:
        return 0 
     
    config_file = open("qkdm_src/config.yaml", 'r') 
    prefs = yaml.safe_load(config_file) 
    config_file.close() 

    qkdm['init'] = prefs['qkdm']['init']
    if not qkdm['init']: 
        return 1
    return init_module()[0]

def init_module(server : bool = False , reset : bool = False ) -> tuple[int, str]:
    global vault, mongodb, vault_client, mongo_client, qkdm
    if not server or (not reset and qkdm['init'] == True): 
        config_file = open("qkdm_src/config.yaml", 'r+') 
        prefs = yaml.safe_load(config_file) 
        

        mongodb = {
            'host' : prefs['mongo_db']['host'],
            'port' : prefs['mongo_db']['port'], 
            'user' : prefs['mongo_db']['user'],
            'password' : prefs['mongo_db']['password'],
            'auth_src' : prefs['mongo_db']['auth_src'],
            'db' : prefs['mongo_db']['db_name']
        }

        vault = {
            'host' : prefs['vault']['host'],
            'port' : prefs['vault']['port'], 
            'token' : prefs['vault']['token']
        } 

        vault_client = VaultClient(vault['host'], vault['port'], vault['token']) 
        if not vault_client.connect() :
            config_file.close()
            return (11, "ERROR: unable to connect to Vault")

        try: 
            mongo_client = MongoClient(f"mongodb://{mongodb['user']}:{mongodb['password']}@{mongodb['host']}:{mongodb['port']}/{mongodb['db']}?authSource={mongodb['auth_src']}")
            mongo_client[mongo_db['db']].list_collection_names()
        except Exception: 
            config_file.close()
            return (11, "ERROR: unable to connect to MongoDB")

        
        qkdm['init'] = True 
        prefs['qkdm']['init'] = True
        yaml.safe_dump(prefs, config_file, default_flow_style=False)
        config_file.close()

        message =  "QKDM initialized as standalone component" if not server else "QKDM initialized with QKS data from previous registration"
        return (0, message)
    else: 
        return (1, "QKDM is waiting for registration to a QKS")

