import re


def to_seconds(s: str) -> int:
    if s == "0":
        return 0
    s = s.lower().strip()
    hours = minutes = 0

    # match forms like "1h30", "1h 30", "1h30m", "1h 30 min", "1h"
    m = re.search(r"(?P<h>\d+)\s*h(?:\s*(?P<m>\d{1,2})\s*(?:m(?:in)?)?)?", s)
    if m:
        hours = int(m.group("h"))
        if m.group("m"):
            minutes = int(m.group("m"))
        return hours * 3600 + minutes * 60

    # match minutes like "30min", "30 min", "30m"
    m = re.search(r"(?<!\d)(?P<m>\d{1,3})\s*(?:m(?:in)?)\b", s)
    if m:
        minutes = int(m.group("m"))
        return minutes * 60

    return 0


def to_hours_and_minutes(seconds: int, return_str: bool = True) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if return_str:
        parts = []
        if hours > 0:
            parts.append(f"{int(hours)}h")
        if minutes > 0:
            parts.append(f"{int(minutes):02d}")
        if hours == 0:
            parts.append("min")
        return "".join(parts)
    else:
        return hours, minutes


# check if two intervals (start1, end1) and (start2, end2) overlap and how much
def intervals_overlap(start1, end1, start2, end2):
    overlap = min(end1, end2) - max(start1, start2)
    return max(0, overlap.total_seconds())
