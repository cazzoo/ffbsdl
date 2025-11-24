"""SingleStore integration layer for ffbsdl.

This module provides a thin wrapper around the official `singlestoredb` Python
client, plus a small schema and helper API focused on the ffbsdl use case:

- Users / identities
- Versioned test suites (JSON documents)
- Versioned test results and analyses (JSON documents)

It is intentionally small and does not try to be a full ORM.

The actual SingleStore credentials and connection information are provided via
environment variables so that they are never committed to this repo:

- FFBSD_SINGLESTORE_URI  (recommended, e.g. "user:pass@host:3306/db")
- or granular parameters:
  - FFBSD_SINGLESTORE_HOST
  - FFBSD_SINGLESTORE_PORT
  - FFBSD_SINGLESTORE_USER
  - FFBSD_SINGLESTORE_PASSWORD
  - FFBSD_SINGLESTORE_DATABASE

Ownership and auth model
------------------------

To keep things simple and avoid pulling in a full auth stack, this module uses
per-user API keys. Each user row has a stable `id` plus a `display_name` and a
secret `api_key` that must be presented by clients when talking to the DB
(e.g. via an environment variable when invoking scripts, or via the interactive
runner in future extensions).

Security notes:
- API keys are generated as random 32-byte hex strings.
- Lookups always go through `authenticate_user(api_key)`; callers then pass the
  resolved `user_id` into other functions.
- All write operations require an explicit `owner_user_id` and enforce that the
  authenticated user matches.
- Read helpers can optionally enforce ownership or allow shared read-only
  access for suites/results via simple boolean flags.

Versioning model
----------------

We use append-only versioned tables:

- `test_suites` holds the logical suite identity (stable id, owner, share flag).
- `test_suite_versions` holds immutable JSON payloads for each revision.
- `test_results` holds the logical result identity (stable id, suite link,
  owner, share flag).
- `test_result_versions` holds immutable JSON payloads for each revision.

Each *versions* table has:
- an auto-increment `version` starting at 1
- `created_at` timestamp (UTC NOW())

The helpers in this module always insert new versions instead of updating rows
in-place. Callers can choose whether they care about the latest version or a
specific historical one.

This module is written to be imported but not required: the rest of the repo
should treat it as optional (best-effort remote sync). Scripts should catch
`ImportError` / `RuntimeError` and continue to work locally if the SingleStore
client or credentials are missing.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # Import is optional at runtime
    import singlestoredb as s2  # type: ignore
except Exception:  # pragma: no cover - allow running without the client installed
    s2 = None  # type: ignore


class SingleStoreNotConfigured(RuntimeError):
    """Raised when SingleStore integration is not available or misconfigured."""


@dataclass
class User:
    id: int
    display_name: str
    api_key: str


@dataclass
class TestSuite:
    id: int
    owner_user_id: int
    name: str
    is_shared: bool


@dataclass
class TestResult:
    id: int
    owner_user_id: int
    suite_id: int
    label: str
    is_shared: bool


def _require_client() -> None:
    if s2 is None:
        raise SingleStoreNotConfigured(
            "singlestoredb client is not installed. Install it to use remote DB "
            "integration."
        )


def _connect():
    """Return a new SingleStore connection using env-based configuration.

    Prefer a single URI via FFBSD_SINGLESTORE_URI, but also support granular
    host/user/password variables.
    """

    _require_client()

    uri = os.getenv("FFBSD_SINGLESTORE_URI")
    if uri:
        return s2.connect(uri)

    host = os.getenv("FFBSD_SINGLESTORE_HOST")
    if not host:
        raise SingleStoreNotConfigured(
            "FFBSD_SINGLESTORE_HOST (or FFBSD_SINGLESTORE_URI) is not set"
        )
    user = os.getenv("FFBSD_SINGLESTORE_USER")
    password = os.getenv("FFBSD_SINGLESTORE_PASSWORD")
    database = os.getenv("FFBSD_SINGLESTORE_DATABASE")
    port = int(os.getenv("FFBSD_SINGLESTORE_PORT", "3306"))

    if not user or not password or not database:
        raise SingleStoreNotConfigured(
            "FFBSD_SINGLESTORE_USER, _PASSWORD and _DATABASE must be set when "
            "using granular configuration."
        )

    return s2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        results_type="dict",
    )


def ensure_schema() -> None:
    """Create the minimal schema if it does not already exist.

    This is idempotent and safe to call at startup.
    """

    conn = _connect()
    with conn:
        conn.autocommit(True)
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    display_name VARCHAR(255) NOT NULL,
                    api_key CHAR(64) NOT NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS test_suites (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    owner_user_id INT NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    is_shared TINYINT(1) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS test_suite_versions (
                    suite_id INT NOT NULL,
                    version INT NOT NULL AUTO_INCREMENT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    suite_json JSON NOT NULL,
                    PRIMARY KEY (suite_id, version),
                    FOREIGN KEY (suite_id) REFERENCES test_suites(id)
                ) AUTO_INCREMENT=1;
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS test_results (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    owner_user_id INT NOT NULL,
                    suite_id INT NOT NULL,
                    label VARCHAR(255) NOT NULL,
                    is_shared TINYINT(1) NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_user_id) REFERENCES users(id),
                    FOREIGN KEY (suite_id) REFERENCES test_suites(id)
                );
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS test_result_versions (
                    result_id INT NOT NULL,
                    version INT NOT NULL AUTO_INCREMENT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    manifest_json JSON NOT NULL,
                    analysis_json JSON NULL,
                    PRIMARY KEY (result_id, version),
                    FOREIGN KEY (result_id) REFERENCES test_results(id)
                ) AUTO_INCREMENT=1;
                """
            )


