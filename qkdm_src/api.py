
import asyncio
import qkd_device.QKD
from uuid import uuid4
from asyncVaultClient import VaultClient 
import yaml
from threading import Thread
from time import sleep
from base64 import b64encode, b64decode

import aiohttp #import requests
from motor.motor_asyncio import AsyncIOMotorClient as MongoClient # from pymongo import MongoClient, ReturnDocument


vault_client : VaultClient = None 
mongo_client : MongoClient = None 
supported_protocols = ["fake"]
http_client : aiohttp.ClientSession = None


config_file_name = "qkdm_src/config2.yaml"
config_file = open(config_file_name, 'r') 
config = yaml.safe_load(config_file) 
config_file.close() 



if config['qkdm']['protocol'] == "fake":
    from qkd_device.fakeKE import fakeKE as QKDCore
qkd_device : QKDCore = None 


# SOUTHBOUND INTERFACE
async def OPEN_CONNECT(source:str, destination:str, key_stream_ID:str=None, qos=None) -> tuple[int, str]: 
    global mongo_client, config, http_client
    init = await check_init() 
    if init != 0: 
        return (11, "")

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
    if key_stream_ID is not None: 
        key_stream = await key_streams_collection.find_one({"_id" : key_stream_ID}) 
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
            #res = requests.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/open_stream", json=post_data)
            
            async with http_client.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/open_stream", json=post_data, timeout = 5) as res:
                if res.status == 200:
                    await key_streams_collection.insert_one(key_stream)
                    return (0, key_stream_ID)
                else: 
                    status = await res.json()['status']
                    return (status, key_stream_ID)
        except Exception: 
            return (1, key_stream_ID)

    else: # key_stream not none 
        if key_stream['status'] == "waiting" and key_stream['src_id'] == source and key_stream['dest_id'] == destination: # ok 
            try: 
                post_data = {"key_stream_ID" : key_stream_ID}
                
                #res = requests.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/exchange", json=post_data)
                async with http_client.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/exchange", json=post_data,  timeout = 5) as res: 
                    if res.status == 200: 
                        await key_streams_collection.update_one({"_id" : key_stream_ID},{"$set" : {"status" : "exchanging", "qos" : qos}})
                        ExchangerThread(key_stream_ID).start()
                        return (0, key_stream_ID)
                    else: 
                        status = await res.json()['status']
                        return (status, key_stream_ID)
            except Exception: 
                return (1, key_stream_ID)
        else: # found a ksid in use 
            return (5, key_stream_ID)
 

async def CLOSE(key_stream_ID:str) -> int: 
    global mongo_client, vault_client, config
    init = await check_init() 
    if init != 0: 
        return 11

    streams_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    key_stream = await streams_collection.find_one_and_delete({"_id" : key_stream_ID})
    if key_stream is not None: 
        mount = config['vault']['secret_engine'] + "/" + key_stream_ID
        for key in key_stream['available_keys'] : 
            await vault_client.remove(mount, str(key))
        return 0
    else: 
        return 9
    

async def GET_KEY(key_stream_ID:str, indexes: list, metadata=None) -> tuple[int, list, list]: 
    
    global mongo_client, vault_client, config
    init = await check_init() 
    if init != 0: 
        return (11, [], [])

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 
    key_stream = await key_streams_collection.find_one({"_id" : key_stream_ID})
    if key_stream is None: 
        return (9, [], [])

    res = await key_streams_collection.find_one_and_update({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}}, {"$pull" : {"available_keys" : {"$in" : indexes}}})
    keys = []
    if res is not None: 
        for index in indexes:
            path = key_stream_ID + "/" + str(index)
            ret = await vault_client.readAndRemove(mount=config['vault']['secret_engine'], path=path)
            keys.append(ret[str(index)])
        return (0, indexes, keys)
    
    return (2, [], [])
            

async def GET_KEY_ID(key_stream_ID:str, count:int = -1) -> tuple[int, list]:
    global mongo_client, config
    init = await check_init() 
    if init != 0: 
        return 11, []
        
    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 

    res = await key_streams_collection.find_one({"_id" : key_stream_ID})
    if res is not None: 
        c = count if count != -1 else len(res['available_keys'])
        l = res['available_keys'][:c] 
        return 0, l 
    else : 
        return 9, []
    

async def CHECK_ID(key_stream_ID:str, indexes:list) -> int: 
    global mongo_client, config
    init = await check_init() 
    if init != 0: 
        return 11

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams'] 

    res = await key_streams_collection.find_one({"_id" : key_stream_ID, "available_keys" : {"$all" : indexes}})
    status = 0 if res is not None else 10
    return status 

