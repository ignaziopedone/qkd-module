from QKD import QKD
import mysql.connector
import hvac
from random import randint
import yaml
import time
from flask import Flask, request
import requests
import multiprocessing
from multiprocessing import Process
import logging

pref_file = open("configM.yaml", 'r')
prefs = yaml.safe_load(pref_file)

app = Flask(__name__)
server = None
serverPort = 4000

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


@app.route('/sendRegister', methods=['POST'])
def getQuantumKey():
	key = eval(request.data)
	requestIP = request.remote_addr
	# retrieve information about this destination if any
	db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
	cursor = db.cursor()
	cursor.execute("SELECT * FROM " + str(prefs['simulator']['table']))
	result = cursor.fetchone()
	if result is not None:
		# previous key exchange is not completed yet, return an error
		return "Error", 400
	else:
		# a new key exchange can be started
		# save key in vault
		client = hvac.Client(url='http://' + prefs['vault']['host'] + ':' + str(prefs['vault']['port']))
		client.token = prefs['vault']['token']
		client.secrets.kv.v2.create_or_update_secret(path='currentKey', secret=dict(key=key),)
		# insert information in db
		cursor.execute("INSERT INTO " + str(prefs['simulator']['table']) + " (requestIP, complete, verified) VALUES ('%s', True, True)" % (requestIP))
		return "OK", 200



class fakeKE(QKD):
	def exchangeKey(self, key_length, destination='http://localhost:4000', timeout=0, source=1, eve=False):
		app.logger.info('Starting key exchange. Desired key length: %s' % str(key_length))
		# sender source code
		if source == 1:
			# generate a new fake key
			key = []
			for i in range(key_length):
				key.append(randint(0,1))
			# forward the key to destination
			x = requests.post(destination + '/sendRegister?newKey=true&keyLen=' + str(key_length), data = repr(key))
			if x.status_code != 200:
				# send key failed
				return None, False
			# key exchange succeded
			return key, True

		# destination source code
		else:
			# check if a key has already been exchanged with desired destination
			destAddr = str(destination.split(':')[1][2:])
			db = mysql.connector.connect(host=str(prefs['internal_db']['host']), port=str(prefs['internal_db']['port']), user=str(prefs['internal_db']['user']), passwd=str(prefs['internal_db']['passwd']), database=str(prefs['internal_db']['database']), autocommit=True)
			cursor = db.cursor()
			cursor.execute("SELECT * FROM " + str(prefs['simulator']['table']))
			result = cursor.fetchone()
			if result is None:
				# key has not been received yet, wait until the key is received or timeout elapses
				start_time = current_time()
				while result is None:
					cursor.execute("SELECT * FROM " + str(prefs['simulator']['table']))
					result = cursor.fetchone()
					if current_time() > start_time + timeout:
						# timeout elapsed - clean requests list
						cursor.execute("DELETE FROM " + str(prefs['simulator']['table']))
						return None, 4

			# now key exchange is complete
			verified = result[3]
			# key is saved in vault
			client = hvac.Client(url='http://' + prefs['vault']['host'] + ':' + str(prefs['vault']['port']))
			client.token = prefs['vault']['token']
			response = client.secrets.kv.read_secret_version(path='currentKey')
			key = response['data']['data']['key']
			# delete key once returned
			client.secrets.kv.delete_metadata_and_all_versions('currentKey')
			# once key has been exchange, delete its data from this module
			cursor.execute("LOCK TABLES " + str(prefs['simulator']['table']) + " WRITE")
			cursor.execute("DELETE FROM " + str(prefs['simulator']['table']))
			return key, verified

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
