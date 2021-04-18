import sys
from pathlib import Path
path = Path(__file__).parent
sys.path.insert(1, str(path))

import requests
import time
from flask import Flask, request
from threading import Thread, Lock
import sys
import QKD
import mysql.connector
import yaml
import hvac
import json
import logging
import uuid
import random


app = Flask(__name__)
serverPort = 4000

# synchronization variables
keyNo = 0

# DB ELEMENTS POSITION
# handles table
_HANDLE = 0
_DESTINATION = 1
_TIMEOUT = 2
_LENGTH = 3
_SYNCHRONIZED = 4
_NEWKEY = 5
_CURRENTKEYNO = 6
_STOP = 7
  
pref_file = open("/usr/src/app/src/configM.yaml", 'r')
prefs = yaml.safe_load(pref_file)

if str(prefs['module']['sim']) == 'bb84':
	from BB84 import BB84 as QKDCore
else:
	from fakeKE import fakeKE as QKDCore

# global parameters
HANDLE_LEN = 512 # in bits

# error codes
SUCCESSFUL = 0
INSUFFICIENT_KEY_AVAILABLE = 1	# (to be used with QKD_GET_KEY)
NO_QKD_CONNECTION_AVAILABLE = 2
HANDLE_IN_USE = 3		# (to be used with QKD_OPEN)
TIMEOUT = 4

# module status
AVAILABLE = 0
OPENED = 1
BUSY = 2

keyExchanger = None


# utility function - timeout parameter is expressed in milliseconds
# convert epoch time to milliseconds
current_time = lambda: int(round(time.time() * 1000))

# convert the array of bits into an array of bytes as per QKD specifications (bit 0 is the first bit of the octect - ETSI GS QKD 004 v1.1.1 (2010-12), page 9, table 1)
def convertToBytes(key, key_length):
	# convert list of bit in list of bytes
	byteskey = []
	for octect in range(int(key_length/8)):
		i = 7
		num = 0
		for bit in key[(8*octect):(8*(octect+1))]:
			num = (int(bit) << i) | num
			i = i - 1
		byteskey.append(num)
	# convert list to bytearray
	byteskey = bytearray(byteskey)
	return byteskey


