# 从输入到三组模型对照

目标是让复核者从固定公开源码、新编译的模型、新生成的输入和空卡重跑，观察原版全按、原版仅半按、候选仅半按。运行只针对功能模型；不涉及相机安装。以下命令在 **Linux / WSL 的 Bash** 中执行，从本仓库根目录开始。

## 1. 准备外部输入与环境

自备准确的 `Z_8_0311.bin`（99,051,117 B，SHA-256 `d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96`）。缺少该文件或身份不符就停止。

还需正确提取的 MAIN，或者自行准备的旧格式 T1/T2/T3 XOR 表；表的取得与提取过程见 [firmware-input.md](firmware-input.md)。项目不分发这些表，也不承诺仅一个 Z8 包足够恢复全部表。这是明确的外部输入条件，不能将缺表包装成“一键可运行”。

使用 Python 3.11+；编译工具和系统依赖见 [MODEL.md](../runtime/MODEL.md)，卡格式化工具需要 Linux `exfatprogs`。检查 WSL 所在 Windows 卷的实际可用空间，不能只看虚拟磁盘的容量。所有输出放在新的 Linux 私有目录，避免在 `/mnt/c` 等共享文件系统上生成稀疏卡。

```bash
Z8_PACKAGE=/path/to/Z_8_0311.bin
Z8_KEY_JSON=/path/to/private/key.json
ROUTE4_WORK="$HOME/z8-route4-private"
mkdir "$ROUTE4_WORK"
python3 -m venv "$ROUTE4_WORK/venv"
"$ROUTE4_WORK/venv/bin/python" -m pip install -r runtime/requirements-runtime.txt
```

以上变量是示例路径；`mkdir` 若提示目录已存在，应选新的实验目录，保留旧记录。

## 2. 提取、重建并独立核查 MAIN

```bash
python3 tools/extract_main.py --package "$Z8_PACKAGE" --key-json "$Z8_KEY_JSON" \
  --output-dir "$ROUTE4_WORK/extracted"
python3 tools/build_candidate.py --package "$Z8_PACKAGE" \
  --stock "$ROUTE4_WORK/extracted/stock-MAIN.bin" --output-dir "$ROUTE4_WORK/candidate"
python3 tools/verify_candidate.py --package "$Z8_PACKAGE" \
  --stock "$ROUTE4_WORK/extracted/stock-MAIN.bin" \
  --candidate "$ROUTE4_WORK/candidate/route4-half-native-nef.model-payload"
```

已有经核对的 MAIN 时可跳过提取，将后续 `--stock` 指向它。两种路径都必须满足完整 MAIN 身份。候选应为7个修改指令窗口、21个不同字节，SHA-256 `2f8207645aeaf8b704613f71d88abc8b27dc5141130219a0176e3ef2ecb1954e`。它是研究载荷，不是相机更新包。

要检查验证器确实拒绝错误候选，可另运行：

```bash
python3 tools/test_static_tools.py --package "$Z8_PACKAGE" \
  --stock "$ROUTE4_WORK/extracted/stock-MAIN.bin" --output-dir "$ROUTE4_WORK/static-tests"
```

## 3. 取得固定源码并重新编译

```bash
python3 runtime/prepare_model.py --workspace "$ROUTE4_WORK/model" --cache "$ROUTE4_WORK/source-cache"
python3 runtime/build_model.py --workspace "$ROUTE4_WORK/model" --jobs 2
```

准备器从锁定地址下载并核对源码包，应用两份公开补丁。构建器要求新的 build 目录，不复用旧目标文件。它保留源码准备回执、构建日志、编译器版本和实际二进制摘要。编译器或构建路径变化可能使二进制摘要不同；不能用编译成功代替后面的运行结果。

## 4. 生成输入并运行三组

```bash
"$ROUTE4_WORK/venv/bin/python" tools/generate_raw_fixture.py --output "$ROUTE4_WORK/frame-00.raw"
"$ROUTE4_WORK/venv/bin/python" runtime/run_experiments.py \
  --package "$Z8_PACKAGE" \
  --stock "$ROUTE4_WORK/extracted/stock-MAIN.bin" \
  --candidate "$ROUTE4_WORK/candidate/route4-half-native-nef.model-payload" \
  --raw "$ROUTE4_WORK/frame-00.raw" \
  --qemu "$ROUTE4_WORK/model/build/qemu-system-aarch64" \
  --build-receipt "$ROUTE4_WORK/model/build/z8-build-receipt.json" \
  --model-root "$ROUTE4_WORK/model/z8-source" \
  --output "$ROUTE4_WORK/first-frame-001" --execute
```

去掉最后的 `--execute` 可先核查输入。运行器拒绝 `-O`，因为固定的上游依赖仍使用断言。每组独立启动、使用新的稀疏卡，不共享前一组运行状态。输入、前态、实际交付、等待、停止与内容验收细节见 [RUN.md](../runtime/RUN.md)。

## 5. 判断和报告

三组预期 NEF 数依次为 **1、0、1**。有文件的两组还必须完整解码，并分别与本次源和本次 producer 比较全部45,705,600个样本，得到 `PASS_MATCH`。只有这些条件和完整运行条件同时满足，`runtime-summary.json` 才给出 `all_runtime_controls_passed=true` 与 `native_nef_content_passed=true`，命令退出码才为0。

请保留每次尝试，包括失败。超时、启动前异常、输入未交付、等待未完成或卡读取失败，都不能作为“原版半按不出片”的有效负对照。不要改成功标志或删除失败重试记录来构造通过。

向维护者报告时，先提供操作系统/编译器/依赖版本、源码锁与实际二进制摘要、三组退出状态、输入约束及文件数量、内容审核状态和完整像素摘要。完整日志和卡属于私有产物；分享前逐项检查路径和内容，不能直接把整份工作目录提交进仓库。截图可辅助定位，但不能代替这些数值与可执行流程。

同一合成源的全像素摘要可用于检查内容一致性。整个 NEF 还包括时间与其他元数据，文件摘要差异应定位原因，不能仅凭文件摘要相同或不同就宣布整项实验成功或失败。
