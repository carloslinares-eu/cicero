from cicero.login import LoginApp
from cicero.pptxtranslator import TranslationApp
import os


def main():
    if os.path.exists("cicero/cicero.ico"):
        icon_path = "cicero/cicero.ico"
    elif os.path.exists("cicero.ico"):
        icon_path = "cicero.ico"
    else:
        print("Icon not found")
        return
    cicero_login_app = LoginApp(icon_path)
    cicero_login_app.initialize()

    if cicero_login_app.has_logged_in is True:
        main_translation_app = TranslationApp(icon_path, credentials=cicero_login_app.credentials)
        main_translation_app.initialize()


if __name__ == "__main__":
    main()