class QKDModule():
	'''
	 OPEN_CONNECT

	Reserve an association (Key_stream_ID) to a set of future keys at both ends of the QKD link through this distributed Key Management Layer and establish a set of paramenters that define the expected levels of key service.
	This function shall block until both sides of the link have rendezvoused, an error is detected, or the specified TIMEOUT delay has been exeeded.

	@param source: IP address of the peer node to distribute the key with
	@param destination: IP address of the peer node to distribute the key with
	@param qos: dictionary containing information about requested_length, max_bps, priority and timeout
	@param Key_stream_ID: Unique handle to identify the key provided by the QKD Key Manager to the application. If it is NULL it will be automatically generated.
	@param status: Success/Failure of the request. Possible values: SUCCESSFUL, HANDLE_IN_USE, TIMEOUT. (IN/OUT parameter)

	@return: Key_stream_ID and status. Caller should check status variable before using Key_stream_ID to ensure request was successful.
	'''
	def OPEN_CONNECT(self, source, destination, qos, Key_stream_ID, status):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()

		time.sleep(random.randint(1,10)) # [cr] replace with a better management

		cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
		result = cursor.fetchone()
		if result is not None:
			if Key_stream_ID is None:
				# an handle has already been registered. Only calls with a specified handle will be accepted
				status = NO_QKD_CONNECTION_AVAILABLE
				return Key_stream_ID, status
		if Key_stream_ID is not None:
			# check if Key_stream_ID has already been assigned
			cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(Key_stream_ID))
			result = cursor.fetchone()
			if result is None:
				# ID not found, error
				status = NO_QKD_CONNECTION_AVAILABLE
				return Key_stream_ID, status
			# key ID was already sent from the other module, update its information
			cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
			cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET destination = '%s', timeout = %d, length = %d, synchronized = True WHERE handle = '%s'" % (str(destination), int(qos['timeout']), int(qos['length']), str(Key_stream_ID)))
			cursor.execute("UNLOCK TABLES")
		else:
			# Key_stream_ID must be a UUID_v4 as per standard specification
			Key_stream_ID = str(uuid.uuid4())
			# insert Key_stream_ID in handles' list with its related information
			cursor.execute("INSERT INTO " + str(prefs['module']['table']) + " (handle, destination, timeout, length, synchronized, newKey) VALUES ('%s', '%s', %d, %d, False, False)" % (str(Key_stream_ID), str(destination), int(qos['timeout']), int(qos['length'])))

		# start synchronization
		x = requests.get('http://' + destination + '/sync?key_handle=' + str(Key_stream_ID))
		if x.status_code != 200:
			# an error occurred. Procedure must be repeated
			status = NO_QKD_CONNECTION_AVAILABLE
			return Key_stream_ID, status

		status = SUCCESSFUL
		return Key_stream_ID, status


	'''
	 CLOSE

	This terminates the association established for this Key_stream_ID and no further keys will be allocated for this Key_stream_ID.

	@param Key_stream_ID: Unique handle to identify the key stream provided by the QKD Key Manager to the application.
	@param status: Success/Failure of the request. Possible values: SUCCESSFUL, NO_QKD_CONNECTION_AVAILABLE. (IN/OUT parameter)

	@return status
	'''
	def CLOSE(self, Key_stream_ID, status):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
		try:
			cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET stop = true WHERE handle = '%s'" % str(Key_stream_ID))
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			cursor.execute("UNLOCK TABLES")
			status = NO_QKD_CONNECTION_AVAILABLE
			return status
		# signal the running thread to stop
		status = SUCCESSFUL
		return status

	'''
	 GET_KEY

	Obtain the required amount of key material requested for the requested Key_stream_ID.

	@param Key_stream_ID: Unique handle to identify the stream provided by the QKD Key Manager to the application.
	@param index: position within the key that has to be accessed (pass -1 to get the first available key).
	@param key_buffer: Buffer containing the current stream of keys. (IN/OUT parameter)
	@param Metadata: Additional information (currently not used).
	@param status: : Success/Failure of the request. Possible values: SUCCESSFUL, NO_QKD_CONNECTION_AVAILABLE, INSUFFICIENT_KEY_AVAILABLE. (IN/OUT parameter)

	@return key_buffer, index, status
	'''
	def GET_KEY(self, Key_stream_ID, index, key_buffer, Metadata, status):
		# vault access must be synchronized with GET_KEY function - use DB lock for this purpose
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
		
		try:
			client = hvac.Client(url='http://' + prefs['vault']['host'] + ':' + str(prefs['vault']['port']))
			client.token = prefs['vault']['token']
			response = client.secrets.kv.read_secret_version(path=Key_stream_ID)
			keys = response['data']['data']['keys']
			if index == -1:
				# index not specified, return the first available key
				entry = keys.pop(0)
				index = entry[0]
				key = eval(entry[1])
			else:
				key = 0
				# iterate the list until the desired index is found
				for i in range(len(keys)):
					if int(index) == int(keys[i][0]):
						key = eval(keys[i][1])
						# remove element from the list
						entry = keys.pop(i)
						break
				if key == 0:
					# no key with specified index found - error
					status = INSUFFICIENT_KEY_AVAILABLE
					# release vault lock
					cursor.execute("UNLOCK TABLES")
					return None, index, status

			# if keys list is empty now remove the whole handle from vault, otherwise just update the list on the storage 
			if keys == []:
				client.secrets.kv.delete_metadata_and_all_versions(Key_stream_ID)
			else:
				client.secrets.kv.v2.create_or_update_secret(path=Key_stream_ID, secret=dict(keys=keys),)
			# update the number of available keys
			cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET currentKeyNo = %d WHERE handle = '%s'" % (len(keys), str(Key_stream_ID)))
			# release vault lock
			cursor.execute("UNLOCK TABLES")

			# return key associated to this key handle
			status = SUCCESSFUL
			return key, index, status
		except:
			# if key handle does not exist in vault an exception is thrown
			# release lock and return an error
			cursor.execute("UNLOCK TABLES")
			status = INSUFFICIENT_KEY_AVAILABLE
			return None, -1, status


	'''
	 AVAILABLE_KEYS

	Utility function to retrieve the number of available keys for the requested Key_stream_ID.

	@param Key_stream_ID: Unique handle to identify the stream provided by the QKD Key Manager to the application.

	@return key_number
	'''
	def AVAILABLE_KEYS(self, Key_stream_ID):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
		result = cursor.fetchone()
		currentKno = int(result[_CURRENTKEYNO])
		return currentKno


'''
Syncrhonization API
'''

