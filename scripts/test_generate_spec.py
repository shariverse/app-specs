import contextlib
import io
import json
import tempfile
import textwrap
import unittest
from pathlib import Path

import generate_spec as spec


def write(root: Path, path: str, text: str) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


class FixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.original_root = spec.ROOT
        spec.ROOT = self.root
        write(
            self.root,
            "apps.json",
            json.dumps(
                {
                    "sample-app": {
                        "name": "サンプル",
                        "repositories": {"ios": "shariverse/sample-app-ios", "android": "shariverse/sample-app-android"},
                    }
                }
            ),
        )
        write(
            self.root,
            "sample-app/README.md",
            """
            # サンプル

            <!-- features:start -->
            <!-- features:end -->

            - [規則](rules.md)
            - [iOS のテーマ](design/theme.md) <!-- only: ios -->
            - [この OS だけの決定](platforms/ios.md) <!-- only: ios -->
            - [この OS だけの決定](platforms/android.md) <!-- only: android -->
            - [全体の README](../README.md)
            """,
        )
        write(self.root, "sample-app/rules.md", "# 規則\n\n[ホーム](features/01-home.md#並び)\n")
        write(
            self.root,
            "sample-app/features/01-home.md",
            """
            # ホーム

            共通の段落。

            <!-- only: android -->
            Android だけの段落。
            <!-- /only -->

            | 項目 | 内容 |
            |---|---|
            | 共通 | どちらも |
            | 数 | 64 件まで | <!-- only: ios -->
            """,
        )
        write(
            self.root,
            "sample-app/features/02-crop.md",
            """
            ---
            status:
              ios: shipped
              android: planned
            ---
            # 写真の調整

            本文。
            """,
        )
        write(
            self.root,
            "sample-app/features/03-live.md",
            """
            ---
            status:
              ios: shipped
              android: undecided
            ---
            # ライブアクティビティ
            """,
        )
        write(
            self.root,
            "sample-app/design/theme.md",
            """
            ---
            status:
              ios: shipped
              android: none
            ---
            # iOS のテーマ
            """,
        )
        write(self.root, "sample-app/design/tokens.json", '{"pink": "#C8326A"}\n')
        write(self.root, "sample-app/platforms/ios.md", "# iOS 版\n\n[ホーム](../features/01-home.md)\n")
        write(self.root, "sample-app/platforms/android.md", "# Android 版\n\n[規則](../rules.md)\n")
        write(self.root, "README.md", "# app-specs\n")
        write(self.root, "sample-app/product.md", "# 方針\n\n[全体の方針](../shariverse.md)\n")
        write(self.root, "sample-app/roadmap.md", "# ロードマップ\n\n[案](proposals/idea.md)\n")
        write(self.root, "sample-app/proposals/idea.md", "# 案\n\n[ホーム](../features/01-home.md)\n")
        write(self.root, "sample-app/proposals/sketch.svg", "<svg/>\n")
        write(self.root, "sample-app/notes/crop.md", "# 写真の調整の補足\n\n[写真の調整](../features/02-crop.md)\n")
        write(
            self.root,
            "shariverse.md",
            """
            # Shariverse の方針

            共通。
            タッチ領域は 44pt 以上。 <!-- only: ios -->
            """,
        )
        self.app = spec.load_apps()["sample-app"]

    def tearDown(self) -> None:
        spec.ROOT = self.original_root
        self.directory.cleanup()

    def render(self, platform: str) -> dict[str, str]:
        files = spec.render(self.app, platform, "abc1234")
        return {path: content.decode("utf-8") for path, content in files.items()}


