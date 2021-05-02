import login
import pptxtranslator


def main():
    cicero_login_app = login.LoginApp()
    cicero_login_app.initialize()

    if cicero_login_app.has_logged_in is True:
        main_translation_app = pptxtranslator.TranslationApp(credentials=cicero_login_app.credentials)
        main_translation_app.initialize()


if __name__ == "__main__":
    main()
