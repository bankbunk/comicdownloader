import requests
from bs4 import BeautifulSoup
import time
import re
import zipfile
import concurrent.futures

# --- CONFIGURATION ---
MANGA_BASE_URL = "https://manhwatop.com/manga/lookism-manhwa-series-manhwa/chapter-"
START_CHAPTER = 40
END_CHAPTER = 600  # Set to None to download until the end
OUTPUT_FILE = f"Lookism_{START_CHAPTER}_to_{END_CHAPTER if END_CHAPTER else 'End'}.cbz"

GATEWAY_URL = "https://gateway.niko2nio2.workers.dev/?url="
MAX_RETRIES = 5
MAX_THREADS = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def fetch_with_retries(target_url, is_binary=False):
    gateway_link = f"{GATEWAY_URL}{target_url}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(gateway_link, headers=HEADERS, timeout=(10, 60))
            response.raise_for_status()
            return response.content if is_binary else response.text
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"\n    [Error fetching {target_url}]: {e}")
            time.sleep(2)
    return None

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

def download_image(args):
    idx, img_url = args
    img_data = fetch_with_retries(img_url, is_binary=True)
    ext = ".png" if ".png" in img_url.lower() else ".webp" if ".webp" in img_url.lower() else ".jpg"
    return idx, ext, img_data

def main():
    current_url = f"{MANGA_BASE_URL}{START_CHAPTER}/"
    chapters_downloaded = 0

    print(f"Starting download to {OUTPUT_FILE}...\n")
    
    with zipfile.ZipFile(OUTPUT_FILE, 'a', zipfile.ZIP_STORED) as cbz_file:
        
        while current_url:
            match = re.search(r'chapter-(\d+)', current_url)
            current_chapter_num = int(match.group(1)) if match else START_CHAPTER

            if END_CHAPTER and current_chapter_num > END_CHAPTER:
                print(f"\nReached target end chapter ({END_CHAPTER}). Stopping.")
                break

            print(f"Processing Chapter {current_chapter_num}... ", end="", flush=True)
            
            html_content = fetch_with_retries(current_url, is_binary=False)
            if not html_content:
                print("Failed to fetch chapter HTML. Stopping.")
                break

            soup = BeautifulSoup(html_content, "html.parser")
            images = soup.find_all("img", class_=re.compile(r"wp-manga-chapter-img"))
            
            if not images:
                print("No images found! Site structure may have changed.")
                break

            image_tasks = []
            for idx, img in enumerate(images):
                img_url = img.get("data-src") or img.get("src")
                if img_url:
                    image_tasks.append((idx + 1, img_url.strip()))

            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                for idx, ext, img_data in executor.map(download_image, image_tasks):
                    if img_data:
                        filename = f"Chapter_{current_chapter_num:04d}/Page_{idx:03d}{ext}"
                        cbz_file.writestr(filename, img_data)

            chapters_downloaded += 1
            print(f"Done! (Total downloaded: {chapters_downloaded})")

            next_url = get_next_chapter(soup, current_url)
            if not next_url or next_url == current_url:
                print("\nNo next chapter found. Reached the end.")
                break
                
            current_url = next_url

    print(f"\nFinished! Saved {chapters_downloaded} chapters to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
