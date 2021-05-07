from PyInstaller.utils.hooks import copy_metadata, collect_data_files
datas = copy_metadata('google-cloud-translate')
datas += collect_data_files('grpc')
