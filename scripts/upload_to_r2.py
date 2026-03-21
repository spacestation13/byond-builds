import os
import re
import logging
import argparse
import mimetypes
from pathlib import Path
from typing import List, Optional, Tuple
import boto3
from botocore.exceptions import ClientError
import shutil
import re
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("upload_r2.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("r2-upload")

if load_dotenv:
    load_dotenv()

# R2 Configuration
R2_BUCKET = os.getenv("R2_BUCKET", "byond-builds")
R2_ENDPOINT = os.getenv("R2_ENDPOINT")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_PUBLIC_BASE_URL = os.getenv("R2_PUBLIC_BASE_URL", "https://files.byond-builds.dm-lang.org")
R2_CACHE_CONTROL = os.getenv("R2_CACHE_CONTROL", "public, max-age=31536000, immutable")
R2_CACHE_CONTROL_LATEST = os.getenv("R2_CACHE_CONTROL_LATEST", "public, max-age=300")
R2_CACHE_CONTROL_HTML = os.getenv("R2_CACHE_CONTROL_HTML", "public, max-age=300")

# Define the base version paths
BASE_VERSIONS = ['515', '516']

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
        name.endswith('_byond.exe') or
        name.endswith('_byond.zip') or
        name.endswith('_byond_linux.zip')
    )

def is_latest_filename(name: str) -> bool:
    return ".latest_" in name

def cache_control_for_file(file_path: Path) -> str:
    """Determine cache control based on file type and name."""
    if file_path.suffix in {'.html', '.txt'}:
        return R2_CACHE_CONTROL_HTML
    elif is_latest_filename(file_path.name):
        return R2_CACHE_CONTROL_LATEST
    else:
        return R2_CACHE_CONTROL

def upload_file_to_r2(
    client,
    local_path: Path,
    key: str,
    skip_existing: bool = True,
    cache_control: Optional[str] = None,
    force_upload: bool = False,
) -> bool:
    """Upload a file to R2."""
    if skip_existing and not force_upload:
        try:
            client.head_object(Bucket=R2_BUCKET, Key=key)
            logger.info(f"R2 already has {key}, skipping upload")
            return True
        except ClientError as e:
            if e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") not in {404, 403}:
                logger.error(f"R2 head_object failed for {key}: {e}")
                return False
    
    content_type, _ = mimetypes.guess_type(str(local_path))
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type
    if cache_control:
        extra_args["CacheControl"] = cache_control
    
    try:
        file_size = local_path.stat().st_size
        logger.info(f"Uploading {key} ({file_size / 1024 / 1024:.2f} MB)...")
        with local_path.open("rb") as f:
            client.upload_fileobj(f, R2_BUCKET, key, ExtraArgs=extra_args if extra_args else None)
        logger.info(f"Uploaded to R2: {key}")
        return True
    except Exception as e:
        logger.error(f"Failed to upload {local_path} to R2 ({key}): {e}")
        return False

def upload_directory(
    client,
    local_dir: Path,
    prefix: str = "",
    skip_existing: bool = True,
    skip_binaries: bool = False,
) -> tuple[int, int]:
    """Upload all files in a directory to R2.
    
    Returns:
        tuple: (successful_uploads, failed_uploads)
    """
    successful = 0
    failed = 0
    
    for item in local_dir.rglob("*"):
        if item.is_file():
            # Skip binary files if requested
            if skip_binaries and is_build_filename(item.name):
                continue
            
            # Calculate relative path from local_dir
            rel_path = item.relative_to(local_dir)
            key = f"{prefix}/{rel_path}".replace("\\", "/") if prefix else str(rel_path).replace("\\", "/")
            
            # Determine cache control
            cache_control = cache_control_for_file(item)
            
            # Upload
            if upload_file_to_r2(client, item, key, skip_existing=skip_existing, cache_control=cache_control):
                successful += 1
            else:
                failed += 1
    
    return successful, failed

def parse_version_from_filename(filename: str) -> Tuple[Optional[str], Optional[int]]:
    pattern = r"(\d+)\.(\d+)_byond(?:\.exe|\.zip|_linux\.zip)"
    match = re.match(pattern, filename)
    if match:
        return match.group(1), int(match.group(2))
    return None, None