@app.route('/sync', methods=['GET'])
def synchronize():
	handle_req = str(request.args.get('key_handle'))
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % handle_req)
	result = cursor.fetchone()
	if result is not None:
		# this handle has been registered with QKD_OPEN_CONNECT on this side too. Synchronization completed
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
		try:
			cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(handle_req))
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			cursor.execute("UNLOCK TABLES")
			return "Internal Server Error", 503
	else:
		# this is a new handle, save it in the db
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
		try:
			cursor.execute("INSERT INTO " + str(prefs['module']['table']) + " (handle, synchronized, newKey) VALUES ('%s', False, False)" % (str(handle_req)))
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			cursor.execute("UNLOCK TABLES")
			return "Internal Server Error", 503
	return "OK", 200


@app.route('/start', methods=['POST'])
def start():
	key_handle = eval(request.data)
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET newKey = True WHERE handle = '%s'" % key_handle)
	return "OK", 200



'''
Web server API
'''
@app.route('/api/v1/qkdm/actions/open_connect', methods=['POST'])
def OPEN_CONNECT():
	try:
		req_data = eval(request.data)
		source = req_data[0]
		destination = req_data[1]
		qos = req_data[2]
		Key_stream_ID = req_data[3]
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()

		time.sleep(random.randint(1,10)) # [cr] replace with a better management
		
		cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
		result = cursor.fetchone()
		if result is not None:
			if Key_stream_ID is None:
				# an handle has already been registered. Only calls with a specified handle will be accepted
				status = NO_QKD_CONNECTION_AVAILABLE
				return repr([str(Key_stream_ID), status]), 400
			if Key_stream_ID is not None:
				# check if Key_stream_ID has already been assigned
				cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(Key_stream_ID))
				result = cursor.fetchone()
				if result is None:
					# ID not found, error
					status = NO_QKD_CONNECTION_AVAILABLE
					return repr([str(Key_stream_ID), status]), 400
				# key ID was already sent from the other module, update its information
				cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
				cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET destination = '%s', timeout = %d, length = %d, synchronized = True WHERE handle = '%s'" % (str(destination), int(qos['timeout']), int(qos['length']), str(Key_stream_ID)))
				cursor.execute("UNLOCK TABLES")
		else:
			# Key_stream_ID must be a UUID_v4 as per standard specification
			Key_stream_ID = str(uuid.uuid4())
			# insert Key_stream_ID in handles' list with its related information
			cursor.execute("INSERT INTO " + str(prefs['module']['table']) + " (handle, destination, timeout, length, synchronized, newKey) VALUES ('%s', '%s', %d, %d, False, False)" % (str(Key_stream_ID), str(destination), int(qos['timeout']), int(qos['length'])))

		# start synchronization
		x = requests.get('http://' + destination + '/sync?key_handle=' + str(Key_stream_ID))
		if x.status_code != 200:
			# an error occurred. Procedure must be repeated
			status = NO_QKD_CONNECTION_AVAILABLE
			return repr([str(Key_stream_ID), status]), 400

		status = SUCCESSFUL
		return repr([str(Key_stream_ID), status]), 200
	except Exception as e:
		return "Server error", 500


@app.route('/api/v1/qkdm/actions/close', methods=['POST'])
def CLOSE():
	req_data = eval(request.data)
	Key_stream_ID = req_data[0]

	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	# use a lock to access database to avoid concurrency access
	cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
	try:
		cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET stop = true WHERE handle = '%s'" % str(Key_stream_ID))
		cursor.execute("UNLOCK TABLES")
	except Exception as e:
		cursor.execute("UNLOCK TABLES")
		status = NO_QKD_CONNECTION_AVAILABLE
		return str(status), 400
	# signal the running thread to stop
	status = SUCCESSFUL
	return str(status), 200



