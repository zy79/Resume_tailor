from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from resume_tailor.contracts import canonical_json_bytes

ModelT = TypeVar("ModelT", bound=BaseModel)
_PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DIAGNOSTIC_STEP_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class ProtocolError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_input", blocked: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.blocked = blocked


def resolve_input_path(path: str | Path) -> Path:
    try:
        value = Path(path).expanduser()
        if "\0" in str(value):
            raise ValueError
        return value.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        raise ProtocolError("Input path is missing or inaccessible.") from error


def ensure_private_directory(path: str | Path) -> Path:
    private_root = Path.cwd() / "private_data"
    target = Path(path).expanduser()
    if "\0" in str(target) or ".." in target.parts:
        raise ProtocolError(
            "Managed output path is not allowed.", code="unsafe_path"
        )
    if not target.is_absolute():
        target = Path.cwd() / target
    try:
        relative = target.relative_to(private_root)
    except ValueError as error:
        raise ProtocolError(
            "Managed output must stay under private_data/.", code="unsafe_path"
        ) from error

    current = private_root
    for part in ("", *relative.parts):
        if part:
            current = current / part
        if current.is_symlink():
            raise ProtocolError("Managed output path contains a symbolic link.", code="unsafe_path")
        try:
            current.mkdir(mode=0o700, exist_ok=True)
            if not current.is_dir():
                raise OSError("managed path is not a directory")
            current.chmod(0o700)
        except OSError as error:
            raise ProtocolError("Could not secure the managed output directory.") from error
    return target


def ensure_profile_directory(profile_name: str) -> Path:
    if not _PROFILE_NAME_PATTERN.fullmatch(profile_name):
        raise ProtocolError("Profile name must be a safe local identifier.", code="unsafe_path")
    return ensure_private_directory(Path("private_data") / "profiles" / profile_name)


def profile_snapshot_path(profile_name: str, version: int, source_sha256: str) -> Path:
    if version < 1 or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ProtocolError("Profile snapshot metadata is invalid.", code="invalid_input")
    profile_dir = ensure_profile_directory(profile_name)
    return profile_dir / f"profile-v{version:04d}-{source_sha256}.json"


def prepare_diagnostic_output(path: str | Path) -> Path:
    target = Path(path).expanduser()
    if "\0" in str(target) or ".." in target.parts:
        raise ProtocolError("Diagnostics output path is not allowed.", code="unsafe_path")
    if not target.is_absolute():
        target = Path.cwd() / target

    diagnostics_root = Path.cwd() / "private_data" / "tmp"
    try:
        relative = target.relative_to(diagnostics_root)
    except ValueError as error:
        raise ProtocolError(
            "Diagnostics must be saved under private_data/tmp/.", code="unsafe_path"
        ) from error

    if len(relative.parts) != 2:
        raise ProtocolError(
            "Diagnostics path must identify a run and a step file.", code="unsafe_path"
        )
    run_id, filename = relative.parts
    step = Path(filename).stem
    if (
        not _PROFILE_NAME_PATTERN.fullmatch(run_id)
        or Path(filename).suffix != ".json"
        or not _DIAGNOSTIC_STEP_PATTERN.fullmatch(step)
    ):
        raise ProtocolError("Diagnostics path is not a safe run-step path.", code="unsafe_path")

    ensure_private_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise ProtocolError("Output target already exists.", code="output_conflict")
    return target


def resolve_managed_path(base_dir: str | Path, relative_path: str | Path) -> Path:
    base = Path(base_dir).resolve(strict=True)
    relative = Path(relative_path)
    if "\0" in str(relative) or relative.is_absolute() or ".." in relative.parts:
        raise ProtocolError("Managed path is not allowed.", code="unsafe_path")
    target = (base / relative).resolve(strict=False)
    if not target.is_relative_to(base):
        raise ProtocolError("Managed path escapes its storage directory.", code="unsafe_path")
    return target


def read_model(path: str | Path, model: type[ModelT]) -> ModelT:
    input_path = resolve_input_path(path)
    try:
        return model.model_validate_json(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as error:
        raise ProtocolError("Input JSON is unreadable or does not match its schema.") from error


def write_exclusive(path: str | Path, content: bytes, *, mode: int = 0o600) -> Path:
    output_path = Path(path).expanduser()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(output_path, flags, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProtocolError("Output target already exists.", code="output_conflict") from error
    except OSError as error:
        raise ProtocolError("Could not create the output file.") from error
    return output_path


def write_json_exclusive(path: str | Path, value: BaseModel | object) -> Path:
    return write_exclusive(path, canonical_json_bytes(value) + b"\n")


def _write_atomic(
    path: str | Path,
    content: bytes,
    *,
    mode: int,
    replace: bool,
) -> Path:
    output_path = Path(path).expanduser()
    temporary_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        write_exclusive(temporary_path, content, mode=mode)
    except ProtocolError:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise

    try:
        if replace:
            os.replace(temporary_path, output_path)
        else:
            os.link(temporary_path, output_path)
    except FileExistsError as error:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise ProtocolError("Output target already exists.", code="output_conflict") from error
    except OSError as error:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise ProtocolError("Could not atomically finalize the output file.") from error
    if not replace:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
    return output_path


def write_atomic_replace(path: str | Path, content: bytes, *, mode: int = 0o600) -> Path:
    return _write_atomic(path, content, mode=mode, replace=True)


def write_atomic_exclusive(path: str | Path, content: bytes, *, mode: int = 0o600) -> Path:
    return _write_atomic(path, content, mode=mode, replace=False)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ProtocolError("Could not read an artifact file.") from error
    return digest.hexdigest()


def json_bytes(value: BaseModel | object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def read_json_value(path: str | Path) -> object:
    input_path = resolve_input_path(path)
    try:
        return json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProtocolError("Input JSON is unreadable or invalid.") from error