# 上游与本次增量

| 来源 | 本次研究使用的能力或线索 | 不归本项目首创的部分 |
|---|---|---|
| [RdWing/z8-qemu](https://github.com/RdWing/z8-qemu) | Z8模型、控制器/菜单/拍摄驱动、普通NEF与解码审核基础 | QEMU机型、原生普通NEF能力、功能硬件/ISP/存储模型 |
| [WonderLantern/z9-qemu](https://github.com/WonderLantern/z9-qemu) | RdWing模型继承的Z9基础，RdWing NOTICE注明基线 `deb3a75df1795924e9be8f814d9a24ce6b439a67` | 继承的模型、图像与存储算法 |
| [YCX81/z8-qemu](https://github.com/YCX81/z8-qemu) | 前序格式链、预拍研究和模型验收方法的公开线索 | 其已发表分析与普通NEF模型结果 |
| [XinmiaoZhao/NikonFirmwarePatch](https://github.com/XinmiaoZhao/NikonFirmwarePatch) | 包结构、兼容性校验、A64修改及独立验证方法参考 | ProRes补丁、包处理工具和其作者的真机声明 |
| [WonderLantern/nikon-fw-key-tool](https://github.com/WonderLantern/nikon-fw-key-tool) | 原厂包解包/重打包背景资料 | 解码与包校验工具 |
| [LibRaw](https://github.com/LibRaw/LibRaw) / Dave Coffin、rawpy | 已记录的主机RAW解码；上游模型编码器的格式参考 | 解码器与既有格式知识 |

本次增量是具体按钮路径的核查与否证、七指令输入映射、独立字节验证、规定输入的三组对照、释放观察及共享模型失败的归因边界。它建立在上游之上，不代表完整模拟器由本项目开发。

本次公开的 `runtime/route4_stream.py` 从 RdWing 控制器派生，保留 `Copyright (C) 2026 RdWing` 和 `GPL-2.0-or-later`；半按映射、前态与交付/等待验收等本地修改另有说明。`tools/generate_raw_fixture.py` 同样保留其 RdWing 生成器的归属。旧生命周期驱动未随本版本分发。完整 QEMU 与依赖不在本仓库捆绑。

以上仓库链接用于来源追溯，不表示其当前分支与实验二进制完全一致。新增模型流程固定 RdWing 提交 `c24e33460ab311b8b120b19ba25f532ccef1b391` 与 QEMU 11.1.1 官方源码包，并公开本地 overlay 及 QEMU 本体差异；见 [runtime/MODEL.md](runtime/MODEL.md)。源码准备、实际编译和运行验收各有独立回执，不以源码哈希代替运行成功。
