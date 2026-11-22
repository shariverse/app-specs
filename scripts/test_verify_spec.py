import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import verify_spec as verify

SCRIPTS = Path(__file__).resolve().parent
IOS = "shariverse/sample-app-ios"
ANDROID = "shariverse/sample-app-android"
OTHER_IOS = "shariverse/other-app-ios"
# 手元の設定（署名・フックなど）に左右されないようにする
GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def git(directory: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(directory), *args], capture_output=True, text=True, check=True, env=GIT_ENV
    )
    return result.stdout.strip()


def write(root: Path, path: str, text: str) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")


def commit_all(directory: Path, message: str) -> str:
    git(directory, "add", "--all")
    git(directory, "commit", "--quiet", "--allow-empty", "-m", message)
    return git(directory, "rev-parse", "HEAD")


class VerifyTestCase(unittest.TestCase):
    """一時フォルダに、app-specs の代わりのリポジトリ（specs）と、各 OS の代わりのリポジトリ（app）を作る。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.specs = root / "app-specs"
        self.app = root / "app"
        self.spec = self.app / "docs" / "spec"

        self.specs.mkdir()
        git(self.specs, "init", "--quiet", "--initial-branch=main")
        (self.specs / "scripts").mkdir()
        shutil.copy(SCRIPTS / "generate_spec.py", self.specs / "scripts" / "generate_spec.py")
        apps = {
            "sample-app": {"name": "サンプル", "repositories": {"ios": IOS, "android": ANDROID}},
            "other-app": {"name": "ほか", "repositories": {"ios": OTHER_IOS}},
        }
        write(self.specs, "apps.json", json.dumps(apps, ensure_ascii=False))
        for app, platforms in (("sample-app", ("ios", "android")), ("other-app", ("ios",))):
            write(self.specs, f"{app}/README.md", "# 概要\n\n<!-- features:start -->\n<!-- features:end -->\n\n[規則](rules.md)\n")
            write(self.specs, f"{app}/rules.md", "# 規則\n\n最初の規則。\n")
            for platform in platforms:
                write(self.specs, f"{app}/platforms/{platform}.md", f"# {platform} 版\n")
        self.first = commit_all(self.specs, "first")

        self.app.mkdir()
        git(self.app, "init", "--quiet", "--initial-branch=develop")
        write(self.app, "README.md", "# app\n")
        commit_all(self.app, "init")

    def advance_main(self, text: str = "次の規則。") -> str:
        """app-specs の main を 1 つ進める。"""
        with open(self.specs / "sample-app" / "rules.md", "a", encoding="utf-8") as file:
            file.write(f"\n{text}\n")
        return commit_all(self.specs, "next")

    def generate(self, commit: str, app: str = "sample-app", platform: str = "ios", label: str = "") -> None:
        """app-specs の commit の中身から、docs/spec/ を生成する（Sync がすることと同じ）。label は .source.json に書くコミット。"""
        current = git(self.specs, "rev-parse", "--abbrev-ref", "HEAD")
        git(self.specs, "checkout", "--quiet", commit)
        # 壊した .source.json の上には生成できない（generate は、前に生成した場所だけを置き換える）ので、消してから作る
        shutil.rmtree(self.spec, ignore_errors=True)
        try:
            subprocess.run(
                [sys.executable, str(self.specs / "scripts" / "generate_spec.py"), "generate", "--app", app,
                 "--platform", platform, "--out", str(self.spec), "--source-commit", label or commit],
                check=True, capture_output=True,
            )
        finally:
            git(self.specs, "checkout", "--quiet", current)

    def source(self, **changes: object) -> None:
        """.source.json の値を書き換える。"""
        file = self.spec / ".source.json"
        data = json.loads(file.read_text(encoding="utf-8"))
        data.update(changes)
        file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def run_verify(self, repository: str = IOS, base: "str | None" = None) -> verify.Outcome:
        return verify.verify(self.spec, repository, base, app_specs=self.specs, main="main")

    def assert_fails(self, pattern: str, repository: str = IOS, base: "str | None" = None) -> verify.VerifyError:
        with self.assertRaisesRegex(verify.VerifyError, pattern) as context:
            self.run_verify(repository, base)
        return context.exception


class PassTests(VerifyTestCase):
    def test_generated_from_main(self) -> None:
        self.generate(self.first)
        outcome = self.run_verify()
        self.assertFalse(outcome.skipped)
        self.assertIn(self.first[:7], outcome.message)

    def test_older_commit_of_main_is_still_valid(self) -> None:
        self.generate(self.first)
        self.advance_main()
        self.run_verify()

    def test_android(self) -> None:
        self.generate(self.first, platform="android")
        self.run_verify(ANDROID)

    def test_repository_name_ignores_case(self) -> None:
        self.generate(self.first)
        self.run_verify(IOS.upper())

    def test_uses_generator_of_that_commit(self) -> None:
        """生成スクリプトを変えた後でも、変える前のコミットの docs/spec/ は、そのコミットのスクリプトで比べる。"""
        self.generate(self.first)
        # 生成スクリプトの中身に寄らないよう、元のスクリプトを動かした後でファイルを 1 つ足すスクリプトに置き換える
        script = self.specs / "scripts" / "generate_spec.py"
        script.rename(script.with_name("generate_spec_before.py"))
        script.write_text(
            "import runpy, sys\n"
            "from pathlib import Path\n"
            "try:\n"
            "    runpy.run_path(str(Path(__file__).with_name('generate_spec_before.py')), run_name='__main__')\n"
            "except SystemExit as stop:\n"
            "    if stop.code:\n"
            "        raise\n"
            "out = Path(sys.argv[sys.argv.index('--out') + 1])\n"
            "(out / 'added.md').write_text('新しいスクリプトが足すファイル\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        changed = commit_all(self.specs, "change generator")
        self.run_verify()

        self.generate(changed)
        self.assertTrue((self.spec / "added.md").exists())
        self.run_verify()

        # 新しいスクリプトで作ったものに、前のコミットを名乗らせると通らない
        self.generate(changed, label=self.first)
        error = self.assert_fails("生成したものと違います")
        self.assertEqual(error.details, ['生成したものに無い: "added.md"'])


class NoSpecTests(VerifyTestCase):
    def test_skips_when_spec_was_never_added(self) -> None:
        outcome = self.run_verify(base="HEAD")
        self.assertTrue(outcome.skipped)
        self.assertIn("まだありません", outcome.message)

    def test_fails_when_spec_was_removed(self) -> None:
        self.generate(self.first)
        commit_all(self.app, "spec")
        git(self.app, "rm", "--quiet", "-r", "docs/spec")
        commit_all(self.app, "remove spec")
        self.assert_fails("消えています", base="HEAD^1")

    def test_fails_when_spec_is_a_file(self) -> None:
        write(self.app, "docs/spec", "x")
        self.assert_fails("フォルダではありません")

    @unittest.skipIf(os.name == "nt", "シンボリックリンクを作れない")
    def test_fails_when_spec_is_a_symlink(self) -> None:
        self.generate(self.first)
        (self.app / "elsewhere").mkdir()
        self.spec.rename(self.app / "elsewhere" / "spec")
        os.symlink(Path("..") / "elsewhere" / "spec", self.spec, target_is_directory=True)
        self.assert_fails("シンボリックリンク")

    @unittest.skipIf(os.name == "nt", "シンボリックリンクを作れない")
    def test_fails_when_parent_is_a_symlink(self) -> None:
        """docs をリンクにして、ベースの docs/spec/ と比べる場所をずらせない。"""
        self.generate(self.first)
        (self.app / "docs").rename(self.app / "elsewhere")
        os.symlink("elsewhere", self.app / "docs", target_is_directory=True)
        self.assert_fails("シンボリックリンク")


class TamperTests(VerifyTestCase):
    def test_edited_by_hand(self) -> None:
        self.generate(self.first)
        with open(self.spec / "rules.md", "a", encoding="utf-8") as file:
            file.write("手で足した規則。\n")
        error = self.assert_fails("生成したものと違います")
        self.assertEqual(error.details, ['中身が違う: "rules.md"'])

    def test_extra_and_missing_files(self) -> None:
        self.generate(self.first)
        write(self.app, "docs/spec/features/99-extra.md", "# 足したファイル\n")
        (self.spec / "platform.md").unlink()
        error = self.assert_fails("生成したものと違います")
        self.assertEqual(error.details, ['生成したものに無い: "features/99-extra.md"', '足りない: "platform.md"'])

    @unittest.skipIf(os.name == "nt", "シンボリックリンクを作れない")
    def test_symlink_with_same_content(self) -> None:
        self.generate(self.first)
        shutil.copy(self.spec / "rules.md", self.app / "rules-copy.md")
        (self.spec / "rules.md").unlink()
        os.symlink(Path("..") / ".." / "rules-copy.md", self.spec / "rules.md")
        error = self.assert_fails("生成したものと違います")
        self.assertEqual(error.details, ['シンボリックリンクになっている: "rules.md"'])

    def test_lists_at_most_twenty_differences(self) -> None:
        self.generate(self.first)
        for number in range(25):
            write(self.app, f"docs/spec/extra/{number:02}.md", "x")
        error = self.assert_fails("生成したものと違います")
        self.assertEqual(len(error.details), verify.MAX_LISTED + 1)
        self.assertEqual(error.details[-1], "ほか 5 件")

    def test_commit_not_on_main(self) -> None:
        """app-specs の作業ブランチ（main に入っていないコミット）から生成したものは通らない。"""
        git(self.specs, "checkout", "--quiet", "-b", "draft")
        with open(self.specs / "sample-app" / "rules.md", "a", encoding="utf-8") as file:
            file.write("\nレビュー前の規則。\n")
        draft = commit_all(self.specs, "draft")
        git(self.specs, "checkout", "--quiet", "main")
        self.generate(draft)
        error = self.assert_fails("main に入っていません")
        self.assertEqual(error.details, [f"commit: {draft}"])

    def test_commit_unknown_to_app_specs(self) -> None:
        self.generate(self.first, label="1" * 40)
        self.assert_fails("main に入っていません")

    def test_other_platform(self) -> None:
        self.generate(self.first, platform="android")
        error = self.assert_fails("このリポジトリのものではありません")
        self.assertIn("app=sample-app platform=ios", error.details[1])

    def test_other_app(self) -> None:
        self.generate(self.first, app="other-app")
        self.assert_fails("このリポジトリのものではありません")

    def test_repository_not_in_apps(self) -> None:
        self.generate(self.first)
        error = self.assert_fails("このリポジトリのものではありません", repository="shariverse/unknown")
        self.assertIn("apps.json にありません", error.details[1])

    def test_main_apps_json_decides(self) -> None:
        """app・platform は、元のコミットではなく main の apps.json で確かめる。"""
        self.generate(self.first, app="other-app")
        self.run_verify(OTHER_IOS)
        apps = json.loads((self.specs / "apps.json").read_text(encoding="utf-8"))
        apps["other-app"]["repositories"]["ios"] = "shariverse/moved"
        write(self.specs, "apps.json", json.dumps(apps, ensure_ascii=False))
        commit_all(self.specs, "move")
        self.assert_fails("このリポジトリのものではありません", repository=OTHER_IOS)


class RollbackTests(VerifyTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.second = self.advance_main()

    def merge_into_develop(self) -> None:
        """PR のブランチを develop にマージしたコミットを作る（pull_request で checkout されるものと同じ形）。"""
        git(self.app, "checkout", "--quiet", "develop")
        git(self.app, "merge", "--quiet", "--no-ff", "--no-edit", "pr")

    def test_forward(self) -> None:
        self.generate(self.first)
        commit_all(self.app, "spec first")
        git(self.app, "checkout", "--quiet", "-b", "pr")
        self.generate(self.second)
        commit_all(self.app, "spec second")
        self.merge_into_develop()
        self.run_verify(base="HEAD^1")

    def test_unchanged(self) -> None:
        self.generate(self.second)
        commit_all(self.app, "spec second")
        git(self.app, "checkout", "--quiet", "-b", "pr")
        write(self.app, "Sources/App.swift", "// code\n")
        commit_all(self.app, "code only")
        self.merge_into_develop()
        self.run_verify(base="HEAD^1")

    def test_rollback(self) -> None:
        self.generate(self.second)
        commit_all(self.app, "spec second")
        git(self.app, "checkout", "--quiet", "-b", "pr")
        self.generate(self.first)
        commit_all(self.app, "spec first again")
        self.merge_into_develop()
        error = self.assert_fails("巻き戻しています", base="HEAD^1")
        self.assertEqual(error.details, [f"ベースの元のコミット: {self.second}", f"この docs/spec/ の元のコミット: {self.first}"])
        # ベースと比べなければ、古いコミットでも main のものなので通る
        self.run_verify()

    def test_first_spec(self) -> None:
        git(self.app, "checkout", "--quiet", "-b", "pr")
        self.generate(self.first)
        commit_all(self.app, "first spec")
        self.merge_into_develop()
        self.run_verify(base="HEAD^1")

    def test_broken_base_can_be_fixed(self) -> None:
        self.generate(self.second)
        (self.spec / ".source.json").write_text("{", encoding="utf-8")
        commit_all(self.app, "broken")
        git(self.app, "checkout", "--quiet", "-b", "pr")
        self.generate(self.first)
        commit_all(self.app, "fixed")
        self.merge_into_develop()
        self.run_verify(base="HEAD^1")

    def test_base_not_from_main_can_be_fixed(self) -> None:
        """ベースが main に無いコミットの仕様なら、main のコミットに直す PR を通す（どの PR も通らなくなるのを避ける）。"""
        git(self.specs, "checkout", "--quiet", "-b", "draft")
        write(self.specs, "sample-app/rules.md", "# 規則\n\nレビュー前の規則。\n")
        draft = commit_all(self.specs, "draft")
        git(self.specs, "checkout", "--quiet", "main")
        self.generate(draft)
        commit_all(self.app, "spec from draft")
        self.assert_fails("main に入っていません", base="HEAD")
        git(self.app, "checkout", "--quiet", "-b", "pr")
        self.generate(self.first)
        commit_all(self.app, "spec from main")
        self.merge_into_develop()
        self.run_verify(base="HEAD^1")

    def test_unknown_base(self) -> None:
        self.generate(self.first)
        with self.assertRaisesRegex(verify.SetupError, "fetch-depth"):
            self.run_verify(base="HEAD~9")


class SourceFileTests(VerifyTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.generate(self.first)

    def test_missing(self) -> None:
        (self.spec / ".source.json").unlink()
        self.assert_fails(r"\.source\.json がありません")

    def test_broken_json(self) -> None:
        (self.spec / ".source.json").write_text('{"commit": ', encoding="utf-8")
        self.assert_fails("JSON として読めません")

    def test_not_utf8(self) -> None:
        (self.spec / ".source.json").write_bytes(b"\xff\xfe{}")
        self.assert_fails("JSON として読めません")

    def test_not_an_object(self) -> None:
        (self.spec / ".source.json").write_text('["commit"]', encoding="utf-8")
        self.assert_fails("オブジェクトではありません")

    def test_missing_key(self) -> None:
        for key in ("repository", "commit", "app", "platform"):
            with self.subTest(key=key):
                self.generate(self.first)
                data = json.loads((self.spec / ".source.json").read_text(encoding="utf-8"))
                del data[key]
                (self.spec / ".source.json").write_text(json.dumps(data), encoding="utf-8")
                self.assert_fails(f"{key} がありません")

    def test_value_is_not_a_string(self) -> None:
        self.source(commit=["0" * 40])
        self.assert_fails("commit がありません")

    def test_other_source_repository(self) -> None:
        self.source(repository="someone/app-specs")
        self.assert_fails("repository が shariverse/app-specs ではありません")

    def test_commit_must_be_full_sha(self) -> None:
        for value in (self.first[:7], "main", "refs/pull/1/head", self.first.upper(), self.first + "0", f"{self.first}\n", ""):
            with self.subTest(value=value):
                self.source(commit=value)
                self.assert_fails("40 桁の SHA ではありません")


class UntrustedValueTests(VerifyTestCase):
    """.source.json は PR の作者が書ける。値をシェルにも、ログのコマンドにも渡さない。"""

    def setUp(self) -> None:
        super().setUp()
        self.generate(self.first)
        self.marker = Path(self.directory.name) / "INJECTED"
        self.shell = f'$(touch {self.marker}); `touch {self.marker}`; touch {self.marker} #'

    def run_main(self, github: bool = True) -> "tuple[int, str, str]":
        arguments = ["--spec", str(self.spec), "--repository", IOS, "--app-specs", str(self.specs), "--main", "main"]
        environment = {**os.environ, "GITHUB_ACTIONS": "true" if github else "false"}
        stdout, stderr = io.StringIO(), io.StringIO()
        with unittest.mock.patch.dict(os.environ, environment, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = verify.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_shell_characters_are_not_executed(self) -> None:
        for key in ("app", "platform", "commit", "repository"):
            with self.subTest(key=key):
                self.generate(self.first)
                self.source(**{key: self.shell})
                code, _, _ = self.run_main()
                self.assertEqual(code, 1)
                self.assertFalse(self.marker.exists())

    def test_option_like_values_are_not_passed_to_the_generator(self) -> None:
        elsewhere = Path(self.directory.name) / "elsewhere"
        self.source(app=f"--out={elsewhere}", platform="--source-commit=x")
        code, _, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("このリポジトリのものではありません", stderr)
        self.assertFalse(elsewhere.exists())

    def test_newlines_do_not_start_a_log_command(self) -> None:
        self.source(app="x\n::error::fake\r\n::set-output name=commit::fake", platform="ios\n##[error]fake")
        code, stdout, stderr = self.run_main()
        self.assertEqual(code, 1)
        lines = (stdout + stderr).splitlines()
        commands = [line for line in lines if line.startswith("::")]
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[0], "::error title=Spec check::docs/spec/ の app・platform が、このリポジトリのものではありません")
        # PR から来た値は、コマンドの解釈を止めた間に、1 行ずつ出す
        self.assertRegex(commands[1], r"^::stop-commands::[0-9a-f]{32}$")
        self.assertEqual(commands[2], f"::{commands[1].split('::')[2]}::")
        between = lines[lines.index(commands[1]) + 1 : lines.index(commands[2])]
        self.assertTrue(all(line.startswith("- ") for line in between))
        self.assertIn(r"x\n::error::fake\r\n::set-output name=commit::fake", "\n".join(between))
        self.assertTrue(all("fake" not in line for line in lines if line not in between))

    def test_file_names_are_quoted(self) -> None:
        name = "a\n::warning::fake.md"
        try:
            write(self.app, f"docs/spec/{name}", "x")
        except OSError:
            self.skipTest("改行を含む名前のファイルを作れない")
        code, stdout, stderr = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn(r'- 生成したものに無い: "a\n::warning::fake.md"', stderr)
        self.assertNotIn("\n::warning::", stdout + stderr)

    def test_long_values_are_cut(self) -> None:
        self.source(commit="a" * 5000)
        code, _, stderr = self.run_main(github=False)
        self.assertEqual(code, 1)
        self.assertLess(len(stderr), 1000)
        self.assertTrue(stderr.startswith("Spec check: docs/spec/.source.json の commit が 40 桁の SHA ではありません\n"))


class CommandTests(VerifyTestCase):
    def run_main(self, *arguments: str, github: bool = False) -> "tuple[int, str, str]":
        environment = {**os.environ, "GITHUB_ACTIONS": "true" if github else "false"}
        stdout, stderr = io.StringIO(), io.StringIO()
        with unittest.mock.patch.dict(os.environ, environment, clear=True):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = verify.main(["--spec", str(self.spec), "--app-specs", str(self.specs), *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_default_main_is_origin_main(self) -> None:
        """ワークフローは app-specs を checkout するので、main は origin/main として見える。"""
        self.generate(self.first)
        code, _, stderr = self.run_main("--repository", IOS)
        self.assertEqual(code, 2)
        self.assertIn("origin/main がありません", stderr)
        git(self.specs, "update-ref", "refs/remotes/origin/main", self.first)
        code, stdout, _ = self.run_main("--repository", IOS)
        self.assertEqual(code, 0)
        self.assertIn("生成したままです", stdout)

    def test_local_main_ahead_of_origin_is_not_trusted(self) -> None:
        git(self.specs, "update-ref", "refs/remotes/origin/main", self.first)
        self.generate(self.advance_main())
        code, _, stderr = self.run_main("--repository", IOS)
        self.assertEqual(code, 1)
        self.assertIn("main に入っていません", stderr)

    def test_skip_is_a_notice_on_github(self) -> None:
        code, stdout, _ = self.run_main("--repository", IOS, "--main", "main", "--base", "HEAD", github=True)
        self.assertEqual(code, 0)
        self.assertTrue(stdout.startswith("::notice title=Spec check::docs/spec/ がまだありません"))

    def test_spec_outside_a_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = verify.main(["--spec", str(Path(directory) / "docs" / "spec"), "--repository", IOS,
                                    "--app-specs", str(self.specs), "--main", "main"])
        self.assertEqual(code, 2)
        self.assertIn("git の作業ツリーの中にありません", stderr.getvalue())

    def test_does_not_touch_the_app_specs_checkout(self) -> None:
        """元のコミットの中身は一時フォルダに書き出す。app-specs の作業ツリーとインデックスは変えない。"""
        self.generate(self.first)
        self.advance_main()
        before = (git(self.specs, "rev-parse", "HEAD"), git(self.specs, "status", "--porcelain"),
                  git(self.specs, "ls-files", "--stage"))
        code, _, _ = self.run_main("--repository", IOS, "--main", "main")
        self.assertEqual(code, 0)
        after = (git(self.specs, "rev-parse", "HEAD"), git(self.specs, "status", "--porcelain"),
                 git(self.specs, "ls-files", "--stage"))
        self.assertEqual(before, after)


class TemplateTests(unittest.TestCase):
    """各 OS に置くワークフローが、値を run: に埋めずに、このスクリプトを呼ぶ形のままか。"""

    def setUp(self) -> None:
        self.text = (SCRIPTS.parent / "templates" / "spec-check.yml").read_text(encoding="utf-8")

    def test_runs_this_script_from_main(self) -> None:
        self.assertIn("repository: shariverse/app-specs", self.text)
        self.assertIn("ref: main", self.text)
        self.assertIn("python3 app-specs/scripts/verify_spec.py --spec app/docs/spec", self.text)
        self.assertIn('--repository "$GITHUB_REPOSITORY"', self.text)
        self.assertIn("--base 'HEAD^1'", self.text)

    def test_no_expression_in_the_workflow(self) -> None:
        self.assertNotIn("${{", self.text)

    def test_runs_on_every_pull_request_with_read_only_token(self) -> None:
        self.assertNotRegex(self.text, r"(?m)^\s*paths(-ignore)?:")
        self.assertNotIn("pull_request_target", self.text)
        self.assertIn("permissions:\n  contents: read\n", self.text)
        self.assertEqual(self.text.count("persist-credentials: false"), self.text.count("actions/checkout@"))

    def test_actions_are_pinned_to_a_commit(self) -> None:
        uses = [line.split("uses:", 1)[1].split("#")[0].strip() for line in self.text.splitlines() if "uses:" in line]
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
