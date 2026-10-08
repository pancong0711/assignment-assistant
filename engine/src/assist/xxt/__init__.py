"""学习通（超星）只读对接层 —— D63 T1 起步。

分层（docs/16 §14.2）：
- engine 主包零浏览器依赖：playwright 为 optional extra，本包内全部 lazy import；
- 语义来源：.scratch 探针（xxt_session_check / xxt_login_capture / xxt_probe3）；
- 只读硬保证：本包不提供任何写操作命令（POST/PUT/DELETE 拦截在后续 extract 落地时加路由层）；
- 隐私：storage（cookies）/学生姓名一律不入 git（docs/04 口径）。
"""
