from curl_cffi import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import time
import re
import zipfile
import concurrent.futures
import os

# --- CONFIGURATION ---
COMIC_URL = "https://comix.to/title/emrmx-lookism?group=9375"
START_CHAPTER = 366
END_CHAPTER = 367 

MAX_RETRIES = 5
OUTPUT_DIR = "CBZ_Files"

MAX_CONCURRENT_CHAPTERS = 3
MAX_THREADS_PER_CHAPTER = 5

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

HTML_HEADERS = {
    "User-Agent": USER_AGENT
}

def fetch_url(url, is_image=False):
    headers = HTML_HEADERS.copy()
    if is_image:
        headers.update({
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://comix.to/",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site"
        })
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, impersonate="chrome110", timeout=30)
            if response.status_code == 200:
                return response.content if is_image else response.text
        except Exception:
            time.sleep(2)
    return None

def extract_chapter_number(url):
    match = re.search(r'chapter-([\d.]+)', url)
    if match:
        return float(match.group(1))
    return -1

def format_chapter_name(num):
    if num.is_integer():
        return f"{int(num):04d}"
    parts = str(num).split('.')
    return f"{int(parts[0]):04d}.{parts[1]}"

def get_all_chapter_links():
    chapter_links = set()
    print("🤖 Starting Playwright to dynamically extract chapter URLs...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        page.goto(COMIC_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(".chap-list a.title", timeout=15000)
        except Exception:
            print("❌ Failed to find chapter list.")
            browser.close()
            return []

        page_num = 1
        while True:
            print(f"📖 Scraping chapter list page {page_num}...")
            elements = page.query_selector_all(".chap-list a.title")
            if not elements:
                break

            first_href = elements[0].get_attribute("href")

            for el in elements:
                href = el.get_attribute("href")
                if href:
                    if href.startswith("/"):
                        href = "https://comix.to" + href
                    chapter_links.add(href)

            next_locator = page.locator("nav.navigation a.page-link:has(i.fa-angle-right)").first
            if next_locator.count() == 0:
                break

            li_class = next_locator.evaluate("el => el.parentElement.className")
            if "disabled" in li_class:
                break

            next_locator.evaluate("el => el.click()")
            page_num += 1

            try:
                page.wait_for_function(
                    f"() => document.querySelector('.chap-list a.title') && document.querySelector('.chap-list a.title').getAttribute('href') !== '{first_href}'",
                    timeout=10000
                )
                time.sleep(0.5)
            except Exception:
                break

        browser.close()

    links = list(chapter_links)
    links.sort(key=extract_chapter_number)
    return links

def download_image(args):
    idx, img_url = args
    img_data = fetch_url(img_url, is_image=True)
    ext = ".png" if ".png" in img_url.lower() else ".webp" if ".webp" in img_url.lower() else ".jpg"
    return idx, ext, img_data

def process_chapter(chapter_url):
    chapter_num = extract_chapter_number(chapter_url)
    if START_CHAPTER and chapter_num < START_CHAPTER: return
    if END_CHAPTER and chapter_num > END_CHAPTER: return

    ch_str = format_chapter_name(chapter_num)
    cbz_filename = os.path.join(OUTPUT_DIR, f"Lookism_Chapter_{ch_str}.cbz")

    if os.path.exists(cbz_filename):
        print(f"⏭️ Chapter {ch_str} already exists. Skipping.")
        return

    html_content = fetch_url(chapter_url, is_image=False)
    if not html_content:
        print(f"❌ Failed to fetch HTML for Chapter {ch_str}.")
        return

    image_urls = []

    # 1. Extract from Next.js payload (Regex)
    images_block_match = re.search(r'(?:\\"|")images(?:\\"|"):\s*\[(.*?)\]', html_content)
    if images_block_match:
        extracted_urls = re.findall(r'(?:\\"|")url(?:\\"|"):\s*(?:\\"|")(https?://.*?)(?:\\"|")', images_block_match.group(1))
        image_urls = [u.replace('\\/', '/') for u in extracted_urls]

    # 2. Fallback to BeautifulSoup if it was server-side rendered normally
    if not image_urls:
        soup = BeautifulSoup(html_content, "html.parser")
        for img in soup.select(".read-viewer .page img, .read-viewer img"):
            src = img.get("data-src") or img.get("src")
            if src:
                image_urls.append(src.strip())

    if not image_urls:
        print(f"❌ No images found for Chapter {ch_str}.")
        return

    image_tasks = [(idx + 1, url) for idx, url in enumerate(image_urls)]
    successful_pages = 0

    with zipfile.ZipFile(cbz_filename, 'w', zipfile.ZIP_STORED) as cbz_file:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS_PER_CHAPTER) as executor:
            for idx, ext, img_data in executor.map(download_image, image_tasks):
                if img_data:
                    filename = f"Page_{idx:03d}{ext}"
                    cbz_file.writestr(filename, img_data)
                    successful_pages += 1
                    
    print(f"✅ Chapter {ch_str} successfully downloaded & zipped! ({successful_pages}/{len(image_urls)} pages)")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    all_links = get_all_chapter_links()
    print(f"\n🔍 Total unique chapters found: {len(all_links)}")

    links_to_process = []
    for link in all_links:
        cnum = extract_chapter_number(link)
        if cnum < 0: continue
        if START_CHAPTER and cnum < START_CHAPTER: continue
        if END_CHAPTER and cnum > END_CHAPTER: continue
        links_to_process.append(link)

    print(f"🚀 Chapters to process after filtering: {len(links_to_process)}\n")

    if not links_to_process:
        print("🛑 No chapters in the defined range to download.")
        return

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHAPTERS) as executor:
        executor.map(process_chapter, links_to_process)

    print("\n🎉 All done! Ready for GitHub to zip the files.")

if __name__ == "__main__":
    main()