def create_user(display_name: str) -> User:
    """Create a new user with a freshly generated API key.

    Returns the created User (including api_key).
    """

    api_key = secrets.token_hex(32)
    conn = _connect()
    with conn:
        conn.autocommit(True)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (display_name, api_key) VALUES (%s, %s)",
                (display_name, api_key),
            )
            cur.execute("SELECT id, display_name, api_key FROM users WHERE api_key = %s", (api_key,))
            row = cur.fetchone()
            assert row is not None
            return User(id=row["id"], display_name=row["display_name"], api_key=row["api_key"])  # type: ignore[index]


def authenticate_user(api_key: str) -> Optional[User]:
    """Return the User for this API key, or None if invalid."""

    if not api_key:
        return None
    conn = _connect()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name, api_key FROM users WHERE api_key = %s",
                (api_key,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return User(id=row["id"], display_name=row["display_name"], api_key=row["api_key"])  # type: ignore[index]


def upsert_test_suite(
    owner_user_id: int,
    name: str,
    suite_json: Dict[str, Any],
    is_shared: bool = False,
) -> Tuple[TestSuite, int]:
    """Create or update a logical test suite and append a new version.

    Returns (TestSuite, version_number).
    """

    suite_json_str = json.dumps(suite_json, separators=(",", ":"))
    conn = _connect()
    with conn:
        conn.autocommit(True)
        with conn.cursor() as cur:
            # Look for an existing suite with the same owner+name.
            cur.execute(
                "SELECT id, owner_user_id, name, is_shared FROM test_suites "
                "WHERE owner_user_id = %s AND name = %s",
                (owner_user_id, name),
            )
            row = cur.fetchone()
            if row:
                suite_id = row["id"]
                cur.execute(
                    "UPDATE test_suites SET is_shared = %s WHERE id = %s",
                    (1 if is_shared else 0, suite_id),
                )
            else:
                cur.execute(
                    "INSERT INTO test_suites (owner_user_id, name, is_shared) "
                    "VALUES (%s, %s, %s)",
                    (owner_user_id, name, 1 if is_shared else 0),
                )
                suite_id = cur.lastrowid

            # Append a new suite version.
            cur.execute(
                "INSERT INTO test_suite_versions (suite_id, suite_json) VALUES (%s, CAST(%s AS JSON))",
                (suite_id, suite_json_str),
            )
            version = cur.lastrowid

            return TestSuite(
                id=suite_id,
                owner_user_id=owner_user_id,
                name=name,
                is_shared=is_shared,
            ), int(version)


def create_or_update_test_result(
    owner_user_id: int,
    suite_id: int,
    label: str,
    manifest_json: Dict[str, Any],
    analysis_json: Optional[Dict[str, Any]] = None,
    is_shared: bool = False,
) -> Tuple[TestResult, int]:
    """Create or update a logical test result and append a new version.

    The manifest_json and analysis_json are stored as-is; callers are
    responsible for ensuring they are reasonably sized.

    Returns (TestResult, version_number).
    """

    manifest_str = json.dumps(manifest_json, separators=(",", ":"))
    analysis_str = (
        json.dumps(analysis_json, separators=(",", ":")) if analysis_json is not None else None
    )

    conn = _connect()
    with conn:
        conn.autocommit(True)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_user_id, suite_id, label, is_shared FROM test_results "
                "WHERE owner_user_id = %s AND suite_id = %s AND label = %s",
                (owner_user_id, suite_id, label),
            )
            row = cur.fetchone()
            if row:
                result_id = row["id"]
                cur.execute(
                    "UPDATE test_results SET is_shared = %s WHERE id = %s",
                    (1 if is_shared else 0, result_id),
                )
            else:
                cur.execute(
                    "INSERT INTO test_results (owner_user_id, suite_id, label, is_shared) "
                    "VALUES (%s, %s, %s, %s)",
                    (owner_user_id, suite_id, label, 1 if is_shared else 0),
                )
                result_id = cur.lastrowid

            cur.execute(
                "INSERT INTO test_result_versions (result_id, manifest_json, analysis_json) "
                "VALUES (%s, CAST(%s AS JSON), CAST(%s AS JSON))",
                (result_id, manifest_str, analysis_str),
            )
            version = cur.lastrowid

            return TestResult(
                id=result_id,
                owner_user_id=owner_user_id,
                suite_id=suite_id,
                label=label,
                is_shared=is_shared,
            ), int(version)


