# QKD module 2.0

## files and modules 
### qkdm_src 
This folder contains all files related with qkdm code. 
- qkd_device folder contains simulator related files. 
    - QKD : interface class for any simulator/device implementation 
    - fakeKE : simple (unsecure) simulator for testing purposes, with async support
- api : all function to be called when a request is received 
- qkdm_server : main file to be executed with Quart app inside 
- asyncVaultClient : async module to interact with vault 
- config_files folder 

Please run the app in production with hypercorn, not by running the qkdm_server.py file. 

## docs
This folder contains project APIs, DB and sequence diagram documentation as pictures and as plantUML code