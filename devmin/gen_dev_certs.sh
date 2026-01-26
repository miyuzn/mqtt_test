#!/bin/bash
# Generate development certificates for local testing
set -e

CERT_DIR="./certs"
mkdir -p $CERT_DIR

echo "Generating CA..."
openssl req -new -x509 -days 3650 -extensions v3_ca -keyout $CERT_DIR/ca.key -out $CERT_DIR/ca.crt -subj "/CN=Dev-Local-CA" -nodes

echo "Generating Server Key..."
openssl genrsa -out $CERT_DIR/server.key 2048

echo "Generating CSR..."
openssl req -new -key $CERT_DIR/server.key -out $CERT_DIR/server.csr -config dev_cert.conf

echo "Signing Server Certificate..."
openssl x509 -req -in $CERT_DIR/server.csr -CA $CERT_DIR/ca.crt -CAkey $CERT_DIR/ca.key -CAcreateserial -out $CERT_DIR/server.crt -days 3650 -extensions v3_req -extfile dev_cert.conf

echo "Cleaning up..."
rm $CERT_DIR/server.csr $CERT_DIR/ca.srl

echo "Done! Certificates generated in $CERT_DIR"