class RenderTests(FixtureTestCase):
    def test_android_keeps_only_android_parts(self) -> None:
        home = self.render("android")["features/01-home.md"]
        self.assertIn("Android だけの段落。", home)
        self.assertNotIn("64 件まで", home)
        self.assertNotIn("<!-- only", home)

    def test_ios_keeps_only_ios_parts(self) -> None:
        home = self.render("ios")["features/01-home.md"]
        self.assertNotIn("Android だけの段落。", home)
        self.assertIn("| 数 | 64 件まで |\n", home)

    def test_excludes_undecided_and_none(self) -> None:
        files = self.render("android")
        self.assertNotIn("features/03-live.md", files)
        self.assertNotIn("design/theme.md", files)
        self.assertIn("design/theme.md", self.render("ios"))

    def test_planned_has_notice(self) -> None:
        crop = self.render("android")["features/02-crop.md"]
        self.assertIn("# 写真の調整\n\n> [!NOTE]\n> Android 版では、まだ作っていない（予定）。\n\n本文。", crop)
        self.assertNotIn("[!NOTE]", self.render("ios")["features/02-crop.md"])

    def test_platform_file_becomes_platform_md(self) -> None:
        files = self.render("ios")
        self.assertIn("platform.md", files)
        self.assertNotIn("platforms/ios.md", files)
        self.assertNotIn("platforms/android.md", files)
        self.assertIn("[ホーム](features/01-home.md)", files["platform.md"])

    def test_links_are_rewritten(self) -> None:
        files = self.render("android")
        self.assertIn("[この OS だけの決定](platform.md)", files["README.md"])
        self.assertIn("[ホーム](features/01-home.md#並び)", files["rules.md"])
        self.assertIn(
            "[全体の README](https://github.com/shariverse/app-specs/blob/abc1234/README.md)", files["README.md"]
        )

    def test_links_with_title_are_rewritten(self) -> None:
        write(
            self.root,
            "sample-app/platforms/ios.md",
            "# iOS 版\n\n[ホーム](../features/01-home.md \"ホームの仕様\") [補足](../notes/crop.md#理由 '補足')\n",
        )
        platform = self.render("ios")["platform.md"]
        self.assertIn('[ホーム](features/01-home.md "ホームの仕様")', platform)
        self.assertRegex(platform, r"\[補足\]\(https://github\.com/\S+/sample-app/notes/crop\.md#理由 '補足'\)")

    def test_link_with_title_to_excluded_file_fails(self) -> None:
        write(self.root, "sample-app/rules.md", '# 規則\n\n[テーマ](design/theme.md "テーマ")\n')
        with self.assertRaisesRegex(spec.SpecError, "Android 版の docs/spec/ に出さないファイルへのリンク"):
            self.render("android")

    def test_relative_links_in_unsupported_forms_fail(self) -> None:
        cases = {
            "[この OS だけの決定][p]\n\n[p]: platforms/android.md\n": "参照式のリンク（\\[名前\\]: リンク先）は、相対パスでは書けません.*: platforms/android.md",
            "[次に作るもの][r]\n\n   [r]: roadmap.md\n": "参照式のリンク.*: roadmap.md",
            "[補足](<notes/crop.md>)\n": "<> で囲んだリンク先は、相対パスでは書けません.*: notes/crop.md",
            "[テーマ](<design/my theme.md>)\n": "<> で囲んだリンク先.*: design/my theme.md",
            '<a href="features/01-home.md">ホーム</a>\n': "HTML のリンク（href・src）は、相対パスでは書けません.*: features/01-home.md",
            "<IMG alt='図' SRC = 'design/tokens.json'>\n": "HTML のリンク.*: design/tokens.json",
        }
        for text, message in cases.items():
            with self.subTest(text=text):
                write(self.root, "sample-app/rules.md", "# 規則\n\n" + text)
                with self.assertRaisesRegex(spec.SpecError, "^sample-app/rules.md: " + message):
                    self.render("android")

    def test_urls_and_code_in_unsupported_forms_pass(self) -> None:
        text = (
            "# 規則\n\n[外][e] [図](<https://example.com/a b>) <a href=\"https://example.com/\">外</a> <a href='#並び'>並び</a>\n"
            "脚注[^1]。参照式は `[p]: platforms/ios.md` と書かない。<a name=\"並び\"></a> <a 閉じていない\n\n"
            "[e]: https://example.com/\n[^1]: 脚注の文。\n\n```html\n<img src=\"design/none.png\">\n[p]: none.md\n```\n"
        )
        write(self.root, "sample-app/rules.md", text)
        self.assertEqual(self.render("android")["rules.md"].split("-->\n\n", 1)[1], text)

    def test_shared_file_rejects_relative_links_in_unsupported_forms(self) -> None:
        for text in ("[アプリ][a]\n\n[a]: sample-app/README.md\n", '<a href="sample-app/README.md">アプリ</a>\n'):
            with self.subTest(text=text):
                write(self.root, "shariverse.md", "# 方針\n\n" + text)
                with self.assertRaisesRegex(spec.SpecError, "shariverse.md: .*相対リンクは書けません（URL にする）: sample-app/README.md"):
                    self.render("ios")

    def test_platform_index(self) -> None:
        readme = self.render("android")["README.md"]
        self.assertIn("| [ホーム](features/01-home.md) | あり |", readme)
        self.assertIn("| [写真の調整](features/02-crop.md) | 予定 |", readme)
        self.assertIn("| ライブアクティビティ | 未定 |", readme)
        self.assertNotIn("features:start", readme)
        self.assertIn("\n# サンプル（Android 版）\n", readme)

    def test_header_and_source(self) -> None:
        files = self.render("ios")
        self.assertTrue(files["rules.md"].startswith("<!--\n  app-specs から生成したファイル。直接編集しない。"))
        self.assertIn("shariverse/app-specs@abc1234 sample-app/rules.md", files["rules.md"])
        self.assertEqual(json.loads(files[".source.json"])["commit"], "abc1234")
        self.assertEqual(files["design/tokens.json"], '{"pink": "#C8326A"}\n')

    def test_link_to_excluded_file_fails(self) -> None:
        write(self.root, "sample-app/rules.md", "# 規則\n\n[テーマ](design/theme.md)\n")
        with self.assertRaisesRegex(spec.SpecError, "Android 版の docs/spec/ に出さないファイルへのリンク"):
            self.render("android")

    def test_missing_link_target_fails(self) -> None:
        write(self.root, "sample-app/rules.md", "# 規則\n\n[無い](features/99-none.md)\n")
        with self.assertRaisesRegex(spec.SpecError, "リンク先がありません"):
            self.render("ios")

    def test_roadmap_and_proposals_are_not_distributed(self) -> None:
        files = self.render("ios")
        self.assertNotIn("roadmap.md", files)
        self.assertFalse([path for path in files if path.startswith("proposals/")])
        self.assertIn("product.md", files)

    def test_notes_are_linked_by_url(self) -> None:
        write(self.root, "sample-app/features/02-crop.md", "# 写真の調整\n\n[補足](../notes/crop.md#理由)\n")
        files = self.render("android")
        self.assertFalse([path for path in files if path.startswith("notes/")])
        self.assertIn(
            "[補足](https://github.com/shariverse/app-specs/blob/abc1234/sample-app/notes/crop.md#理由)",
            files["features/02-crop.md"],
        )

    def test_link_to_roadmap_fails(self) -> None:
        write(self.root, "sample-app/rules.md", "# 規則\n\n[次に作るもの](roadmap.md)\n")
        with self.assertRaisesRegex(spec.SpecError, "roadmap.md・proposals/ へはリンクしない"):
            self.render("ios")

    def test_shared_file_is_distributed(self) -> None:
        files = self.render("android")
        self.assertIn("共通。", files["shariverse.md"])
        self.assertNotIn("44pt", files["shariverse.md"])
        self.assertIn("44pt", self.render("ios")["shariverse.md"])
        self.assertIn("[全体の方針](shariverse.md)", files["product.md"])

    def test_shared_file_may_mention_platforms_the_app_does_not_have(self) -> None:
        write(self.root, "apps.json", json.dumps({"solo-app": {"name": "iOS だけ", "repositories": {"ios": "shariverse/solo-app-ios"}}}))
        write(self.root, "solo-app/README.md", "# iOS だけ\n\n<!-- features:start -->\n<!-- features:end -->\n")
        write(self.root, "solo-app/platforms/ios.md", "# iOS 版\n")
        write(self.root, "shariverse.md", "# 方針\n\n44pt 以上。 <!-- only: ios -->\n48dp 以上。 <!-- only: android -->\n")
        shared = spec.render(spec.load_apps()["solo-app"], "ios", "abc1234")["shariverse.md"].decode("utf-8")
        self.assertIn("44pt 以上。\n", shared)
        self.assertNotIn("48dp", shared)

    def test_shared_file_rejects_unknown_platform(self) -> None:
        write(self.root, "shariverse.md", "# 方針\n\nWeb だけ。 <!-- only: web -->\n")
        with self.assertRaisesRegex(spec.SpecError, "shariverse.md:3: only に知らない OS"):
            self.render("ios")

    def test_shared_file_rejects_relative_links(self) -> None:
        write(self.root, "shariverse.md", "# 方針\n\n[アプリ](sample-app/README.md)\n")
        with self.assertRaisesRegex(spec.SpecError, "相対リンクは書けません"):
            self.render("ios")

    def test_undistributed_links_are_checked(self) -> None:
        documents = spec.load_documents(self.app)
        self.assertEqual(spec.check_undistributed_links(self.app, documents), [])
        write(self.root, "sample-app/proposals/idea.md", "# 案\n\n[無い](../features/99-none.md)\n")
        errors = spec.check_undistributed_links(self.app, spec.load_documents(self.app))
        self.assertEqual(errors, ["sample-app/proposals/idea.md: リンク先がありません: ../features/99-none.md"])

    def test_feature_without_title_fails_with_app_name(self) -> None:
        write(self.root, "sample-app/features/01-home.md", "   # 字下げした題は、見出しにならない\n\n本文。\n")
        with self.assertRaisesRegex(spec.SpecError, "^sample-app/features/01-home.md: 先頭の見出し（# ）がありません"):
            spec.readme_with_index(self.app)

    def test_full_index(self) -> None:
        _, expected = spec.readme_with_index(self.app)
        self.assertIn("| 機能 | iOS | Android |", expected)
        self.assertIn("| [写真の調整](features/02-crop.md) | あり | 予定 |", expected)


