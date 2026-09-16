# Contributing to Quanthecy / 参与贡献

[English README](README.md) · [中文 README](README.zh-CN.md)

Contributions to collection reliability, data quality, research evidence, analytics, accessibility, and documentation are welcome. Issues and pull requests may be written in English or Chinese.

欢迎改进采集可靠性、数据质量、研究证据、分析功能、无障碍体验和文档。Issue 和 Pull Request 均可使用中文或英文。

## Start with a concrete problem / 从具体问题开始

- [Report a bug / 反馈问题](https://github.com/chongliujia/Quanthecy/issues/new?template=bug_report.yml): include reproduction steps, your commit/version, and relevant observations.
- [Suggest a feature / 提出功能建议](https://github.com/chongliujia/Quanthecy/issues/new?template=feature_request.yml): explain the user workflow and expected result.
- For a small documentation or bug fix, open a focused pull request. Discuss substantial architecture or data-model changes in an issue first. 小型文档或问题修复可直接提交 PR；较大的架构或数据模型改动请先通过 Issue 讨论。

## Development / 开发

1. Read [AGENTS.md](AGENTS.md) for architecture and contribution requirements. 阅读项目架构与贡献规范。
2. Follow the [quick start](README.md#quick-start) or [中文快速开始](README.zh-CN.md#快速开始). Use `make dev` for hot reload; its local helper requires Python 3. Follow the [foundation guide](docs/foundation.md) for host development.
3. Keep the change focused, update the relevant documentation, and use explicit migrations for persistent schema changes. 保持改动范围清晰，同步文档，持久化模式变更需包含迁移。
4. Run checks appropriate to the affected code and report the results in the PR. 运行与改动相关的检查，并在 PR 中记录结果。

| Area / 范围 | Checks / 检查 |
| --- | --- |
| Python / Django | `make test-python`, `make check-python` |
| Rust collector / 采集器 | `make test-rust` |
| React frontend / 前端 | `make test-web` |
| Shared data contracts / 共享数据契约 | `make check-contracts` |
| Documentation / 文档 | Verify local links, language pairing, and examples / 核对链接、语言配对和示例 |

Tests normally mock exchange and model requests. See the research guides for optional integration checks. 常规测试模拟交易所和模型请求，可选集成检查见研究指南。

## Review expectations / 评审要求

Describe the problem, the final behavior, and relevant validation. Include operational steps when a change affects deployment. Do not commit credentials, local databases, or private account details in logs and screenshots.

说明问题、最终行为与验证结果；影响部署时注明操作步骤。不要提交凭据、本地数据库，或日志和截图中的私人账号信息。

Preserve the documented boundaries: Rust collects exchange data; Python computes metrics and runs research; Django owns the application API, identity, and authorization; React presents the results. LLM conclusions must remain traceable to structured inputs.

保持已约定的架构边界：Rust 采集交易所数据，Python 计算指标并运行研究，Django 管理应用 API、身份与权限，React 展示结果。LLM 结论应能追溯到结构化输入。
