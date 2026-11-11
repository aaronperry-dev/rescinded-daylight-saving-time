"""Static checks on the web UI: markup the script depends on, and mobile-first basics."""
import re
from pathlib import Path

from rdst import build

WEB = Path(build.WEB_DIR)
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "style.css").read_text(encoding="utf-8")

# elements app.js creates itself, so they are not in index.html
CREATED_BY_JS = {"divider", "chipLeft", "chipRight", "handle"}


def test_every_element_the_script_looks_up_exists():
    ids = set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", JS)) - CREATED_BY_JS
    missing = sorted(i for i in ids if f'id="{i}"' not in HTML)
    assert not missing, missing


def test_viewport_is_mobile_friendly():
    assert "width=device-width" in HTML and "viewport-fit=cover" in HTML
    assert "user-scalable=no" not in HTML and "maximum-scale" not in HTML      # never block pinch-zoom


def test_form_controls_are_at_least_16px_so_ios_does_not_zoom():
    m = re.search(r"select\s*\{[^}]*font-size:\s*(\d+)px", CSS)
    assert m and int(m.group(1)) >= 16


def test_phone_layout_pins_the_map_and_scrolls_the_panel():
    media = CSS[CSS.index("@media (max-width: 820px)"):]
    assert "--map-h" in media and 'grid-template-areas: "top" "stage" "panel"' in media
    assert re.search(r"#panel\s*\{[^}]*overflow-y:\s*auto", CSS)      # the panel, not the page, scrolls
    assert "dvh" in CSS                                                  # survives mobile browser chrome


def test_touch_targets_and_swipe_hit_area_are_generous():
    assert "--tap: 44px" in CSS
    assert re.search(r"\.handle\s*\{[^}]*width:\s*44px", CSS.replace("\n", " ")) or "width: 44px; height: 44px" in CSS
    assert "touch-action: none" in CSS                                    # dragging the divider must not scroll the page


def test_controls_have_accessible_names():
    for needle in ('aria-label="Swap left and right"', 'aria-label="Share this view"', 'role="radiogroup"',
                   'for="dateRange"', 'for="opacityRange"'):
        assert needle in HTML, needle
    assert 'aria-live="polite"' in HTML


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion" in CSS and "animation: none" in CSS