class FilterTests(unittest.TestCase):
    def filter(self, text: str, platform: str = "ios") -> str:
        return spec.filter_platform("a.md", textwrap.dedent(text), platform, ["ios", "android"])

    def test_multiple_platforms(self) -> None:
        self.assertIn("両方", self.filter("<!-- only: ios, android -->\n両方\n<!-- /only -->\n"))

    def test_nested_block_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "only の中に only"):
            self.filter("<!-- only: ios -->\n<!-- only: ios -->\n<!-- /only -->\n<!-- /only -->\n")

    def test_line_mark_in_block_fails(self) -> None:
        text = "<!-- only: ios -->\n共通\n- a <!-- only: android -->\n<!-- /only -->\n"
        for platform in ("ios", "android"):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(spec.SpecError, "^a.md:3: only の中に only は書けません（1 行目から）"):
                    self.filter(text, platform)

    def test_unclosed_block_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "閉じていません"):
            self.filter("<!-- only: ios -->\n本文\n")

    def test_unknown_platform_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "知らない OS"):
            self.filter("本文 <!-- only: web -->\n")

    def test_collapses_blank_lines(self) -> None:
        self.assertEqual(self.filter("前\n\n<!-- only: android -->\n消える\n<!-- /only -->\n\n後\n"), "前\n\n後\n")

    def test_malformed_mark_fails(self) -> None:
        for text in (
            "| 数 | 64 件まで | <!-- only: iOS -->\n",
            "- iOS だけ <!-- only ios -->\n",
            "- iOS だけ <!-- only: ios -->。\n",
            "a <!-- only: ios --> b\n",
            "<!-- Only: android -->\nAndroid だけ\n",
            "<!-- only: ios -->\n本文\n<!-- /only -->\n<!-- / only -->\n",
            "本文 <!-- /only -->\n",
            "<!-- only: android -->\n- Android だけ <!-- only Android -->\n<!-- /only -->\n",
        ):
            for platform in ("ios", "android"):
                with self.subTest(text=text, platform=platform):
                    with self.assertRaisesRegex(spec.SpecError, "only の印の形が違います"):
                        self.filter(text, platform)

    def test_malformed_mark_reports_the_line(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "^a.md:3: only の印の形が違います"):
            self.filter("本文\n\n- iOS だけ <!-- only: iOS -->\n")

    def test_mark_in_inline_code_is_not_a_mark(self) -> None:
        text = "OS で分けるときは `<!-- only: iOS -->` のように書かず、`<!-- only: ios -->` と書く。\n"
        self.assertEqual(self.filter(text), text)


