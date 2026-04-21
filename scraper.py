from curl_cffi import requests
from bs4 import BeautifulSoup
import time
import re
import zipfile
import concurrent.futures
import os

# --- CONFIGURATION ---
MANGA_BASE_URL = "https://manhwatop.com/manga/lookism-manhwa-series-manhwa/chapter-"
START_CHAPTER = 401
END_CHAPTER = 500  

MAX_RETRIES = 5
OUTPUT_DIR = "CBZ_Files"

# LOWERED SPEED to prevent DDoS IP bans from the server
MAX_CONCURRENT_CHAPTERS = 2
MAX_THREADS_PER_CHAPTER = 5

# Browser Headers
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://manhwatop.com/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site"
}

def fetch_url(url, is_image=False):
    headers = IMAGE_HEADERS if is_image else HTML_HEADERS
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, impersonate="chrome110", timeout=30)
            if response.status_code == 200:
                return response.content if is_image else response.text
        except Exception:
            time.sleep(2)
    return None

def get_next_chapter(soup, current_url):
    next_btn = soup.select_one(".nav-next a, a.next_page")
    if next_btn and next_btn.get("href"):
        return next_btn["href"]
    
    match = re.search(r'chapter-([\d.]+)', current_url)
    if match:
        prefix = current_url.split(match.group(0))[0] + "chapter-"
        num = float(match.group(1))
        next_num = int(num + 1) if num.is_integer() else num + 1
        return f"{prefix}{next_num}/"
    return None

def format_chapter_name(num):
    if num.is_integer():
        return f"{int(num):04d}"
    parts = str(num).split('.')
    return f"{int(parts[0]):04d}.{parts[1]}"

def download_image(args):
    idx, img_url = args
    img_data = fetch_url(img_url, is_image=True)
    ext = ".png" if ".png" in img_url.lower() else ".webp" if ".webp" in img_url.lower() else ".jpg"
    return idx, ext, img_data

def process_chapter_images(chapter_num, image_urls):
    ch_str = format_chapter_name(chapter_num)
    cbz_filename = os.path.join(OUTPUT_DIR, f"Lookism_Chapter_{ch_str}.cbz")
    
    image_tasks = [(idx + 1, url) for idx, url in enumerate(image_urls)]
    successful_pages = 0

    with zipfile.ZipFile(cbz_filename, 'w', zipfile.ZIP_STORED) as cbz_file:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_PER_CHAPTER) as executor:
            for idx, ext, img_data in executor.map(download_image, image_tasks):
                if img_data:
                    filename = f"Page_{idx:03d}{ext}"
                    cbz_file.writestr(filename, img_data)
                    successful_pages += 1
                    
    print(f"✅ Chapter {ch_str} successfully downloaded & zipped! ({successful_pages} pages)")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    current_url = f"{MANGA_BASE_URL}{START_CHAPTER}/"
    
    current_chapter_num = float(START_CHAPTER)
    chapter_image_urls = []
    
    print("Starting balanced multi-threaded downloads...\n")

    chapter_executor = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHAPTERS)
    active_futures = []

    while current_url:
        match = re.search(r'chapter-([\d.]+)', current_url)
        extracted_num = float(match.group(1)) if match else current_chapter_num

        if END_CHAPTER and extracted_num > float(END_CHAPTER):
            print(f"\n🛑 Reached target end chapter ({END_CHAPTER}).")
            break

        if extracted_num != current_chapter_num:
            if chapter_image_urls:
                active_futures.append(
                    chapter_executor.submit(process_chapter_images, current_chapter_num, chapter_image_urls)
                )
            current_chapter_num = extracted_num
            chapter_image_urls = []
        
        html_content = fetch_url(current_url, is_image=False)
        if not html_content:
            print(f"❌ Failed to fetch HTML for Chapter {format_chapter_name(current_chapter_num)}.")
            break

        soup = BeautifulSoup(html_content, "html.parser")
        images = soup.find_all("img", class_=re.compile(r"wp-manga-chapter-img"))
        
        if not images:
            print(f"❌ No images found for Chapter {format_chapter_name(current_chapter_num)}.")
            break

        for img in images:
            img_url = img.get("data-src") or img.get("src")
            if img_url:
                chapter_image_urls.append(img_url.strip())

        next_url = get_next_chapter(soup, current_url)
        if not next_url or next_url == current_url:
            print("\n🛑 No next chapter found. Reached the end.")
            break
            
        current_url = next_url
        
        # ARTIFICIAL DELAY: Prevents the scraper from triggering anti-bot firewalls
        time.sleep(1)

    if chapter_image_urls:
        active_futures.append(
            chapter_executor.submit(process_chapter_images, current_chapter_num, chapter_image_urls)
        )

    print("\n⏳ All HTML scraped! Waiting for the last background downloads to finish...")
    concurrent.futures.wait(active_futures)
    print("🎉 All done! Ready for GitHub to zip the files.")

if __name__ == "__main__":
    main()
