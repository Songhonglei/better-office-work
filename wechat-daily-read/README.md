# 微信公众号每日汇总

1. 运行 `npm ci`，在微信开发者工具导入本目录。
2. 构建 npm 后可预览。默认使用标明身份的演示数据，公众号管理和导入历史保存在本机。

## 使用自己的文章数据

用自己的小程序 AppID 和 CloudBase 环境，将环境 ID 填入 `config/cloud.js`，部署 `cloudfunctions/`。数据库中的 `accounts` 和 `articles` 应限制为服务端访问。文章由有权限的数据源导入，按 `owner`、`date`、`accountBiz` 关联公众号，`publishTime` 用于排序。按需为 `articles` 创建 `owner + date + publishTime` 查询索引。

支持账号管理、查看已导入文章和按分类汇总标题。公众号链接包含 `__biz` 时可导入账号 ID。短链接缺少账号 ID 时可手动添加。文章链接可以复制后用微信打开。当前版本的云端语音服务需要单独接入。
