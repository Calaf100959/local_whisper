# Local Whisper Transcriber

Windows 向けのローカル文字起こしデスクトップアプリです。`faster-whisper` を CPU モードで使い、音声ファイル、動画ファイル、YouTube URL を入力として `.txt` / `.srt` / `.json` を出力します。

## 機能
- 音声入力: `.mp3` / `.wav` / `.m4a`
- 動画入力: `.mp4` / `.mov` / `.mkv`
- YouTube URL 入力
- Whisper `base` / `small` モデルを使った文字起こし
- 長尺ファイルのチャンク分割処理
- 進捗表示、完了予定時刻表示、途中停止
- 音声/動画ファイルのドラッグ＆ドロップ入力
- `.txt` / `.srt` / `.json` 出力
- 話者分離オプションと話者数指定

## 動作前提
- Windows 10 / 11 x64
- Python 3.11 以上
- CPU 実行

## 開発環境セットアップ
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -e .[dev]
```

## デスクトップアプリの起動
```powershell
.\.venv\Scripts\python.exe -m app.desktop.main
```

または:

```powershell
.\.venv\Scripts\local-whisper-desktop.exe
```

## 配布用アセット
GitHub には外部バイナリと Whisper モデル本体を含めていません。配布ビルド前に以下を取得してください。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download_bundle_assets.ps1
```

配置先:
- `resources/bin/ffmpeg.exe`
- `resources/bin/ffprobe.exe`
- `resources/bin/yt-dlp.exe`
- `resources/models/base/model.bin`
- `resources/models/small/model.bin`
- `resources/models/speechbrain-spkrec-ecapa-voxceleb/hyperparams.yaml` ほか一式

詳細は `docs/distribution-guide.md` を参照してください。

## 配布物の作成
デスクトップ配布物を作る:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

Windows installer を作る:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
```

出力先:
- `dist/LocalWhisperTranscriber`
- `dist/installer/LocalWhisperSetup-<version>-x64.exe`

配布物には以下も同梱されます。
- `README.txt`
- `EULA.txt`
- `THIRD_PARTY_LICENSES.txt`
- `licenses/`

## 使い方
1. アプリを起動する
2. 入力方式を選ぶ
3. ファイルまたは YouTube URL を指定する
   ローカルファイルはウィンドウへドラッグ＆ドロップでも指定できます
4. モデルと言語を選ぶ
5. 必要に応じて `話者分離を有効化` と `話者数` を設定する
6. `文字起こし開始` を押す
7. 結果を確認する。必要に応じて `結果ファイルを出力する` で `.txt` / `.srt` / `.json` を別の場所へコピーする

## 出力先
- 開発実行時: `data/outputs`
- インストール版: `%LOCALAPPDATA%\\local-whisper-transcriber\\data\\outputs`

ログ:
- 開発実行時: `data/logs`
- インストール版: `%LOCALAPPDATA%\\local-whisper-transcriber\\logs\\app.log`

## テスト
```powershell
py -m unittest discover -s tests -p "*_unittest.py" -v
```

## 注意事項
- 現行版は CPU 専用です
- 長尺ファイルは処理に時間がかかります
- YouTube 入力はネット接続が必要です
- 話者分離は `Silero VAD + SpeechBrain + clustering` で動作します
- GPU 対応は未実装です
- 配布版には第三者ソフトウェアと `base` / `small` モデルが含まれます。詳細は `THIRD_PARTY_LICENSES.txt` と `licenses/` を参照してください
- installer では `EULA.txt` に基づく利用規約同意ページを表示します
