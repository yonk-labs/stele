"""Reference parsing and formatting."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from stele.core.exceptions import ReferenceError


@dataclass(frozen=True)
class Reference:
    scheme: str
    namespace: str
    artifact_id: str
    params: dict[str, str]

    @property
    def canonical_without_params(self) -> str:
        namespace = "/".join(quote(part) for part in self.namespace.split("/") if part)
        return f"{self.scheme}://{namespace}/{quote(self.artifact_id)}"

    @property
    def canonical(self) -> str:
        if not self.params:
            return self.canonical_without_params
        return f"{self.canonical_without_params}?{urlencode(self.params)}"


def make_reference(namespace: str, artifact_id: str, *, scheme: str = "stele") -> Reference:
    _validate_namespace(namespace)
    _validate_artifact_id(artifact_id)
    return Reference(
        scheme=scheme,
        namespace=namespace.strip("/"),
        artifact_id=artifact_id,
        params={},
    )


def parse_reference(value: str) -> Reference:
    parsed = urlparse(value)
    if parsed.scheme != "stele":
        raise ReferenceError(f"Unsupported reference scheme: {parsed.scheme!r}")
    path_parts = [unquote(part) for part in parsed.path.split("/") if part]
    if not parsed.netloc:
        raise ReferenceError("Reference is missing namespace")
    parts = [unquote(parsed.netloc), *path_parts]
    if len(parts) < 2:
        raise ReferenceError("Reference is missing artifact id")
    namespace = "/".join(parts[:-1])
    artifact_id = parts[-1]
    _validate_namespace(namespace)
    _validate_artifact_id(artifact_id)
    params = {k: v[-1] for k, v in parse_qs(parsed.query).items() if v}
    return Reference(
        scheme=parsed.scheme,
        namespace=namespace,
        artifact_id=artifact_id,
        params=params,
    )


def _validate_namespace(namespace: str) -> None:
    if not namespace or namespace.strip("/") == "":
        raise ReferenceError("Namespace cannot be empty")
    if "?" in namespace or "#" in namespace:
        raise ReferenceError("Namespace contains invalid URL control characters")


def _validate_artifact_id(artifact_id: str) -> None:
    if not artifact_id:
        raise ReferenceError("Artifact id cannot be empty")
    if "/" in artifact_id or "?" in artifact_id or "#" in artifact_id:
        raise ReferenceError("Artifact id contains invalid characters")
