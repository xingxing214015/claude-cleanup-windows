# Claude Cleanup for Windows

Claude Code / Claude Desktop 的 Windows 原生清理技能，参考
[Suyuan 的 macOS 版](https://github.com/suyuan2022/suyuan-skill/tree/main/claude-cleanup)实现。

## 在其他电脑安装

在 Codex 中发送以下指令，无需手动下载 ZIP：

```text
请使用 $skill-installer 安装 https://github.com/xingxing214015/claude-cleanup-windows/tree/main/claude-cleanup-windows
只安装，不执行清理。
```

安装后用 `$claude-cleanup-windows` 调用；未识别到时重启 Codex。
Windows 原生 Python 3.10+，脚本无需第三方依赖；不适用于 WSL。

## 功能

- 只读审计、完整 SHA-256 校验备份、可恢复的缓存隔离。
- 识别传统 Desktop 数据目录及 Claude MSIX 软件包内的缓存。
- 可选 CLI 文件凭据重置、本地 userID/machineID 轮换和精简模式设置。
- 默认缓存清理保留历史、skills、plugins 和 MCP；CLI 保护范围与遥测设置始终保持。
- `--desktop reset` 完整备份后重置桌面端登录、配置、扩展及本地会话。
- `--desktop uninstall` 再通过 Windows 原生机制卸载当前用户的 Claude MSIX 应用，并复查结果。

## 手动运行

```powershell
python .\claude-cleanup-windows\scripts\claude_cleanup.py --audit
python .\claude-cleanup-windows\scripts\claude_cleanup.py
python .\claude-cleanup-windows\scripts\claude_cleanup.py --audit --desktop reset
python .\claude-cleanup-windows\scripts\claude_cleanup.py --desktop reset
python .\claude-cleanup-windows\scripts\claude_cleanup.py --desktop uninstall
```

实际清理需要正常关闭 Claude 并在交互终端审阅清单、输入 `CONFIRM`。
移除项进入 `%USERPROFILE%\ClaudeCleanupBackups` 中的隔离目录，并非回收站。
备份可能包含凭据和历史，请勿上传。自定义 `CLAUDE_CONFIG_DIR`、目录联接或
符号链接会使脚本停止。CLI 凭据重置不保证注销其他认证方式。

## 验证

```powershell
python -X utf8 .\test_claude_cleanup_windows.py
```

15 项隔离测试覆盖完整桌面重置、备份失败、卸载调用顺序与失败恢复、保护路径、
Windows junction、MSIX 缓存、凭据选择、进程识别、设置保留和本地 ID 轮换。
卸载系统调用使用模拟验证；未执行真实清理或真实卸载。

完整重置会移走桌面端 MCP 配置、扩展和本地 Claude Code/Cowork 数据；
这些数据均先备份。卸载只处理当前用户，恢复应用安装需要官方安装器。

原作者：Suyuan。Windows 适配说明与代码见
[SKILL.md](claude-cleanup-windows/SKILL.md)。
