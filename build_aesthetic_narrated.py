import os, asyncio, subprocess, shutil, edge_tts
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

BASE_DIR = r"C:\youtube_pipeline"
FONT_PATH = os.path.join(BASE_DIR, "Vazirmatn-Bold.ttf")
OUT_DIR = os.path.join(BASE_DIR, "aesthetic_build")
BG_MUSIC = os.path.join(BASE_DIR, "sad_aesthetic_bg.mp3")
FINAL_OUT = os.path.join(BASE_DIR, "aesthetic_dark_short_final.mp4")
DESKTOP_OUT = r"C:\Users\Allah\Desktop\aesthetic_dark_short_final.mp4"

os.makedirs(OUT_DIR, exist_ok=True)

slides_data = [
    {
        "sub": "فلسفه سکوت",
        "title": "چرا آدما یهو ساکت میشن؟",
        "text": "وقتی متوجه میشی حرف زدن\nهیچ تغییری ایجاد نمیکنه،\nآرامش سکوت رو به هر بحثی ترجیح میدی.",
        "speech": "وقتی متوجه میشی توضیح دادن هیچ تغییری ایجاد نمیکنه، کم‌کم سکوت رو به هر بحث و جوابی ترجیح میدی."
    },
    {
        "sub": "حقیقت تلخ",
        "title": "سنگینی تظاهر",
        "text": "آدم‌ها از تنهایی خسته نمیشن،\nبلکه از تظاهر به خوب بودن\nکنار کسانی که نمیفهمنشون خسته میشن.",
        "speech": "آدم‌ها از تنهایی خسته نمیشن، بلکه از تظاهر به خوب بودن خسته میشن، مخصوصاً کنار کسانی که هیچ‌وقت واقعاً نمیفهمنشون."
    },
    {
        "sub": "بهای رشد",
        "title": "تاریک‌ترین شب",
        "text": "هر کسی که امروز قویه،\nیه روزی تو تاریک‌ترین نقطه زندگیش\nهیچ پناهی جز خودش نداشته.",
        "speech": "هر کسی رو دیدی که امروز قوی و مستقله، بدون یه روزی توی تاریک‌ترین شب زندگیش، هیچ پناهی جز خودش نداشته."
    }
]

def prep(t: str) -> str:
    return get_display(arabic_reshaper.reshape(t))

def main():
    clip_files = []
    total = len(slides_data)

    for idx, s in enumerate(slides_data, start=1):
        img = Image.new("RGB", (1080, 1920), color=(10, 12, 16))
        draw = ImageDraw.Draw(img)

        card_margin = 75
        card_top = 430
        card_bottom = 1470
        draw.rounded_rectangle(
            [(card_margin, card_top), (1080 - card_margin, card_bottom)],
            radius=36, fill=(17, 21, 28), outline=(33, 40, 52), width=2
        )

        draw.rounded_rectangle([(540 - 30, card_top + 45), (540 + 30, card_top + 51)], radius=3, fill=(100, 116, 139))

        f_sub = ImageFont.truetype(FONT_PATH, 34)
        draw.text((540, card_top + 105), prep(s["sub"]), font=f_sub, fill=(148, 163, 184), anchor="mm")

        f_title = ImageFont.truetype(FONT_PATH, 54)
        draw.text((540, card_top + 210), prep(s["title"]), font=f_title, fill=(248, 250, 252), anchor="mm")

        draw.line([(card_margin + 70, card_top + 285), (1080 - card_margin - 70, card_top + 285)], fill=(38, 47, 60), width=2)

        f_text = ImageFont.truetype(FONT_PATH, 44)
        lines = s["text"].split("\n")
        start_y = card_top + 410
        for l_idx, line in enumerate(lines):
            draw.text((540, start_y + (l_idx * 76)), prep(line), font=f_text, fill=(203, 213, 225), anchor="mm")

        f_ind = ImageFont.truetype(FONT_PATH, 30)
        draw.text((540, card_bottom - 60), prep(f"{idx} از {total}"), font=f_ind, fill=(100, 116, 139), anchor="mm")

        f_brand = ImageFont.truetype(FONT_PATH, 32)
        draw.text((540, 1680), prep("Padiz Studio | @padiz_studio"), font=f_brand, fill=(71, 85, 105), anchor="mm")

        img_path = os.path.join(OUT_DIR, f"slide_{idx}.png")
        img.save(img_path)

        audio_path = os.path.join(OUT_DIR, f"tts_{idx}.mp3")
        asyncio.run(edge_tts.Communicate(s["speech"], "fa-IR-FaridNeural", rate="-8%", pitch="-4Hz").save(audio_path))

        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            stdout=subprocess.PIPE, text=True, check=True
        )
        dur = float(res.stdout.strip()) + 0.6

        clip_path = os.path.join(OUT_DIR, f"clip_{idx}.mp4")
        clip_cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path, "-i", audio_path,
            "-t", f"{dur:.2f}", "-vf", "scale=1080:1920,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-shortest", clip_path
        ]
        subprocess.run(clip_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clip_files.append(clip_path)

    concat_txt = os.path.join(OUT_DIR, "concat.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for c in clip_files:
            safe = c.replace("\\", "/")
            f.write(f"file '{safe}'\n")

    speech_full = os.path.join(OUT_DIR, "speech_full.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", speech_full], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    mix_cmd = [
        "ffmpeg", "-y", "-i", speech_full,
        "-stream_loop", "-1", "-i", BG_MUSIC,
        "-filter_complex", "[0:a]volume=1.0[a0];[1:a]volume=0.22[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
        FINAL_OUT
    ]
    subprocess.run(mix_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.copy2(FINAL_OUT, DESKTOP_OUT)
    print("SUCCESS: Video created and saved to Desktop!")

if __name__ == "__main__":
    main()
