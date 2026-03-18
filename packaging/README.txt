Local Whisper Transcriber

このアプリは、音声ファイル・動画ファイル・YouTube URL を文字起こしする
Windows 向けデスクトップアプリです。

対応入力
- 音声ファイル: .mp3 / .wav / .m4a
- 動画ファイル: .mp4 / .mov / .mkv
- YouTube URL

基本的な使い方
1. Local Whisper Transcriber を起動します。
2. 入力方式を選びます。
3. 対象ファイルまたは YouTube URL を指定します。音声・動画ファイルはドラッグ＆ドロップでも指定できます。
4. 言語を選びます。Whisper モデルは small 固定です。
5. 「文字起こし開始」を押します。
6. 処理完了後、結果を確認します。必要に応じて「結果ファイルを出力する」で .txt / .srt / .json を別の場所へ保存できます。

補足
- 音声・動画ファイルの文字起こしはオフラインで利用できます。
- YouTube URL の処理にはインターネット接続が必要です。
- 長いファイルは内部で分割して順番に処理します。
- CPU 版のため、長尺ファイルは処理に時間がかかります。
- installer では同梱の EULA.txt に基づく利用規約同意ページを表示します。
- この配布物には第三者ソフトウェアとモデルが含まれています。詳細は同梱の THIRD_PARTY_LICENSES.txt と licenses フォルダを確認してください。

結果ファイル保存先
- 既定の保存先:
  C:\Users\<ユーザー名>\AppData\Local\local-whisper-transcriber\data\outputs

ログ保存先
- ログファイル:
  C:\Users\<ユーザー名>\AppData\Local\local-whisper-transcriber\logs\app.log

トラブル時
- 処理に失敗した場合は、上記の app.log を確認してください。
- YouTube の取得失敗は、対象動画の公開状態や配信元仕様の影響を受けることがあります。

注意事項
- 対応 OS は Windows 10 / 11 x64 です。
- 初回起動時に Windows の警告が表示される場合があります。
- 本アプリには Whisper small モデル、ffmpeg、ffprobe、yt-dlp が同梱されています。
- 利用規約や独自ライセンスを追加する場合でも、同梱された LGPL/GPL コンポーネントの権利を制限しないよう注意してください。
