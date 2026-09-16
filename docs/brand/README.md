# GitHub presentation assets / GitHub 展示素材

[English README](../../README.md) · [中文 README](../../README.zh-CN.md)

The repository's presentation copy is recorded in [repository-metadata.json](../../.github/repository-metadata.json). This is a maintainer reference, **not an automatically applied GitHub configuration**.

仓库展示文案记录在上述 JSON 中，供维护者使用；**GitHub 不会自动应用此文件**。

## About and discovery / 简介与发现入口

- Keep the About description aligned with the README positioning. 简介与 README 的定位保持一致。
- Add the eight relevant Topics from the metadata file. Preserve any additional relevant topics already configured. 添加元数据文件中的八个主题，并保留已有的相关主题。
- Set the Website field only when a public product or documentation site is available. 本项目有公开的产品或文档站点后，再设置 Website 字段。
- README links point to quick start, the screenshot tour, documentation, the current roadmap, bug reports, and contribution instructions. There is no live-demo link until such a demo exists. README 提供快速开始、截图导览、文档、当前路线图、问题反馈及贡献入口；在线 Demo 上线后再增加相应链接。

GitHub's [Topics guide](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics) explains where to configure these tags.

## Social preview / 分享封面

![Quanthecy social preview](social-preview.png)

- Upload [social-preview.png](social-preview.png) in [repository settings](https://github.com/chongliujia/Quanthecy/settings), under **Social preview → Edit → Upload an image**. 在仓库设置的 Social preview 中上传 PNG。
- The PNG is 1280 × 640 with an opaque background and is under 1 MB, following [GitHub's image guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview). PNG 为 1280 × 640、不透明背景、小于 1 MB。
- The editable source is [social-preview.svg](social-preview.svg). This is a brand graphic with an illustrative workflow, separate from the original platform screenshots in [the screenshot index](../images/README.md). 可编辑源文件为 SVG；封面是流程示意品牌图，平台原始截图仍单独保存。
- Export the SVG at its native size after changing it, and inspect the result before uploading. 修改 SVG 后按原尺寸导出，并检查成品再上传。

## Community entry points / 社区入口

The bug and feature forms, issue chooser links, and pull request template live in `.github/`. They take effect after those files reach GitHub's default branch. Forms accept English and Chinese; no labels or assignees are applied automatically.

问题与功能建议表单、Issue 选择页链接和 PR 模板位于 `.github/`；这些文件进入 GitHub 默认分支后生效。表单支持中英文，不自动设置标签或指派人员。
