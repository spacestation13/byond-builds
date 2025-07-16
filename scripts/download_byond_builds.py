import os
import re
import time
import logging
import argparse
import tempfile
import shutil
import urllib.request
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
from selenium.webdriver.chrome.service import Service

def create_chrome_browser(tmpdirname=None):
    """Create a Selenium Chrome browser with options for headless use."""
    chrome_service = Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install())
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--safebrowsing-disable-download-protection')
    options = [
        "--headless",
        "--disable-gpu",
        "--window-size=1920,1200",
        "--ignore-certificate-errors",
        "--disable-extensions",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--start-maximized",
        "--no-sandbox",
        "--agressive-cache-discard",
        "--remote-debugging-port=9222",
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36 Edg/138.0.0.0 SS13 BYOND Mirror/1.0"
    ]
    for option in options:
        chrome_options.add_argument(option)
    if tmpdirname:
        prefs = {
            "download.default_directory": tmpdirname,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True
        }
        chrome_options.add_experimental_option("prefs", prefs)
    return webdriver.Chrome(service=chrome_service, options=chrome_options)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("download_byond.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("byond-mirror")

# Define the base URLs for BYOND builds
BASE_URLS = {
    '515': 'https://www.byond.com/download/build/515/',
    '516': 'https://www.byond.com/download/build/516/'
}

def get_available_builds(version, manual_pause=False):
    """Get list of available build files from BYOND website"""
    url = BASE_URLS.get(version)
    if not url:
        logger.error(f"Unknown version: {version}")
        return []
    try:
        browser = create_chrome_browser()
        browser.get(url)
        if manual_pause:
            input(f"\n[Manual Step] Please solve any CAPTCHAs or Cloudflare challenges in the browser window, then press Enter to continue...")
        # Wait for anchors to appear
        WebDriverWait(browser, 15).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
        links = browser.find_elements(By.TAG_NAME, "a")
        logger.info(f"Found {len(links)} anchor tags on the page for version {version}")
        files = []
        for link in links:
            file_name = link.text.strip()
            # Only match the specific file types we want: .exe, byond.zip, and byond_linux.zip
            if (file_name.endswith('_byond.exe') or
                file_name.endswith('_byond.zip') or
                file_name.endswith('_byond_linux.zip')):
                if re.search(f"{version}\\.\\d+_", file_name):  # Verify it's the right version
                    files.append(file_name)
        browser.quit()
        logger.info(f"Returning {len(files)} build files for version {version}: {files}")
        return files
    except Exception as e:
        logger.error(f"Error fetching build list for version {version}: {str(e)}")
        return []

def download_file(url, target_path, manual_pause=False, timeout=120):
    logger.info(f"Downloading via Selenium: {url}")
    try:
        # Use a unique temp directory for this download
        with tempfile.TemporaryDirectory() as tmpdirname:
            browser = create_chrome_browser(tmpdirname=tmpdirname)
            file_name = os.path.basename(target_path)
            browser.get(url)
            if manual_pause:
                input(f"\n[Manual Step] Please solve any CAPTCHAs or Cloudflare challenges in the browser window, then press Enter to continue...")
            start_time = time.time()
            final_path = os.path.join(tmpdirname, file_name)
            crdownload_path = final_path + ".crdownload"
            # Wait for download to start
            while not os.path.exists(final_path) and not os.path.exists(crdownload_path):
                if time.time() - start_time > timeout:
                    logger.error(f"Timeout waiting for download to start: {file_name}")
                    browser.quit()
                    return False
                time.sleep(0.1)
            # Wait for download to finish
            while os.path.exists(crdownload_path):
                if time.time() - start_time > timeout:
                    logger.error(f"Timeout waiting for download to finish: {file_name}")
                    browser.quit()
                    return False
                time.sleep(0.2)
            browser.quit()
            # Move file to target_path
            if os.path.exists(final_path):
                shutil.move(final_path, target_path)
                logger.info(f"Downloaded {url} to {target_path}")
                return True
            else:
                logger.error(f"Download failed or file not found: {final_path}")
                return False
    except Exception as e:
        logger.error(f"Error downloading {url}: {str(e)}")
        return False

def generate_version_index(version_dir: Path):
    """Generate a static index.html for a version directory listing all downloaded files."""
    # Find files with our specific patterns
    files = sorted(f for f in version_dir.iterdir() if
                   f.name.endswith('_byond.exe') or
                   f.name.endswith('_byond.zip') or
                   f.name.endswith('_byond_linux.zip'))
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "    <meta charset='UTF-8'>",
        f"    <title>BYOND Builds for {version_dir.name}</title>",
        "    <style>body{font-family:sans-serif;max-width:600px;margin:2em auto;}h1{font-size:1.5em;}ul{padding:0;}li{margin:8px 0;list-style:none;}a{color:#0366d6;text-decoration:none;}a:hover{text-decoration:underline;}</style>",
        "</head>",
        "<body>",
        f"    <h1>BYOND Builds for {version_dir.name}</h1>",
        "    <ul>"
    ]
    for f in files:
        html.append(f"        <li><a href='{f.name}'>{f.name}</a></li>")
    html.append("    </ul>")
    html.append("    <p style='font-size:0.9em;color:#666;margin-top:2em;'>This is a static listing generated automatically. Return to <a href='../index.html'>main mirror page</a>.</p>")
    html.append("</body>\n</html>")
    (version_dir / "index.html").write_text("\n".join(html), encoding="utf-8")

