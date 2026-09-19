# 决赛 v2 复现边界与运行入口

候选代码包，不是已提交终版。默认不调用商业模型、不连接ERP/MES。真实系统报告是原作者本机实跑证据，不会因为解压而自动在新机器创建相同实例。

## 离线运行

Python 3.11或以上；推荐与测试一致的3.12。macOS自带的`python3`可能仍为3.9，不能直接假设可用。以下明确使用已安装的3.12；若找不到，请先准备兼容解释器，不要修改系统Python。前端需要Node >=22.13.0。根目录执行：

```bash
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m delivery_guard.finals_api --port 8766
```

另开终端启动前端：

```bash
cd frontend/site
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

访问 http://localhost:3000/finals，选择离线规则演练。它用于复现状态/规则/求解，不是LLM效果。API与浏览器均只在本机使用；不要将此开发服务直接暴露到公网。

当前回归协议位于`configs/finals_v2_tasks_v4.json`；新增表达验证见`configs/finals_v2_release_holdout_v2.json`，后续一旦用于调试即不能再称独立封存。先运行脚本`--help`确认参数，使用新输出路径，不能覆盖已有失败或成功报告。默认规则与真实模型测试分别记账。

## 在线与真实系统不是零配置

`finals_live.py`只读取本项目授权配置。包不包含凭据、调用账本、SQLite运行库或个人环境文件。下载者须自行确认模型/端点许可和费用；原作者授权不适用于其他账号。不要把密钥写入代码或提交Git。

真实系统需分别建立ERPNext/OpenMES测试实例、受限接口凭据、公司/仓库及映射。OpenMES上游固定提交为`f0ccdd1c7a57804212ed337d340aebfeebacc372`。不附带镜像或原本机数据库，不宣称本包包含一键安装两套系统。

本机原作者已授权`YOUJIE-FINALS-*`测试物料与BOM原生提交：`scripts/provision_finals_erpnext.py`为独立初始化工具。它不是模型工具，不开放一般工单提交权限。不同环境必须先自行审查目标/凭据/映射并授权；勿照抄作者的绝对路径。

`scripts/provision_finals_openmes.php`和`finals_mes_operator_event.php`是本机应用ORM测试工具，不是对外ERP API，也不是生产控制。后者只对指定run和测试产品的原始零产量工单生成100件人工测试事件。不要对真实工单运行。

`scripts/validate_finals_real_chain.py --help`列出原生闭环验收参数。它会真实创建草稿/导入测试工单和模拟产量，不能把运行它视为只读检查。默认600、变体400、响应丢失恢复三轮；必须先有匹配BOM、MES产品/产线和显式本机操作授权。

## 证据与已知限制

当前版本证据索引见 `finals_v2_current_evidence_20260918.md`。下列旧报告保留为历史，不代替当前源码验收。

- `real_chain_20260917_03/report.json`：三轮同run真实模型和ERP/MES回读、旧审批失效、剩余重算。产量/质量/耗料是明确模拟，不是现场设备数据。
- `tasks_live_20260917_02/report.json`保留一次合法输入误拒；03修复，04为相同表达集回归，不重复声称独立封存。
- `local_checks_20260917_09/report.json`：本机Python测试、编译、类型、构建；不能替代新机器完整重装。
- `tasks_live_20260918_01/report.json`：当前解析修复后的144项真实模型回归，固定/动态均通过；已用表达，不是新的封存集。详见`finals_v2_regression_20260918.md`。
- `browser_20260918_01/repaired_browser_chain.json`：页面输入400件、28小时，两次补证后真实交付，再由明确的应用层模拟报产事件触发剩余300件重算；不是设备实产。
- 代码版本变化时历史任务只读；本地事件hash链用于损坏/崩溃检测，不是签名认证或分布式锁。
- 新案例库存为模拟快照；真实BOM验证物料比例，不代表已读取并落实ERP真实库存预留。
- 后续剩余计划待人工落实，不重复下发整单，也不自动修改旧工单。
- 完整UI实点、各分辨率/缩放、最终PPT/视频与干净环境验收仍以当前验收账为准。

旧Mendeley案例独立保留许可证及派生标识。新Wiki案例均为合成资料，不能标为Mendeley真实工厂邮件。项目与第三方许可见LICENSE和THIRD_PARTY_NOTICES.md。
