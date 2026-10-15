# 从自备原厂包取得精确 MAIN

`tools/extract_main.py` 为静态重建补齐输入提取步骤。它只接受这一份 Z8 C3.11 原包，不下载固件、不恢复密钥、不重打包，不调用外部工具，也不会连接设备。Python 3.10以上，只有标准库依赖。

## 所需输入

| 文件 | 要求 |
|---|---|
| 使用者自备 `Z_8_0311.bin` | 99,051,117 B；SHA256 `d67413c2ede6b9ce8887175f20700bd9fbad2a973a4820968c45503d15d80d96` |
| 使用者自备 key JSON | `T1`、`T2`、`T3` 各为256字节十六进制字符串；不随本仓库分发 |

JSON结构如下；尖括号内容是格式说明，不能直接运行：

```json
{"T1":"<512 hexadecimal characters>","T2":"<512 hexadecimal characters>","T3":"<512 hexadecimal characters>"}
```

可使用外部 [WonderLantern/nikon-fw-key-tool 的固定提交文档](https://github.com/WonderLantern/nikon-fw-key-tool/blob/33426e892afd329a3b366b73776bcf53b9ac4ee8/README.md) 准备这些表。参考提交为 `33426e892afd329a3b366b73776bcf53b9ac4ee8`；该工具及密钥并未捆绑在本项目中。其生成命令是：

```sh
python /path/to/nikon-fw-key-tool/extract_key.py \
  --firmware-dir /path/to/your-owned-legacy-images \
  --out /path/to/private/key.json
```

**仅有这一份 Z8 文件，不保证能恢复全部三张表。** 外部工具要求所提供输入的常量填充覆盖全部256个T3块索引，可能报告缺块；请遵循其固定版本文档。这里既不自动取得其他型号固件，也不将“已拥有Z8原包”当成“已有完整表”。没有完整表时提取步骤仍未满足，应停止并明确缺少输入。

## 提取与重建

在仓库外建立私有父目录，再指定尚不存在的输出子目录：

```sh
python tools/extract_main.py \
  --package /path/to/Z_8_0311.bin \
  --key-json /path/to/private/key.json \
  --output-dir ../route4-private/extracted
```

Windows可在同一行传入带引号的Windows路径。普通Python与`python -O`具有相同的输入门控。

输出为 `stock-MAIN.bin` 和 `extraction-receipt.json`。MAIN 必须为81,807,709 B，SHA256：

```text
2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853
```

随后将该文件作为静态工具输入：

```sh
python tools/build_candidate.py --package /path/to/Z_8_0311.bin --stock ../route4-private/extracted/stock-MAIN.bin --output-dir ../route4-private/candidate
python tools/verify_candidate.py --package /path/to/Z_8_0311.bin --stock ../route4-private/extracted/stock-MAIN.bin --candidate ../route4-private/candidate/route4-half-native-nef.model-payload
```

## 实际验收规则

脚本先验证原包完整长度与摘要，再解码并要求解码后全文摘要为 `7dec1be784812c32ea3b735f18b46e260b15b0a960f5a3dc40c4197d0b07fc0a`。密钥表不是凭名字或未检验的`self_check`字段接受；只有它实际解出规定原文才接受。

随后检查5个模块的名字/顺序、目录连续性、范围、reserved字段、末尾padding，每个模块CRC以及包CRC，最后检查MAIN完整长度与摘要。所有检查完成后才建立输出目录。错误原包、错误表、已有输出目录均拒绝。若输出写盘本身失败，可能留下未完成目录；不要使用没有成功回执的输出，改用新的空闲目录复跑。

偏移规则是 `file_offset = body_offset + 32`。文件前32字节是外头，接着32个空格为body标签；XOR从文件offset64开始，但表索引是 `file_offset - 32`。模块目录offset相对body，length包括末尾2字节CRC。MAIN只取EG模块去CRC后的正文。把body offset直接当文件offset会提前32字节截取，已有历史物料因此出错。

两级CRC使用`poly=0x1021, init=0, refin=false, refout=false, xorout=0`，直接逐字节更新，存储值为大端。包CRC覆盖body去掉末尾16字节，包含各模块自己的CRC；只验包CRC不能替代逐模块校验。

本步骤不需要签名密钥K8，也没有重新计算头部的带密钥SHA1。完整原包SHA256固定了被接受的原始文件身份；这里没有借此声称改包会被更新器接受。原包、表、完整MAIN及生成候选均应保存在使用者自己的私有目录，不要随研究仓库发布。
