import PyPDF4

global page_counter, number_of_pages


def open_pdf_file(path_to_input):
    global number_of_pages
    with open(path_to_input, 'rb') as f:
        read_pdf = PyPDF4.PdfFileReader(f)
        number_of_pages = read_pdf.getNumPages()

        return read_pdf


def extract_text_from_pdf(active_pdf):
    global page_counter
