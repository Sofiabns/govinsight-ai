import hashlib
import json
from collections.abc import Mapping

ParameterValue = str | int


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scope_parameters(params: Mapping[str, ParameterValue]) -> dict[str, ParameterValue]:
    return {key: value for key, value in params.items() if key != "pagina"}


def request_fingerprint(
    source: str, dataset: str, endpoint: str, params: Mapping[str, ParameterValue]
) -> str:
    return sha256_text(
        canonical_json(
            {"source": source, "dataset": dataset, "endpoint": endpoint, "params": dict(params)}
        )
    )


def scope_fingerprint(
    source: str, dataset: str, endpoint: str, params: Mapping[str, ParameterValue]
) -> str:
    return sha256_text(
        canonical_json(
            {
                "source": source,
                "dataset": dataset,
                "endpoint": endpoint,
                "params": scope_parameters(params),
            }
        )
    )
