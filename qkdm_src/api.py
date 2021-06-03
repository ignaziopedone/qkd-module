import requests
import qkd_device.QKD
from uuid import uuid4
from vaultClient import VaultClient 
from pymongo import MongoClient, ReturnDocument
import yaml
from threading import Thread
from time import sleep


vault_client : VaultClient = None 
mongo_client : MongoClient = None 
supported_protocols = ["fake"]

config_file_name = "qkdm_src/config2.yaml"
config_file = open(config_file_name, 'r') 
config = yaml.safe_load(config_file) 
config_file.close() 



if config['qkdm']['protocol'] == "fake":
    from qkd_device.fakeKE import fakeKE as QKDCore
qkd_device : QKDCore = None 


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
                    ExchangerThread(key_stream_ID).start()
                    return (0, key_stream_ID)
                else: 
                    status = res.json()['status']
                    return (status, key_stream_ID)
            except Exception: 
                return (1, key_stream_ID)
        else: # found a ksid in use 
            return (5, key_stream_ID)
 

def CLOSE(key_stream_ID:str) -> int: 
    global mongo_client, vault_client, config
    init = check_init() 
    if init != 0: 
        return 11

    streams_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    stream = streams_collection.find_one_and_delete({"_id" : key_stream_ID})
    if stream is not None: 
        mount = config['vault']['secret_engine'] + "/" + key_stream_ID
        for key in stream['available_keys'] : 
            vault_client.remove(mount, str(key))
        return 0
    else: 
        return 9
    

def GET_KEY(key_stream_ID:str, indexes: list, metadata=None) -> tuple[int, list, list]: 
    
    global mongo_client, vault_client, config
    init = check_init() 
    if init != 0: 
        return (11, [], [])

    stream_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    stream = stream_collection.find_one({"_id" : key_stream_ID})
    if stream is None: 
        return (9, [], [])

    res = stream_collection.find_one_and_update({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}}, {"$pull" : {"available_keys" : {"$in" : indexes}}})
    keys = []
    if res is not None: 
        for index in indexes:
            path = key_stream_ID + "/" + str(index)
            ret = vault_client.readAndRemove(mount=config['vault']['secret_engine'], path=path, id=index)
            keys.append(ret[str(index)])
        return (0, indexes, keys)
    
    return (2, [], [])
            

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
        ExchangerThread(key_stream_ID).start()
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

    config_file = open(config_file_name, 'w') 
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

def init_module(server : bool = False , reset : bool = False ) -> tuple[int, str, int]:
    global vault_client, mongo_client, config, supported_protocols, qkd_device

    if config['qkdm']['protocol'] not in supported_protocols: 
        return (4, "ERROR: unsupported qkd protocol", -1)


    qkd_device = QKDCore(config['qkd_device']['role'], config['qkd_device']['port'], config['qkd_device']['host'], config['qkdm']['MAX_KEY_COUNT'])
    if qkd_device.begin() != 0: 
        return (4, "ERROR: unable to start qkd device", -1) 


    if not server or (server and not reset): 
        config_file = open(config_file_name, 'r') 
        config = yaml.safe_load(config_file) 
        config_file.close()

        if not server :
            config.pop("qks", None)

        vault_client = VaultClient(config['vault']['host'], config['vault']['port'], config['vault']['token']) 
        if not vault_client.connect() :
            return (11, "ERROR: unable to connect to Vault", -1)

        try: 
            mongo_client = MongoClient(f"mongodb://{config['mongo_db']['user']}:{config['mongo_db']['password']}@{config['mongo_db']['host']}:{config['mongo_db']['port']}/{config['mongo_db']['db']}?authSource={config['mongo_db']['auth_src']}")
            mongo_client[config['mongo_db']['db']].list_collection_names()
        except Exception: 
            return (11, "ERROR: unable to connect to MongoDB", -1)

        
        config['qkdm']['init'] = True 
        config_file = open(config_file_name, 'w') 
        yaml.safe_dump(config, config_file, default_flow_style=False)
        config_file.close()

        message =  "QKDM initialized as standalone component" if not server else "QKDM initialized with QKS data from previous registration"
        return (0, message, config['qkdm']['port'])
    else: 
        return (1, "QKDM is waiting for registration to a QKS", config['qkdm']['port'])

class ExchangerThread(Thread) : 
    def __init__(self, key_stream:str):
        self.key_stream = key_stream 
        Thread.__init__(self)

    def run(self):
        global config, qkd_device, vault_client, mongo_client  
        qkd_device.begin() 

        streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
        
        mount = config['vault']['secret_engine'] + "/" + self.key_stream
        n = config['qkdm']['MAX_KEY_COUNT']

        while True: 
            stream = streams_collection.find_one({"_id" : self.key_stream})
            if stream is None: 
                break 
            
            if len(stream['available_keys']) < n : 
                key, id, status = qkd_device.exchangeKey()
                
                if status == 0: 
                    data = {str(id) : str(key)}
                    res_v = vault_client.writeOrUpdate(mount=mount, path=str(id), data=data) 
                    
                    res_m = streams_collection.update_one(({"_id" : self.key_stream, f"available_keys.{n}" : {"$exists" : False}}), {"$push" : {"available_keys" : id}})
                    if res_m.modified_count == 0: 
                        vault_client.remove(mount, path) 

            else: 
                sleep(0.1)
                
            
            


        

            
        


