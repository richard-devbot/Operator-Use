import argparse
import json
import yt_dlp


def fmt_duration(seconds):
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_count(n):
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def search_videos(query, limit):
    ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        return info.get("entries", [])


def format_markdown(query, entries):
    if not entries:
        return f"No results found for: {query}"

    lines = [f"## YouTube Search: {query}\n"]
    for i, v in enumerate(entries, 1):
        title = v.get("title", "Unknown")
        video_id = v.get("id", "")
        url = f"https://www.youtube.com/watch?v={video_id}" if video_id else v.get("url", "")
        channel = v.get("channel") or v.get("uploader") or "Unknown"
        duration = fmt_duration(v.get("duration"))
        views = fmt_count(v.get("view_count"))

        lines.append(f"{i}. **[{title}]({url})**")
        lines.append(f"   - Channel: {channel}")
        lines.append(f"   - Duration: {duration} | Views: {views}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="YouTube search")
    parser.add_argument("query", nargs="+", help="Search query (multiple words allowed without quotes)")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to return")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of markdown")
    parser.add_argument("-o", "--output", help="Output file path")

    args = parser.parse_args()

    query = " ".join(args.query)
    entries = search_videos(query, args.limit)

    if args.json:
        output = json.dumps(entries, indent=2)
    else:
        output = format_markdown(query, entries)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
