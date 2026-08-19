import os
import grpc

from dataclasses import dataclass

@dataclass
class SecurityProfile:
    """
    A configuration dataclass holding all security-related parameters for a session.
    """
    tls_ca: str = ""
    tls_cert: str = ""
    tls_key: str = ""
    skip_verify: bool = False
    tls_server_name: str = ""
    tls_version: str = ""

    ssh_key: str = ""

class SecurityModule:
    """
    A universal security profile holding X.509 certificates and keys.
    Exports credentials into formats required by different transport libraries.
    """
    def __init__(self, profile: SecurityProfile):
        self.ca_cert = profile.tls_ca
        self.client_cert = profile.tls_cert
        self.client_key = profile.tls_key
        self.skip_verify = profile.skip_verify
        self.tls_server_name = profile.tls_server_name
        self.tls_version = profile.tls_version

    def _read_file(self, path):
        if path and os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
        elif path:
            print(f"[Security] Warning: Credential file not found at {path}")
        return None

    def get_grpc_credentials(self):
        """Exports credentials for gNMI (HTTP/2 via grpc)."""
        root_certs = self._read_file(self.ca_cert)
        private_key = self._read_file(self.client_key)
        cert_chain = self._read_file(self.client_cert)

        if not private_key and not cert_chain:
            # If the user asks for TLS features, they expect an encrypted secure channel
            if self.skip_verify or self.tls_server_name:
                if self.skip_verify:
                    print(f"[Security] Python gRPC cannot modify its options - but It will be create an TLS session without any credentials")
                    return grpc.ssl_channel_credentials(root_certificates=root_certs)
            return None

        return grpc.ssl_channel_credentials(
            root_certificates=root_certs,
            private_key=private_key,
            certificate_chain=cert_chain
        )

    def get_grpc_options(self):
        """Exports gRPC channel options about secure connections"""
        options = []

        if self.tls_server_name:
            options.append(('grpc.ssl_target_name_override', self.tls_server_name))

        # 'tls_version' is meaningless for Python gRPC: it does auto-negotiate via BoringSSL.

        return options if options else None

    def get_requests_kwargs(self):
        """Exports credentials for RESTCONF (HTTPS via requests)."""
        kwargs = {}
        if self.ca_cert:
            kwargs['verify'] = self.ca_cert
        elif self.skip_verify:
            kwargs['verify'] = False
            
        if self.client_cert and self.client_key:
            kwargs['cert'] = (self.client_cert, self.client_key)
        return kwargs

    def get_ssh_kwargs(self):
        """Exports credentials for NETCONF (SSH via ncclient)."""
        kwargs = {}
        if self.client_key:
            kwargs['key_filename'] = self.client_key
        return kwargs
