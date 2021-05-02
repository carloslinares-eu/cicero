import tkinter.ttk
import tkinter.filedialog
import tkinter.messagebox
import google.oauth2.service_account
import google.cloud.translate_v2
import google.auth.exceptions


class LoginApp:
    def __init__(self):
        self.root = tkinter.Tk()
        self.root.title("CICERO - Login")
        self.root.geometry("400x120")
        self.root.resizable(0, 0)
        self.root.iconbitmap("cicero/resources/cicero.ico")
        self.text_format_01 = ("Segoe UI", 10)

        self.license_label = tkinter.Label(self.root, text="Select License File", anchor="w", font=self.text_format_01)
        self.license_entry = tkinter.Entry(self.root, font=self.text_format_01, width=38)
        self.browse_button = tkinter.ttk.Button(self.root, text="Browse", command=self.browse_service_account_file)
        self.login_button = tkinter.ttk.Button(self.root, text="Login", command=self.login_into_main_app)

        self.credentials = None
        self.credentials_scoped = None
        self.has_logged_in = False

        self.valid_license_filetypes = (("JavaScript Object Notation", "*.json"), ("All files", "*.*"))

    def initialize(self):
        self.license_label.grid(padx=20, pady=10, row=0, column=0, columnspan=2, sticky="W")
        self.license_entry.grid(padx=20, pady=0, row=1, column=0, columnspan=2)
        self.browse_button.grid(row=1, column=2, sticky="W")
        self.login_button.grid(row=2, column=2, pady=8, sticky="W")
        self.root.mainloop()

    def browse_service_account_file(self):
        prompt_title = "Open License File"
        license_file = tkinter.filedialog.askopenfile(filetypes=self.valid_license_filetypes, title=prompt_title)
        if license_file is not None:
            self.license_entry.delete(0, 'end')
            self.license_entry.insert(0, license_file.name)

    def load_service_account_file(self):
        file = self.license_entry.get()
        scope = ['https://www.googleapis.com/auth/cloud-platform']
        try:
            self.credentials = google.oauth2.service_account.Credentials.from_service_account_file(file)
            self.credentials_scoped = self.credentials.with_scopes(scope)

        except FileNotFoundError:
            tkinter.messagebox.showerror(title="Critical error", message="File not found")

        except AttributeError:
            tkinter.messagebox.showerror(title="Critical error", message="Incorrect credentials file")

    def check_service_account_file(self):
        translate_client = google.cloud.translate_v2.Client(credentials=self.credentials)
        try:
            translate_client.translate("TEST", target_language="EN")
            self.has_logged_in = True

        except google.auth.exceptions.RefreshError:
            refresh_error_message = "The credentials' access token failed.\n"
            refresh_error_message += "If the problem persist the key has probably expired."
            tkinter.messagebox.showerror(title="Critical error", message=refresh_error_message)
            self.has_logged_in = False

        except google.auth.exceptions.GoogleAuthError:
            auth_error_message = "Could not automatically determine credentials."
            auth_error_message += "Please, explicitly create credentials and re-run the application"
            tkinter.messagebox.showerror(title="Critical error", message=auth_error_message)
            self.has_logged_in = False

    def login_into_main_app(self):
        self.load_service_account_file()
        if self.credentials is not None:
            self.check_service_account_file()
        else:
            return
        if self.has_logged_in is True:
            self.root.destroy()
