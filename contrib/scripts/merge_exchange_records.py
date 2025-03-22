import sys

import yaml


def load_yaml(filename):
    with open(filename, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or []


def save_yaml(filename, data):
    with open(filename, "w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True, default_flow_style=False)


def extract_existing_combinations(data):
    return {
        (
            entry["fields"]["currency_from"],
            entry["fields"]["currency_to"],
            entry["fields"]["year"],
        )
        for entry in data
        if entry["model"] == "games.exchangerate"
    }


def filter_new_entries(existing_combinations, additional_files):
    new_entries = []

    for filename in additional_files:
        data = load_yaml(filename)
        for entry in data:
            if entry["model"] == "games.exchangerate":
                key = (
                    entry["fields"]["currency_from"],
                    entry["fields"]["currency_to"],
                    entry["fields"]["year"],
                )
                if key not in existing_combinations:
                    new_entries.append(entry)

    return new_entries


def main():
    if len(sys.argv) < 3:
        print("Usage: script.py example.yaml additions1.yaml [additions2.yaml ...]")
        sys.exit(1)

    example_file = sys.argv[1]
    additional_files = sys.argv[2:]
    output_file = "filtered_output.yaml"

    existing_data = load_yaml(example_file)
    existing_combinations = extract_existing_combinations(existing_data)

    new_entries = filter_new_entries(existing_combinations, additional_files)

    save_yaml(output_file, new_entries)
    print(f"Filtered data saved to {output_file}")


if __name__ == "__main__":
    main()
