# The DeepL client reports its version, read from package metadata, in its user agent.
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("deepl")
