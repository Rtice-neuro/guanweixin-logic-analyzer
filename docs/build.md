# 构建与运行

## 工具
PDS Lite 2022.2-SP1；Logos PGL50H / FBG484 / -6。
Windows与Python 3运行Web工作台；串口工作器使用Windows PowerShell。
重新构建固件需RISC-V裸机交叉编译器；ISA rv32i_zmmul_zicsr，应用-Os、CoreMark-O2。

## PDS
建议解压到简短英文路径，例如F:/GWX-r20。
在PDS Tcl控制台切换到hardware目录，执行 source build_portable.tcl。
ROM和源码路径已整理为相对路径，ai.fic指向synthesize/guanweixin_ai_board_top_syn.adf。
此路径整理副本尚未重新运行完整构建；Release位流为原归档产物。
如果PDS的FIC路径解析目录不同，在Fabric Inserter重新选择当前综合产物并保存。

## 部署与网站
1. 板卡上电并连接板载UART与JTAG。
2. Fabric Debugger连接下载器，选择Release中的.sbit进行SRAM配置。
3. 运行web/start.cmd，访问127.0.0.1:8765。
4. 在网页选择实际CP210x串口（原环境COM8，以当前电脑为准）。
5. 断电后SRAM配置丢失，需重新下载；本版本未写Flash。

Release中app.elf、app.bin、app.map为归档部署固件。
hardware/rom_banks包含ROM初始化数据。
源码保留固件、模型运行时与CoreMark；仓库不包含编译器和PDS安装包。
