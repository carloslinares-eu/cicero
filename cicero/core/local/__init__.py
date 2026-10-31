"""Translating with open-weight models on this computer, through a private Ollama server that Cicero manages.

``catalog``    the models Cicero offers and the languages each one knows
``runtime``    finding, downloading and starting Ollama, hidden from the user
``ollama``     the Ollama HTTP API: installed models, downloads, chat
``prompts``    the prompt each model was trained on, and reading its answers back
``translator`` LocalTranslator: the same Translator protocol as Google and DeepL
``hardware``   how much GPU memory there is, to say which models fit
"""
