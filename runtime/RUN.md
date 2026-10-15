# 固定的三组首帧实验

这里提供本地功能模型的实验入口。它直接加载 MAIN，不执行 Nikon 更新器或原厂 loader，也不连接相机。成功只支持这份模型下的首帧结论；持续拍摄、历史缓存与真机可用性均不由本实验验证。

`route4_stream.py` 从 RdWing 的 GPL-2.0-or-later 控制器派生，保留原归属。运行时使用固定上游工具与本地模型修改；模型准备和编译见 [MODEL.md](MODEL.md)。仅克隆上游当前主分支不等价。

## 输入与环境

- Linux 或 WSL Linux，Python 3.11 或更新版本；运行器拒绝 `-O` / `PYTHONOPTIMIZE`，因为上游依赖仍使用断言。
- 用户自备准确原厂 `Z_8_0311.bin`、正确提取的 MAIN，以及[静态工具](../tools/README.md)重建的候选。缺少原包、身份不符或候选验证失败即停止。
- 用公开 `build_model.py` 编译的 QEMU、`route4-model-build-v1` 构建回执，以及准备好的模型源码目录。入口核对实际二进制、公开源码锁、overlay、QEMU 版本、编译参数、准备回执与构建脚本身份；不接受仅自填一个二进制哈希的旧回执。重新编译后的二进制不必与历史 SHA 相同，结果会标明是否相同。这里是溯源一致性核查，运行结论仍要由实验给出。
- `exfatprogs` 提供 `mkfs.exfat` / `fsck.exfat`。它们只格式化新建的普通镜像文件，不操作物理设备。
- 输出目录放在仓库外的 Linux 文件系统，必须不存在。三组依次运行，各有独立 8 GiB 稀疏卡；不采用占满空间的稠密复制回退。宿主 Windows 的可用空间与 WSL 虚拟磁盘显示的可用空间应分别确认。运行会保留截图、日志、卡和 producer 快照，需要额外实际磁盘空间。

从仓库根目录安装 Python 依赖并生成合成源：

```bash
python3 -m venv /path/to/work/venv
/path/to/work/venv/bin/python -m pip install -r runtime/requirements-runtime.txt
/path/to/work/venv/bin/python tools/generate_raw_fixture.py \
  --output /path/to/work/frame-00.raw
```

合成源必须为 90,882,080 字节，SHA-256 为 `85878e2e56ee0f6bc10cc0d5dd474375e2ee67bc310d24acf955b0fa5efba293`。这是生成的 RGGB 色条，不能作为真实 CMOS 数据。MCU、CCOMP、ROM 与 GPIO 辅助输入由固定模型工具的源码构造；不需要私有内存、机身 ROM、旧卡或下载 NEF。

## 先核查，再运行

将以下示例路径替换为自己的路径。`--model-root` 指向模型工作区中的 `z8-source/`，其父目录需保留 `source-preparation.json`；入口核对模型源码锁，并对照 `driver-sources.json` 的 25 份运行依赖。

```bash
/path/to/work/venv/bin/python runtime/run_experiments.py \
  --package /path/to/inputs/Z_8_0311.bin \
  --stock /path/to/inputs/stock-payload.bin \
  --candidate /path/to/work/candidate/route4-half-native-nef.model-payload \
  --raw /path/to/work/frame-00.raw \
  --qemu /path/to/work/model/build/qemu-system-aarch64 \
  --build-receipt /path/to/work/model/build/z8-build-receipt.json \
  --model-root /path/to/work/model/z8-source \
  --output /path/to/work/first-frame-001
```

默认只验证输入并打印计划，不创建实验目录、不启动 QEMU。给同一命令加 `--execute` 才执行。每组进入观测循环后默认限制 600 秒宿主墙钟（不含此前启动和之后内容审核），观察到五步 MCU 输入实际完成交付后再观察 25 秒模型虚拟时间。完整交付、观察开始/结束时间和最终模型时钟会另行核对；墙钟期限耗尽而未完成观察会失败。可以显式记录调整 `--seconds` / `--settle`，但应对三组统一调整，不将超时当作负对照通过。

另有组级上限 `--seconds + 180` 秒，覆盖子进程的输入核查、启动及运行。超时后仅终止该组新建的进程组，保留超时记录且不读取其卡；若无法确认整个组消失，停止后续组。强制停机不能记作一次完整实验。

三组固定顺序如下；每组启动独立 Python/QEMU 进程，猴子补丁及状态不会跨组复用。

| 目录 | MAIN | 规定 `(HALF,FULL)` 手势 | 预期最终 NEF 数 |
|---|---|---|---:|
| `stock-full` | 原版 | `00 → 10 → 11 → 10 → 00` | 1 |
| `stock-half` | 原版 | `00 → 10 → 10 → 10 → 00` | 0 |
| `candidate-half` | 七指令候选 | `00 → 10 → 10 → 10 → 00` | 1 |

启动 MCU 的既有资料含 `HALF=1/FULL=0`。入口会保存启动前空卡目录，在规定手势前另外读取 contacts/pending、两个 busy masks 与 producer 的 jobs/acks/pending；本次首次空闲实验要求读得的忙掩码共八字节为零。若此前已经产生任务或仍有旧按键输入排队/传输，直接失败并保留证据，不会清状态或将早期文件归因给后续手势。这里的零值是本实验契约，不是所有模式的普遍不变量。

入口显式关闭并通过 QMP 核对 `engine151-loose-admission`、`engine1543-loose-admission`、`unmodeled-tolerant`，开机前和运行后均要求禁用且计数为零。子进程还清除 `Z8_WATCH`、`Z8_WATCH_OFF`。旧 watch hook 的 `ra` 不能解释为 guest PC。以上开关关闭不等于没有其他本地模型修改，完整差异仍以模型源码为准。

## 如何判断本次结果

`runtime-summary.json` 的成功需要同时满足：进程无运行错误并已退出；全部五步输入和 MCU/GPIO 约束吻合；手势前没有 producer 任务；最终 producer 状态符合预期；停机后的卡目录得到对应文件数。MCU 入队记录不能代替实际交付：审核另查 `continuous_mcu_peer.rx` 的五个 `complete` 回执、完整帧编码，以及原厂 RX 缓冲区的实际转储和地址/摘要。两组有文件时，还会自动调用独立 `tools/audit_nef.py --require-match`，完整解码实际 NEF，与这次使用的源和这次停机后导出的 producer 逐样本比较，并核对三个文件的身份与本次回执；producer 快照的文件名、源地址和大小还须与最终 target/bytes 相符。

只有三组全部完成且内容检查也通过，`all_runtime_controls_passed` 和 `native_nef_content_passed` 才应均为 `true`，进程退出码为 0。缺少输入、不能启动、超时、异常、卡目录失败、源/producer 缺失、内容不同或一组失败都会保留结果并返回非零，不被记为成功。`PASS_MATCH` 本身不独立证明同次运行归属，归属由运行入口的实际路径、停机状态、snapshot 大小/摘要及 source/result 对应另行核对。

每组保留 `result.json`、控制器与 QEMU 日志、初始/最终卡目录、输入记录、模型属性读回；成功正对照另有实际 NEF、完整内容审核及 producer 快照。未命中断点不等于未执行，零文件结论只来自完成规定输入后的停机卡目录。不要自动把整个输出目录上传：其中包含用户自备固件派生内容、模拟卡、RAW/NEF、内存窗口和本地路径。

四个原有 NEF 的宿主重审与新的三组运行是不同证据。该入口和源码能够准备完整流程，不意味着每一种主机环境已经重放通过；发布时应另附实际本轮结果和失败项。
