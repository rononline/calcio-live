#!/usr/bin/env python3
"""Validate the automation blueprints.

Checks that each blueprint under blueprints/ is valid YAML and has a sound
structure: a `blueprint` mapping with a name and `domain: automation`, a
trigger and an action, and — importantly — that every `!input <name>` used
anywhere resolves to a declared `blueprint.input.<name>` (catches selector /
input typos before users hit them).
"""
import glob
import sys

import yaml

# Collected while parsing a single file.
_used_inputs = []


class _BlueprintLoader(yaml.SafeLoader):
    pass


def _construct_input(loader, node):
    name = loader.construct_scalar(node)
    _used_inputs.append(name)
    return {"__input__": name}


_BlueprintLoader.add_constructor("!input", _construct_input)


def validate_file(path):
    errors = []
    _used_inputs.clear()
    try:
        with open(path) as handle:
            data = yaml.load(handle, Loader=_BlueprintLoader)
    except yaml.YAMLError as err:
        return [f"{path}: invalid YAML: {err}"]

    if not isinstance(data, dict):
        return [f"{path}: top level is not a mapping"]

    blueprint = data.get("blueprint")
    if not isinstance(blueprint, dict):
        return [f"{path}: missing 'blueprint' mapping"]
    if not blueprint.get("name"):
        errors.append(f"{path}: blueprint.name is required")
    if blueprint.get("domain") != "automation":
        errors.append(f"{path}: blueprint.domain must be 'automation'")

    inputs = blueprint.get("input") or {}
    if not isinstance(inputs, dict):
        errors.append(f"{path}: blueprint.input must be a mapping")
        inputs = {}

    if "trigger" not in data:
        errors.append(f"{path}: missing 'trigger'")
    if "action" not in data:
        errors.append(f"{path}: missing 'action'")

    for name in sorted(set(_used_inputs)):
        if name not in inputs:
            errors.append(f"{path}: !input {name} has no matching blueprint.input.{name}")

    if not errors:
        print(f"{path}: OK ({len(inputs)} inputs, {len(set(_used_inputs))} referenced)")
    return errors


def main():
    files = sorted(glob.glob("blueprints/**/*.yaml", recursive=True))
    if not files:
        print("No blueprints found")
        return 0

    errors = []
    for path in files:
        errors.extend(validate_file(path))

    if errors:
        print("\nBlueprint validation FAILED:")
        for err in errors:
            print(f" - {err}")
        return 1

    print(f"\nAll {len(files)} blueprints valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