class FrontMatterTests(unittest.TestCase):
    def test_default_is_shipped(self) -> None:
        status, body = spec.parse_front_matter("a.md", "# 題\n", ["ios", "android"])
        self.assertEqual(status, {"ios": "shipped", "android": "shipped"})
        self.assertEqual(body, "# 題\n")

    def test_front_matter_not_at_the_top_fails(self) -> None:
        front_matter = "---\nstatus:\n  ios: planned\n  android: none\n---\n# 題\n"
        for text in ("\n" + front_matter, "\ufeff" + front_matter, "--- " + front_matter[3:], "  \n\n" + front_matter):
            with self.subTest(text=text):
                with self.assertRaisesRegex(spec.SpecError, "a.md: front matter は 1 行目の先頭から"):
                    spec.parse_front_matter("a.md", text, ["ios", "android"])

    def test_horizontal_rule_is_not_front_matter(self) -> None:
        text = "# 題\n\n---\n\nstatus: の書き方\n"
        self.assertEqual(spec.parse_front_matter("a.md", text, ["ios"]), ({"ios": "shipped"}, text))
        text = "\n---\n\n本文\n"
        self.assertEqual(spec.parse_front_matter("a.md", text, ["ios"]), ({"ios": "shipped"}, text))

    def test_missing_platform_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "すべて書きます"):
            spec.parse_front_matter("a.md", "---\nstatus:\n  ios: shipped\n---\n# 題\n", ["ios", "android"])

    def test_duplicated_platform_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "a.md: status に ios が 2 回あります"):
            spec.parse_front_matter(
                "a.md", "---\nstatus:\n  ios: planned\n  ios: none\n  android: none\n---\n# 題\n", ["ios", "android"]
            )

    def test_unknown_status_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "書けません"):
            spec.parse_front_matter(
                "a.md", "---\nstatus:\n  ios: done\n  android: none\n---\n# 題\n", ["ios", "android"]
            )


