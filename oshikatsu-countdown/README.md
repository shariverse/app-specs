# 推し活カウントダウン 仕様

推し活の予定（推しのライブ・誕生日・発売日など）を登録し、その日まであと何日かを数えるアプリ。

画面デザインの正はデザインキャンバス「推し活カウントダウン 画面デザイン」。デザインから引き継ぐのは機能・文言・配色で、部品と操作感は各 OS の標準に従う。
ただし iOS 版の配色・書体・角の丸み・装飾は、デザインキャンバスから独自のテーマ「地雷系・ゴシック」に置き換えている（[地雷系・ゴシック](design/jirai-gothic.md)）。 <!-- only: ios -->

誰のためのアプリか・守る原則・作らないものは [方針](product.md)。機能を足すときは、先に方針を読む。

## 機能と対応状況

<!-- features:start -->
| 機能 | iOS | Android |
|---|---|---|
| [初回の導線](features/01-onboarding.md) | あり | あり |
| [タブ](features/02-navigation.md) | あり | あり |
| [ホーム](features/03-home.md) | あり | あり |
| [予定の詳細](features/04-event-detail.md) | あり | あり |
| [予定の追加・編集](features/05-event-editor.md) | あり | あり |
| [推しの一覧と登録・編集](features/06-oshi.md) | あり | あり |
| [写真の調整](features/07-photo-crop.md) | あり | 予定 |
| [設定](features/08-settings.md) | あり | あり |
| [通知](features/09-notifications.md) | あり | 予定 |
| [ホーム画面ウィジェット](features/10-home-widgets.md) | あり | あり |
| [ロック画面のカウントダウン](features/11-lock-screen.md) | あり | 予定 |
| [当日のライブアクティビティ](features/12-live-activity.md) | あり | 予定 |
| [シェア](features/13-share.md) | あり | 予定 |
| [推し活カウントダウン Plus](features/14-plus.md) | あり | 予定 |
| [推しの並べ替え](features/15-oshi-order.md) | あり | 予定 |
| [推しの写真ウィジェット](features/16-photo-widget.md) | あり | 予定 |
| [背景・飾りの着せ替え](features/17-dress-up.md) | あり | 予定 |
<!-- features:end -->

## 読む順番

- [方針](product.md)
- [Shariverse の方針](../shariverse.md)（どのアプリにも効く決まり）
- [規則](rules.md)（日付の数え方・並び・文字数など、画面をまたぐ決まり）
- 上の表の機能
- [推し色](design/oshi-colors.md)
- [デザインキャンバスの配色](design/design-canvas.md) <!-- only: android -->
- [地雷系・ゴシック](design/jirai-gothic.md) <!-- only: ios -->
- [iOS 版だけの決定](platforms/ios.md) <!-- only: ios -->
- [Android 版だけの決定](platforms/android.md) <!-- only: android -->

推し色の値と、推しなしの予定の色・推し色を薄く敷くときの割合は [`design/tokens.json`](design/tokens.json) にもある（表と同じ値）。
