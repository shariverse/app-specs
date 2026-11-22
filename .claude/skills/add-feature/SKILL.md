---
name: add-feature
description: app-specs のアプリに、作ると決めた機能の仕様を features/NN-<name>.md として足す。「この機能を features に足して」「提案を仕様にして」「新しい機能の仕様を書いて」のように、アプリに機能の仕様を追加する依頼で使う。まだ作るか決めていない案は features/ に書かず proposals/ に書く。既にある機能の仕様を直すだけのときは使わない。
---

# 機能の仕様を足す

作ると決めた機能を `<app>/features/NN-<name>.md` に `planned` で書き、対応表・ロードマップを合わせ、生成が通るところまでやる。
書き方の決まりの正は `README.md` の「書き方」と `CLAUDE.md`。ここではその手順だけを書く。

## 1. 決まっているかを確かめる

- 対象のアプリ（`apps.json` のキー）と、機能の中身を確かめる。分からなければ聞く
- `<app>/proposals/` に、その機能の提案があるかを見る。あればそれを元にする
- 提案が無く、作ると決まったとも言われていないときは、features/ に書く前に聞く。決まっていなければ `templates/proposal.md` を写して `<app>/proposals/<name>.md` に書き、ここで止める

## 2. 先に読む

- `<app>/product.md` と `shariverse.md`。原則・作らないものとぶつからないか確かめる。ぶつかるときは書き始めず、どこがぶつかるかを伝えて、原則を変えるかを聞く（黙って原則を曲げない）
- `<app>/rules.md` と、関係する既存の `features/`。同じことを決め直さず、規則やほかの機能へリンクする
- 書き方の手本に、既存の `features/` を 1〜2 本読む（見出し・箇条書き・「規則」の表の形をそろえる）

## 3. 書く

ファイル名は `features/NN-<name>.md`。`NN` は今ある最大の番号の次（読む順番なので、間に入れたいときだけ聞く）。`<name>` は英小文字とハイフン。

```markdown
---
status:
  ios: planned
  android: planned
---
# 〈機能の名前〉

何をする機能かを 1〜2 文で。

## 〈画面・中身など〉

## 規則

| 項目 | 規則 |
|---|---|
```

- `status` にはそのアプリの OS をすべて書く。作ると決めたものは `planned`。片方の OS は作るか決めていないなら `undecided`、作らないなら `none`
- 共通の文に OS の API・部品の名前や `pt`・`dp` だけの寸法を書かない。わざと OS で変えることだけを `<!-- only: ios -->` で囲むか `platforms/` に書く。片方がまだ作らないだけなら `only` にしない
- 文言は画面に出すとおりに「」で書く
- 決めた経緯・Issue や PR の番号・変更の履歴は書かない
- 長い根拠・採らなかった案・測った値・実装の参考は `<app>/notes/<topic>.md` に書き、仕様からリンクする
- 配るファイルから `roadmap.md`・`proposals/` へリンクしない
- まだ決まっていない細部は、決めたふりをして埋めない。「作るときにここへ書き足す」と書くか、人に聞く

## 4. まわりを合わせる

- 提案から書き直したときは、`proposals/` の提案を消す。残したい根拠・採らなかった案は `notes/` に移す
- `<app>/roadmap.md` を合わせる（「検討中」から外し、「作っているもの」などに載せる）。時期など分からないことは聞く
- 後で効く決まり（新しく作らないものなど）が出たら、`product.md` に短く足す

## 5. 確かめる

```bash
python3 scripts/generate_spec.py write-index
python3 scripts/generate_spec.py check
python3 -m unittest discover -s scripts
```

落ちたら直して通す。各 OS の出力を見たいときは、作業ディレクトリの外（スクラッチパッドなど）に出して読む。

```bash
python3 scripts/generate_spec.py generate --app <app> --platform ios --out <作業ディレクトリの外>
```

## 6. 伝える

足したファイル・消した提案・直したファイルと、決めずに残したこと・聞きたいことを短く伝える。コミット・push は頼まれるまでしない。
