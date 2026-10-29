# 吟谱 · PoemChant Studio

[English](README.en.md)

独立运行的古诗候选吟诵谱生成与标注工具。输入五言或七言诗，生成连续曲线谱，逐字编辑读音、调类、字长、音高和备注，保存工程并导出 SVG、MusicXML、MIDI、器乐 WAV、CSV 与 JSON。

**公开版默认使用透明规则 R0，并非训练模型。** 可导入本地 `prosody_v1` 研究模型后使用 M0–M4。来源录音、训练词表和研究模型没有随公开版再分发；两种模式在界面、工程和导出说明中分别标明。生成结果是待审候选，不能据此声称历史吟调复原或专家认可。器乐试听不含人声。

## 开始使用

**Mac 桌面版**：下载发行页中的 `PoemChant-Studio-2.0.0-macOS-arm64.zip`，解压，将「吟谱 PoemChant Studio.app」放到应用程序文件夹后打开。不需要安装 Python；运行和生成不需要网络。当前二进制面向 Apple Silicon、macOS 14 及以上，只有本地临时签名，没有 Apple Developer ID 签名或公证。系统可能要求自行判断开发者信任；本项目不提供关闭系统保护的脚本。也可以从源码构建。

1. 输入题名、作者和四句 / 八句的五言或七言诗，点击「生成吟诵谱」。
2. 在「逐字标注与编辑」选择一个字，编辑数字拼音、历史调类、韵部候选、分节、备注、时长或音高控制点。
3. 点击「保存修改并生成新稿」。原稿保留在「最近保存」中；未保存时导出链接暂停使用。
4. 下载完整工程、标注或曲谱文件。以后通过「打开工程文件」继续编辑。

**源码运行**（Python 3.11+；本机实际验证为 3.12）：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/poemchant-studio
```

Windows 使用 `.venv\Scripts\python.exe` / `.venv\Scripts\poemchant-studio.exe`。首次安装需下载依赖；安装完成后本地使用无须付费 API。Mac 原生窗口仅在 macOS 构建；其他平台源码使用本机浏览器。其他平台的实际可用性须由对应平台检查，不能从 Mac 的检查自动推定。

## 两种生成模式

| 模式 | 随公开版提供 | 方法与适用边界 |
|---|---|---|
| 公开规则 R0 | 是 | 明示字长权重、现代调号轮廓和分节提示；没有训练、没有覆盖保证、没有音乐学验证。 |
| 本地研究模型 | 否；支持导入 | `prosody_v1` 冻结模型；自动标签默认 M2，显式标签条件默认 M3。时长模型来自统计学习，音高使用粗模板；依然是待审候选。 |

本机已有研究模型时，导入模型 ZIP 即可继续使用，不依赖原研究文件夹。应用不下载录音、不训练模型、不把数据上传到服务器。没有导入模型时，不会把 R0 冒充 AI 训练结果。模型导入格式和验证边界见 [模型说明](docs/MODELS.md)。

## 导出与保存

| 文件 | 内容 |
|---|---|
| `project.poemchant.json` | 完整工程、生成原稿、逐字修改、标注和备注，可重开。 |
| `score.svg` | 连续曲线谱、字长、拼音、调类、韵部候选、分节与缺失提示。 |
| `annotations.csv` / `annotations.json` | 逐字标注；CSV 兼容中文表格并防范公式前缀，JSON 保留标注原值。 |
| `score.musicxml` | 自由时间的代表音近似，保留逐字歌词。 |
| `score.mid` / `preview.wav` | 弯音 MIDI / 器乐试听；没有吟诵人声。 |
| `score.project.json` | 底层原生成器兼容工程，不包含新标注层；完整编辑请用上方完整工程。 |
| `manifest.json` / `score-bundle.zip` | 文件散列、导出诊断 / 全部文件打包。 |

每次保存建立一个新版本，不覆盖原稿。修改标注并保存不会静默重算声音；「按当前标注重新生成」会明确询问，并在新稿中重算、替换手工时长和音高。分节符本身不增加字间空档。未知音高保持断开，不自动补成有声曲线。

Mac 数据保存在 `~/Library/Application Support/PoemChant Studio/`；Linux 为 XDG 数据目录，Windows 为 LocalAppData。自动稿件在 `projects/`，可选研究模型在 `model_packs/`。没有遥测或外部推理请求。需要备份时复制完整数据目录或导出工程。

## 开发与验证

```sh
.venv/bin/python -m pip install -e '.[build,test]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/collect_licenses.py
.venv/bin/python scripts/make_icon.py
.venv/bin/python scripts/build_macos.py
```

代码、运行文件与原研究隔离；研究冻结结果没有被部署修改。测试覆盖原稿保留、工程重开、缺失音高、真实 MIDI/XML/WAV 回读、标注一致性、非法输入和 ZIP 路径限制；测试通过不等于艺术质量验证。实际检查记录见 [验证说明](docs/VERIFICATION.md)。

## 来源、许可与贡献

本项目原创应用代码为 MIT，第三方依赖和词典保留各自许可，见 [第三方说明](THIRD_PARTY_NOTICES.md) 与 `licenses/`。源录音、训练词表、已有研究模型及私人论文材料不在公开仓库或安装包中，应用代码的 MIT 不能替它们授权。

研究背景参考 Zuo et al., *Intoner: For Chinese Poetry Intoning Synthesis*, IJCAI 2025, [doi:10.24963/ijcai.2025/1139](https://doi.org/10.24963/ijcai.2025/1139)。本项目不是 Intoner 官方产品，没有声称首次实现古诗吟诵生成。

Codex 参与设计、实现、检查与文档编写，详见 [AI 参与说明](docs/AI_DISCLOSURE.md)。欢迎提交可重现问题、读音依据或改进建议；不能将用户反馈自动当作本研究的受试者或专家评测数据。
