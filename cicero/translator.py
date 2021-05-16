import cicero.config as cfg
import csv


def read_and_group_input_string(text_file):
    input_string_list = []
    with open(text_file) as csv_file:
        csv_reader = csv.reader(csv_file, delimiter="\t")
        for row in csv_reader:
            elements_in_list = len(input_string_list)
            characters_in_list = count_characters(input_string_list)
            if elements_in_list < 128 & characters_in_list < 2000:
                input_string_list.append(row[2])

    print(input_string_list)


def count_characters(string_list):
    total_characters = 0
    for element in string_list:
        total_characters += len(element)
    return total_characters


def translate_text_gcloud(input_string, target_language):
    output_string = cfg.gcloud_translate_client.translate(input_string, target_language=target_language)
    return output_string