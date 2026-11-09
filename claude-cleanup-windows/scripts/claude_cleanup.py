"""Windows Claude cleanup: read-only audit, verified snapshots, recoverable moves."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid


CLI_CACHES = ("cache", "stats-cache.json", "telemetry", "usage-data",
              "usage.jsonl", "usage.with-fix.jsonl")
DESKTOP_CACHES = ("Cache", "Code Cache", "GPUCache", "DawnCache", "logs", "Crashpad")
ACCOUNT_CACHE_KEYS = {
    "additionalModelCostsCache", "additionalModelOptionsCache", "anonymousId",
    "autoCompactWindowsCache", "cachedChromeExtensionInstalled", "cachedDynamicConfigs",
    "cachedExperimentData", "cachedExperimentFeatures", "cachedExtraUsageDisabledReason",
    "cachedGrowthBookFeatures", "cachedGrowthBookFeaturesAt", "cachedStatsigGates",
    "clientDataCache", "clientDataCacheSlots", "feedbackSurveyState", "groveConfigCache",
    "metricsStatusCache", "modelAccessCache", "oauthAccount", "orgModelDefaultCache",
    "passesEligibilityCache", "s1mAccessCache",
}


def reject_links(path: Path) -> None:
    """Check every existing ancestor as well as descendants; never traverse a junction."""
    for entry in reversed((path, *path.parents)):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RuntimeError(f"Link/reparse point refused: {entry}")
    if path.is_dir():
        for child in path.iterdir():
            reject_links(child)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inventory(path: Path) -> dict:
    reject_links(path)
    if not path.exists():
        return {"exists": False}
    if path.is_file():
        return {"file": digest(path)}
    return {str(item.relative_to(path)): digest(item) if item.is_file() else None
            for item in sorted(path.rglob("*"))}


def save_json(path: Path, value: object) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def process_table() -> list[dict]:
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
               "@(Get-CimInstance Win32_Process | Select-Object "
               "ProcessId,ParentProcessId,Name,CommandLine) | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                             "-Command", command], capture_output=True, check=True)
    # Force Unicode-safe transport without exposing process command lines in audit output.
    raw = result.stdout.decode("utf-8-sig", errors="replace").strip()
    data = json.loads(raw or "[]")
    return data if isinstance(data, list) else [data]


def is_claude(process: dict) -> bool:
    name = str(process.get("Name", "")).lower()
    command = str(process.get("CommandLine") or "").lower().replace("\\", "/")
    return (name in {"claude.exe", "claude-code.exe", "claude"}
            or name == "node.exe" and any(marker in command for marker in
                ("/@anthropic-ai/claude-code/", "/claude-code/cli.js")))


def ensure_idle() -> int:
    table = process_table()
    count = sum(is_claude(process) for process in table)
    if count:
        raise RuntimeError(f"Close all Claude processes normally first ({count} detected).")
    return count


def roots(home: Path, roaming: Path) -> dict[str, Path]:
    return {"cli": home / ".claude", "identity": home / ".claude.json",
            "desktop": roaming / "Claude", "local": Path(os.environ.get(
                "LOCALAPPDATA", str(home / "AppData/Local")))}


def desktop_roots(locations: dict[str, Path]) -> list[Path]:
    local = locations["local"]
    found = [locations["desktop"], locations["desktop"].with_name("Claude-3p"),
             local / "Claude-3p"]
    packages = local / "Packages"
    # Only inspect known Claude package-family names, never delete package roots.
    if packages.exists():
        for package in packages.iterdir():
            if re.fullmatch(r"(?:Claude|Anthropic\.Claude)_[a-z0-9]+", package.name, re.I):
                for parent in ("Roaming", "Local"):
                    found.extend(package / "LocalCache" / parent / name
                                 for name in ("Claude", "Claude-3p"))
    return sorted(set(found), key=str)


def installed_packages() -> list[dict]:
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
               "@(Get-AppxPackage | Where-Object { $_.Name -in @('Claude','Anthropic.Claude') } | "
               "Select-Object Name,PackageFullName,PackageFamilyName) | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, check=True)
    data = json.loads(result.stdout.decode("utf-8-sig").strip() or "[]")
    packages = data if isinstance(data, list) else [data]
    for package in packages:
        if (package.get("Name") not in {"Claude", "Anthropic.Claude"}
                or not re.fullmatch(r"(?:Claude|Anthropic\.Claude)_[a-z0-9]+",
                                    package.get("PackageFamilyName", ""), re.I)
                or not re.fullmatch(r"(?:Claude|Anthropic\.Claude)_[a-zA-Z0-9_.-]+",
                                    package.get("PackageFullName", ""))):
            raise RuntimeError("Unexpected Claude package identity; refusing uninstall/reset")
    return packages


def uninstall_package(package: dict) -> None:
    # Pass the exact identity as data rather than interpolating a shell command.
    if package not in installed_packages():
        raise RuntimeError("Installed package changed since the plan was confirmed")
    ensure_idle()
    command = "$ErrorActionPreference='Stop'; Remove-AppxPackage -Package $env:CLAUDE_CLEANUP_PACKAGE -ErrorAction Stop"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env=dict(os.environ, CLAUDE_CLEANUP_PACKAGE=package["PackageFullName"]), capture_output=True)
    if result.returncode:
        raise RuntimeError("Windows package uninstall failed: " + result.stderr.decode(errors="replace"))
    if any(p["PackageFullName"] == package["PackageFullName"] for p in installed_packages()):
        raise RuntimeError("Windows still reports the package installed")


def compact_paths(paths: list[Path]) -> list[Path]:
    unique = sorted(set(paths), key=lambda p: (len(p.parts), str(p)))
    result = []
    for path in unique:
        if not any(root == path or root in path.parents for root in result):
            result.append(path)
    return result


def desktop_state_paths(locations: dict[str, Path], packages: list[dict]) -> list[Path]:
    paths = desktop_roots(locations)
    # LocalCache includes the virtualized Electron profile. State folders can
    # contain login/session data outside that profile; keep the package root intact.
    for package in packages:
        root = locations["local"] / "Packages" / package["PackageFamilyName"]
        paths.extend(root / name for name in ("LocalCache", "LocalState", "RoamingState", "Settings", "TempState"))
    return compact_paths([path for path in paths if path.exists()])


def candidates(locations: dict[str, Path], reset_login: bool,
               desktop: str = "keep", packages: list[dict] | None = None) -> list[Path]:
    if desktop not in {"keep", "reset", "uninstall"}:
        raise ValueError("Invalid desktop mode")
    paths = [locations["cli"] / name for name in CLI_CACHES]
    if desktop == "keep":
        paths += [root / name for root in desktop_roots(locations) for name in DESKTOP_CACHES]
    else:
        paths += desktop_state_paths(locations, packages if packages is not None else installed_packages())
    if reset_login:
        paths.append(locations["cli"] / ".credentials.json")
    cli_allowed = {locations["cli"] / name for name in CLI_CACHES + (".credentials.json",)}
    for path in paths:
        if not path.is_absolute():
            raise RuntimeError("Expected an absolute cleanup path")
        if path not in cli_allowed and (path == locations["cli"] or path in locations["cli"].parents
                                       or locations["cli"] in path.parents):
            raise RuntimeError("Desktop target overlaps protected CLI state")
        reject_links(path)
    return compact_paths([path for path in paths if path.exists()])


def read_settings(path: Path) -> dict:
    reject_links(path)
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("env", {}), dict):
        raise ValueError("settings.json and env must be JSON objects")
    return data


def prepare_identity(locations: dict[str, Path]) -> list[tuple[Path, dict]]:
    identity = locations["identity"]
    if not identity.is_file():
        raise RuntimeError("Local identity file .claude.json not found")
    paths = [identity] + sorted((locations["cli"] / "backups").glob(".claude.json.backup.*"))
    values = {"userID": os.urandom(32).hex(), "machineID": os.urandom(32).hex()}
    prepared = []
    for path in paths:
        reject_links(path)
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"Identity must be a JSON object: {path}")
        updated = {key: value for key, value in data.items() if key not in ACCOUNT_CACHE_KEYS}
        updated.update(values)
        prepared.append((path, updated))
    return prepared


def execute(home: Path, roaming: Path, targets: list[Path], simple: str | None,
            reset_login: bool = False, rotate_ids: bool = False,
            desktop: str = "keep", expected_packages: list[dict] | None = None) -> Path:
    locations = roots(home, roaming)
    packages = installed_packages() if desktop != "keep" else []
    if expected_packages is not None and packages != expected_packages:
        raise RuntimeError("Package list changed since confirmation")
    if desktop == "uninstall" and not packages:
        raise RuntimeError("No supported current-user Claude MSIX package found; nothing uninstalled")
    permitted = set(candidates(locations, reset_login, desktop, packages))
    if len(set(targets)) != len(targets) or any(path not in permitted for path in targets):
        raise RuntimeError("Target outside exact allowlist")
    if desktop != "keep" and set(targets) != permitted:
        raise RuntimeError("Incomplete Desktop reset plan; re-audit before proceeding")
    ensure_idle()
    settings = locations["cli"] / "settings.json"
    original = read_settings(settings) if simple else None
    identity_updates = prepare_identity(locations) if rotate_ids else []
    sources = [(locations["cli"], "cli"), (locations["identity"], "identity.json")]
    desktop_targets = [path for path in targets if locations["cli"] not in path.parents]
    sources += [(path, f"desktop/{index:02d}-{path.name}") for index, path in enumerate(desktop_targets)]
    if desktop == "uninstall":
        # Windows may remove additional package-owned data during unregistration.
        # Preserve the complete per-user package data before invoking Windows.
        sources += [(locations["local"] / "Packages" / p["PackageFamilyName"],
                     f"packages/{p['PackageFamilyName']}") for p in packages]
    before = {str(path): inventory(path) for path, _ in sources}
    # All link and settings validation finishes before the first write.
    backup_root = home / "ClaudeCleanupBackups"
    reject_links(backup_root)
    batch = backup_root / (datetime.datetime.now().strftime("%Y%m%d-%H%M%S-")
                           + uuid.uuid4().hex[:8])
    snapshot = batch / "snapshot"
    snapshot.mkdir(parents=True)
    print(f"Backup batch (retain on any failure): {batch}", flush=True)
    for source, relative in sources:
        if not source.exists():
            continue
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        if inventory(destination) != before[str(source)]:
            raise RuntimeError(f"Backup verification failed: {source}")
    for source, _ in sources:
        if inventory(source) != before[str(source)]:
            raise RuntimeError(f"Source changed during backup: {source}")
    plan = [{"source": str(path), "destination": str(batch / "quarantine" / f"{i:02d}-{path.name}")}
            for i, path in enumerate(targets)]
    record = {"moves": plan, "simple": simple,
              "snapshots": [{"source": str(path), "snapshot": str(snapshot / relative)}
                            for path, relative in sources],
              "desktop": desktop, "packages": packages,
              "identity_updates": [str(path) for path, _ in identity_updates]}
    save_json(batch / "plan.json", dict(record, status="backed-up"))
    ensure_idle()
    for item in plan:
        source, destination = Path(item["source"]), Path(item["destination"])
        reject_links(source)
        destination.parent.mkdir(exist_ok=True)
        shutil.move(str(source), str(destination))
        print(f"Quarantined: {source}")
        save_json(batch / "progress.json", {"last_completed_move": item})
    if simple:
        if read_settings(settings) != original:
            raise RuntimeError("Settings changed during cleanup; refusing overwrite")
        updated = dict(original)
        env = dict(updated.get("env", {}))
        if simple == "on":
            env["CLAUDE_CODE_SIMPLE"] = "1"
        else:
            env.pop("CLAUDE_CODE_SIMPLE", None)
        if env or "env" in updated:
            updated["env"] = env
        if updated != original:
            settings.parent.mkdir(exist_ok=True)
            save_json(settings, updated)
    for path, data in identity_updates:
        save_json(path, data)
    for package in packages if desktop == "uninstall" else []:
        uninstall_package(package)
        save_json(batch / "uninstall-progress.json", {"last_uninstalled": package["PackageFullName"]})
    save_json(batch / "plan.json", dict(record, status="complete"))
    return batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true", help="Read only; default without this flag is interactive cleanup")
    parser.add_argument("--reset-cli-login", action="store_true")
    parser.add_argument("--rotate-local-ids", action="store_true",
                        help="Rotate local userID/machineID and known account cache fields")
    parser.add_argument("--simple", choices=("on", "off"))
    parser.add_argument("--desktop", choices=("keep", "reset", "uninstall"), default="keep",
                        help="reset: quarantine Desktop profile/login/session data; uninstall: also remove current-user MSIX app")
    args = parser.parse_args()
    try:
        if os.name != "nt":
            raise RuntimeError("Run with native Windows Python, not WSL")
        if os.environ.get("CLAUDE_CONFIG_DIR"):
            raise RuntimeError("Custom CLAUDE_CONFIG_DIR is not supported")
        home = Path.home()
        roaming = Path(os.environ.get("APPDATA", str(home / "AppData/Roaming")))
        locations = roots(home, roaming)
        packages = installed_packages() if args.desktop != "keep" else []
        targets = candidates(locations, args.reset_cli_login, args.desktop, packages)
        try:
            count = sum(is_claude(process) for process in process_table())
        except (OSError, ValueError, subprocess.SubprocessError):
            if not args.audit:
                raise RuntimeError("Process query unavailable; run in a normal Windows terminal with CIM access")
            count = "unavailable (process query denied; cleanup blocked)"
        print(f"Claude processes: {count}; selected targets: {len(targets)}")
        for path in targets:
            size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else path.stat().st_size
            print(f"  {size:,} bytes  {path}")
        print(f"CLI login reset: {args.reset_cli_login}; simple mode: {args.simple or 'unchanged'}")
        print(f"Local ID rotation: {args.rotate_local_ids} (includes identity backup files)")
        print(f"Desktop action: {args.desktop}")
        for package in packages:
            print("  Installed MSIX:", package["PackageFullName"])
        if args.desktop != "keep":
            print("Desktop reset includes login, local sessions/Cowork data, MCP configuration and extensions.")
            print("Desktop installation is retained for reset. Uninstall removes the current-user MSIX app;")
            print("reinstall from the official installer before restoring data. CLI history/skills are retained.")
        if args.desktop == "uninstall" and not packages:
            raise RuntimeError("No supported Claude MSIX installation found; refusing an incomplete uninstall")
        if args.audit:
            return 0
        if not targets and not args.simple and not args.rotate_local_ids and args.desktop != "uninstall":
            print("Nothing to clean.")
            return 0
        if not sys.stdin.isatty():
            raise RuntimeError("An interactive terminal is required")
        ensure_idle()
        print("Full verified snapshot first. Moves go to ClaudeCleanupBackups, not Recycle Bin.")
        if input("Enter CONFIRM to apply the list above: ").strip() != "CONFIRM":
            print("Cancelled; no changes.")
            return 1
        ensure_idle()
        batch = execute(home, roaming, targets, args.simple, args.reset_cli_login,
                        args.rotate_local_ids, args.desktop, packages)
        print(f"Complete. Backup and recovery plan: {batch}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, EOFError, KeyboardInterrupt) as error:
        print(f"STOPPED: {error}. If a backup batch was printed, retain it; work may be partial.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
