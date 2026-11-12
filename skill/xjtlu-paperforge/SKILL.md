---
name: xjtlu-paperforge
description: "打开 XJTLUPaperForge 本地试卷工作台，让用户输入西交利物浦大学 XJTLU 课程编号并导出校验过的 PDF。用于在支持终端和本地文件的 Skill 工具中安装、调用、迁移应用，以及用户明确要求的批量导出。"
---

# XJTLUPaperForge

## 默认：打开应用

用户说“调用这个 skill”“打开试卷工作台”或希望在界面输入课程时，先读取本 skill 目录中的 `installation.json`：若其中 `launcher` 指向存在的应用包可执行文件，直接运行它，不需要系统 Python。没有有效 `launcher` 时，运行本 skill 目录中的 `scripts/launch.py` 使用源码安装。不要先在聊天里追问课程编号。

这是普通 `SKILL.md` 加本地启动器，不调用 Codex 专有 API。Codex 可用 `$xjtlu-paperforge`；Claude Code 可用 `/xjtlu-paperforge`。其他工具必须具备本机终端、文件访问和本地浏览器能力；纯聊天或云端沙箱不能因此控制用户电脑，不能承诺仅上传本 Skill 就会弹出本机界面。

应用包启动器和源码启动器都会检查服务就绪。源码启动器需要系统 Python 3.10+，根据安装记录定位项目并调用该项目的虚拟环境。成功时返回本地地址；不要只根据进程已创建就宣称界面可用。把该地址提供给用户，并说明在界面填写课程编号即可。

`python scripts/launch.py` 中的相对路径须先按此 SKILL.md 所在目录展开为绝对路径。Windows 可用 `py -3.12`，macOS / Linux 可用 `python3`，或当前已确认的 Python 解释器。启动器正常情况下自动打开浏览器；调试时可传 `--no-browser`，仅查询安装位置可传 `--print-root`。

首次使用，用户在界面点击“开始整理试卷”后，后台打开学校专用浏览器（默认 Chrome），请用户直接在学校页面完成登录。账号密码不进入聊天。登录完成后自动处理所选课程，界面显示逐份校验结果和实际输出目录。

## 安装与迁移

安装由下载仓库中的 `install.py` 完成。用户要求装配已下载项目时，阅读该项目 `README.md`，运行 `py -3.12 install.py`（macOS / Linux 使用 `python3 install.py`，要求 Python 3.10+）。默认注册到 Codex；Claude Code 使用 `install.py --agent claude`。其他兼容工具可用 `--skills-dir` 指定其 Skill 目录。已有完整环境时可加 `--skills-only` 仅注册。Windows 10/11 已有真实学校验证；macOS / Linux 是预览适配，不能将合成页面 CI 描述为已通过学校登录或真实导出验收。Linux 需要图形桌面及 Zenity/KDialog 或 Tkinter，详见项目 README。

源码 ZIP 不含独立 Python。自带 Python 的应用包与源码 ZIP 是不同产物：Windows 的 `paperforge-cli.exe`、macOS 的 `PaperForge.app/Contents/MacOS/paperforge`、Linux 的 `paperforge` 可以用 `--register-skill codex`（或 `claude`、`--skills-dir`）注册实际安装位置。包的签名、原生桌面和学校验收状态以随包说明为准。普通聊天用户可自己双击应用包；AI 工具不是运行依赖。

工作台启动和学校登录均优先 Google Chrome，即使系统默认浏览器是 Edge。只有找不到 Chrome 时，工作台才显示已安装的 Edge、Brave 或 Chromium 供用户选择；每种浏览器使用独立登录资料。无 Chrome 且尚未选择时，系统默认浏览器仅用于打开工作台供用户选择，不会自动取得学校浏览器的使用授权。Firefox/Safari 不能用于当前 CDP 试卷读取引擎。网页工作台的显示浏览器与后台学校登录浏览器使用各自的会话。

安装位置记录在已安装 skill 的 `installation.json`，不在源码包里写死。`XJTLUPAPERFORGE_HOME` 可覆盖位置；项目移动后重新运行 `install.py` 更新记录。启动器找不到项目或环境时，报告具体问题并在已知下载位置重新装配，不依赖原开发者的 D 盘目录。

新安装 skill 如未出现在当前会话，提示开启新对话刷新。安装验证不需要学校账号或实际试卷；不要为检查安装而自动下载课程。

## 用户明确要求命令行批处理时

应用包可通过安装记录中的启动器运行 `--worker login` 或 `--worker batch_capture ABC123 --scale 2`。源码安装以 `scripts/launch.py --print-root` 返回的项目目录为工作目录，使用该项目 `.venv\Scripts\python.exe`（macOS / Linux 改用 `.venv/bin/python`）：

```powershell
.\.venv\Scripts\python.exe login.py
.\.venv\Scripts\python.exe batch_capture.py ABC123 --scale 2
```

把示例编号换为用户指定课程。多门课程顺序执行，共享专用浏览器，不同时操作同一会话。默认约 192 DPI；用户需要约 300 DPI 时使用 `--scale 3.125`。`login.py --status` 仅检查进程，`login.py` 才验证登录态。

程序逐页检查页数、顺序、像素和有效 DPI，整套通过后才发布；重跑只复用来源身份与版本均匹配的文件；没有身份记录的旧文件保留原样并提示更换位置。按实际退出码及逐套结果报告成功、部分完成、失败或未找到，不能把零结果和部分成功描述为完整导出。不要假设每门课固定六套。

## 数据与质量边界

- 应用包默认试卷在用户主目录的 `XJTLUPaperForge-Output/课程编号/`；源码版在项目父目录的 `XJTLUPaperForge-Output/课程编号/`，仅包含 PDF；运行资料位置由 `settings.DATA_ROOT` 决定，采用对应系统的用户数据目录，不写死 Windows 路径。网页保存位置可通过系统选择器更改并持久化，实际位置以界面为准。命令行默认目录由 `.env` / `XJTLUPAPERFORGE_OUTPUT` 决定，网页任务会传递本次冻结的目录。
- 发布或维护仓库时只收录代码、测试、依赖说明、前端及 skill；不收录真实试卷、个人下载清单、`.env`、Cookie、浏览器资料、运行日志或已安装 skill 的 `installation.json`。不自动迁移其他程序的试卷或登录状态。
- 网站封存且没有 `View Online` 入口时说明状态，不因日期已过而猜测开放。持续网络超时后保留会话，等待恢复，避免无休止重试。
- 不降低检查标准来宣布成功，不猜缺失页数或考试类型，不插值放大冒充高清。用户要求恢复旧备份时单独核验并披露来源、原始分辨率。
- 无损封装不能恢复源文档缺失的细节；输出无自动添加的可搜索文字层。需要视觉检查时，预览放任务临时目录，不放课程文件夹。

## 维护

阅读项目根目录 `AGENTS.md` 与 `README.md`。`legacy/capture.py` 仅供查阅，产品入口为 `app.py`，批处理入口为 `batch_capture.py`。修改程序后运行 unittest 和 pip check；测试使用合成页面，不需要真实试卷。修改 skill 后重新运行 `install.py` 同步安装副本并用 skill-creator 验证器检查。不要仅为改品牌而更改已有 PDF 校验格式标识。

兼容性排查：用项目虚拟环境运行 `doctor.py --json`，并阅读项目根目录 `COMPATIBILITY.md`。诊断只检查本机能力，不能替代学校登录/下载端到端验收；遇到网站关闭如实报告，不自动进行无期限重试。
