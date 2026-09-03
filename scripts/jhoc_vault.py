from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jhoc.guard.vault import CredentialVault


def get_default_vault() -> CredentialVault:
    vault_file = ROOT / "logs" / "p19-vault.bin"
    return CredentialVault(persistence_path=vault_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="JHOC Zero-Knowledge Credential Vault CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Set secret
    set_parser = subparsers.add_parser("set", help="Register a secret into the vault")
    set_parser.add_argument("secret_id", help="Canonical identifier for the secret (e.g. ALPHAFOLD_API_KEY)")
    set_parser.add_argument("raw_secret", help="Raw secret value")
    set_parser.add_argument("--scope", default="global", help="Scope for secret token digest")

    # List secrets
    subparsers.add_parser("list", help="List registered secret identifiers (zero-knowledge)")

    # Get token reference
    ref_parser = subparsers.add_parser("ref", help="Get opaque token reference for a secret")
    ref_parser.add_argument("secret_id", help="Canonical identifier")

    # Resolve token for egress
    resolve_parser = subparsers.add_parser("resolve", help="Dereference secret for authorized egress actor")
    resolve_parser.add_argument("token_ref", help="Opaque token reference (vault://secret/...)")
    resolve_parser.add_argument("--actor", required=True, help="Authorized egress actor prefix (e.g. adapter.science)")

    args = parser.parse_args()
    vault = get_default_vault()

    if args.command == "set":
        token_ref = vault.register_secret(args.secret_id, args.raw_secret, scope=args.scope)
        print(f"[PASS] Secret '{args.secret_id}' registered successfully.")
        print(f"Token Reference: {token_ref}")
    elif args.command == "list":
        secrets = vault.list_secrets()
        print(f"[INFO] Total Registered Secrets in Vault: {len(secrets)}")
        for s in secrets:
            token = vault.get_token_ref(s)
            print(f"  - {s} -> {token}")
    elif args.command == "ref":
        token = vault.get_token_ref(args.secret_id)
        if token:
            print(token)
        else:
            print(f"[FAIL] Secret '{args.secret_id}' not found in vault.", file=sys.stderr)
            sys.exit(1)
    elif args.command == "resolve":
        try:
            val = vault.resolve_for_egress(args.token_ref, args.actor)
            print(val)
        except Exception as e:
            print(f"[FAIL] Egress resolution denied: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
