# XJTLUPaperForge

把课程编号交给它，把整理好的试卷带走。

XJTLUPaperForge 是一个面向西交利物浦大学历年试卷库的本地工具。调用 Codex skill 后打开网页工作台，输入课程编号，完成学校登录，即可查看搜索、导出和校验进度。

## 从 Git 下载后，交给 Codex 装配

```powershell
git clone https://github.com/Mushroom666888/XJTLUPaperForge.git
cd XJTLUPaperForge
```

下载或克隆此仓库到自己的电脑，在 Codex 中打开该文件夹，然后说：

> 请阅读这个项目的 README，装配到本地，并安装 xjtlu-paperforge skill。

Codex 会运行安装脚本，创建独立 Python 环境，安装依赖，并把 skill 注册到当前用户的 Codex skills 目录。安装记录使用你实际下载的位置，没有写死 D 盘路径。

也可以自己在项目目录运行：

```powershell
py -3.12 install.py
```

要求：**Windows 10/11、Python 3.10+（推荐 3.12）**。默认优先 Google Chrome；仅在未检测到 Chrome 时，界面才提供已安装的兼容浏览器选项。安装依赖需要联网；使用时需要能够打开学校试卷库。当前版本不支持 macOS/Linux，浏览器与 AI 工具的实际验证范围见 [COMPATIBILITY.md](COMPATIBILITY.md)。

## 调用 skill，打开小界面

安装完成后，在新 Codex 对话中说：

> 使用 $xjtlu-paperforge 打开试卷工作台。

然后在界面里：

1. 输入一个或多个课程编号，以空格或逗号分隔。
2. 选择标准 192 DPI 或精细 300 DPI；需要时点击“更改位置”，通过系统文件夹选择器选择保存位置。
3. 点击“开始整理试卷”。若弹出学校登录页面，在专用浏览器中手动登录，完成后自动继续；默认使用 Chrome。
   等待手动登录时，工作台会显示“请去登录哦”和对应浏览器名称；登录完成后提示自动收起。
4. 查看每门课程的结果，通过“打开本次归档”取走 PDF。

账号密码直接填写在学校网页，不在 Codex 聊天或项目代码中保存。界面由本机服务提供，只监听 `127.0.0.1`，无需部署服务器或配置云端账户。新安装的 skill 若未出现在当前会话，开启新对话刷新。

不通过 Codex 也能打开：

```powershell
.\.venv\Scripts\python.exe app.py --open
```

关闭网页不会中断后台导出；任务完成后可点击右上角“退出应用”停止本地界面服务。学校专用 Chrome 可在后续任务中复用，或用 `login.py --close` 关闭。

界面会随真实阶段切换七个彩色表情：准备、等待登录、搜索、下载、校验、完成或异常。进度轨道表示**完成归档的课程数**，另列当前课程的已校验 PDF 数和当前文件已读取页数。总文件数未确认时不会显示猜测的百分比；部分失败和零结果不会显示全部完成。

“取消整理”会在当前有界网络/页面操作结束后停止，最长通常需等待当前 30–60 秒的操作超时。已校验 PDF 保留，正在处理的临时图片和 PDF 会清理；重新整理会复用合格文件。减少动态效果的系统设置会关闭持续动画。

## 文件放在哪里

- **代码**：你克隆本仓库的目录。
- **试卷**：默认位于项目父目录下的 `XJTLUPaperForge-Output`，每门课一个文件夹，里面只放 PDF。
- **登录资料、运行日志、临时文件**：`%LOCALAPPDATA%\XJTLUPaperForge`。
- **已安装 skill**：`$CODEX_HOME\skills\xjtlu-paperforge`；未设置 `CODEX_HOME` 时使用 `%USERPROFILE%\.codex\skills\xjtlu-paperforge`。

本仓库不含真实试卷、个人导出清单、学校账号、Cookie 或浏览器资料。测试数据为合成页面。

界面的“保存位置 → 更改位置”调用本机原生文件夹选择器，需要 Python 的 Tkinter（官方 Windows Python 安装默认包含）。选择后会实际检查可写性，并原子保存到运行资料目录的 `preferences.json`，重启后恢复；取消选择保持原位置。任务开始时冻结目标目录，整理过程中不允许切换。更改设置后，“打开本次归档”仍指向那次任务的原位置。

恢复按钮会回到默认目录：本项目放在 `D:\XJTLUPaperForge` 时为 `D:\XJTLUPaperForge-Output`。也可将 `.env.example` 复制成 `.env`，设置 `XJTLUPAPERFORGE_OUTPUT`（默认目录、命令行输出）和 `XJTLUPAPERFORGE_DATA`。界面已保存的偏好优先于默认目录，点击恢复默认会采用新的环境配置。相对环境路径按项目目录解析。移动项目后重新运行 `install.py` 更新 skill 的位置。

