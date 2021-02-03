import tkinter
import tkinter.messagebox
import tkinter.scrolledtext
import tkinter.ttk
import tkinter.filedialog
import login

main_window = tkinter.Tk()
main_window.title("CICERO - ATEXIS Powerpoint Translator App")
main_window.geometry("500x400")
# main_window.resizable(0, 0)
# main_window.iconbitmap("@./cicero.ico")
text_format_01 = ("Segoe UI", 10)
text_format_02 = ("Segoe UI", 8)
text_format_03 = ("Segoe UI", 6)

main_width = 60

languages = ["English - UK", "French", "Spanish"]


def set_input(entry):
    powerpoint_extension = (("Powerpoint presentation", "*.pptx"), ("All files", "*.*"))
    prompt_title = "Open Powerpoint presentation"
    path_to_file = tkinter.filedialog.askopenfile(filetypes=powerpoint_extension, title=prompt_title)
    entry.delete(0, 'end')
    entry.insert(0, path_to_file.name)


def set_output(entry):
    powerpoint_extension = (("Powerpoint presentation", "*.pptx"), ("All files", "*.*"))
    prompt_title = "Save Powerpoint presentation"
    path_to_file = tkinter.filedialog.asksaveasfilename(filetypes=powerpoint_extension, title=prompt_title)
    entry.delete(0, 'end')
    entry.insert(0, path_to_file)


def translate_powerpoint_file(input, output, original_language, translated_language):
    credentials, scoped_credentials = login.login_with_json("/home/carlos/Documentos/cicero/ATX-CORP-AIresearch-f7577a6626b5.json")



input_label = tkinter.Label(main_window, text="Input file", anchor="w", font=text_format_01)
input_entry = tkinter.Entry(main_window, font=text_format_01, width=54)
browse_button = tkinter.ttk.Button(main_window, text="Browse", command=lambda: set_input(input_entry))

origin_label = tkinter.ttk.Label(main_window, text="Language", anchor="w", font=text_format_02)
origin_dropdown = tkinter.ttk.Combobox(main_window, value=languages)

translation_label = tkinter.ttk.Label(main_window, text="Translation Language", anchor="w", font=text_format_02)
translation_dropdown = tkinter.ttk.Combobox(main_window, value=languages)

horizontal_separator = tkinter.ttk.Separator(main_window, orient="horizontal")

output_label = tkinter.Label(main_window, text="Output file", anchor="w", font=text_format_01)
output_entry = tkinter.Entry(main_window, font=text_format_01, width=54)
save_button = tkinter.ttk.Button(main_window, text="Save", command=lambda: set_output(output_entry))

translate_button = tkinter.ttk.Button(main_window, text="Translate!", command=translate_powerpoint_file)

current_row = 0
input_label.grid(padx=10, pady=10, row=current_row, column=0, columnspan=2, sticky="W")

current_row += 1
input_entry.grid(padx=10, pady=0, row=current_row, column=0, columnspan=2)
browse_button.grid(padx=10, row=current_row, column=2, sticky="EW")

current_row += 1
origin_label.grid(padx=10, pady=10, row=current_row, column=0, sticky="W")
origin_dropdown.grid(padx=10, row=current_row, column=1, columnspan=2, sticky="E", pady=5)

current_row += 1
horizontal_separator.grid(padx=10, row=current_row, column=0, columnspan=3, sticky="EW")

current_row += 1
output_label.grid(padx=10, pady=10, row=current_row, column=0, columnspan=2, sticky="W")

current_row += 1
output_entry.grid(padx=10, pady=0, row=current_row, column=0, columnspan=2)
save_button.grid(padx=10, row=current_row, column=2, sticky="EW")

current_row += 1
translation_label.grid(padx=10, pady=10, row=current_row, column=0, sticky="W")
translation_dropdown.grid(padx=10, row=current_row, column=1, columnspan=2, sticky="E", pady=5)

current_row += 1
translate_button.grid(padx=10, row=current_row, column=2, sticky="W", pady=5)


main_window.mainloop()
