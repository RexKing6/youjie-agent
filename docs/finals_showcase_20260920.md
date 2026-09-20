# 决赛交互展示版

用途：评委浏览当前决赛界面，不是在线Agent服务。顶部“演示回放”标识始终保留；七个情节来自已完成的同一任务历史。模型、ERP/MES不接入此入口。

## 构建与启动

```bash
cd frontend/site
npm ci
npx vite build --config showcase/vite.config.ts
cd ../..
.venv/bin/streamlit run streamlit_finals.py --server.address 127.0.0.1 --server.port 8503
```

Streamlit部署使用已提交的showcase_static/index.html及该HTML引用的assets文件，因此云端无需Node或本机后台。不要上传旧版生成资源；构建目录不自动清空，避免删除未确认文件。

recording.json为脱敏记录导出，含原始状态哈希及journal头哈希，关联版本b72ed68的录屏任务。不附带运行数据库或会话能力。重新导出脚本只适用于持有该本机任务的作者，下载者无需运行它。

## 安全与验证

- 复用WikiWorkbench的preview模式；跳过bootstrap和进度请求，act入口阻断所有计算、批准、导出及系统写入。
- 浏览器CSP connect-src none作为第二层保护；只向父页面发送组件ready及高度通知。
- 不显示指向127.0.0.1的ERP/MES链接。
- 已验证本地Streamlit组件加载、三方案/甘特图、知识库目录与正文、审批失效和ERP/MES历史回执。
- 只读操作提示不显示通信失败，不冒充新模型结果。
- TypeScript、静态构建、脱敏凭据扫描及展示专项测试通过；全量438项测试通过，176.73秒。

## 发布

2026-09-20用户确认切换。保留云端main/app.py及原网址，通过app.py直接运行streamlit_finals.py，st.stop阻止旧界面继续执行；旧版源码保留。入口AppTest通过，无异常、无缺失资源、无旧版下拉控件。最终需检查云端标题、情节切换、静态资源以及匿名访问。未经验证不宣称免登录可用。
