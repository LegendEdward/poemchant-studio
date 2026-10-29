# 构建与版本核对

源代码发行包包含应用、原生窗口、公开词典、测试和许可，不依赖研究目录，也不附带录音派生模型。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/collect_licenses.py
.venv/bin/python scripts/make_icon.py
.venv/bin/python scripts/build_macos.py
```

原生应用需要 Apple Silicon Mac、macOS 14+ 和 Apple Command Line Tools / Xcode 中的 Swift 编译器。构建过程调用系统 AppKit、WebKit，把 Python 和应用依赖打进 `.app`；运行用户不必装 Python。当前构建没有 Apple Developer ID 签名或公证。

源安装可以在本机浏览器运行，入口 `poemchant-studio`。服务只绑定本机回环地址，自动选择空闲端口；关闭原生窗口退出时会停止附属服务。

生成发行文件：

```sh
.venv/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir dist
.venv/bin/python scripts/make_release.py
```

发行器仅收集明确列出的源码目录，排除 `private/`、模型、稿件、虚拟环境和检查日志。`dist/release-manifest.json` 与 `SHA256SUMS.txt` 记录安装包、源码包和 wheel 的散列。Mac ZIP 使用系统 `ditto`，保留 `.app` 的执行权限与符号链接。

CI 配置提供跨平台源码检查，但在没有看到远程实际运行结果前，不声称 CI 已通过，也不以它代替 Mac 窗口实际操作。软件验收不等于吟诵艺术质量验收。
