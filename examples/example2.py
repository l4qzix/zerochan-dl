import io
import time
import requests
from PIL import Image
from zerochan_dl import ZerochanClient


WEBHOOK_URL = "XXXXXX"
DISCORD_FILE_LIMIT = 20 * 1024 * 1024

def resize_image_to_limit(image_bytes: io.BytesIO, max_size=DISCORD_FILE_LIMIT) -> io.BytesIO:
    image_bytes.seek(0)
    img = Image.open(image_bytes)
    fmt = img.format
    quality = 95
    output = io.BytesIO()
    img.save(output, format=fmt, quality=quality)
    size = output.tell()
    if size <= max_size:
        output.seek(0)
        return output

    scale = 0.9
    while size > max_size and quality > 30:
        quality -= 5
        output = io.BytesIO()
        img.save(output, format=fmt, quality=quality, optimize=True)
        size = output.tell()
        if size <= max_size:
            break
        if scale > 0.3:
            new_size = (int(img.width * scale), int(img.height * scale))
            img_resized = img.resize(new_size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            img_resized.save(output, format=fmt, quality=quality, optimize=True)
            size = output.tell()
            scale -= 0.1
    output.seek(0)
    return output

def send_to_discord(image_bytes, filename, content=""):
    adjusted = resize_image_to_limit(image_bytes)
    files = {"file": (filename, adjusted, "image/jpeg")}
    data = {"content": content}
    resp = requests.post(WEBHOOK_URL, data=data, files=files)
    resp.raise_for_status()

def main():
    client = ZerochanClient(username="XXXXXX",impersonate="chrome")
    client.authorize(z_hash="XXXXXXX", z_id="XXXXXX")
    search_tags = ["scan", "Suzumiya Haruhi no Yuuutsu"]
    max_images = 10
    count = 0

    for item in client.iter_search(search_tags, max_pages=5, limit=50):
        if count >= max_images:
            break
        try:
            entry = client.get_entry(item["id"])
            print(f"[{count+1}] #{entry.id} 処理中...")
            resp = client.session.get(entry.full_image_url)
            resp.raise_for_status()
            image_bytes = io.BytesIO(resp.content)
            send_to_discord(
                image_bytes,
                filename=entry.filename,
                content=f"Zerochan #{entry.id}\nタグ: {', '.join(entry.tags[:5])}"
            )
            count += 1
            time.sleep(0.6)  # Discord レート制限対策
        except Exception as e:
            print(f"スキップ: {e}")
            continue
    print("完了")

if __name__ == "__main__":
    main()
