import os
import re
import time
import logging
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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

# Define the regex pattern to match executable files
FILE_PATTERN = r'\d+\.\d+_byond\.exe'

def get_available_builds(version):
    """Get list of available build files from BYOND website"""
    url = BASE_URLS.get(version)
    if not url:
        logger.error(f"Unknown version: {version}")
        return []
    
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        browser = webdriver.Chrome(options=options)
        browser.get(url)
        
        # Wait for anchors to appear
        WebDriverWait(browser, 15).until(EC.presence_of_element_located((By.TAG_NAME, "a")))
        
        links = browser.find_elements(By.TAG_NAME, "a")
        files = []
        for link in links:
            file_name = link.text.strip()
            if re.search(f"{version}\\.\\d+_byond\\.exe", file_name):
                files.append(file_name)
        browser.quit()
        return files
    except Exception as e:
        logger.error(f"Error fetching build list for version {version}: {str(e)}")
        return []

def download_file(url, target_path):
    logger.info(f"Downloading via Selenium: {url}")
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        prefs = {
            "download.default_directory": str(os.path.dirname(target_path)),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True
        }
        options.add_experimental_option("prefs", prefs)
        browser = webdriver.Chrome(options=options)
        browser.get(url)
        
        # Wait briefly for download to complete
        time.sleep(5)
        browser.quit()
        logger.info(f"Downloaded {url} to {target_path}")
        return True
    except Exception as e:
        logger.error(f"Error downloading {url}: {str(e)}")
        return False

def download_builds():
    """Main function to download BYOND builds"""
    output_dir = Path("public")
    output_dir.mkdir(exist_ok=True)
    
    for version in BASE_URLS:
        version_dir = output_dir / version
        version_dir.mkdir(exist_ok=True)
        
        # Track existing files to avoid re-downloading
        existing_files = set(f.name for f in version_dir.glob("*"))
        logger.info(f"Found {len(existing_files)} existing files in {version_dir}")
        
        builds = get_available_builds(version)
        logger.info(f"Found {len(builds)} builds available for version {version}")
          # Download new files
        for file_name in builds:
            if file_name in existing_files:
                logger.info(f"File {file_name} already exists, skipping")
                continue
                
            url = f"{BASE_URLS[version]}{file_name}"
            target_path = str(version_dir / file_name)
            
            logger.info(f"Downloading {url} to {target_path}")
            success = download_file(url, target_path)
            
            if success:
                logger.info(f"Successfully downloaded {file_name}")
            else:
                logger.error(f"Failed to download {file_name}")
                
            # Be nice to the server
            time.sleep(1)

if __name__ == "__main__":
    logger.info("Starting BYOND builds download")
    download_builds()
    logger.info("Finished BYOND builds download")
