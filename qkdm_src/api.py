
import asyncio
from uuid import uuid4
from asyncVaultClient import VaultClient 
import yaml
from threading import Thread
from base64 import b64encode, b64decode
from pymongo import ReturnDocument
import logging
import time

import aiohttp
from motor.motor_asyncio import AsyncIOMotorClient as MongoClient

logger = logging.getLogger('api')
vault_client : VaultClient = None 
mongo_client : MongoClient = None 
supported_protocols = ["fake"]
http_client : aiohttp.ClientSession = None
qkd_device = None 
config : dict = {} 
config_file_name = "qkdm_src/config_files/config.yaml"



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
                
                async with http_client.post(f"http://{config['qkdm']['dest_IP']}:{config['qkdm']['dest_port']}/api/v1/qkdm/actions/exchange", json=post_data,  timeout = 5) as res: 
                    if res.status == 200: 
                        await key_streams_collection.update_one({"_id" : key_stream_ID},{"$set" : {"status" : "exchanging", "qos" : qos}})
                        asyncio.create_task(device_exchange(key_stream_ID))
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
    tasks = [] 
    if res is not None: 
        for index in indexes:
            path = key_stream_ID + "/" + str(index)
            tasks.append(asyncio.create_task(vault_client.readAndRemove(mount=config['vault']['secret_engine'], path=path)))

        ret_data = await asyncio.gather(*tasks)
        for ret, ind in zip(ret_data, indexes): 
            keys.append(ret[str(ind)])
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


    auth_string = f"client_id={config['keycloak']['client_id']}&client_secret={config['keycloak']['client_secret']}&grant_type=password&scope=openid&username={config['keycloak']['username'] }&password={config['keycloak']['password']}"
    auth_headers = {'Content-Type':'application/x-www-form-urlencoded'}

    async with http_client.post(f"http://{config['keycloak']['address']}:{config['keycloak']['port']}/auth/realms/{config['keycloak']['realm']}/protocol/openid-connect/token", data=auth_string, headers=auth_headers, timeout = 5) as auth_res:  
        if auth_res.status != 200 : 
            return 14
        else: 
            ret_json = await auth_res.json()
            access_token = ret_json['access_token']

    token_header = {'Authorization' : f'Bearer {access_token}'}
    async with http_client.post(f"http://{qks_src_ip}:{qks_src_port}/api/v1/qkdms", json=post_data, headers = token_header, timeout = 5) as response:  
        if response.status != 200 : 
            return 13

        res_data = await response.json() 

        ret = await register_data(res_data['vault_data'], res_data['database_data'], qks_data)
        if ret == 0: 
            ret, _ , _ = await init_module(server=True, reset=False)    
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

        await key_streams_collection.insert_one(key_stream)
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
        await key_streams_collection.update_one({"_id" : key_stream_ID}, {"$set" : {"status" : "exchanging"}})
        asyncio.create_task(device_exchange(key_stream_ID))
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

async def check_init() -> int : # return 0 if everything is ok 
    global config
    if config['qkdm']['init'] is True:
        return 0 

    return await init_module()[0]

async def init_module(server : bool = False , reset : bool = False, custom_config_file : str = None ) -> tuple[int, str, int]:
    global vault_client, mongo_client, config, supported_protocols, qkd_device, http_client, config_file_name

    http_client = aiohttp.ClientSession()
    if custom_config_file is not None: 
        config_file_name = custom_config_file
    try:
        config_file = open(config_file_name, 'r') 
        config = yaml.safe_load(config_file) 
        config_file.close()

        if config['qkdm']['protocol'] not in supported_protocols: 
            return (4, "ERROR: unsupported qkd protocol", -1)

        if config['qkdm']['protocol'] == "fake":
            from qkd_devices.fakeKE import fakeKE as QKDCore
    except Exception as e: 
        return (11, f"ERROR: wrong config file: {e}", -1)
        
    try: 
        if qkd_device is None: 
            qkd_device = QKDCore(config['qkd_device']['role'], config['qkd_device']['port'], config['qkd_device']['host'], config['qkdm']['max_key_count'])
            if await qkd_device.begin() != 0: 
                return (4, "ERROR: unable to start qkd device", -1) 
    except Exception as e: 
        return (4, f"ERROR: exception in qkd device startup - {e}", -1) 

    if not server or (server and not reset): 
        try: 
            mongo_client = MongoClient(f"mongodb://{config['mongo_db']['user']}:{config['mongo_db']['password']}@{config['mongo_db']['host']}:{config['mongo_db']['port']}/{config['mongo_db']['db']}?authSource={config['mongo_db']['auth_src']}")
            await mongo_client[config['mongo_db']['db']].list_collection_names()
        except Exception as e: 
            return (11, f"ERROR: unable to connect to MongoDB: {e}", -1)

        vault_client = VaultClient(config['vault']['host'], config['vault']['port'], config['vault']['token']) 
        if not (await vault_client.connect()):
            return (11, "ERROR: unable to connect to Vault", -1)

        try: 
            key_streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
            key_streams = key_streams_collection.find({"status" : "exchanging"}) 
            async for ks in key_streams : 
                asyncio.create_task(device_exchange(ks['_id']))
            config['qkdm']['init'] = True 
        except Exception as e:
            return (11, f"ERROR: unable to start device exchange: {e}", -1)

            
        message =  "QKDM initialized as standalone component" if not server else "QKDM initialized with QKS data from previous registration"
        return (0, message, config['qkdm']['port'])
    else: 
        return (1, "QKDM is waiting for registration to a QKS", config['qkdm']['port'])

async def device_exchange(key_stream_id:str): 
        global config, qkd_device, vault_client, mongo_client  
        res = await qkd_device.begin() 
        if res != 0: 
            logger.error("QKD device ERROR: unable to start")
            return 

        streams_collection = mongo_client[config['mongo_db']['db']]['key_streams']
        
        mount = config['vault']['secret_engine'] + "/" + key_stream_id
        n = config['qkdm']['max_key_count']
        logger.info(f"QKD device started: key_stream_id = {key_stream_id}")
        key_stream = await streams_collection.find_one({"_id" : key_stream_id})
        
        while True: 
            if key_stream is None: 
                logger.warning(f"QKD device stopping: key_stream_id {key_stream_id} not available")
                break 
        
            if key_stream['status'] =="exchanging" and len(key_stream['available_keys']) < n : 
                start = time.time_ns()
                key, id, status = await qkd_device.exchangeKey()
                end = time.time_ns() 
                if config['qkd_device']['role'] == 'sender':
                    logger.info(f"Key {id} sent in nanosec: {end-start}")
                if status == 0: 
                    data = {str(id) : b64encode(key).decode()} # bytearray saved as b64 string 
                    await vault_client.writeOrUpdate(mount=mount, path=str(id), data=data) 
                    
                    key_stream = await streams_collection.find_one_and_update(({"_id" : key_stream_id, f"available_keys.{n}" : {"$exists" : False}}), {"$push" : {"available_keys" : id}}, return_document=ReturnDocument.AFTER)
                    if config['qkd_device']['role'] == 'sender':
                        end = time.time_ns()
                        logger.info(f"Key {id} saved in nanoseconds: {end-start}")
                    
                    if key_stream is not None and id not in key_stream['available_keys']: 
                        await vault_client.remove(mount, path=str(id)) 
            else: 
                key_stream = await streams_collection.find_one({"_id" : key_stream_id})
                await asyncio.sleep(0.01)
