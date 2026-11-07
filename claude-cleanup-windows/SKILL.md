---
name: claude-cleanup-windows
description: 在 Windows 原生环境审计、备份和清理 Claude Code 与 Claude Desktop 缓存，按选择重置 CLI 文件凭据、轮换本地 ID 或设置精简模式，并指导桌面端退出登录、卸载及可选时区调整。适用于 Windows 本机排障和空间清理。
---

# Claude Windows 清理

要求 Windows 和 Python 3.10+，无需第三方依赖。WSL 不属于此 skill 的运行环境。
脚本路径相对于本文件所在目录。用 `python` 或 `py -3` 启动。

## 执行

1. 先执行 `python scripts/claude_cleanup.py --audit`，只列出路径、体积和进程数，不读取输出令牌或会话内容。
2. 向用户说明审计结果和范围。默认处理明确列出的缓存；`--reset-cli-login` 将移走 `.credentials.json`，下一次可能需要重新登录；`--simple on|off` 仅修改 `settings.json` 中的 `env.CLAUDE_CODE_SIMPLE`。`--rotate-local-ids` 轮换 `.claude.json` 的 `userID` / `machineID`，清除已知账号缓存键，并同步 `.claude/backups/.claude.json.backup.*`；保留 MCP、项目和其他字段。上述可选操作必须符合用户选择，不默认附加。
3. 仅在用户要求实际清理后，在用户可交互的终端执行脚本，无参数表示仅清缓存。用户须正常退出所有 Claude 进程，然后审阅完整清单并输入一次 `CONFIRM`。不要管道代答或自动结束进程。Claude Code 自身只能调用只读审计；写入须切换到独立 PowerShell 或 Codex。
4. 脚本首先完整复制并按 SHA-256 校验 `.claude`、`.claude.json` 及选中的 Desktop 缓存，再执行移动。没有 `.claude` 时也允许仅清理 Desktop 缓存。所有移走的文件留在 `%USERPROFILE%\ClaudeCleanupBackups\<批次>\quarantine`，这是隔离目录，不是 Windows 回收站。
5. 报告实际完成项、备份路径和恢复方法。失败视为可能部分完成；保留批次目录，检查其中 `plan.json` 与隔离目录，不自动覆盖恢复。

```powershell
python scripts/claude_cleanup.py --audit
python scripts/claude_cleanup.py
python scripts/claude_cleanup.py --reset-cli-login
python scripts/claude_cleanup.py --simple on
python scripts/claude_cleanup.py --simple off
python scripts/claude_cleanup.py --rotate-local-ids
```

## 范围与恢复

仅支持脚本中固定白名单。保护历史、项目、skills、plugins、MCP 和其他配置；只有明确选择的设置键及身份文件允许结构化修改。不打印秘密，不改遥测设置，也不读取或改写全局环境变量。`CLAUDE_CONFIG_DIR` 有值时停止，避免清错配置。遇到符号链接或 Windows junction/reparse point 停止，不跟随它们复制或移动。进程检查失败时停止写入。脚本不结束进程。

Desktop 缓存目录包括 `%APPDATA%\Claude`、相邻的 `Claude-3p`、`%LOCALAPPDATA%\Claude-3p`，以及 `%LOCALAPPDATA%\Packages` 中实际存在的 `Claude_<发布者ID>` / `Anthropic.Claude_<发布者ID>` 下 `LocalCache\Roaming` 或 `LocalCache\Local` 中的同名目录。仅移动这些目录中的 `Cache`、`Code Cache`、`GPUCache`、`DawnCache`、`logs`、`Crashpad`，不移动整个应用数据目录或软件包。未知安装布局先通过应用的日志/配置位置确认，不扩展通配删除范围。

恢复前关闭 Claude。根据 `plan.json` 的 `source` / `destination` 将隔离项移回原处；原处已存在时先另存现有内容，不能直接覆盖。设置变更可从 `snapshot/cli/settings.json` 逐键恢复。快照包含凭据和历史，保留在当前用户自己的目录，不上传或提交。

本地 ID 轮换的原始主文件在 `snapshot/identity.json`，原始内部备份在 `snapshot/cli/backups`。轮换不修改 Windows 系统设备标识，不保证退出登录，也不保证改变平台关联判断。`--reset-cli-login` 只处理文件凭据；环境变量、第三方凭据助手或其他认证存储仍可能生效，不能宣称已完全退出账号。

## macOS 操作在 Windows 上的对应方式

- 钥匙串：Windows 文件凭据使用 `--reset-cli-login`；不运行 macOS `security`，不批量删除 Windows 凭据管理器。若用户实际使用其他凭据存储，先确认其认证方式，再用对应官方退出流程。
- Desktop 退出登录：使用应用内退出登录。整个 Desktop 数据目录可能包含 MCP 配置、扩展、Claude Code / Cowork 会话，不能当作登录缓存移除。若用户明确要求完整重置，先确认应用实际数据路径，关闭应用并完整备份，另行列出会受影响的数据后处理；本脚本不提供完整重置选项。
- 卸载 Desktop：用户明确选择卸载后，先备份其实际数据目录，再使用 Windows“设置 → 应用 → 已安装的应用 → Claude → 卸载”。不手动移动 `WindowsApps`、软件包根目录或旧版安装目录。卸载完成后复查安装状态。
- 台北时区：仅在用户选择该操作时读取 `tzutil /g`。若不是 `Taipei Standard Time`，列明系统范围影响并执行 `tzutil /s "Taipei Standard Time"`，随后用 `/g` 验证。权限不足时说明需用户在 Windows 原生提升权限界面完成；不收集密码、不自动提权。这一步独立于清理脚本，清理不默认改变时区。
- 最小提示词模式：保留 `CLAUDE_CODE_SIMPLE` 设置方式；具体功能以本机 Claude Code 版本为准。不会删除 hooks、skills、plugins 或 MCP 资产。

不将本技能用于规避封禁、支付检查或平台风控。

设计参考：[suyuan2022/suyuan-skill 的 macOS 版](https://github.com/suyuan2022/suyuan-skill/tree/main/claude-cleanup)。Windows 脚本为独立实现。

平台依据：[Claude 配置目录](https://code.claude.com/docs/en/settings)、[认证](https://code.claude.com/docs/en/iam)、[MSIX 路径实际问题](https://github.com/anthropics/claude-code/issues/25579)、[Windows tzutil](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/tzutil)。

安装：在本目录执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Target Codex`，或选择 `-Target Claude`。安装器拒绝覆盖已有同名技能。安装本身不执行清理；新聊天中可用 `$claude-cleanup-windows` 调用。
