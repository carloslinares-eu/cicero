import cicero.cfg as cfg


def translate_text_gcloud(input_string_list, target_language):
    translated_string = cfg.gcloud_translate_client.translate(input_string_list, target_language=target_language)
    return translated_string
