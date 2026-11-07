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
- 保留项目、历史、skills、plugins、MCP 与遥测设置。
- 桌面端退出登录、卸载及可选时区调整使用 Windows 原生流程，详见技能说明。

## 手动运行

```powershell
python .\claude-cleanup-windows\scripts\claude_cleanup.py --audit
python .\claude-cleanup-windows\scripts\claude_cleanup.py
```

实际清理需要正常关闭 Claude 并在交互终端审阅清单、输入 `CONFIRM`。
移除项进入 `%USERPROFILE%\ClaudeCleanupBackups` 中的隔离目录，并非回收站。
备份可能包含凭据和历史，请勿上传。自定义 `CLAUDE_CONFIG_DIR`、目录联接或
符号链接会使脚本停止。CLI 凭据重置不保证注销其他认证方式。

## 验证

```powershell
python -X utf8 .\test_claude_cleanup_windows.py
```

8 项隔离测试覆盖备份失败、保护路径、Windows junction、MSIX 缓存、
凭据选择、进程识别、设置保留和本地 ID 轮换；未执行真实清理。

原作者：Suyuan。Windows 适配说明与代码见
[SKILL.md](claude-cleanup-windows/SKILL.md)。
