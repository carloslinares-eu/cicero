import cicero.cfg as cfg
import csv


def create_repository_file(path_to_repository):
    with open(path_to_repository, mode="w", newline='') as repository_file:
        repository_writer = csv.DictWriter(repository_file, fieldnames=cfg.repository_field_names)
        repository_writer.writeheader()


def write_line_to_repository(path_to_repository, line):
    with open(path_to_repository, mode="a", newline='') as repository_file:
        repository_writer = csv.DictWriter(repository_file, fieldnames=cfg.repository_field_names, delimiter=',',
                                           quotechar='"', quoting=csv.QUOTE_MINIMAL)
        try:
            repository_writer.writerow(line)
        except UnicodeEncodeError:
            encoded_line = line
            encoded_line["text"] = line["text"].encode("utf8")
            encoded_line["encoded"] = str(True)
            repository_writer.writerow(encoded_line)


def read_and_group_from_repository(path_to_repository):
    with open(path_to_repository, 'r', newline='') as repository_file:
        repository_reader = csv.DictReader(repository_file, delimiter=',', quotechar='"')
        list_id = 0
        input_list = [{"list_id": list_id, "input_text": []}]
        for row in repository_reader:
            characters_in_list = count_characters(input_list[list_id]["input_text"]) + len(row["text"])
            elements_in_list = len(input_list[list_id]["input_text"])
            if elements_in_list >= 50 and characters_in_list >= 1000:
                list_id += 1
                input_list.append({"list_id": list_id, "input_text": []})
            input_list[list_id]["input_text"].append(row["text"])
    return input_list


def count_characters(string_list):
    total_characters = 0
    for element in string_list:
        total_characters += len(element)
    return total_characters
