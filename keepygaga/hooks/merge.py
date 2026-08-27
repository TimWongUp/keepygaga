"""Ownership-aware merging for Keepygaga hook fragments."""

from __future__ import annotations

import shlex
from copy import deepcopy
from typing import Any

FRAGMENT_SCHEMA = "keepygaga-hook-fragment-v1"


class HookFragmentError(ValueError):
    pass


def _validate_fragment(fragment: dict[str, Any]) -> None:
    if fragment.get("schema") != FRAGMENT_SCHEMA:
        raise HookFragmentError("unsupported hook fragment schema")
    if not isinstance(fragment.get("host"), str):
        raise HookFragmentError("fragment host must be a string")
    target = fragment.get("merge_target")
    if not isinstance(target, str) or not target:
        raise HookFragmentError("merge_target must be a non-empty string")
    required = fragment.get("required_top_level", {})
    if not isinstance(required, dict) or target in required:
        raise HookFragmentError("required_top_level is invalid")
    markers = fragment.get("owned_command_markers")
    if not isinstance(markers, list) or not all(
        isinstance(marker, str) and marker for marker in markers
    ):
        raise HookFragmentError("owned command markers are invalid")
    token_sets = fragment.get("owned_command_token_sets", [])
    if not isinstance(token_sets, list) or not all(
        isinstance(tokens, list)
        and tokens
        and all(isinstance(token, str) and token for token in tokens)
        for tokens in token_sets
    ):
        raise HookFragmentError("owned command token sets are invalid")
    suffix_sets = fragment.get("owned_command_suffix_token_sets", [])
    if not isinstance(suffix_sets, list) or not all(
        isinstance(tokens, list)
        and tokens
        and all(isinstance(token, str) and token for token in tokens)
        for tokens in suffix_sets
    ):
        raise HookFragmentError("owned command suffix token sets are invalid")
    signatures = fragment.get("owned_command_signatures", [])
    if not isinstance(signatures, list) or not all(
        isinstance(signature, list)
        and len(signature) == 4
        and all(isinstance(token, str) and token for token in signature)
        for signature in signatures
    ):
        raise HookFragmentError("owned command signatures are invalid")
    if not markers and not token_sets and not suffix_sets and not signatures:
        raise HookFragmentError("fragment must declare owned commands")
    payload = fragment.get("payload")
    if not isinstance(payload, dict) or not all(
        isinstance(event, str) and isinstance(entries, list)
        for event, entries in payload.items()
    ):
        raise HookFragmentError("fragment payload must map events to lists")


def _has_owned_command(
    value: dict[str, Any],
    markers: tuple[str, ...],
    token_sets: tuple[tuple[str, ...], ...],
    suffix_sets: tuple[tuple[str, ...], ...],
    signatures: tuple[tuple[str, str, str, str], ...],
) -> bool:
    command = value.get("command")
    if not isinstance(command, str):
        return False
    normalized = command.replace("\\", "/")
    if any(marker in normalized for marker in markers):
        return True
    parsed_candidates: list[list[str]] = []
    for posix in (True, False):
        try:
            parsed = shlex.split(normalized, posix=posix)
        except ValueError:
            continue
        parsed_candidates.append(
            [
                token[1:-1] if token.startswith('"') and token.endswith('"') else token
                for token in parsed
            ]
        )
    exact_match = any(
        any(
            candidate[index : index + len(tokens)] == list(tokens)
            for index in range(len(candidate) - len(tokens) + 1)
        )
        for tokens in token_sets
        for candidate in parsed_candidates
    )
    suffix_match = any(
        any(
            candidate[index].endswith(tokens[0])
            and candidate[index + 1 : index + len(tokens)] == list(tokens[1:])
            for index in range(len(candidate) - len(tokens) + 1)
        )
        for tokens in suffix_sets
        for candidate in parsed_candidates
    )
    signature_match = any(
        candidate
        and candidate[0].rsplit("/", 1)[-1].lower() == executable.lower()
        and candidate[1:3] == ["--config", candidate[2]]
        and candidate[3:9] == ["hook", "run", action, owner, "--host", host]
        for executable, action, owner, host in signatures
        for candidate in parsed_candidates
        if len(candidate) >= 9
    )
    return exact_match or suffix_match or signature_match


def _strip_owned(
    value: Any,
    markers: tuple[str, ...],
    token_sets: tuple[tuple[str, ...], ...],
    suffix_sets: tuple[tuple[str, ...], ...],
    signatures: tuple[tuple[str, str, str, str], ...],
) -> Any | None:
    if isinstance(value, dict):
        if _has_owned_command(value, markers, token_sets, suffix_sets, signatures):
            return None
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            result = _strip_owned(nested, markers, token_sets, suffix_sets, signatures)
            if result is not None:
                cleaned[key] = result
        if "hooks" in value and not cleaned.get("hooks"):
            return None
        return cleaned
    if isinstance(value, list):
        return [
            result
            for nested in value
            if (
                result := _strip_owned(
                    nested, markers, token_sets, suffix_sets, signatures
                )
            )
            is not None
        ]
    return value


def merge_hook_fragment(
    existing: dict[str, Any], fragment: dict[str, Any]
) -> dict[str, Any]:
    _validate_fragment(fragment)
    merged = deepcopy(existing)
    for key, value in fragment.get("required_top_level", {}).items():
        if key in merged and merged[key] != value:
            raise HookFragmentError(
                f"live top-level field {key!r} does not match required value"
            )
        merged.setdefault(key, deepcopy(value))

    target = fragment["merge_target"]
    current = merged.get(target, {})
    if not isinstance(current, dict):
        raise HookFragmentError(f"live target {target!r} must be an object")
    markers = tuple(
        marker.replace("\\", "/") for marker in fragment["owned_command_markers"]
    )
    token_sets = tuple(
        tuple(token.replace("\\", "/") for token in tokens)
        for tokens in fragment.get("owned_command_token_sets", [])
    )
    suffix_sets = tuple(
        tuple(token.replace("\\", "/") for token in tokens)
        for tokens in fragment.get("owned_command_suffix_token_sets", [])
    )
    signatures = tuple(
        tuple(token.replace("\\", "/") for token in signature)
        for signature in fragment.get("owned_command_signatures", [])
    )
    cleaned = _strip_owned(current, markers, token_sets, suffix_sets, signatures)
    if not isinstance(cleaned, dict):
        cleaned = {}
    cleaned = {
        event: entries for event, entries in cleaned.items() if entries not in ([], {})
    }
    for event, entries in fragment["payload"].items():
        desired = deepcopy(entries)
        existing_entries = cleaned.get(event)
        if existing_entries is None:
            cleaned[event] = desired
        elif isinstance(existing_entries, list):
            existing_entries.extend(desired)
        else:
            raise HookFragmentError(f"live event {event!r} must be a list")
    merged[target] = cleaned
    return merged
