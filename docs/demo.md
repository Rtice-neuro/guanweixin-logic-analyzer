# 演示步骤

1. 网页连接串口并确认就绪。
2. 八路恢复正常，生成64点并送板分析，检查回读一致与无异常。
3. 切PDS Debugger点击Run，查看D0–D7_report_replay及sample_index。
4. 网页将D5设卡高，重新生成并送板；再次Run，D5持续高、fault_mask=0x20。
5. 同样演示卡低、丢脉冲、周期异常；多路设置D0卡高、D1卡低、D2丢脉冲、D3周期异常。
6. 展示CoreMark实时终端、计时与CRC；运行中抓取trace_pc、trace_insn、trace_valid和流水线事件。
7. KEY2复位后查看IRQ SELFTEST PASS及33组启动自检。
8. AI固定同通道同样例，分别运行CPU与硬件点积路径，对照模型CRC、输出和耗时。
9. 导出JSON/CSV/VCD及原始日志。

每次新输入送板后重新Run，无需为不同异常更换位流。
PDS显示最新板端报告；网页回看历史不会自动让FPGA重新回放历史报告。
三维示波器为辅助界面，数字波形、原始回包及PDS样点用于结果核对。