def download_version_txt(output_dir: Path):
    """Download version.txt from BYOND and save to output_dir/version.txt"""
    url = "https://www.byond.com/download/version.txt"
    target_path = output_dir / "version.txt"
    try:
        logger.info(f"Downloading {url} to {target_path}")
        with urllib.request.urlopen(url) as response:
            content = response.read()
            target_path.write_bytes(content)
        logger.info("version.txt downloaded successfully")
    except Exception as e:
        logger.error(f"Failed to download version.txt: {e}")

def parse_version_from_filename(filename):
    """Parse major and minor version from a BYOND build filename.
    
    Args:
        filename: Filename like '515.1605_byond.exe'
        
    Returns:
        tuple: (major_version, minor_version) or (None, None) if parsing fails
    """
    # Pattern to match: major.minor_byond.exe or major.minor_byond.zip or major.minor_byond_linux.zip
    pattern = r'(\d+)\.(\d+)_byond(?:\.exe|\.zip|_linux\.zip)'
    match = re.match(pattern, filename)
    if match:
        major_version = match.group(1)
        minor_version = int(match.group(2))  # Convert to int for comparison
        return major_version, minor_version
    return None, None

def copy_latest_build(version_dir: Path, major_version: str):
    """Copy the latest build file to a _latest.exe file based on minor version number.
    
    Args:
        version_dir: Directory containing the build files
        major_version: Major version string (e.g., '515')
    """
    # Find all build files in the directory
    build_files = []
    for file_path in version_dir.iterdir():
        if file_path.is_file():
            major, minor = parse_version_from_filename(file_path.name)
            if major == major_version and minor is not None:
                build_files.append((file_path, minor))
    
    if not build_files:
        logger.warning(f"No build files found for version {major_version}")
        return
    
    # Sort by minor version (descending) to get the latest
    build_files.sort(key=lambda x: x[1], reverse=True)
    latest_file, latest_minor = build_files[0]
    
    # Create the latest file name
    latest_filename = f"{major_version}_latest.exe"
    latest_path = version_dir / latest_filename
    
    try:
        # Copy the latest file
        shutil.copy2(latest_file, latest_path)
        logger.info(f"Copied {latest_file.name} (version {latest_minor}) to {latest_filename}")
    except Exception as e:
        logger.error(f"Failed to copy latest build: {e}")

def download_builds(manual_pause=False):
    """Main function to download BYOND builds"""
    output_dir = Path("public")
    output_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdirname:
        logger.info(f"Using temporary directory for downloads: {tmpdirname}")
        browser = create_chrome_browser(tmpdirname=tmpdirname)
        try:
            for version in BASE_URLS:
                version_dir = output_dir / version
                version_dir.mkdir(exist_ok=True)
                # generate_version_index(version_dir) # just use this here if you're manually downloading files

                # Track existing files to avoid re-downloading
                existing_files = set(f.name for f in version_dir.glob("*"))
                logger.info(f"Found {len(existing_files)} existing files in {version_dir}")
                builds = get_available_builds(version, manual_pause=manual_pause)
                logger.info(f"Found {len(builds)} builds available for version {version}")
                # Download new files
                for file_name in builds:
                    if file_name in existing_files:
                        logger.info(f"File {file_name} already exists, skipping")
                        continue
                    url = f"{BASE_URLS[version]}{file_name}"
                    target_path = str(version_dir / file_name)
                    logger.info(f"Downloading {url} to {target_path}")
                    browser.execute_script("window.open('about:blank', '_blank');")
                    browser.switch_to.window(browser.window_handles[-1])
                    browser.get(url)
                    if manual_pause:
                        input(f"\n[Manual Step] Please solve any CAPTCHAs or Cloudflare challenges in the browser window, then press Enter to continue...")
                    file_path = os.path.join(tmpdirname, file_name)
                    crdownload_path = file_path + ".crdownload"
                    start_time = time.time()
                    while not os.path.exists(file_path) and not os.path.exists(crdownload_path):
                        if time.time() - start_time > 120:
                            logger.error(f"Timeout waiting for download to start: {file_name}")
                            break
                        time.sleep(0.1)
                    while os.path.exists(crdownload_path):
                        if time.time() - start_time > 120:
                            logger.error(f"Timeout waiting for download to finish: {file_name}")
                            break
                        time.sleep(0.2)
                    browser.close()
                    browser.switch_to.window(browser.window_handles[0])
                    if os.path.exists(file_path):
                        shutil.move(file_path, target_path)
                        logger.info(f"Successfully downloaded {file_name}")
                    else:
                        logger.error(f"Failed to download {file_name}")
                    time.sleep(1.5)
                # Generate static index.html for this version
                generate_version_index(version_dir)
                # Copy the latest build to a _latest.exe file
                copy_latest_build(version_dir, version)
        finally:
            browser.quit()
    # Download version.txt after builds
    download_version_txt(output_dir)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download BYOND builds locally.")
    parser.add_argument('--manual-pause', action='store_true', help='Pause after opening browser for manual CAPTCHA/Cloudflare solving')
    args = parser.parse_args()
    logger.info("Starting BYOND builds download (local mode)")
    download_builds(manual_pause=args.manual_pause)
    logger.info("Finished BYOND builds download")
