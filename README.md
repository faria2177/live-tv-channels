# 🎬 FMFTP Auto Movie & Series Scanner

প্রতি **২ দিন** পর পর `fmftp.net` থেকে সব movie ও TV series collect করে GitHub-এ auto-push করে।

---

## 📁 Folder Structure

```
├── movies/
│   ├── Bollywood.json          (category=1)
│   ├── Hollywood.json          (category=2)
│   ├── Animation.json          (category=3)
│   ├── Korean.json             (category=4)
│   ├── Hindi_dubbed.json       (category=5)
│   ├── Horror.json             (category=6)
│   ├── Indian_Bangla.json      (category=7)
│   ├── Tamil.json              (category=8)
│   └── foreign.json            (category=14)
│
├── series/
│   ├── English_Tv_Series.json  (category=9)
│   ├── Indian_Tv_Series.json   (category=10)
│   ├── Korean_Tv_Series.json   (category=11)
│   ├── Bangla_Tv_Series.json   (category=12)
│   └── Turkish_Tv_Series.json  (category=13)
│
├── scan_summary.json            (last scan info)
├── fetch_data.py                (main scanner script)
└── .github/workflows/scan.yml  (auto-run schedule)
```

---

## 📄 JSON Output Format

### Movies (`movies/*.json`)
```json
{
  "type": "category_collection",
  "source_url": "https://fmftp.net/movies?category=1",
  "category_id": "1",
  "category_name": "Bollywood",
  "total_items": 350,
  "collected_at": "2026-05-26T10:00:00Z",
  "last_updated": "2026-05-28T10:00:00Z",
  "items": {
    "Movie Title": {
      "year": "2024",
      "tvg_logo": "https://fmftp.net/content-images/movies/posters/...",
      "rating": 7.5,
      "genre": ["Action", "Drama"],
      "links": [
        {
          "url": "https://fmftp.net/api/stream/video/stream?type=movies&id=123",
          "language": "Bollywood",
          "quality": "1080p",
          "watch_page": "https://fmftp.net/watch?type=MOVIE&id=123"
        }
      ]
    }
  }
}
```

### Series (`series/*.json`)
```json
{
  "type": "series_collection",
  "source_url": "https://fmftp.net/tv-shows?category=9",
  "category_id": "9",
  "category_name": "English TV Series",
  "total_items": 120,
  "collected_at": "2026-05-26T10:00:00Z",
  "items": {
    "Series Title": {
      "year": "2023",
      "tvg_logo": "https://fmftp.net/content-images/movies/posters/...",
      "rating": 8.2,
      "genre": ["Thriller"],
      "language": "English TV Series",
      "watch_page": "https://fmftp.net/watch?type=SERIES&id=456",
      "stream_url": "https://fmftp.net/api/stream/video/stream?type=tv-shows&id=456"
    }
  }
}
```

---

## ⚙️ How It Works

1. **GitHub Actions** runs every 2 days (cron schedule)
2. `fetch_data.py` fetches all pages from fmftp.net API concurrently
3. New items are merged into existing JSON files (old data is preserved)
4. Only commits if there are actual changes
5. Commit message shows date + number of new items

---

## 🔧 Manual Run

Go to **Actions** tab → **FMFTP Auto Scanner** → **Run workflow**

---

## 📊 Scan Summary

`scan_summary.json` always shows the last scan result:
```json
{
  "last_scan": "2026-05-28T00:00:00Z",
  "total_new_items": 15,
  "results": [
    { "file": "movies/Bollywood.json", "total": 350, "new": 5 },
    ...
  ]
}
```