class WriteOutputTests(unittest.TestCase):
    def test_refuses_to_replace_handwritten_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "spec"
            out.mkdir()
            (out / "README.md").write_text("手書き", encoding="utf-8")
            with self.assertRaisesRegex(spec.SpecError, "生成したものではない"):
                spec.write_output(out, {"README.md": b"x"})

    def test_replaces_generated_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "spec"
            spec.write_output(out, {spec.SOURCE_FILE: b"{}", "old.md": b"x"})
            spec.write_output(out, {spec.SOURCE_FILE: b"{}", "new.md": b"y"})
            self.assertFalse((out / "old.md").exists())
            self.assertTrue((out / "new.md").exists())


class CodeTests(FixtureTestCase):
    """コードブロックとインラインコードの中は、書いたとおりに出す。"""

    def filter(self, text: str, platform: str = "ios") -> str:
        return spec.filter_platform("a.md", text, platform, ["ios", "android"])

    def test_only_marks_in_code_block_are_kept(self) -> None:
        text = "書き方:\n\n```markdown\n<!-- only: android -->\nAndroid だけ\n<!-- /only -->\n| 数 | 64 | <!-- only: ios -->\n```\n"
        self.assertEqual(self.filter(text, "ios"), text)
        self.assertEqual(self.filter(text, "android"), text)

    def test_blank_lines_in_code_block_are_kept(self) -> None:
        self.assertEqual(self.filter("前\n\n\n\n~~~\na\n\n\n\nb\n~~~\n\n\n後\n"), "前\n\n~~~\na\n\n\n\nb\n~~~\n\n後\n")

    def test_code_block_in_only_block_follows_the_block(self) -> None:
        text = "<!-- only: android -->\n```kotlin\nval a = 1\n```\n<!-- /only -->\n共通\n"
        self.assertEqual(self.filter(text, "ios"), "共通\n")
        self.assertEqual(self.filter(text, "android"), "```kotlin\nval a = 1\n```\n共通\n")

    def test_code_block_closes_only_with_the_same_mark(self) -> None:
        text = "````\n```\n<!-- only: android -->\n```\n````\n本文 <!-- only: android -->\n"
        self.assertEqual(self.filter(text, "ios"), "````\n```\n<!-- only: android -->\n```\n````\n")

    def test_unclosed_code_block_fails(self) -> None:
        with self.assertRaisesRegex(spec.SpecError, "a.md:2: コードブロック（```）が閉じていません"):
            self.filter("本文\n```swift\nlet a = 1\n")

    def test_links_in_code_are_not_rewritten(self) -> None:
        write(
            self.root,
            "sample-app/platforms/ios.md",
            "# iOS 版\n\nリンクは `[文字](パス)` と書く。[ホーム](../features/01-home.md)\n\n"
            "```swift\nlet x = handlers[index](value)\n[無い](none.md)\n```\n",
        )
        platform = self.render("ios")["platform.md"]
        self.assertIn("リンクは `[文字](パス)` と書く。[ホーム](features/01-home.md)", platform)
        self.assertIn("```swift\nlet x = handlers[index](value)\n[無い](none.md)\n```", platform)

    def test_links_in_code_are_not_checked_in_shared_and_undistributed_files(self) -> None:
        write(self.root, "shariverse.md", "# 方針\n\n`[文字](パス)` と書く。\n")
        write(self.root, "sample-app/notes/crop.md", "# 補足\n\n```\n[無い](none.md)\n```\n")
        self.assertIn("`[文字](パス)`", self.render("ios")["shariverse.md"])
        self.assertEqual(spec.check_undistributed_links(self.app, spec.load_documents(self.app)), [])


