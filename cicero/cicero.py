from login.login import LoginApp
from pptxtranslator import TranslationApp


cicero_login_app = LoginApp()
cicero_login_app.initialize()

if cicero_login_app.has_logged_in is True:
    main_translation_app = TranslationApp(credentials=cicero_login_app.credentials)
    main_translation_app.initialize()
