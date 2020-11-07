# importing Qiskit
from qiskit import QuantumCircuit, ClassicalRegister, QuantumRegister, execute, BasicAer

# Import basic plotting tools
from qiskit.tools.visualization import plot_histogram

# import utility modules
import math
from flask import Flask, request
import requests
import pickle
import sys
import multiprocessing
from multiprocessing import Process
import logging
import pyspx.shake256_128f as sphincs
from trng import randomStringGen
import time
import mysql.connector
import hvac
import yaml
from QKD import QKD

# global variables
alice_key = []
alice_table = []
temp_alice_key = ''
key_length = 128
bobPublicKey = b'64ewf98wqrsdfft1^\xbf\x9a\x1e\xdc\xac+\x94\x06E\x12\xfa?\xa2\xddf'
defaultLen = 128 # can be overwritten from command line
chunk = 16 # for a local backend n can go as up as 23, after that it raises a Memory Error
alicePrivateKey=b'124986546848776451342111546854654643545484981234>\xff\xb3\xa9\x96F\x94\xbc\xadHz\xca\xcd\xc7+.'
app = Flask(__name__)
server = None
serverPort = 4000
DEBUG = False

pref_file = open("configM.yaml", 'r')
prefs = yaml.safe_load(pref_file)


# utility function - timeout parameter is expressed in milliseconds
# convert epoch time to milliseconds
current_time = lambda: int(round(time.time() * 1000))


def run():
	fh = logging.FileHandler('bb84.log')
	formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	fh.setFormatter(formatter)
	app.logger.addHandler(fh)
	app.logger.setLevel(logging.DEBUG)
	app.run(host='0.0.0.0', port=serverPort)


def SendState(qc1, qc2, qc1_name, qr):
	''' This function takes the output of a circuit qc1 (made up only of x and 
		h gates and initializes another circuit qc2 with the same state
	''' 

	# Quantum state is retrieved from qasm code of qc1
	qs = qc1.qasm().split(sep=';')[4:-1]
	#print(qs)

	# Process the code to get the instructions
	for index, instruction in enumerate(qs):
		qs[index] = instruction.lstrip()
	#print(qs)

	# Parse the instructions and apply to new circuit
	for instruction in qs:
		if instruction[0] == 'x':
			old_qr = int(instruction[5:-1])
			qc2.x(qr[old_qr])
		elif instruction[0] == 'h':
			old_qr = int(instruction[5:-1])
			qc2.h(qr[old_qr])
		elif instruction[0] == 'm': # exclude measuring:
			pass
		else:
			raise Exception('Unable to parse instruction')