@app.route('/api/v1/qkdm/actions/get_key', methods=['POST'])
def GET_KEY():
	req_data = eval(request.data)
	Key_stream_ID = req_data[0]
	index = req_data[1]
	Metadata = req_data[2]

	# vault access must be synchronized with GET_KEY function - use DB lock for this purpose
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
	
	try:
		client = hvac.Client(url='http://' + prefs['vault']['host'] + ':' + str(prefs['vault']['port']))
		client.token = prefs['vault']['token']
		response = client.secrets.kv.read_secret_version(path=Key_stream_ID)
		keys = response['data']['data']['keys']
		if index == -1:
			# index not specified, return the first available key
			entry = keys.pop(0)
			index = entry[0]
			key = eval(entry[1])
		else:
			key = 0
			# iterate the list until the desired index is found
			for i in range(len(keys)):
				if int(index) == int(keys[i][0]):
					key = eval(keys[i][1])
					# remove element from the list
					entry = keys.pop(i)
					break
			if key == 0:
				# no key with specified index found - error
				status = INSUFFICIENT_KEY_AVAILABLE
				# release vault lock
				cursor.execute("UNLOCK TABLES")
				return repr([None, index, status]), 400

		# if keys list is empty now remove the whole handle from vault, otherwise just update the list on the storage 
		if keys == []:
			client.secrets.kv.delete_metadata_and_all_versions(Key_stream_ID)
		else:
			client.secrets.kv.v2.create_or_update_secret(path=Key_stream_ID, secret=dict(keys=keys),)
		# update the number of available keys
		cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET currentKeyNo = %d WHERE handle = '%s'" % (len(keys), str(Key_stream_ID)))
		# release vault lock
		cursor.execute("UNLOCK TABLES")

		# return key associated to this key handle
		status = SUCCESSFUL
		return repr([key, index, status]), 200
	except Exception as e:
		# if key handle does not exist in vault an exception is thrown
		# release lock and return an error
		cursor.execute("UNLOCK TABLES")
		status = INSUFFICIENT_KEY_AVAILABLE
		return repr([None, -1, status]), 400


@app.route('/api/v1/qkdm/available_keys', methods=['GET'])
def AVAILABLE_KEYS():
	handle = request.args.get('handle')
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
	result = cursor.fetchone()
	currentKno = int(result[_CURRENTKEYNO])
	return repr([currentKno]), 200


@app.route('/attach_to_server', methods=['POST'])
def ATTACH_TO_SERVER():
	serverIP = eval(request.data)
	
	# try to register this QKD module to specified QKD key server
	x = requests.post('http://' + serverIP + '/api/v1/keys/modules', data=repr([prefs['module']['sim'], prefs['module']['this_public_IP'], prefs['module']['max_key_count']]))
	if x.status_code != 200:
		# error
		return "Key server unavailable", 400
	# retrieve vault and mysql references
	result = eval(x.content)
	prefs['internal_db']['host'] = result[0]
	prefs['internal_db']['port'] = result[1]
	prefs['internal_db']['user'] = result[2]
	prefs['internal_db']['passwd'] = result[3]
	prefs['internal_db']['database'] = result[4]
	prefs['vault']['host'] = result[5]
	prefs['vault']['port'] = result[6]
	prefs['vault']['token'] = result[7]
	# write data to config file
	with open('/usr/src/app/src/configM.yaml', 'w') as fp:
		yaml.dump(prefs, fp)
	return "OK", 200


'''
Key exchanger thread
'''

