# python-docx opens its default template from its own package data.
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = copy_metadata("python-docx") + collect_data_files("docx")