def ensure_latest_files(version_dir: Path, major_version: str) -> List[Path]:
    """Create .latest_ copies for the highest minor in the version directory if missing.

    Returns list of created latest file paths.
    """
    files = [p for p in version_dir.iterdir() if p.is_file() and is_build_filename(p.name)]
    version_groups = {}
    for p in files:
        major, minor = parse_version_from_filename(p.name)
        if major == major_version and minor is not None:
            version_groups.setdefault(minor, []).append(p)
    if not version_groups:
        return []
    latest_minor = max(version_groups.keys())
    created = []
    for src in version_groups[latest_minor]:
        target_name = re.sub(fr'{major_version}\.\d+_', f'{major_version}.latest_', src.name)
        target_path = version_dir / target_name
        if not target_path.exists():
            try:
                shutil.copy2(src, target_path)
                logger.info(f"Created latest file: {target_path.name}")
                created.append(target_path)
            except Exception as e:
                logger.error(f"Failed to create latest file {target_path.name}: {e}")
    return created

def main():
    parser = argparse.ArgumentParser(description="Upload BYOND builds and site to Cloudflare R2.")
    parser.add_argument('--skip-existing', action='store_true', default=True, 
                       help='Skip files that already exist in R2 (default: True)')
    parser.add_argument('--force', action='store_true', 
                       help='Upload all files even if they exist (opposite of --skip-existing)')
    parser.add_argument('--html-only', action='store_true', 
                       help='Only upload HTML/text files, skip binaries')
    parser.add_argument('--binaries-only', action='store_true', 
                       help='Only upload binary files, skip HTML/text')
    args = parser.parse_args()
    
    skip_existing = not args.force if args.force else args.skip_existing
    
    logger.info("Starting R2 upload")
    logger.info(f"Skip existing: {skip_existing}")
    
    try:
        client = get_r2_client()
    except RuntimeError as e:
        logger.error(str(e))
        return 1
    
    public_dir = Path("public")
    if not public_dir.exists():
        logger.error(f"Public directory not found: {public_dir}")
        return 1
    
    total_successful = 0
    total_failed = 0
    
    # Upload root files (index.html, version.txt)
    if not args.binaries_only:
        logger.info("Uploading root files...")
        for file_path in public_dir.glob("*"):
            if file_path.is_file():
                cache_control = cache_control_for_file(file_path)
                # Always force upload index.html and version.txt since they may have new versions listed
                force = file_path.suffix in {'.html', '.txt'}
                if upload_file_to_r2(client, file_path, file_path.name, skip_existing=skip_existing, cache_control=cache_control, force_upload=force):
                    total_successful += 1
                else:
                    total_failed += 1
    
    # Upload version directories
    for version in BASE_VERSIONS:
        version_dir = public_dir / version
        if not version_dir.exists():
            logger.warning(f"Version directory not found: {version_dir}")
            continue
        
        logger.info(f"Uploading version {version}...")
        # Ensure .latest_ copies exist locally so they can be uploaded/overwritten
        ensure_latest_files(version_dir, version)
        
        # Upload HTML files first (always force since they change with each new build)
        if not args.binaries_only:
            for file_path in version_dir.glob("*.html"):
                key = f"{version}/{file_path.name}"
                cache_control = cache_control_for_file(file_path)
                if upload_file_to_r2(client, file_path, key, skip_existing=skip_existing, cache_control=cache_control, force_upload=True):
                    total_successful += 1
                else:
                    total_failed += 1
        
        # Upload binaries
        if not args.html_only:
            for file_path in version_dir.iterdir():
                if file_path.is_file() and is_build_filename(file_path.name):
                    key = f"{version}/{file_path.name}"
                    cache_control = cache_control_for_file(file_path)
                    # Always force-upload "latest" build files so the public "latest" isn't stale
                    force_upload = is_latest_filename(file_path.name)
                    if upload_file_to_r2(client, file_path, key, skip_existing=skip_existing, cache_control=cache_control, force_upload=force_upload):
                        total_successful += 1
                    else:
                        total_failed += 1
    
    logger.info(f"Upload complete: {total_successful} successful, {total_failed} failed")
    return 0 if total_failed == 0 else 1

if __name__ == "__main__":
    exit(main())