class AppsTests(FixtureTestCase):
    def apps(self, data: object) -> None:
        (self.root / "apps.json").write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")

    def test_targets(self) -> None:
        self.assertEqual(
            spec.targets(spec.load_apps()),
            [
                {
                    "app": "sample-app",
                    "platform": "ios",
                    "repository": "shariverse/sample-app-ios",
                    "repository_name": "sample-app-ios",
                },
                {
                    "app": "sample-app",
                    "platform": "android",
                    "repository": "shariverse/sample-app-android",
                    "repository_name": "sample-app-android",
                },
            ],
        )

    def test_malformed_apps_fail(self) -> None:
        repositories = {"ios": "shariverse/sample-app-ios"}
        cases = [
            ("{broken", "apps.json を読めません"),
            (["sample-app"], "いちばん外は"),
            ({"sample-app": "shariverse/sample-app-ios"}, "sample-app に name"),
            ({"sample-app": {"repositories": repositories}}, "sample-app に name"),
            ({"sample-app": {"name": " ", "repositories": repositories}}, "sample-app に name"),
            ({"sample-app": {"name": "サンプル"}}, "sample-app に repositories"),
            ({"sample-app": {"name": "サンプル", "repositories": {}}}, "sample-app に repositories"),
            ({"sample-app": {"name": "サンプル", "repositories": ["shariverse/sample-app-ios"]}}, "sample-app に repositories"),
            ({"sample-app": {"name": "サンプル", "repositories": {"web": "shariverse/sample-app-web"}}}, "知らない OS"),
            ({"sample-app": {"name": "サンプル", "repositories": {"ios": "sample-app-ios"}}}, "ios のリポジトリは owner/name の形"),
            ({"sample-app": {"name": "サンプル", "repositories": {"ios": "shariverse/sample/app"}}}, "owner/name の形"),
            ({"sample-app": {"name": "サンプル", "repositories": {"ios": None}}}, "owner/name の形"),
        ]
        for data, message in cases:
            with self.subTest(data=data):
                self.apps(data)
                with self.assertRaisesRegex(spec.SpecError, message):
                    spec.load_apps()

    def test_check_fails_on_malformed_apps(self) -> None:
        # 前は check が通り、main に入ってから Sync の targets が IndexError で落ちた
        self.apps({"sample-app": {"name": "サンプル", "repositories": {"ios": "sample-app-ios"}}})
        for command in ("check", "targets"):
            with self.subTest(command=command):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(spec.main([command]), 1)
                self.assertIn("owner/name の形", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
