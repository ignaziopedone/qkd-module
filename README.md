# QKD module 2.0

## files and modules 
### qkdm_src 
This folder contains all files related with qkdm code. 
- qkd_device folder contains simulator related files. 
    - QKD : Interface class for any simulator/device implementation 
    - fakeKE : simple (unsecure) simulator for testing purposes
- api : all function to be called when a request is received 
- qkdm_server : main file to be executed with flask app inside
- asyncVaultClient : interface module to intercat with vault 
- config_files folder 

## docs
This folder contains project APIs, DB and sequence diagram documentation as pictures and as plantUML code