async def attachToServer(qks_src_ip:str, qks_src_port:int, qks_src_id:str, qks_dest_id:str) -> int: 
    global config, http_client
    if (await check_init()) == 0: 
        return 12
    
    qks_data = {
        'src_id' : qks_src_id, 
        'src_ip' : qks_src_ip,
        'src_port' : qks_src_port,
        'dest_id' : qks_dest_id
    }

    post_data = { 
        'QKDM_ID' : config['qkdm']['id'], 
        'protocol' : config['qkdm']['protocol'],
        'QKDM_IP' : config['qkdm']['ip'],
        'QKDM_port' : config['qkdm']['port'], 
        'reachable_QKS' : qks_dest_id, 
        'reachable_QKDM' : config['qkdm']['dest_ID'],
        'max_key_count' : config['qkdm']['max_key_count'], 
        'key_size' : config['qkdm']['key_size']
    }

    # response = requests.post(f"http://{qks_src_ip}:{qks_src_port}/api/v1/qkdms", json=post_data)
    async with http_client.post(f"http://{qks_src_ip}:{qks_src_port}/api/v1/qkdms", json=post_data, timeout = 5) as response:  
        if response.status != 200 : 
            return 13

        res_data = await response.json() 

        ret = await register_data(res_data['vault_data'], res_data['database_data'], qks_data)
        if ret == 0: 
            ret, _ = await init_module(server=True, reset=False)    
        return ret 
        

# QKDM INTERFACE 
async def open_stream(key_stream_ID:str, source:str, destination:str) -> int:
    global mongo_client, config
    init = await check_init() 
    if init != 0: 
        return 11

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
    key_stream = await key_streams_collection.find_one({"_id" : key_stream_ID}) 

    if key_stream is None: 
        key_stream = {
            "_id" : key_stream_ID, 
            "available_keys" : [], 
            "src_id" : source, 
            "dest_id" : destination, 
            "qos" : None, 
            "status" : "waiting"
        } 

        res = await key_streams_collection.insert_one(key_stream)
        return 0 
    else: 
        return 9 

async def exchange(key_stream_ID:str) -> int:
    global mongo_client, config
    init = await check_init() 
    if init != 0: 
        return 11

    key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
    key_stream = await key_streams_collection.find_one({"_id" : key_stream_ID}) 

    if key_stream is None: 
        return 9 
    else: 
        res = await key_streams_collection.update_one({"_id" : key_stream_ID}, {"$set" : {"status" : "exchanging"}})
        ExchangerThread(key_stream_ID).start()
        return 0

# MANAGMENT FUNCTIONS 
async def register_data(vault_data : dict, db_data : dict, qks_data: dict) -> int:
    global vault_client, config
    
    vault_client = VaultClient(vault_data['host'],vault_data['port'])
    res = await vault_client.approle_login(vault_data['role_id'], vault_data['secret_id'])
    
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

async def check_init() -> int : # return 1 if everything is ok 
    global config
    if config['qkdm']['init'] is True:
        return 0 
     
    config_file = open(config_file_name, 'r') 
    prefs = yaml.safe_load(config_file) 
    config_file.close() 

    config['qkdm']['init'] = prefs['qkdm']['init']
    if not config['qkdm']['init']: 
        return 1
    return await init_module()[0]

async def init_module(server : bool = False , reset : bool = False ) -> tuple[int, str, int]:
    global vault_client, mongo_client, config, supported_protocols, qkd_device, http_client

    if config['qkdm']['protocol'] not in supported_protocols: 
        return (4, "ERROR: unsupported qkd protocol", -1)

    if qkd_device is None: 
        qkd_device = QKDCore(config['qkd_device']['role'], config['qkd_device']['port'], config['qkd_device']['host'], config['qkdm']['max_key_count'])
        if qkd_device.begin() != 0: 
            return (4, "ERROR: unable to start qkd device", -1) 

    http_client = aiohttp.ClientSession()

    if not server or (server and not reset): 
        config_file = open(config_file_name, 'r') 
        config = yaml.safe_load(config_file) 
        config_file.close()

        if not server :
            config.pop("qks", None)

        try: 
            mongo_client = MongoClient(f"mongodb://{config['mongo_db']['user']}:{config['mongo_db']['password']}@{config['mongo_db']['host']}:{config['mongo_db']['port']}/{config['mongo_db']['db']}?authSource={config['mongo_db']['auth_src']}")
            await mongo_client[config['mongo_db']['db']].list_collection_names()
        except Exception: 
            return (11, "ERROR: unable to connect to MongoDB", -1)

        vault_client = VaultClient(config['vault']['host'], config['vault']['port'], config['vault']['token']) 
        if not (await vault_client.connect()):
            return (11, "ERROR: unable to connect to Vault", -1)

        key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
        key_streams = await key_streams_collection.find({"status" : "exchanging"}) 
        for ks in key_streams : 
            ExchangerThread(ks['_id']).start()

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
        Thread.__init__(self, daemon=True  )

    async def run(self):
        global config, qkd_device, vault_client, mongo_client  
        qkd_device.begin() 

        streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
        
        mount = config['vault']['secret_engine'] + "/" + self.key_stream
        n = config['qkdm']['max_key_count']

        while True: 
            key_stream = await streams_collection.find_one({"_id" : self.key_stream})
            if key_stream is None: 
                break 
            
            if len(key_stream['available_keys']) < n : 
                key, id, status = qkd_device.exchangeKey()
                
                if status == 0: 
                    data = {str(id) : b64encode(key).decode()} # bytearray saved as b64 string 
                    res_v = await vault_client.writeOrUpdate(mount=mount, path=str(id), data) 
                    
                    res_m = await streams_collection.update_one(({"_id" : self.key_stream, f"available_keys.{n}" : {"$exists" : False}}), {"$push" : {"available_keys" : id}})
                    if res_m.modified_count == 0: 
                        await vault_client.remove(mount, path=str(id)) 

            else: 
                sleep(0.1)
