# Third-Party Notices

Quick Pass Exam 的 Apache License 2.0 只适用于本项目有权许可的代码、文档和合成示例。下列依赖不包含在本 ZIP 中，安装后仍适用各自的许可证。

## 运行时依赖

- **Requests** — Apache License 2.0  
  <https://github.com/psf/requests>
- **pypdfium2** — Apache License 2.0 或 BSD 3-Clause，并带有 PDFium 及其第三方组件的许可文件  
  <https://pypi.org/project/pypdfium2/>
- **Pillow** — HPND License  
  <https://python-pillow.org/>

`pypdfium2` 发布的 wheel 会携带 PDFium 及相关第三方许可文件。本项目不将这些 wheel 或二进制库重新打包到 Skill ZIP 中。

## 开发与测试依赖

- **pytest** — MIT License
- **PyYAML** — MIT License
- **ReportLab** — BSD License
- **python-docx** — MIT License

完整条款以各依赖实际安装版本随附的许可文件为准。如果将依赖二进制与本项目一起重新分发，发布者应同时提供对应许可文件。
