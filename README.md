# dt-sandbox

数字分身 DT-ORC V4.0 的 Multica 沙盒仓库。只放合成内容，用来验证 agent 的执行权限边界（ARCHITECTURE 5.2c）和首跑流程。

- 不放任何真实业务数据、个人信息或凭据。
- `main` 受分支保护：只能经 PR 合并，不能直接推送。
- agent 只推 `agent/…` 分支并开 PR，合并由常浩决定。

## todo-lite

`todo-lite` 是一个只用 Python 3.11 标准库写的极简命令行待办清单（合成首跑项目）。

### 安装

需要 Python 3.11+，运行时只用标准库，无第三方依赖。

```sh
git clone https://github.com/Natsukashii1997/dt-sandbox.git
cd dt-sandbox
python -m todo_lite --version   # 输出 0.1.0
```

在仓库根目录直接用 `python -m todo_lite …` 即可，不需要安装。想在任意目录使用时，可以把仓库装进当前虚拟环境：
`pip install -e .`（需要 setuptools；本项目没有注册命令行脚本，装好后仍用 `python -m todo_lite` 调用）。

### 命令

| 命令 | 作用 |
| --- | --- |
| `add "文字"` | 新增一条待办（文字两端空白会被去掉，去掉后为空则报错） |
| `list` | 按新增顺序列出待办：序号、状态（`[ ]` 未完成 / `[x]` 已完成）、文字 |
| `done <序号>` | 把该序号的待办标为完成（已完成的再标一次不报错） |
| `remove <序号>` | 删除该序号的待办，后面的序号依次前移 |

序号就是 `list` 里显示的数字，从 1 开始。

### 示例

以下是在空目录里依次执行的真实输出：

```console
$ python -m todo_lite list
暂无待办
$ python -m todo_lite add "买牛奶"
已新增 #1：买牛奶
$ python -m todo_lite add "写周报"
已新增 #2：写周报
$ python -m todo_lite add "回邮件"
已新增 #3：回邮件
$ python -m todo_lite list
1. [ ] 买牛奶
2. [ ] 写周报
3. [ ] 回邮件
$ python -m todo_lite done 2
已完成 #2：写周报
$ python -m todo_lite list
1. [ ] 买牛奶
2. [x] 写周报
3. [ ] 回邮件
$ python -m todo_lite remove 1
已删除 #1：买牛奶
$ python -m todo_lite list
1. [x] 写周报
2. [ ] 回邮件
```

### `--db`：指定数据文件

数据默认存在当前目录的 `./todo.json`。用 `--db <路径>` 换成别的文件，写在子命令前后都可以：

```console
$ python -m todo_lite --db work.json add "整理会议纪要"
已新增 #1：整理会议纪要
$ python -m todo_lite list --db work.json
1. [ ] 整理会议纪要
```

文件不存在时视为空清单，第一次写入时创建。文件格式：

```json
{
  "todos": [
    {
      "text": "写周报",
      "done": true
    }
  ]
}
```

写入是原子的（同目录临时文件 + fsync + `os.replace`），中途出错不会留下半截文件；不支持多个进程同时修改同一文件。

### 退出码

| 退出码 | 含义 | 示例 |
| --- | --- | --- |
| 0 | 成功 | 上面所有示例 |
| 2 | 用法错误：待办文字为空、序号不存在或不是正整数、缺少参数 | 见下 |
| 3 | 数据文件已损坏（不是合法 JSON、空文件、结构不对）；此时不会改写该文件 | 见下 |

```console
$ python -m todo_lite add "  "
错误：待办文字不能为空
$ echo $?
2
$ python -m todo_lite done 9
错误：序号 9 不存在（当前共 2 条）
$ echo $?
2
$ python -m todo_lite remove abc
错误：序号必须是正整数：abc
$ echo $?
2
$ printf '{"todos": [' > broken.json
$ python -m todo_lite --db broken.json add "x"
错误：数据文件已损坏：broken.json（JSON 解析失败：Expecting value，第 1 行第 12 列），未做任何修改，请手动修复或移走该文件
$ echo $?
3
```

错误信息写到 stderr，正常输出写到 stdout。

### 怎么跑测试

测试用 pytest（只是开发依赖，运行 todo-lite 本身不需要）。在仓库根目录执行：

```sh
pip install pytest      # 首次需要
python -m pytest -q
```

全部通过时最后一行形如 `150 passed in 0.53s`（用例数和耗时会随版本变化）；有失败时 pytest 会列出失败的用例并以非 0 退出码结束。