def get_latest_suite_version(
    requesting_user_id: int,
    suite_id: int,
) -> Optional[Tuple[TestSuite, int, Dict[str, Any]]]:
    """Return the latest visible version of a suite for the requesting user.

    Ownership rules:
    - The owner always has access.
    - Non-owners only see the suite if is_shared=1.
    """

    conn = _connect()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_user_id, name, is_shared FROM test_suites WHERE id = %s",
                (suite_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            owner_user_id = row["owner_user_id"]
            is_shared = bool(row["is_shared"])
            if requesting_user_id != owner_user_id and not is_shared:
                return None

            cur.execute(
                "SELECT version, suite_json FROM test_suite_versions "
                "WHERE suite_id = %s ORDER BY version DESC LIMIT 1",
                (suite_id,),
            )
            vrow = cur.fetchone()
            if not vrow:
                return None
            version = int(vrow["version"])
            doc = json.loads(vrow["suite_json"])
            suite = TestSuite(
                id=row["id"],
                owner_user_id=owner_user_id,
                name=row["name"],
                is_shared=is_shared,
            )
            return suite, version, doc


def list_suites_for_user(user_id: int) -> List[TestSuite]:
    """List all suites owned by the user (ignores shared-by-others for now)."""

    conn = _connect()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_user_id, name, is_shared FROM test_suites WHERE owner_user_id = %s",
                (user_id,),
            )
            suites: List[TestSuite] = []
            for row in cur.fetchall() or []:
                suites.append(
                    TestSuite(
                        id=row["id"],
                        owner_user_id=row["owner_user_id"],
                        name=row["name"],
                        is_shared=bool(row["is_shared"]),
                    )
                )
            return suites


def get_latest_result_version(
    requesting_user_id: int,
    result_id: int,
) -> Optional[Tuple[TestResult, int, Dict[str, Any], Optional[Dict[str, Any]]]]:
    """Return the latest visible version of a result for the requesting user.

    Ownership rules:
    - The owner always has access.
    - Non-owners only see the result if is_shared=1, and it is always
      read-only at the API level.
    """

    conn = _connect()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, owner_user_id, suite_id, label, is_shared FROM test_results WHERE id = %s",
                (result_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            owner_user_id = row["owner_user_id"]
            is_shared = bool(row["is_shared"])
            if requesting_user_id != owner_user_id and not is_shared:
                return None

            cur.execute(
                "SELECT version, manifest_json, analysis_json FROM test_result_versions "
                "WHERE result_id = %s ORDER BY version DESC LIMIT 1",
                (result_id,),
            )
            vrow = cur.fetchone()
            if not vrow:
                return None
            version = int(vrow["version"])
            manifest = json.loads(vrow["manifest_json"])
            analysis = (
                json.loads(vrow["analysis_json"]) if vrow["analysis_json"] is not None else None
            )
            result = TestResult(
                id=row["id"],
                owner_user_id=owner_user_id,
                suite_id=row["suite_id"],
                label=row["label"],
                is_shared=is_shared,
            )
            return result, version, manifest, analysis

