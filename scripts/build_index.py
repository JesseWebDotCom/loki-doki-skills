from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SOURCES_DIR = ROOT_DIR / "sources" / "skills"
PUBLISHED_DIR = ROOT_DIR / "skills"
INDEX_PATH = ROOT_DIR / "index.json"
README_PATH = ROOT_DIR / "README.md"
REPO_URL = "https://github.com/JesseWebDotCom/loki-doki-skills"
SOURCE_REPO_URL = "https://github.com/JesseWebDotCom/loki-doki"
SOURCE_REPO_LINK = f"[LokiDoki]({SOURCE_REPO_URL})"


def canonical_logo(source_dir: Path) -> Path:
    matches = sorted(path for path in source_dir.iterdir() if path.suffix.lower() in {".svg", ".png", ".jpg", ".jpeg", ".webp"} and "logo" in path.stem.lower())
    if not matches:
        raise RuntimeError(f"{source_dir.name} is missing a logo image")
    return matches[0]


def load_manifest(source_dir: Path) -> dict[str, object]:
    manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    logo_path = source_dir / str(manifest.get("logo_path") or "")
    if not logo_path.exists():
        logo_path = canonical_logo(source_dir)
        manifest["logo_path"] = logo_path.name
    return manifest


def build_zip(source_dir: Path, target_zip: Path) -> None:
    target_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(source_dir).as_posix())


def write_skill_files(source_dir: Path, manifest: dict[str, object]) -> dict[str, object]:
    skill_id = str(manifest.get("id") or source_dir.name).strip()
    title = str(manifest.get("title") or skill_id).strip()
    description = str(manifest.get("description") or "LokiDoki skill package.").strip()
    version = str(manifest.get("version") or "1.0.0").strip() or "1.0.0"
    logo_path = source_dir / str(manifest["logo_path"])
    publish_dir = PUBLISHED_DIR / skill_id
    publish_dir.mkdir(parents=True, exist_ok=True)
    target_zip = publish_dir / f"{skill_id}.zip"
    build_zip(source_dir, target_zip)
    shutil.copy2(logo_path, publish_dir / "logo.svg")
    meta = {
        "id": skill_id,
        "title": title,
        "description": description,
        "version": version,
        "domain": str(manifest.get("domain") or ""),
        "domains": [str(manifest.get("domain") or "")],
        "platforms": ["mac", "pi_cpu", "pi_hailo"],
        "account_mode": str(manifest.get("account_mode") or "none"),
        "download_url": f"skills/{skill_id}/{skill_id}.zip",
        "logo_url": f"skills/{skill_id}/logo.svg",
        "meta_url": f"skills/{skill_id}/meta.json",
    }
    (publish_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    readme = "\n".join([
        f"# {title}",
        "",
        f'<img src="./logo.svg" alt="{title} logo" width="72" height="72">',
        "",
        description,
        "",
        "## Install",
        "",
        f"- Open {SOURCE_REPO_LINK} and browse the skills catalog",
        f"- Direct package: [`{skill_id}.zip`](./{skill_id}.zip)",
        "",
        "## Metadata",
        "",
        f"- ID: `{skill_id}`",
        f"- Version: `{version}`",
        f"- Meta: [`meta.json`](./meta.json)",
        "",
    ])
    (publish_dir / "README.md").write_text(readme + "\n", encoding="utf-8")
    return meta


def build_root_readme(entries: list[dict[str, object]]) -> str:
    gallery = [
        (
            f'<td align="center" valign="top" width="160">'
            f'<a href="./skills/{item["id"]}/">'
            f'<img src="./skills/{item["id"]}/logo.svg" alt="{item["title"]}" width="72" height="72"><br>'
            f'<strong>{item["title"]}</strong></a></td>'
        )
        for item in entries
    ]
    gallery_block = ["<table>", f"<tr>{''.join(gallery)}</tr>", "</table>"] if gallery else ["_No skills published yet._"]
    return "\n".join([
        "# LokiDoki Skills",
        "",
        f"Skills for {SOURCE_REPO_LINK}, the local AI platform for the home.",
        "",
        f"This repo is the official installable skills catalog for {SOURCE_REPO_LINK}.",
        "",
        "## Browse Skills",
        "",
        *gallery_block,
        "",
        "## What Skills Add",
        "",
        "- local tools and workflows",
        "- household utilities and integrations",
        f"- focused capabilities {SOURCE_REPO_LINK} can browse and install",
        f"- required icons for the {SOURCE_REPO_LINK} skill browser",
        "",
        "## Maintainer Note",
        "",
        "Generated files are rebuilt with:",
        "",
        "```bash",
        "python scripts/build_index.py",
        "```",
        "",
    ]) + "\n"


def main() -> None:
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    for source_dir in sorted(path for path in SOURCES_DIR.iterdir() if path.is_dir()):
        entries.append(write_skill_files(source_dir, load_manifest(source_dir)))
    index = {
        "title": "LokiDoki Skills",
        "description": "Skills for LokiDoki, the local AI platform for the home.",
        "repo_url": REPO_URL,
        "source_repo_url": SOURCE_REPO_URL,
        "skills": entries,
    }
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    README_PATH.write_text(build_root_readme(entries), encoding="utf-8")


if __name__ == "__main__":
    main()
