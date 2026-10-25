# The Google client libraries read their own version from package metadata at import time.
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = copy_metadata("google-cloud-translate") + copy_metadata("google-api-core") + copy_metadata("grpcio")
datas += collect_data_files("grpc")  # roots.pem, the CA bundle gRPC uses for TLS
