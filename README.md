# Nikon Z8 RAW 预拍探索：半按触发原生 RAW（QEMU 原型）

**仅经 QEMU 验证的研究原型：本项目已从固定源码重新编译模型并自复跑三组首帧对照；真机未验证，尚无外部独立复现记录。**

**QEMU-only research prototype. This project rebuilt the pinned model and reran the three first-frame controls. Physical-camera operation has not been tested, and no independent external reproduction has been reported.**

本项目探索把 Nikon Z8 的 RAW 拍摄请求提前到半按阶段，通过原生拍摄流程直接保存 NEF。这是我们研究 RAW 预拍体验的一条路线。当前模型候选实现的是**半按触发单帧拍摄并直接保存**；尚未实现已验收的持续半按连拍，也没有证明全按后能从历史缓存回溯保存帧。

The project studies half-press-triggered native NEF capture on Nikon Z8 C3.11 as a route toward RAW pre-capture. Three controls passed using a clean build of the pinned, locally modified functional QEMU model: stock full press produced one NEF, stock HALF-only produced none, and the seven-instruction candidate with HALF-only produced one. Complete decoded samples matched the synthetic source and each run's producer snapshot. Physical-camera operation, sustained capture and retained pre-trigger frames remain unverified. Source recipes, patches and a reproduction guide are included; firmware, keys and compiled emulators are not distributed.

**复核入口：[从输入到三组模型对照](docs/reproduction.md)。** 使用者须自备准确原厂包，以及正确 MAIN 或所需 XOR 表。只有原包不保证足够完成输入准备；这里不承诺无前提的一键运行。

欢迎通过 issue 或 PR 分享复现结果、失败案例、反例和纠正。请附可核查的步骤与证据；我们会据此更新或撤回不成立的结论。

Reproduction reports, counterexamples and corrections are welcome through issues or pull requests. Please include checkable steps and evidence; conclusions will be revised or withdrawn when the evidence warrants it.

## 本次研究做了什么

- 追踪原固件的按钮事件、工作队列、订户与按下/释放配对，纠正了“改一个事件号即可”的初始假设。
- 实现七个原位指令修改，MAIN 长度不变，实际改变 21 字节。它不使用额外注入区或 loader 扩展。
- 提供固定模型源码、公开补丁、合成源生成器和三组运行入口；用新构建和三张新空卡对比原版全按、原版仅半按、候选仅半按，核对实际输入交付、完整等待及停机卡目录。
- 对两个成功首帧文件检查完整 RAW 解码、全部样本与合成输入及同次 producer 的对应，以及三个 JPEG 预览。
- 单独观察首次释放；保留第二周期的共同模型故障和未执行实验，不把失败改记为通过。

模拟器、普通 NEF 写入、硬件模型和解码基础工作来自上游。本文不主张首创这些能力，也不主张全球首次或唯一实现。具体归属见 [UPSTREAM.md](UPSTREAM.md)。

## 新构建的实际重放结果

本轮三组均正常退出并满足输入、完整等待、停止及卡检查条件。仅半按两组使用相同规定手势 `(HALF,FULL): 00 → 10 → 10 → 10 → 00`；没有把排队记录当成已交付。结果见 [runtime-reproduction.json](evidence/runtime-reproduction.json)。

| 固件与规定输入 | 最终 NEF 数 | 内容检查 |
|---|---:|---|
| 原版，完整全按手势 | 1 | `PASS_MATCH`：完整 RAW 与本次源、同次 producer 零差异 |
| 原版，仅半按 | 0 | 完整交付及观察后遍历卡目录，未发现 NEF；采集 jobs/acks 均为0 |
| 七指令候选，同样仅半按 | 1 | `PASS_MATCH`：完整 RAW 与本次源、同次 producer 零差异 |

两份 NEF 各35,110,512字节，RAW 为8280 × 5520、14 bit Nikon lossless/F0。每份45,705,600个样本全部参与源及同次 packed14 producer 比较，差异均为零，三张 JPEG 预览均完整解码。完整像素 SHA-256 为 `e3b0bf6dd2fc4c85f88f0f50e30f690c59202297b4f3a90a02d687b3259b6a3a`。这里的像素来自功能模型，不是真实传感器；审核使用一个 RAW 解码器实现（LibRaw，经 rawpy），没有第二种独立 RAW 解码器验证。

本轮新编译 QEMU 二进制 SHA-256 为 `b318f19e73c8339fa18ce2fd6da621c7ffb8fde6198a283d1efc25a76871b43a`，与历史二进制不同；本次结论来自它的实际运行，不来自编译成功或历史哈希。源码差异见 [MODEL.md](runtime/MODEL.md)。三项可选宽松开关均读回关闭，相关计数为0，`Z8_UNKNOWN` 与 `Z8_TOLERATED` 均为0条。不过三组仍分别有 **6、1、6条 `Z8_1508_GROUP` 未建模输出诊断**。这类记录不是完成事件，不能声称没有任何模型缺项。

