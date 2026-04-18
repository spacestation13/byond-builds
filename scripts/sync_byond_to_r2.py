import email.utils
import html
import logging
import mimetypes
import os
import random
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


if load_dotenv:
    load_dotenv()


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("download_byond_r2.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("byond-r2-sync")


BYOND_DOWNLOAD_BASE_URL = "https://www.byond.com/download"
BYOND_BUILD_BASE_URL = f"{BYOND_DOWNLOAD_BASE_URL}/build"
BYOND_VERSION_TXT_URL = f"{BYOND_DOWNLOAD_BASE_URL}/version.txt"
MIRROR_USER_AGENT = "SS13BYONDMirror/2.0 (+https://byond-builds.dm-lang.org)"
REQUEST_DELAY_SECONDS = 6.7
REQUEST_TIMEOUT_SECONDS = 120
HTTP_RETRIES = 8
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAJOR_VERSIONS = ("516", "515")

R2_BUCKET = os.getenv("R2_BUCKET", "byond-builds")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_CACHE_CONTROL = os.getenv("R2_CACHE_CONTROL", "public, max-age=31536000, immutable")
R2_CACHE_CONTROL_LATEST = os.getenv("R2_CACHE_CONTROL_LATEST", "public, max-age=300")
R2_CACHE_CONTROL_HTML = os.getenv("R2_CACHE_CONTROL_HTML", "public, max-age=300")
REPO_ROOT = Path(__file__).resolve().parent.parent
REPO_PUBLIC_DIR = REPO_ROOT / "public"

_host_request_times: Dict[str, float] = {}


@dataclass(frozen=True)
class VersionSyncState:
    existing_r2_names: Set[str]
    available_builds: List[str]
    latest_changed: bool


class DirectoryIndexParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: List[Tuple[str, str]] = []
        self._current_href: Optional[str] = None
        self._current_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        self._current_href = dict(attrs).get("href")
        self._current_text = []

    def handle_data(self, data):
        if self._current_href is None:
            return
        self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or self._current_href is None:
            return
        self.links.append((self._current_href, "".join(self._current_text).strip()))
        self._current_href = None
        self._current_text = []


def get_r2_client():
    if not (R2_ENDPOINT and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY):
        raise RuntimeError(
            "Missing R2 credentials. Set R2_ENDPOINT, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY in environment or .env."
        )
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )


def is_build_filename(name: str) -> bool:
    return (
        name.endswith("_byond.exe")
        or name.endswith("_byond.zip")
        or name.endswith("_byond_linux.zip")
    )


def is_latest_filename(name: str) -> bool:
    return ".latest_" in name


def parse_version_from_filename(filename: str) -> Tuple[Optional[str], Optional[int]]:
    match = re.match(r"(\d+)\.(\d+)_byond(?:\.exe|\.zip|_linux\.zip)", filename)
    if not match:
        return None, None
    return match.group(1), int(match.group(2))


def wait_for_byond_slot(url: str):
    host = urlparse(url).netloc.lower()
    if not host.endswith("byond.com"):
        return

    last_request_time = _host_request_times.get(host)
    if last_request_time is not None:
        remaining_delay = REQUEST_DELAY_SECONDS - (time.monotonic() - last_request_time)
        if remaining_delay > 0:
            logger.info(f"Waiting {remaining_delay:.1f}s before next BYOND request")
            time.sleep(remaining_delay)

    _host_request_times[host] = time.monotonic()


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        pass

    try:
        retry_at = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    return max(retry_at.timestamp() - time.time(), 0.0)


def get_retry_delay(attempt: int, retry_after: Optional[float]) -> float:
    exponential_delay = min(max(REQUEST_DELAY_SECONDS, 1.0) * (2 ** (attempt - 1)), 90.0)
    minimum_delay = retry_after if retry_after is not None else 0.0
    return max(exponential_delay, minimum_delay) + random.uniform(0.25, 1.25)


