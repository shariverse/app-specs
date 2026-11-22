#!/usr/bin/env python3
"""各 OS のリポジトリの docs/spec/ が、app-specs の main から生成したままかを確かめる。

各 OS のリポジトリの Spec check（templates/spec-check.yml）が、app-specs の main のこのスクリプトを動かす。

使い方:
  verify_spec.py --spec <各 OS のリポジトリの docs/spec> --repository <owner/name> [--base <コミット>]

確かめること:
  1. .source.json の commit が 40 桁の SHA で、app-specs の main に入っている
  2. .source.json の app・platform が、main の apps.json でこのリポジトリのもの
  3. --base（PR のベース）の docs/spec/ より古い仕様に巻き戻していない
  4. docs/spec/ が、その commit の app-specs を、その commit の生成スクリプトで生成したものと同じ

docs/spec/ がまだ無いリポジトリ（最初の spec-sync を入れる前）は、知らせを出して成功にする。
終了コードは、通れば 0、通せなければ 1、確かめる用意ができていなければ 2。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_REPOSITORY = "shariverse/app-specs"
SOURCE_FILE = ".source.json"
COMMIT = re.compile(r"[0-9a-f]{40}")
# 違うファイルを並べる数の上限（ログを埋めないため）
MAX_LISTED = 20
MAX_QUOTED = 200


class VerifyError(Exception):
    """docs/spec/ を通せないとき。summary は決まった文、details は PR から来た値を含むことがある。"""

    def __init__(self, summary: str, details: list[str] | None = None) -> None:
        super().__init__(summary)
        self.summary = summary
        self.details = details or []


class SetupError(Exception):
    """確かめる用意ができていないとき（引数・checkout の取り方の間違い）。"""


@dataclass(frozen=True)
class Source:
    commit: str
    app: str
    platform: str


@dataclass(frozen=True)
class Outcome:
    message: str
    # docs/spec/ がまだ無く、何も確かめなかった
    skipped: bool = False


def quote(value: object) -> str:
    """PR から来た値を、改行や制御文字をそのまま出さない形にする。"""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_QUOTED else text[:MAX_QUOTED] + "…"


def git(directory: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, check=False, env=env)


def has_commit(repository: Path, revision: str) -> bool:
    return git(repository, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}").returncode == 0


def is_ancestor(repository: Path, older: str, newer: str) -> bool | None:
    """older が newer の祖先か同じなら True。どちらかのコミットが無ければ None。"""
    code = git(repository, "merge-base", "--is-ancestor", older, newer).returncode
    return {0: True, 1: False}.get(code)


def locate(spec: Path) -> tuple[Path, str]:
    """spec を含む作業ツリーの直下と、その中での spec のパスを返す。

    シンボリックリンクを辿ると、ベースの docs/spec/ と違う場所を比べてしまうので、パスの字面で探す。
    """
    spec = Path(os.path.abspath(spec))
    for top in spec.parents:
        if (top / ".git").exists():
            return top, spec.relative_to(top).as_posix()
    raise SetupError(f"--spec {spec} が、git の作業ツリーの中にありません")


def read_source(data: bytes, where: str) -> Source:
    try:
        source = json.loads(data.decode("utf-8"))
    except ValueError as error:
        raise VerifyError(f"{where} が JSON として読めません") from error
    if not isinstance(source, dict):
        raise VerifyError(f"{where} の形が違います（オブジェクトではありません）")
    for key in ("repository", "commit", "app", "platform"):
        if not isinstance(source.get(key), str):
            raise VerifyError(f"{where} に {key} がありません（文字列で書きます）")
    if source["repository"] != SOURCE_REPOSITORY:
        raise VerifyError(
            f"{where} の repository が {SOURCE_REPOSITORY} ではありません",
            [f"repository: {quote(source['repository'])}"],
        )
    if not COMMIT.fullmatch(source["commit"]):
        raise VerifyError(
            f"{where} の commit が 40 桁の SHA ではありません",
            [f"commit: {quote(source['commit'])}"],
        )
    return Source(commit=source["commit"], app=source["app"], platform=source["platform"])


def check_repository(source: Source, repository: str, app_specs: Path, main: str) -> None:
    """app・platform が、main の apps.json でこのリポジトリのものかを確かめる。"""
    result = git(app_specs, "show", f"{main}:apps.json")
    if result.returncode != 0:
        raise SetupError(f"app-specs の {main} に apps.json がありません")
    try:
        apps = json.loads(result.stdout.decode("utf-8"))
    except ValueError as error:
        raise SetupError(f"app-specs の {main} の apps.json が読めません") from error

    owned = []
    expected = None
    for key, value in apps.items() if isinstance(apps, dict) else []:
        repositories = value.get("repositories") if isinstance(value, dict) else None
        for platform, name in repositories.items() if isinstance(repositories, dict) else []:
            if not isinstance(name, str):
                continue
            if name.casefold() == repository.casefold():
                owned.append(f"app={key} platform={platform}")
            if key == source.app and platform == source.platform:
                expected = name
    if expected is not None and expected.casefold() == repository.casefold():
        return
    raise VerifyError(
        "docs/spec/ の app・platform が、このリポジトリのものではありません",
        [
            f".source.json: app={quote(source.app)} platform={quote(source.platform)}",
            f"このリポジトリ（{repository}）: {'、'.join(owned) if owned else 'apps.json にありません'}",
        ],
    )


def check_not_rolled_back(source: Source, top: Path, path: str, base: str, app_specs: Path, main: str) -> None:
    """ベースの docs/spec/ の元のコミットが、この docs/spec/ の元のコミットに含まれているかを確かめる。"""
    result = git(top, "show", f"{base}:{path}/{SOURCE_FILE}")
    if result.returncode != 0:
        return
    try:
        before = read_source(result.stdout, "ベースの .source.json")
    except VerifyError:
        # ベースが壊れているなら、比べられない。この PR が main のコミットに直すのは通す
        return
    if not is_ancestor(app_specs, before.commit, main):
        # ベースが main のものでないなら、どの main のコミットにも含まれない。main のコミットに直すのは通す
        return
    if not is_ancestor(app_specs, before.commit, source.commit):
        raise VerifyError(
            "ベースの docs/spec/ より古い仕様に巻き戻しています",
            [f"ベースの元のコミット: {before.commit}", f"この docs/spec/ の元のコミット: {source.commit}"],
        )


def export(app_specs: Path, commit: str, tree: Path, index: Path) -> None:
    """app-specs の commit の中身を tree に書き出す（app-specs の作業ツリーとインデックスは変えない）。"""
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    for args in (("read-tree", commit), ("checkout-index", "--all", f"--prefix={tree.as_posix()}/")):
        result = git(app_specs, *args, env=env)
        if result.returncode != 0:
            raise SetupError(f"app-specs の {commit} を書き出せません: {result.stderr.decode('utf-8', 'replace').strip()}")


def files_in(root: Path) -> dict[str, Path]:
    """root の下のファイル（とシンボリックリンク）を、root からのパスで返す。"""
    found = {}
    for directory, directories, names in os.walk(root):
        links = [name for name in directories if (Path(directory) / name).is_symlink()]
        for name in [*names, *links]:
            file = Path(directory) / name
            found[file.relative_to(root).as_posix()] = file
    return found


def compare(expected: Path, actual: Path) -> list[str]:
    """生成し直したもの（expected）と docs/spec/（actual）の違いを、1 つ 1 行で返す。"""
    expected_files = files_in(expected)
    actual_files = files_in(actual)
    differences = []
    for path in sorted(set(expected_files) | set(actual_files)):
        if path not in actual_files:
            differences.append(f"足りない: {quote(path)}")
        elif path not in expected_files:
            differences.append(f"生成したものに無い: {quote(path)}")
        elif actual_files[path].is_symlink():
            differences.append(f"シンボリックリンクになっている: {quote(path)}")
        elif actual_files[path].read_bytes() != expected_files[path].read_bytes():
            differences.append(f"中身が違う: {quote(path)}")
    return differences


def check_generated(source: Source, spec: Path, app_specs: Path) -> None:
    """その commit の app-specs を、その commit の生成スクリプトで生成し直して、docs/spec/ と比べる。

    main の生成スクリプトで作り直すと、スクリプトを変えたときに、前のコミットの docs/spec/ と食い違う。
    """
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory) / "app-specs"
        expected = Path(directory) / "expected"
        export(app_specs, source.commit, tree, Path(directory) / "index")
        script = tree / "scripts" / "generate_spec.py"
        if not script.is_file():
            raise VerifyError("元のコミットの app-specs に、生成スクリプトがありません", [f"commit: {source.commit}"])
        result = subprocess.run(
            [sys.executable, str(script), "generate", "--app", source.app, "--platform", source.platform,
             "--out", str(expected), "--source-commit", source.commit],
            capture_output=True, check=False,
        )
        if result.returncode != 0:
            lines = result.stderr.decode("utf-8", "replace").strip().splitlines()
            raise VerifyError("元のコミットの app-specs から、この OS の仕様を生成できません", lines[-MAX_LISTED:])
        differences = compare(expected, spec)
    if differences:
        more = len(differences) - MAX_LISTED
        raise VerifyError(
            "docs/spec/ が、app-specs から生成したものと違います",
            differences[:MAX_LISTED] + ([f"ほか {more} 件"] if more > 0 else []),
        )


def verify(
    spec: Path,
    repository: str,
    base: str | None = None,
    app_specs: Path = ROOT,
    main: str = "origin/main",
) -> Outcome:
    top, path = locate(spec)
    spec = top / path
    if not has_commit(app_specs, main):
        raise SetupError(f"app-specs に {main} がありません（app-specs は main を、履歴をすべて取って checkout します）")
    base_has_spec = False
    if base is not None:
        if not has_commit(top, base):
            raise SetupError(f"--base {base} が見つかりません（各 OS のリポジトリは fetch-depth を 2 以上で checkout します）")
        base_has_spec = bool(git(top, "ls-tree", base, "--", path).stdout.strip())

    for index in range(1, len(Path(path).parts) + 1):
        if (top / Path(*Path(path).parts[:index])).is_symlink():
            raise VerifyError(f"{path} までのパスに、シンボリックリンクがあります")
    if not spec.is_dir():
        if spec.exists():
            raise VerifyError(f"{path} がフォルダではありません")
        if base_has_spec:
            raise VerifyError(f"{path}/ が消えています（ベースにはあります）")
        return Outcome(f"{path}/ がまだありません。最初の spec-sync の PR を入れると、ここで確かめます", skipped=True)

    source_file = spec / SOURCE_FILE
    if source_file.is_symlink() or not source_file.is_file():
        raise VerifyError(f"{path}/{SOURCE_FILE} がありません")
    source = read_source(source_file.read_bytes(), f"{path}/{SOURCE_FILE}")

    if not is_ancestor(app_specs, source.commit, main):
        raise VerifyError(
            f"{path}/{SOURCE_FILE} の commit が、app-specs の main に入っていません（main から生成した仕様だけを置けます）",
            [f"commit: {source.commit}"],
        )
    check_repository(source, repository, app_specs, main)
    if base is not None and base_has_spec:
        check_not_rolled_back(source, top, path, base, app_specs, main)
    check_generated(source, spec, app_specs)
    return Outcome(f"{path}/ は、app-specs の main の {source.commit[:7]} から生成したままです")


def report_failure(error: VerifyError) -> None:
    """GitHub Actions では、PR から来た値を出す間、ログの中のコマンドの解釈を止める。"""
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    print(f"::error title=Spec check::{error.summary}" if on_github else f"Spec check: {error.summary}", file=sys.stderr)
    if error.details:
        token = secrets.token_hex(16)
        if on_github:
            print(f"::stop-commands::{token}", file=sys.stderr)
        for line in error.details:
            print(f"- {line}", file=sys.stderr)
        if on_github:
            print(f"::{token}::", file=sys.stderr)
    print(
        f"docs/spec/ は直接編集しません。変えるときは https://github.com/{SOURCE_REPOSITORY} に PR を出します",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", required=True, help="各 OS のリポジトリの docs/spec/ のパス")
    parser.add_argument("--repository", required=True, help="各 OS のリポジトリ（owner/name）")
    parser.add_argument("--base", help="巻き戻しを比べる先のコミット（PR なら、マージコミットの第 1 親の HEAD^1）")
    parser.add_argument("--app-specs", default=str(ROOT), help="app-specs の checkout（既定は、このスクリプトのあるリポジトリ）")
    parser.add_argument("--main", default="origin/main", help="app-specs の main を指す名前")
    args = parser.parse_args(argv)

    try:
        outcome = verify(Path(args.spec), args.repository, args.base, Path(args.app_specs), args.main)
    except VerifyError as error:
        report_failure(error)
        return 1
    except SetupError as error:
        print(f"Spec check を始められません: {error}", file=sys.stderr)
        return 2
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    print(f"::notice title=Spec check::{outcome.message}" if on_github and outcome.skipped else outcome.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
