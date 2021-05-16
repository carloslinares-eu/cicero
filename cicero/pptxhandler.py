import pptx
from pptx.enum.shapes import MSO_SHAPE_TYPE
import tkinter.messagebox
import cicero.config

global id_counter
global current_slide


def open_powerpoint_file(path_to_input):
    try:
        active_presentation = pptx.Presentation(path_to_input)
        return active_presentation
    except pptx.exc.PackageNotFoundError:
        refresh_error_message = "Failed to open the Powerpoint file"
        tkinter.messagebox.showerror(title="Critical error", message=refresh_error_message)
        raise IOError


def extract_text_from_powerpoint(active_presentation):
    global id_counter, current_slide
    id_counter = 0

    for current_slide in active_presentation.slides:
        extract_text_from_notes(current_slide)
        extract_text_from_simple_shapes(current_slide)
        extract_text_from_complex_shapes(current_slide)
        extract_text_from_tables(current_slide)
        id_counter = 0

    cicero.config.text_repository_file.close()


def extract_text_from_notes(slide):
    for paragraph in slide.notes_slide.notes_text_frame.paragraphs:
        write_line_to_text_file(paragraph.text)


def extract_text_from_simple_shapes(slide):
    for shape in slide.shapes:
        if shape.has_text_frame:
            extract_paragraphs_from_shapes(shape)


def extract_text_from_complex_shapes(slide):
    for grouped_shape in slide.shapes:
        if grouped_shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            extract_text_from_simple_shapes(grouped_shape)


def extract_text_from_tables(slide):
    for shape in slide.shapes:
        if shape.has_table:
            for cell in shape.table.iter_cells():
                extract_paragraphs_from_shapes(cell)


def extract_paragraphs_from_shapes(shape):
    for paragraph in shape.text_frame.paragraphs:
        write_line_to_text_file(paragraph.text)


def write_line_to_text_file(text):
    global id_counter
    global current_slide
    cicero.config.text_repository_file.write(str(current_slide) + "\t" + str(id_counter) + "\t" + text + "\n")
    id_counter += 1