def fetch_text(url: str, *, source_label: str, allow_not_found: bool = False) -> Optional[str]:
    for attempt in range(1, HTTP_RETRIES + 1):
        wait_for_byond_slot(url)
        request = urllib.request.Request(url, headers={"User-Agent": MIRROR_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            if allow_not_found and error.code == 404:
                return None

            if error.code in RETRYABLE_STATUS_CODES and attempt < HTTP_RETRIES:
                retry_delay = get_retry_delay(attempt, parse_retry_after(error.headers.get("Retry-After")))
                logger.warning(
                    "%s request for %s returned HTTP %s. Retry %s/%s in %.1fs",
                    source_label,
                    url,
                    error.code,
                    attempt,
                    HTTP_RETRIES,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            logger.error("%s request failed for %s: HTTP %s", source_label, url, error.code)
            return None
        except Exception as error:
            if attempt < HTTP_RETRIES:
                retry_delay = get_retry_delay(attempt, None)
                logger.warning(
                    "%s request for %s failed: %s. Retry %s/%s in %.1fs",
                    source_label,
                    url,
                    error,
                    attempt,
                    HTTP_RETRIES,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            logger.error("%s request failed for %s: %s", source_label, url, error)
            return None

    return None


def download_to_path(url: str, target_path: Path, *, source_label: str) -> bool:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = target_path.with_name(f"{target_path.name}.part")

    for attempt in range(1, HTTP_RETRIES + 1):
        wait_for_byond_slot(url)
        request = urllib.request.Request(url, headers={"User-Agent": MIRROR_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                with partial_path.open("wb") as file_handle:
                    shutil.copyfileobj(response, file_handle)
            partial_path.replace(target_path)
            logger.info(f"Downloaded {url} to {target_path}")
            return True
        except urllib.error.HTTPError as error:
            if partial_path.exists():
                partial_path.unlink()

            if error.code in RETRYABLE_STATUS_CODES and attempt < HTTP_RETRIES:
                retry_delay = get_retry_delay(attempt, parse_retry_after(error.headers.get("Retry-After")))
                logger.warning(
                    "%s download for %s returned HTTP %s. Retry %s/%s in %.1fs",
                    source_label,
                    url,
                    error.code,
                    attempt,
                    HTTP_RETRIES,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            logger.error("%s download failed for %s: HTTP %s", source_label, url, error.code)
            return False
        except Exception as error:
            if partial_path.exists():
                partial_path.unlink()

            if attempt < HTTP_RETRIES:
                retry_delay = get_retry_delay(attempt, None)
                logger.warning(
                    "%s download for %s failed: %s. Retry %s/%s in %.1fs",
                    source_label,
                    url,
                    error,
                    attempt,
                    HTTP_RETRIES,
                    retry_delay,
                )
                time.sleep(retry_delay)
                continue

            logger.error("%s download failed for %s: %s", source_label, url, error)
            return False

    return False


def build_sort_key(name: str) -> Tuple[int, int, str]:
    match = re.search(r"\.(\d+)_", name)
    minor_version = int(match.group(1)) if match else -1
    return (0 if is_latest_filename(name) else 1, -minor_version, name)


def get_available_builds(version: str) -> Optional[List[str]]:
    listing_url = f"{BYOND_BUILD_BASE_URL}/{version}/"
    content = fetch_text(listing_url, source_label="BYOND", allow_not_found=True)
    if content is None:
        logger.error(f"Failed to fetch build listing for version {version}")
        return None

    parser = DirectoryIndexParser()
    parser.feed(content)
    build_names = set()
    for href, text in parser.links:
        candidate = (text or href.rsplit("/", 1)[-1]).strip()
        if not candidate or candidate.startswith("?") or candidate.endswith("/"):
            continue
        if not is_build_filename(candidate):
            continue
        major_version, minor_version = parse_version_from_filename(candidate)
        if major_version == version and minor_version is not None:
            build_names.add(candidate)

    sorted_builds = sorted(build_names, key=build_sort_key)
    logger.info(f"Found {len(sorted_builds)} build files for version {version}")
    return sorted_builds


def list_r2_names(client, prefix: str) -> Set[str]:
    paginator = client.get_paginator("list_objects_v2")
    prefix_with_slash = f"{prefix}/"
    names: Set[str] = set()

    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix_with_slash):
        for item in page.get("Contents", []):
            key = item["Key"]
            relative_key = key[len(prefix_with_slash):]
            if not relative_key or "/" in relative_key:
                continue
            names.add(relative_key)

    return names


def download_r2_object(client, key: str, target_path: Path) -> bool:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target_path.open("wb") as file_handle:
            client.download_fileobj(R2_BUCKET, key, file_handle)
        logger.info(f"Downloaded R2 object {key} to {target_path}")
        return True
    except ClientError as error:
        logger.error(f"Failed to download R2 object {key}: {error}")
        if target_path.exists():
            target_path.unlink()
        return False


def cache_control_for_file(file_path: Path) -> str:
    if file_path.suffix in {".html", ".txt"}:
        return R2_CACHE_CONTROL_HTML
    if is_latest_filename(file_path.name):
        return R2_CACHE_CONTROL_LATEST
    return R2_CACHE_CONTROL


def upload_file_to_r2(client, local_path: Path, key: str) -> bool:
    content_type, _ = mimetypes.guess_type(str(local_path))
    extra_args = {"CacheControl": cache_control_for_file(local_path)}
    if content_type:
        extra_args["ContentType"] = content_type

    try:
        with local_path.open("rb") as file_handle:
            client.upload_fileobj(file_handle, R2_BUCKET, key, ExtraArgs=extra_args)
        logger.info(f"Uploaded {key} to R2")
        return True
    except Exception as error:
        logger.error(f"Failed to upload {key} to R2: {error}")
        return False


def get_r2_object_identity(client, key: str) -> Optional[Tuple[str, int]]:
    try:
        response = client.head_object(Bucket=R2_BUCKET, Key=key)
    except ClientError as error:
        error_code = str(error.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise

    return response.get("ETag", "").strip('"'), response["ContentLength"]


def get_latest_build_targets(file_names: List[str], major_version: str) -> List[Tuple[str, str]]:
    version_groups: Dict[int, List[str]] = {}
    for file_name in file_names:
        parsed_major, parsed_minor = parse_version_from_filename(file_name)
        if parsed_major == major_version and parsed_minor is not None:
            version_groups.setdefault(parsed_minor, []).append(file_name)

    if not version_groups:
        return []

    latest_minor = max(version_groups.keys())
    latest_targets = []
    for source_name in version_groups[latest_minor]:
        target_name = re.sub(fr"{major_version}\.\d+_", f"{major_version}.latest_", source_name)
        latest_targets.append((source_name, target_name))
    return latest_targets


def latest_aliases_need_update(client, version: str, existing_r2_names: Set[str], available_builds: List[str]) -> bool:
    latest_targets = get_latest_build_targets(available_builds, version)
    if not latest_targets:
        logger.warning(f"No latest targets found for version {version}")
        return False

    for source_name, alias_name in latest_targets:
        if source_name not in existing_r2_names:
            logger.info("Version %s needs sync because %s is not in R2", version, source_name)
            return True

        if alias_name not in existing_r2_names:
            logger.info("Version %s needs sync because %s is missing from R2", version, alias_name)
            return True

        source_identity = get_r2_object_identity(client, f"{version}/{source_name}")
        alias_identity = get_r2_object_identity(client, f"{version}/{alias_name}")
        if source_identity != alias_identity:
            logger.info("Version %s needs sync because %s does not match %s", version, alias_name, source_name)
            return True

    return False


def scan_version_state(client, version: str) -> Optional[VersionSyncState]:
    existing_r2_names = list_r2_names(client, version)
    available_builds = get_available_builds(version)
    if available_builds is None:
        return None

    try:
        latest_changed = latest_aliases_need_update(client, version, existing_r2_names, available_builds)
    except ClientError as error:
        logger.error(f"Failed to inspect R2 state for version {version}: {error}")
        return None

    return VersionSyncState(
        existing_r2_names=existing_r2_names,
        available_builds=available_builds,
        latest_changed=latest_changed,
    )


def read_text_required(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Required template missing: {path}")
    return path.read_text(encoding="utf-8")


def replace_required(content: str, pattern: str, replacement: str, description: str, flags: int = 0) -> str:
    updated_content, replacements = re.subn(pattern, replacement, content, count=1, flags=flags)
    if replacements != 1:
        raise RuntimeError(f"Could not patch {description}")
    return updated_content


def build_version_list_markup(file_names: List[str]) -> str:
    if not file_names:
        return "        <li>No builds found</li>"
    return "\n".join(
        f"        <li><a href='{html.escape(file_name)}'>{html.escape(file_name)}</a></li>"
        for file_name in file_names
    )


def generate_version_index(version: str, file_names: List[str], output_path: Path):
    sorted_names = sorted((name for name in file_names if is_build_filename(name)), key=build_sort_key)
    template = read_text_required(REPO_PUBLIC_DIR / version / "index.html")
    content = replace_required(
        template,
        r"<ul>\s*.*?\s*</ul>",
        "<ul>\n" + build_version_list_markup(sorted_names) + "\n    </ul>",
        f"build list for version {version}",
        flags=re.S,
    )
    output_path.write_text(content, encoding="utf-8")


def copy_root_index(output_path: Path):
    output_path.write_text(read_text_required(REPO_PUBLIC_DIR / "index.html"), encoding="utf-8")


def write_version_txt(content: str, output_path: Path):
    output_path.write_text(content.strip() + "\n", encoding="utf-8")


def set_github_output(name: str, value: str):
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return

    with open(output_path, "a", encoding="utf-8") as file_handle:
        file_handle.write(f"{name}={value}\n")


def sync_version(client, stage_root: Path, version: str, state: VersionSyncState) -> int:
    version_dir = stage_root / version
    version_dir.mkdir(parents=True, exist_ok=True)

    existing_r2_names = state.existing_r2_names
    existing_build_names = {name for name in existing_r2_names if is_build_filename(name)}
    source_build_names = {name for name in existing_build_names if not is_latest_filename(name)}
    existing_latest_names = {name for name in existing_r2_names if is_latest_filename(name)}

    available_builds = state.available_builds

    failures = 0
    local_source_paths: Dict[str, Path] = {}
    uploaded_build_names: Set[str] = set()

    for file_name in available_builds:
        if file_name in source_build_names:
            continue

        target_path = version_dir / file_name
        byond_url = f"{BYOND_BUILD_BASE_URL}/{version}/{file_name}"
        if not download_to_path(byond_url, target_path, source_label="BYOND"):
            failures += 1
            continue

        if not upload_file_to_r2(client, target_path, f"{version}/{file_name}"):
            failures += 1
            continue

        local_source_paths[file_name] = target_path
        uploaded_build_names.add(file_name)

    latest_targets = get_latest_build_targets(available_builds, version)
    version_index_names = set(source_build_names)
    version_index_names.update(uploaded_build_names)
    version_index_names.update(existing_latest_names)

    for source_name, alias_name in latest_targets:
        source_path = local_source_paths.get(source_name)
        if source_path is None:
            source_path = version_dir / source_name
            if not download_r2_object(client, f"{version}/{source_name}", source_path):
                failures += 1
                continue

        alias_path = version_dir / alias_name
        shutil.copy2(source_path, alias_path)
        if not upload_file_to_r2(client, alias_path, f"{version}/{alias_name}"):
            failures += 1
            continue

        version_index_names.add(alias_name)

    index_path = version_dir / "index.html"
    generate_version_index(version, sorted(version_index_names, key=build_sort_key), index_path)
    if not upload_file_to_r2(client, index_path, f"{version}/index.html"):
        failures += 1

    return failures


def sync_builds() -> int:
    client = get_r2_client()
    set_github_output("synced", "false")

    logger.info(f"Target major versions: {', '.join(MAJOR_VERSIONS)}")

    version_states: Dict[str, VersionSyncState] = {}
    for version in MAJOR_VERSIONS:
        state = scan_version_state(client, version)
        if state is None:
            return 1
        version_states[version] = state

    if not any(state.latest_changed for state in version_states.values()):
        logger.info("Skipping sync because no latest build aliases changed")
        return 0

    official_version_txt = fetch_text(BYOND_VERSION_TXT_URL, source_label="BYOND")
    if official_version_txt is None:
        logger.error("Failed to fetch official version.txt")
        return 1

    failures = 0
    with tempfile.TemporaryDirectory(prefix="byond-r2-sync-") as temp_dir:
        stage_root = Path(temp_dir)

        for version in MAJOR_VERSIONS:
            failures += sync_version(client, stage_root, version, version_states[version])

        version_txt_path = stage_root / "version.txt"
        write_version_txt(official_version_txt, version_txt_path)
        if not upload_file_to_r2(client, version_txt_path, "version.txt"):
            failures += 1

        root_index_path = stage_root / "index.html"
        copy_root_index(root_index_path)
        if not upload_file_to_r2(client, root_index_path, "index.html"):
            failures += 1

    if failures:
        logger.error(f"Finished with {failures} failed operations")
        return 1

    set_github_output("synced", "true")
    logger.info("Finished with no sync failures")
    return 0


if __name__ == "__main__":
    logger.info("Starting BYOND to R2 sync")
    raise SystemExit(sync_builds())