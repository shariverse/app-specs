# app-specs

Shariverse のアプリの仕様の正。各 OS のリポジトリの `docs/spec/` は、ここから `scripts/generate_spec.py` で生成する。
書き方の決まりは `README.md` の「書き方」。

## 新しい機能を考えるとき

- 先に、そのアプリの `product.md` と `shariverse.md` を読む。原則とぶつかる案は、ぶつかることを提案に書く（黙って原則を曲げない）
- 案は `templates/proposal.md` を写して `proposals/` に書く。いきなり `features/` に書かない
- 作ると決まったら `features/` に `planned` で書き直し、提案は消す。残したい根拠・採らなかった案は `notes/` に移す。`roadmap.md` も合わせる

## 仕様を書くとき

- 共通の文に OS の API・部品の名前を書かない。要るときは `<!-- only: ios -->` で囲むか、`platforms/` に書く
- 片方の OS がまだ作っていないだけの違いは `only` にせず、`status` を `planned` にする。わざと変えたことだけを `only` と `platforms/` に書く
- 片方の OS のリポジトリにしか無い事実（コードの値・挙動）を移すときは、もう片方のリポジトリのコードや仕様と食い違っていないか確かめる。食い違っていたら、どちらかに寄せずに人に聞く
- 決めた経緯・Issue や PR の番号・変更の履歴は書かない
- 振る舞いを決めないもの（長い根拠・測った値・採らなかった案・実装の参考）は `features/` に書かず `notes/` に書く。`notes/` を実装の根拠にしない
- 設計（モジュール・クラスの構成）・ストアの掲載文は書かない。各 OS のリポジトリに置く
- 文言は画面に出すとおりに「」で書く

## 変えたら

```bash
python3 scripts/generate_spec.py write-index
python3 scripts/generate_spec.py check
python3 -m unittest discover -s scripts
```

出力を見たいときは、作業ディレクトリの外に `generate --out` で出して読む。

## 生成スクリプト

- 標準ライブラリだけで書く（CI と各 OS のリポジトリの CI で、何も入れずに動かすため）
- 出力は同じ入力から毎回同じになるようにする（各 OS のリポジトリの Spec check が、生成し直したものと比べるため）
- 元の commit は `.source.json` にだけ書く。各ファイルの注記や URL に書くと、仕様を 1 行変えるたびに全ファイルが変わり、各 OS の作業ブランチどうしがコンフリクトする
- 振る舞いを変えたら `scripts/test_generate_spec.py` にテストを足す
