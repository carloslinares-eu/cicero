import pptx


def extract_notes(pptx_file_path):
    active_pptx = pptx.Presentation(pptx_file_path)
    data = {'slides': []}

    for slide_number, slide in enumerate(active_pptx.slides):
        text_note = slide.notes_slide.notes_text_frame.text
        data['slides'].append({
            'slide_number': slide_number,
            'speaker_notes': text_note
        })
    return data

