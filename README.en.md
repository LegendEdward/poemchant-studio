# PoemChant Studio

An offline application for generating, annotating and editing **candidate chant scores for classical Chinese poetry**. It supports four- or eight-line poems with five or seven characters per line. Output includes continuous pitch curves, character durations, pronunciation and historical-tone annotations, editorial notes, SVG, MusicXML, pitch-bend MIDI, instrumental WAV, JSON and CSV.

The public distribution includes an **untrained, transparent rule baseline (R0)**. It does not include the recording-derived research model, training lexicon or recordings. Users with an appropriate local `prosody_v1` model pack can import it to enable the trained duration predictors and coarse pitch templates. The interface and exported provenance distinguish the two modes. R0 must not be described as a trained AI model.

Neither mode is an authenticated reconstruction of a historical intoning tradition. There is no independent expert evaluation of the generated scores. Instrumental previews are not human-voice intoning, and MusicXML represents a note approximation rather than a lossless transcription of the continuous curve.

## Run

The macOS release is self-contained for Apple Silicon, macOS 14+. It has an ad-hoc signature, not an Apple Developer ID signature or notarization. Source builds remain available. No script disables system security settings.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/poemchant-studio
```

For Windows, use the corresponding executables under `.venv\Scripts\`. Source installation requires Internet access to obtain dependencies; subsequent generation is local. Cross-platform source support is not a claim of validation on every platform.

Each save creates a new revision; the original score is retained separately from acoustic edits and editable annotations. Re-inference is explicit and replaces manual acoustic edits in a new revision. Missing pitch stays missing, and editorial caesura marks do not silently create audio gaps. Export a complete `project.poemchant.json` to continue editing later.

## Develop

```sh
.venv/bin/python -m pip install -e '.[build,test]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/collect_licenses.py
.venv/bin/python scripts/make_icon.py
.venv/bin/python scripts/build_macos.py
```

The desktop shell uses Swift/AppKit and WKWebView with a private loopback service. Python and runtime dependencies are bundled in the macOS application. No external inference API, corpus download or telemetry is used at runtime.

Original application code is MIT-licensed. Third-party components retain their respective licenses. See `THIRD_PARTY_NOTICES.md`, `docs/MODELS.md`, `docs/VERIFICATION.md`, and `docs/AI_DISCLOSURE.md`. Codex assisted research design, implementation, execution, checking and documentation; human responsibility for release review remains with the project owner.
