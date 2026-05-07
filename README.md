# 小豆芽多平台自动发布脚本

这是一个基于 `新榜小豆芽` 客户端的本地自动化仓库，当前包含两个平台脚本：

- `xiaodouya_poster.py`：抖音自动发布
- `xhs_xiaodouya_poster.py`：小红书自动发布

仓库定位是“一个仓库，两个项目”，便于统一维护依赖、启动脚本和公共运行约定。

## 项目结构

- `xiaodouya_poster.py`：抖音自动发布主脚本
- `xiaodouya_launcher.py`：抖音启动入口
- `xiaodouya_config.example.json`：抖音配置示例
- `xhs_xiaodouya_poster.py`：小红书自动发布主脚本
- `xhs_xiaodouya_launcher.py`：小红书启动入口
- `xhs_xiaodouya_config.example.json`：小红书配置示例
- `requirements.txt`：Python 依赖
- `启动抖音自动发布.bat`：抖音一键启动
- `启动小红书自动发布.bat`：小红书一键启动

## 安装依赖

```powershell
py -3 -m pip install -r requirements.txt
```

## 配置文件

仓库默认不提交真实本地配置，请先复制示例文件再填写你自己的路径和任务信息：

```powershell
Copy-Item .\xiaodouya_config.example.json .\xiaodouya_config.json
Copy-Item .\xhs_xiaodouya_config.example.json .\xhs_xiaodouya_config.json
```

需要修改的通常包括：

- `app_exe`：小豆芽客户端安装路径
- `source_dir`：待发布素材目录
- `published_dir`：已发布素材归档目录
- 平台任务名、合集名、账号列表、文案和话题

## 运行方式

### 抖音

```powershell
py -3 .\xiaodouya_launcher.py
```

或双击：

```text
启动抖音自动发布.bat
```

### 小红书

```powershell
py -3 .\xhs_xiaodouya_launcher.py
```

或双击：

```text
启动小红书自动发布.bat
```

## 使用注意

- 运行前先打开并登录 `新榜小豆芽`
- 自动化执行期间尽量不要操作鼠标和键盘
- 如果出现验证码、掉线或异常弹窗，请先人工处理后再继续
- 客户端页面结构变化后，脚本中的按钮文案、控件定位或等待时间可能需要调整

## 仓库说明

为避免泄露本地环境与运行痕迹，以下内容默认不上传：

- 本地虚拟环境
- 打包产物与构建目录
- 日志、截图、调试输出
- 真实配置文件
- 历史备份目录
