# E-Textile Online Receive System Setup & Usage Guide

## 1. Setup Guide

Driver: CP2102N USB to UART

### 1.1 Board Flash

Check Board vision(on board):
V2.1: two connector
V2.2.c: board with 24 eclipse pin

Tool: Flash Download Tool

ChipType: ESP32-S3
WorkMode: Develop
Load Mode: UART

SPIDownload: rom file @ 0x0

SPI SPEED: 80Mhz 
SPI MODE: QIO

Select correct COM port
BAUD: 1152000

### 1.2 WiFi Configuration
Enter WiFi Configuration Status: Switch on/off 5 times (only LED light on counts)

Phone App: ESP BLE Provisioning (AppStore / Google Play Store)

Provision New Device -> I don't have a QR code -> BLE -> Select Device -> WiFi Config
### 1.3 Board License
#### 1.3.1 WebUI Configuration Method
WebUI Configuration Method need implement System (Chapter 2) at first

Server Configuration address: http://163.143.136.103:5002/
Local Configuration address: http://127.0.0.1:5002/

#### 1.3.2 Python Script Method
Run send_filter_config.py
1. Broadcast address: default
2. Broadcast times: 10

Remember device ip, mac.

Run /license/license_gen.py
Download private key priv.pem from NAS: Public/ESP32/priv.pem
Copy priv.pem to ./
1. Generate and push
2. Copy device mac addr. to Device code
3. set License duration
4. default priv.pem
5. set license type
6. Copy device IP to Target IP
7. default port


## 2. Usage Guide

### 2.1 System Implementation

git clone https://github.com/miyuzn/mqtt_test

Generate SSL keys: run /scripts/dev_generate_certs.ps1

### 2.2 Usage of WebUI Server
WebUI Server is implemented at https://isensing-s1.u-aizu.ac.jp/ or https://163.143.136.103/


### 2.3 Local Version of WebUI System

/devmin/docker-compose.yml -> Run all services

Run devmin/data_receive_local.py 

Environment Requirement:
Python 3.10 above
pip install paho.mqtt