## 清晰度与完整度

- 等待 PDF.js 完成目标缩放下的绘制，并检查画布尺寸，避免空白或旧尺寸页面。
- 使用阅读器的真实总页数，检查连续页码、疑似空白/纯色页、完全重复页。
- 将 PNG 无损嵌入 PDF，并逐页核对解码后的像素哈希、顺序、尺寸及有效 DPI。
- 检查图片确实完整绘制在 PDF 页面上，拒绝缺失绘制指令、偏移、裁切或异常旋转的文件。
- 整套通过校验后才发布最终文件；失败不会覆盖已有 PDF。重跑可复用达到本次分辨率要求的合格文件。
- 新文件先在目标磁盘的临时目录内校验，再以禁止覆盖的方式发布，支持跨盘保存。如果已有同名文件损坏或分辨率不足，请选择另一个保存位置或自行移走旧文件；程序不会自动覆盖。
- 按完整课程编号搜索，使用网站信息和封面 OCR 核对课程、学年及考试类型。`F` 为期末，`R` 为补考；未知学年用 `idx` 标记，需核对。

输出是图像型 PDF，没有自动添加可搜索文字层。更高渲染分辨率不能恢复源文档已经缺失的细节。套数由网站结果决定，不固定为六套。

网站封存、账号失效、网络故障和页面校验失败会分别反映为未完成或部分完成，不会伪装成成功。非封存失败每套自动重试一次，阅读器等待最多 60 秒；持续故障应等待网站或网络恢复。

## 命令行与开发

Skill 使用普通 Markdown 和 Python 启动器，不依赖 Codex 专有 API。Claude Code 可用 `py -3.12 install.py --agent claude` 安装，再用 `/xjtlu-paperforge` 调用；其他具备本地终端和文件访问的 Skill 工具可通过 `--skills-dir` 指定安装目录。宿主客户端的实际验证范围见 [COMPATIBILITY.md](COMPATIBILITY.md)。`doctor.py --json` 可检查本机环境，但不会代替用户登录或测试学校下载。

```powershell
# 手动登录
.\.venv\Scripts\python.exe login.py
# 将 ABC123 替换为实际课程编号
.\.venv\Scripts\python.exe batch_capture.py ABC123 --scale 2
# 检查进程状态或关闭专用 Chrome
.\.venv\Scripts\python.exe login.py --status
.\.venv\Scripts\python.exe login.py --close
# 本地测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

`--status` 只检查浏览器进程；`login.py` 才验证登录状态。程序使用已安装的 Chrome 或所选兼容浏览器，不需要另装 Playwright 浏览器。

| 文件 | 用途 |
| --- | --- |
| `install.py` | 创建环境、安装依赖、注册可迁移的 skill |
| `app.py`、`frontend/` | 本地界面、课程任务、状态与结果 |
| `skill/xjtlu-paperforge/` | 可分发的 skill 和启动器 |
| `settings.py` | 输出和运行资料路径 |
| `output_preferences.py`、`folder_picker.py` | 原生目录选择、可写检查、偏好持久化 |
| `task_events.py` | 实际阶段/页数事件与协作取消信号 |
| `login.py`、`browser_session.py`、`browser_config.py` | Chrome 优先的浏览器选择、独立会话和手动登录 |
| `batch_capture.py`、`capture_canvas.py` | 课程搜索、逐套读取页面 |
| `pdf_output.py`、`pdf_quality.py`、`merge_png_to_pdf.py` | 无损生成、完整性校验及最终发布 |
| `tests/` | 模拟网站、合成 PDF、接口和可迁移安装测试 |
| `legacy/capture.py` | 原项目早期实现，仅供查阅 |

GitHub Actions 会在 Windows 上运行测试。默认不提交 `.venv`、运行资料或个人配置。发布前可用 `git status` 检查待提交文件。

审查方法与修复记录见 [AUDIT.md](AUDIT.md)，自动化及真实学校网站验收范围见 [VERIFICATION.md](VERIFICATION.md)。

这是直接由 Python 提供的 HTML/CSS/JavaScript，无 npm 构建、TypeScript 或 ESLint 配置。浏览器测试使用系统 Chrome，覆盖真实 DOM、按钮、表情、减少动态效果、响应式布局和后端接口；PDF 集成测试用合成阅读器真正生成并验证文件。它们不等于学校网站端到端测试，后者需要有效学校会话和可用网络。界面插画来源及处理方式见 `frontend/assets/ASSETS.md`。

## 来源与许可


独立开源工具，与学校无隶属关系。仅处理用户有权访问和保存的试卷；软件许可证不授予试卷内容的再分发权。