class QKDExchange(Thread):
	def __init__(self):
		Thread.__init__(self)

	def run(self):
		global keyNo

		while True:
			try:
				pref_file = open("/usr/src/app/src/configM.yaml", 'r')
				prefs = yaml.safe_load(pref_file)
				
				db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
				cursor = db.cursor()
				sync = False
				core = QKDCore()
				while not sync:
					# make sure both side of communication are sinchronised before starting the exchange
					cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
					result = cursor.fetchone()
					if result is None:
						continue
					sync = result[4]

				cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
				cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
				result = cursor.fetchone()
				cursor.execute("UNLOCK TABLES")
					
				# now both side are ready
				Key_stream_ID = result[_HANDLE]
				key_length = result[_LENGTH]
				timeout = result[_TIMEOUT]
				destination = result[_DESTINATION]
				stop = result[_STOP]
				currentKno = int(result[_CURRENTKEYNO])
				
				portNo = int(destination[-4] + destination[-3] + destination[-2] + destination[-1])
				QKDdestination = 'http://' + destination[:-4] + str(portNo + 1)

				sender = int(prefs['module']['sender'])

				# exchange keys until CLOSE method is called
				while stop != True:
					# sender code
					if sender == 1:
						# wait if we reached the maximum number of keys storable
						while currentKno >= prefs['module']['max_key_count'] and stop != True:
							cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
							result = cursor.fetchone()
							currentKno = result[_CURRENTKEYNO]
							stop = result[_STOP]

						key, verified = core.exchangeKey(key_length, QKDdestination, timeout, prefs['module']['sender'])
						# signal destination it can retrieve the key
						x = requests.post('http://' + str(destination) + '/start', data=repr(Key_stream_ID))
						# save the key in vault
						if verified == True:
							# convert the array of bits into an array of bytes as per QKD specifications (bit 0 is the first bit of the octect - ETSI GS QKD 004 v2.1.1 (2020-8), page 10, table 2)
							key = convertToBytes(key, key_length)
							# vault access must be synchronized with GET_KEY function - use DB lock for this purpose
							cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
							try:
								client = hvac.Client(url='http://' + prefs['vault']['host'] + ':' + str(prefs['vault']['port']))
								client.token = prefs['vault']['token']
								try:
									response = client.secrets.kv.read_secret_version(path=Key_stream_ID)
									keys = response['data']['data']['keys']
									keys.append([keyNo, str(key)])
								except:
									# if key handle does not exist in vault yet
									keys = [[keyNo, str(key)]]
								keyNo = keyNo + 1
								client.secrets.kv.v2.create_or_update_secret(path=Key_stream_ID, secret=dict(keys=keys),)
								# update the number of available keys
								cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET currentKeyNo = %d WHERE handle = '%s'" % (len(keys), str(Key_stream_ID)))
								# release vault lock
								cursor.execute("UNLOCK TABLES")
							except:
								cursor.execute("UNLOCK TABLES")

							newKey = False
							while not newKey:
								# wait for the other module to retrieve the same key
								cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % Key_stream_ID)
								result = cursor.fetchone()
								newKey = result[_NEWKEY]

							# reset flag
							cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET newKey = False WHERE handle = '%s'" % str(Key_stream_ID))
					# receiver code
					else:
						# wait until sender sends a key
						newKey = False
						while not newKey:
							# wait for the other module to retrieve the same key
							cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % Key_stream_ID)
							result = cursor.fetchone()
							newKey = result[_NEWKEY]

						# reset flag
						cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET newKey = False WHERE handle = '%s'" % str(Key_stream_ID))

						# retrieve the just exchanged key
						key, verified = core.exchangeKey(key_length, QKDdestination, timeout, prefs['module']['sender'])

						# signal sender it can exchange a new key
						x = requests.post('http://' + str(destination) + '/start', data=repr(Key_stream_ID))
						# save the key in vault
						if verified == True:
							# convert the array of bits into an array of bytes as per QKD specifications (bit 0 is the first bit of the octect - ETSI GS QKD 004 v2.1.1 (2020-8), page 10, table 2)
							key = convertToBytes(key, key_length)
							# vault access must be synchronized with GET_KEY function - use DB lock for this purpose
							cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
							try:
								client = hvac.Client(url='http://' + prefs['vault']['host'] + ':' + str(prefs['vault']['port']))
								client.token = prefs['vault']['token']
								try:
									response = client.secrets.kv.read_secret_version(path=Key_stream_ID)
									keys = response['data']['data']['keys']
									keys.append([keyNo, str(key)])
								except:
									# if key handle does not exist in vault yet
									keys = [[keyNo, str(key)]]
								keyNo = keyNo + 1
								client.secrets.kv.v2.create_or_update_secret(path=Key_stream_ID, secret=dict(keys=keys),)
								# update the number of available keys
								cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET currentKeyNo = %d WHERE handle = '%s'" % (len(keys), str(Key_stream_ID)))
								# release vault lock
								cursor.execute("UNLOCK TABLES")
							except:
								cursor.execute("UNLOCK TABLES")
					cursor.execute("SELECT * FROM " + str(prefs['module']['table']))
					result = cursor.fetchone()
					currentKno = result[_CURRENTKEYNO]
					stop = result[_STOP]

				# CLOSE has been called - clean DB before exit
				cursor.execute("DELETE FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(Key_stream_ID))
				break
			except Exception as e:
				pass

def main():
	global serverPort
	# check for port parameter
	try:
		port = eval(sys.argv[1])
		if isinstance(port, int):
			serverPort = port
	except:
		pass
	# check QKDCore
	if not issubclass(QKDCore, QKD.QKD):
		print("Please select a valid QKD protocol class for key exchange. A valid protocol class must inherit its methods from QKD abstract class.")
		exit(2)
	core = QKDCore()
	core.begin(serverPort + 1)
	fh = logging.FileHandler('module.log')
	formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	fh.setFormatter(formatter)
	app.logger.addHandler(fh)
	app.logger.setLevel(logging.DEBUG)
	# launch
	keyExchanger = QKDExchange()
	keyExchanger.start()	
	app.run(host='0.0.0.0', port=serverPort)

if __name__ == "__main__":
	main()
