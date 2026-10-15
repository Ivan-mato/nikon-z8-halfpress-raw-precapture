# 原生 NEF 内容审核与合成输入

这些工具只在宿主上生成测试输入或读取文件，不启动固件、不访问相机。它们补齐可重放的内容检查；同一次运行的输入、卡提取与 producer 来源仍须由运行记录独立绑定。

## 环境

内容审核和输入生成使用 Python **3.11 或更新版本**。这是额外工具的依赖要求；仅做静态补丁重建仍可使用 Python 3.10。

```sh
python -m pip install -r tools/requirements-audit.txt
```

固定依赖是 NumPy 2.4.6、rawpy 0.26.1、Pillow 12.3.0。本轮 Windows 实际使用 rawpy 自带的 LibRaw 0.22.0；脚本在每份回执中记录实际版本。不同平台的 wheel 可能携带不同 LibRaw，必须保留该信息。没有使用 ExifTool 或 Adobe；不能将本工具的通过改称另一解码器或全部元数据规则通过。

## 生成完全相同的合成输入

先建立仓库外的私有工作目录；输出路径必须尚不存在。

```sh
python tools/generate_raw_fixture.py --output ../route4-private/frame-00.raw
```

该生成器沿用 RdWing `tools/make_cmos.py --capture` 的八色色条、垂直亮度和 sRGB 逆传递函数，保留其 `GPL-2.0-or-later` 与作者署名。不是根据 NEF 反推输入。结果必须为：

```text
bytes:  90882080
sha256: 85878e2e56ee0f6bc10cc0d5dd474375e2ee67bc310d24acf955b0fa5efba293
```

文件前32字节是小端 `<8s6I>`：`NZ9RAW1\0, 8256, 5504, 14, 0, 0, 16383`，随后为 8256×5504 个小端 uint16 样本。CFA=0 对应 RGGB，black=0，white=16383。生成器完整计算 SHA-256；字节数或摘要不符即失败。已存在文件不会覆盖。

本轮重新生成的完整文件与恢复访问后的历史 `frame-00.raw` 摘要完全一致，因此它可重建该历史输入。它只是合成数据，不能作为传感器、画质或历史预拍帧的证据。

## 完整比较命令

模型停止后，先从该次虚拟卡提取实际文件，并取得该次实际的 packed14 producer 转储。不要用从 NEF 重新打包的数据替代 producer。

```sh
python tools/audit_nef.py \
  --nef ../route4-private/run/DSC_0001.NEF \
  --source ../route4-private/frame-00.raw \
  --producer ../route4-private/run/engine151-raw-side-target.bin \
  --require-match \
  --report ../route4-private/run/nef-content-audit.json
```

Windows 可使用同样参数和带引号的本地路径，将续行改为单行。脚本不包含作者机器的绝对路径。报告路径必须新建；输入和旧报告不会被覆盖。普通 Python 与 `python -O` 使用同样的验收条件，不依赖 assert。

检查包括：

- 有界 TIFF、Exif 与 Nikon MakerNote 解析，型号 `NIKON Z 8`，唯一 8280×5520、14bit、compression34713 的 Bayer RAW IFD。
- Nikon F0 与四个2048预测器；拒绝恰好满足 LibRaw packed-size 兜底长度的所谓压缩条带。
- 三份 JPEG 的边界、标记、实际解码和尺寸：160×120、8256×5504、1620×1080。
- LibRaw 完整 RAW 数组与 SHA-256/SHA-512；检查全部45,705,600个样本。
- 若提供 source，按模型的 CFA 对齐最近邻映射逐样本比较；若提供 producer，解包每行前14,490字节，再逐样本比较。producer 的每行 stride 为14,496字节，末6字节是传输填充，不属于图像样本。

对于目标位置 `(x,y)`，源位置为：

```text
sx = ((x // 2) * (8256 // 2) // (8280 // 2)) * 2 + (x & 1)
sy = ((y // 2) * (5504 // 2) // (5520 // 2)) * 2 + (y & 1)
```

每7个 packed14 字节形成一个小端56bit整数，依次取 bit0..13、14..27、28..41、42..55 四个样本。这是本模型的中间格式，不是宣称实际相机硬件必然采用同样打包方式。压缩 NEF strip 应与解码后的样本对应，不能要求它与未压缩 producer 字节相等。

## 状态与退出码

| JSON 状态 | 已证明的内容 |
|---|---|
| `PASS_MATCH` | 文件内容检查通过；完整解码样本与**两份实际提供的文件**均零差异 |
| `PARTIAL_SOURCE_MATCH` | 内容及 source 比较通过；没有 producer 比较 |
| `PARTIAL_PRODUCER_MATCH` | 内容及 producer 比较通过；没有 source 比较 |
| `PASS_DECODE_ONLY` | 内容及完整解码通过；两种样本来源均未比较 |
| `FAIL` | 结构、解码、输入格式或任一提供的样本比较失败 |

带 `--require-match` 时，仅 `PASS_MATCH` 返回0；缺任一来源返回2并记录 `required_match_missing=true`。不带该参数时，上述三个有界/部分结果可返回0，但状态名称不会伪装成 `PASS_MATCH`。任何实际失败都返回2。

**`PASS_MATCH` 只证明文件数值对应，不验证同次运行来源。** 即使提供的是另一次相同色条 producer，也可能零差异，因此报告始终将 `same_run_provenance_verified=false`。要声称“同次”，仍需将 QEMU 结果中的 source hash、producer 地址/长度/作业计数、转储事件与实际文件绑定。该 CLI 不凭文件名或未经证明的回执布尔值补足因果链。

## 本轮宿主测试

在不重新执行固件的条件下，两份首帧 NEF 与新生成的精确 source、从旧运行目录只读取得的实际 producer 均完整零差异。两份后续生命周期 NEF 与 source 也完整零差异；没有用无效或缺失的生命周期 producer 补成 `PASS_MATCH`。

正反例还覆盖缺任一来源、全部来源缺失、截断文件、错误 TIFF 头、伪造 packed-size 兜底、损坏预览、单个源样本篡改、单个 producer 样本篡改、错误 producer 长度、Python `-O` 和拒绝覆盖。损坏的 NEF 与私有生成物仅用于本地测试，不随仓库发布。
