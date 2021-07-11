import cicero.cfg as cfg


def translate_text_gcloud(input_list_of_springs, target_language):
    output_list_of_springs = []
    server_response = cfg.gcloud_translate_client.translate(input_list_of_springs,
                                                            target_language=target_language)
    for element in server_response:
        output_list_of_springs.append(element["translatedText"])
    return output_list_of_springs
