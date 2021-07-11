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


def load_and_group_from_repository(path_to_repository):
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


def ungroup_output(grouped_strings, key):
    output_single_list = []
    for group in grouped_strings:
        for string in group[key]:
            output_single_list.append(string)
    return output_single_list


def update_repository_with_translation(path_to_repository, output_list):
    with open(path_to_repository, mode="r", newline='') as repository_file:
        repository_reader = csv.DictReader(repository_file, delimiter=',', quotechar='"')
        repository_writer = csv.DictWriter(repository_file, fieldnames=cfg.repository_field_names, delimiter=',',
                                           quotechar='"', quoting=csv.QUOTE_MINIMAL)
        updated_row = []
        id_count = 0
        for row in repository_reader:
            updated_row.append({"slide_id": row["slide_id"],
                                "element_id": row["element_id"],
                                "encoded": row["encoded"],
                                "text": row["text"],
                                "font_name": row["font_name"],
                                "font_size": row["font_size"],
                                "font_color": row["font_color"],
                                "translation": output_list[id_count]})
            id_count += 1

    with open(path_to_repository, mode="w", newline='') as repository_file:
        repository_writer = csv.DictWriter(repository_file, fieldnames=cfg.repository_field_names, delimiter=',',
                                           quotechar='"', quoting=csv.QUOTE_MINIMAL)
        repository_writer.writeheader()
        for row in updated_row:
            try:
                repository_writer.writerow(row)
            except UnicodeEncodeError:
                row.update({"translation": row["translation"].encode("utf-8")})
                row.update({"encoded": True})
                repository_writer.writerow(row)


def load_repository_to_list_of_dictionaries(path_to_repository):
    with open(path_to_repository, mode="r", newline='') as repository_file:
        repository_reader = csv.DictReader(repository_file, delimiter=',', quotechar='"')
        repository_content = []
        for row in repository_reader:
            repository_content.append({"slide_id": row["slide_id"],
                                       "element_id": row["element_id"],
                                       "encoded": row["encoded"],
                                       "text": row["text"],
                                       "font_name": row["font_name"],
                                       "font_size": row["font_size"],
                                       "font_color": row["font_color"],
                                       "translation": row["translation"]})
    return repository_content
