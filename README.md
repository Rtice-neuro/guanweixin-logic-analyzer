# 观微芯 · 八路逻辑检测仪

基于紫光同创盘古50 FPGA的自研RISC-V处理器与八路数字逻辑检测系统。

## 功能
- RV32I五级流水线处理器，带前递、冲刷、停顿、分支预测和返回地址栈。
- 两路组相联指令/数据Cache：4KiB / 2KiB。
- 八路数字采集、触发和64点缓存，支持卡高、卡低、丢脉冲及周期异常定位。
- 板端260K参数微型Transformer，支持CPU推理与分组点积硬件加速。
- 本地Web工作台，支持八路配置、波形、故障定位、串口终端与记录导出。
- PDS Fabric Debugger同时观察报告回放与CPU追踪。

当前硬件版本r20；固件实际ISA为rv32i_zmmul_zicsr。
演示链路：网页生成测试向量 → UART送板 → FPGA/自研CPU分析 → 回传 → 网页显示。
PDS的D0–D7_report_replay为最近64点报告回放，按sample_index与网页对应；CPU追踪为实时信号。

## 快速开始
1. Windows安装Python 3后，运行web/start.cmd。
2. 浏览器访问 http://127.0.0.1:8765/ 。
3. 在“板卡连接”选择实际CP210x串口；连接成功后配置八路输入并送板分析。
4. FPGA需先加载r20位流，位流及调试波形可从Release附件获取。

详见[构建与运行](docs/build.md)、[演示步骤](docs/demo.md)、[验证记录](docs/validation.md)。

## 目录
| 路径 | 内容 |
| --- | --- |
| hardware/ | RTL、IO约束、ROM、PDS Tcl与探针 |
| firmware/ | 固件、启动/中断处理、CoreMark源码与移植 |
| model/ | 板端量化模型 |
| web/ | 本地工作台源码与启动入口 |
| sim/ | 报告回放测试平台与归档结论 |
| evidence/ | r20实板验证JSON |
| licenses/ | 第三方许可 |

## 归档结果
- r20整机27MHz；LUT16097、FF12935、DRM132/134、APM8/84。
- 时序All Constraints Met；慢角Setup +11.336ns、Hold +0.047ns。
- r20正常、卡高、卡低、丢脉冲、周期异常及多路组合六场景64点回读全部一致。
- 历史r14 CoreMark约2.643/MHz，1100迭代、超过15秒、CRC通过。
- 历史r14模型合成独立测试549/550（99.82%）；同条件AI加速约1.16–1.22倍。

详细来源与版本见docs/validation.md。UART与报告回放结果不代替外部排针采集实测。
本次公开材料整理未重新编译PDS或执行新的实板测试。

## 版本与许可
建议Release标签v1.0-r20。Release附件包括演示视频、r20位流、调试配置与部署固件。
尚未为自研代码指定仓库级许可证；第三方代码保留原许可证，见[第三方说明](THIRD_PARTY_NOTICES.md)。
