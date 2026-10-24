#!/usr/bin/env python3
"""Profile-scoped keys and paths must win over the gateway process environment."""
import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent.secret_scope import (
    UnscopedSecretError,
    reset_secret_scope,
    set_multiplex_active,
    set_secret_scope,
)
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


_HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("jev_home_scope_probe", _HERE.parent / "__init__.py")
assert spec and spec.loader
jev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jev)

# Isolate the environment fallback from runtime credentials and local configuration.
jev._key_from_runtime_provider = lambda provider: ""
jev._key_from_dotenv = lambda: ""
jev._setting = lambda key, default=None: default

with TemporaryDirectory() as tmp:
    process_home = Path(tmp) / "A"
    profile_home = Path(tmp) / "B"
    with patch.dict(os.environ, {
        "HERMES_HOME": str(process_home),
        "TYPESAFE_API_KEY": "process-value",
        "OPENROUTER_API_KEY": "process-value",
        "CUSTOM_JEV_KEY": "process-value",
    }):
        home_token = set_hermes_home_override(profile_home)
        scope_token = set_secret_scope({
            "TYPESAFE_API_KEY": "home-value",
            "OPENROUTER_API_KEY": "home-value",
            "CUSTOM_JEV_KEY": "home-value",
        }, profile_home=str(profile_home))
        try:
            assert jev._api_key() == "home-value"
            print("1. TypeSafe resolver uses the scoped key ok")
            assert jev.JevClient().api_key == "home-value"
            assert jev.JevClient(api_key="explicit-value").api_key == "explicit-value"
            print("2. client uses the scoped key; explicit key still wins ok")
            assert jev._api_key("https://openrouter.ai/api/alpha") == "home-value"
            jev._setting = lambda key, default=None: "CUSTOM_JEV_KEY" if key == "key_env" else default
            assert jev._api_key("https://jev.example/decisions") == "home-value"
            print("3. aggregator and custom routes use scoped keys ok")
            assert jev._log_path() == profile_home / jev._LOG_NAME
            print("4. default log path uses the active home override ok")
        finally:
            reset_secret_scope(scope_token)
            reset_hermes_home_override(home_token)

        jev._setting = lambda key, default=None: default
        scope_token = set_secret_scope(None)
        set_multiplex_active(True)
        try:
            for resolve in (jev._api_key, jev.JevClient):
                try:
                    resolve()
                except UnscopedSecretError:
                    pass
                else:
                    raise AssertionError("unscoped multiplex read did not fail closed")
        finally:
            set_multiplex_active(False)
            reset_secret_scope(scope_token)
        print("5. unscoped multiplex key reads fail closed ok")
        set_multiplex_active(True)
        try:
            jev._log_path()  # a path setting, not a secret: the audit log must still resolve
        finally:
            set_multiplex_active(False)
        print("6. audit log path still resolves outside a scope ok")

print("\nall 6 home scope checks pass")
