# Third-party sources and notices

Original PoemChant Studio application code is MIT-licensed. Dependency software, dictionary transcriptions and runtime components retain their own notices. The application license does **not** grant rights to external recordings, intoners' performances, trained model packs or private research materials.

| Component | Version / source | Notice |
|---|---|---|
| pypinyin | 0.55.0 | MIT; installed distribution notices in `licenses/`. Pronunciation predictions are candidates, not verified readings. |
| OpenCC Python reimplementation | 0.1.7 | Apache-2.0; installed distribution notice. No text conversion is silently applied to the user's poem. |
| NumPy and bundled native dependencies | 2.3.5 | NumPy BSD and bundled-library notices in `licenses/`; retained with the native app. |
| Python | Runtime build used for the binary | PSF and included historical notices in `licenses/Python_LICENSE.txt`. |
| PyInstaller | 6.22.0 | GPL with bootloader exception and applicable Apache portions; notices retained. The tool is used for packaging, not model inference. |
| Packaging / macholib / altgraph / hook collection | Exact build versions in dependency manifest | Their individual notices are included. |
| Pingshui rhyme transcription | [charlesix59/chinese_word_rhyme](https://github.com/charlesix59/chinese_word_rhyme), commit `ff0e9c13fb037c43e0eaa5dc929c0fe4fa2ffb18` | Upstream declares MIT; full notice retained in `licenses/chinese_word_rhyme_LICENSE.txt`. The upstream attributes rhyme text to Wikisource. This is a secondary machine-readable transcription, not a critical edition. |

The Pingshui resource SHA-256 is `fd11164ca1b848eb6b777688d5d6628ce772d72d0a25a0efd12d6b58459c6e2e`. Character membership is not a contextual pronunciation decision, and orthographic lookup proxies are not a reconstruction of historical phonology.

Research background: Zuo, Heda; Sun, Liyao; Lai, Zeyu; You, Weitao; Chen, Pei; Sun, Lingyun (2025). *Intoner: For Chinese Poetry Intoning Synthesis*. IJCAI, pp. 10252–10260. [DOI](https://doi.org/10.24963/ijcai.2025/1139); [author-associated repository](https://github.com/CSpringleaf/Intoner). The observed repository MIT notice is retained as `licenses/Intoner_MIT.txt` for attribution context; it is not treated as permission to redistribute a separate recording dataset. This application does not bundle Intoner neural checkpoints, its recording dataset, or a human voice clone.

The app icon is drawn by `scripts/make_icon.py`. No external artwork or system font file is redistributed for the icon. Ancient poem examples are short public-domain texts, provided as input examples rather than a critically edited corpus.
