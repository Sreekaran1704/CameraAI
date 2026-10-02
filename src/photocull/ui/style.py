"""Shared product styles; native widgets retain keyboard/accessibility behavior."""

from pathlib import Path

import streamlit as st

STYLE = """
<style>
:root { --pc-accent:#86d6b5; --pc-muted:#9bafad; }
h1,h2,h3 { letter-spacing:-.035em; }
h1 { font-family:Georgia,serif !important; font-weight:400 !important; }
p { line-height:1.65; }
.pc-eyebrow {font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;
 color:#86d6b5;margin:0 0 16px;}
.pc-hero h1 {font-size:clamp(2.6rem,6vw,4.5rem);line-height:1.02;margin:0 0 24px;}
.pc-hero p {font-size:1rem;color:#abbcba;max-width:540px;}
.pc-badge {display:inline-block;padding:6px 12px;border:1px solid #34534b;
 border-radius:40px;font-size:.72rem;color:#a6e0c6;letter-spacing:.06em;}
.pc-note {font-size:.86rem;color:#a7bab6;padding:16px 0;border-top:1px solid #30433f;}
.pc-footer {font-size:.78rem;color:#869c96;margin:26px 0;}
.pc-mode {padding:18px;border:1px solid #30433f;border-radius:14px;min-height:130px;}
.pc-mode h3 {font-size:1rem;margin:0 0 8px;letter-spacing:0;}
.pc-mode p {font-size:.85rem;color:#a9b9b5;margin:0;}
[data-testid="stMetric"] {background:#162620;border:1px solid #30433f;
 padding:14px 18px;border-radius:12px;}
[data-testid="stMetricValue"] {font-size:1.7rem;}
[data-testid="stImage"] img {border-radius:10px;}
[data-testid="stButton"] button {border-radius:10px;min-height:42px;}
[data-testid="stDownloadButton"] button {border-radius:10px;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:12px;}
button, input, textarea {font-family:inherit;}
@media(max-width:600px) {
 .pc-hero h1 {font-size:2.7rem;}
 [data-testid="stMetric"] {padding:10px;}
}
</style>
"""


def apply_style(embed=False):
    st.html(STYLE)
    if embed:
        # Scope to a stable Streamlit test-id; do not remove toolbar/security controls by CSS.
        st.html(
            "<style>[data-testid='stMainBlockContainer']"
            "{padding-top:1rem;padding-left:1rem;padding-right:1rem;max-width:1100px;}</style>"
        )


def bundled_manifest():
    import json

    root = Path(__file__).resolve().parents[3] / "assets/demo"
    return json.loads((root / "manifest.json").read_text())


def bundled_sources():

    from photocull.sources import UploadedImageSource

    root = Path(__file__).resolve().parents[3] / "assets/demo"
    manifest = bundled_manifest()
    return [UploadedImageSource(name, (root / name).read_bytes()) for name in manifest["files"]]
