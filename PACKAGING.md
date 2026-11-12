# 自带 Python 的桌面预览包

发行包包含 CPython、Python 依赖、Playwright Node 驱动、OCR 模型和网页资源；用户仍需安装 Chrome（缺失时可明确选择 Edge 等兼容浏览器）并使用图形桌面。它不是学校登录或试卷权限的替代物。

Windows 解压后双击 `PaperForge/PaperForge.exe`；命令行/Agent 使用同目录的 `paperforge-cli.exe`。macOS 将 `PaperForge.app` 放入 Applications 后打开；命令行入口为 `PaperForge.app/Contents/MacOS/paperforge`。Linux 解压后运行 `PaperForge/paperforge`；桌面文件管理器是否允许双击可执行文件取决于其设置。程序检查本地服务健康后才报告成功。

应用包默认将试卷保存到用户主目录的 `XJTLUPaperForge-Output`；运行资料继续使用各系统用户数据目录。不要将输出或资料放入应用包、源码目录或其子目录。移动安装包后重新注册 Skill。

注册 Skill 不需要系统 Python：

```powershell
.\paperforge-cli.exe --register-skill codex
.\paperforge-cli.exe --register-skill claude
```

macOS/Linux 对应使用包内 `paperforge --register-skill codex`。自定义宿主目录可加 `--skills-dir`。Agent 读取安装后的 `installation.json`，优先直接执行 `launcher` 指向的应用程序；源码安装和原有 Python CLI 保留。

## 构建

在目标操作系统与 CPU 架构上使用 Python 3.12 原生构建；不做跨系统冻结。先安装 `packaging/requirements-build.txt`（CI 同时应用依赖锁定文件），再运行：

```powershell
.\.venv\Scripts\python.exe tools/build_package.py
.\.venv\Scripts\python.exe tools/smoke_package.py dist/PaperForge
```

macOS 烟测参数改为 `dist/PaperForge.app`，解释器改为 `.venv/bin/python`。烟测复制到包含空格和中文的新路径，清空 Python 配置，使用临时用户资料，在真实 Chrome/可用 Edge 中运行合成导出、真实离线 OCR、健康检查、重复启动、Skill 注册及退出。`--self-test` 不访问学校，不是学校端到端验收。

`dist` 生成平台归档、SHA256、依赖/文件清单和第三方许可证。请保留整个目录结构，不要只复制一个 exe。构建记录包含当前提交和是否有未提交修改。源码内的真实试卷、浏览器资料、`.env` 和机器安装记录不得入包。

`preview.2` 在包内保存 `build-info.json`，记录实际打包源码（含未提交与新增模块）的逐文件哈希和总指纹。工作台页脚、健康端点和本地任务日志显示版本/指纹；同一安装位置仍运行其他版本时，启动器要求先退出旧工作台，不能把旧服务报告为新版本就绪。重新签名后用 `--skip-build` 更新归档时保留包内原始指纹。

本轮 Windows 产物使用 `--output dist/review2`，保留原 `preview.1` 归档。两个版本都属于预览包，不能把上一版本的自动化或学校验收记录转用于新版本。

后续 `preview.3` 使用 `--output dist/browser-fix`，修复工作台曾跟随系统默认浏览器而打开 Edge 的问题。源码、Skill 和包入口现在共用 Chrome 优先策略；没有 Chrome 时采用已明确保存的兼容浏览器。两者都没有时仅用系统默认浏览器展示选择界面，不自动选择学校浏览器。已有 Chrome 启动失败则明确报错，不静默回退。换包后需重新注册 Skill，旧包和旧注册位置不会自动升级。

## 原生验收与正式发布

隔离 PATH 的开发机烟测可以发现隐藏的 Python/源码依赖，但不能声称等同于一台从未装过 Python 的干净机器。Windows Sandbox/干净虚拟机必须安装 Chrome，解压产物并完成启动、文件夹选择/取消/记忆、合成导出、退出；学校试卷验收另由用户手动登录。macOS/Linux 同样需要对应图形桌面测试者完成实际学校搜索、导出、逐页检查、取消与重试。

macOS 正式发行需要 Developer ID 签名、公证与 stapling；相关凭据通过构建环境提供，不放入源码。未签名/未公证的预览包不得描述为通过 Gatekeeper 验收。Windows 正式签名可通过受信任代码签名证书完成。当前界面衍生插画的分发权说明见 `frontend/assets/ASSETS.md`；公开正式发行前须确认许可。

源码 CI、应用包烟测和真实桌面学校验收分别记录；稳定版本须在对应系统人工验收后再合并/发布。
