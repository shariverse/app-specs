# 推し活カウントダウン ロードマップ

次に作るものと、検討中のもの。各 OS の `docs/spec/` には配らない。
作ると決めたものは `features/` に `planned` で書き、実装がその OS の既定のブランチに入ったら `shipped` にする（[機能と対応状況](README.md#機能と対応状況)）。

## 作っているもの

| 機能 | iOS | Android |
|---|---|---|
| [推し活カウントダウン Plus](features/14-plus.md)（課金の仕組みと課金画面） | 実装済み。1.3.0 で出す | 時期は未定 |
| [推しの写真ウィジェット](features/16-photo-widget.md) | 実装済み。1.3.0 で出す | 時期は未定 |
| [背景・飾りの着せ替え](features/17-dress-up.md) | 実装済み。1.3.0 で出す | 時期は未定 |
| [シェア](features/13-share.md) | 実装済み。1.3.0 で出す | 時期は未定 |
| [残り時間のタイル](features/19-countdown-tiles.md)（予定の詳細の残りの見せ方） | 実装済み。1.4.0 で出す | 時期は未定 |

## Android 版で追いつくもの

iOS 版で先に出したもの。順番は決めていない。

- [通知](features/09-notifications.md)
- [写真の調整](features/07-photo-crop.md)
- [推しの並べ替え](features/15-oshi-order.md)
- [ロック画面のカウントダウン](features/11-lock-screen.md)（Android の端末のどこに置くかから決める）
- [当日のライブアクティビティ](features/12-live-activity.md)（Android での形から決める）

## 検討中

- Android 版に [地雷系・ゴシック](design/jirai-gothic.md) を入れるか（1 位の推しの推し色で染めるテーマカラーを含む）
- Android 版のホームの見出しを、iOS 版と同じくタイトルの文字を出さない形にするか（[ホーム](features/03-home.md)）

新しい機能の提案は [`proposals/`](proposals/)。書き方は [ひな形](../templates/proposal.md)。

## 作らないと決めたもの

[方針](product.md#作らないもの)を見る。
