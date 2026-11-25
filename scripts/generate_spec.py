#!/usr/bin/env python3
"""app-specs の共通仕様から、各 OS のリポジトリに置く docs/spec/ を作る。

使い方:
  generate_spec.py generate --app <app> --platform <ios|android> --out <dir> [--source-commit <sha>]
  generate_spec.py check          全アプリ・全 OS を生成できるか、README の対応表が最新かを確かめる
  generate_spec.py write-index    README の対応表を書き直す
  generate_spec.py targets        同期のワークフローが回す (アプリ, OS) の一覧を JSON で出す
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_REPOSITORY = "shariverse/app-specs"
PLATFORM_LABELS = {"ios": "iOS", "android": "Android"}
STATUS_LABELS = {"shipped": "あり", "planned": "予定", "undecided": "未定", "none": "作らない"}
# 未定の機能は、その OS の仕様として読まれると「作るもの」と誤解されるので出力に含めない
INCLUDED_STATUSES = {"shipped", "planned"}
SOURCE_FILE = ".source.json"
# 決まっていないもの・よく変わるものは、各 OS で実装の根拠として読まれないよう配らない
UNDISTRIBUTED_FILES = {"roadmap.md"}
UNDISTRIBUTED_DIRECTORIES = ("proposals/", "notes/")
# 配らないもののうち、仕様の補足として各 OS からも辿れるよう、リンクを GitHub の URL にして残すもの
LINKED_BY_URL_DIRECTORIES = ("notes/",)
# リポジトリの直下にあって、どのアプリの docs/spec/ にも配るファイル
SHARED_FILES = ("shariverse.md",)

BLOCK_START = re.compile(r"^\s*<!--\s*only:\s*([a-z, ]+?)\s*-->\s*$")
BLOCK_END = re.compile(r"^\s*<!--\s*/only\s*-->\s*$")
LINE_ONLY = re.compile(r"\s*<!--\s*only:\s*([a-z, ]+?)\s*-->\s*$")
LINK = re.compile(r"(\]\()([^)\s]+)(\))")
INDEX_START = "<!-- features:start -->"
INDEX_END = "<!-- features:end -->"


class SpecError(Exception):
    pass


@dataclass(frozen=True)
class App:
    key: str
    name: str
    repositories: dict[str, str]

    @property
    def platforms(self) -> list[str]:
        return list(self.repositories)

    @property
    def directory(self) -> Path:
        return ROOT / self.key


@dataclass(frozen=True)
class Document:
    path: str
    status: dict[str, str]
    body: str

    @property
    def title(self) -> str:
        for line in self.body.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        raise SpecError(f"{self.path}: 先頭の見出し（# ）がありません")


def load_apps() -> dict[str, App]:
    data = json.loads((ROOT / "apps.json").read_text(encoding="utf-8"))
    apps = {}
    for key, value in data.items():
        unknown = set(value["repositories"]) - set(PLATFORM_LABELS)
        if unknown:
            raise SpecError(f"apps.json: {key} に知らない OS があります: {sorted(unknown)}")
        apps[key] = App(key=key, name=value["name"], repositories=value["repositories"])
    return apps


def parse_front_matter(path: str, text: str, platforms: list[str]) -> tuple[dict[str, str], str]:
    """先頭の `status:` だけを読む。PyYAML を入れずに CI で動かすため、書ける形をこの 1 つに絞っている。"""
    default = {platform: "shipped" for platform in platforms}
    if not text.startswith("---\n"):
        return default, text
    end = text.find("\n---\n", 4)
    if end == -1:
        raise SpecError(f"{path}: front matter が閉じていません")
    lines = text[4:end].splitlines()
    body = text[end + len("\n---\n"):]

    if not lines or lines[0].strip() != "status:":
        raise SpecError(f"{path}: front matter に書けるのは status だけです")
    status = {}
    for line in lines[1:]:
        match = re.fullmatch(r"  ([a-z]+): ([a-z]+)", line)
        if not match:
            raise SpecError(f"{path}: status の行の形が違います: {line!r}")
        platform, value = match.groups()
        if value not in STATUS_LABELS:
            raise SpecError(f"{path}: status に {value!r} は書けません（{', '.join(STATUS_LABELS)}）")
        status[platform] = value
    if set(status) != set(platforms):
        raise SpecError(f"{path}: status にはこのアプリの OS をすべて書きます（{', '.join(platforms)}）")
    return status, body


def filter_platform(path: str, text: str, platform: str, platforms: list[str]) -> str:
    """`<!-- only: ios -->` の段落と、行末に同じ印を付けた行を、対象の OS のときだけ残す。"""
    def targets(raw: str, line_number: int) -> set[str]:
        names = {name.strip() for name in raw.split(",") if name.strip()}
        unknown = names - set(platforms)
        if not names or unknown:
            raise SpecError(f"{path}:{line_number}: only に知らない OS があります: {raw!r}")
        return names

    output = []
    block: set[str] | None = None
    block_line = 0
    for number, line in enumerate(text.splitlines(), start=1):
        if match := BLOCK_START.match(line):
            if block is not None:
                raise SpecError(f"{path}:{number}: only の中に only は書けません（{block_line} 行目から）")
            block = targets(match.group(1), number)
            block_line = number
            continue
        if BLOCK_END.match(line):
            if block is None:
                raise SpecError(f"{path}:{number}: 対応する <!-- only: … --> がありません")
            block = None
            continue
        if block is not None and platform not in block:
            continue
        if match := LINE_ONLY.search(line):
            if platform not in targets(match.group(1), number):
                continue
            line = line[: match.start()]
        output.append(line)
    if block is not None:
        raise SpecError(f"{path}:{block_line}: <!-- only: … --> が閉じていません")

    result = "\n".join(output)
    return re.sub(r"\n{3,}", "\n\n", result).strip("\n") + "\n"


def output_path(source: str, platform: str, documents: dict[str, Document]) -> str | None:
    """共通仕様のパスを、その OS の docs/spec/ の中のパスにする。出さないファイルは None。"""
    if source in UNDISTRIBUTED_FILES or source.startswith(UNDISTRIBUTED_DIRECTORIES):
        return None
    if source.startswith("platforms/"):
        return "platform.md" if source == f"platforms/{platform}.md" else None
    document = documents.get(source)
    if document is not None and document.status[platform] not in INCLUDED_STATUSES:
        return None
    return source


def rewrite_links(
    source: str,
    text: str,
    app: App,
    platform: str,
    documents: dict[str, Document],
    commit: str,
) -> str:
    target = output_path(source, platform, documents)
    assert target is not None

    def replace(match: re.Match[str]) -> str:
        href = match.group(2)
        if re.match(r"^[a-z][a-z0-9+.-]*:", href) or href.startswith("#"):
            return match.group(0)
        link, _, anchor = href.partition("#")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), link))
        if resolved.startswith("../") or resolved == "..":
            outside = posixpath.normpath(posixpath.join(app.key, resolved))
            if not (ROOT / outside).exists():
                raise SpecError(f"{app.key}/{source}: リンク先がありません: {href}")
            if outside in SHARED_FILES:
                mapped = outside
            else:
                url = f"https://github.com/{SOURCE_REPOSITORY}/blob/main/{outside}"
                return f"{match.group(1)}{url}{'#' + anchor if anchor else ''}{match.group(3)}"
        else:
            if not (app.directory / resolved).exists():
                raise SpecError(f"{app.key}/{source}: リンク先がありません: {href}")
            if resolved.startswith(LINKED_BY_URL_DIRECTORIES):
                url = f"https://github.com/{SOURCE_REPOSITORY}/blob/main/{app.key}/{resolved}"
                return f"{match.group(1)}{url}{'#' + anchor if anchor else ''}{match.group(3)}"
            mapped = output_path(resolved, platform, documents)
        if mapped is None:
            raise SpecError(
                f"{app.key}/{source}: {PLATFORM_LABELS[platform]} 版の docs/spec/ に出さないファイルへのリンクです: {href}"
                f"（OS で分けるならリンクを <!-- only: … --> で囲む。roadmap.md・proposals/ へはリンクしない）"
            )
        relative = posixpath.relpath(mapped, posixpath.dirname(target) or ".")
        return f"{match.group(1)}{relative}{'#' + anchor if anchor else ''}{match.group(3)}"

    return LINK.sub(replace, text)


def load_documents(app: App) -> dict[str, Document]:
    documents = {}
    for file in sorted(app.directory.rglob("*.md")):
        path = file.relative_to(app.directory).as_posix()
        text = file.read_text(encoding="utf-8")
        status, body = parse_front_matter(f"{app.key}/{path}", text, app.platforms)
        if path.startswith("platforms/") and text.startswith("---\n"):
            raise SpecError(f"{app.key}/{path}: platforms/ のファイルには status を書きません")
        documents[path] = Document(path=path, status=status, body=body)
    if "README.md" not in documents:
        raise SpecError(f"{app.key}: README.md がありません")
    for platform in app.platforms:
        if f"platforms/{platform}.md" not in documents:
            raise SpecError(f"{app.key}: platforms/{platform}.md がありません")
    return documents


def features(documents: dict[str, Document]) -> list[Document]:
    return [document for path, document in documents.items() if path.startswith("features/")]


def full_index(app: App, documents: dict[str, Document]) -> str:
    header = "| 機能 | " + " | ".join(PLATFORM_LABELS[p] for p in app.platforms) + " |"
    rule = "|---|" + "---|" * len(app.platforms)
    rows = [
        f"| [{document.title}]({document.path}) | "
        + " | ".join(STATUS_LABELS[document.status[p]] for p in app.platforms)
        + " |"
        for document in features(documents)
    ]
    return "\n".join([header, rule, *rows])


def platform_index(platform: str, documents: dict[str, Document]) -> str:
    rows = ["| 機能 | 状態 |", "|---|---|"]
    for document in features(documents):
        status = document.status[platform]
        title = document.title
        if status in INCLUDED_STATUSES:
            title = f"[{title}]({document.path})"
        rows.append(f"| {title} | {STATUS_LABELS[status]} |")
    return "\n".join(rows)


def replace_index(path: str, text: str, index: str) -> str:
    start = text.find(INDEX_START)
    end = text.find(INDEX_END)
    if start == -1 or end == -1 or end < start:
        raise SpecError(f"{path}: {INDEX_START} と {INDEX_END} で囲んだ対応表の場所がありません")
    return text[: start + len(INDEX_START)] + "\n" + index + "\n" + text[end:]


def header(source: str, commit: str) -> str:
    return (
        "<!--\n"
        "  app-specs から生成したファイル。直接編集しない。\n"
        f"  元: {SOURCE_REPOSITORY} {source}\n"
        f"  変えるときは https://github.com/{SOURCE_REPOSITORY} に PR を出す。\n"
        "-->\n\n"
    )


def planned_notice(platform: str) -> str:
    return f"> [!NOTE]\n> {PLATFORM_LABELS[platform]} 版では、まだ作っていない（予定）。\n"


def render(app: App, platform: str, commit: str) -> dict[str, bytes]:
    """出力する docs/spec/ の中身を、パスからファイルの中身への対応で返す。"""
    if platform not in app.platforms:
        raise SpecError(f"{app.key} に {platform} 版はありません")
    documents = load_documents(app)
    files: dict[str, bytes] = {}

    for path, document in documents.items():
        target = output_path(path, platform, documents)
        if target is None:
            continue
        body = document.body
        if path == "README.md":
            body = replace_index(f"{app.key}/README.md", body, platform_index(platform, documents))
        body = filter_platform(f"{app.key}/{path}", body, platform, app.platforms)
        body = rewrite_links(path, body, app, platform, documents, commit)
        if path == "README.md":
            body = body.replace(INDEX_START + "\n", "").replace(INDEX_END + "\n", "")
            if body.startswith("# "):
                title, _, rest = body.partition("\n")
                body = f"{title}（{PLATFORM_LABELS[platform]} 版）\n{rest}"
        if document.status[platform] == "planned":
            title, _, rest = body.partition("\n")
            body = f"{title}\n\n{planned_notice(platform)}\n{rest.lstrip(chr(10))}"
        files[target] = (header(f"{app.key}/{path}", commit) + body).encode("utf-8")

    for file in sorted(app.directory.rglob("*")):
        if file.is_dir() or file.suffix == ".md":
            continue
        path = file.relative_to(app.directory).as_posix()
        if path.startswith("platforms/"):
            raise SpecError(f"{app.key}/{path}: platforms/ には Markdown だけを置きます")
        if output_path(path, platform, documents) is not None:
            files[path] = file.read_bytes()

    for name in SHARED_FILES:
        file = ROOT / name
        if not file.exists():
            continue
        body = filter_platform(name, file.read_text(encoding="utf-8"), platform, app.platforms)
        for match in LINK.finditer(body):
            if not re.match(r"^[a-z][a-z0-9+.-]*:", match.group(2)) and not match.group(2).startswith("#"):
                raise SpecError(f"{name}: 各アプリに配るので、相対リンクは書けません（URL にする）: {match.group(2)}")
        files[name] = (header(name, commit) + body).encode("utf-8")

    source = {
        "repository": SOURCE_REPOSITORY,
        "commit": commit,
        "app": app.key,
        "platform": platform,
    }
    files[SOURCE_FILE] = (json.dumps(source, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return files


def write_output(out: Path, files: dict[str, bytes]) -> None:
    if out.exists() and any(out.iterdir()) and not (out / SOURCE_FILE).exists():
        # 手で書いた docs/spec/ を消さないよう、生成したことのある場所だけを置き換える
        raise SpecError(f"{out}: {SOURCE_FILE} が無いので、生成したものではないファイルを消してしまいます。中身を移してから空にしてください")
    if out.exists():
        shutil.rmtree(out)
    for path, content in files.items():
        file = out / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "0000000"


def readme_with_index(app: App) -> tuple[str, str]:
    path = app.directory / "README.md"
    text = path.read_text(encoding="utf-8")
    return text, replace_index(f"{app.key}/README.md", text, full_index(app, load_documents(app)))


def command_generate(args: argparse.Namespace) -> None:
    apps = load_apps()
    if args.app not in apps:
        raise SpecError(f"apps.json に {args.app} がありません")
    commit = args.source_commit or current_commit()
    write_output(Path(args.out), render(apps[args.app], args.platform, commit))


def check_undistributed_links(app: App, documents: dict[str, Document]) -> list[str]:
    """配らないファイルは生成でリンクを確かめないので、リンク先があるかだけをここで見る。"""
    errors = []
    for path, document in documents.items():
        if output_path(path, app.platforms[0], documents) is not None or path.startswith("platforms/"):
            continue
        for match in LINK.finditer(document.body):
            href = match.group(2)
            if re.match(r"^[a-z][a-z0-9+.-]*:", href) or href.startswith("#"):
                continue
            resolved = posixpath.normpath(posixpath.join(app.key, posixpath.dirname(path), href.partition("#")[0]))
            if not (ROOT / resolved).exists():
                errors.append(f"{app.key}/{path}: リンク先がありません: {href}")
    return errors


def command_check(_: argparse.Namespace) -> None:
    errors = []
    for app in load_apps().values():
        try:
            errors.extend(check_undistributed_links(app, load_documents(app)))
            current, expected = readme_with_index(app)
            if current != expected:
                errors.append(f"{app.key}/README.md: 対応表が古いです（write-index で書き直す）")
            for platform in app.platforms:
                with tempfile.TemporaryDirectory() as directory:
                    write_output(Path(directory) / "spec", render(app, platform, "0000000"))
        except SpecError as error:
            errors.append(str(error))
    if errors:
        raise SpecError("\n".join(errors))


def command_write_index(_: argparse.Namespace) -> None:
    for app in load_apps().values():
        current, expected = readme_with_index(app)
        if current != expected:
            (app.directory / "README.md").write_text(expected, encoding="utf-8")
            print(f"{app.key}/README.md を書き直しました")


def command_targets(_: argparse.Namespace) -> None:
    targets = [
        {
            "app": app.key,
            "platform": platform,
            "repository": repository,
            "repository_name": repository.split("/", 1)[1],
        }
        for app in load_apps().values()
        for platform, repository in app.repositories.items()
    ]
    print(json.dumps(targets, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate")
    generate.add_argument("--app", required=True)
    generate.add_argument("--platform", required=True, choices=sorted(PLATFORM_LABELS))
    generate.add_argument("--out", required=True)
    generate.add_argument("--source-commit")
    generate.set_defaults(handler=command_generate)

    commands.add_parser("check").set_defaults(handler=command_check)
    commands.add_parser("write-index").set_defaults(handler=command_write_index)
    commands.add_parser("targets").set_defaults(handler=command_targets)

    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except SpecError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
