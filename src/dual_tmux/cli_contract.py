"""Stable, JSON-safe description of the public ``dt`` argparse surface.

The manifest produced here is a compatibility guard, not the implementation of
the CLI.  It deliberately records syntax and defaults while leaving command
execution in :mod:`dual_tmux.cli`.
"""

from __future__ import annotations

import argparse
from typing import Any

SCHEMA_VERSION = 1


def _json_value(value: Any) -> Any:
    if value is argparse.SUPPRESS:
        return "__SUPPRESS__"
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return repr(value)


def _type_name(action: argparse.Action) -> str:
    converter = getattr(action, "type", None)
    if converter is None:
        return ""
    return getattr(converter, "__name__", repr(converter))


def _action_manifest(action: argparse.Action) -> dict[str, Any]:
    positional = not action.option_strings
    data: dict[str, Any] = {
        "dest": action.dest,
        "kind": "positional" if positional else "option",
        "action": type(action).__name__,
        "required": bool(action.required),
        "nargs": _json_value(action.nargs),
        "default": _json_value(action.default),
    }
    if action.option_strings:
        data["flags"] = list(action.option_strings)
    if action.choices is not None:
        data["choices"] = [_json_value(item) for item in action.choices]
    converter = _type_name(action)
    if converter:
        data["type"] = converter
    if getattr(action, "const", None) is not None:
        data["const"] = _json_value(action.const)
    return data


def _parser_manifest(parser: argparse.ArgumentParser) -> dict[str, Any]:
    arguments: list[dict[str, Any]] = []
    commands: dict[str, Any] = {}
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            commands = {
                name: _parser_manifest(child)
                for name, child in sorted(action.choices.items())
            }
            continue
        arguments.append(_action_manifest(action))
    return {"arguments": arguments, "commands": commands}


def cli_manifest(parser: argparse.ArgumentParser | None = None) -> dict[str, Any]:
    """Return the versioned public syntax contract for ``dt``."""
    if parser is None:
        from .cli import build_parser

        parser = build_parser()
    return {
        "schema_version": SCHEMA_VERSION,
        "program": parser.prog,
        **_parser_manifest(parser),
    }
