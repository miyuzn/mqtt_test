import socket
import ssl
import sys
import os
import argparse

def test_ssl_connection(host, port, ca_cert_path):
    print(f"[*] Testing connection to {host}:{port}...")
    print(f"[*] Using CA cert: {ca_cert_path}")

    if not os.path.exists(ca_cert_path):
        print(f"[!] Error: CA certificate file not found at {ca_cert_path}")
        return

    # 1. Create a raw socket to ensure connectivity
    try:
        sock = socket.create_connection((host, port), timeout=5)
        print(f"[*] TCP connection established to {host}:{port}")
    except Exception as e:
        print(f"[!] TCP connection failed: {e}")
        return

    # 2. Create SSL Context
    # Phase 1: Inspect Remote Certificate (Insecure connection just to peek)
    print("\n[*] Phase 1: Inspecting Remote Server Certificate...")
    try:
        ctx_inspect = ssl.create_default_context()
        ctx_inspect.check_hostname = False
        ctx_inspect.verify_mode = ssl.CERT_NONE
        with ctx_inspect.wrap_socket(sock, server_hostname=host) as ssock_inspect:
            remote_cert_bin = ssock_inspect.getpeercert(binary_form=True)
            import hashlib
            remote_fingerprint = hashlib.sha256(remote_cert_bin).hexdigest()
            print(f"    Remote Cert SHA256 Fingerprint: {remote_fingerprint[:16]}...{remote_fingerprint[-16:]}")
    except Exception as e:
        print(f"    [!] Failed to inspect remote cert: {e}")
        # Re-connect for Phase 2
        try:
            sock = socket.create_connection((host, port), timeout=5)
        except:
            return

    # Phase 1b: Inspect Local Expected Certificate
    local_crt_path = os.path.join(os.path.dirname(ca_cert_path), "mosquitto.crt")
    if os.path.exists(local_crt_path):
        try:
            with open(local_crt_path, "rb") as f:
                content = f.read()
                # Simple parsing of PEM to DER for fingerprinting (simulated)
                # Or just warn user to check file dates.
                import base64
                lines = content.decode().strip().splitlines()
                b64_data = "".join([l for l in lines if not l.startswith("-----")])
                local_der = base64.b64decode(b64_data)
                local_fingerprint = hashlib.sha256(local_der).hexdigest()
                print(f"    Local  Cert SHA256 Fingerprint: {local_fingerprint[:16]}...{local_fingerprint[-16:]}")
                
                if remote_fingerprint != local_fingerprint:
                    print("\n[!!!] CRITICAL MISMATCH DETECTED [!!!]")
                    print("    The certificate served by the remote host is DIFFERENT from your local 'mosquitto.crt'.")
                    print("    PROOF: The fingerprints do not match.")
                    print("    ACTION: You MUST upload the local 'certs/' files to the server and RESTART Mosquitto.")
                    return # Stop here, no point verifying
                else:
                    print("    [OK] Fingerprints match. The server has the correct certificate.")
        except Exception as e:
            print(f"    (Could not compare with local mosquitto.crt: {e})")

    # Re-connect for Phase 2 (Validation)
    try:
        sock.close()
        sock = socket.create_connection((host, port), timeout=5)
    except:
        pass

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert_path)
    # Enable debug logging for SSL (if supported by environment, though Python's ssl module is limited here)
    # context.verify_mode = ssl.CERT_REQUIRED # Implied by create_default_context
    # context.check_hostname = True # Implied by create_default_context

    print("[*] Starting SSL Handshake...")
    try:
        # 3. Wrap socket
        with context.wrap_socket(sock, server_hostname=host) as ssock:
            print("[*] SSL Handshake Successful!")
            cert = ssock.getpeercert()
            print("\n--- Server Certificate ---")
            print(f"Subject: {cert.get('subject')}")
            print(f"Issuer: {cert.get('issuer')}")
            print(f"Subject Alt Names: {cert.get('subjectAltName')}")
            print(f"Cipher: {ssock.cipher()}")
            print(f"Protocol: {ssock.version()}")
            print("--------------------------\n")
            
    except ssl.SSLCertVerificationError as e:
        print(f"\n[!] SSL Verification Failed: {e}")
        print(f"[!] Reason: {e.reason}")
        print(f"[!] Verify Message: {e.verify_message}")
        print(f"[!] Verify Code: {e.verify_code}")
        
        if "certificate signature failure" in str(e):
             print("\n[HINT] 'Certificate signature failure' almost ALWAYS means the Client's CA file does not match the Server's Key.")
             print("       Did you upload the NEW 'ca.crt', 'mosquitto.crt', AND 'mosquitto.key' to the server and RESTART Mosquitto?")
    except ssl.SSLError as e:
        print(f"\n[!] SSL Protocol Error: {e}")
    except Exception as e:
        print(f"\n[!] General Error during handshake: {e}")
    finally:
        try:
            sock.close()
        except:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_ssl_handshake.py <HOST> <PORT> [CA_PATH]")
        print("Default CA_PATH is 'certs/ca.crt'")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    ca_path = sys.argv[3] if len(sys.argv) > 3 else "certs/ca.crt"

    test_ssl_connection(host, port, ca_path)
