import requests
from curl_cffi import requests as c_requests
from bs4 import BeautifulSoup
import time
import re
import zipfile
import concurrent.futures
import os

# --- CONFIGURATION ---
MANGA_BASE_URL = "https://manhwatop.com/manga/lookism-manhwa-series-manhwa/chapter-"
START_CHAPTER = 40
END_CHAPTER = None  

GATEWAY_URL = "https://gateway.niko2nio2.workers.dev/?url="
MAX_RETRIES = 5
OUTPUT_DIR = "CBZ_Files"

MAX_CONCURRENT_CHAPTERS = 5
MAX_THREADS_PER_CHAPTER = 10

# Headers for the HTML (Gateway)
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Strict headers for the CDN Images
IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://manhwatop.com/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site"
}

def fetch_html(target_url):
    gateway_link = f"{GATEWAY_URL}{target_url}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(gateway_link, headers=HTML_HEADERS, timeout=(10, 60))
            response.raise_for_status()
            return response.text
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"\n    [Error fetching HTML {target_url}]: {e}")
            time.sleep(2)
    return None

def download_image(args):
    idx, img_url = args
    ext = ".png" if ".png" in img_url.lower() else ".webp" if ".webp" in img_url.lower() else ".jpg"
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Using curl_cffi to spoof Chrome's TLS fingerprint for the CDN
            response = c_requests.get(img_url, headers=IMAGE_HEADERS, impersonate="chrome110", timeout=60)
            if response.status_code == 200:
                return idx, ext, response.content
            elif response.status_code == 403 and attempt == MAX_RETRIES:
                print(f"\n    [403 Forbidden] Failed to download: {img_url}")
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"\n    [Error downloading {img_url}]: {e}")
        time.sleep(2)
        
    return idx, ext, None

def get_next_chapter(soup, current_url):
    next_btn = soup.select_one(".nav-next a, a.next_page")
    if next_btn and next_btn.get("href"):
        return next_btn["href"]
    match = re.search(r'(chapter-)(\d+)', current_url)
    if match:
        prefix = match.group(1)
        num = int(match.group(2))
        return current_url.replace(f"{prefix}{num}", f"{prefix}{num+1}")
    return None

def process_chapter_images(chapter_num, image_urls):
    cbz_filename = os.path.join(OUTPUT_DIR, f"Lookism_Chapter_{chapter_num:04d}.cbz")
    image_tasks = [(idx + 1, url) for idx, url in enumerate(image_urls)]
    successful_pages = 0

    with zipfile.ZipFile(cbz_filename, 'w', zipfile.ZIP_STORED) as cbz_file:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_PER_CHAPTER) as executor:
            for idx, ext, img_data in executor.map(download_image, image_tasks):
                if img_data:
                    filename = f"Page_{idx:03d}{ext}"
                    cbz_file.writestr(filename, img_data)
                    successful_pages += 1
                    
    print(f"✅ Chapter {chapter_num} saved! ({successful_pages} pages)")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    current_url = f"{MANGA_BASE_URL}{START_CHAPTER}/"
    current_chapter_num = START_CHAPTER
    chapter_image_urls = []
    
    print("Starting hyper-fast HTML scraping & background downloading...\n")

    chapter_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHAPTERS)
    active_futures = []

    while current_url:
        match = re.search(r'chapter-(\d+)', current_url)
        extracted_num = int(match.group(1)) if match else current_chapter_num

        if END_CHAPTER and extracted_num > END_CHAPTER:
            print(f"\nReached target end chapter ({END_CHAPTER}).")
            break

        if extracted_num != current_chapter_num:
            if chapter_image_urls:
                active_futures.append(
                    chapter_executor.submit(process_chapter_images, current_chapter_num, chapter_image_urls)
                )
            current_chapter_num = extracted_num
            chapter_image_urls = []

        print(f"🔍 Scraping HTML for: {current_url}")
        
        html_content = fetch_html(current_url)
        if not html_content:
            print(f"Failed to fetch HTML for {current_url}.")
            break

        soup = BeautifulSoup(html_content, "html.parser")
        images = soup.find_all("img", class_=re.compile(r"wp-manga-chapter-img"))
        
        if not images:
            print("No images found! Site structure may have changed.")
            break

        for img in images:
            img_url = img.get("data-src") or img.get("src")
            if img_url:
                chapter_image_urls.append(img_url.strip())

        next_url = get_next_chapter(soup, current_url)
        if not next_url or next_url == current_url:
            print("\nNo next chapter found. Reached the end.")
            break
            
        current_url = next_url

    if chapter_image_urls:
        active_futures.append(
            chapter_executor.submit(process_chapter_images, current_chapter_num, chapter_image_urls)
        )

    print("\n✅ All HTML scraped! Waiting for background downloads to finish...")
    concurrent.futures.wait(active_futures)
    print("🎉 All done! Ready for zipping.")

if __name__ == "__main__":
    main()
