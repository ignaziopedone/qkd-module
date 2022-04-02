# QKD module 2.0

## files and modules 

### qkdm_src 
This folder contains all files related with qkdm code. 
- qkdm_server : is the file that contains the Quart server which receives and manages the incoming HTTP calls and returns results. It performs the mapping between error codes and their meaning, returning human-readable messages in case of errors. It can receive in the input parameters the name of the configuration file to use.
- api : contains all the functions called from the \code{qkdm_server} and the management function required to exchange keys, initialize the module and handle the connected QKD device.  
- asyncVaultClient :  is an asynchronous interface built to communicate with Vault, equal to the one used in the QKS. 
- qkd_device is the folder that contains the \code{QKDcore} Python interface that should be extended to handle QKD devices. The \code{fakeKE.py} file contains the fake simulated protocol used for tests purposes.  
    - QKD : is the interface class for any simulator/device implementation 
    - fakeKE : is a simple (unsecure) simulator for testing purposes, with async support. It does not map any real QKD protocol. 
- config_files folder : it contains some example configuration files 
- qkdmDockerfile : file to build the Qkdm docker image
- requirements.txt : file with pip requirements 

### tests 
This folder contains a simple http file with the requests used for testing purposes. Refers to the Quantum Key Server repository for more information. 

### docs
This folder contains project APIs and DB model both as pictures and as plantUML code

## Notes
These files have been packaged in a \textit{Docker image} to simplify the deployment of the app. The Docker image can be built from the \code{Dockerfile} in the `qkdm_src` folder with the command: 
```docker build -f <path/to/dockerfile> -t <image_name:image_tag> ```
Note that in a production environment the *Quart* web server should by run directly through the Python file, but an ASGI webserver (e.g. [Hypercorn](https://pgjones.gitlab.io/hypercorn/)) should be used in front of it. 
To run the server with Hypercorn use the command: 
```hypercorn server:app ```
The Docker image should be modified accordingly.

Because the QKDM can work both as a standalone module and connected to a QKS, the `qkdm_server` file can receive the `server` input parameter, which is a boolean that defines if the QKDM should wait for the registration to a QKS or if it must start with the data received in the configuration file. The `reset` input parameter can be used to delete any registration data present in the configuration file, thus deleting the previous registration. 