@app.route('/sendRegister', methods=['POST'])
def getQuantumKey():
	global temp_alice_key
	global alice_key
	global alice_table
	global key_length

	bob = pickle.loads(request.data)
	#print(alice)

	# check if this is a new key
	new = request.args.get('newKey')
	if(new == 'true'):
		requestIP = request.remote_addr
		# retrieve information about this destination if any
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['simulator']['table']) + " WRITE")
		try:
			if DEBUG:
				print("SELECT * FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % requestIP)
			cursor.execute("SELECT * FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % requestIP)
			result = cursor.fetchone()
			if result is not None:
				# an exchange for this key is already in progress, return an error
				# release db lock
				cursor.execute("UNLOCK TABLES")
				return "Error", 400
			else:
				# a new key exchange can be started
				# insert information
				if DEBUG:
					print("INSERT INTO " + str(prefs['simulator']['table']) + " (requestIP, complete, exchangedKey, verified) VALUES ('%s', False, NULL, False)" % (requestIP))
				cursor.execute("INSERT INTO " + str(prefs['simulator']['table']) + " (requestIP, complete, exchangedKey, verified) VALUES ('%s', False, NULL, False)" % (requestIP))
			# release db lock
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			# always release lock before quit
			cursor.execute("UNLOCK TABLES")
			raise(e)
		# new key requested - reset all variables
		alice_table = []
		alice_key = []
		# get key length
		key_length = int(request.args.get('keyLen'))
		app.logger.info('New key exchange requested from client. Desired key length %s' % str(key_length))

	# try to generate a quantum circuit with the given quantum register
	qr = QuantumRegister(chunk, name='qr')
	cr = ClassicalRegister(chunk, name='cr')
	# Quantum circuit for bob state
	alice = QuantumCircuit(qr, cr, name='Alice')
	SendState(bob, alice, 'Bob', qr)

	# randomly chose basis for measurement
	for index in range(len(qr)): 
		if 0.5 < int(randomStringGen(1)):  # With 50% chance...
			alice.h(qr[index])        # ...change to diagonal basis
			alice_table.append('X')
		else:
			alice_table.append('Z')

	# Measure all qubits
	for index in range(len(qr)): 
		alice.measure(qr[index], cr[index])

	# Execute the quantum circuit
	backend = BasicAer.get_backend('qasm_simulator')
	result = execute(alice, backend=backend, shots=1).result()

	# Result of the measure is Alice's key candidate
	temp_alice_key = list(result.get_counts(alice))[0]
	temp_alice_key = temp_alice_key[::-1]      # key is reversed so that first qubit is the first element of the list
	#print(temp_alice_key)

	return "OK"

@app.route('/compareBasis', methods=['POST'])
def compareBasis():
	global alice_key
	global alice_table

	res = eval(request.data)
	bob_table = res[0]
	tableSign = res[1]

	# check that table was actually sent from Bob
	# convert ascii list to bytes string
	b = ''
	for i in range(len(bob_table)):
		b += bob_table[i]
	if not sphincs.verify(b.encode(), tableSign, bobPublicKey):
		app.logger.error("Table comparison failed due to wrong signature!")
		return "Unauthorized", 401

	keep = []
	discard = []
	for qubit, basis in enumerate(zip(bob_table, alice_table)):
		if basis[0] == basis[1]:
			#print("Same choice for qubit: {}, basis: {}" .format(qubit, basis[0])) 
			keep.append(qubit)
		else:
			#print("Different choice for qubit: {}, Alice has {}, Bob has {}" .format(qubit, basis[0], basis[1]))
			discard.append(qubit)

	#print('Percentage of qubits to be discarded according to table comparison: ', len(keep)/chunk)

	# get new key
	alice_key += [temp_alice_key[qubit] for qubit in keep]

	# prepare reply
	reply = alice_table
	# sign reply to let Bob trust us
	# convert ascii list to bytes string
	a = ''
	for i in range(len(alice_table)):
		a += alice_table[i]
	repSign = sphincs.sign(a.encode(), alicePrivateKey)
	# reset alice_table for next comparisons
	alice_table = []

	return repr([reply, repSign])

@app.route('/verifyKey', methods=['POST'])
def verifyKey():
	global alice_key

	# key exchange completed

	# verify key
	req = eval(request.data)
	bobKey = req[0]
	keySign = req[1]
	picked = req[2]
	pickSign = req[3]

	# check that message actually comes from Bob
	if not sphincs.verify(bytes(bobKey), keySign, bobPublicKey):
		app.logger.error("Key verification failed due to wrong signature!")
		return "Unauthorized", 401
	if not sphincs.verify(bytes(picked), pickSign, bobPublicKey):
		app.logger.error("Key verification failed due to wrong signature!")
		return "Unauthorized", 401

	# get part of the key to be used during key verification
	verifyingKey = []
	# add picked bit to verifyingKey and remove them from the key
	for i in sorted(picked, reverse=True):
		verifyingKey.append(int(alice_key[i]))
		del alice_key[i]

	# make sure key length is exactly equals to key_length
	alice_key = alice_key[:key_length]
	app.logger.info("New Alice's key: %s" % alice_key)
	app.logger.info("key len: %s" % str(len(alice_key)))

	# prepare our reply - sign this key part
	keySignature = sphincs.sign(bytes(verifyingKey), alicePrivateKey)

	# check that Alice and Bob have the same key
	acc = 0
	for bit in zip(verifyingKey, bobKey):
		if bit[0] == bit[1]:
			acc += 1

	app.logger.info('\nPercentage of similarity between the keys: %s' % str(acc/len(verifyingKey)))

	if (acc//len(verifyingKey) == 1):
		verified = True
		app.logger.info("\nKey exchange has been successfull")
	else:
		verified = False
		app.logger.error("\nKey exchange has been tampered! Check for eavesdropper or try again")

	# save key
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	# use a lock to access database to avoid concurrency access
	cursor.execute("LOCK TABLES " + str(prefs['simulator']['table']) + " WRITE")
	try:
		# save key in vault
		client = hvac.Client(url='http://' + prefs['vault']['host'] + ':8200')
		client.token = prefs['vault']['token']
		client.secrets.kv.v2.create_or_update_secret(path='currentKey', secret=dict(key=alice_key),)
		if DEBUG:
			print('UPDATE ' + str(prefs["simulator"]["table"]) + ' SET complete = True, verified = %d WHERE requestIP = "%s"' % (verified, request.remote_addr))
		cursor.execute('UPDATE ' + str(prefs["simulator"]["table"]) + ' SET complete = True, verified = %d WHERE requestIP = "%s"' % (verified, request.remote_addr))
		cursor.execute("UNLOCK TABLES")
	except Exception as e:
		# error occurred - clean requests list
		if DEBUG:
			print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (request.remote_addr))
		cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (request.remote_addr))
		# always release lock before quit
		cursor.execute("UNLOCK TABLES")
		raise(e)

	return repr([verifyingKey, keySignature])


# generateQubits
# generates a random string and encodes it in a quantum circuit
# @return: the quantum circuit generated, the basis table used to measure the qubits and the measurement results
def generateQubits(eve=False):
	# Creating registers with n qubits
	qr = QuantumRegister(chunk, name='qr')
	cr = ClassicalRegister(chunk, name='cr')

	# Quantum circuit for alice state
	alice = QuantumCircuit(qr, cr, name='Alice')

	# Generate a random number in the range of available qubits [0,65536))
	temp_alice_key = randomStringGen(chunk)
	#app.logger.info("key: ", temp_alice_key)

	# Encode key as alice qubits 
	# IBM's qubits are all set to |0> initially
	for index, digit in enumerate(temp_alice_key):
		if digit == '1':
			alice.x(qr[index]) # if key has a '1', change state to |1>
		
	# Switch randomly about half qubits to diagonal basis
	alice_table = []        # Create empty basis table
	for index in range(len(qr)):       # BUG: enumerate(q) raises an out of range error
		if 0.5 < int(randomStringGen(1)):   # With 50% chance...
			alice.h(qr[index])         # ...change to diagonal basis
			alice_table.append('X')    # character for diagonal basis
		else:
			alice_table.append('Z')    # character for computational basis

	# Measure all qubits
	for index in range(len(qr)): 
		alice.measure(qr[index], cr[index])

	# Execute the quantum circuit
	backend = BasicAer.get_backend('qasm_simulator')
	result = execute(alice, backend=backend, shots=1).result()
	'''
	# I qubit misurati non restano polarizzati, se misuro di nuovo ottengo dei dati casuali (nella base X - la Z dà
	# comunque risultati certi perchè il qubit viene inizializzato a |0>). Questo spiegherebbe perchè l'invio del solo
	# quantum register non funziona e devo inviare l'intero circuito per la copia.
	# Quindi non posso usare come chiave la misurazione di questo circuito.
	# In un vero computer quantistico invece funzionerebbe, giusto??????

	temp_alice_key = list(result.get_counts(alice))[0]
	temp_alice_key = temp_alice_key[::-1]      # key is reversed so that first qubit is the first element of the list
	app.logger.info("measure: ", temp_alice_key)
	#backend = BasicAer.get_backend('qasm_simulator')    
	result = execute(alice, backend=backend, shots=1).result()
	temp_alice_key = list(result.get_counts(alice))[0]
	temp_alice_key = temp_alice_key[::-1]      # key is reversed so that first qubit is the first element of the list
	app.logger.info("measure: ", temp_alice_key)
	result = execute(alice, backend=backend, shots=1).result()
	temp_alice_key = list(result.get_counts(alice))[0]
	temp_alice_key = temp_alice_key[::-1]      # key is reversed so that first qubit is the first element of the list
	app.logger.info("measure: ", temp_alice_key)
	'''

	if eve:
		# EVE is listening on the quantum channel - now she makes her measurements
		eve = QuantumCircuit(qr, cr, name='Eve')
		SendState(alice, eve, 'Alice', qr)
		eve_table = []
		for index in range(len(qr)):
			if 0.5 < int(randomStringGen(1)):
				eve.h(qr[index])
				eve_table.append('X')
			else:
				eve_table.append('Z')

		for index in range(len(qr)):
			eve.measure(qr[index], cr[index])

		# Execute (build and run) the quantum circuit
		backend = BasicAer.get_backend('qasm_simulator')
		result = execute(eve, backend=backend, shots=1).result()

		# Result of the measure is Eve's key
		eve_key = list(result.get_counts(eve))[0]
		eve_key = eve_key[::-1]
		# Eve's measurements changed qubits polarization - here we return Eve's circuit to remark this behavior
		return eve, alice_table, temp_alice_key

	# return quantum circuit, basis table and temporary key
	return alice, alice_table, temp_alice_key

'''
generateQubits()
'''

# getKeyChunk
# generate and exchange a chunk of quantum bits.
# @param firstChunk: if true, we are requesting a new key exchange - if false this is just a piece of the key exchange
# @param generateLength: length of the key to be generated
# @return: a piece of key already validated between sender and receiver
def getKeyChunk(destination='http://localhost:4000', firstChunk=False, generateLength=128, eve=False):
	global alicePrivateKey
	# generate a chunk of the temporary key
	qc, alice_table, temp_alice_key = generateQubits(eve)
	qcSerialized = pickle.dumps(qc)
	#app.logger.info(qc)

	# send our quantum register
	if(firstChunk == True):
		x = requests.post(destination + '/sendRegister?newKey=true&keyLen=' + str(generateLength), data = qcSerialized)
	else:
		x = requests.post(destination + '/sendRegister', data = qcSerialized)
	if x.status_code != 200:
		app.logger.error("Server error occurred %s" % x.status_code)
		return None

	# sign alice_table before sending it
	# convert ascii list to bytes string
	a = ''
	for i in range(len(alice_table)):
		a += alice_table[i]
	aliceSign = sphincs.sign(a.encode(), alicePrivateKey)

	# compare basis table
	y = requests.post(destination + '/compareBasis', data = repr([alice_table, aliceSign]))
	rep = eval(y.content)
	bob_table = rep[0]
	tableSign = rep[1]
	# check that table was actually sent from Bob
	b = ''
	for i in range(len(bob_table)):
		b += bob_table[i]
	if not sphincs.verify(b.encode(), tableSign, bobPublicKey):
		app.logger.error("Table comparison failed due to wrong signature!")
		return None

	keep = []
	discard = []
	for qubit, basis in enumerate(zip(alice_table, bob_table)):
		if basis[0] == basis[1]:
			#print("Same choice for qubit: {}, basis: {}" .format(qubit, basis[0]))
			keep.append(qubit)
		else:
			#print("Different choice for qubit: {}, Alice has {}, Bob has {}" .format(qubit, basis[0], basis[1]))
			discard.append(qubit)

	#print('Percentage of qubits to be discarded according to table comparison: ', len(keep)/chunk)
	return [temp_alice_key[qubit] for qubit in keep]


class BB84(QKD):
	def exchangeKey(self, key_length, destination='http://localhost:4000', timeout=0, eve=False):
		# delay the start of the exchange of a random number of seconds (between 0 and 8)
		randNo = randomStringGen(3)
		# convert bit string into bytes
		randNo = int(randNo, 2)
		time.sleep(randNo)

		app.logger.info('Starting key exchange. Desired key length: %s' % str(key_length))
		# 1/3 of the key needs to be exchanged in order to verify key
		# that part of the key cannot be used anymore after key verification
		# generate 1/3 more than key_length that will then be exchanged
		# in this way final key length will be as equals as key_length
		key_length = int(key_length)
		generateLength = round(key_length + (key_length / 3))

		# check if a key has already been exchanged with desired destination
		destAddr = str(destination.split(':')[1][2:])
		db = mysql.connector.connect(host=str(prefs['internal_db']['host']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
		cursor = db.cursor()
		# use a lock to access database to avoid concurrency access
		cursor.execute("LOCK TABLES " + str(prefs['simulator']['table']) + " WRITE")
		try:
			if DEBUG:
				print("SELECT * FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % (destAddr))
			cursor.execute("SELECT * FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % (destAddr))
			result = cursor.fetchone()
			if result is not None:
				if DEBUG:
					print("match found")
				# a key with this id has already been requested from server side
				# wait until the whole key is received
				# release lock during wait
				cursor.execute("UNLOCK TABLES")
				start_time = current_time()
				while bool(result[1]) is not True:
					if DEBUG:
						print("key exchange not completed yet")
						print("SELECT * FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % (destAddr))
					cursor.execute("SELECT * FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % (destAddr))
					result = cursor.fetchone()
					if current_time() > start_time + timeout:
						# timeout elapsed - clean requests list
						if DEBUG:
							print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
						cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
						return None, 4
				if DEBUG:
					print("result found - returning it")
				# now key exchange is complete
				verified = result[3]
				# key is saved in vault
				client = hvac.Client(url='http://' + prefs['vault']['host'] + ':8200')
				client.token = prefs['vault']['token']
				response = client.secrets.kv.read_secret_version(path='currentKey')
				key = response['data']['data']['key']
				# delete key once returned
				client.secrets.kv.delete_metadata_and_all_versions('currentKey')
				# once key has been exchange, delete its data from this module
				cursor.execute("LOCK TABLES " + str(prefs['simulator']['table']) + " WRITE")
				if DEBUG:
					print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
				cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
				cursor.execute("UNLOCK TABLES")
				return key, verified
			else:
				if DEBUG:
					print("match not found - start key exchange")
					print("INSERT INTO " + str(prefs['simulator']['table']) + " (requestIP, complete, exchangedKey, verified) VALUES ('%s', False, NULL, False)" % (destAddr))
				# start key exchange - save information
				cursor.execute("INSERT INTO " + str(prefs['simulator']['table']) + " (requestIP, complete, exchangedKey, verified) VALUES ('%s', False, NULL, False)" % (destAddr))
			# release lock
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			# error occurred - clean requests list
			if DEBUG:
				print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
			cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
			# always release lock before quit
			cursor.execute("UNLOCK TABLES")
			raise(e)

		# get the first piece of the key
		alice_key = getKeyChunk(destination, True, key_length, eve)
		if alice_key is None:
			# get key chunk failed
			# since exchange failed, delete record from db
			if DEBUG:
				print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % (destAddr))
			cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE requestIP = '%s'" % (destAddr))
			return None, False
		current_len = len(alice_key)

		# exchange all qubit needed up to key_length
		while current_len < generateLength:
			# get a new piece of key
			keyChunk = getKeyChunk(destination, eve=eve)
			if keyChunk is None:
			# error occurred - clean requests list
				if DEBUG:
					print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (request.remote_addr))
				cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (request.remote_addr))
				return None, False
			# append the new piece to the key
			alice_key += keyChunk
			current_len += len(keyChunk)

		# randomly select bit to be used for key verification
		picked, verifyingKey = [], []
		i = 0
		# we need to generate a random number between 0 and generateLength
		# randomStringGen generates a string of bit - calculate how many bit we need to get a consistent top value
		bits = 0
		temp = generateLength
		while temp > 0:
			temp = temp >> 1
			bits += 1
		while i < generateLength - key_length:
			# generate a valid random number (in range 0 - key_length + generateLength and not already used)
			while True:
				randNo = randomStringGen(bits)
				# convert bit string into bytes
				randNo = int(randNo, 2)
				if randNo >= generateLength:
					# not a valid number
					continue
				if randNo in picked:
					# number already used
					continue
				# number is valid - exit from this inner loop
				break
			# add randNo to list of picked
			picked.append(randNo)
			i += 1

		# remove used bits from the key
		for i in sorted(picked, reverse=True):
			verifyingKey.append(int(alice_key[i]))
			del alice_key[i]

		# make sure key length is exactly equals to key_length
		alice_key = alice_key[:key_length]

		app.logger.info("Key exchange completed - new key: %s" % alice_key)
		app.logger.info("key len: %s" % str(len(alice_key)))

		# delete info once key exchange is complete
		try:
			cursor.execute("LOCK TABLES " + str(prefs['simulator']['table']) + " WRITE")
			if DEBUG:
				print("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
			cursor.execute("DELETE FROM " + str(prefs['simulator']['table']) + " WHERE `requestIP` = '%s'" % (destAddr))
			cursor.execute("UNLOCK TABLES")
		except Exception as e:
			# always release lock before quit
			cursor.execute("UNLOCK TABLES")
			raise(e)

		# sign data with our private key
		keySign = sphincs.sign(bytes(verifyingKey), alicePrivateKey)
		pickSign = sphincs.sign(bytes(picked), alicePrivateKey)
		# send data and signature to verify key exchange
		x = requests.post(destination + '/verifyKey', data = repr([verifyingKey, keySign, picked, pickSign]))
		if x.status_code != 200:
			app.logger.error("Server error occurred %s" % x.status_code)
			return alice_key, False

		# get Bob's reply
		rep = eval(x.content)
		bobKey = rep[0]
		bobKeySign = rep[1]

		# verify Bob's signature
		if not sphincs.verify(bytes(bobKey), bobKeySign, bobPublicKey):
			app.logger.error("Key verification failed due to wrong signature!")
			return alice_key, false

		# check that Alice and Bob have the same key
		acc = 0
		for bit in zip(verifyingKey, bobKey):
			if bit[0] == bit[1]:
				acc += 1

		app.logger.info('\nPercentage of similarity between the keys: %s' % str(acc/len(verifyingKey)))

		if (acc//len(verifyingKey) == 1):
			return alice_key, True
			app.logger.info("\nKey exchange has been successfull")
		else:
			app.logger.error("\nKey exchange has been tampered! Check for eavesdropper or try again")
			return alice_key, False


	def begin(self, port = 4000):
		global server
		global serverPort

		serverPort = port
		# configure logger
		# file logging
		fh = logging.FileHandler('bb84.log')
		formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
		fh.setFormatter(formatter)
		app.logger.addHandler(fh)
		app.logger.setLevel(logging.DEBUG)

		# start server
		app.logger.info('Starting server')
		server = Process(target=run)
		server.start()

	def end(self):
		app.logger.info('Killing threads')
		server.terminate()
		server.join()
		app.logger.info('Correctly quit application')

def main():
	# configure logger
	# file logging
	fh = logging.FileHandler('bb84.log')
	formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	fh.setFormatter(formatter)
	app.logger.addHandler(fh)
	app.logger.setLevel(logging.DEBUG)

	# start server
	app.logger.info('Starting server')
	server = Process(target=run)
	server.start()

	while True:
		app.logger.info('Waiting for commands')
		userCmd = input("waiting for user commands:\n")
		app.logger.info("processing command: %s" % userCmd)
		if "exchange key" in userCmd:
			# check if key length is specified
			try:
				data = userCmd.split(" ")
				key_length = int(data[2])
			except:
				key_length = defaultLen
			alice_key, verified = exchangeKey(key_length)
		elif "exchange with eve" in userCmd:
			try:
				data = userCmd.split(" ")
				key_length = int(data[3])
			except:
				key_length = defaultLen
			alice_key, verified = exchangeKey(key_length, eve = True)
		elif "quit" == userCmd:
			# exit
			break
		else:
			print("cmd not found")
			app.logger.warning('Unrecognized command: %s' % userCmd)

	app.logger.info('Killing threads')
	server.terminate()
	p.terminate()
	server.join()
	p.join()
	app.logger.info('Correctly quit application')

if __name__ == "__main__":
	main()
