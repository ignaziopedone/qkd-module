import requests
import qkd_device.QKD
from uuid import uuid4
from vaultClient import VaultClient 
from pymongo import MongoClient
import yaml

vault_client : VaultClient = None 
mongo_client : MongoClient = None 

mongodb = {}
vault = {} 
qks = {}


config_file = open("qkdm_src/config.yaml", 'r') 
prefs = yaml.safe_load(config_file) 
config_file.close() 

qkdm = {
    'id' : prefs['qkdm']['QKDM_ID'],
    'ip' : prefs['qkdm']['QKDM_IP'],
    'port' : prefs['qkdm']['QKDM_port'],
    'max_key_count' : prefs['qkdm']['MAX_KEY_COUNT'],
    'key_size' : prefs['qkdm']['KEY_SIZE'],
    'protocol' :  prefs['qkdm']['protocol'],
    'destination_QKDM' : prefs['qkdm']['destination_QKDM'],
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

    stream_collection = mongo_client[mongodb['db']]['key_streams'] 

    res = stream_collection.find_one({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}})
    status = 0 if res is not None else 10
    return status 

def attachToServer(qks_src_ip:str, qks_src_port:int, qks_src_id:str, qks_dest_id:str) -> int: 
    global qkdm
    if check_init() == 0: 
        return 12
    
    qks_data = {
        'src_id' : qks_src_id, 
        'src_ip' : qks_src_ip,
        'src_port' : qks_src_port,
        'dest_id' : qks_dest_id
    }

    post_data = { 
        'QKDM_ID' : qkdm['id'], 
        'protocol' : qkdm['protocol'],
        'QKDM_IP' : qkdm['ip'],
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
def register_data(vault_data : dict, db_data : dict, qks_data: dict) -> int:
    global vault_client, vault, mongodb, qks

    config_file = open("qkdm_src/config.yaml", 'r+') 
    prefs = yaml.safe_load(config_file) 
    
    vault_client = VaultClient(vault_data['host'],vault_data['port'])
    res = vault_client.approle_login(vault_data['role_id'], vault_data['secret_id'])
    
    if not res: 
        config_file.close()
        return 11

    vault = {
        'host' : vault_data['host'],
        'port' : vault_data['port'], 
        'token' : vault_client.client.token,
        'secret_engine' : vault_data['secret_engine']
    } 

    mongodb = {
        'host' : db_data['host'],
        'port' : db_data['port'], 
        'user' : db_data['username'],
        'password' : db_data['password'],
        'auth_src' : db_data['auth_src'],
        'db' : db_data['db_name']
    }

    qks = {
        'src_id' : qks_data['src_id'],
        'src_ip' : qks_data['src_ip'],
        'src_port' : qks_data['src_port'],
        'dest_id' :  qks_data['dest_id']
    }

    prefs['mongo_db'] = mongodb
    prefs['vault'] = vault
    prefs['qks'] = qks

    config_file.seek(0,0)
    yaml.safe_dump(prefs, config_file, default_flow_style=False)
    config_file.close() 
    return 0

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
    global vault, mongodb, vault_client, mongo_client, qkdm, qks
    if not server or (server and not reset): 
        config_file = open("qkdm_src/config.yaml", 'r+') 
        prefs = yaml.safe_load(config_file) 
        

        mongodb = {
            'host' : prefs['mongo_db']['host'],
            'port' : prefs['mongo_db']['port'], 
            'user' : prefs['mongo_db']['user'],
            'password' : prefs['mongo_db']['password'],
            'auth_src' : prefs['mongo_db']['auth_src'],
            'db' : prefs['mongo_db']['db']
        }

        vault = {
            'host' : prefs['vault']['host'],
            'port' : prefs['vault']['port'], 
            'token' : prefs['vault']['token']
        } 

        if server and not reset :
            qks = {
                'src_id' : prefs['qks']['src_id'],
                'src_ip' : prefs['qks']['src_ip'],
                'src_port' : prefs['qks']['src_port'],
                'dest_id' :  prefs['qks']['dest_id']
            }


        vault_client = VaultClient(vault['host'], vault['port'], vault['token']) 
        if not vault_client.connect() :
            config_file.close()
            return (11, "ERROR: unable to connect to Vault")

        try: 
            mongo_client = MongoClient(f"mongodb://{mongodb['user']}:{mongodb['password']}@{mongodb['host']}:{mongodb['port']}/{mongodb['db']}?authSource={mongodb['auth_src']}")
            mongo_client[mongodb['db']].list_collection_names()
        except Exception: 
            config_file.close()
            return (11, "ERROR: unable to connect to MongoDB")

        
        qkdm['init'] = True 
        prefs['qkdm']['init'] = True
        config_file.seek(0, 0)
        yaml.safe_dump(prefs, config_file, default_flow_style=False)
        config_file.close()

        message =  "QKDM initialized as standalone component" if not server else "QKDM initialized with QKS data from previous registration"
        return (0, message)
    else: 
        return (1, "QKDM is waiting for registration to a QKS")

