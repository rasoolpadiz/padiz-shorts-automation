# -*- coding: utf-8 -*-
"""Canonical niche lists for Padiz Studio long-form content.

SOURCE OF TRUTH: written by the channel owner (rasoolpadiz) on 2026-09-30.
Both lists live here so the daily GitHub Actions run (run_long_daily.py) and any
future topic generation always draw from these categories - never invent new ones
outside these lists.

English niches (~80) - ordered roughly by CPM potential:
AI, Technology, Money, Finance, Business, Entrepreneurship, Psychology,
Human Behavior, Science, Space, History, Mystery, True Crime, Survival, Health,
Fitness, Self Improvement, Motivation, Education, Interesting Facts, Weird Facts,
Animals, Nature, Travel, Geography, Food, Cooking, Gaming, Sports, Football,
Basketball, Movies, TV Shows, Entertainment, Celebrity Stories, Pop Culture,
Internet Culture, Social Media, Relationships, Dating, Love, Life Hacks,
Productivity, Career, Jobs, Coding, Software, Cybersecurity, Future Technology,
Robotics, Cars, Luxury, Real Estate, Investing, Cryptocurrency, Marketing,
E-commerce, Startups, Inventions, Ancient Civilizations, Archaeology, Ancient
Technology, Military History, World Records, Disasters, Natural Phenomena,
Human Body, Medical Science, Space Discoveries, Ocean Mysteries, Conspiracy
Theories, Unsolved Mysteries, Horror Stories, Dark History, Fascinating Stories,
Incredible Discoveries, Micro Dramas, Short Stories, Moral Stories, Philosophy,
Personal Development, Communication, Social Skills, Wealth, Success Stories

Persian niches (19) - all Iran-focused or Iran-referenced:
1.  ایران و تاریخ ایران
2.  حقایق عجیب ایران
3.  مهاجرت و زندگی خارج از ایران
4.  پول و اقتصاد روزمره
5.  هوش مصنوعی و تکنولوژی
6.  روانشناسی و رفتار انسان
7.  عجایب و رازهای حل‌نشده
8.  علم و فضا
9.  جغرافیا و کشورهای جهان
10. فرهنگ و آداب ایرانی
11. فوتبال و ورزش
12. سینما و سریال
13. داستان‌های واقعی
14. جنایت و پرونده‌های معمایی
15. تاریخ تاریک و اتفاقات عجیب تاریخی
16. موفقیت و ثروت
17. کسب‌وکار و درآمد اینترنتی
18. مقایسه ایران با جهان
19. ایران‌شناسی و مناطق ناشناخته
"""

EN_NICHES = [
    "AI", "Technology", "Money", "Finance", "Business", "Entrepreneurship",
    "Psychology", "Human Behavior", "Science", "Space", "History", "Mystery",
    "True Crime", "Survival", "Health", "Fitness", "Self Improvement",
    "Motivation", "Education", "Interesting Facts", "Weird Facts", "Animals",
    "Nature", "Travel", "Geography", "Food", "Cooking", "Gaming", "Sports",
    "Football", "Basketball", "Movies", "TV Shows", "Entertainment",
    "Celebrity Stories", "Pop Culture", "Internet Culture", "Social Media",
    "Relationships", "Dating", "Love", "Life Hacks", "Productivity", "Career",
    "Jobs", "Coding", "Software", "Cybersecurity", "Future Technology",
    "Robotics", "Cars", "Luxury", "Real Estate", "Investing", "Cryptocurrency",
    "Marketing", "E-commerce", "Startups", "Inventions", "Ancient Civilizations",
    "Archaeology", "Ancient Technology", "Military History", "World Records",
    "Disasters", "Natural Phenomena", "Human Body", "Medical Science",
    "Space Discoveries", "Ocean Mysteries", "Conspiracy Theories",
    "Unsolved Mysteries", "Horror Stories", "Dark History",
    "Fascinating Stories", "Incredible Discoveries", "Micro Dramas",
    "Short Stories", "Moral Stories", "Philosophy", "Personal Development",
    "Communication", "Social Skills", "Wealth", "Success Stories",
]

FA_NICHES = [
    "ایران و تاریخ ایران",
    "حقایق عجیب ایران",
    "مهاجرت و زندگی خارج از ایران",
    "پول و اقتصاد روزمره",
    "هوش مصنوعی و تکنولوژی",
    "روانشناسی و رفتار انسان",
    "عجایب و رازهای حل‌نشده",
    "علم و فضا",
    "جغرافیا و کشورهای جهان",
    "فرهنگ و آداب ایرانی",
    "فوتبال و ورزش",
    "سینما و سریال",
    "داستان‌های واقعی",
    "جنایت و پرونده‌های معمایی",
    "تاریخ تاریک و اتفاقات عجیب تاریخی",
    "موفقیت و ثروت",
    "کسب‌وکار و درآمد اینترنتی",
    "مقایسه ایران با جهان",
    "ایران‌شناسی و مناطق ناشناخته",
]

# Niches that already have a published topic (topic id -> niche) - used to avoid repeats.
# Filled in as topics are written; the daily runner reads it via counts in posted_long.json.
NICHE_ROTATION_HINT = {
    "en": ["Money", "Psychology", "AI", "Ancient Civilizations", "Unsolved Mysteries",
           "Human Body", "Ancient Technology", "Space Discoveries", "Success Stories"],
    "fa": ["پول و اقتصاد روزمره", "ایران و تاریخ ایران", "عجایب و رازهای حل‌نشده",
           "فرهنگ و آداب ایرانی", "حقایق عجیب ایران"],
}
