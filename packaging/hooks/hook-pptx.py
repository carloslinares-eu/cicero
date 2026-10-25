# python-pptx opens a blank presentation template from its own package data.
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = copy_metadata("python-pptx") + collect_data_files("pptx")
