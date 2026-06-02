from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from .research_models import EvidenceItem
from .utils import clean_filename


SCREENSHOT_DIR = Path("downloads") / "evidence_screenshots"


def find_browser_executable() -> str:
    candidates = [
        os.getenv("CHROME_PATH", ""),
        os.getenv("EDGE_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        str(Path.home() / r"AppData\Local\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def capture_evidence_screenshots(evidence: list[EvidenceItem], limit: int = 3) -> list[str]:
    browser = find_browser_executable()
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    captured = 0
    for index, item in enumerate(_screenshot_priority(evidence)):
        if captured >= limit:
            break
        if item.screenshot_path or not _is_captureable_url(item.url):
            continue
        output_path = SCREENSHOT_DIR / _screenshot_filename(index, item)
        ok = False
        error = "browser_not_found"
        if browser:
            ok, error = capture_url_screenshot(item.url, output_path, browser=browser, width=1280, height=900, timeout=8)
        if not ok:
            _write_evidence_snapshot(item, output_path, error)
            ok = True
        if ok:
            item.screenshot_path = str(output_path)
            item.trace_type = "browser_screenshot" if error == "" else "evidence_snapshot"
            captured += 1
        elif len(notes) < 5:
            notes.append(f"{item.ticker or item.company}: 截图失败 {item.url[:120]}：{error}")
    notes.insert(0, f"浏览器截图：成功生成 {captured} 张关键证据截图。")
    return notes


def capture_url_screenshot(
    url: str,
    output_path: Path,
    *,
    browser: str = "",
    width: int = 1280,
    height: int = 900,
    timeout: int = 24,
) -> tuple[bool, str]:
    browser = browser or find_browser_executable()
    if not browser:
        return False, "browser_not_found"
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="research_browser_") as profile_dir:
        base_args = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--ignore-certificate-errors",
            f"--user-data-dir={profile_dir}",
            f"--window-size={width},{height}",
            f"--screenshot={output_path}",
            url,
        ]
        ok, error = _run_browser_capture(base_args, output_path, timeout)
        if ok:
            return True, ""
        fallback_args = [arg if arg != "--headless=new" else "--headless" for arg in base_args]
        return _run_browser_capture(fallback_args, output_path, timeout)


def _run_browser_capture(args: list[str], output_path: Path, timeout: int) -> tuple[bool, str]:
    try:
        completed = subprocess.run(args, capture_output=True, text=False, timeout=timeout)
    except Exception as exc:
        return False, str(exc)
    if output_path.exists() and output_path.stat().st_size > 1000:
        return True, ""
    raw_error = completed.stderr or completed.stdout or f"exit={completed.returncode}".encode("utf-8")
    error = raw_error.decode("utf-8", errors="ignore").strip() if isinstance(raw_error, bytes) else str(raw_error).strip()
    return False, error[:300]


def _screenshot_priority(evidence: list[EvidenceItem]) -> list[EvidenceItem]:
    priority = {
        "official": 0,
        "platform": 1,
        "media": 2,
        "search": 3,
        "medium": 4,
    }
    type_priority = {
        "presentation": 0,
        "transcript": 1,
        "annual": 2,
        "quarterly": 3,
    }
    return sorted(
        evidence,
        key=lambda item: (
            priority.get(item.confidence_tier, 9),
            type_priority.get(item.evidence_type, 8),
            0 if ".pdf" in item.url.casefold() else 1,
            item.ticker,
        ),
    )


def _is_captureable_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https", "file"} and bool(parsed.netloc or parsed.scheme == "file")


def _screenshot_filename(index: int, item: EvidenceItem) -> str:
    digest = hashlib.sha1(item.url.encode("utf-8", errors="ignore")).hexdigest()[:10]
    label = clean_filename(f"{item.ticker or item.company}_{item.evidence_type}_{item.title}", "evidence")
    return f"{index:03d}_{label[:70]}_{digest}.png"


def _write_evidence_snapshot(item: EvidenceItem, output_path: Path, error: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1280, 900), "#f8fafc")
    draw = ImageDraw.Draw(image)
    font = _font(28)
    small = _font(22)
    muted = "#475569"
    draw.rectangle([0, 0, 1280, 110], fill="#0f172a")
    draw.text((42, 34), "Evidence Snapshot (browser fallback)", fill="#ffffff", font=font)
    rows = [
        ("Company", f"{item.ticker} · {item.company}"),
        ("Type", item.evidence_type),
        ("Source", item.source),
        ("Confidence", item.confidence_tier),
        ("Title", item.title),
        ("URL", item.url),
        ("Trace", f"Browser screenshot failed or timed out: {error[:160]}"),
    ]
    y = 150
    for label, value in rows:
        draw.text((48, y), label, fill="#0f172a", font=font)
        y += 42
        for line in _wrap(value, 92)[:5]:
            draw.text((72, y), line, fill=muted, font=small)
            y += 32
        y += 18
    draw.text((48, 840), "This fallback preserves source traceability; open the URL for full original context.", fill="#64748b", font=small)
    image.save(output_path)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _wrap(value: str, width: int) -> list[str]:
    text = " ".join(str(value or "").split())
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        if len(current) + len(word) + 1 <= width:
            current = f"{current} {word}".strip()
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines
