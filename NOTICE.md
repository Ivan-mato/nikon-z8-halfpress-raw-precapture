# 发布范围与许可

这个研究草稿包含静态修改/验证工具、研究文本、数值观察、模型源码补丁与派生运行驱动。根目录研究文本及单独编写的静态/NEF审核工具采用 GPL-3.0-only，许可证全文见 LICENSE。`runtime/` 中的运行代码、模型补丁的本地新增代码，以及派生自 RdWing 的 `tools/generate_raw_fixture.py`，采用 GPL-2.0-or-later；继承部分仍须按上游逐文件许可与声明理解。

两处 QEMU 核心原文件 `system/physmem.c` 和 `accel/tcg/cputlb.c` 的许可为 LGPL-2.1-or-later，原头部与作者声明保留在准备后的源码中；补丁的 SPDX 不覆盖这些原声明。原 LGPL 文本见 [runtime/COPYING.LIB](runtime/COPYING.LIB)，来源、GPL 文本和 QEMU 许可范围说明见 [runtime/NOTICE.md](runtime/NOTICE.md)。上游贡献另见 UPSTREAM.md。未捆绑完整 QEMU 源码、编译产物或解码器实现；模型准备脚本按固定版本取得上游源码。

源代码许可不授予 Nikon 固件、固件界面、第三方代码或用户输入的再分发权。工具产生的完整 MAIN 几乎包含整份使用者固件，不能仅因生成器采用开放许可而把该输出视为同许可作品。

本仓库不分发原厂或修改后的完整固件、密钥、校准/参数正文、内存镜像、虚拟卡或界面截图。使用者自行准备兼容固件输入。后续持续半按实验另附由合成输入产生的 NEF 研究样本与解码概览，见下文；这些不是实机照片。

公开的数值摘要不是完整原始运行记录，也不能代替他人独立重跑。本仓库另提供固定源码与执行入口，并单独记录本地实际重放结果；文件身份、已知错误与未覆盖范围分别标明。

Nikon、Z8及其他名称仅标识研究目标或来源。本项目与 Nikon 无隶属关系，未获其背书。

## 持续半按实验的新增材料

`experiments/held-half/model/` 保留所交付模型逐文件的 GPL-2.0-or-later 与 RdWing 声明；它包含本地实验修改，不代表完整代码等同于未经修改的上游提交。该目录的 `COPYING` 保留原 GPL v2 文本。独立复现/审核脚本和新研究文本采用根目录 GPL-3.0-only。`synthetic-inputs.zip` 中 32 份合成 Bayer 输入及解码概览图作为合成研究材料公开；不含相机照片或 Nikon 固件。输入的完整身份在 source-lock.json 中。

新公开的 JSON 是注明原始摘要的路径脱敏副本，不冒充未修改的原始日志。原始固件、XOR 表、校准正文、完整内存和虚拟卡仍不分发。新实验许可与来源详见 [MODEL.md](experiments/held-half/MODEL.md)。
