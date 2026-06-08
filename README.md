# 拼多多自动上架工具

当前已支持 ERP 账号密码登录：价格册查询会优先复用 `erp.storage_state`，如果登录态失效或被踢回登录页，会自动使用 `erp.username` / `erp.password` 登录，登录成功后保存新的 `storage_state`，再继续读取价格册价格。

## ERP 优质价规则

自动上架时使用“订单 > 价格册 > 优质价”里的价格作为基础价，再乘以商品 `meta.yaml` 里的 `price_multiplier` 填到平台售价。

尺寸图文件名要用于精确匹配优质价：

- 文件名里包含完整型号，例如 `8065-25古铜色.jpg`。
- 程序会先搜索基础型号 `8065`。
- 搜索结果里会精确匹配 `8065-25`，不会误拿 `8065-20` 或 `8065-30`。
- 如果同一型号有多个颜色，会继续按文件名里的颜色匹配，例如 `古铜色`。

## 配置 ERP

复制 `config.example.yaml` 为 `config.yaml`，填写 ERP 地址和页面选择器。账号密码建议用环境变量：

```powershell
$env:ERP_USERNAME="你的ERP账号"
$env:ERP_PASSWORD="你的ERP密码"
```

`config.yaml` 中保持：

```yaml
erp:
  username: "${ERP_USERNAME}"
  password: "${ERP_PASSWORD}"
```

需要用 F12 填好的选择器：

- `username_input`: ERP 登录页账号输入框
- `password_input`: ERP 登录页密码输入框
- `login_submit`: ERP 登录按钮
- `search_input`: 价格册搜索框
- `search_submit`: 搜索按钮，可留空，留空会按 Enter
- `price_cell`: 价格显示元素
- `login_error`: 登录失败提示，可留空

真实账号、密码、`states/*.json` 不要提交到 git。
