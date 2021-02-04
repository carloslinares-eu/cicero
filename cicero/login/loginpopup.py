import tkinter.ttk
import tkinter.filedialog
from google.oauth2 import service_account
from google.cloud import texttospeech


login_window = tkinter.Tk()
login_window.title("CICERO - Login")
login_window.geometry("400x120")

login_window.iconbitmap("cicero/cicero.ico")
text_format_01 = ("Segoe UI", 10)

login_data = None
scoped_login_data = None


def browse_license_file(entry_widget):
    license_extension = (("JavaScript Object Notation", "*.json"), ("All files", "*.*"))
    prompt_title = "Open License File"
    license_file = tkinter.filedialog.askopenfile(filetypes=license_extension, title=prompt_title)
    entry_widget.delete(0, 'end')
    entry_widget.insert(0, license_file.name)


def load_service_account_file(entry_widget):
    global login_data, scoped_login_data
    license_file_path = entry_widget.get()

    try:
        login_data = service_account.Credentials.from_service_account_file(license_file_path)
        scoped_login_data = login_data.with_scopes(['https://www.googleapis.com/auth/cloud-platform'])
        client = texttospeech.TextToSpeechClient(credentials=credentials)

    except FileNotFoundError:
        print('File not found')
    except AttributeError:
        print('File corrupted')





license_label = tkinter.Label(login_window, text="Select a License File", anchor="w", font=text_format_01)
license_entry = tkinter.Entry(login_window, font=text_format_01, width=38)
browse_button = tkinter.ttk.Button(login_window, text="Browse", command=lambda: browse_license_file(license_entry))
login_button = tkinter.ttk.Button(login_window, text="Login", command=lambda: load_service_account_file(license_entry))

license_label.grid(padx=20, pady=10, row=0, column=0, columnspan=2, sticky="W")
license_entry.grid(padx=20, pady=0, row=1, column=0, columnspan=2)
browse_button.grid(row=1, column=2, sticky="W")
login_button.grid(row=2, column=2, pady=8, sticky="W")

login_window.mainloop()
