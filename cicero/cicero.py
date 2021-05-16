import cicero.config as cfg
import cicero.pptxhandler
import cicero.translator
import tkinter
import tkinter.messagebox
import tkinter.scrolledtext
import tkinter.ttk
import tkinter.filedialog
import google.oauth2.service_account
import google.cloud.translate_v2
import google.auth.exceptions


class TranslationApp:
    def __init__(self, icon_path, credentials=None):
        self.credentials = credentials
        self.icon = icon_path
        self.translate_client = google.cloud.translate_v2.Client(credentials=self.credentials)
        self.root = tkinter.Tk()
        self.root.title("CICERO - Universal Translator App")
        self.root.geometry("500x260")
        self.root.resizable(0, 0)
        self.root.iconbitmap(self.icon)
        self.large = ("Segoe UI", 10)
        self.medium = ("Segoe UI", 8)
        self.small = ("Segoe UI", 6)
        self.main_width = 60
        self.compatible_files = (("Powerpoint presentation", "*.pptx"), ("PDF file", "*.pdf"))
        self.path_to_input = None
        self.path_to_output = None
        self.file_type = None
        self.input_language = None
        self.target_language = None
        self.temp_file = None

        self.input_label = tkinter.Label(self.root, text="Input file", anchor="w", font=self.large)
        self.input_entry = tkinter.Entry(self.root, font=self.large, width=54)
        self.browse_button = tkinter.ttk.Button(self.root, text="Browse", command=self.set_input)

        self.origin_label = tkinter.ttk.Label(self.root, text="Origin Language", anchor="w", font=self.medium)
        self.origin_combo = tkinter.ttk.Combobox(self.root)
        self.origin_combo.configure(postcommand=self.origin_combo.configure(values=self.get_language_list()))

        self.target_label = tkinter.ttk.Label(self.root, text="Target Language", anchor="w", font=self.medium)
        self.target_combo = tkinter.ttk.Combobox(self.root)
        self.target_combo.configure(postcommand=self.target_combo.configure(values=self.get_language_list()))

        self.horizontal_separator = tkinter.ttk.Separator(self.root, orient="horizontal")

        self.output_label = tkinter.Label(self.root, text="Output file", anchor="w", font=self.large)
        self.output_entry = tkinter.Entry(self.root, font=self.large, width=54)
        self.save_button = tkinter.ttk.Button(self.root, text="Save", command=self.set_output)

        self.translate_button = tkinter.ttk.Button(self.root, text="Translate!", command=self.translate_file)

    def initialize(self):
        current_row = 0
        self.input_label.grid(padx=10, pady=10, row=current_row, column=0, columnspan=2, sticky="W")

        current_row += 1
        self.input_entry.grid(padx=10, pady=0, row=current_row, column=0, columnspan=2)
        self.browse_button.grid(padx=10, row=current_row, column=2, sticky="EW")

        current_row += 1
        self.origin_label.grid(padx=10, pady=10, row=current_row, column=0, sticky="W")
        self.origin_combo.grid(padx=10, row=current_row, column=1, columnspan=2, sticky="E", pady=5)

        current_row += 1
        self.horizontal_separator.grid(padx=10, row=current_row, column=0, columnspan=3, sticky="EW")

        current_row += 1
        self.output_label.grid(padx=10, pady=10, row=current_row, column=0, columnspan=2, sticky="W")

        current_row += 1
        self.output_entry.grid(padx=10, pady=0, row=current_row, column=0, columnspan=2)
        self.save_button.grid(padx=10, row=current_row, column=2, sticky="EW")

        current_row += 1
        self.target_label.grid(padx=10, pady=10, row=current_row, column=0, sticky="W")
        self.target_combo.grid(padx=10, row=current_row, column=1, columnspan=2, sticky="E", pady=5)

        current_row += 1
        self.translate_button.grid(padx=10, row=current_row, column=2, sticky="W", pady=5)

        self.root.mainloop()

    def set_input(self):
        prompt_title = "Open file to translate"

        try:
            self.path_to_input = tkinter.filedialog.askopenfile(filetypes=self.compatible_files, title=prompt_title)
        except PermissionError:
            tkinter.messagebox.showerror(title="Critical error", message="Can't access the file. It might be open by other application")

        if self.path_to_input is not None:
            self.input_entry.delete(0, 'end')

        self.input_entry.insert(0, self.path_to_input.name)

        self.set_file_type()

    def set_file_type(self):
        self.file_type = None
        if self.path_to_input.name[-5:] == ".pptx":
            self.file_type = {("Powerpoint presentation", "*.pptx")}
        elif self.path_to_input.name[-4:] == ".pdf":
            self.file_type = {("PDF file", "*.pdf")}

    def set_output(self):
        prompt_title = "Save translated file to:"
        self.path_to_output = tkinter.filedialog.asksaveasfilename(filetypes=self.file_type, title=prompt_title)

        if self.path_to_input is not None:
            self.output_entry.delete(0, 'end')

        self.complete_output_path()
        self.output_entry.insert(0, self.path_to_output)

    def complete_output_path(self):
        if (self.file_type == {("Powerpoint presentation", "*.pptx")}) & (self.path_to_output[-5:] != ".pptx"):
            self.path_to_output += ".pptx"
        elif (self.file_type == {("PDF file", "*.pdf")}) & (self.path_to_output[-4:] != ".pdf"):
            self.path_to_output += ".pdf"

    def get_language_list(self, language_code=None):
        language_list = self.translate_client.get_languages(language_code)
        screen_name_list = []
        for language in language_list:
            screen_name_list.append(language.get("language") + " - " + language.get("name"))
        return screen_name_list

    def translate_file(self):
        self.load_values_from_gui()
        cfg.text_repository_file_path = self.path_to_output + ".txt"
        cfg.text_repository_file = open(cfg.text_repository_file_path, "w+")
        cfg.text_repository_file.write("slide" + "\t" + "id" + "\t" + "text" + "\n")

        if self.file_type == {("Powerpoint presentation", "*.pptx")}:
            self.translate_powerpoint_file()
        elif self.file_type == {("PDF file", "*.pdf")}:
            self.translate_pdf_file()
        else:
            tkinter.messagebox.showerror(title="Critical error", message="Can't perform operation: invalid file type")
            return

    def translate_powerpoint_file(self):
        cfg.active_presentation = cicero.pptxhandler.open_powerpoint_file(self.path_to_input)
        cicero.pptxhandler.extract_text_from_powerpoint(cfg.active_presentation)
        cicero.translator.read_and_group_input_string(cfg.text_repository_file_path)
        cfg.active_presentation.save(self.path_to_output)
        tkinter.messagebox.showinfo(title="Job finished", message="The file has been successfully translated")

    def translate_pdf_file(self):
        return 0

    def load_values_from_gui(self):
        self.path_to_input = self.input_entry.get()
        self.path_to_output = self.output_entry.get()
        self.input_language = self.origin_combo.get()[0:2]
        self.target_language = self.target_combo.get()[0:2]
        cfg.input_language = self.input_language
        cfg.target_language = self.target_language

