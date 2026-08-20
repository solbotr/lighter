from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

EXPECTED_SDK_VERSION = "1.1.2"


@dataclass(frozen=True)
class CompatibilityReport:
    sdk_version: str | None
    checks: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def compatible(self) -> bool:
        return not self.failures


def check_sdk_compatibility() -> CompatibilityReport:
    checks: list[str] = []
    failures: list[str] = []
    try:
        import lighter
    except ImportError as exc:
        return CompatibilityReport(None, (), (f"sdk import failed: {exc}",))
    try:
        sdk_version = version("lighter-sdk")
    except PackageNotFoundError:
        sdk_version = None
    if sdk_version != EXPECTED_SDK_VERSION:
        failures.append(f"expected lighter-sdk=={EXPECTED_SDK_VERSION}, found {sdk_version or 'missing'}")
    else:
        checks.append("sdk version")
    required_classes = ("SignerClient", "Configuration", "ApiClient", "OrderApi", "AccountApi")
    for name in required_classes:
        if not hasattr(lighter, name):
            failures.append(f"missing SDK class: {name}")
        else:
            checks.append(f"class {name}")
    signer = getattr(lighter, "SignerClient", None)
    required_methods = {
        "create_auth_token_with_expiry": ("deadline", "api_key_index"),
        "create_market_order": ("market_index", "client_order_index", "base_amount", "avg_execution_price", "is_ask"),
        "cancel_order": ("market_index", "order_index"),
        "cancel_all_orders": ("time_in_force", "timestamp_ms"),
    }
    if signer is not None:
        for method, parameters in required_methods.items():
            member = getattr(signer, method, None)
            if member is None:
                failures.append(f"missing SDK method: SignerClient.{method}")
                continue
            names = set(inspect.signature(member).parameters)
            missing = sorted(set(parameters) - names)
            if missing:
                failures.append(f"SignerClient.{method} missing parameters: {','.join(missing)}")
            else:
                checks.append(f"method {method}")
    return CompatibilityReport(sdk_version, tuple(checks), tuple(failures))


def require_sdk_compatibility() -> CompatibilityReport:
    report = check_sdk_compatibility()
    if not report.compatible:
        raise RuntimeError("SDK compatibility preflight failed: " + "; ".join(report.failures))
    return report
