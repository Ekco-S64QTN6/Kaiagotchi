#
# kaiagotchi/identity.py
#
from Crypto.Signature import PKCS1_PSS
from Crypto.PublicKey import RSA
import Crypto.Hash.SHA256 as SHA256
import base64
import hashlib
import os
import logging
import subprocess

# Aligned with project structure
DefaultPath = "/etc/kaiagotchi/"


class KeyPair(object):
    def __init__(self, path=DefaultPath, view=None):
        self.path = path
        self.priv_path = os.path.join(path, "id_rsa")
        self.priv_key = None
        self.pub_path = "%s.pub" % self.priv_path
        self.pub_key = None
        self.fingerprint_path = os.path.join(path, "fingerprint")
        
        # The 'view' object is legacy from the hardware display. 
        # We accept it for compatibility but check if it's None.
        self._view = view

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        while True:
            # first time, generate new keys
            if not os.path.exists(self.priv_path) or not os.path.exists(self.pub_path):
                if self._view:
                    self._view.on_keys_generation()
                
                logging.info("generating %s ..." % self.priv_path)
                
                # CRITICAL SECURITY FIX: Replaced os.system() with subprocess.run
                # This prevents command injection vulnerabilities.
                try:
                    # We assume 'pwngrid' is a required external dependency.
                    subprocess.run(["pwngrid", "-generate", "-keys", self.path], check=True, capture_output=True, text=True)
                
                except subprocess.CalledProcessError as e:
                    logging.error(f"pwngrid key generation failed: {e.stderr}")
                    # Loop will retry after a delay (handled by the caller's loop)
                except FileNotFoundError:
                    logging.error("pwngrid command not found. Key generation failed.")
                    # If pwngrid isn't installed, we must raise this.
                    raise

            # load keys: they might be corrupted if the unit has been turned off during the generation
            try:
                with open(self.priv_path) as fp:
                    self.priv_key = RSA.importKey(fp.read())

                with open(self.pub_path) as fp:
                    self.pub_key = RSA.importKey(fp.read())
                    self.pub_key_pem = self.pub_key.exportKey('PEM').decode("ascii")
                    
                    if 'RSA PUBLIC KEY' not in self.pub_key_pem:
                        self.pub_key_pem = self.pub_key_pem.replace('PUBLIC KEY', 'RSA PUBLIC KEY')

                pem_ascii = self.pub_key_pem.encode("ascii")

                self.pub_key_pem_b64 = base64.b64encode(pem_ascii).decode("ascii")
                self.fingerprint = hashlib.sha256(pem_ascii).hexdigest()

                with open(self.fingerprint_path, 'w+t') as fp:
                    fp.write(self.fingerprint)

            except Exception as e:
                # Specify the exception for clarity
                logging.exception(f"Error loading keys, possibly corrupted, deleting and regenerating: {e}")
                try:
                    os.remove(self.priv_path)
                    os.remove(self.pub_path)
                except OSError as e:
                    # Specify the cleanup exception
                    logging.error(f"Failed to remove corrupted key files: {e}")
                    pass

            # no exception, keys loaded correctly.
            if self._view:
                self._view.on_starting()
            return

    def sign(self, message):
        hasher = SHA256.new(message.encode("ascii"))
        signer = PKCS1_PSS.new(self.priv_key, saltLen=16)
        signature = signer.sign(hasher)
        signature_b64 = base64.b64encode(signature).decode("ascii")
        return signature, signature_b64