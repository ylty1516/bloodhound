# 验证记录

仓库仅包含经过检查的最新测试摘要和界面预览。完整日志、抓取正文、安装/运行诊断、私人运行回执及本机状态保留在原电脑，不随源码上传。

- `discovery-sources-final-tests.headroom.txt`：258项回归的压缩摘要。
- `discovery-sources-final-tests.headroom.json`：上述压缩统计，原264行缩至7行。
- `discovery-sources-desktop.png`：全量线索页面预览，包含公开项目线索，不含钱包、模型凭据或个人收款信息。
- `github-clean-source-tests.headroom.txt` / `.json`：首次上传前从 Git 暂存树导出的干净副本测试摘要与压缩统计。258项中257通过，1项因可选 DeepSeek SDK 测试依赖未随源码分发而跳过；没有使用本机生成适配器或原运行数据库。

文档中的其他evidence路径是原开发环境的历史验证位置。克隆仓库不会恢复原电脑的账户、数据库、项目安全审阅、观察时长或真实运行授权；这些状态需要在目标环境重新核对。