第一阶段发布复核曾在 Windows 上重新解码保留的四份历史 NEF，当时没有重读 WSL 源和 producer，该阶段记录保留在 [publication-recheck.json](evidence/publication-recheck.json)。随后已重新生成源并核对旧源；两份历史首帧与各自保留的实际 producer 再次全样本比较零差异。两份历史生命周期 NEF 只补做源比较，未升级为同次 producer 验证。这些历史审核与上面的新三组执行分开记载。

历史首次释放记录到 `D0 → 1D → 1C` 发射点及所查状态恢复。历史第二周期中原版与候选均再次提交采集，最终 producer 计数均为2，但卡上各只有1份 NEF；两者都在 `PC 0x40C26848` 写 `0x15432004 = 0x103` 时遭模型拒绝。**本次新三组只重测首帧，没有闭合第二张保存与持续拍摄问题。**

[evidence/observations.json](evidence/observations.json) 保留历史数值摘要，没有被新运行覆盖。公开摘要不等于原始日志，哈希也不独自证明结论；完整卡、内存和原始运行日志不随本仓库分发。现在提供执行入口，让复核者可以自己生成证据。

## 如何复核

静态工具需要 Python 3.10+，只使用标准库；运行与内容审核使用 Python 3.11+ 及锁定依赖。使用者自备两个输入：

| 输入 | 字节数 | SHA-256 |
|---|---:|---|
| 原厂 `Z_8_0311.bin` | 99,051,117 | `d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96` |
| 正确提取的 EG 去除末尾 2 字节 CRC 后的 MAIN | 81,807,709 | `2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853` |

原包缺失或任一身份不符时停止，不替换版本或按固定差值平移地址。可用自备 XOR 表经 [提取工具](docs/firmware-input.md) 取得 MAIN；仅一个 Z8 原包不保证能恢复全部表。旧提取文件曾提前32字节取片，文件名和长度不能代替完整身份检查。

构建与独立验证的命令见 [tools/README.md](tools/README.md)。生成结果应为 81,807,709 字节，SHA-256 为：

```text
2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e
```

生成物是本地研究用 MAIN，没有 Nikon 安装容器或模块 CRC；不能当更新包使用。静态哈希一致仅证明重建一致，不证明运行、更新器接受或相机恢复。

完整命令见 [复现指南](docs/reproduction.md)。提出复现问题时，请给出工具/模型版本与摘要、执行命令的路径占位版本、退出码、三组文件数和内容审核状态。超时、手势未交付、等待不足或卡读取失败均是无效实验，不能算“原版半按不出片”。相关依赖与边界见 [docs/evidence-and-limits.md](docs/evidence-and-limits.md)。原始固件、卡和内存不要直接附到公开 issue。

本轮 [76项主机工具测试](evidence/reproduction-tool-tests.json) 覆盖静态CLI、提取、NEF审核、运行验收与归档链接策略，全部得到预期结果。故意坏输入被拒才是对应测试通过，不能用这些主机测试代替三组固件执行。旧13项静态审计仍保留在 [static-tests.json](evidence/static-tests.json)，其中一项复现旧验证器错误放行，不能算旧工具通过，也不把两批数字简单相加成独立覆盖率。

## 尚未闭合的条件

- 真机加载入口、适用故障范围明确的恢复方法、真实半按动作及相机生成的 NEF。
- 真实参数区的来源与取值。模型中的 `bank8[999]=1` 不是已证明的真机 RAW 必要条件；MAIN 内重置模板该字节为 0，也不能冒充实际机身值。
- 持续半按连拍、快速释放、忙恢复后取消、任意热状态及全部拍摄模式。
- 半按期间加入物理全按的实验此前在启动前被当时的主机环境故障阻止，至今未执行。

研究代码会改变半按的行为，并跳过独立物理 full-ID 回调；原生延迟请求仍可能补发。详见 [docs/patch.md](docs/patch.md)。

## 研究记录与更正

参见 [docs/errata.md](docs/errata.md)。其中包含我们自己的摘要误认和验证器自比较错误；保留更正而不静默改写历史记录。研究使用 AI 辅助分析与代码生成，结论按现有指令、文件和实验记录核查；AI 输出本身不作为证据。

独立研究文本及单独编写的工具采用 [GPL-3.0-only](LICENSE)。`runtime/` 派生代码和 RAW 生成器保留 GPL-2.0-or-later；QEMU 原有许可按文件保留，包括两处核心文件的 LGPL-2.1-or-later。详见 [NOTICE.md](NOTICE.md)。这些许可不改变 Nikon 固件或其他第三方作品的权利。此项目与 Nikon 无隶属关系。
