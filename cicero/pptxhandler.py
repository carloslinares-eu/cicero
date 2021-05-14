import pptx


def extract_text_from_notes(source_file_path, text_repository):
    try:
        active_presentation = pptx.Presentation(source_file_path)
        text_repository.update({"text_from_speaker_notes": []})
    except pptx.exc.PackageNotFoundError:
        raise IOError

    for slide in active_presentation.slides:
        text_repository["text_from_speaker_notes"].append(slide.notes_slide.notes_text_frame.text)


def extract_text_from_shapes(source_file_path, text_repository):
    try:
        active_presentation = pptx.Presentation(source_file_path)
        text_repository.update({"text_from_shapes": []})
    except pptx.exc.PackageNotFoundError:
        raise IOError

    for slide in active_presentation.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                text_repository["text_from_shapes"].append(paragraph.text)


def extract_text_from_tables(source_file_path, text_repository):
    try:
        active_presentation = pptx.Presentation(source_file_path)
        text_repository.update({"text_from_tables": []})
    except pptx.exc.PackageNotFoundError:
        raise IOError

    for slide in active_presentation.slides:
        for shape in slide.shapes:
            if shape.has_table:
                for cell in shape.table.iter_cells():
                    for paragraph in cell.text_frame.paragraphs:
                        text_repository["text_from_tables"].append(paragraph.text)


def update_text_of_shapes(source_file_path, destination_file_path, source_text):
    try:
        active_presentation = pptx.Presentation(source_file_path)
    except pptx.exc.PackageNotFoundError:
        raise IOError

    for slide in active_presentation.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                paragraph.text = source_text

    active_presentation.save(destination_file_path)
