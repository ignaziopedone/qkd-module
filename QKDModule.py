'''
key_handle is a 512 bits (64 bytes) variable to identify a key request. It needs to be unique within the manager. If it is NULL a key_handle must be generated

__handle_list is the internal list of key_handle. It is a dictionary that save information with the following format:
"key_handle" : [destination, qos, linkedToPeer (True/False)]
'''

import requests
import time
from flask import Flask, request
from trng import *
import sys
from BB84 import BB84 as QKDCore
import QKD
import mysql.connector
import yaml
import hvac
import json

app = Flask(__name__)
serverPort = 4000
DEBUG = False

pref_file = open("configM.yaml", 'r')
prefs = yaml.safe_load(pref_file)

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
	module_status = AVAILABLE

	'''
	 QKD_OPEN

	Reserve an association (key_handle) to a set of future keys at both ends of the QKD link through this distributed Key Management Layer and establish a set of paramenters that define the expected levels of key service.
	This function shall return immediately and not block.

	@param destination: IP address of the peer node to distribute the key with
	@param qos: dictionary containing information about requested_length, max_bps, priority and timeout
	@param key_handle: Unique handle to identify the key provided by the QKD Key Manager to the application. If it is NULL it will be automatically generated.
	@param status: Success/Failure of the request. Possible values: SUCCESSFUL, HANDLE_IN_USE, TIMEOUT. (IN/OUT parameter)

	@return: key_handle and status. Caller should check status variable before using key_handle to ensure request was successful.
	'''
	def QKD_OPEN(self, destination, qos, key_handle, status):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		if key_handle is not None:
			# check if key_handle has already been assigned
			if DEBUG:
				print("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
			cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
			result = cursor.fetchone()
			if result is not None:
				# handle already used
				cursor.execute("UNLOCK TABLES")
				status = HANDLE_IN_USE
				return key_handle, status
		else:
			# generate a unique KEY_HANDLE
			randNo = randomStringGen(HANDLE_LEN)
			# convert bit string into bytes
			key_handle = int(randNo, 2)
			start_time = current_time() # get current time in ms
			# make sure key is really unique
			cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
			result = cursor.fetchone()
			while result is not None:
				# try to generate new random key until we found a unique one
				randNo = randomStringGen(HANDLE_LEN)
				key_handle = int(randNo, 2)
				cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
				result = cursor.fetchone()
				# keep trying until timeout occurs
				if current_time() > start_time + qos['timeout']:
					cursor.execute("UNLOCK TABLES")
					status = TIMEOUT
					return key_handle, status
		# insert key_handle in handles' list with its related information
		if DEBUG:
			print("INSERT INTO " + str(prefs['module']['table']) + " (handle, destination, timeout, length, synchronized) VALUES ('%s', '%s', %d, %d, False)" % (str(key_handle), str(destination), int(qos['timeout']), int(qos['length'])))
		cursor.execute("INSERT INTO " + str(prefs['module']['table']) + " (handle, destination, timeout, length, synchronized) VALUES ('%s', '%s', %d, %d, False)" % (str(key_handle), str(destination), int(qos['timeout']), int(qos['length'])))
		status = SUCCESSFUL
		self.module_status = OPENED
		return key_handle, status


	'''
	 QKD_CONNECT_NONBLOCK

	Verifies that the QKD link is available and the key_handle association is synchronized at both ends of the link.
	This function shall not block and returns immediately indicating that both sides of the link have rendezvoused or an error has occurred.
	Since here a simulated Quantum channel is used, this function will check only for synchronization of key_handle. QKD link is always considered available.

	@param key_handle: Unique handle to identify the key provided by the QKD Key Manager to the application.
	@param status: Success/Failure of the request. Possible values: SUCCESSFUL, NO_QKD_CONNECTION_AVAILABLE. (IN/OUT parameter)

	@return status
	'''
	def QKD_CONNECT_NONBLOCK(self, key_handle, status):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		if DEBUG:
			print("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
		cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
		result = cursor.fetchone()
		if result is None:
			return NO_QKD_CONNECTION_AVAILABLE

		remote_IP = str(result[1])
		synchronized = bool(result[4])
		if synchronized == False:
			# check if peer has received key_handle
			x = requests.get('http://' + remote_IP + '/sync?key_handle=' + str(key_handle))
			if x.status_code == 200:
				# peer is ready
				status = SUCCESSFUL
				# update this information in handles' db
				# use a lock to access database to avoid concurrency access
				cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
				try:
					if DEBUG:
						print("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(key_handle))
					cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(key_handle))
					cursor.execute("UNLOCK TABLES")
				except Exception as e:
					cursor.execute("UNLOCK TABLES")
					status = NO_QKD_CONNECTION_AVAILABLE
					return status
			else:
				# if reply is not OK consider peer not ready yet
				status = NO_QKD_CONNECTION_AVAILABLE
			return status
		else:
			# connection with peer was previously estabilshed
			status = SUCCESSFUL
			return status


	'''
	 QKD_CONNECT_BLOCKING

	Verifies that the QKD link is available and the key_handle association is synchronized at both ends of the link.
	This function shall block until both sides of the link have rendezvoused, an error is detected, or the specified TIMEOUT delay has been exeeded.
	Since here a simulated Quantum channel is used, this function will check only for synchronization of key_handle. QKD link is always considered available.

	@param key_handle: Unique handle to identify the key provided by the QKD Key Manager to the application.
	@param timeout: Maximum wait time for the connection to be synchronized.
	@param status: Success/Failure of the request. Possible values: SUCCESSFUL, NO_QKD_CONNECTION_AVAILABLE, TIMEOUT. (IN/OUT parameter)

	@return status

	'''
	def QKD_CONNECT_BLOCKING(self, key_handle, timeout, status):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		if DEBUG:
			print("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
		cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
		result = cursor.fetchone()
		if result is None:
			status = NO_QKD_CONNECTION_AVAILABLE
			return status

		remote_IP = str(result[1])
		synchronized = bool(result[4])
		if synchronized == False:
			# get current time
			start_time = current_time()
			# perform requests until timeout elapses or connection is established
			while current_time() < start_time + timeout:
				# check if peer has received key_handle
				x = requests.get('http://' + remote_IP + '/sync?key_handle=' + str(key_handle))
				if x.status_code == 200:
					# peer is ready
					status = SUCCESSFUL
					# update this information in handles' db
					# use a lock to access database to avoid concurrency access
					cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
					try:
						if DEBUG:
							print("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(key_handle))
						cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(key_handle))
						cursor.execute("UNLOCK TABLES")
					except Exception as e:
						cursor.execute("UNLOCK TABLES")
						status = NO_QKD_CONNECTION_AVAILABLE
					return status
			# if while loop has exited timeout has elapsed
			status = TIMEOUT
			return status
		else:
			# connection with peer was previously estabilshed
			status = SUCCESSFUL
			return status

	'''
	 QKD_CLOSE

	This terminates the association established for this key_handle and no further keys will be allocated for this key_handle.

	@param key_handle: Unique handle to identify the key provided by the QKD Key Manager to the application.
	@param status: Success/Failure of the request. Possible values: SUCCESSFUL, NO_QKD_CONNECTION_AVAILABLE. (IN/OUT parameter)

	@return status
	'''
	def QKD_CLOSE(self, key_handle, status):
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
		try:
			if DEBUG:
				print("DELETE FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
			cursor.execute("DELETE FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			cursor.execute("UNLOCK TABLES")
			status = NO_QKD_CONNECTION_AVAILABLE
			return status
		status = SUCCESSFUL
		self.module_status = AVAILABLE
		return status

	'''
	 QKD_GET_KEY

	Obtain the required amount of key material requested for this key_handle.
	The timeout value for this function is specified in QKD_OPEN() function.

	@param key_handle: Unique handle to identify the key provided by the QKD Key Manager to the application.
	@param key_buffer: Buffer containing the current stream of keys. (IN/OUT parameter)
	@param status: : Success/Failure of the request. Possible values: SUCCESSFUL, NO_QKD_CONNECTION_AVAILABLE, INSUFFICIENT_KEY_AVAILABLE. (IN/OUT parameter)
	'''
	def QKD_GET_KEY(self, key_handle, key_buffer, status):
		# check QKDCore
		if not issubclass(QKDCore, QKD.QKD):
			print("Please select a valid QKD protocol class for key exchange. A valid protocol class must inherit its methods from QKD abstract class.")
			status = INSUFFICIENT_KEY_AVAILABLE
			return None, status
		core = QKDCore()
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		# check if key associated to this key_handle has already been exchanged previously
		client = hvac.Client(url='http://' + prefs['vault']['host'] + ':8200')
		client.token = prefs['vault']['token']
		try:
			response = client.secrets.kv.read_secret_version(path=key_handle)
			keys = response['data']['data']['keys']
			# remove first element of the list
			key = eval(keys.pop(0))
			# if keys list is empty now remove the whole handle from vault, otherwise just update the list on the storage 
			if keys == []:
				client.secrets.kv.delete_metadata_and_all_versions(key_handle)
			else:
				client.secrets.kv.v2.create_or_update_secret(path=key_handle, secret=dict(keys=keys),)
			# return key associated to this key handle
			status = SUCCESSFUL
			return key, status
		except:
			# if key handle does not exist in vault an exception is thrown
			# try to exchange the key with the QKD module
			pass


		if DEBUG:
			print("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
		cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % str(key_handle))
		result = cursor.fetchone()
		if result is None:
			status = NO_QKD_CONNECTION_AVAILABLE
			return None, status
		key_length = result[3]
		destination = result[1]
		timeout = result[2]
		portNo = int(destination[-4] + destination[-3] + destination[-2] + destination[-1])
		QKDdestination = 'http://' + destination[:-4] + str(portNo + 1)

		# check if we need to exchange key associated to other key handle or we can start the one requested
		if DEBUG:
			print("SELECT * FROM currentExchange")
		try:
			cursor.execute("SELECT * FROM currentExchange")
			result = cursor.fetchone()
			if result is None:
				# we can proceed by exchanging key associated to this key handle - check if also destination is ready

				# delay the start of the exchange of a random number of seconds (between 0 and 8)
				randNo = randomStringGen(3)
				# convert bit string into bytes
				randNo = int(randNo, 2)
				time.sleep(randNo)

				cursor.execute("LOCK TABLES currentExchange WRITE")
				cursor.execute("SELECT * FROM currentExchange")
				result = cursor.fetchone()
				if result is not None:
					# go ahead only if a record was no inserted in the meatime
					status = INSUFFICIENT_KEY_AVAILABLE
					return None, status
				if DEBUG:
					print("INSERT INTO currentExchange (destination, handle) VALUES ('%s', '%s')" % (str(destination[:-5]), key_handle))
					print("UNLOCK TABLES")
				cursor.execute("INSERT INTO currentExchange (destination, handle) VALUES ('%s', '%s')" % (str(destination[:-5]), key_handle))
				cursor.execute("UNLOCK TABLES")
				x = requests.post('http://' + str(destination) + '/start', data = json.dumps(str(key_handle)))
				if x.status_code != 200:
					# error occurred - perhaps target is trying to exchange another key handle. Remove record from currentExchange db to allows new exchanges
					if DEBUG:
						print("DELETE FROM currentExchange")
					cursor.execute("DELETE FROM currentExchange")
					status = INSUFFICIENT_KEY_AVAILABLE
					return None, status
				if DEBUG:
					print("UNLOCK TABLES")
				cursor.execute("UNLOCK TABLES")
				# target is ready too - start the exchange
				self.module_status = BUSY
				key, verified = core.exchangeKey(key_length, QKDdestination, timeout)
				self.module_status = OPENED

				if verified == True:
					# convert the array of bits into an array of bytes as per QKD specifications (bit 0 is the first bit of the octect - ETSI GS QKD 004 v1.1.1 (2010-12), page 9, table 1)
					key = convertToBytes(key, key_length)

					# insert record in previously exchanged db
					if DEBUG:
						print("SELECT * FROM completedExchanges WHERE destination = '%s'" % str(destination[:-5]))
					cursor.execute("SELECT * FROM completedExchanges WHERE destination = '%s'" % str(destination[:-5]))
					result = cursor.fetchone()
					if result is None:
						handles = [key_handle]
						if DEBUG:
							print("INSERT INTO completedExchanges (destination, handles) VALUES ('%s', '%s')" % (str(destination[:-5]), json.dumps(handles)))
						cursor.execute("INSERT INTO completedExchanges (destination, handles) VALUES ('%s', '%s')" % (str(destination[:-5]), json.dumps(handles)))
					else:
						handles = json.loads(result[1])
						handles.append(key_handle)
						if DEBUG:
							print("UPDATE completedExchanges SET handles = '%s' WHERE destination = '%s'" % (json.dumps(handles), str(destination[:-5])))
						cursor.execute("UPDATE completedExchanges SET handles = '%s' WHERE destination = '%s'" % (json.dumps(handles), str(destination[:-5])))
					# remove record from currentExchange db to allows new exchanges
					if DEBUG:
						print("DELETE FROM currentExchange")
					cursor.execute("DELETE FROM currentExchange")

					status = SUCCESSFUL
					# here key can be directly returned (it is associated to the key handle passed as parameter to this function)
					return key, status
				else:
					status = INSUFFICIENT_KEY_AVAILABLE
					return None, status
			# QKD module must exchange key associated to another key handle - exchange this key, then return an error for the current key handle
			else:
				if DEBUG:
					print("UNLOCK TABLES")
				cursor.execute("UNLOCK TABLES")
				new_key_handle = result[1]

				self.module_status = BUSY
				key, verified = core.exchangeKey(key_length, QKDdestination, timeout)
				self.module_status = OPENED
				if verified == True:
					# convert the array of bits in an array of bytes
					key = convertToBytes(key, key_length)

					# save the key in vault
					client = hvac.Client(url='http://' + prefs['vault']['host'] + ':8200')
					client.token = prefs['vault']['token']
					try:
						response = client.secrets.kv.read_secret_version(path=new_key_handle)
						keys = response['data']['data']['keys']
						keys.append(str(key))
					except:
						# if key handle does not exist in vault yet
						keys = [str(key)]
					client.secrets.kv.v2.create_or_update_secret(path=new_key_handle, secret=dict(keys=keys),)
					# remove record from currentExchange db to allows new exchanges
					if DEBUG:
						print("DELETE FROM currentExchange")
					cursor.execute("DELETE FROM currentExchange")
				# return an error for the requested key handle
				status = INSUFFICIENT_KEY_AVAILABLE
				return None, status
		except Exception as e:
			# always unlock table if any error occurs
			if DEBUG:
				print(e)
				print("UNLOCK TABLES")
			cursor.execute("UNLOCK TABLES")
			# clear currentExchange table if an error occurred
			if DEBUG:
				print("DELETE FROM currentExchange")
			cursor.execute("DELETE FROM currentExchange")
			status = INSUFFICIENT_KEY_AVAILABLE
			return None, status

	'''
	 QKD_MODULE_STATUS

	Get the current status of this module.

	@return module_status
	'''
	def QKD_MODULE_STATUS(self):
		return self.module_status


@app.route('/sync', methods=['GET'])
def synchronize():
	handle_req = str(request.args.get('key_handle'))
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	if DEBUG:
		print("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % handle_req)
	cursor.execute("SELECT * FROM " + str(prefs['module']['table']) + " WHERE handle = '%s'" % handle_req)
	result = cursor.fetchone()
	if result is not None:
		# this handle has been registered with QKD_OPEN on this side too. Synchronization completed
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['module']['table']) + " WRITE")
		try:
			if DEBUG:
				print("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(handle_req))
			cursor.execute("UPDATE " + str(prefs['module']['table']) + " SET synchronized = True WHERE handle = '%s'" % str(handle_req))
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			cursor.execute("UNLOCK TABLES")
			return "Internal Server Error", 503
		return "OK", 200
	else:
		return "Not Found", 404

@app.route('/start', methods=['POST'])
def start():
	handle_req = json.loads(request.data)
	ip_req = str(request.remote_addr)
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	if DEBUG:
		print("SELECT * FROM completedExchanges WHERE destination = '%s'" % ip_req)
	try:
		# check if client is requesting a key already exchanged
		cursor.execute("SELECT * FROM completedExchanges WHERE destination = '%s'" % ip_req)
		result = cursor.fetchone()
		if result is not None:
			handles = json.loads(result[1])
			if handle_req in handles:
				# this exchange already took place, return ok
				return "OK", 200
		cursor.execute("LOCK TABLES currentExchange WRITE")
		cursor.execute("SELECT * FROM currentExchange")
		result = cursor.fetchone()
		if result is not None:
			# we already started an exchange with this destination - return an error
			return "Error", 400
		# insert this exchange as current exchange
		if DEBUG:
			print("INSERT INTO currentExchange (destination, handle) VALUES ('%s', '%s')" % (ip_req, handle_req))
			print("UNLOCK TABLES")
		cursor.execute("INSERT INTO currentExchange (destination, handle) VALUES ('%s', '%s')" % (ip_req, handle_req))
		cursor.execute("UNLOCK TABLES")
		return "OK", 200
	except Exception as e:
		# if any kind of error occurs, unlock tables before die
		if DEBUG:
			print(e)
			print("UNLOCK TABLES")
		cursor.execute("UNLOCK TABLES")
		return "Internal Server Error", 503

	

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
	# launch 
	app.run(host='0.0.0.0', port=serverPort)

if __name__ == "__main__":
	main()
