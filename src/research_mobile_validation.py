from __future__ import annotations

from pathlib import Path

from .research_models import ResearchDraft
from .research_screenshots import capture_url_screenshot, find_browser_executable
from .utils import clean_filename


MOBILE_DIR = Path("downloads") / "mobile_validation"


def validate_mobile_html(path: str | Path, draft: ResearchDraft) -> dict[str, object]:
    html_path = Path(path).resolve()
    MOBILE_DIR.mkdir(parents=True, exist_ok=True)
    output = MOBILE_DIR / f"{clean_filename(html_path.stem, 'mobile')}_390x844.png"
    browser = find_browser_executable()
    if not browser:
        result = {
            "passed": False,
            "screenshot_path": "",
            "viewport": "390x844",
            "error": "Chrome/Edge not found",
        }
    else:
        ok, error = capture_url_screenshot(html_path.as_uri(), output, browser=browser, width=390, height=844, timeout=10)
        result = {
            "passed": bool(ok),
            "screenshot_path": str(output) if ok else "",
            "viewport": "390x844",
            "error": error,
        }
    draft.run_metadata.setdefault("mobile_validation", result)
    draft.run_metadata["mobile_validation"] = result
    return result
