# 安全说明

## BUFF Cookie

`BUFF_COOKIE` 是敏感的临时登录凭证。请只把它放在自己电脑的 `.env` 文件中，不要提交到 GitHub、聊天、截图或日志。

本仓库的 `.gitignore` 已排除 `.env` 和本地 SQLite 数据库。提交前仍建议运行 `git status`，确认它们没有出现在待提交文件中。

如果 Cookie 已经泄露，请立即退出 BUFF 的其他登录会话并重新登录，以使旧 Cookie 失效。

## 漏洞报告

请勿在公开 Issue 中粘贴 Cookie、请求头、账户资料或其他隐私数据。报告问题时请先移除这些内容。
